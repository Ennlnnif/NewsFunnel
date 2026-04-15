# AI Daily News 📰

个人 AI 日报系统 — 自动聚合多渠道信息源，经筛选、编辑后生成每日 AI/游戏行业资讯日报。

## 四层架构

```
Layer 1: 收集 → Layer 2: 筛选 → Layer 3: 编辑 → Layer 4: 归档
```

| Layer | 模块 | 功能 | 输出 | 状态 |
|-------|------|------|------|------|
| **Layer 1** | `collector.py` | 从全渠道拉取原始信息 | `raw.json` | ✅ 已完成 |
| **Layer 2** | `filter.py` | 去重 + 关键词筛选 + LLM分类(quality+tag) + 评分 + 配额过滤 | `filtered.json` | ✅ 已完成 |
| **Layer 3** | `editor.py` | 全文抓取 + AI 摘要 + 日报生成 | `daily.md` | ✅ 已完成 |
| **Layer 4** | `archiver.py` | 归档 + 知识沉淀 | `archived.json` | ⬜ 待设计 |

> 详细设计文档：[docs/architecture.md](docs/architecture.md)

## 信息渠道（100+ 源）

- **RSS 订阅**：70+ 源（资讯媒体、AI 巨头博客、HN 热门博客、游戏引擎）
- **GitHub**：Trending（日/周）、Blog、Releases（按需）
- **Exa 搜索**：无 RSS 网站兜底 + 通用关键词搜索
- **Twitter/X**：热门推文搜索 + 重点账号追踪
- **微信公众号**：36 个号（通过 we-mp-rss 采集）
- **手工输入**：随时向 `manual_input/` 丢入文章

## 快速开始

```bash
# 1. 创建虚拟环境
cd ~/CodeBuddy/ai-daily
python3 -m venv .venv && source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env  # 编辑填入 API Key

# 4. 运行完整 pipeline
python pipeline.py

# 5. 从指定层开始（如只重跑筛选+后续）
python pipeline.py --from layer2

# 6. 只运行某一层
python pipeline.py --only layer1

# 7. 指定日期重跑
python pipeline.py --date 2026-04-12
```

## 目录结构

```
ai-daily-news/
├── config.yaml              # 全局配置（信息源、筛选规则、输出偏好）
├── pipeline.py              # 主调度器：串联 4 层，支持从任意层开始
├── layers/
│   ├── collector.py         # Layer 1: 收集
│   ├── filter.py            # Layer 2: 筛选
│   ├── editor.py            # Layer 3: 编辑
│   └── archiver.py          # Layer 4: 归档
├── data/                    # 运行时数据（按日期组织，gitignore）
│   └── {date}/
│       ├── raw.json         # Layer 1 输出 / Layer 2 输入
│       ├── filtered.json    # Layer 2 输出 / Layer 3 输入
│       ├── llm_filter_input.json   # LLM 分类候选（稳定哈希ID）
│       ├── llm_filter_results.json # LLM 分类结果（tag+quality）
│       ├── llm_results.json # Layer 3 摘要/关键词/洞察（含URL精确匹配）
│       ├── daily.md         # Layer 3 输出（Markdown 日报）
│       ├── debug/           # 全流程调试中间产物
│       └── archived.json    # Layer 4 归档记录
├── knowledge_base/          # Layer 4 沉淀的知识
├── manual_input/            # 人工添加的文章（任何时候丢进来）
├── docs/
│   └── architecture.md      # 架构设计文档
├── requirements.txt
├── .env.example
└── .gitignore
```

## 设计亮点

- **层间 JSON 解耦**：每层输出为独立文件，可断点续跑、可手动调试
- **支持手工输入**：随时向 `manual_input/` 丢入文章，Layer 1 自动合入
- **知识沉淀**：Layer 4 将日报转化为可检索的长期知识库
- **灵活调度**：命令行支持指定层、指定日期，方便开发和运维
