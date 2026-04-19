# Layer 3 编辑层演进史

> 当前最新设计：[docs/architecture.md §3.3](../architecture.md)
> 本文归档 Layer 3 历史演进、Prompt 规范演进、匹配机制升级。

---

## 📋 概览：Layer 3 经历的关键演进

| 演进方向 | 关键节点 | 当前形态 |
|---|---|---|
| LLM 匹配机制 | 顺序索引 → URL 精确匹配 | URL 精确 > 标题前缀 > 顺序索引 fallback |
| Summary 字数 | ≤40 字 → ≤100 字 → ≤80 字 → 15-80 字 | 15-80 字硬约束（下限防碎片） |
| Summary 来源 | 仅标题推测 → 全文摘要 | 强制 web_fetch 原文后生成 |
| Prompt 数量 | 1 个统一 | 4 个独立（SECTION/TWITTER/GITHUB/OPINION） |
| 全文阅读 | 可选 | 四个 Prompt 强制要求 |
| URL 防伪 | 无 | filter.py 预填 + editor.py 校验双保险 |

---

## 1. LLM 匹配机制演进

### 初始方案（2026-04-14 之前）：顺序索引
```python
# llm_results.json 中 articles 按顺序对齐 filtered.json
article[i].summary = llm_results["articles"][i]["summary"]
```

**问题**：`run_filter` 每次执行时，Layer 2 的去重/评分排序可能导致顺序变化，顺序索引严重漂移，日报出现"标题和内容错位"。

### 新方案（2026-04-14）：URL 精确匹配 + 三级 fallback

```python
def _match_llm_result(article, llm_items):
    # 优先级 1: URL 精确匹配（最可靠）
    for item in llm_items:
        if item.get("url") == article.url:
            return item

    # 优先级 2: 标题前缀匹配（fallback）
    for item in llm_items:
        if item.get("title", "")[:30] == article.title[:30]:
            return item

    # 优先级 3: 旧式顺序索引（兼容旧格式）
    try:
        return llm_items[int(item.id) - 1]
    except (ValueError, IndexError):
        return None
```

---

## 2. Summary 生成流程演进

### 初始（2026-04-14 之前）：仅靠标题推测
CodeBuddy 根据标题 + summary 字段生成摘要，不抓原文。

**问题**：标题信息密度低，生成的摘要空洞，经常和 keywords 信息重复。

### 2026-04-14：入选文章强制 web_fetch
```
入选文章 URL → web_fetch 抓取全文 → 基于全文写摘要
```
- 微信/RSS 文章均通过 web_fetch 抓取原文全文
- summary 基于全文核心内容生成，而非仅靠标题推测
- Twitter 推文本身即全文，无需额外抓取

### 2026-04-16：四个 Prompt 全文阅读强制要求
四个 Prompt（SECTION/TWITTER/GITHUB/OPINION）新增 **⚠️ 全文阅读强制要求**：
- 所有英文 summary 必须翻译为中文
- summary 结构改为"谁+做了什么+影响"
- 技术细节下沉到 keywords

### GitHub 特殊优化（2026-04-16）
GITHUB_PROMPT 新增"**优先阅读 README.md 即可，无需逐行读源码**"指引，减少工作量。

---

## 3. Summary 字数规范 4 轮演进

### 第一版（2026-04-14）：≤40 字
- 强制结构公式 `[主体]+[动作]+[结果]`
- 只保留最核心的一个事件
- 禁止重复、禁止渲染
- 加入正反示例

**示例**：
- ✅ "Anthropic 发布 Managed Agents 架构，将推理与执行解耦提升 Agent 扩展性"
- ✅ "Cisco 拟 3.5 亿美元收购 AI 安全公司 Astrix Security"
- ✅ "markitdown: 微软开源的多格式转 Markdown 工具"

**反例**：
- ❌ "Anthropic 获取 70% 新增企业客户，Claude 推出灵魂校准对齐策略，从工程师口碑到企业信任全面突围"
- ❌ "新款 AI 男友产品上线，标志着 AI 情感陪伴从女性市场延伸到全性别覆盖"

