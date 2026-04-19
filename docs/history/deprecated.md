# 已废弃 / 已替代的方案

> 本文集中记录所有"曾经用过但后来被替代"的方案，附带废弃原因和当前替代方案。
> 当前最新设计：[docs/architecture.md](../architecture.md)

---

## 1. Twitter 采集：`twikit` 库

| 维度 | 旧方案 `twikit` | 新方案 `xreach` CLI |
|---|---|---|
| 配置 | ❌ 需要 Twitter 用户名+密码 | ✅ 零配置 |
| Python 版本 | ❌ 需要 Python 3.10+ | ✅ 无版本限制（CLI） |
| Cookie 维护 | ❌ 会过期需重新登录 | ✅ 不需要维护 |
| 数据维度 | likes/retweets/replies | ✅ 额外有 views/bookmarks/quotes |
| 安装 | `pip install twikit` | ✅ `xreach` 已通过 nvm node 全局安装 |

**废弃时间**：2026-04-13
**替代方案**：`xreach` CLI（agent-reach skill），通过 `asyncio.create_subprocess_exec` 异步调用

---

## 2. LLM 轻筛：OpenAI API 自动调用

### 旧方案
```python
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
resp = client.chat.completions.create(...)
```

### 废弃原因
- 需要维护 API Key
- 成本不可控
- CodeBuddy 本身自带主模型，重复建设

### 新方案（2026-04-14 统一）
所有 LLM 工作（editor 摘要、filter 去噪/捞漏）均由 **CodeBuddy 在对话中完成**，不依赖任何外部 API：

```
用户发起对话: "帮我跑一次轻筛"
       │
       ▼
CodeBuddy 读取 raw.json + config.yaml
       │
       ├─ 重跑 Step 1-3a 获取元数据
       ├─ Step 3b 去噪：对话中逐篇判断
       ├─ Step 3c 捞漏：对话中逐篇判断
       │
       └─ 将判断结果写回 filtered.json（通过 Python 脚本执行）
```

**已移除的代码**：所有 OpenAI SDK 调用、`OPENAI_API_KEY` 读取、`llm_denoise()` / `llm_rescue()` 的 API 实现。

**脚本支持**：`scripts/run_llm_light_filter.py` 封装了完整的重跑流程。

---

## 3. 配额体系：`quota_per_tag`（单一配额）

### 旧方案
```yaml
quota_per_tag:
  ai_core: 5
  ai_agent: 5
  ai_video: 5
```

### 废弃原因
main（主日报）/ github / twitter 三个管道共享同一套配额，管道间性质差异大（文章 vs 项目 vs 推文）却平等竞争，导致 GitHub 项目挤占主日报空间等问题。

