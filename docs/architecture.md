# AI Daily News — 四层架构设计文档

> **项目更名**：`ai-daily` → `ai-daily-news`
> **架构更新**：2026-04-13，从原来的"配置层+采集层+AI层"三层伪架构，合并为真正的四层流水线。
> **Layer 1 完成**：2026-04-13，collector.py 已实现全部 6 种 Fetcher，集成测试通过。
> **评分架构更新**：2026-04-13，三渠道独立评分 + 独立板块输出（RSS/微信、GitHub、Twitter 彻底分离）
> **评分维度优化**：2026-04-13，主日报管道移除"互动数据"假维度，重分配为四维度（时效3+覆盖3+多标签1.5+内容类型）
> **LLM 轻筛引入**：2026-04-13，方案 C — 关键词主力 + LLM 去噪/捞漏，Prompt 聚焦具体关注领域
> **Layer 3 完成**：2026-04-14，editor.py 已实现完整工作流：LLM 结果加载 → 三管道渲染 → Markdown 输出
> **Summary Prompt 优化**：2026-04-14，强制结构公式 [主体]+[动作]+[结果]、≤40字、禁止重复/渲染、正反示例
> **GitHub 通行证移除**：2026-04-14，GitHub Search API 扩展后需关键词/LLM 验证相关性，不再自动通过
> **三管道独立配额**：2026-04-14，pipeline_quotas 替代旧的 quota_per_tag，main/github/twitter 各自独立配额
> **质量控制增强**：2026-04-14，新增 Twitter 综合热度门槛（min_heat）和 GitHub 最低 stars 门槛（min_stars）
> **冷门保护机制**：2026-04-14，优质源/核心标签的低热度文章受保护，降低通过阈值
> **行业观点板块**：2026-04-14，opinion 文章从 main/twitter 分流到独立板块，不再降权而是独立排序（VIP>评分），固定 3 篇
> **LLM ID 稳定化**：2026-04-14，classify/rescue 的文章 ID 从顺序编号改为基于标题的 sha256 哈希，消除重跑时 ID 漂移
> **单标签分类**：2026-04-14，LLM classify 去掉 secondary_tags，每篇文章只保留一个 primary_tag
> **质量分维度**：2026-04-14，新增 quality 0-3 评分维度替代多标签加成，拉大文章区分度（重大3/常规2/边缘1/噪声0）
> **板块定义重构**：2026-04-14，ai_social 限定为 AI 社交产品、ai_agent 扩展（游戏化社交/创作人格）、opinion 扩展为观点+宏观洞察、ai_gaming 新增 AI Native 玩法
> **ai_agent 配额扩容**：2026-04-14，主日报 ai_agent 配额从 5 提升到 10
> **事件级去重**：2026-04-14，配额选择阶段新增事件级去重（标题相似度>0.5 OR 共享核心实体），同管道+跨管道均生效
> **Editor URL 匹配**：2026-04-14，editor.py 的 LLM 结果匹配从顺序索引改为 URL 精确匹配→标题匹配→索引 fallback
> **Layer3 全文摘要**：2026-04-14，日报摘要基于源文章全文（web_fetch 抓取）生成，不再仅靠标题推测
> **quality 规则细化**：2026-04-14，榜单征集/申报/投票一律 quality=0；纯拼接型聚合新闻 quality=0，垂直周报除外
> **ai_core 配额扩容**：2026-04-15，主日报 ai_core 配额从 3 提升到 5
> **事件去重通用词扩充**：2026-04-15，实体去重排除词列表补充 Anthropic/Claude/Gemini/DeepMind/NVIDIA 等 AI 公司名，防止仅因共享公司名误判同一事件
> **板块定义收敛（产品优先）**：2026-04-15，除 ai_business 和 opinion 外，所有垂直板块限定为"具体产品/项目/模型的事实性新闻"；解读/分析/教程/争议全部归 opinion（兜底板块）；ai_agent 新增排除 B端企业SaaS
> **CLASSIFY_PROMPT 全面升级**：2026-04-15，新增：① 同事件多报道去重提示（只保留最优一篇）② quality 打分可信度说明（标题摘要不一致时按摘要判断）③ rescue 候选说明（摘要中的产品名优先于标题）
> **rescue 扫描范围扩展**：2026-04-15，rescue 预过滤从只扫描标题改为同时扫描标题+摘要；触发词补充讯飞/Manus/Lovable/Gemini/Kimi/豆包/通义/文心/Harness/Hermes 等国内外 AI 产品名
> **Layer3 Prompt 全面升级**：2026-04-15，summary ≤100字（从≤40字放宽）、必须以厂商+产品名作为主语、关键词从2-3个升到3-4个；产品类列核心功能/价值、事件类列核心影响；insight 扩到≤80字，要求回答why/how、揭示因果与影响、可选务实启示
> **gen_llm_results_skeleton 操作清单**：2026-04-15，脚本输出末尾追加逐篇 web_fetch URL 清单，固化"必须用骨架中的真实URL抓全文"的操作纪律，防止URL手写错位
> **RSS 失败历史持久化**：2026-04-15，RSSFetcher 新增 rss_fail_history.json，记录连续失败天数；连续≥3天失败的源自动降级为 Exa 永久替代，不再发起 RSS 请求
> **launchd 替代 crontab**：2026-04-15，macOS 定时任务从 crontab 迁移到 launchd（支持睡眠后补跑），collector 和 wechat auto_fetch 均迁移；两个 plist 配置了完整 PATH（含 nvm node 路径，确保 xreach 可用）
> **collector load_dotenv**：2026-04-15，collector.py 顶部加 load_dotenv，确保 .env 中的 EXA_API_KEY 等在 launchd 环境中也能正确加载
> **Twitter 采集修复**：2026-04-15，xreach-cli@0.3.3 已通过 nvm node 全局安装，launchd PATH 含 nvm 路径，Twitter 采集恢复正常（从0篇→81篇）
> **LLM 去重覆盖回填**：2026-04-16，Step 3b LLM 标记同事件重复（dup_of 字段）时，被踢文章的渠道/源信息回填到保留文章的 coverage_count，使 Step 4 覆盖广度评分反映 LLM 识别的语义级重复
> **聚合新闻评级调整**：2026-04-16，纯拼接聚合类新闻（晚报/早报/速递）从 quality=0 提升到 quality=1（⚡TUNABLE），primary_tag 由 LLM 判断
> **Layer3 Prompt 全文阅读**：2026-04-16，四个 Prompt（SECTION/TWITTER/GITHUB/OPINION）新增⚠️全文阅读强制要求（web_fetch 原文后再生成）、所有英文 summary 必须翻译为中文、summary 结构改为"谁+做了什么+影响"、技术细节下沉到 keywords
> **GitHub 优先读 README**：2026-04-16，GITHUB_PROMPT 新增"优先阅读 README.md 即可，无需逐行读源码"指引，减少工作量
> **GitHub 持久化去重**：2026-04-16，新增 data/github_seen.json 永久记录已入选 GitHub URL（含 title/first_seen/stars 元数据），替代 72h 滑动窗口防止老项目周期性重新涌入
> **GitHub 管道拆分**：2026-04-16，单一 github 管道拆分为 github_trending（Trending Daily+Weekly，stars≥100）和 github_new（Search API+Blog，stars≥30），独立评分+配额，防止新品被 trending 高 stars 洗掉
> **launchd 触发时间调整**：2026-04-16，微信采集从 9:00/21:00 改为 12:00/22:00，ai-daily 从 9:05/21:05 改为 12:05/22:05
> **板块定义重构（第二轮）**：2026-04-16，ai_agent 剔除开发框架/安全相关→not_relevant；ai_gaming 新增桌面宠物/助手；ai_social 新增传统社交+AI/AI聊天；ai_core 剔除论文和训练框架→ai_product，新增世界模型论文；ai_product 剔除AI硬件→not_relevant；not_relevant 新增明确排除清单
> **Layer 4 实现**：2026-04-16，archiver.py 实现产品深度分析报告。两种触发方式：①从日报选择产品（--product）②手动输入链接（--url，支持 GitHub/Twitter/Reddit/文章/图片自动识别）。Prompt 来自 report_template.md，10 模块结构（一句话速览→产品概览→投融资→核心功能→技术方案→版本迭代→商业模式→用户策略→竞争格局→产品总结→行业趋势）
> **报告按产品归档**：2026-04-16，输出路径从 `data/{date}/reports/` 改为 `data/reports/{product_name}/{date}.md`，同一产品多次分析集中存储，方便纵向追踪
> **飞书迁移预埋**：2026-04-16，报告头部自动包含 YAML front matter（product/date/source_mode/source_url/source_type/tags），为未来批量同步飞书多维表格预留结构化元数据
> **Layer 3 summary 规范**：2026-04-17，四个 Prompt 统一更新：≤80字、必须出现产品名、不堆砌数字、参考副标题写法、summary 与 keywords 不允许信息重复
> **防伪 URL 双重防线**：2026-04-17，filter.py 自动生成 llm_results_template.json（URL 从 filtered.json 预填）；editor.py 新增 _validate_llm_urls() 校验，URL 不匹配则报错终止
> **板块定义第三轮**：2026-04-17，ai_agent 剔除 Agent 基础设施（沙箱/治理/编排）和 Agent 合规风险→not_relevant；rescue() 新增 dup_of 检查防止重复报道被捞回
> **板块定义第四轮**：2026-04-17，TTS/语音模型从 ai_core→ai_video，世界模型从 ai_core→ai_gaming（按应用场景归属）
> **Bug 修复×3**：2026-04-17，①_generate_llm_results_template 字段名不一致（读 `output_section` 改为 `_output_section`）②Twitter 文章识别改用 `channel=="twitter"` ③`_github_subpipe` 仅标记 GitHub 文章
> **模板增强**：2026-04-17，llm_results_template 新增 _excerpt/MUST_FETCH 标记 + _tag_source/_priority（keyword_fallback=low）；llm_filter_results_template 新增标题聚类（同事件排一起）
> **classify fallback**：2026-04-17，LLM 分类缺失时从关键词标签补 _primary_tag_llm，标记 _tag_source="keyword_fallback"
> **design 原则**：每一层都有独立运行时逻辑，层间通过 JSON 文件解耦，支持从任意层重跑。

