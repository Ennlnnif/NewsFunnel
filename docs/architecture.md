# NewsFunnel — 四层架构设计文档

> **项目名**：NewsFunnel（代码仓库：`ai-daily` / 历史名 `ai-daily-news`）
> **定位**：个人 AI 日报系统 —— 自动聚合多渠道信息源，经筛选、编辑后生成每日 AI / 游戏行业资讯日报 + 按需生成产品深度分析报告。

## 版本里程碑

| 里程碑 | 日期 | 标志性事件 |
|---|---|---|
| 架构定型 | 2026-04-13 | 从三层伪架构合并为真正的四层流水线；Layer 1 全部 6 种 Fetcher 完成 |
| Layer 3 完成 | 2026-04-14 | editor.py 完整工作流；summary 规范成文；LLM 工作统一由 CodeBuddy 完成 |
| Layer 4 完成 | 2026-04-16 | archiver.py 实现产品深度分析报告；10 模块结构；按产品归档 |
| 板块定义收敛 | 2026-04-18 | 板块第 5 轮收敛；summary 字数统一 15-80 字；Layer 2 权威来源指向修正 |
| Syncer 上线 | 2026-04-19 | Layer 4 新增 syncer.py；飞书多维表格索引 + GitHub 独立仓库存深度报告/日报 md |
| 开源化脱敏 | 2026-04-19 | 代码/文档全面移除个人凭证与硬编码路径；.env.example 为开源用户提供配置模板；run.sh 自动探测 Python 3.10+ |

> **演进史 / 中间形态 / 已废弃方案** 请看 [`docs/history/`](./history/README.md)
> **每日变更日志** 位于 `~/.codebuddy/memory/{YYYY-MM-DD}.md`（CodeBuddy Agent 全局记忆目录，跨项目共享，未随仓库提交）

---

## 一、整体架构

```
                        ┌────────────────────────────┐
                        │       pipeline.py          │
                        │  主调度器：串联 4 层        │
                        │  支持从任意层开始 / 单层重跑 │
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
   raw.json   filtered.json   daily.md     reports/{product}/   │
        │           ▲               ▲         {date}.md         │
        └───────────┘               │              │            │
                    └───────────────┘              │            │
                                    └──────────────┘            │
                                         ▲                      │
                                         └──────────────────────┘
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
  │  Layer 2    │     → data/{date}/llm_filter_input.json
  │  筛选       │     → data/{date}/llm_filter_results.json
  │             │     → data/{date}/llm_results_template.json
  │             │        去重 + 相关性评分 + LLM 去噪/捞漏 + 重要性过滤
  └──────┬──────┘
         ▼
  ┌─────────────┐     → data/{date}/llm_results.json (CodeBuddy 生成)
  │  Layer 3    │     → data/{date}/daily.md
  │  编辑       │        全文抓取 + LLM 摘要/关键词/洞察 + 多板块渲染
  └──────┬──────┘
         ▼
  ┌─────────────┐     → data/reports/{product}/{date}.md
  │  Layer 4    │     → knowledge_base/（预埋）
  │  归档       │        按产品触发深度分析报告（10 模块结构）
  └─────────────┘
```

### 设计原则

- **层间解耦**：每层只读取上一层的 JSON 文件，不直接调用上层函数
- **JSON 为层间契约**：可调试、可手动编辑、可断点续跑
- **幂等性**：同一层对同一 date 多次运行结果一致
- **渠道并行**：RSS/微信/Exa、GitHub、Twitter 三条管道在 Layer 2/3 全程独立

---

## 二、项目目录结构