### 第二版（2026-04-15）：放宽到 ≤100 字
**原因**：40 字过紧，用户反馈技术细节写不下。

- summary ≤ 100 字（从 ≤ 40 字放宽）
- 必须以厂商+产品名作为主语
- 关键词从 2-3 个升到 3-4 个
- 产品类列核心功能/价值，事件类列核心影响
- insight 扩到 ≤ 80 字，要求回答 why/how、揭示因果与影响、可选务实启示

### 第三版（2026-04-17）：收敛到 ≤80 字
- summary ≤ 80 字
- 必须出现产品名
- 不堆砌数字
- 参考副标题写法
- summary 与 keywords 不允许信息重复

### 第四版（2026-04-18）✅ 当前：15-80 字硬约束
**原因**：editor.py 四个 PROMPT 原本"任务处 ≤ 100 / 规范处 ≤ 80"自相矛盾。

- **统一为 15-80 字硬约束**
- **下限 15 字**：避免输出孤立短语片段
- **上限 80 字**：像新闻副标题一样精炼
- SECTION_PROMPT 示例段替换为更精炼的范例（OpenAI Codex / CodeFuse NES / Claude Design）

---

## 4. 写作规范历次补充

### 结构要求（2026-04-14 起稳定）
| 维度 | 要求 |
|---|---|
| **结构** | `[主体] + [做了什么] + [关键结果]` |
| **具体性** | 必须出现具体产品名/公司名/人名，禁止"某 AI 产品""新工具"等模糊表述 |
| **反重复** | 一句话中不得用不同措辞说同一件事 |
| **反渲染** | 删掉"全面突围""标志着""引爆市场"等空洞修饰 |
| **与关键词的关系** | 互补不重叠 —— keywords 承载实体名，summary 聚焦事件动态 |
| **GitHub 特殊** | 必须以项目名开头，说功能不说评价 |

---

## 5. 四 Prompt 独立化

### 2026-04-14 之前：单一 Prompt
所有板块共用同一个 summary prompt，无差异化处理。

### 2026-04-14 起：按场景拆分为 4 个
- `SECTION_PROMPT`：主日报 7 个垂直板块
- `TWITTER_PROMPT`：Twitter 推文（含热度数据展示）
- `GITHUB_PROMPT`：GitHub 项目（含 stars/语言）
- `OPINION_PROMPT`：行业观点板块（独立池）

每个 Prompt 针对不同内容类型有独立的 summary 要求、keywords 生成规则、渲染格式。

---

## 6. 板块渲染架构演进

### 单一主日报 → 四板块架构（2026-04-14）

```
filtered.json 入选文章
       │
       ├── channel in (rss, wechat, exa, manual)
       │     ├── opinion → 💡 行业观点板块（VIP 优先 > 评分，top-3）
       │     └── 非 opinion → 📰 主日报管道（按 relevance_tag 分 7 个板块）
       │
       ├── channel == twitter
       │     ├── opinion → 💡 行业观点板块（合并）
       │     └── 非 opinion → 🐦 Twitter 热门（按 score 降序，top-N）
       │
       └── channel == github → 🐙 GitHub 热门项目（按 stars 降序，top-N）
```

---

## 7. 防伪 URL 双重防线（2026-04-17）

### 问题
Layer 3 的 LLM 结果 URL 可能手写错误，导致日报链接到错误的文章。

### 方案
**第一重防线 - filter.py 预填**：
- 自动生成 `llm_results_template.json`
- URL 从 `filtered.json` 预填，不需要人工手写

**第二重防线 - editor.py 校验**：
- 新增 `_validate_llm_urls()` 校验
- URL 不匹配则报错终止，不会生成有错误链接的日报

### 占位符拦截（2026-04-17 C1）
`editor.py` 三个 `_render_*` 函数中增加占位符检测：
- summary 含 `__TODO__` 或 `__MUST_FETCH__` 时 fallback 到 title
- 打印 `[C1]` warning
- 防止占位符渲染到日报

---

## 📎 相关文档

- [当前 Layer 3 设计](../architecture.md)
- 每日变更日志：`~/.codebuddy/memory/{YYYY-MM-DD}.md`
- [已废弃方案](./deprecated.md)
