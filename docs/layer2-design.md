# ⚠️ 已弃用 — 请参阅 [architecture.md](architecture.md)

> 本文档为 2026-04-12 的原始 Layer 2 设计。
> 2026-04-13 架构重构后，Layer 1（配置）+ Layer 2（采集引擎）已合并拆分为新的四层流水线。
> 新架构设计文档：**docs/architecture.md**

---

# Layer 2 设计文档 - 采集引擎（原始版本，仅供参考）

> **目标**：将 Layer 1 定义的全部信息源（RSS / GitHub / Exa / Twitter / 微信）统一拉取、清洗、去重、存入本地数据库，为 Layer 3（AI 摘要 & 日报生成）提供干净的原料。

---

## 一、整体架构

```
                         ┌─────────────────────────────┐
                         │     Scheduler (APScheduler)  │
                         │  每 30 分钟触发一次采集周期   │
                         └────────────┬────────────────┘
                                      │
                         ┌────────────▼────────────────┐
                         │      Orchestrator 编排器      │
                         │   读取 sources.yaml 配置      │
                         │   按渠道分发给各 Fetcher      │
                         └────────────┬────────────────┘
                                      │
              ┌───────────┬───────────┼───────────┬───────────┐
              ▼           ▼           ▼           ▼           ▼
        ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐
        │RSS Fetcher││GitHub   ││Exa       ││Twitter   ││WeChat    │
        │feedparser ││Fetcher  ││Fetcher   ││Fetcher   ││Fetcher   │
        │          ││(RSS同)  ││exa-py SDK││agent-    ││we-mp-rss │
        │          ││         ││          ││reach/API ││本地 API   │
        └────┬─────┘└────┬────┘└────┬─────┘└────┬─────┘└────┬─────┘
             │           │          │           │           │
             └───────────┴──────────┼───────────┴───────────┘
                                    ▼
                         ┌────────────────────────┐
                         │    Pipeline 数据管道     │
                         │  normalize → dedup →    │
                         │  classify → store       │
                         └────────────┬───────────┘
                                      ▼
                         ┌────────────────────────┐
                         │   SQLite (articles.db)  │
                         │   统一文章存储 + 元信息   │
                         └────────────────────────┘
```

---

## 二、核心模块设计

### 2.1 Fetcher 层（各渠道采集器）

每个 Fetcher 负责一个渠道的数据拉取，输出统一的 `RawArticle` 数据结构。

#### RawArticle 通用数据模型

```python
@dataclass
class RawArticle:
    """各 Fetcher 统一输出的原始文章结构"""
    # ── 必填字段 ──
    source_name: str        # 信息源名称（如 "36氪"、"OpenAI Blog"）
    channel: str            # 渠道标识：rss / github / exa / twitter / wechat
    title: str              # 文章标题
    url: str                # 原文链接（用于去重的主键之一）
    fetched_at: datetime    # 采集时间

    # ── 可选字段（各渠道能力不同） ──
    published_at: datetime | None = None   # 原文发布时间
    author: str | None = None              # 作者
    summary: str | None = None             # 原文摘要/description（RSS 自带）
    content: str | None = None             # 全文内容（如果能拿到）
    category: str | None = None            # 分类标签（来自 sources.yaml）
    language: str | None = None            # 语言（zh / en）
    extra: dict | None = None              # 渠道特有字段（如 GitHub stars、Twitter likes）
```

#### 各 Fetcher 实现要点