```
ai-daily/（NewsFunnel）
├── config.yaml                     # 全局配置（信息源、筛选规则、输出偏好）
├── pipeline.py                     # 主调度器：串联 4 层，支持从任意层开始
├── layers/
│   ├── __init__.py
│   ├── collector.py                # Layer 1: 收集（6 种 Fetcher）
│   ├── filter.py                   # Layer 2: 筛选（去重+评分+LLM 轻筛+配额）
│   ├── editor.py                   # Layer 3: 编辑（LLM 结果加载+多板块渲染）
│   ├── archiver.py                 # Layer 4: 产品深度分析报告
│   └── report_template.md          # Layer 4: REPORT_PROMPT 模板
├── config/
│   └── sources.yaml                # 旧版信息源配置（已迁移至 config.yaml，保留作参考）
├── scripts/
│   ├── gen_llm_results_skeleton.py # LLM 结果骨架生成（含 web_fetch 清单）
│   └── run_llm_light_filter.py     # LLM 轻筛重跑脚本
├── data/                           # 运行时产物与调试文件（gitignore）
│   │                               # 仅作为本地测试/验证/debug 中间产物，不是必须输出
│   ├── {date}/                     # 按日期组织
│   │   ├── raw.json                # Layer 1 输出
│   │   ├── filtered.json           # Layer 2 输出
│   │   ├── llm_filter_input.json   # LLM 分类候选（稳定哈希 ID）
│   │   ├── llm_filter_results.json # LLM 分类结果（tag+quality）
│   │   ├── llm_results_template.json # Layer 3 URL 预填模板（防伪）
│   │   ├── llm_results.json        # Layer 3 摘要/关键词/洞察
│   │   ├── daily.md                # 最终日报
│   │   └── debug/                  # 可选调试产物（_collect_debug.py / layer2_debug.md 等）
│   ├── reports/{product}/{date}.md # Layer 4 产品分析报告
│   └── github_seen.json            # GitHub 持久化去重记录
├── knowledge_base/                 # Layer 4 沉淀的知识（跨日期持久化，预埋）
├── manual_input/                   # 人工添加的文章（随时丢入）
├── docs/
│   ├── architecture.md             # 本文（当前最新设计）
│   ├── user-guide.md               # 跑测 SOP / 对话框模板
│   ├── layer2-design.md            # 旧版 Layer 2 设计（归档参考）
│   ├── history/                    # 演进史 / 中间形态 / 已废弃方案
│   │   ├── README.md               # 演进时间线 + 6 个关键里程碑
│   │   ├── layer1-evolution.md
│   │   ├── layer2-evolution.md
│   │   ├── layer3-evolution.md
│   │   └── deprecated.md
│   └── image/                      # 文档图片
│
│   # 注：每日变更日志不在仓库内，位于 ~/.codebuddy/memory/{YYYY-MM-DD}.md
│   #     （CodeBuddy Agent 全局记忆目录，跨项目共享）
├── AGENTS.md                       # Agent 行为契约（硬约束边界）
├── README.md                       # 项目介绍 / 快速开始
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 三、各层详细设计

### 3.1 Layer 1: 收集（collector.py）

> **职责**：从所有渠道拉取原始信息，统一格式，输出 `raw.json`
> **原则**：只管"拿到"，不做任何筛选判断
> **状态**：✅ 已实现

#### 输入 / 输出

- **输入**：`config.yaml` 中的信息源配置 + `manual_input/` 目录
- **输出**：`data/{date}/raw.json`（今日所有采集到的文章列表）

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

#### 6 种 Fetcher

| Fetcher | 库 / 工具 | 技术方案 |
|---|---|---|
| **RSSFetcher** | `feedparser` + `httpx` | httpx 异步获取 → feedparser 解析；ETag/Last-Modified 条件请求；编码异常处理；无 pubDate 的 entry 直接跳过（避免历史全量灌入） |
| **GitHubFetcher** | `feedparser` + GitHub API | Trending RSS + Search API + Blog RSS；Trending 走 RSS 解析逻辑 + GitHub API 补充 `repo_created_at` / `stars` / `repo_language`；Search API 按 7 个兴趣领域定向搜索近 90 天新项目；采集层内 URL 级去重 |
| **ExaFetcher** | `exa-py` SDK | `exa.search_and_contents()`，按 `published_after` 过滤近 24h；定向站点搜索 + 通用关键词搜索；每条查询限 5 条；兜底 4 个 RSS 失效源（a16z / Rachel by the Bay / Dwarkesh Patel / Unreal Engine） |
| **TwitterFetcher** | `xreach` CLI | 搜索模式（`xreach search`）+ 用户时间线（`xreach tweets @user`）；`--json` 输出；`asyncio.create_subprocess_exec` 异步调用；无需账号 / API Key |
| **WeChatFetcher** | `we-mp-rss` 本地 HTTP API | 复用 RSSFetcher 逻辑，通过 `localhost:8001/feed/{mp_id}.rss` 访问本地服务 |
| **ManualFetcher** | 读本地文件 | 扫描 `manual_input/`，支持 JSON/MD/TXT 三种格式；处理完成后移入 `.processed/` 子目录 |

#### GitHub 管道细分（2026-04-16 起）

GitHub 管道拆分为两条子管道，独立评分和配额：

| 子管道 | 来源 | 门槛 |
|---|---|---|
| `github_trending` | Trending Daily + Weekly | stars ≥ 100 |
| `github_new` | Search API + Blog | stars ≥ 30 |

#### RSS 失败自愈

- `rss_fail_history.json` 记录每个源连续失败天数
- 连续 ≥ 3 天失败的源自动降级为 Exa 永久替代，不再发起 RSS 请求

#### 错误处理 & 并发控制

- 单源 15s 超时，最多重试 2 次（间隔 5s）
- 连续 5 次失败的源标记 `disabled`，每日凌晨重置
- 失败不阻塞其他源，记录到日志
- `asyncio.Semaphore(max_concurrent)` 控制并发数（默认 10），50+ 源 ~1 分钟

#### 数据存储策略

- `raw.json` 是**今日信息池**，每次运行 Layer 1 **全量覆盖**（非增量追加）
- 临时中间产物：`raw.json` / `filtered.json` / `llm_*.json` 保留最近 3 天自动清理
- 长期保留：`daily.md` / `data/reports/` / `knowledge_base/`

#### raw.json 示例

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

### 3.2 Layer 2: 筛选（filter.py）

> **职责**：对 `raw.json` 去重、相关性筛选、热度评分、过滤，输出高质量的 `filtered.json`
> **原则**：规则为主 + CodeBuddy 为辅。关键词硬筛是主力，LLM 仅用于边界情况去噪/捞漏；LLM 不可用时自动 fallback 到纯关键词筛选
> **架构**：三管道独立 —— RSS/微信/Exa、GitHub、Twitter 各自独立评分排序
> **权威来源**：`CLASSIFY_PROMPT` / `RESCUE_PROMPT` 常量在 `layers/filter.py` 内，**不在** JSON 里

#### 输入 / 输出

- **输入**：`data/{date}/raw.json` + `data/{date-1}/filtered.json` / `data/{date-2}/filtered.json`（去重窗口）
- **输出**：
  - `data/{date}/filtered.json`（最终入选文章）
  - `data/{date}/llm_filter_input.json`（LLM 分类候选）
  - `data/{date}/llm_filter_results.json`（LLM 分类结果）
  - `data/{date}/llm_results_template.json`（Layer 3 URL 预填模板，防伪第一重防线）

#### 处理流水线

```
raw.json (~4000+ 篇)
     │
     ▼
┌──────────────────┐
│ Step 1: Normalize│   统一时间格式、清理 HTML、URL 归一化、标题清洗
│                  │   N 篇 → N 篇（结构标准化）
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
│ 关键词硬筛（主力）     │   + 渠道通行证（manual 直接通过）
│                       │   命中标签 → 标记 relevance_tags
│                       │   → keyword_passed (~200 篇)
│                       │   → keyword_rejected (~3800 篇)
└────────┬──────────────┘
         ▼
┌───────────────────────┐
│ Step 3b: LLM 去噪     │   CLASSIFY_PROMPT 复核低置信度命中
│ （关键词假阳性）       │   仅品牌词单词命中 + 非标题命中 → LLM 判断
│                       │   同时打 quality 0-3 分 + primary_tag
└────────┬──────────────┘
         ▼