---

## 一、整体架构

```
                        ┌────────────────────────────┐
                        │       pipeline.py           │
                        │  主调度器：串联 4 层          │
                        │  支持从任意层开始 / 单层重跑   │
                        └────────────┬───────────────┘
                                     │
         ┌───────────┬───────────────┼───────────────┬───────────┐
         ▼           ▼               ▼               ▼           ▼
   ┌──────────┐┌──────────┐  ┌──────────────┐ ┌──────────┐┌──────────┐
   │ Layer 1  ││ Layer 2  │  │   Layer 3    │ │ Layer 4  ││  手工    │
   │ 收集     ││ 筛选     │  │   编辑       │ │ 归档     ││  输入    │
   │collector ││ filter   │  │   editor     │ │ archiver ││manual_   │
   │          ││          │  │              │ │          ││input/    │
   └────┬─────┘└────┬─────┘  └──────┬───────┘ └────┬─────┘└────┬────┘
        │           │               │              │           │
        ▼           ▼               ▼              ▼           │
   raw.json   filtered.json   daily.md      archived.json  │
        │           ▲               ▲              │           │
        └───────────┘               │              │           │
                    └───────────────┘              │           │
                                    └──────────────┘           │
                                         ▲                     │
                                         └─────────────────────┘
                                         (manual_input 可插入任意层)
```

### 层间数据流

```
互联网 / manual_input
       │
       ▼
  ┌─────────────┐
  │  Layer 1    │     → data/{date}/raw.json
  │  收集       │        所有渠道的原始文章（未筛选）
  └──────┬──────┘
         ▼
  ┌─────────────┐     → data/{date}/filtered.json
  │  Layer 2    │     → data/{date}/llm_filter_input.json（CodeBuddy 轻筛候选）
  │  筛选       │        去重 + 相关性评分 + LLM 去噪/捞漏 + 重要性过滤
  └──────┬──────┘
         ▼
  ┌─────────────┐     → data/{date}/llm_results.json（CodeBuddy 预生成）
  │  Layer 3    │     → data/{date}/daily.md
  │  编辑       │        LLM 摘要加载 + 三管道渲染 + Markdown 日报
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Layer 4    │     → data/{date}/archived.json
  │  归档       │     → knowledge_base/
  └─────────────┘        知识沉淀 + 长期存储
```

---

## 二、项目目录结构

```
ai-daily-news/
├── config.yaml              # 全局配置（信息源、筛选规则、输出偏好）
├── pipeline.py              # 主调度器：串联 4 层，支持从任意层开始
├── diagnose_layer1.py       # Layer 1 诊断脚本
├── layers/
│   ├── __init__.py
│   ├── collector.py         # Layer 1: 收集
│   ├── filter.py            # Layer 2: 筛选
│   └── editor.py            # Layer 3: 编辑
├── scripts/
│   └── run_llm_light_filter.py  # CodeBuddy 轻筛重跑脚本
├── config/
│   └── sources.yaml         # 旧版信息源配置（已迁移至 config.yaml）
├── data/                    # 运行时数据（按日期组织）
│   └── 2026-04-13/
│       ├── raw.json             # Layer 1 输出 / Layer 2 输入
│       ├── llm_filter_input.json # Layer 2 导出的 CodeBuddy 轻筛候选
│       ├── filtered.json        # Layer 2 输出 / Layer 3 输入
│       ├── filtered_backup.json # Layer 2 筛选前备份
│       ├── llm_results.json     # CodeBuddy 预生成的 LLM 摘要/关键词/洞察
│       ├── daily.md             # Layer 3 输出：Markdown 日报
│       └── archived.json       # Layer 4 归档记录
├── knowledge_base/          # Layer 4 沉淀的知识（跨日期持久化）
├── manual_input/            # 人工添加的文章（任何时候丢进来）
├── docs/
│   ├── architecture.md      # 本文档
│   └── layer2-design.md     # 旧版 Layer 2 设计（已弃用，仅供参考）
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 三、各层详细设计

### 3.1 Layer 1: 收集（collector.py）✅ 已实现

> **职责**：从所有渠道拉取原始信息，统一格式，输出 `raw.json`
> **原则**：只管"拿到"，不做任何筛选判断
> **状态**：✅ 全部 6 种 Fetcher 已实现，集成测试通过（2026-04-13）
> **最近更新**：2026-04-13，新增无日期文章过滤、RSS→Exa 迁移、GitHub Trending 日期增强与 API 补充

#### 输入

- `config.yaml` 中的信息源配置（RSS / GitHub / Exa / Twitter / 微信）
- `manual_input/` 目录中的手工文章

#### 输出

- `data/{date}/raw.json` — 当日所有采集到的文章列表

#### 统一文章数据模型

```python
@dataclass
class RawArticle:
    """Layer 1 统一输出结构"""
    # ── 必填 ──
    source_name: str        # 信息源名称（如 "36氪"、"OpenAI Blog"）
    channel: str            # 渠道：rss / github / exa / twitter / wechat / manual
    title: str              # 文章标题
    url: str                # 原文链接
    fetched_at: str         # 采集时间（ISO 8601）

    # ── 可选 ──
    published_at: Optional[str] = None   # 原文发布时间
    author: Optional[str] = None
    summary: Optional[str] = None        # 原文摘要/description
    content: Optional[str] = None        # 全文（如果能拿到）
    category: Optional[str] = None       # 来源分类（来自 config.yaml）
    language: Optional[str] = None       # zh / en
    extra: Optional[dict] = None         # 渠道特有字段（默认空 dict）
```

#### 各渠道 Fetcher 实现详情

| Fetcher | 库/工具 | 技术方案 | 实现状态 |
|---------|---------|---------|---------|
| **RSSFetcher** | `feedparser` + `httpx` | httpx 异步获取 → feedparser 解析；ETag/Last-Modified 条件请求；编码异常处理；按 config 中的 `rss.news/ai_companies/game_industry/vc_blogs/hn_blogs` 五类遍历；**无 pubDate 的 entry 直接跳过**（避免历史全量灌入） | ✅ 已实现 |
| **GitHubFetcher** | `feedparser` + GitHub API | Trending RSS + **Search API** + Blog RSS；Trending 走 RSS 解析逻辑 + GitHub API 补充元数据；**Search API 按 7 个兴趣领域定向搜索近 90 天新项目**（`extra.type = "search"`，`extra.search_query_tag` 自动标记领域）；**采集层内 URL 级去重**（Trending/Search 重叠项目只保留一条）；Blog 走标准 RSS | ✅ 已实现 |
| **ExaFetcher** | `exa-py` SDK | `exa.search_and_contents()`，按 `published_after` 过滤近 24h；定向站点搜索 + 通用关键词搜索；每条查询限 5 条；**新增 4 个 RSS 失效源的定向搜索兜底**（a16z / Rachel by the Bay / Dwarkesh Patel / Unreal Engine） | ✅ 已实现 |
| **TwitterFetcher** | `xreach` CLI（agent-reach skill） | 搜索模式（`xreach search`）+ 用户时间线（`xreach tweets @user`）；`--json` 输出；`asyncio.create_subprocess_exec` 异步调用；自动过滤转发；无需 Twitter 账号密码或 API Key | ✅ 已实现 |
| **WeChatFetcher** | `we-mp-rss` 本地 HTTP API | 复用 RSSFetcher，`localhost:8001/feed/{mp_id}.rss`；采集前检查服务可用性；依赖 we-mp-rss 本地服务运行 | ✅ 已实现 |
| **ManualFetcher** | 读本地文件 | 扫描 `manual_input/` 目录；支持 JSON/MD/TXT 三种格式；处理完成后移入 `.processed/` 子目录 | ✅ 已实现 |

#### 2026-04-13 变更记录

##### 变更 1：无日期文章跳过（RSSFetcher）

- **问题**：Paul Graham 等 RSS 源不含 `pubDate`，导致历史全部文章灌入 raw.json
- **方案**：`_fetch_single_rss()` 中，当 `published_at is None` 且 `max_age_days > 0` 时，直接跳过该条目
- **影响范围**：仅影响 RSSFetcher，不影响 GitHubFetcher（独立方法）

##### 变更 2：4 个失效 RSS 源迁移到 Exa 定向搜索

- **问题**：a16z / Unreal Engine / Rachel by the Bay / Dwarkesh Patel 的 RSS 长期返回 403/404
- **方案**：在 `config.yaml` 中注释掉这 4 个 RSS 源，新增 Exa `sites` 定向搜索条目
- **兜底逻辑**：ExaFetcher 的 `fallback_sources` 机制仍然保留，可自动为其他临时失败的 RSS 源兜底

##### 变更 3：GitHub Trending 日期增强

- **问题**：第三方 Trending RSS 的 entry 没有日期字段，导致"今日文章=0"
- **方案**（两步增强）：
  1. **榜单捕捉日期**：用 feed 级别的 `published_parsed` 作为 `published_at`，在 `extra.date_type` 中标记为 `"trending_capture"`（区分于项目本身的发布日期）
  2. **GitHub API 补充**：对 `_type == "trending"` 的条目，并发调用 `GET /repos/{owner}/{repo}` 补充三个关键字段：
     - `extra.repo_created_at` — 仓库创建时间（判断新项目 vs 老项目）
     - `extra.stars` — 当前 star 总数（结合创建时间判断爆发程度）
     - `extra.repo_language` — 主语言
  - **API 限速**：无需 Token，60 次/小时；daily trending ≤25 个项目，远低于限速
  - **性能**：并发请求，14 个项目 ~1-2 秒

##### GitHub Trending extra 字段示例

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

**下游判断规则**（供 Layer 2/3 使用）：
| 场景 | 判断方式 |
|------|---------|
| 新项目爆发 | `repo_created_at` 在 30 天内 + 高 stars |
| 中期快速增长 | 1~6 个月 + 高 stars |
| 老项目翻红 | 6 个月以上 + 出现在 daily trending |

##### 设计决策备忘

| 决策 | 结论 | 原因 |
|------|------|------|
| 用 `created_at` 还是首个 Release 时间？ | `created_at` | Release 覆盖率低（很多项目无 release）、API 分页限制（100 条截断）、多 1 次 API 调用 |
| 是否补充 `pushed_at`？ | 不补充 | trending 本身已代表"当前热门"，不需要额外判断活跃度 |
| GitHub Trending 无日期是否需要修复？ | 用 feed 时间兜底 | 第三方 RSS 服务限制，无法修改源数据；feed 级时间足够准确 |

#### 技术选型总结

| 决策点 | 选型 | 原因 |
|--------|------|------|
| HTTP 客户端 | `httpx`（异步） | 原生 async 支持，多源并发采集；50+ 源串行 ~12 分钟，并发 ~1 分钟 |
| RSS 解析 | `feedparser` | 稳定可靠，兼容 RSS 1.0/2.0 和 Atom |
| Twitter 采集 | `xreach` CLI（弃用 twikit） | 零配置、无需账号密码、无 Python 版本限制；数据更丰富（含 views/bookmarks/quotes） |
| Exa 搜索 | `exa-py` SDK | 官方 SDK，支持 `published_after` 过滤，免费额度充足 |
| 微信公众号 | `we-mp-rss` 本地服务 | 已部署运行，提供标准 RSS/Feed 接口，复用 RSS 解析逻辑 |
| 进度展示 | `rich` | Progress bar + Spinner，美化终端输出 |
| 数据模型 | `dataclasses` | 轻量，避免 pydantic 的额外依赖 |
| 类型注解 | `Optional[T]`（非 `T | None`） | 兼容 Python 3.9+，避免版本限制 |

#### Twitter 采集方案演进

```
twikit（旧）                    xreach/agent-reach（新）
─────────────────────           ─────────────────────
❌ 需要 Twitter 用户名+密码      ✅ 零配置
❌ 需要 Python 3.10+             ✅ 无 Python 版本限制（CLI）
❌ Cookie 会过期需重新登录         ✅ 不需要维护
  likes/retweets/replies         ✅ 额外有 views/bookmarks/quotes
  pip install twikit             ✅ xreach v0.3.3 已安装