| Fetcher | 库/工具 | 输入 | 特殊处理 |
|---------|---------|------|---------|
| **RSSFetcher** | `feedparser` | RSS/Atom URL | 解析 entry.published、entry.summary；处理编码异常；支持条件请求（ETag/Last-Modified）节省带宽 |
| **GitHubFetcher** | 复用 RSSFetcher | Trending/Blog/Releases 的 RSS URL | Trending 条目提取 repo 名+描述+stars；Releases 条目提取版本号 |
| **ExaFetcher** | `exa-py` SDK | search_query 字符串 | 调用 `exa.search_and_contents()`，按 `published_after` 过滤近 24h 内容；每条查询限 5 条结果 |
| **TwitterFetcher** | `agent-reach` Skill 或 Twitter API v2 | search query + 账号列表 | 按 min_faves 过滤；提取推文文本 + 引用链接；注意速率限制 |
| **WeChatFetcher** | `we-mp-rss` 本地 HTTP API | 本地 RSS 端点 | 调用 `http://localhost:3000/feeds/{biz_id}`；复用 RSSFetcher 逻辑 |

#### 错误处理与重试策略

```python
class FetchResult:
    """每个源的采集结果"""
    source_name: str
    status: Literal["success", "partial", "failed"]
    articles: list[RawArticle]
    error: str | None = None
    retry_count: int = 0
```

- **超时**：单源 15s 超时，超时后标记 `failed` 并记录
- **重试**：最多 2 次，间隔 5s（指数退避可选）
- **熔断**：连续 5 次失败的源自动标记为 `disabled`，下次采集跳过，每天凌晨重置

### 2.2 Pipeline 层（数据管道）

采集回来的 `RawArticle` 经过四步处理：

```
RawArticle[] ──→ normalize ──→ dedup ──→ classify ──→ store ──→ Article[]
```

#### Step 1: Normalize（标准化）

- 统一时间格式为 UTC `datetime`
- 清理 HTML 标签（`summary`/`content` 字段）→ 纯文本
- URL 归一化：去掉 tracking 参数（`utm_*`、`ref`、`source` 等）
- 标题清理：去掉首尾空白、重复空格

#### Step 2: Dedup（去重）

**两级去重策略**：

1. **URL 精确去重**：归一化后的 URL 在 72h 窗口内唯一
2. **标题模糊去重**：同一 72h 窗口内，标题相似度 ≥ 0.85 视为重复
   - 使用 `difflib.SequenceMatcher` 计算（轻量、无额外依赖）
   - 标记为 `is_duplicate=True`，保留首次出现的文章

#### Step 3: Classify（分类打标）

根据 `sources.yaml` 中的 `category` 字段 + 关键词匹配，为文章打上分类标签：

```python
CATEGORIES = [
    "AI模型/研究",      # 新模型发布、论文、benchmark
    "AI产品/应用",      # 产品上线、功能更新、商业化
    "AI开源/工具",      # GitHub 新项目、框架更新
    "AI行业/融资",      # 融资、并购、政策
    "游戏/引擎",        # 游戏行业、引擎更新
    "开发者/技术",      # 编程、工程实践
    "深度/观点",        # 长文分析、评论
]
```

- 初版用规则匹配（关键词 + 源分类），Layer 3 可升级为 LLM 分类

#### Step 4: Store（存储）

写入 SQLite 数据库，同时保存到每日 JSON 快照。

### 2.3 存储层（SQLite + 文件）

#### 数据库 Schema