┌───────────────────────┐
│ Step 3c: LLM 捞漏     │   RESCUE_PROMPT 扫描被拒文章
│ （关键词假阴性）       │   预过滤（触发词 loose_trigger_names）缩小范围
│                       │   识别间接表达的 AI 相关文章
│                       │   新增 dup_of 检查防止重复报道被捞回
└────────┬──────────────┘
         ▼
┌───────────────────────┐
│ Step 3.5: Split       │   按渠道分流为三条独立管道
│                       │   RSS/微信/Exa/manual → 主日报管道
│                       │   GitHub → GitHub 管道（分 trending/new 子管道）
│                       │   Twitter → Twitter 热议管道
└────────┬──────────────┘
         ├──────────────────────────────────────────┐
         ▼                    ▼                      ▼
┌─── 📰 主日报管道 ───┐ ┌─ 🐙 GitHub 管道 ──┐ ┌─ 🐦 Twitter 管道 ─┐
│ Score: 四维度       │ │ Score: stars      │ │ Score: 热度       │
│  时效 3 + 覆盖 3    │ │  + 新项目加分     │ │  likes×1          │
│  + quality 1.5      │ │  + 主题相关性     │ │  + retweets×3     │
│  + 内容类型调整     │ │ 门槛: min_stars   │ │  + views×0.01     │
│ Filter:             │ │  trending≥100    │ │ 门槛: min_heat=50 │
│  pipeline_quotas    │ │  new≥30          │ │                   │
│  .main              │ │  pipeline_quotas │ │  pipeline_quotas  │
│                     │ │  .github         │ │  .twitter         │
│ 分流: opinion →     │ │                  │ │ 分流: opinion →   │
│  独立观点池         │ │                  │ │  独立观点池       │
└────────┬────────────┘ └────────┬──────────┘ └────────┬──────────┘
         │                       │                      │
         └───────────────────────┴──────────────────────┘
                                 ▼
                     filtered.json
                     每篇文章带 output_section / primary_tag / quality
```

#### 核心机制

##### 双层关键词体系

| 层级 | 说明 | 示例 |
|---|---|---|
| **信号词 (signals)** | 描述领域的通用概念词，自动覆盖未来新品 | "AI 视频生成"、"大模型"、"agent framework" |
| **品牌词 (brands)** | 具体产品/公司/模型名，精确命中已知目标 | "Sora"、"DeepSeek"、"Cursor" |

- 两层 OR 关系：命中任意一个就算匹配
- 英文短词（≤ 4 字符纯 ASCII）用 `\b` 正则词边界，中文词和长英文词用 `in` 子串匹配
- 预编译所有正则，无运行时性能损耗

##### LLM 轻筛（方案 C）

> 详细设计与演进请看 [history/layer2-evolution.md §3](./history/layer2-evolution.md)

- **Step 3b 去噪**：`CLASSIFY_PROMPT`（在 `layers/filter.py` 中）对低置信度命中做 batch 复核；同时打 quality 0-3 分 + primary_tag
- **Step 3c 捞漏**：`RESCUE_PROMPT` 对被拒文章做 batch 标题扫描；预过滤用 `loose_trigger_names`（Sam Altman / 微软 / 英伟达 等）缩小范围
- **LLM 实现**：CodeBuddy 在对话中完成，不依赖任何外部 API Key
- **ID 稳定化**：候选 ID 为基于标题的 sha256 哈希（如 `c81c67417`），重跑时不漂移
- **单标签 + quality**：每篇文章一个 `primary_tag` + quality 0-3 维度（替代旧的"多标签加成"）

##### 板块定义（第 5 轮收敛 ✅ 当前）

| 标签 | 关注领域 | 优先级 | 主日报配额 |
|---|---|---|---|
| `ai_core` | AI 核心技术：大模型发布/架构创新/训练推理/开源模型/模型能力变化。**不含**：芯片硬件/AI 安全合规/纯数学/具身智能/Physical AI/人形机器人/自动驾驶 | core | 5 |
| `ai_agent` | AI Agent 产品与架构：AI 编程助手（Cursor/Copilot/Claude Code/Manus/Harness/Evolver/OpenClaw/CodeFuse NES）、自动化工作流、多 Agent 协作、Agent 游戏化社交、AI 桌面助手；**例外**大厂官方 Agent 运行时重大里程碑（OpenAI Agents SDK / MS agent-framework / Google ADK / Anthropic Harness 的战略级更新 → q=2） | core | 10 |
| `ai_video` | AI 视频与影像生成：AI 视频生成模型（Sora/Vidu/Kling）、AI 短剧/动画/电影、文生视频、TTS/语音模型 | core | 5 |
| `ai_gaming` | AI + 游戏：AI NPC、AI 剧情生成、AI UGC 关卡编辑器、AI Native 游戏、**桌面宠物/AI 桌面助手**、世界模型 | core | 5 |
| `ai_social` | AI 社交产品（仅限具体产品）：融合 AI 的社交软件、AI 虚拟伴侣/角色扮演社交平台 | core | 5 |
| `ai_product` | 其他 AI 产品与应用（兜底板块）：AI 办公工具、AI 搜索 | supplementary | 3 |
| `ai_business` | AI 商业动态：投融资/收购/IPO/营收财报、公司竞争策略、AI 产品出海商业化 | supplementary | 3 |
| `opinion` | 观点与宏观洞察：个人观点/评论/行业展望、AI 宏观议题（伦理/治理/就业影响/孵化器生态等非产品类讨论） | independent | 3（独立池） |

> ℹ️ 日报不再收录：具身智能 / Physical AI / 人形机器人 / 自动驾驶类新闻；开源 Agent SDK / 框架的普通小版本更新（LangChain / CrewAI / Dify / AutoGen 等）。

##### 三管道独立配额（pipeline_quotas）

```yaml
pipeline_quotas:
  main:                    # 📰 主日报管道
    ai_core: 5
    ai_agent: 10
    ai_video: 5
    ai_gaming: 5
    ai_social: 5
    ai_product: 3
    ai_business: 3
  github:                  # 🐙 GitHub 管道
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