搜索模式: xreach search "query" -n 20 --json
时间线:   xreach tweets @username -n 10 --json

已知限制: 搜索模式下 user 对象只有 id/restId（无 screenName），
         代码中用 restId 作为 fallback 用户名。
```

#### 错误处理

- 单源 15s 超时，最多重试 2 次（间隔 5s）
- 连续 5 次失败的源标记 `disabled`，每日凌晨重置
- 失败不阻塞其他源，记录到日志
- xreach 命令 30s 超时，JSON 解析失败自动跳过

#### 并发控制

- `run_collector()` 使用 `asyncio.Semaphore(max_concurrent)` 控制并发数（默认 10）
- 各 Fetcher 独立运行，互不阻塞
- 采集结果通过 `asyncio.gather()` 汇总

#### 数据存储策略

- `raw.json` 是**今日信息池**，每次运行 Layer 1 **全量覆盖**（非增量追加）
- 一天只跑一次完整 pipeline，不需要增量合并
- `raw.json` 属于临时中间产物，**自动清理**：保留最近 3 天，超期删除
- 清理由 `pipeline.py` 在每次运行时执行，或 Layer 4 archiver 负责

```
data/
├── 2026-04-13/
│   ├── raw.json          ← 今日信息池（临时，3 天后自动清理）
│   ├── filtered.json     ← Layer 2 输出（临时，3 天后自动清理）
│   ├── llm_results.json  ← CodeBuddy 预生成（临时）
│   └── daily.md          ← Layer 3 输出（长期保留）
├── 2026-04-12/
│   └── ...
```

#### raw.json 格式

```json
{
  "date": "2026-04-13",
  "collected_at": "2026-04-13T23:30:00+08:00",
  "stats": {
    "total": 156,
    "by_channel": {"rss": 98, "github": 12, "exa": 20, "twitter": 15, "wechat": 8, "manual": 3}
  },
  "articles": [
    {
      "source_name": "TechCrunch AI",
      "channel": "rss",
      "title": "...",
      "url": "...",
      "fetched_at": "...",
      "published_at": "...",
      "summary": "...",
      "category": "国外资讯",
      "language": "en"
    }
  ]
}
```

---

### 3.2 Layer 2: 筛选（filter.py）✅ 已实现

> **职责**：对 raw.json 去重、相关性筛选、热度评分、过滤，输出高质量的 `filtered.json`
> **原则**：去噪声、排优先级，但不生成新内容
> **约束**：规则为主、CodeBuddy 为辅。关键词硬筛是主力通道，CodeBuddy 仅用于边界情况的去噪/捞漏。不可用时自动 fallback 到纯关键词筛选
> **架构**：三渠道独立管道 — RSS/微信/Exa、GitHub、Twitter 各自独立评分排序，互不干扰
> **最近更新**：
> - 2026-04-13：LLM 轻筛（方案 C）；三渠道独立评分体系；双层关键词体系；渠道通行证；覆盖广度增强；主日报移除互动数据假维度
> - 2026-04-14：GitHub 通行证移除（Search API 扩展后需验证相关性）；三管道独立配额（pipeline_quotas）；Twitter/GitHub 质量控制门槛；冷门保护机制

#### 核心设计：两道漏斗

```
第一道：相关性硬筛（是不是我关注的领域？）
第二道：热度软排（在关注的领域里，哪些值得看？）
```

#### 输入

- `data/{date}/raw.json`（Layer 1 输出）
- `data/{date-1}/filtered.json`、`data/{date-2}/filtered.json`（前几天的去重窗口）

#### 输出

- `data/{date}/filtered.json`

#### 处理流水线

```
raw.json (~4000+ 篇)
     │
     ▼
┌──────────────────┐
│ Step 1: Normalize│   统一时间格式、清理 HTML、URL 归一化、标题清洗
│                  │   输入 N 篇 → 输出 N 篇（结构标准化）
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Step 2: Dedup    │   URL 精确去重 + 标题模糊去重（72h 窗口）
│                  │   记录 dup_group，计算覆盖广度
│                  │   用源权重选代表（同一事件选最权威的源）
└────────┬─────────┘
         ▼
┌───────────────────────┐
│ Step 3a: Relevance    │   双层关键词匹配（signals + brands）
│ 关键词硬筛（主力）     │   + 渠道通行证（github/manual 直接通过）
│                       │   命中标签 → 标记 relevance_tags
│                       │   → keyword_passed (~200篇)
│                       │   → keyword_rejected (~3800篇)
└────────┬──────────────┘
         ▼
┌───────────────────────┐
│ Step 3b: LLM 去噪     │   复核 keyword_passed 中的低置信度命中
│ （关键词假阳性）       │   仅品牌词单词命中 + 非标题命中 → LLM 判断
│                       │   ❌ "Yi姓DNA分析" → 踢掉
│                       │   ✅ "Yi-Lightning 新模型" → 保留
└────────┬──────────────┘
         ▼
┌───────────────────────┐
│ Step 3c: LLM 捞漏     │   扫描 keyword_rejected 中的潜在漏网之鱼
│ （关键词假阴性）       │   batch 发送标题 → LLM 判断是否与
│                       │   AI核心/AI游戏/AI视频/AI社交/AI Agent
│                       │   等具体关注领域相关
│                       │   ✅ 捞回 ~10篇 + 自动打标签
└────────┬──────────────┘
         ▼
┌───────────────────────┐
│ Step 3.5: Split       │   按渠道分流为三条独立管道
│                  │   RSS/微信/Exa → 主日报管道
│                  │   GitHub → GitHub Trending 管道
│                  │   Twitter → Twitter 热议管道
└────────┬─────────┘
         ├──────────────────────────────────────────┐
         ▼                    ▼                      ▼
┌─── 📰 主日报管道 ───┐ ┌─ 🐙 GitHub 管道 ──┐ ┌─ 🐦 Twitter 管道 ─┐
│ Score: 信号匹配强度  │ │ Score: 项目质量    │ │ Score: 热度排名    │
│  + 时效性 + 覆盖广度 │ │  stars 相对排名    │ │  likes/RT 排名     │
│  + 多标签加成        │ │  + 新项目加分      │ │  纯互动量排序      │
│ Filter: 标签配额制   │ │  + 主题相关性     │ │  相关性由关键词保证 │
│  pipeline_quotas.main│ │ Filter:           │ │ Filter:            │
│  ai_core:5 等       │ │  pipeline_quotas   │ │  pipeline_quotas   │
│                     │ │  .github 按标签    │ │  .twitter 按标签   │
│                     │ │  min_stars 门槛    │ │  min_heat 门槛     │
└────────┬────────────┘ └────────┬──────────┘ └────────┬───────────┘
         │                       │                      │
         └───────────────────────┴──────────────────────┘
                                 ▼
                     filtered.json (~30+ 篇 + ~15 项目 + ~10 推文)
                     每篇文章带 output_section 字段