```sql
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 核心字段
    url             TEXT NOT NULL,
    url_hash        TEXT NOT NULL,           -- URL 的 MD5 哈希（索引用）
    title           TEXT NOT NULL,
    -- 来源信息
    source_name     TEXT NOT NULL,
    channel         TEXT NOT NULL,           -- rss/github/exa/twitter/wechat
    category        TEXT,                    -- 分类标签
    language        TEXT DEFAULT 'en',       -- zh/en
    -- 内容
    author          TEXT,
    summary         TEXT,                    -- 原文摘要（清洗后纯文本）
    content         TEXT,                    -- 全文（如果有）
    -- 时间
    published_at    TIMESTAMP,               -- 原文发布时间
    fetched_at      TIMESTAMP NOT NULL,      -- 采集时间
    -- AI 处理结果（Layer 3 填充）
    ai_summary      TEXT,                    -- AI 生成的一句话摘要
    ai_category     TEXT,                    -- AI 重新分类
    ai_importance   INTEGER,                 -- AI 评分 1-5
    -- 状态
    is_duplicate    BOOLEAN DEFAULT FALSE,
    is_used         BOOLEAN DEFAULT FALSE,   -- 是否已用于日报生成
    -- 渠道特有数据
    extra           TEXT,                    -- JSON 格式
    -- 约束
    UNIQUE(url_hash)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_fetched_at ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_channel ON articles(channel);
CREATE INDEX IF NOT EXISTS idx_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_published_at ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_is_used ON articles(is_used);

-- 采集日志表（监控用）
CREATE TABLE IF NOT EXISTS fetch_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,            -- 本次采集周期 UUID
    source_name     TEXT NOT NULL,
    channel         TEXT NOT NULL,
    status          TEXT NOT NULL,            -- success/partial/failed
    articles_count  INTEGER DEFAULT 0,
    new_count       INTEGER DEFAULT 0,        -- 本次新增（去重后）
    error           TEXT,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP NOT NULL
);
```

#### 文件快照

每天 23:59 导出当日新增文章为 JSON 快照，方便调试和人工检查：

```
data/
├── articles.db                    # 主数据库
├── snapshots/
│   ├── 2026-04-12.json           # 每日快照
│   ├── 2026-04-13.json
│   └── ...
└── logs/
    └── fetch.log                  # 采集日志
```

### 2.4 调度层（Scheduler）

使用 `APScheduler` 做定时任务编排：

| 任务 | 频率 | 说明 |
|------|------|------|
| RSS + GitHub 采集 | 每 30 分钟 | 最高频，RSS 是实时性最好的渠道 |
| Exa 搜索 | 每 2 小时 | Exa API 有速率限制，降频 |
| Twitter 搜索 | 每 2 小时 | 同上，且热门推文变化较慢 |
| WeChat 采集 | 每 1 小时 | 依赖 we-mp-rss 本地服务 |
| 每日快照导出 | 每天 23:59 | 导出当日文章为 JSON |
| 数据库清理 | 每天 03:00 | 删除 30 天前的非重要文章 |

---

## 三、项目结构

```
ai-daily/
├── config/
│   └── sources.yaml              # Layer 1 信息源配置（已完成）
├── src/
│   ├── __init__.py
│   ├── main.py                   # 入口：启动调度器
│   ├── config.py                 # 配置加载器（解析 sources.yaml）
│   ├── models.py                 # 数据模型（RawArticle、Article、FetchResult）
│   ├── db.py                     # 数据库操作（初始化、CRUD、快照导出）
│   ├── fetchers/                 # Fetcher 层
│   │   ├── __init__.py
│   │   ├── base.py               # BaseFetcher 抽象基类
│   │   ├── rss_fetcher.py        # RSS/Atom 采集器（含 GitHub 复用）
│   │   ├── exa_fetcher.py        # Exa 搜索采集器
│   │   ├── twitter_fetcher.py    # Twitter/X 采集器
│   │   └── wechat_fetcher.py     # 微信公众号采集器（对接 we-mp-rss）
│   ├── pipeline/                 # Pipeline 层
│   │   ├── __init__.py
│   │   ├── normalize.py          # 标准化处理
│   │   ├── dedup.py              # 去重逻辑
│   │   └── classify.py           # 分类打标
│   └── scheduler.py              # 调度器配置
├── data/                         # 运行时数据（gitignore）
│   ├── articles.db
│   ├── snapshots/
│   └── logs/
├── tests/                        # 测试
│   ├── test_fetchers.py
│   └── test_pipeline.py
├── docs/
│   └── layer2-design.md          # 本文档
├── requirements.txt              # 依赖
├── .env.example                  # 环境变量模板
└── README.md
```

---

## 四、依赖清单