##### 热度评分

**主日报管道**（rss/wechat/exa/manual）—— 四维度（满分 8）：

```
总分 = 时效性(0-3.0) + 覆盖广度(0-3.0) + LLM quality(0-1.5)
     + 内容类型调整(tech_product:+0.5, opinion:+0.0, news:+0.0)
     + 优质源 bonus(0-0.5)
```

**覆盖广度评分**（跨渠道覆盖权重最高）：

| 条件 | 分数 |
|---|---|
| 3+ 渠道 or 5+ 源 or 6+ 报道 | 3.0 |
| 2 渠道 or 4+ 源 or 4+ 报道 | 2.5 |
| 3 源 or 3 报道 | 1.5 |
| 2 源 or 2 报道 | 0.5 |
| 单源 | 0.0 |

**quality 定义**：

| quality | 含义 | 评分加成 | 示例 |
|---|---|---|---|
| 3 | 重大 | +1.5 | 产品首发/技术突破/独家深度/重要开源/重大融资收购 |
| 2 | 常规 | +1.0 | 行业报告/公司动态/产品更新/技术解析/垂直周报 |
| 1 | 边缘 | +0.5 | 消费评测/泛科技/轻度相关；纯拼接聚合新闻（晚报/早报/速递） |
| 0 | 噪声 | +0.0 | 活动推广/榜单征集/申报/投票/招聘/广告 |

**quality=0 强制规则**：
- 标题含"申报""征集""报名""投票"等行动号召词 → 一律 q=0
- 垂直领域周报（如"AI 短剧周报"）聚焦单一主题的不受此规则影响

**GitHub / Twitter 管道** —— 保留互动数据维度（stars / likes 有真实数据）。

##### 质量控制门槛

| 管道 | 门槛 | 计算公式 |
|---|---|---|
| **Twitter** | `min_heat: 50` | `likes×1.0 + retweets×3.0 + views×0.01` |
| **GitHub (trending)** | `min_stars: 100` | 当前 star 总数 |
| **GitHub (new)** | `min_stars: 30` | 当前 star 总数 |

##### 冷门保护机制

优质源 / 核心标签的低热度文章受保护，降低通过阈值：

```yaml
cold_protection:
  enabled: true
  threshold_override: 2        # 受保护文章的通过阈值（正常核心是 4）
  max_protected_per_day: 3     # 每天最多保护 3 篇
  protected_sources:
    - "Simon Willison"
    - "Lilian Weng"
    - "Jay Alammar"
  protected_tags:
    - "ai_core"
    - "ai_gaming"
    - "ai_agent"
```

##### 事件级去重（配额选择阶段）

解决同一事件多篇报道同时入选的问题。在 `_select_by_tag_quota` 中检查：

```
候选文章 → 是否已有同事件入选？
           ├── 标题相似度 > 0.5 → 同事件，跳过
           ├── 共享核心实体关键词（≥ 4 字符，排除 Agent/Model/AI/大模型等通用词） → 同事件，跳过
           └── 无匹配 → 不同事件，正常入选
```

跨管道去重：main 管道入选的标题传递给 twitter 管道，同一事件不会在两个管道各入选一次。

##### 观点分流（独立板块）

opinion 文章**不降权**，从 main/twitter 管道分流到独立的观点池：

```
main/twitter 管道中的文章
       │
       ├── content_type != "opinion" → 正常参与标签配额竞争
       │
       └── content_type == "opinion" → 分流到观点池
                                        │
                                        ▼
                                   排序：VIP 优先 > 综合评分
                                   取 top-3 → 行业观点板块
```

VIP 作者：Sam Altman / Matthew Ball / Andrej Karpathy / Yann LeCun / Ben Thompson / Simon Willison / ...

##### 防伪 URL 第一重防线

- Layer 2 在 run_filter 结束时自动生成 `llm_results_template.json`
- URL 从 `filtered.json` 直接预填，不需要人工手写
- 下游 Layer 3 读取此模板，避免 URL 手写错误

#### filtered.json 示例

```json
{
  "date": "2026-04-13",
  "filtered_at": "2026-04-13T23:35:00+08:00",
  "stats": {
    "input": 4265,
    "after_dedup": 3800,
    "after_relevance": 200,
    "after_filter": 43,
    "by_section": {"main": 30, "github": 8, "twitter": 5},
    "by_tag_passed": {"ai_core": 5, "ai_agent": 8, "ai_gaming": 5, "ai_video": 5, "ai_social": 3, "ai_product": 3, "ai_business": 3}
  },
  "articles": [
    {
      "source_name": "OpenAI Blog",
      "channel": "rss",
      "title": "Introducing GPT-5",
      "url": "https://openai.com/blog/gpt-5",
      "published_at": "2026-04-13T18:00:00Z",
      "summary_clean": "...",
      "output_section": "main",
      "score": 7.5,
      "score_details": {"timeliness": 2.5, "coverage": 2.0, "quality": 1.5, "content_type": 0.5, "source_bonus": 0.0},
      "relevance_tags": ["ai_core"],
      "primary_tag_llm": "ai_core",
      "quality": 3,
      "is_duplicate": false,
      "coverage_count": 5,
      "filtered_out": false
    }
  ]
}
```

---

### 3.3 Layer 3: 编辑（editor.py）

> **职责**：读取 `filtered.json` + `llm_results.json`，按板块渲染 Markdown 日报
> **原则**：LLM 工作由 CodeBuddy 在对话中完成，不依赖外部 API
> **状态**：✅ 已实现

#### 输入 / 输出

- **输入**：
  - `data/{date}/filtered.json`（仅 `filtered_out=false` 的文章）
  - `data/{date}/llm_results_template.json`（Layer 2 预填 URL 模板）
  - `data/{date}/llm_results.json`（CodeBuddy 生成的摘要/关键词/洞察）
