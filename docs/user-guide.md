# AI Daily News — 使用手册

> 本手册面向**使用本项目的人**（包括未来公开后的外部用户）。
> Agent 的行为契约见 [`AGENTS.md`](../AGENTS.md)；系统结构见 [`README.md`](../README.md)。

---

## 1. 环境准备

### 1.1 依赖安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.2 环境变量

复制 `.env.example` 为 `.env`，填入必要的 API Key（参考文件内注释）：

```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 1.3 微信数据源（可选）

如果启用了微信公众号采集，需要本地 Docker 服务运行中：

```bash
docker ps | grep we-mp-rss   # 应有容器在跑
# 若未启动：cd ../we-mp-rss && docker compose up -d
```

> Session 过期（超 48h 无更新）需重新扫码登录。

---

## 2. 跑一次完整日报（Layer 1 → Layer 3）

本项目的流水线由 Agent（CodeBuddy / Claude Code / Cursor 等）与人协作完成：

- **Terminal 步骤**：人类执行，跑 `pipeline.py`
- **LLM 判断步骤**：Agent 在对话框里完成（Layer 2 轻筛、Layer 3 写稿）

### 2.1 前置检查

```bash
git branch --show-current   # 确认当前分支
```

### 2.2 Step 1：Layer 1 — 采集

```bash
source .venv/bin/activate
python pipeline.py --only layer1
```

输出：`data/{YYYY-MM-DD}/raw.json`

### 2.3 Step 2：Layer 2 — 关键词筛选

```bash
python pipeline.py --only layer2
```

输出：

- `data/{YYYY-MM-DD}/filtered.json`
- `data/{YYYY-MM-DD}/llm_filter_input.json`
- `data/{YYYY-MM-DD}/llm_filter_results_template.json`

### 2.4 Step 3：Layer 2 — LLM 轻筛（交给 Agent）

给 Agent 发送以下指令（**最小版**，详细版见 § 4）：

```text
帮我完成 2026-04-17 的 Layer 2 LLM 轻筛。
规则以 layers/filter.py 的 CLASSIFY_PROMPT / RESCUE_PROMPT 常量为准。
```

Agent 会产出 `data/{YYYY-MM-DD}/llm_filter_results.json`。

完成后回 Terminal 让 Layer 2 加载结果：

```bash
python pipeline.py --only layer2
```

### 2.5 Step 4：Layer 3 — 生成 daily.md

先让 pipeline 生成 Layer 3 模板：

```bash
python pipeline.py --only layer3
```

此时若 `llm_results.json` 不存在，会生成 `llm_results_template.json`。

给 Agent 发送以下指令（**最小版**，详细版见 § 4）：

```text
帮我完成 2026-04-17 的 Layer 3 写稿。
规则以 layers/editor.py 的 SECTION_PROMPT / TWITTER_PROMPT / GITHUB_PROMPT / OPINION_PROMPT 为准。
```

Agent 会产出 `data/{YYYY-MM-DD}/llm_results.json`。

完成后回 Terminal 渲染日报：

```bash
python pipeline.py --only layer3
```

最终产物：`data/{YYYY-MM-DD}/daily.md` ✅

---

## 3. 常用命令速查

```bash
python pipeline.py --only layer1                       # 只跑采集
python pipeline.py --only layer2                       # 只跑筛选
python pipeline.py --only layer3                       # 只跑写稿
python pipeline.py --from layer2                       # 从 Layer 2 开始跑到结尾
python pipeline.py --from layer2 --date 2026-04-17     # 指定日期重跑
```

---

## 4. Agent 对话框模板（可选）

### 4.1 要不要用模板？

**不一定。** 理想状态下 Agent 看完 `README.md` + `AGENTS.md` + 源码，应该能根据你的一句话自动推断标准流程。

**但有一件事 Agent 不能自己搞定：日期。** Agent 没有可靠的"今天是哪天"工具，所以：

- **最小指令**：`"帮我完成 2026-04-17 的 Layer 2 LLM 轻筛"` / `"帮我完成 2026-04-17 的 Layer 3 写稿"`
  → 够用，Agent 会自动读 `AGENTS.md` 和约束源执行
- **详细模板**（见下文）：当你想显式重申某些约束、或 Agent 之前翻过车时再用

### 4.2 Layer 2 详细模板（按需使用）

```text
帮我完成 data/{YYYY-MM-DD}/ 的 Layer 2 LLM 轻筛。

步骤：
1. 读取 data/{YYYY-MM-DD}/llm_filter_input.json（待判断的候选数据）
2. 以 layers/filter.py 的 CLASSIFY_PROMPT / RESCUE_PROMPT 两个常量为硬约束来源
   （视为硬约束，等同于 AGENTS.md 核心约束）
   对 classify_candidates 和 rescue_candidates 两个列表逐条判断
