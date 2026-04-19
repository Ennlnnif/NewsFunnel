# AGENTS.md — AI Daily News 项目 Agent 协作契约

> 本文件定义 Agent（CodeBuddy / Claude Code / Cursor / Windsurf / Aider 等）
> 在本项目中的行为契约。
>
> **系统结构、运行方式**请读 [`README.md`](./README.md) 与源码本身；
> **跑测 SOP / 对话框模板**请读 [`docs/user-guide.md`](./docs/user-guide.md)。

---

## ⚠️ 核心约束（最高优先级，任何情况下不得违反）

### A. 文件读写边界

**禁止修改（只能读取）**：

- `layers/*.py` / `pipeline.py` / `config.yaml` / `config/` / `docs/`

**禁止读取或打印**：

- `.env`

**可自由读写**：

- `data/`（所有中间产物和输出文件）
- `manual_input/`（人工添加的文章）

> 若判断某个核心文件需要修改：**先停下，描述改动意图，等用户确认**。

### B. Prompt 模板是硬约束

两类"约束来源"具有与本文件同等强度：

1. `layers/filter.py` 里的 `CLASSIFY_PROMPT` / `RESCUE_PROMPT` 两个常量（Layer 2 轻筛约束，定义板块归属/质量分/去重/活动推广等硬规则）
2. `layers/editor.py` 里的 `SECTION_PROMPT` / `TWITTER_PROMPT` / `GITHUB_PROMPT` / `OPINION_PROMPT` 四个常量（Layer 3 写稿约束，虽然不被代码调用，但作为 Agent 的参考标准具有硬约束地位）

> 这两类常量都在 `layers/*.py` 里——A 节禁止 Agent **修改** 这些文件，但**读取**属于正当行为，且是执行 Layer 2/3 的前置条件。
> 过去版本错误指向 `data/{today}/llm_filter_results_template.json` 的 `prompt_template` 字段，实际该字段并不存在；权威来源统一为 `layers/*.py` 的 PROMPT 常量。

对这些约束中所有"≤N字 / 必须 / 禁止 / 不要"：

- **约束 > 信息完整度**：读全文是输入方式，字数/格式是输出规约，两者冲突时无条件守约束
- 多余信息一律归入 `keywords` 或舍弃，**禁止扩写 summary 超字数**
- 视为与本文件 A 节同等强度，违反等于修改了禁止修改的 `.py` 文件

### C. 禁止的辩解话术

以下借口**不构成违反约束的正当理由**：

- ❌ "信息太丰富装不下"
- ❌ "原文细节很多"
- ❌ "读者需要更多背景"
- ❌ "这条新闻特别重要"

信息装不进约束 = 归 keywords 或舍弃，**不是扩写 summary 的理由**。

---

## 🔒 强制自检协议

所有调用 LLM 填写 JSON 的步骤（Layer 2 轻筛、Layer 3 写稿），**提交前必须逐条通过**：

- [ ] **字数校验**：逐条 `len()` 检查 summary / 其他受限字段，超标立刻重写
- [ ] **禁止项校验**：对应约束源里每条"禁止 / 不要"条目逐条对照
- [ ] **格式校验**：JSON schema 与 template 完全一致，字段不增不减
- [ ] **完整性校验**：所有待填条目填完，无 `__TODO__` / 占位符残留

**自检未通过就写入文件 = 违反核心约束**，等同于修改了禁止修改的 `.py` 文件。

---

## 🔁 Layer 3 执行协议（最容易翻车的环节）

### 工作流强约束

- [ ] **先抓后写**：先遍历 `llm_results_template.json` 所有文章，按 channel 规则做完全部 web_fetch，统计成功/失败/命中兜底链；**再**开始写 summary
- [ ] **禁止交错**：不允许"抓一篇写一篇"的流程（前几篇认真读、后几篇因疲劳跳过，是本项目多次翻车的直接原因）

### 数据来源权威

Layer 3 的 channel 路由规则、抓取失败兜底链，**以 `layers/editor.py` 中的四个 PROMPT 常量为唯一权威来源**。本文件不再镜像抓取规则表，避免双份维护漂移。

读取这些 PROMPT 时关注：

- 每种 channel 的 `web_fetch` 必要性（禁止 / 必须 / 可选）
- 抓取失败的降级顺序（`content` 字段 → `summary` 字段 → 末尾标注"（基于摘要生成）"）
- 特殊源的避坑规则（如 `x.com` / `twitter.com` 的登录墙 → 直接用 Layer 1 已抓的 summary，禁止 web_fetch）

### 交付阈值

- 单次日报中带"（基于摘要生成）"标注的条目 **建议 ≤ 10%**（24 条里不超过 2-3 条）
- 超过阈值：**回 Terminal 报告当日抓取失败清单，等待用户指示，禁止直接交付**

### 不允许的越界行为

- ❌ Layer 3 手动调用 Exa / 其他搜索引擎补抓正文（Exa 是 Layer 1 职责，Layer 3 不再二次抓取）
- ❌ 撞登录墙（x.com 等）后用"基于摘要生成"兜底（应直接走 channel=twitter 规则，用 Layer 1 已抓的 summary）
- ❌ 为了补足信息越过约束源的字数上限

### 板块归属不由 Agent 决定

Layer 3 template 已按板块 key 分组（`ai_agent` / `ai_core` / `twitter` / `github_trending` 等顶层 key），文章的归属在 Layer 2 由 `_primary_tag_llm` 决定好了。
**Agent 在 Layer 3 不需要判断 tag，只写 summary / keywords / insight。** 板块的定义本身以 `README.md` 的"日报板块"表和 `config.yaml` 的 `sections:` 段为准。

---

## 🤝 协作协议

### 用户交互原则

- 遇到不能靠工具自行解决的分歧 / 异常 / 判断题：**先在 Terminal 或对话框报告，等待用户指示**
- 用户已声明"不要修改 .py / .yaml 文件"时，即使认为修改能解决问题，也要**先描述方案等用户确认**
- 禁止自行创建文档文件（`*.md` / `README` 等），除非用户明确要求

### 日期处理（重要）

- Agent 没有可靠的"今天日期"工具，日期必须**由用户显式给出**
- 若用户只说"跑一次 daily"但未给日期：**先问，不要猜**
- 日期格式：ISO `YYYY-MM-DD`（如 `2026-04-17`），对应 `data/` 下的子目录名

### 运行环境约定

- Python 解释器：`.venv/bin/python`
- 当前工作分支：`feature/claude-test`（测试专用分支，不合并回主线）

### 对外一致性

| 话题 | 权威来源 |
| --- | --- |
| 项目是什么 / 四层架构 / 数据流 | `README.md` + 源码 |
| 某函数的实现 / 某 channel 的抓取规则 | `layers/*.py` 源码 |
| 板块定义 / RSS 源 / 筛选关键词 | `README.md` + `config.yaml` |
| Layer 3 抓取规则 / 兜底链 / 写稿字数规约 | `layers/editor.py` 的 PROMPT 常量 |
| Layer 2 轻筛约束（板块定义/质量分/去重/活动推广规则） | `layers/filter.py` 的 `CLASSIFY_PROMPT` / `RESCUE_PROMPT` 常量 |
| Agent 的行为边界 / 出错怎么办 | **本文件** |
| 跑测 SOP / 对话框模板 | `docs/user-guide.md` |

> 当发现源码 / README 与本文件冲突时：**源码和 README 为准**，并回报用户更新本文件。