- **输出**：`data/{date}/daily.md` —— Markdown 格式日报

#### 工作流

```
CodeBuddy 对话                      editor.py 脚本
─────────────                        ────────────────
1. 读取 filtered.json                
2. 读取 llm_results_template.json    
   （URL 已预填）                    
3. 对每篇入选文章 web_fetch 原文     
4. 按 Prompt 模板生成 LLM 结果        
5. 写入 llm_results.json             
                                     6. 加载 filtered.json + llm_results.json
                                     7. _validate_llm_urls() URL 防伪校验
                                     8. 三管道分组（main/twitter/github）
                                     9. 逐板块渲染 Markdown
                                    10. 占位符拦截（__TODO__ / __MUST_FETCH__）
                                    11. 输出 daily.md
```

#### 四板块渲染架构

```
filtered.json 入选文章
       │
       ├── channel in (rss, wechat, exa, manual)
       │     ├── opinion → 💡 行业观点板块（VIP 优先 > 评分，top-3）
       │     └── 非 opinion → 📰 主日报（按 relevance_tag 分 7 个垂直板块）
       │
       ├── channel == twitter
       │     ├── opinion → 💡 行业观点板块（合并）
       │     └── 非 opinion → 🐦 Twitter 热门（按 score 降序，top-N）
       │
       └── channel == github → 🐙 GitHub 热门项目（按 stars 降序，top-N）
```

#### LLM 结果匹配机制

**匹配优先级**（解决旧顺序索引漂移问题）：
1. **URL 精确匹配**：`article.url == item.url`（最可靠）
2. **标题前缀匹配**：`article.title[:30] == item.title[:30]`（fallback）
3. **旧式顺序索引**：`int(item.id) - 1`（兼容旧格式）

#### 4 个 Prompt 模板

| Prompt | 适用场景 | 特殊规则 |
|---|---|---|
| `SECTION_PROMPT` | 主日报 7 个垂直板块 | 强制结构 `[主体]+[动作]+[结果]` |
| `TWITTER_PROMPT` | Twitter 推文 | 额外展示热度数据 🔁views |
| `GITHUB_PROMPT` | GitHub 项目 | 优先读 README.md 无需逐行源码；必须以项目名开头 |
| `OPINION_PROMPT` | 行业观点板块 | VIP 作者优先；侧重 why/how |

#### Summary 写作规范（四个 Prompt 共性）

| 维度 | 要求 |
|---|---|
| **字数** | **15-80 字硬约束**（下限防碎片，上限像新闻副标题） |
| **结构** | `[主体] + [做了什么] + [关键结果]` |
| **具体性** | 必须出现具体产品名/公司名/人名，禁止模糊表述 |
| **反重复** | 一句话中不得用不同措辞说同一件事 |
| **反渲染** | 删掉"全面突围""标志着""引爆市场"等空洞修饰 |
| **全文阅读** | ⚠️ 强制要求 web_fetch 原文后再生成，不靠标题推测 |
| **语言** | 所有英文 summary 必须翻译为中文 |
| **与关键词的关系** | 互补不重叠 —— keywords 承载实体名，summary 聚焦事件动态 |

**好的示例**：
- ✅ "OpenAI 发布 Codex CLI 0.4，开源 AGENTS.md 规范并统一 Cursor / Claude Code 等多客户端上下文"（36 字）
- ✅ "蚂蚁 CodeFuse 推出 NES 模式（Next Edit Suggestion），不等 Tab 就主动推荐下一步编辑，对标 Cursor 预测编辑"（51 字）
- ✅ "Anthropic 发布 Claude Design：把设计师的 UI 草图直接翻译为可运行组件并同步到 Figma"（45 字）

**反例**（字数超 / 堆砌 / 渲染过度）：
- ❌ "Anthropic 获取 70% 新增企业客户，Claude 推出灵魂校准对齐策略，从工程师口碑到企业信任全面突围"

#### 防伪双重防线

- **第一重**（Layer 2）：`filter.py` 自动生成 `llm_results_template.json`，URL 预填
- **第二重**（Layer 3）：`editor.py` 的 `_validate_llm_urls()` 校验 LLM 结果 URL 与 filtered.json 一致，不匹配则报错终止

#### 占位符拦截（C1）

三个 `_render_*` 函数（`_render_main_article` / `_render_twitter_article` / `_render_github_article`）中增加占位符检测：
- summary 含 `__TODO__` 或 `__MUST_FETCH__` 时 fallback 到 title
- 打印 `[C1]` warning
- 防止占位符渲染到日报

#### Markdown 渲染格式

**主日报 / 行业观点文章**：
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

- ...

## AI Agent

> **洞察**: ...

- ...

---

## 行业观点

> **洞察**: ...

- ...

## Twitter 热门

- ...

## GitHub 热门项目

- ...
```

---

### 3.4 Layer 4: 归档（archiver.py）

> **职责**：对产品进行多信息源深度分析，产出策略级洞察报告
> **原则**：手动触发、按需运行；LLM 工作由 CodeBuddy 完成
> **状态**：✅ 已实现

#### 两种触发方式

**方式一：从日报选择产品**
```bash
python -m layers.archiver --list                      # 列出当天日报可选产品
python -m layers.archiver --product "Archon"          # 直接分析指定产品
python -m layers.archiver                             # 交互式选择
```

**方式二：手动输入链接**
```bash
python -m layers.archiver --url "https://github.com/xxx"              # GitHub
python -m layers.archiver --url "https://twitter.com/xxx/status/123"  # Twitter
python -m layers.archiver --url "https://techcrunch.com/xxx"          # 文章
python -m layers.archiver --url "https://reddit.com/r/xxx"            # Reddit
python -m layers.archiver --url "/path/to/image.png"                  # 图片
```

#### 工作流

```
用户触发（两种方式之一）
     │
     ▼