```

#### 2026-04-13 相关性筛选重大改进

##### 改进 1：双层关键词体系（替代旧的单一 keywords 列表）

| 层级 | 说明 | 设计目的 | 示例 |
|------|------|---------|------|
| **信号词 (signals)** | 描述领域的通用概念词 | 不随产品更迭过时，**自动覆盖未来新品** | "AI视频生成"、"大模型"、"agent framework" |
| **品牌词 (brands)** | 具体产品/公司/模型名 | 精确命中已知目标 | "Sora"、"DeepSeek"、"Cursor" |

- 两层 OR 关系：命中任意一个就算匹配
- 信号词是主力：一篇讲 "全新AI视频生成工具XXX" 的文章，即使XXX不在品牌词列表里，"AI视频生成" 这个信号词也能捕获它
- 旧配置中的 `keywords` 字段仍然兼容

**旧方案问题**：关键词全是具体名称（`GPT-4`、`Sora`、`Cursor`），对市场新品无能为力
**新方案解决**：信号词覆盖领域通用概念，品牌词精确命中已知产品，双管齐下

##### 改进 2：英文短词词边界匹配

| 词长 | 匹配方式 | 原因 |
|------|---------|------|
| ≤ 4 字符的纯 ASCII 词 | `\b` 正则词边界 | 避免 "o1" 匹配 "o1签证"、"Yi" 匹配 "Yi姓" |
| 中文词 / 长英文词 | `in` 子串匹配 | 中文无自然词边界，长词误命中概率低 |

预编译所有正则，无运行时性能损耗。

##### 改进 3：渠道通行证

```yaml
always_pass_channels:
  # - github   # 已移除：Search API 扩展后需要关键词/LLM 验证相关性
  - manual     # 手工输入已是人工判断
```

当前仅 **manual** 渠道的文章跳过关键词检查，直接进入评分排序。

**GitHub 通行证移除原因（2026-04-14）**：
- 初期仅采集 Trending，上榜本身已是社区筛选，通行证合理
- 现在 GitHub Search API 按 7 个兴趣领域定向搜索，采集范围大幅扩展
- 搜索结果中可能包含仅名称沾边但实际不相关的项目，需要关键词/LLM 验证

##### 改进 4：覆盖广度评分增强

跨渠道覆盖比同渠道多源更有价值（同一事件 RSS + Twitter + 微信 > 3 个 RSS 源）：

| 条件 | 分数 | 说明 |
|------|------|------|
| 3+ 渠道 or 5+ 源 or 6+ 报道 | **3.0** | 重大事件（↑ 从 2.5 提升到 3.0） |
| **2 渠道** or 4+ 源 or 4+ 报道 | **2.5** | 热点事件（↑ 从 2.0 提升到 2.5） |
| 3 源 or 3 报道 | 1.5 | 有热度 |
| 2 源 or 2 报道 | 0.5 | 有一定关注度 |
| 单源 | 0.0 | 无覆盖加分 |

##### 改进 5：LLM 轻筛 — 方案 C（关键词主力 + LLM 去噪/捞漏）

> **2026-04-13 新增**。解决关键词硬筛的两个结构性短板：假阳性（歧义词误入）和假阴性（间接表达漏掉）。
> **适用范围**：当前仅用于**主日报管道**（RSS/微信/Exa）。GitHub 预留接口，未来收集范围调整后可启用。Twitter 不需要（关键词搜索结果本身已保证相关性）。
> **2026-04-14 重大更新**：
> - **ID 稳定化**：classify/rescue 候选的 ID 从顺序编号（`c0, c1, c2...`）改为基于标题的 sha256 哈希（`c81c67417`），消除 `run_filter` 重跑时的 ID 漂移问题
> - **单标签分类**：去掉 `secondary_tags`，每篇文章只保留一个 `primary_tag`，降低分类歧义
> - **quality 0-3 分**：LLM classify 时同步打质量分，替代旧的"多标签加成"评分维度
> - **板块定义重构**：ai_social 限定为 AI 社交产品、ai_agent 扩展、opinion 扩展为宏观洞察

**LLM classify 输出格式**：

```json
[
  {"id": "c81c67417", "relevant": true, "primary_tag": "ai_agent", "quality": 3, "reason": "一句话原因"},
  {"id": "cfc90a83d", "relevant": false, "primary_tag": "not_relevant", "quality": 0, "reason": "与AI无关"}
]
```

**ID 稳定化机制**：

```python
def _stable_id(prefix: str, art: dict) -> str:
    """基于标题的稳定哈希ID，不随文章顺序变化"""
    content = art.get('title', '')
    return f"{prefix}{hashlib.sha256(content.encode()).hexdigest()[:8]}"
```

> 解决的问题：`run_filter` 每次执行时去重后文章顺序可能变化，旧的顺序编号（c0, c1...）会导致 `llm_filter_results.json` 和 `llm_filter_input.json` 的 ID 错位。哈希 ID 基于标题内容，无论跑多少次同一篇文章的 ID 永远不变。

##### 改进 6：内容类型分类与观点分流（技术/产品优先，观点类独立板块）

> **2026-04-13 新增**，**2026-04-14 重大调整**：观点文章从"降权竞争"改为"分流到独立板块"。
> **适用范围**：影响**主日报管道**（rss/wechat/exa）和 **Twitter 管道**。GitHub 不参与。

**问题演进**：
- 2026-04-13：观点类 -1.0 降权，在同一标签配额里排后面 → 大部分被淘汰
- 2026-04-14：有价值的行业洞察也被淘汰了 → 改为分流到独立"行业观点"板块

**当前方案（2026-04-14）**：opinion 文章**不降权**，而是从 main/twitter 管道**分流**到独立的观点池：

```
main/twitter 管道中的文章
       │
       ├── content_type != "opinion" → 正常参与标签配额竞争
       │
       └── content_type == "opinion" → 分流到观点池
                                        │
                                        ▼
                                   排序：VIP 优先 > 综合评分
                                   取 top-3 → "行业观点"板块
```

**内容分类逻辑**（`ContentTypeClassifier`）：

```
                    标题+摘要
                        │
                        ▼
              ┌─────────────────┐
              │ 双路信号词匹配    │
              │ tech_signals ──→ tech_score
              │ opinion_signals → opinion_score
              │ 标题命中 ×2 权重  │
              └────────┬────────┘
                       ▼
         ┌───── 分类判断（技术优先）─────┐
         │                              │
    tech_score ≥ 2                opinion_score ≥ 2
    且 ≥ opinion_score            且 > tech_score + 1
         │                              │
         ▼                              ▼
   "tech_product"                  "opinion"
   技术/产品发布                    观点/评论文
         │                              │
         │                         VIP 检查
         │                     ┌────┴────┐
         │                     ▼         ▼
         │               VIP 作者    普通作者
         │               不降权       降权 -1.0
         ▼
   加分 +0.5                    其他 → "news" (不调整)
```

| 类型 | 评分调整 | 处理方式 | 信号词示例 |
|------|---------|---------|-----------|
| `tech_product` | **+0.5** | 在原标签板块正常竞争 | "发布""开源""推出""架构""训练""API""benchmark" |
| `opinion` | **+0.0** | **分流到独立"行业观点"板块**，不参与原标签配额 | "认为""演讲""焦虑""失业""吗？""为什么" |
| `news` | **+0.0** | 在原标签板块正常竞争 | 其他 |

**观点板块排序规则**：VIP 作者优先 → 综合评分（含时效性+覆盖广度）→ 取 top-3

**VIP 作者机制**：

VIP 作者的 opinion 文章在观点板块中**排序优先**（VIP > 非VIP），但**只出现在观点板块**，不双重曝光到原标签板块。

```yaml
# config.yaml → filter.content_type
vip_authors:               # 这些人的观点文章不降权
  - "Sam Altman"
  - "Matthew Ball"          # 用户特别提到
  - "Andrej Karpathy"
  - "Yann LeCun"
  - "Ben Thompson"          # Stratechery
  - "Simon Willison"
  - ...

vip_sources:               # 这些源的观点文章不降权
  - "OpenAI Blog"
  - "Anthropic"
  - "Google DeepMind"
  - "a16z Blog"
```

**实证效果（2026-04-13 数据）**：

| 分类 | 全部主日报文章 | 入选文章 | 说明 |
|------|-------------|---------|------|
| tech_product | 77 篇（46%） | **18 篇**（75%） | 技术/产品类在配额竞争中优势明显 |
| opinion | 10 篇（6%） | **2 篇**（8%） | 观点类被有效控制 |
| news | 79 篇（48%） | **4 篇**（17%） | 新闻类中性，按热度竞争 |

被正确降权的观点文示例：
- "AI 会带来大规模失业吗？" → opinion -1.0（泛泛讨论，非核心资讯）
- "米哈游刘伟演讲：对抗AI时代焦虑" → opinion -1.0（演讲+焦虑类）

被正确加分的技术文示例：
- "大佬深度解析：Coding Agent 的底层运行逻辑" → tech_product +0.5（虽含"深度解析"但有"底层""逻辑""运行"等技术信号）
- "Scaling Managed Agents: Decoupling..." → tech_product +0.5（架构类技术文）

##### 改进 7：三管道独立配额体系（pipeline_quotas）

> **2026-04-14 升级**。替代旧的单一 `quota_per_tag`，三个管道各自拥有独立的标签配额。

**旧方案问题**：main/github/twitter 共享同一套 `quota_per_tag`，管道间性质差异大却平等竞争。

**新方案**：`pipeline_quotas` 为每个管道分别配置标签配额，管道间互不干扰：

```yaml
pipeline_quotas:
  main:                    # 📰 主日报管道
    ai_core: 3
    ai_agent: 5
    ai_video: 5
    ai_gaming: 5
    ai_social: 5
    ai_product: 3
    ai_business: 3
  github:                  # 🐙 GitHub 管道（按标签独立竞争）
    ai_core: 2
    ai_agent: 3
    ai_video: 2
    ai_gaming: 2
    ai_social: 2
    ai_product: 1
    ai_business: 1
  twitter:                 # 🐦 Twitter 管道
    ai_core: 2
    ai_agent: 2
    ai_video: 1
    ai_gaming: 1
    ai_social: 1
    ai_product: 1
    ai_business: 1