### 新方案（2026-04-14）
`pipeline_quotas`，三管道独立配额。详见 [layer2-evolution.md §5](./layer2-evolution.md#5-配额体系演进)。

**兼容性**：旧的 `quota_per_tag` 保留作为 fallback，未在 `pipeline_quotas` 中配置的管道退化为此值。

---

## 4. 评分维度：互动数据假维度

### 旧方案（2026-04-13 早期）
```
总分 = 时效性(0-3) + 覆盖广度(0-3) + 互动数据(0-2) + 多标签(0-1.5)
```

### 废弃原因
"互动数据"维度只对 GitHub（stars）和 Twitter（likes/retweets）有真实数据。主日报管道（RSS/微信/Exa）**没有互动数据**，这个维度恒为 0，相当于满分从 9 分降为 7 分的假维度。

### 新方案（2026-04-13 → 2026-04-14 再进一步）
- 2026-04-13: 主日报移除互动维度，重分配为 `时效 3 + 覆盖 3 + 多标签 1.5 + 内容类型调整`
- 2026-04-14: 再把"多标签加成"替换为"LLM quality 0-3"：`时效 3 + 覆盖 3 + quality 1.5 + 内容类型调整`
- GitHub/Twitter 管道保留互动数据维度（有真实数据）

---

## 5. 观点处理：降权策略

### 第一版（2026-04-13）：直接竞争
观点类和技术/产品文平等参与标签配额竞争。

### 第二版（2026-04-13）：opinion 文章 -1.0 降权 + VIP 不降权
VIP 作者的观点文章不降权，其他观点文章降权 -1.0，在同一标签配额里排后面。

### 废弃原因（2026-04-14）
有价值的行业洞察也被淘汰了 —— 比如 Simon Willison 的技术评论、Matthew Ball 的行业报告。降权策略把"优质观点"和"垃圾讨论"一视同仁。

### 新方案（2026-04-14 起 ✅）：分流到独立板块
opinion 文章**不降权**，从 main/twitter 管道分流到独立的"行业观点"池：
- 排序规则：VIP 优先 > 综合评分
- 取 top-3 → 独立"行业观点"板块
- 不双重曝光到原标签板块

---

## 6. GitHub 通行证（always_pass_channels 包含 github）

### 旧方案（2026-04-13）
```yaml
always_pass_channels:
  - github   # 上榜本身已是社区筛选
  - manual
```

### 废弃原因（2026-04-14）
- 初期仅采集 Trending，上榜本身已是社区筛选，通行证合理
- 2026-04-14 起 GitHub Search API 按 7 个兴趣领域定向搜索，采集范围大幅扩展
- 搜索结果中可能包含仅名称沾边但实际不相关的项目，需要关键词/LLM 验证相关性

### 新方案（2026-04-14 起 ✅）
```yaml
always_pass_channels:
  - manual   # 仅手工输入直通
```

GitHub 文章必须通过关键词/LLM 相关性验证才能入选。

---

## 7. LLM 分类 ID：顺序编号 `c0, c1, c2...`

### 旧方案
classify/rescue 候选的 ID 从 0 开始顺序编号。

### 废弃原因（2026-04-14）
`run_filter` 每次执行时去重后文章顺序可能变化，旧的顺序编号会导致 `llm_filter_results.json` 和 `llm_filter_input.json` 的 ID 错位。

### 新方案：基于标题的稳定哈希
```python
def _stable_id(prefix: str, art: dict) -> str:
    content = art.get('title', '')
    return f"{prefix}{hashlib.sha256(content.encode()).hexdigest()[:8]}"
# 输出示例：c81c67417、cfc90a83d
```

哈希 ID 基于标题内容，无论跑多少次同一篇文章的 ID 永远不变。

---

## 8. LLM 分类：secondary_tags 多标签

### 旧方案
```json
{"id": "c0", "primary_tag": "ai_agent", "secondary_tags": ["ai_core", "ai_gaming"]}
```
每篇文章可标记一个主标签 + 多个次标签。

### 废弃原因（2026-04-14）
- 分类歧义，下游评分和板块分配逻辑复杂
- 多标签加成评分维度使区分度不足（只有 0.5 分区间）

### 新方案：单标签 + quality 0-3
```json
{"id": "c81c67417", "primary_tag": "ai_agent", "quality": 3, "reason": "..."}
```
- 每篇文章只有一个 `primary_tag`
- 新增 quality 0-3 维度，区分度从 0.5 分扩大到 2+ 分

---

## 9. Layer 2 权威来源：`llm_filter_results_template.json` 的 `prompt_template` 字段

### 旧方案（AGENTS.md / user-guide.md 文档中的说法）
```
Layer 2 轻筛约束见 data/{today}/llm_filter_results_template.json 的 prompt_template 字段
```

### 废弃原因（2026-04-18）
**该字段根本不存在**。真正的约束源是 `layers/filter.py` 里的 `CLASSIFY_PROMPT` / `RESCUE_PROMPT` 两个常量。这是一个长期的文档错误指向。

### 新方案（2026-04-18 起 ✅）
AGENTS.md §B.1 和 user-guide.md §2.4 / §4.2 统一指向：
- `layers/filter.py` 的 `CLASSIFY_PROMPT` 常量（去噪 prompt）
- `layers/filter.py` 的 `RESCUE_PROMPT` 常量（捞漏 prompt）

AGENTS.md 补充说明："A 节禁止修改 py 文件，但读取 py 里的 PROMPT 常量是正当行为，且是执行 Layer 2/3 的前置条件"。

---

## 10. 定时调度：crontab

### 旧方案
macOS crontab 定时任务。

### 废弃原因（2026-04-15）
crontab 在 macOS 睡眠后**不会补跑**，导致定时任务经常漏执行。

### 新方案：launchd
迁移到 launchd，两个 plist：
- `com.niu.wechat-auto-fetch.plist`（微信采集，2026-04-17 后仍在用）
- `com.niu.ai-daily-collector.plist`（Layer 1 采集，2026-04-17 起禁用，改为手动触发）

两个 plist 配置了完整 PATH（含 nvm node 路径，确保 xreach 可用）。

---

## 11. GitHub 去重：72 小时滑动窗口

### 旧方案
GitHub 项目去重用 72 小时滑动窗口，只避免短期重复。

### 废弃原因（2026-04-16）
- 老项目（如 `tensorflow/tensorflow`）经常 4-5 天周期性涌入 Trending
- 72 小时窗口无法过滤这种周期性重复

### 新方案：持久化去重
新增 `data/github_seen.json`，永久记录已入选的 GitHub URL（含 title/first_seen/stars 元数据）。

---

## 12. 报告归档路径：`data/{date}/reports/`

### 旧方案（Layer 4 初版）
```
data/
├── 2026-04-16/
│   └── reports/
│       ├── Archon.md
│       └── SuperClaude.md
```

### 废弃原因（2026-04-16）
按日期归档导致"同一产品在不同日期的分析报告分散在各处"，难以做纵向追踪。

### 新方案（2026-04-16 起 ✅）
```
data/
└── reports/
    ├── Archon/
    │   ├── 2026-04-16.md
    │   └── 2026-04-17.md
    └── SuperClaude/
        └── 2026-04-16.md
```

同一产品多次分析集中存储在 `data/reports/{product_name}/{date}.md`，方便纵向追踪。

---

## 13. LLM 输入 JSON：内嵌 Prompt 字段

### 旧方案（2026-04-17 之前）
```json
{
  "candidates": [...],
  "CLASSIFY_PROMPT": "你是一个 AI 资讯相关性判断器...",  // ~3,200 token
  "RESCUE_PROMPT": "以下是一批文章标题..."              // ~650 token
}
```

### 废弃原因（2026-04-17）
- 这两个字段仅供人工阅读
- CodeBuddy 实际执行时直接从 `layers/filter.py` 读取 Prompt 常量
- JSON 副本无消费者，纯占用 token

### 新方案：移除内嵌 Prompt
- `llm_filter_input.json` 不再内嵌 CLASSIFY/RESCUE Prompt
- CodeBuddy 直接从 `layers/filter.py` 的 `CLASSIFY_PROMPT` / `RESCUE_PROMPT` 常量读取
- 节省 ~3,850 token/次

同时移除 classify 候选中的 `url` 字段（~3,100 token/次）：LLM 分类不访问 URL，`channel` 字段已提供来源信息，URL 对分类决策贡献为零。

---

## 14. 文档：`claude.md`

### 旧方案
`claude.md` 作为 Agent 行为契约文档，强绑定 Claude Code 工具。

### 废弃原因（2026-04-18）
项目希望兼容多主流 Agent 工具（CodeBuddy / Claude Code / Cursor / Windsurf / Aider），命名不够通用。

### 新方案：`AGENTS.md`
- 重命名为 `AGENTS.md`
- 泛化为所有主流 Agent 工具的行为契约
- 瘦身到只保留"硬约束 + 出错怎么办"
- 跑测 SOP 挪到 `docs/user-guide.md`

---

## 15. 文档：旧版 `config/sources.yaml`

### 旧方案
信息源配置独立放在 `config/sources.yaml`。

### 废弃原因
架构演进后，信息源配置已迁移至根目录 `config.yaml` 统一管理。

### 当前状态
`config/sources.yaml` 保留作为旧版参考，不再被代码读取。

---

## 📎 相关文档

- [当前最新设计](../architecture.md)
- [项目演进时间线](./README.md)
- 每日变更日志：`~/.codebuddy/memory/{YYYY-MM-DD}.md`