┌─────────────────────────┐
│ Step 1: 识别输入来源     │   从日报匹配 / URL 自动识别类型
│                         │   （GitHub / Twitter / Reddit / 文章 / 图片）
└──────┬──────────────────┘
       ▼
┌─────────────────────────┐
│ Step 2: 构建素材信息     │   提取产品名、初始元数据
│                         │   合并日报中该产品的所有文章
└──────┬──────────────────┘
       ▼
┌─────────────────────────┐
│ Step 3: 加载 Prompt     │   从 layers/report_template.md
│                         │   提取 REPORT_PROMPT 常量
└──────┬──────────────────┘
       ▼
┌─────────────────────────┐
│ Step 4: 生成输入骨架     │   素材填入 Prompt
│                         │   → data/{date}/llm_report_input.json
└──────┬──────────────────┘
       ▼
┌─────────────────────────┐
│ Step 5: CodeBuddy 工作   │   用户在对话中触发
│                         │   ① 多源信息采集（web_fetch / web_search）
│                         │   ② 生成 10 模块结构报告
└──────┬──────────────────┘
       ▼
┌─────────────────────────┐
│ Step 6: 报告归档         │   写入 data/reports/{product}/{date}.md
│                         │   头部带 YAML front matter（飞书迁移预埋）
└─────────────────────────┘
```

#### 报告结构：10 模块

报告 Prompt 定义在 `layers/report_template.md` 的 `REPORT_PROMPT` 段落：

| # | 模块 | 关键字段 |
|---|---|---|
| ★ | **一句话速览** | 产品 + 最核心卖点 + 时间点 |
| 1 | **产品概览** | 产品名 / 所属赛道 / 成立时间 / 当前状态 / 创始团队 / 体验地址 |
| 2 | **投融资与资源背景** | 融资轮次 / 金额 / 投资方 / 估值 / 战略资源 |
| 3 | **核心功能** | 功能点 / 竞品差异点 |
| 4 | **技术方案** | 技术架构 / 技术壁垒 / 开源情况 / 开发者生态 |
| 5 | **版本迭代** | 里程碑时间线 / 迭代节奏 / 方向转变 / 路线图 |
| 6 | **商业模式与市场数据** | 商业模式 / 定价 / DAU-收入-增长 / 市场规模 |
| 7 | **用户需求与产品策略** | 用户画像 / 痛点 / 切入点 / 增长飞轮 / 定价合理性 |
| 8 | **竞争格局** | 赛道简述 / 竞品对比表 / 波特五力 / 行业结构判断 |
| 9 | **产品总结** | 核心优势 / 关键短板 / 机会窗口 / 潜在风险（含非技术壁垒：品牌/数据/生态等） |
| 10 | **行业趋势信号** | 相关方影响 / 趋势判断 / 后续节点 |

#### 链接类型识别

`_detect_source_type(url)` 根据 URL 特征自动识别：
- `github` — github.com 域名
- `twitter` — twitter.com / x.com 域名
- `reddit` — reddit.com 域名
- `image` — 扩展名在 IMAGE_EXTENSIONS 中（.png / .jpg / .jpeg / .gif / .webp / .bmp / .svg）
- `article` — 默认 fallback

#### 按产品归档

```
data/reports/
├── Archon/
│   ├── 2026-04-16.md
│   └── 2026-04-17.md
├── SuperClaude/
│   └── 2026-04-16.md
└── OpenClaw/
    └── 2026-04-18.md
```

**优点**：同产品多次分析集中存储，方便纵向追踪产品演进。

#### 飞书迁移预埋

报告头部自动包含 YAML front matter，为当前和未来的多维表格同步预留结构化元数据（已于 2026-04-19 由 `syncer.py` 实现自动同步）：

```yaml
---
product: Archon
date: 2026-04-16
source_mode: daily_report      # daily_report | manual_url
source_url: https://github.com/archon-ai/archon
source_type: github            # github | twitter | reddit | article | image
tags: [ai_agent, ai_core]
---
```

#### knowledge_base/ 预埋

`knowledge_base/` 目录保留用作未来：
- 从报告中提取关键事实
- 按主题分类存储（模型发布时间线、行业趋势、融资事件等）
- 长期积累后作为个人 AI 知识库

当前 Layer 4 尚未实现自动知识提取，预留接口。

---

### 3.5 Layer 4: 同步（syncer.py）

**职责**：把"已生成深度报告的产品"同步到飞书多维表格，同时把深度报告 md 和日报 md 存入独立 GitHub 仓库，表格里只记录 blob URL 作为索引。

#### 为什么拆一个独立仓库存报告

| 需求 | NewsFunnel 主仓库 | 报告仓库（独立 GitHub repo）|
|---|---|---|
| 版本追踪 | 代码/文档变更 | 每日产出（日报 + 深度报告）|
| 提交频率 | 低（几天/次） | 高（每日 + 每份报告）|
| 关注者 | 开发者（维护架构） | 内容读者（飞书表格跳转点击）|
| 仓库膨胀 | 逻辑代码，可控 | md 文件只增不减，长期 GB 级 |

**结论**：主仓库保持“代码/架构文档”职能不变；每日输出都走独立的报告仓库（通过 `.env` 中 `PRODUCT_ANALYSIS_OWNER` / `PRODUCT_ANALYSIS_REPO` 配置），避免历史被每日 md 淹没。

#### 三种同步模式

```bash
# 模式 1：产品同步（深度报告推 GitHub + 表格 create/update）
python -m layers.syncer --date 2026-04-18 --products "Archon, OpenClaw"

# 模式 2：仅更新已有记录的"深度报告"字段（其他字段不动）
python -m layers.syncer --date 2026-04-18 --update "Archon"