```

旧的 `quota_per_tag` 保留作为 fallback：未在 `pipeline_quotas` 中配置的管道退化为此值。

##### 改进 8：Twitter / GitHub 质量控制门槛

> **2026-04-14 新增**。在标签配额竞争之前，先淘汰低质量内容。

| 管道 | 门槛 | 计算公式 | 说明 |
|------|------|---------|------|
| **Twitter** | `min_heat: 50` | `likes×1.0 + retweets×3.0 + views×0.01` | 低于 50 的推文直接淘汰，避免冷门推文凑数 |
| **GitHub** | `min_stars: 5` | 当前 star 总数 | 低于 5 stars 的项目直接淘汰，避免 spam 项目 |

**参考数值**：
- likes=7 views=489 → heat≈11.9（不过门槛）
- likes=140 retweets=42 views=24760 → heat≈513.6（轻松过门槛）

##### 改进 9：冷门保护机制

> **2026-04-14 新增**。优质源/核心标签的低热度文章受保护，降低通过阈值。

**问题**：Simon Willison、Lilian Weng 等大牛的文章可能因为发布时间晚导致热度还没起来，在配额竞争中被淘汰。

```yaml
cold_protection:
  enabled: true
  threshold_override: 2        # 受保护文章的通过阈值（正常核心是 4）
  max_protected_per_day: 3     # 每天最多保护 3 篇，防止噪声
  protected_sources:
    - "Simon Willison"
    - "Lilian Weng"
    - "Jay Alammar"
  protected_tags:              # 这些标签的文章更值得保护
    - "ai_core"
    - "ai_gaming"
    - "ai_agent"
```

##### 改进 10：事件级去重（配额选择阶段）

> **2026-04-14 新增**。解决同一事件多篇报道同时入选的问题。

**问题**：Step 2 的标题去重（阈值 0.85）无法捕获同一事件的不同角度报道——"马斯克版微信亮相" vs "马斯克版微信，终于来了！" 标题相似度仅 0.4，但讲的是同一产品。

**解决**：在 `_select_by_tag_quota` 的配额选择循环中，对每篇候选文章检查是否和已入选文章是同一事件：

```
候选文章 → 是否已有同事件入选？
              │
              ├── 标题相似度 > 0.5 → 同事件，跳过
              │
              ├── 共享核心实体关键词 → 同事件，跳过
              │   （≥4字符中文实体 or ≥4字符英文实体）
              │   排除通用词：Agent/Model/AI/大模型/开源/发布等
              │
              └── 无匹配 → 不同事件，正常入选
```

**跨管道去重**：main 管道入选的标题传递给 twitter 管道，同一事件不会在两个管道各入选一次。

**误杀控制**：
- 通用词排除列表（Agent, Model, AI, Microsoft, OpenAI, 大模型, 人工智能等）
- 实体长度门槛 ≥4 字符
- 实证：4-14 数据 OpenClaw 2→1、马斯克版微信 3→2，误杀 2 篇（可接受）

**双层关键词体系的结构性短板**：

| 短板 | 示例 | 原因 |
|------|------|------|
| **假阳性（误入）** | "Yi 姓家族 DNA 分析"命中品牌词"Yi" | 关键词**语义歧义**，词边界保护只能解决一部分 |
| **假阴性（漏掉）** | "微软将投入800亿美元建设数据中心" — 没有任何关键词命中 | 文章用**间接表达**讨论 AI 相关领域 |

**方案 C 的核心思路**：关键词仍是主力（200 篇级别命中量已证明覆盖率不错），LLM 只处理两种边界情况。LLM 不可用时自动跳过，退化为纯关键词筛选。

```
raw.json
   │
   ├── Step 3a: 关键词硬筛
   │   ├── keyword_passed（~200篇）──→ Step 3b: LLM 去噪（复核低置信度命中）──→ 通过 ~180篇
   │   │                                                                          │
   │   ├── keyword_rejected（~3800篇）→ Step 3c: LLM 捞漏（batch 标题扫描）──→ 捞回 ~10篇
   │   │                                                                          │
   │   └──────────────── 合并 ────────────────────────────────────────────────→ ~190篇
```

**Step 3b: LLM 去噪（复核关键词假阳性）**

对 `keyword_passed` 中的**低置信度命中**做 LLM 复核：

```python
# 哪些需要复核？
needs_review = [
    a for a in keyword_passed
    if a["_match_type"] == "brand_only"      # 仅品牌词命中（歧义风险高）
    and a["_match_count"] == 1               # 只命中了1个词
    and a["_match_in_title"] == False         # 不是标题命中（正文命中更不确定）
]
# 预估：~20-40 篇需要复核
```

Prompt 设计（batch，一次传 20-30 篇）：

```
你是一个 AI 资讯相关性判断器。

我关注以下具体领域：
- AI 核心技术：大模型、训练推理、模型架构、AI 芯片、AI 安全
- AI Agent：智能体、AI 编程、Function Calling、多 Agent、自动化工作流
- AI 视频：文生视频、AI 短剧、AI 动画、AI 特效、视频生成模型
- AI 游戏：AI 原生游戏、智能 NPC、AI 关卡生成、游戏研发提效、游戏 AIGC
- AI 社交：AI 伴侣、AI 角色扮演、虚拟陪伴、社交 AI 产品
- AI 产品/应用：AI 搜索、AI 绘画、AI 写作、AI 工具、AI 创业产品
- AI 行业动态：AI 公司融资、收购、IPO、营收数据

以下是一批文章标题和摘要，它们已通过关键词匹配，但可能存在歧义（如"Yi"可能是人名、
"GPT"可能是考试缩写、"Phi"可能是物理符号）。
请基于完整语境判断每篇是否真正与上述任一领域相关。

输出 JSON：[{"id": "xxx", "relevant": true/false, "reason": "一句话原因"}]

文章列表：
1. [id: abc] 标题: ... 摘要: ...
2. [id: def] 标题: ... 摘要: ...
...
```

**Step 3c: LLM 捞漏（找回关键词假阴性）**

对 `keyword_rejected` 做**轻量标题扫描**，batch 发送：

```python
# 预过滤：用宽松的人物/公司名单缩小范围，减少 LLM 调用量
# 这些不是关键词体系里的精确匹配词，而是"可能沾边"的宽松触发词
loose_trigger_names = [
    # AI 领域核心人物
    "Sam Altman", "Satya Nadella", "Jensen Huang", "Elon Musk",
    "Mark Zuckerberg", "Sundar Pichai", "Demis Hassabis",
    "Dario Amodei", "李彦宏", "黄仁勋", "马斯克",
    # 科技巨头（可能间接涉及 AI 基建/战略）
    "微软", "Microsoft", "谷歌", "Google", "英伟达", "NVIDIA",
    "苹果", "Apple", "Meta", "Amazon", "亚马逊",
    "腾讯", "字节", "ByteDance", "阿里", "百度",
    "台积电", "TSMC", "三星", "Samsung",
    # 游戏行业（可能涉及 AI 游戏）
    "Epic Games", "Roblox", "米哈游", "网易游戏", "暴雪",
    # 社交平台（可能涉及 AI 社交）
    "Discord", "Snap", "Instagram",
    # 泛 AI 相关词（很宽松，只是缩小到 LLM 能处理的量）
    "数据中心", "data center", "芯片", "chip", "GPU",
    "机器人", "robot", "自动驾驶", "autonomous",
]

maybe_relevant = [
    a for a in keyword_rejected
    if any(name.lower() in a["title"].lower() for name in loose_trigger_names)
]
# maybe_relevant 约 100-300 篇 → 2-6 次 batch 调用
```

Prompt 设计（batch，每批 50 个标题）：

```
你是一个 AI 资讯相关性判断器。

我高度关注以下具体领域：
- AI 核心技术：大模型发布、训练推理、模型架构、AI 芯片/算力基建、AI 安全与监管
- AI Agent：智能体、AI 编程工具、多 Agent 系统、自动化工作流
- AI 视频：文生视频、AI 短剧/动画/电影、视频生成模型
- AI 游戏：AI 原生游戏、智能 NPC、游戏 AIGC、游戏研发提效
- AI 社交：AI 伴侣/角色扮演、虚拟陪伴、社交 AI 产品
- AI 产品/应用：AI 搜索、AI 绘画、AI 工具、AI 创业产品上线
- AI 行业动态：AI 头部公司融资/收购/IPO/营收

以下是一批文章标题，它们没有命中预设的 AI 关键词，但可能仍然与上述领域高度相关。
请识别出那些**确实与上述具体领域核心相关但使用了间接表达**的文章。

例如：
- "微软将投入800亿美元建设数据中心" → AI 算力基建，属于 ai_core
- "Sam Altman 谈下一个十年" → AI 领域核心人物，属于 ai_core
- "Epic 发布新一代虚拟人技术" → 可能涉及 AI+游戏，属于 ai_gaming
- "Snap 推出新型聊天机器人" → 可能涉及 AI 社交，属于 ai_social

**严格标准：不要把所有沾边的都捞进来，只选明确与上述领域核心相关的。**
如果一篇文章只是泛泛提到科技公司但与 AI 无直接关系，不要选。

输出 JSON：[{"id": "xxx", "relevant": true, "reason": "...", "suggested_tags": ["ai_core"]}]
只输出 relevant=true 的。