```txt
# 核心
feedparser>=6.0           # RSS/Atom 解析
exa-py>=1.0               # Exa 搜索 API
httpx>=0.27               # 异步 HTTP 客户端（替代 requests，支持 async）
apscheduler>=3.10         # 定时任务调度

# 数据处理
beautifulsoup4>=4.12      # HTML 清洗
python-dateutil>=2.9      # 日期解析

# 配置 & 工具
pyyaml>=6.0               # YAML 解析
python-dotenv>=1.0        # 环境变量
pydantic>=2.0             # 数据校验（可选，替代 dataclass）

# Twitter（二选一）
# tweepy>=4.14             # Twitter API v2（如果有 API Key）
# — 或通过 agent-reach Skill 调用，不需要额外依赖

# 日志
rich>=13.0                # 美化终端输出（可选）
```

---

## 五、关键设计决策

### Q1: 为什么用 SQLite 而不是 JSON 文件？

- 去重需要快速查询（URL hash 索引），JSON 全量加载太慢
- Layer 3 需要按日期/分类/频道灵活查询
- 单文件部署，不需要外部数据库服务
- 同时保留每日 JSON 快照，兼顾可读性

### Q2: 为什么用 httpx 而不是 requests？

- 原生 async 支持，多源并发采集效率高
- 50+ 源串行请求需要 ~12 分钟，并发可压缩到 ~1 分钟
- 向下兼容同步模式，可渐进式迁移

### Q3: Exa 和 Twitter 如何控制成本？

- Exa：每条查询限 5 条结果，每 2 小时采集一次，日调用 ~120 次（远低于免费额度 1000/月的限制，需确认具体额度）
- Twitter：优先使用 agent-reach Skill（免费），降级方案为 Twitter API v2 Basic（$100/月，读取量足够）

### Q4: we-mp-rss 怎么对接？

- we-mp-rss 本地运行在 `localhost:3000`
- 每个公众号有独立 RSS 端点，复用 RSSFetcher 逻辑
- 采集前检查 we-mp-rss 服务是否在线，离线则跳过微信渠道并告警

### Q5: 如何处理 RSS 条件请求（节省带宽）？

- 首次请求正常拉取，记录响应的 `ETag` 和 `Last-Modified` 头
- 后续请求携带 `If-None-Match` / `If-Modified-Since`
- 收到 `304 Not Modified` 则跳过解析，直接返回空列表
- 存储在 `fetch_state` 表中：

```sql
CREATE TABLE IF NOT EXISTS fetch_state (
    source_url      TEXT PRIMARY KEY,
    etag            TEXT,
    last_modified   TEXT,
    last_fetched_at TIMESTAMP
);
```

---

## 六、执行优先级

| 阶段 | 内容 | 预估工作量 |
|------|------|-----------|
| **P0** | `models.py` + `db.py` + `config.py` — 数据模型和存储基础 | 小 |
| **P0** | `rss_fetcher.py` — RSS 是主力渠道（覆盖 70+ 源 + GitHub + 微信） | 中 |
| **P0** | `pipeline/` — normalize + dedup + classify 三步管道 | 中 |
| **P1** | `exa_fetcher.py` — Exa 搜索兜底 | 小 |
| **P1** | `scheduler.py` + `main.py` — 调度器和入口 | 小 |
| **P2** | `twitter_fetcher.py` — Twitter 渠道 | 中（依赖 API 配置）|
| **P2** | `wechat_fetcher.py` — 微信渠道对接 | 小（复用 RSS）|

---

## 七、开发环境准备

```bash
# 1. 创建虚拟环境
cd ~/CodeBuddy/ai-daily
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 EXA_API_KEY 等

# 4. 初始化数据库
python -m src.db init

# 5. 测试单个 Fetcher
python -m src.fetchers.rss_fetcher --test

# 6. 启动完整采集
python -m src.main
```

---

*设计时间：2026-04-12*
*关联：Layer 1 (sources.yaml) → **Layer 2 (本文档)** → Layer 3 (AI 摘要 & 日报生成)*