# 模式 3：仅推送日报 md 到 GitHub（不动飞书表格）
python -m layers.syncer --date 2026-04-18 --push-daily
```

#### 存储布局

```
<reports-repo>/                        # 独立 GitHub 仓库（本地 clone 在主仓库外）
├── 2026-04-18/
│   ├── daily.md                       # 当日日报（push-daily 触发）
│   ├── Archon.md                      # 产品深度报告（products 触发）
│   └── OpenClaw.md
└── 2026-04-19/
    └── ...
```

飞书表格「深度报告」列写入：
`https://github.com/{owner}/{repo}/blob/{branch}/{date}/{product}.md`

#### 幂等与字段写入契约

- **稳定 ID** = `md5(产品名 + 原文url)[:16]`，命中即 update，未命中即 create
- **受管字段白名单**：`产品名 / 日期 / 板块 / 一句话简讯 / 关键词 / 原文链接 / 深度报告 / 稳定ID`
  - 表格上手工维护的字段（如「进度」「备注」）和系统字段（如「创建时间」）**永不触碰**
  - 隐藏字段不影响 API 读写，表格视图层隐藏 OK

#### 降级策略

| 情形 | 行为 |
|---|---|
| 深度报告 md 不存在 | 对应字段留空，其他字段照常同步 |
| GitHub push 失败 | 打印 warning，跳过深度报告字段，其他字段照常写入 |
| LLM 字段（summary/keywords）缺失 | 留空，不中断 |
| 飞书 token 失效（401） | 自动刷新一次；再失败则整体报错 |

---

## 四、全局配置（config.yaml）

```yaml
# ═══════════════════════════════════════════
# NewsFunnel — 全局配置
# ═══════════════════════════════════════════

# ── 全局参数 ──
global:
  project_name: "NewsFunnel"
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
  max_entry_age_days: 2
  sources:
    rss: [...]         # RSS 订阅源（news/ai_companies/game_industry/vc_blogs/hn_blogs）
    github: [...]      # GitHub Trending / Search API / Blog
    exa_search: [...]  # Exa 搜索（无 RSS 兜底 + RSS 失效源迁移）
    twitter: [...]     # Twitter/X 搜索 + 重点账号
    wechat: [...]      # 微信公众号（通过 we-mp-rss）

# ── Layer 2: 筛选配置 ──
filter:
  dedup_window_hours: 72
  title_similarity_threshold: 0.85
  # 三管道独立配额
  pipeline_quotas:
    main:    {ai_core: 5, ai_agent: 10, ai_video: 5, ai_gaming: 5, ai_social: 5, ai_product: 3, ai_business: 3}
    github:  {ai_core: 2, ai_agent: 3,  ai_video: 2, ai_gaming: 2, ai_social: 2, ai_product: 1, ai_business: 1}
    twitter: {ai_core: 2, ai_agent: 2,  ai_video: 1, ai_gaming: 1, ai_social: 1, ai_product: 1, ai_business: 1}
  quota_per_tag: {...}       # 后备配额（pipeline_quotas 未配置的管道退化）
  default_quota: 5
  # LLM 轻筛
  llm_light_filter:
    enabled: true
    batch_size_denoise: 30
    batch_size_rescue: 50
    pipelines: [main]
  # 内容类型分类
  content_type:
    tech_product_bonus: 0.5
    opinion_penalty: 0.0       # 不再降权，改为分流
    vip_authors: [...]
    vip_sources: [...]
  # 渠道通行证
  always_pass_channels:
    - manual
  # 质量控制门槛
  twitter_quality:
    min_heat: 50
  github_quality:
    trending_min_stars: 100
    new_min_stars: 30
  # 冷门保护
  cold_protection:
    enabled: true
    threshold_override: 2
    max_protected_per_day: 3
    protected_sources: ["Simon Willison", "Lilian Weng", "Jay Alammar"]
    protected_tags: ["ai_core", "ai_gaming", "ai_agent"]
  # 双层关键词体系
  relevance_tags:
    ai_core:     {priority: core, signals: [...], brands: [...]}
    ai_agent:    {priority: core, signals: [...], brands: [...]}
    ai_video:    {priority: core, signals: [...], brands: [...]}
    ai_gaming:   {priority: core, signals: [...], brands: [...]}
    ai_social:   {priority: core, signals: [...], brands: [...]}
    ai_product:  {priority: supplementary, ...}
    ai_business: {priority: supplementary, signals: [...], company_whitelist: [...]}
  source_weights: {...}       # 去重选代表
  source_tiers: {...}         # 源级别（official/media/aggregate）影响时效性衰减
  channel_weights: {...}      # 渠道默认权重
  url_strip_params: [...]     # URL tracking 参数清理

# ── Layer 3: 编辑配置 ──
editor:
  # Prompt 模板参见 layers/editor.py 中的 SECTION_PROMPT / TWITTER_PROMPT / GITHUB_PROMPT / OPINION_PROMPT
  summary_min_length: 15
  summary_max_length: 80
  sections:
    - {tag: ai_agent,    title: "AI Agent"}
    - {tag: ai_video,    title: "AI视频"}
    - {tag: ai_gaming,   title: "AI游戏"}
    - {tag: ai_social,   title: "AI社交"}
    - {tag: ai_core,     title: "AI通用技术/模型"}
    - {tag: ai_product,  title: "其他值得关注的产品"}
    - {tag: ai_business, title: "AI行业动态"}
  opinion_section:
    title: "行业观点"
    max_items: 3
  twitter_section:
    title: "Twitter 热门"
    max_items: 10
  github_section:
    title: "GitHub 热门项目"
    max_items: 10

# ── Layer 4: 归档配置 ──
archiver:
  # Prompt 模板参见 layers/report_template.md 中的 REPORT_PROMPT
  raw_retention_days: 30
  report_dir: "./data/reports"
```

---

## 五、主调度器（pipeline.py）

```python
"""
主调度器：串联 4 层，支持从任意层开始。

用法：
    python pipeline.py                    # 完整运行 Layer 1-3
    python pipeline.py --from layer2      # 从 Layer 2 开始（使用已有 raw.json）
    python pipeline.py --only layer1      # 只运行 Layer 1
    python pipeline.py --date 2026-04-12  # 指定日期（重跑历史）

Layer 4 不在 pipeline.py 自动链路中，按需独立触发：
    python -m layers.archiver --product "Archon"
"""
```

