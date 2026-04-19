# Layer 1 收集层演进史

> 当前最新设计：[docs/architecture.md §3.1](../architecture.md)
> 本文归档 Layer 1 历史演进、中间形态、技术决策备忘。

---

## 1. Twitter 采集方案演进（twikit → xreach）

```
twikit（旧）                    xreach/agent-reach（新）
─────────────────────           ─────────────────────
❌ 需要 Twitter 用户名+密码      ✅ 零配置
❌ 需要 Python 3.10+             ✅ 无 Python 版本限制（CLI）
❌ Cookie 会过期需重新登录         ✅ 不需要维护
  likes/retweets/replies         ✅ 额外有 views/bookmarks/quotes
  pip install twikit             ✅ xreach v0.3.3 已安装
```

- 搜索模式: `xreach search "query" -n 20 --json`
- 时间线:  `xreach tweets @username -n 10 --json`
- **已知限制**：搜索模式下 user 对象只有 id/restId（无 screenName），代码中用 restId 作为 fallback 用户名

**2026-04-15 修复**：xreach-cli@0.3.3 通过 nvm node 全局安装；launchd PATH 含 nvm 路径，确保 xreach 可用；Twitter 采集从 0 篇恢复到 81 篇。

---

## 2. 失效 RSS 源迁移到 Exa（2026-04-13）

### 问题
a16z / Unreal Engine / Rachel by the Bay / Dwarkesh Patel 的 RSS 长期返回 403/404。

### 方案
1. 在 `config.yaml` 中注释掉这 4 个 RSS 源
2. 新增 Exa `sites` 定向搜索条目作为替代
3. 保留 ExaFetcher 的 `fallback_sources` 机制，为其他临时失败的 RSS 源兜底

### 2026-04-15 加固：RSS 失败历史持久化
- 新增 `rss_fail_history.json`，记录每个源连续失败天数
- 连续 ≥3 天失败的源自动降级为 Exa 永久替代，不再发起 RSS 请求
- 防止一次临时故障导致永久降级，也防止顽固失败的源每天白占并发配额

---

## 3. GitHub Trending 日期增强（2026-04-13）

### 问题
第三方 Trending RSS 的 entry 没有日期字段，导致"今日文章=0"。

### 方案（两步增强）

**Step 1: 榜单捕捉日期**
- 用 feed 级别的 `published_parsed` 作为 `published_at`
- 在 `extra.date_type` 中标记为 `"trending_capture"`（区分于项目本身的发布日期）

**Step 2: GitHub API 补充**
对 `_type == "trending"` 的条目，并发调用 `GET /repos/{owner}/{repo}` 补充三个关键字段：

| 字段 | 用途 |
|---|---|
| `extra.repo_created_at` | 仓库创建时间（判断新项目 vs 老项目） |
| `extra.stars` | 当前 star 总数（结合创建时间判断爆发程度） |
| `extra.repo_language` | 主语言 |

- **API 限速**：无需 Token，60 次/小时；daily trending ≤25 个项目，远低于限速
- **性能**：并发请求，14 个项目 ~1-2 秒

### extra 字段示例

```json
{
  "type": "trending",
  "period": "daily",
  "date_type": "trending_capture",
  "raw_description": "Built by @user1 @user2 ...",
  "repo_created_at": "2026-01-27T03:53:13Z",
  "stars": 19716,
  "repo_language": "Python"
}
```

### 下游判断规则（供 Layer 2/3 使用）

| 场景 | 判断方式 |
|---|---|
| 新项目爆发 | `repo_created_at` 在 30 天内 + 高 stars |
| 中期快速增长 | 1~6 个月 + 高 stars |
| 老项目翻红 | 6 个月以上 + 出现在 daily trending |

### 设计决策备忘

| 决策 | 结论 | 原因 |
|---|---|---|
| 用 `created_at` 还是首个 Release 时间？ | `created_at` | Release 覆盖率低（很多项目无 release）、API 分页限制（100 条截断）、多 1 次 API 调用 |
| 是否补充 `pushed_at`？ | 不补充 | trending 本身已代表"当前热门"，不需要额外判断活跃度 |
| GitHub Trending 无日期是否需要修复？ | 用 feed 时间兜底 | 第三方 RSS 服务限制，无法修改源数据；feed 级时间足够准确 |

---

## 4. RSSFetcher 无日期文章跳过（2026-04-13）

### 问题
Paul Graham 等 RSS 源不含 `pubDate`，导致历史全部文章灌入 raw.json。

### 方案
`_fetch_single_rss()` 中，当 `published_at is None` 且 `max_age_days > 0` 时，直接跳过该条目。

**影响范围**：仅影响 RSSFetcher，不影响 GitHubFetcher（独立方法）。

---

## 5. GitHub 管道拆分（2026-04-16）

### 问题
单一 github 管道下，新品容易被 trending 高 stars 项目洗掉。

### 方案
`github` 管道拆分为两条独立管道：

| 管道 | 来源 | 门槛 |
|---|---|---|
| `github_trending` | Trending Daily + Weekly | stars≥100 |
| `github_new` | Search API + Blog | stars≥30 |

两条管道独立评分 + 独立配额，互不洗掉。

### 去重持久化
新增 `data/github_seen.json` 永久记录已入选 GitHub URL（含 title/first_seen/stars 元数据），替代 72h 滑动窗口，防止老项目周期性重新涌入。

---

## 6. launchd 替代 crontab（2026-04-15）

### 问题
crontab 在 macOS 睡眠后不会补跑，导致定时任务经常漏执行。

### 方案
迁移到 launchd，两个 plist 配置了完整 PATH（含 nvm node 路径，确保 xreach 可用）：

- `com.niu.wechat-auto-fetch.plist`（微信采集）
- `com.niu.ai-daily-collector.plist`（Layer 1 采集）

### 触发时间演进

| 版本 | 微信采集 | ai-daily 采集 |
|---|---|---|
| 2026-04-15 | 9:00 / 21:00 | 9:05 / 21:05 |
| 2026-04-16 调整 | 12:00 / 22:00 | 12:05 / 22:05 |

### 2026-04-17 禁用 ai-daily-collector
- `unload com.niu.ai-daily-collector.plist`
- Layer 1 改为纯手动触发（避免 LLM token 消耗）
- `com.niu.wechat-auto-fetch` 保留（微信采集不消耗 LLM token）
- plist 文件保留，恢复命令：`launchctl load ~/Library/LaunchAgents/com.niu.ai-daily-collector.plist`

### collector load_dotenv（2026-04-15）
`collector.py` 顶部加 `load_dotenv()`，确保 `.env` 中的 `EXA_API_KEY` 等在 launchd 环境中也能正确加载。

---

## 7. Exa 搜索扩展（2026-04-13）

### 新增 4 个 RSS 失效源的定向搜索兜底
- a16z
- Rachel by the Bay
- Dwarkesh Patel
- Unreal Engine

### 保留 fallback_sources 机制
仍然可以自动为其他临时失败的 RSS 源兜底，双保险。

---

## 📎 相关文档

- [当前 Layer 1 设计](../architecture.md)
- 每日变更日志：`~/.codebuddy/memory/{YYYY-MM-DD}.md`
- [已废弃方案](./deprecated.md)