文章标题列表：
1. [id: abc] "微软将投入800亿美元建设数据中心"
2. [id: def] "新一轮科技人才招聘潮"
...（每批50个标题）
```

**LLM 调用成本估算**：

| 环节 | 文章数 | 每批大小 | 调用次数 | 输入 token（估） |
|------|--------|---------|---------|----------------|
| 去噪（复核假阳性） | ~30 | 30 | 1 | ~3k |
| 捞漏（预过滤后） | ~200 | 50 | 4 | ~8k |
| **合计** | | | **~5 次** | **~11k token** |

使用系统默认主模型，成本可忽略不计。

**Fallback 机制（三级退化）**：

```python
# 优先级：API 自动调用 > CodeBuddy 对话式代跑 > 纯关键词
try:
    denoised = llm_denoise(keyword_passed)       # Step 3b
    rescued = llm_rescue(keyword_rejected)        # Step 3c
except (APIError, Timeout, RateLimitError):
    logger.warning("LLM 不可用，fallback 到纯关键词筛选")
    denoised = keyword_passed                     # 跳过去噪
    rescued = []                                  # 跳过捞漏
```

##### CodeBuddy 离线轻筛（当前方案，无需 API Key）

> **2026-04-14 统一**：所有 LLM 工作（editor 摘要、filter 去噪/捞漏）均由 CodeBuddy 在对话中完成，不依赖任何外部 API。已移除所有 OpenAI SDK 调用代码。

**工作流程**：

```
用户发起对话: "帮我跑一次轻筛"
       │
       ▼
CodeBuddy 读取 raw.json + config.yaml
       │
       ├─ 重跑 Step 1-3a（Normalize → Dedup → Relevance）获取元数据
       │
       ├─ Step 3b 去噪：识别低置信度命中文章，直接在对话中逐篇判断
       │   输出格式：标题 | ✅保留/❌踢掉 | 理由
       │
       ├─ Step 3c 捞漏：扫描宽松触发词命中的被拒文章，判断是否值得捞回
       │   输出格式：标题 | ✅捞回(标签) / ❌不捞 | 理由
       │
       └─ 将判断结果写回 filtered.json（通过 Python 脚本执行）
```

**与 API 调用模式的对比**：

| 维度 | API 自动调用 | CodeBuddy 代跑 |
|------|---------------|
| 触发方式 | `run_filter()` 自动检测 `llm_filter_results.json`；无文件时导出候选 |
| 需要 API Key | ❌ 不需要，用 CodeBuddy 自身模型 |
| 判断质量 | 取决于 CodeBuddy 主模型能力 |
| 可审计性 | 对话全程可见，判断过程透明 |
| 自动化程度 | 半自动（CodeBuddy 生成结果后，filter.py 自动应用） |
| 适用场景 | 所有场景（日常运行 + 调试审核） |

**脚本支持**：`scripts/run_llm_light_filter.py` 封装了完整的重跑流程，CodeBuddy 判断完成后通过修改脚本中的判断列表即可一键写入 filtered.json。

**实证数据（2026-04-13）**：

| 指标 | 纯关键词 | + CodeBuddy 轻筛 |
|------|---------|-----------------|
| 去噪 | 0 篇踢掉 | 3 篇假阳性踢掉 |
| 捞漏 | 0 篇捞回 | 8 篇捞回 |
| 最终入选 | 41 篇 | 43 篇 |
| ai_gaming 覆盖 | 7 篇 | 9 篇 |

**GitHub 预留接口**：

当前 GitHub Trending 使用渠道通行证直接通过，不经过关键词+LLM 筛选。但如果未来调整 GitHub 的收集范围（如不再限于 Trending、加入自定义仓库监控等），可以复用 LLM 轻筛的去噪/捞漏工具。接口设计预留 `pipeline` 参数：

```python
def llm_light_filter(articles, pipeline="main"):
    """
    LLM 轻筛通用接口。
    pipeline: "main" | "github"（未来扩展）
    不同 pipeline 可使用不同的 prompt 模板和触发条件。
    """
```

**LLM 模型选型**：使用系统默认主模型（跟随 config.yaml 中的全局 LLM 配置），不额外指定模型。

#### 相关性标签

> **2026-04-14 重构**：板块定义全面更新，ai_social 限定为 AI 社交产品，ai_agent 扩展游戏化社交/创作人格，opinion 扩展为观点+宏观洞察，ai_gaming 新增 AI Native 玩法。

| 标签 | 关注领域 | 优先级 | 主日报配额 |
|------|----------|--------|----------|
| `ai_core` | AI 核心技术：大模型发布/架构创新/训练推理/Scaling Law、具身智能/世界模型/Physical AI、学术论文/基准评测/开源模型、模型能力变化。不含：芯片硬件/AI安全合规/纯数学 | core | 3 |
| `ai_agent` | AI Agent 产品与架构：AI 编程助手（Cursor/Copilot/Claude Code）、自动化工作流编排、多 Agent 协作、Agent Memory/OS、**Agent 游戏化社交**（斯坦福 AI 小镇/扣子养虾）、AI 桌面助手、**AI 创作人格**（Ribbi 等） | core | **10** |
| `ai_video` | AI 视频与影像生成：AI 视频生成模型（Sora/Vidu/Kling）、AI 短剧/动画/电影、AI 图像生成/编辑、文生视频/图生视频 | core | 5 |
| `ai_gaming` | AI + 游戏：AI 驱动的游戏新玩法（AI NPC/AI 剧情生成/AI UGC 关卡编辑器）、**AI Native 游戏设计**、游戏行业应用 AI 深度报道。不含：纯游戏行业新闻（营收/人事/评测） | core | 5 |
| `ai_social` | **AI 社交产品（仅限具体产品）**：融合 AI 能力的社交软件（AI 版微信/XChat/AI 推特等）、AI 虚拟伴侣/角色扮演社交平台。不含宏观社会影响讨论 | core | 5 |
| `ai_product` | 其他 AI 产品与应用（兜底板块）：AI 办公工具、AI 搜索、AI 硬件产品 | supplementary | 3 |
| `ai_business` | AI 商业动态：投融资/收购/IPO/营收财报、公司竞争策略（内部信/定价/市场份额）、AI 产品出海商业化 | supplementary | 3 |
| `opinion` | **观点与宏观洞察**：个人观点/评论/行业展望/思考（非事实性新闻）、AI 宏观议题（AI 伦理/治理/哲学/就业影响/AI 孵化器生态分析等非产品类讨论） | independent | 3（独立池） |
| `ai_business` | AI 行业动态 / 融资 | fyi | 3 |

#### 热度评分（满分 8 分）

**主日报管道（rss/wechat/exa）— 四维度**：

```
时效性(0-3.0) + 覆盖广度(0-3.0) + LLM质量分(0-1.5)
+ 内容类型调整(tech_product:+0.5, opinion:+0.0, news:+0.0)
+ 优质源 bonus(0-0.5)
```

> **2026-04-14 更新**：将"多标签加成"维度替换为"LLM 质量分"维度。
> quality 0-3 由 LLM classify 时同步打分，映射为评分加成：quality×0.5（最高1.5分）。
> 效果：区分度从 0.5 分扩大到 2+ 分，重大产品发布(q=3)比活动推广(q=0)高 1.5 分。

**quality 定义**：

| quality | 含义 | 评分加成 | 示例 |
|---------|------|---------|------|
| 3 | 重大 | +1.5 | 产品首发/技术突破/独家深度/重要开源/重大融资收购 |
| 2 | 常规 | +1.0 | 行业报告/公司动态/产品更新/技术解析/垂直领域周报盘点 |
| 1 | 边缘 | +0.5 | 消费评测/泛科技/轻度相关 |
| 0 | 噪声 | +0.0 | 活动推广/榜单征集/申报/投票/招聘/广告/纯拼接型聚合新闻 |

**quality=0 强制规则**（标为 not_relevant）：
- 标题含"申报""征集""报名""投票"等行动号召词 → 一律 quality=0
- 标题用分号/竖线拼接 ≥3 条无关新闻的聚合晚报/早报/速递 → quality=0
- 垂直领域周报（如"AI短剧周报"）聚焦单一主题的除外

**GitHub/Twitter 管道** — 保留互动数据维度（stars/likes 有真实数据，不受影响）。

#### filtered.json 格式

```json
{
  "date": "2026-04-13",
  "filtered_at": "2026-04-13T23:35:00+08:00",
  "config_snapshot": {
    "scoring_dimensions": "主日报四维度（时效3+覆盖3+quality质量1.5+内容类型调整）满分8；GitHub/Twitter保留互动数据维度",
    "content_type_scoring": "tech_product:+0.5, opinion:+0.0, news:+0.0",
    "pipeline_quotas": {
      "main": {"ai_core": 3, "ai_agent": 10, "ai_video": 5, "ai_gaming": 5, "ai_social": 5, "ai_product": 3, "ai_business": 3},
      "github": {"ai_core": 3, "ai_agent": 3, "ai_video": 2, "ai_gaming": 2, "ai_social": 2, "ai_product": 2, "ai_business": 1},
      "twitter": {"ai_core": 2, "ai_agent": 2, "ai_video": 1, "ai_gaming": 1, "ai_social": 1, "ai_product": 1, "ai_business": 1}
    },
    "quality_control": {"twitter_min_heat": 50, "github_min_stars": 5},
    "dedup_window_hours": 72
  },
  "stats": {
    "input": 4265,
    "after_dedup": 3800,
    "after_relevance": 200,
    "after_filter": 43,
    "by_section": {"main": 30, "github": 8, "twitter": 5},
    "by_relevance_tag": {"ai_core": 80, "ai_agent": 50, "ai_gaming": 30, "ai_video": 20, "ai_social": 10, "ai_product": 5, "ai_business": 5},
    "by_tag_passed": {"ai_core": 5, "ai_agent": 5, "ai_gaming": 5, "ai_video": 5, "ai_social": 3, "ai_product": 5, "ai_business": 3}
  },
  "articles": [
    {
      "source_name": "OpenAI Blog",
      "channel": "rss",
      "title": "Introducing GPT-5",
      "url": "https://openai.com/blog/gpt-5",
      "published_at": "2026-04-13T18:00:00Z",
      "summary_clean": "We're releasing GPT-5...",
      "output_section": "main",
      "score": 7.5,
      "score_details": {"signal_strength": 2.0, "timeliness": 2.5, "coverage": 2.0, "quality": 1.5},
      "relevance_tags": ["ai_core"],
      "relevance_priority": "core",
      "primary_tag_llm": "ai_core",
      "quality": 3,
      "is_duplicate": false,
      "coverage_count": 5,
      "filtered_out": false,
      "filter_reason": null
    },
    {
      "source_name": "GitHub Trending",
      "channel": "github",
      "title": "openai/codex - Code generation agent",
      "url": "https://github.com/openai/codex",
      "output_section": "github",
      "score": 3.2,
      "score_details": {"stars_rank": 2.0, "newness_bonus": 1.0, "topic_relevance": 0.2},
      "extra": {"stars": 5200, "repo_created_at": "2026-04-01T...", "repo_language": "Python"}
    },
    {
      "source_name": "Twitter Search",
      "channel": "twitter",
      "title": "@karpathy: GPT-5 is a significant leap...",
      "url": "https://x.com/karpathy/status/...",
      "output_section": "twitter",
      "score": 3.0,
      "score_details": {"likes_rank": 2.0, "retweets_rank": 0.8, "extra_engagement": 0.2},
      "extra": {"likes": 12500, "retweets": 3200, "views": 850000}
    }
  ]
}
```

---

### 3.3 Layer 3: 编辑（editor.py）✅ 已实现

> **职责**：读取 filtered.json + llm_results.json，按板块渲染 Markdown 日报
> **原则**：LLM 工作由 CodeBuddy 在对话中完成，不依赖外部 API
> **状态**：✅ 完整工作流已实现（2026-04-14）
> **最近更新**：2026-04-14，summary 基于全文生成；URL 精确匹配替代顺序索引；summary 写作规范（≤40字、[主体]+[动作]+[结果]）

#### 工作流

```
CodeBuddy 对话                            editor.py 脚本
─────────────                              ────────────────
1. 读取 filtered.json                      
2. 按 Prompt 模板为每个板块                
   生成 LLM 结果                           