### 关键设计点

- **层间解耦**：每层只读取上一层的 JSON 文件，不直接调用上一层的函数
- **幂等性**：同一层对同一 date 多次运行，结果一致
- **断点续跑**：任何一层失败，修复后可从该层重跑，不需要重跑前面的层
- **手工输入**：`manual_input/` 中的文件在 Layer 1 运行时自动合入 `raw.json`

### 调度方式

| 方式 | 工具 | 说明 |
|---|---|---|
| **定时** | macOS launchd | `com.niu.wechat-auto-fetch.plist` 每日 12:00 / 22:00 触发微信采集 |
| **手动** | `pipeline.py` CLI | Layer 1 / Layer 2 / Layer 3 完整链路；Layer 4 独立触发 |

> `com.niu.ai-daily-collector.plist` 已 unload（2026-04-17），Layer 1 改为手动触发，避免 LLM token 消耗。plist 文件保留，恢复命令：`launchctl load ~/Library/LaunchAgents/com.niu.ai-daily-collector.plist`。

---

## 六、手工输入（manual_input/）

支持随时手动丢入文章，格式灵活：

```
manual_input/
├── article1.json          # JSON 格式（标准 RawArticle）
├── article2.md            # Markdown 格式（标题 + 链接 + 简介）
└── article3.txt           # 纯文本（一行一个 URL）
```

Layer 1 运行时会扫描此目录，解析后合入 `raw.json`，处理完成后移入 `manual_input/.processed/`。

---

## 七、关键设计决策

### Q1: 为什么用 JSON 文件而不是 SQLite 做层间通信？

- **可调试**：JSON 文件可直接查看、手动编辑，出问题时定位快
- **可重跑**：每层输出是确定性文件，断点续跑天然支持
- **版本化**：按日期组织，天然支持历史回溯
- **简单**：不需要维护数据库 schema，降低复杂度

> SQLite 仍可用于 Layer 2 去重（快速查询 URL hash），但不作为层间通信介质。

### Q2: 为什么把采集和筛选拆成两层？

- **职责单一**：Layer 1 只管"拿到数据"，Layer 2 只管"判断质量"
- **可独立运行**：采集失败不影响用已有数据做筛选
- **可插入人工**：`manual_input/` 在 Layer 1 汇入，Layer 2 统一评判
- **可换方案**：筛选策略从规则升级到 LLM，只改 Layer 2

### Q3: 为什么 LLM 工作全部由 CodeBuddy 完成，而不走 API？

- **零配置**：不需要维护 `OPENAI_API_KEY` 等外部 API Key
- **成本可控**：CodeBuddy 主模型按对话会话计费，没有跑飞的风险
- **可审计**：对话全程可见，判断过程透明
- **可调试**：出问题时可以实时纠正 LLM 判断，而不是等一轮跑完才发现

> 代价：需要用户发起对话触发，不能 100% 自动化。当前仅 Layer 1 的数据采集是全自动的。

### Q4: 为什么 Layer 4 不进 pipeline.py 自动链路？

- **Layer 4 是按需分析**：不是每天都需要生成产品深度报告
- **产品选择是用户决策**：自动分析会产生大量低价值报告
- **触发成本高**：10 模块报告 LLM 调用成本远超日报，不适合每日跑

---

## 八、变更日志与历史索引

### 每日变更日志

位于 `~/.codebuddy/memory/{YYYY-MM-DD}.md`（CodeBuddy Agent 全局记忆目录，**不随仓库提交**），按日期组织。每天完成 > 3 处改动的会话后，建议在此留痕；跨项目共享记忆便于 Agent 回溯上下文。

### 演进史与中间形态

位于 [`docs/history/`](./history/README.md) 目录：

| 文档 | 内容 |
|---|---|
| [`history/README.md`](./history/README.md) | 演进时间线 + 6 个关键里程碑 |
| [`history/layer1-evolution.md`](./history/layer1-evolution.md) | Layer 1 演进（twikit→xreach / RSS→Exa / Trending 日期修复 / launchd 迁移等） |
| [`history/layer2-evolution.md`](./history/layer2-evolution.md) | Layer 2 演进（10 次改进 / LLM 轻筛方案 C / quota 演进 / 板块 5 轮 / 冷门保护 / 事件级去重等） |
| [`history/layer3-evolution.md`](./history/layer3-evolution.md) | Layer 3 演进（URL 匹配机制 / summary 规范 4 轮迭代 / 4 个 Prompt 独立化等） |
| [`history/deprecated.md`](./history/deprecated.md) | 已废弃/已替代的方案（twikit / API 自动调用 / 单一 quota_per_tag / 观点降权策略 / prompt_template 字段等） |

---

## 九、依赖清单

```txt
# Layer 1: 收集
feedparser>=6.0.11        # RSS/Atom 解析
exa-py>=1.1.0             # Exa 搜索 API
httpx>=0.27.0             # 异步 HTTP 客户端
# Twitter/X 采集通过 xreach CLI，无需 Python 包

# Layer 2: 筛选
beautifulsoup4>=4.12.3    # HTML 清洗
python-dateutil>=2.9.0    # 日期解析

# Layer 3: 编辑（LLM 由 CodeBuddy 完成，不依赖外部 API）

# Layer 4: 归档（LLM 由 CodeBuddy 完成，不依赖外部 API）

# 通用
pyyaml>=6.0.1             # YAML 配置解析
python-dotenv>=1.0.1      # 环境变量
pydantic>=2.7.0           # 数据校验
rich>=13.7.0              # 美化终端输出
```

---

*初始设计：2026-04-13*
*最后更新：2026-04-19*
*Layer 1-4 已实现；板块定义第 5 轮收敛完成；已完成开源化脱敏*