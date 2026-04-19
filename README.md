# NewsFunnel 📰

> 个人 AI 日报系统 — 自动聚合多渠道信息源，经筛选、编辑后生成每日 AI/游戏行业资讯日报。

## 四层架构

```
Layer 1: 收集 → Layer 2: 筛选 → Layer 3: 编辑 → Layer 4: 归档
```

| Layer | 模块 | 功能 | 输出 | 状态 |
|-------|------|------|------|------|
| **Layer 1** | `collector.py` | 从全渠道拉取原始信息（RSS/GitHub/Exa/Twitter/微信/手工） | `raw.json` | ✅ 已完成 |
| **Layer 2** | `filter.py` | 去重 + 双层关键词筛选 + LLM分类(quality+tag) + 多维评分 + 配额过滤 | `filtered.json` | ✅ 已完成 |
| **Layer 3** | `editor.py` | 全文抓取 + AI 摘要 + 多板块日报渲染 | `daily.md` | ✅ 已完成 |
| **Layer 4** | `archiver.py` | 产品深度分析报告（多源信息采集 → 10模块结构报告） | `reports/{product}/{date}.md` | ✅ 已完成 |

> 详细设计文档：[docs/architecture.md](docs/architecture.md)

## 信息渠道（100+ 源）

| 渠道 | 数量 | 说明 |
|------|------|------|
| **RSS 订阅** | 30+ 源 | 资讯媒体、AI 巨头博客、HN 热门博客、游戏引擎 |
| **GitHub** | Trending + Search API + Blog | 日/周趋势 + 7 领域定向搜索近期新项目 |
| **Exa 搜索** | 8+ 站点 | 无 RSS 网站兜底 + RSS 失效源定向搜索 |
| **Twitter/X** | 搜索 + 5 重点账号 | 热门推文搜索 + 重点账号追踪（xreach CLI） |
| **微信公众号** | 29 个号 | 通过 we-mp-rss 本地服务采集 |
| **手工输入** | - | 随时向 `manual_input/` 丢入文章 |

## 快速开始

```bash
# 1. 创建虚拟环境
cd ~/CodeBuddy/ai-daily
python3 -m venv .venv && source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env  # 编辑填入 EXA_API_KEY 等

# 4. 运行完整 pipeline（Layer 1-3）
python pipeline.py

# 5. 从指定层开始（如只重跑筛选+后续）
python pipeline.py --from layer2

# 6. 只运行某一层
python pipeline.py --only layer1

# 7. 指定日期重跑
python pipeline.py --date 2026-04-12

# 8. Layer 4: 产品深度分析
python -m layers.archiver --list                    # 列出当天可选产品
python -m layers.archiver --product "Archon"        # 从日报选择产品
python -m layers.archiver --url "https://github.com/xxx"  # 手动输入链接
```

## 核心特性

### 筛选引擎（Layer 2）
- **双层关键词体系**：信号词（领域通用概念）+ 品牌词（具体产品名），自动覆盖未来新品
- **LLM 轻筛**：关键词主力 + LLM 去噪/捞漏，解决假阳性和假阴性
- **三管道独立评分**：主日报 / GitHub / Twitter 各自独立评分排序，互不干扰
- **事件级去重**：标题相似度 + 核心实体识别，同一事件跨管道只保留最优一篇
- **冷门保护**：优质源 / 核心标签的低热度文章受保护，防止好内容被淘汰

### 日报生成（Layer 3）
- **全文摘要**：通过 web_fetch 抓取原文全文后生成摘要，而非仅靠标题
- **summary 硬约束**：15-80 字中文、必须含产品名、禁堆砌数字、what+so what
- **7 垂直板块**：AI Agent / AI视频 / AI游戏 / AI社交 / AI通用技术 / AI行业动态 / AI产品
- **独立板块**：Twitter 热门 / GitHub 热门趋势 / GitHub 新品发现 / 行业观点
- **防伪 URL 双重防线**：自动生成 URL 模板 + 编辑阶段校验

### 产品分析（Layer 4）
- **两种触发方式**：从日报选择产品 / 手动输入链接（GitHub/Twitter/Reddit/文章/图片）
- **10 模块结构报告**：速览 → 概览 → 投融资 → 核心功能 → 技术方案 → 版本迭代 → 商业模式 → 用户策略 → 竞争格局 → 行业趋势
- **按产品归档**：`data/reports/{product_name}/{date}.md`，同产品多次分析集中存储

## 日报板块