3. 写入 llm_results.json                   
                                           4. 加载 filtered.json + llm_results.json
                                           5. 三管道分组（main/twitter/github）
                                           6. 逐板块渲染 Markdown
                                           7. 输出 daily.md
```

#### 输入

- `data/{date}/filtered.json`（仅 `filtered_out=false` 的文章）
- `data/{date}/llm_results.json`（CodeBuddy 预生成的摘要/关键词/洞察）

#### 输出

- `data/{date}/daily.md` — Markdown 格式日报

#### 四板块渲染架构

```
filtered.json 入选文章
       │
       ├── channel in (rss, wechat, exa, manual) ─┬─ opinion → 💡 行业观点板块
       │                                           │            VIP优先 > 评分，取 top-3
       │                                           │
       │                                           └─ 非opinion → 📰 主日报管道
       │                                                          按 relevance_tag 分 7 个板块
       │
       ├── channel == twitter ──┬─ opinion → 💡 行业观点板块（合并）
       │                        └─ 非opinion → 🐦 Twitter 热门
       │                                       按 score 降序，取 top-N
       │
       └── channel == github → 🐙 GitHub 热门项目
              按 stars 降序，取 top-N
```

#### LLM 结果加载（LLMResultLoader）

> **2026-04-14 重大更新**：匹配机制从顺序索引改为 URL 精确匹配；summary 基于源文章全文生成。

`llm_results.json` 由 CodeBuddy 在对话中按 Prompt 模板生成，结构：

```json
{
  "ai_core": {
    "articles": [
      {"id": 1, "url": "https://...", "title": "原文标题", "summary": "...", "keywords": ["k1", "k2"]},
      ...
    ],
    "insight": "板块洞察..."
  },
  "twitter": { ... },
  "github": { ... }
}
```

- 每个板块的 key 对应 `relevance_tag`（主日报）或 `"twitter"` / `"github"`
- **匹配优先级**（解决旧顺序索引漂移问题）：
  1. **URL 精确匹配**：`article.url == item.url`（最可靠）
  2. **标题前缀匹配**：`article.title[:30] == item.title[:30]`（fallback）
  3. **旧式顺序索引**：`int(item.id) - 1`（兼容旧格式）

**summary 生成流程**（2026-04-14 新增）：

```
入选文章 URL → web_fetch 抓取全文 → 基于全文写摘要
```

- 微信/RSS 文章均通过 web_fetch 抓取原文全文
- summary 基于全文核心内容生成，而非仅靠标题推测
- Twitter 推文本身即全文，无需额外抓取

#### Prompt 模板（summary 写作规范）

> 2026-04-14 优化：强制结构公式、字数压缩到 ≤40 字、加入正反示例

三个 Prompt 模板（`SECTION_PROMPT`、`TWITTER_PROMPT`、`GITHUB_PROMPT`）的 summary 核心规范：

| 维度 | 要求 |
|------|------|
| **结构** | **[主体] + [做了什么] + [关键结果]** |
| **字数** | ≤40 字中文，只保留最核心的一个事件 |
| **具体性** | 必须出现具体产品名/公司名/人名，禁止"某AI产品""新工具"等模糊表述 |
| **反重复** | 一句话中不得用不同措辞说同一件事 |
| **反渲染** | 删掉"全面突围""标志着""引爆市场"等空洞修饰 |
| **与关键词的关系** | 互补不重叠 — keywords 承载实体名，summary 聚焦事件动态 |
| **GitHub 特殊** | 必须以项目名开头，说功能不说评价 |

好的示例：
- ✅ "Anthropic发布Managed Agents架构，将推理与执行解耦提升Agent扩展性"
- ✅ "Cisco拟3.5亿美元收购AI安全公司Astrix Security"
- ✅ "markitdown: 微软开源的多格式转Markdown工具"

差的示例：
- ❌ "Anthropic获取70%新增企业客户，Claude推出灵魂校准对齐策略，从工程师口碑到企业信任全面突围"
- ❌ "新款AI男友产品上线，标志着AI情感陪伴从女性市场延伸到全性别覆盖"

#### Markdown 渲染格式

**主日报文章**：
```markdown
- **一句话概括（LLM summary）**
  关键词: k1 | k2 | k3 · 04-13 · [原文](url)
```

**Twitter 推文**（额外展示热度数据）：
```markdown
- **一句话概括**
  关键词: k1 | k2 · 04-13 · 🔁3,200 👁850,000 · [原文](url)
```

**GitHub 项目**（额外展示语言和 Stars）：
```markdown
- **项目名: 一句话功能描述**
  关键词: k1 | k2 · Python · ⭐19,716 · [原文](url)
```

#### 日报整体结构

```markdown
# AI 日报 — 2026-04-13

> 共 45 条资讯 | 覆盖 6 个领域 + Twitter + GitHub

---

## AI通用技术/模型

> **洞察**: 今日多家大厂发布新模型...

- **OpenAI发布GPT-5，多模态能力全面超越前代**
  关键词: GPT-5 | 多模态 · 04-13 · [原文](url)
- ...

---

## Twitter 热门

> **洞察**: 开发者社区热议...

- ...

---

## GitHub 热门项目

> **洞察**: 本周Agent框架和推理优化项目霸榜...

- ...
```

#### 板块配置（config.yaml → editor）

```yaml
editor:
  # 顺序决定双标签文章归属优先级：垂直领域优先于 ai_core
  sections:
    - tag: ai_agent
      title: "AI Agent"
    - tag: ai_video
      title: "AI视频"
    - tag: ai_gaming
      title: "AI游戏"
    - tag: ai_social
      title: "AI社交"
    - tag: ai_core
      title: "AI通用技术/模型"
    - tag: ai_product
      title: "其他值得关注的产品"
    - tag: ai_business
      title: "AI行业动态"
  opinion_section:
    title: "行业观点"
    max_items: 3
  twitter_section:
    title: "Twitter 热门"
    max_items: 10
  github_section:
    title: "GitHub 热门项目"
    max_items: 10
```

---

### 3.4 Layer 4: 归档（archiver.py）

> **职责**：日报发布后的知识沉淀和长期存储
> **原则**：将一次性日报转化为可检索的知识资产

#### 输入

- `data/{date}/daily.md`
- `data/{date}/filtered.json`

#### 输出

- `data/{date}/archived.json` — 归档记录（带元信息标注）
- `knowledge_base/` — 知识沉淀（长期积累）

#### 处理步骤

##### Step 1: 归档记录

将当日文章的元信息（标题、URL、分类、AI 摘要、评分）写入 `archived.json`，作为长期索引。

##### Step 2: 知识沉淀

从高分文章中提取关键信息，按主题分类存入 `knowledge_base/`：
- 关键技术/模型发布的时间线
- 行业趋势追踪
- 重要融资/并购事件

##### Step 3: 数据清理

- 30 天前的 `raw.json` 可自动清理（节省空间）
- `filtered.json` 和 `daily.md` 永久保留
- `knowledge_base/` 永久保留

---

## 四、全局配置（config.yaml）

合并原来的 `sources.yaml`，扩展为全局配置：

```yaml
# ═══════════════════════════════════════════
# AI Daily News — 全局配置
# ═══════════════════════════════════════════