3. 将结果写入 data/{YYYY-MM-DD}/llm_filter_results.json
   （格式参照 llm_filter_results_template.json：共 classify / rescue 两个列表，每条含 id/relevant/primary_tag/quality/reason）

提交前强制自检：
- [ ] 每条输出的字段与 template 完全一致（不增不减）
- [ ] CLASSIFY_PROMPT / RESCUE_PROMPT 里所有"必须/禁止/不要"条目逐条对照过
- [ ] 同事件去重、活动推广→q=0、具身智能/机器人这类硬规则都检查过
- [ ] 所有待填条目都已填写，无占位符残留

注意：不要修改任何 .py / .yaml 文件。
```

### 4.3 Layer 3 详细模板（按需使用）

```text
帮我完成 data/{YYYY-MM-DD}/ 的 Layer 3 摘要写作。

步骤：
1. 读取 data/{YYYY-MM-DD}/llm_results_template.json
2. 严格执行 layers/editor.py 的四个 PROMPT 常量
   （SECTION_PROMPT / TWITTER_PROMPT / GITHUB_PROMPT / OPINION_PROMPT）
   视为硬约束，等同于 AGENTS.md 核心约束
3. 执行顺序：先把所有该 web_fetch 的文章一次性抓完，再统一写 summary
   —— 禁止"抓一篇写一篇"的交错流程
4. 将结果写入 data/{YYYY-MM-DD}/llm_results.json

提交前强制自检：
- [ ] 逐条 len(summary) 校验，超过 PROMPT 规定字数一个字都不行
- [ ] 所有"禁止/不要"条目逐条对照过
- [ ] keywords 个数/格式符合 PROMPT 规定
- [ ] 冲突裁决：信息装不进 summary 的，归入 keywords 或舍弃，禁止扩写
- [ ] 带"（基于摘要生成）"标注的条目占比 ≤ 10%（超过先报告，等待指示）

注意：不要修改任何 .py / .yaml 文件。
```

---

## 5. 数据目录结构

```text
data/{YYYY-MM-DD}/
├── raw.json                          # Layer 1 输出：原始采集
├── filtered.json                     # Layer 2 输出：筛选后文章
├── llm_filter_input.json             # Layer 2 生成：LLM 轻筛输入
├── llm_filter_results_template.json  # Layer 2 生成：LLM 轻筛模板（含 prompt_template）
├── llm_filter_results.json           # Layer 2 输入：Agent 填写的分类结果
├── llm_results_template.json         # Layer 3 生成：LLM 写稿模板（URL 已预填）
├── llm_results.json                  # Layer 3 输入：Agent 填写的 summary/keywords/insight
└── daily.md                          # Layer 3 最终输出：日报正文
```

---

## 6. 常见问题

### 6.1 Layer 3 撞登录墙（x.com / twitter.com）

**不是 Bug。** Twitter 链接有登录墙，直接用 Layer 1 已抓到 `summary` 字段的完整推文即可，**禁止** `web_fetch` 这些链接。详见 `layers/editor.py` 的 `TWITTER_PROMPT`。

### 6.2 RSS / WeChat 抓取失败率偏高

按 `layers/editor.py` 里 `SECTION_PROMPT` / `OPINION_PROMPT` 的兜底链：

1. 先查 `content` 字段（RSS `content:encoded`）
2. fallback 到 `summary` 字段，末尾标注"（基于摘要生成）"
3. 如果一天有超过 10% 的条目走到第 2 步：检查当天网络 / 源站状态，别硬交付

### 6.3 URL 校验报错 "URL 不匹配"

Agent 在 `llm_results.json` 里写了**编造的 URL**。
解决：删掉 `llm_results.json`，重新基于 `llm_results_template.json` 生成（模板里的 URL 是从 `filtered.json` 预填的真实 URL，不应修改）。

### 6.4 日报里板块标签错了

板块归属在 Layer 2 由 `_primary_tag_llm` 决定，不由 Layer 3 Agent 决定。
若要调整：回到 Layer 2 重跑轻筛（`llm_filter_results.json` 中的 `primary_tag`）。

---

## 7. 手动补充文章（manual_input）

若某篇文章未被 Layer 1 采集到、但你希望纳入今天的日报：

1. 在 `manual_input/{YYYY-MM-DD}/` 目录下创建 JSON 文件
2. 格式参考 `manual_input/` 下已有的示例
3. 从 Layer 2 重跑：`python pipeline.py --from layer2`

---

## 8. Layer 4（产品深度分析，可选）

Layer 4 按需触发，生成单一产品的深度分析报告。使用方式见 `layers/archiver.py` 的模块说明。