| 板块 | 标签 | 关注领域 |
|------|------|---------|
| AI Agent | `ai_agent` | AI 编程助手（Cursor/Copilot/Claude Code/Manus/Harness/Evolver/OpenClaw/CodeFuse NES 等）、自动化工作流、多 Agent 协作、Agent 游戏化社交；**例外**大厂官方 Agent 运行时重大里程碑（OpenAI Agents SDK / MS agent-framework / Google ADK / Anthropic Harness 的战略级更新） |
| AI视频 | `ai_video` | 文生视频、AI 短剧/动画/电影、视频生成模型、TTS/语音模型 |
| AI游戏 | `ai_gaming` | AI NPC、AI 关卡生成、AI Native 游戏、桌面宠物/助手、世界模型 |
| AI社交 | `ai_social` | AI 伴侣、角色扮演社交平台、融合 AI 的社交软件 |
| AI通用技术 | `ai_core` | 大模型发布/架构创新、开源模型（不含世界模型/TTS/具身智能/自动驾驶） |
| AI行业动态 | `ai_business` | 投融资/收购/IPO/营收、公司竞争策略 |
| AI产品 | `ai_product` | AI 办公/搜索/绘画/写作等其他 AI 应用 |
| 行业观点 | `opinion` | 个人观点/评论/行业展望（独立池，VIP优先） |
| Twitter 热门 | - | 按综合热度排序 |
| GitHub 热门趋势 | - | Trending Daily + Weekly，stars≥100 |
| GitHub 新品发现 | - | Search API，stars≥30 |

> ℹ️ **日报不再收录**：具身智能 / Physical AI / 人形机器人 / 自动驾驶类新闻；开源 Agent SDK / 框架的普通小版本更新（LangChain/CrewAI/Dify/AutoGen 等）。

## 目录结构

```
ai-daily/
├── config.yaml              # 全局配置（信息源、筛选规则、输出偏好）
├── pipeline.py              # 主调度器：串联 4 层，支持从任意层开始
├── layers/
│   ├── collector.py         # Layer 1: 收集（6 种 Fetcher）
│   ├── filter.py            # Layer 2: 筛选（去重+评分+LLM轻筛+配额）
│   ├── editor.py            # Layer 3: 编辑（LLM结果加载+多板块渲染）
│   ├── archiver.py          # Layer 4: 产品深度分析报告
│   └── report_template.md   # Layer 4: 报告 Prompt 模板
├── config/
│   └── sources.yaml         # 旧版信息源配置（已迁移至 config.yaml）
├── scripts/
│   ├── gen_llm_results_skeleton.py  # LLM 结果骨架生成（含 web_fetch 清单）
│   └── run_llm_light_filter.py      # LLM 轻筛重跑脚本
├── data/                    # 运行时产物与调试文件（gitignore）
│                            # 仅作为本地测试/验证/debug 中间产物，不是必须输出
│                            # 子目录按 {date}/ 组织：raw→filtered→llm_results→daily.md
├── knowledge_base/          # Layer 4 沉淀的知识
├── manual_input/            # 人工添加的文章
├── docs/
│   ├── architecture.md      # 架构设计文档（含完整变更记录）
│   ├── user-guide.md        # 跑测 SOP / 对话框模板
│                            # 每日变更日志外迁至 ~/.codebuddy/memory/{date}.md
├── AGENTS.md                # Agent 协作契约（趋于稳定）
├── requirements.txt
├── .env.example
└── .gitignore
```
## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| HTTP 客户端 | `httpx`（异步） | 多源并发采集，50+ 源 ~1 分钟 |
| RSS 解析 | `feedparser` | 兼容 RSS 1.0/2.0 和 Atom |
| Twitter 采集 | `xreach` CLI | 零配置、无需账号，含 views/bookmarks 数据 |
| Exa 搜索 | `exa-py` SDK | RSS 失效源定向搜索兜底 |
| 微信公众号 | `we-mp-rss` | 本地 Docker 服务，标准 RSS 接口 |
| LLM 工作 | CodeBuddy | 对话式完成摘要/分类/报告，无需外部 API Key |
| 定时调度 | macOS `launchd` | 支持睡眠后补跑，替代 crontab |

## 设计亮点

- **层间 JSON 解耦**：每层输出为独立文件，可断点续跑、可手动调试
- **支持手工输入**：随时向 `manual_input/` 丢入文章，Layer 1 自动合入
- **灵活调度**：命令行支持指定层、指定日期，方便开发和运维
- **RSS 失败自愈**：连续≥3天失败的 RSS 源自动降级为 Exa 永久替代
- **GitHub 持久化去重**：永久记录已入选 URL，防止老项目周期性涌入

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.3 | 2026-04-18 | 板块定义第五轮：剔除具身智能/Physical AI/人形机器人/自动驾驶；ai_agent 新增"大厂官方 Agent 运行时里程碑"例外条款；editor.py 四个 Prompt summary 字数统一为 15-80 字硬约束；AGENTS.md 和 user-guide.md 的 Layer 2 权威来源从不存在的 `prompt_template` 字段纠正为 `layers/filter.py` 的 `CLASSIFY_PROMPT` / `RESCUE_PROMPT` 常量 |
| v0.2 | 2026-04-17 | 初步跑通 Layer 1-4，新增产品分析报告、GitHub 管道拆分、防伪URL校验 |
| v0.1 | 2026-04-15 | 初始版本，初步跑通 Layer 1-3 |