# ── 全局参数 ──
global:
  project_name: "AI Daily News"
  data_dir: "./data"
  manual_input_dir: "./manual_input"
  log_level: "INFO"

# ── Layer 1: 收集配置 ──
collector:
  fetch_interval_minutes: 30
  request_timeout_seconds: 15
  max_retries: 2
  retry_delay_seconds: 5
  max_concurrent_fetches: 10
  max_entry_age_days: 2              # 只保留近 N 天内的文章
  # 信息源定义
  sources:
    rss: [...]         # RSS 订阅源（news/ai_companies/game_industry/vc_blogs/hn_blogs）
    github: [...]      # GitHub Trending / Search API / Blog
    exa_search: [...]  # Exa 搜索（无 RSS 兜底 + RSS 失效源迁移）
    twitter: [...]     # Twitter/X 搜索 + 重点账号
    wechat: [...]      # 微信公众号（36 个已订阅）

# ── Layer 2: 筛选配置 ──
filter:
  dedup_window_hours: 72
  title_similarity_threshold: 0.85
  # 三管道独立配额（替代旧的 quota_per_tag）
  pipeline_quotas:
    main:                               # 📰 主日报管道（rss/wechat/exa/manual）
      ai_core: 3
      ai_agent: 5
      ai_video: 5
      ai_gaming: 5
      ai_social: 5
      ai_product: 3
      ai_business: 3
    github:                             # 🐙 GitHub 管道
      ai_core: 2
      ai_agent: 3
      ai_video: 2
      ...
    twitter:                            # 🐦 Twitter 管道
      ai_core: 2
      ai_agent: 2
      ...
  quota_per_tag: {...}                  # 后备配额（pipeline_quotas 未配置的管道退化）
  default_quota: 5
  min_articles_warning: 3
  # LLM 轻筛
  llm_light_filter:
    enabled: true
    batch_size_denoise: 30
    batch_size_rescue: 50
    pipelines: [main]
  # 内容类型分类
  content_type:
    tech_product_bonus: 0.5
    opinion_penalty: -1.0
    vip_authors: [...]
    vip_sources: [...]
  # 渠道通行证（仅 manual）
  always_pass_channels:
    - manual
  # 质量控制门槛
  twitter_quality:
    min_heat: 50                        # 综合热度最低门槛
  github_quality:
    min_stars: 5                        # 最低 stars 门槛
  # 冷门保护
  cold_protection:
    enabled: true
    threshold_override: 2
    max_protected_per_day: 3
    protected_sources: ["Simon Willison", "Lilian Weng", ...]
    protected_tags: ["ai_core", "ai_gaming", "ai_agent"]
  # 双层关键词体系
  relevance_tags:
    ai_core: { priority: core, signals: [...], brands: [...] }
    ai_gaming: { ... }
    ai_video: { ... }
    ai_social: { ... }
    ai_agent: { ... }
    ai_product: { priority: supplementary, ... }
    ai_business: { priority: fyi, signals: [...], company_whitelist: [...] }
  source_weights: {...}                 # 仅用于去重选代表
  source_tiers: {...}                   # 源级别（official/media/aggregate）影响时效性衰减
  channel_weights: {...}                # 渠道默认权重
  engagement_thresholds: {...}          # 互动数据阈值
  url_strip_params: [...]               # URL tracking 参数清理

# ── Layer 3: 编辑配置 ──
editor:
  # LLM 工作由 CodeBuddy 在对话中完成，不依赖外部 API
  # Prompt 模板参见 layers/editor.py
  summary_max_length: 50
  # 主日报板块（按 relevance_tag 映射，固定顺序展示）
  sections:
    - tag: ai_core
      title: "AI通用技术/模型"
    - tag: ai_agent
      title: "AI Agent"
    - tag: ai_video
      title: "AI视频"
    - tag: ai_gaming
      title: "AI游戏"
    - tag: ai_social
      title: "AI社交"
    - tag: ai_product
      title: "其他值得关注的产品"
    - tag: ai_business
      title: "AI行业动态"
  # Twitter / GitHub 独立小节
  twitter_section:
    title: "Twitter 热门"
    max_items: 10
  github_section:
    title: "GitHub 热门项目"
    max_items: 10

# ── Layer 4: 归档配置 ──
archiver:
  raw_retention_days: 30
  knowledge_extraction: true
```

---

## 五、主调度器（pipeline.py）

```python
"""
主调度器：串联 4 层，支持从任意层开始。

用法：
    python pipeline.py                    # 完整运行 4 层
    python pipeline.py --from layer2      # 从 Layer 2 开始（使用已有 raw.json）
    python pipeline.py --only layer1      # 只运行 Layer 1
    python pipeline.py --date 2026-04-12  # 指定日期（重跑历史）
"""
```

关键设计点：
- **层间解耦**：每层只读取上一层的 JSON 文件，不直接调用上一层的函数
- **幂等性**：同一层对同一 date 多次运行，结果一致
- **断点续跑**：任何一层失败，修复后可从该层重跑，不需要重跑前面的层
- **手工输入**：`manual_input/` 中的文件在 Layer 1 运行时自动合入 raw.json

---

## 六、manual_input/ 人工输入

支持随时手动丢入文章，格式灵活：

```
manual_input/
├── article1.json          # JSON 格式（标准 RawArticle）
├── article2.md            # Markdown 格式（标题+链接+简介）
└── article3.txt           # 纯文本（一行一个 URL）
```

Layer 1 运行时会扫描此目录，解析后合入 raw.json，处理完成后移入 `manual_input/.processed/`。

---

## 七、与旧架构的映射

| 旧架构 | 新架构 | 变化 |
|--------|--------|------|
| Layer 1: 信息源配置 (sources.yaml) | **合并进 config.yaml** | 配置不再是独立层，而是 Layer 1 的输入参数 |
| Layer 2: 采集引擎 (Fetcher+Pipeline) | **拆分为 Layer 1 收集 + Layer 2 筛选** | 原来的采集和处理拆成了"只管拿"和"只管选" |
| Layer 3: AI 摘要/日报 (未实现) | **Layer 3: 编辑** ✅ | CodeBuddy 预生成 LLM 结果 + 三管道渲染 |
| _(无)_ | **Layer 4: 归档** | 新增，知识沉淀能力 |
| _(无)_ | **manual_input/** | 新增，支持人工输入 |
| _(无)_ | **pipeline.py 主调度器** | 新增，层间编排 + 断点续跑 |

---

## 八、关键设计决策

### Q1: 为什么用 JSON 文件而不是 SQLite 做层间通信？

- **可调试**：JSON 文件可直接查看、手动编辑，出问题时定位快
- **可重跑**：每层输出是确定性文件，断点续跑天然支持
- **版本化**：按日期组织，天然支持历史回溯
- **简单**：不需要维护数据库 schema，降低复杂度

> SQLite 仍可用于 Layer 2 去重（快速查询 URL hash），但不作为层间通信介质。

### Q2: 为什么把采集和筛选拆成两层？

- **职责单一**：Layer 1 只管"拿到数据"，Layer 2 只管"判断质量"
- **可独立运行**：采集失败不影响用已有数据做筛选
- **可插入人工**：manual_input 在 Layer 1 汇入，Layer 2 统一评判
- **可换方案**：筛选策略从规则升级到 LLM，只改 Layer 2

### Q3: knowledge_base 怎么用？

- Layer 4 自动从高价值文章中提取关键事实
- 按主题分类存储（模型发布时间线、行业趋势、融资事件等）
- 后续可供 Layer 3 参考（"上周我们报道过..."）
- 长期积累后可作为个人 AI 知识库

### Q4: 调度怎么做？

两种运行模式：
1. **定时模式**：通过系统 cron 或 CodeBuddy Automation 每天运行一次完整 pipeline
2. **手动模式**：通过命令行指定参数运行

建议先用手动模式开发调试，稳定后再配置自动化。

---

## 九、执行优先级

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P0** | config.yaml + pipeline.py 骨架 + Layer 1 collector.py | ✅ 已完成 |
| **P0** | Layer 2 filter.py (dedup + score + filter + LLM轻筛) | ✅ 已完成 |
| **P1** | Layer 1 补全 (Exa + Twitter + WeChat + Manual Fetcher) | ✅ 已完成 |
| **P1** | Layer 3 editor.py (LLM 结果加载 + 三管道渲染 + 日报生成) | ✅ 已完成 |
| **P2** | Layer 4 archiver.py (归档 + 知识沉淀) | ⏳ 待实现 |
| **P2** | 自动化调度 (Cron / Automation) | ⏳ 待实现 |

---

## 十、依赖清单

```txt
# Layer 1: 收集
feedparser>=6.0.11        # RSS/Atom 解析
exa-py>=1.1.0             # Exa 搜索 API（无 RSS 网站兜底）
httpx>=0.27.0             # 异步 HTTP 客户端（带超时/重试）
# Twitter/X 采集通过 xreach CLI（agent-reach skill），无需 Python 包

# Layer 2: 筛选
beautifulsoup4>=4.12.3    # HTML 清洗
python-dateutil>=2.9.0    # 日期解析

# Layer 3: 编辑（LLM 由 CodeBuddy 完成，不依赖外部 API）
# jinja2>=3.1              # 模板渲染（可选，当前未使用）

# Layer 4: 归档
# 无额外依赖

# 通用
pyyaml>=6.0.1             # YAML 配置解析
python-dotenv>=1.0.1      # 环境变量（.env 文件）
pydantic>=2.7.0           # 数据校验
rich>=13.7.0              # 美化终端输出
```

---

*初始设计：2026-04-13*
*最后更新：2026-04-16*
*Layer 1-3 已实现，Layer 4 待实现*
