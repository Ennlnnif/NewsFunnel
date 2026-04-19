# Layer 2 筛选层演进史

> 当前最新设计：[docs/architecture.md §3.2](../architecture.md)
> 本文归档 Layer 2 历史演进、中间形态、10 次改进、板块定义 5 轮重构。

---

## 📋 概览：Layer 2 经历的关键演进

| 演进方向 | 关键节点 | 当前形态 |
|---|---|---|
| 关键词体系 | 单一 keywords → 双层（signals + brands） | signals 自动覆盖未来新品 + brands 精确命中 |
| 评分维度 | 互动数据假维度 → 四维度 → quality 替代多标签 | 时效 3 + 覆盖 3 + quality 1.5 + 内容类型调整 |
| 配额体系 | 单一 quota_per_tag → pipeline_quotas | main/github/twitter 三管道独立配额 |
| LLM 用法 | 无 → OpenAI API 自动 → CodeBuddy 代跑 | 全部统一 CodeBuddy 对话完成 |
| 观点处理 | 直接竞争 → -1.0 降权 → 分流独立池 | opinion 独立池 VIP 优先取 top-3 |
| 去重 | URL+标题模糊 → 加事件级去重 | 配额选择阶段 +标题相似度 +核心实体 |
| 板块定义 | 泛 AI 列表 → 5 轮收敛 | 当前第 5 轮，剔除具身/自动驾驶 |

---

## 1. 关键词体系演进

### 旧方案（2026-04-13 之前）
单一 `keywords` 列表，全是具体名称（`GPT-4`、`Sora`、`Cursor`），对市场新品无能为力。

### 新方案（2026-04-13）：双层关键词

| 层级 | 说明 | 设计目的 | 示例 |
|---|---|---|---|
| **信号词 (signals)** | 描述领域的通用概念词 | 不随产品更迭过时，自动覆盖未来新品 | "AI视频生成"、"大模型"、"agent framework" |
| **品牌词 (brands)** | 具体产品/公司/模型名 | 精确命中已知目标 | "Sora"、"DeepSeek"、"Cursor" |

- 两层 OR 关系：命中任意一个就算匹配
- 信号词是主力：一篇讲"全新 AI 视频生成工具 XXX"的文章，即使 XXX 不在品牌词列表里，"AI 视频生成"这个信号词也能捕获它
- 旧配置中的 `keywords` 字段仍然兼容

### 英文短词词边界匹配（2026-04-13）

| 词长 | 匹配方式 | 原因 |
|---|---|---|
| ≤ 4 字符的纯 ASCII 词 | `\b` 正则词边界 | 避免 "o1" 匹配 "o1 签证"、"Yi" 匹配 "Yi 姓" |
| 中文词 / 长英文词 | `in` 子串匹配 | 中文无自然词边界，长词误命中概率低 |

预编译所有正则，无运行时性能损耗。

---

## 2. 渠道通行证演进

### 初始（2026-04-13）
```yaml
always_pass_channels:
  - github
  - manual
```

### 2026-04-14 移除 GitHub 通行证
```yaml
always_pass_channels:
  - manual
```

**原因**：
- 初期仅采集 Trending，上榜本身已是社区筛选，通行证合理
- 2026-04-14 起 GitHub Search API 按 7 个兴趣领域定向搜索，采集范围大幅扩展
- 搜索结果中可能包含仅名称沾边但实际不相关的项目，需要关键词/LLM 验证相关性

---

## 3. LLM 轻筛方案 C（2026-04-13）

### 解决的两个结构性短板

| 短板 | 示例 | 原因 |
|---|---|---|
| **假阳性（误入）** | "Yi 姓家族 DNA 分析"命中品牌词"Yi" | 关键词语义歧义，词边界保护只能解决一部分 |
| **假阴性（漏掉）** | "微软将投入 800 亿美元建设数据中心"—— 没有任何关键词命中 | 文章用间接表达讨论 AI 相关领域 |

### 核心思路
关键词仍是主力（200 篇级别命中量已证明覆盖率不错），LLM 只处理两种边界情况。LLM 不可用时自动跳过，退化为纯关键词筛选。

### 处理流程

```
raw.json
   │
   ├── Step 3a: 关键词硬筛
   │   ├── keyword_passed（~200 篇）→ Step 3b: LLM 去噪（复核低置信度命中）→ 通过 ~180 篇
   │   └── keyword_rejected（~3800 篇）→ Step 3c: LLM 捞漏（batch 标题扫描）→ 捞回 ~10 篇
   └─────────────────── 合并 ────────────────────────────────────── ~190 篇
```

### Step 3b: LLM 去噪（复核关键词假阳性）

对 `keyword_passed` 中的**低置信度命中**做 LLM 复核：

```python
needs_review = [
    a for a in keyword_passed
    if a["_match_type"] == "brand_only"      # 仅品牌词命中（歧义风险高）
    and a["_match_count"] == 1               # 只命中 1 个词
    and a["_match_in_title"] == False         # 不是标题命中（正文命中更不确定）
]
# 预估：~20-40 篇需要复核
```

### Step 3c: LLM 捞漏（找回关键词假阴性）

对 `keyword_rejected` 做轻量标题扫描，batch 发送：

```python
# 预过滤：用宽松的人物/公司名单缩小范围
loose_trigger_names = [
    "Sam Altman", "Satya Nadella", "Jensen Huang", "Elon Musk",
    "Mark Zuckerberg", "Sundar Pichai", "Demis Hassabis",
    "Dario Amodei", "李彦宏", "黄仁勋", "马斯克",
    "微软", "Microsoft", "谷歌", "Google", "英伟达", "NVIDIA",
    # ... 等
]
maybe_relevant = [
    a for a in keyword_rejected
    if any(name.lower() in a["title"].lower() for name in loose_trigger_names)
]
# 约 100-300 篇 → 2-6 次 batch 调用
```

### 成本估算（参考）

| 环节 | 文章数 | 每批大小 | 调用次数 | 输入 token（估） |
|---|---|---|---|---|
| 去噪（复核假阳性） | ~30 | 30 | 1 | ~3k |
| 捞漏（预过滤后） | ~200 | 50 | 4 | ~8k |
| **合计** | - | - | **~5 次** | **~11k token** |

### Fallback 机制（三级退化）

```python
# 优先级：API 自动调用 > CodeBuddy 对话式代跑 > 纯关键词
try:
    denoised = llm_denoise(keyword_passed)
    rescued = llm_rescue(keyword_rejected)
except (APIError, Timeout, RateLimitError):
    logger.warning("LLM 不可用，fallback 到纯关键词筛选")
    denoised = keyword_passed
    rescued = []
```

### 实证数据（2026-04-13）

| 指标 | 纯关键词 | + CodeBuddy 轻筛 |
|---|---|---|
| 去噪 | 0 篇踢掉 | 3 篇假阳性踢掉 |
| 捞漏 | 0 篇捞回 | 8 篇捞回 |
| 最终入选 | 41 篇 | 43 篇 |
| ai_gaming 覆盖 | 7 篇 | 9 篇 |

---

## 4. LLM 分类机制演进

### ID 稳定化（2026-04-14）
classify/rescue 候选的 ID 从顺序编号（`c0, c1, c2...`）改为基于标题的 sha256 哈希（`c81c67417`）。

```python
def _stable_id(prefix: str, art: dict) -> str:
    content = art.get('title', '')
    return f"{prefix}{hashlib.sha256(content.encode()).hexdigest()[:8]}"
```

**解决的问题**：`run_filter` 每次执行时去重后文章顺序可能变化，旧的顺序编号（c0, c1...）会导致 `llm_filter_results.json` 和 `llm_filter_input.json` 的 ID 错位。哈希 ID 基于标题内容，无论跑多少次同一篇文章的 ID 永远不变。

### 单标签分类（2026-04-14）
- 去掉 `secondary_tags`
- 每篇文章只保留一个 `primary_tag`
- 降低分类歧义

### Quality 0-3 维度（2026-04-14）
替代旧的"多标签加成"评分维度：

| quality | 含义 | 评分加成 | 示例 |
|---|---|---|---|
| 3 | 重大 | +1.5 | 产品首发/技术突破/独家深度/重要开源/重大融资收购 |
| 2 | 常规 | +1.0 | 行业报告/公司动态/产品更新/技术解析/垂直领域周报盘点 |
| 1 | 边缘 | +0.5 | 消费评测/泛科技/轻度相关 |
| 0 | 噪声 | +0.0 | 活动推广/榜单征集/申报/投票/招聘/广告/纯拼接型聚合新闻 |

**效果**：区分度从 0.5 分扩大到 2+ 分，重大产品发布（q=3）比活动推广（q=0）高 1.5 分。

### Quality=0 强制规则
- 标题含"申报""征集""报名""投票"等行动号召词 → 一律 q=0
- 标题用分号/竖线拼接 ≥3 条无关新闻的聚合晚报/早报/速递 → q=0
- 垂直领域周报（如"AI 短剧周报"）聚焦单一主题的除外

### 聚合新闻评级调整（2026-04-16）
纯拼接聚合类新闻（晚报/早报/速递）从 quality=0 提升到 **quality=1**（⚡TUNABLE），primary_tag 由 LLM 判断。

### classify fallback（2026-04-17）
LLM 分类缺失时从关键词标签补 `_primary_tag_llm`，标记 `_tag_source="keyword_fallback"`。

---

## 5. 配额体系演进

### 旧方案：单一 quota_per_tag（2026-04-13 之前）
```yaml
quota_per_tag:
  ai_core: 5
  ai_agent: 5
  ...
```

**问题**：main/github/twitter 共享同一套配额，管道间性质差异大却平等竞争。

### 新方案：pipeline_quotas（2026-04-14）

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

### 配额调整历史

| 时间 | 改动 |
|---|---|
| 2026-04-14 | ai_agent 主日报配额从 5 → 10 |
| 2026-04-15 | ai_core 主日报配额从 3 → 5 |

---

## 6. 评分维度演进

### 2026-04-13（初始）
```
时效性(0-3) + 覆盖广度(0-3) + 互动数据(0-2) + 多标签(0-1.5) + 内容类型 + 源bonus
```
**移除"互动数据"假维度**（主日报渠道没有 likes/stars 等真实互动数据），重分配为：
```
时效性(0-3) + 覆盖广度(0-3) + 多标签(0-1.5) + 内容类型(±0.5) + 源bonus(0-0.5)
```

### 2026-04-14（quality 替代多标签）
```
时效性(0-3) + 覆盖广度(0-3) + LLM quality(0-1.5) + 内容类型调整 + 源bonus
```

### 覆盖广度评分增强（2026-04-13）
跨渠道覆盖比同渠道多源更有价值（同一事件 RSS + Twitter + 微信 > 3 个 RSS 源）：

| 条件 | 分数 | 说明 |
|---|---|---|
| 3+ 渠道 or 5+ 源 or 6+ 报道 | **3.0** | 重大事件（↑ 从 2.5 提升到 3.0） |
| 2 渠道 or 4+ 源 or 4+ 报道 | **2.5** | 热点事件（↑ 从 2.0 提升到 2.5） |
| 3 源 or 3 报道 | 1.5 | 有热度 |
| 2 源 or 2 报道 | 0.5 | 有一定关注度 |
| 单源 | 0.0 | 无覆盖加分 |

### LLM 去重覆盖回填（2026-04-16）
Step 3b LLM 标记同事件重复（`dup_of` 字段）时，被踢文章的渠道/源信息回填到保留文章的 `coverage_count`，使 Step 4 覆盖广度评分反映 LLM 识别的语义级重复。

---

## 7. 观点处理演进（三轮大变）

### 第一版（2026-04-13）：直接竞争
观点类和技术/产品文平等参与标签配额竞争。

### 第二版（2026-04-13）：-1.0 降权
在同一标签配额里排后面 → 大部分被淘汰。

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
   "tech_product" +0.5            "opinion" -1.0（VIP 不降权）
         │                              │
         │                         ┌────┴────┐
         │                         ▼         ▼
         │                    VIP 作者    普通作者
         │                    不降权       降权 -1.0
         ▼
   其他 → "news" (不调整)
```

### 第三版（2026-04-14）：分流到独立板块 ✅（当前）

**问题**：有价值的行业洞察也被淘汰了 → 改为分流到独立"行业观点"板块。

**当前方案**：opinion 文章**不降权**，而是从 main/twitter 管道**分流**到独立的观点池：

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

**VIP 作者机制**：VIP 作者的 opinion 文章在观点板块中**排序优先**（VIP > 非 VIP），但**只出现在观点板块**，不双重曝光到原标签板块。

---

## 8. 板块定义 5 轮演进

### 第一轮（2026-04-14）
- ai_social 限定为 AI 社交产品
- ai_agent 扩展游戏化社交/创作人格
- opinion 扩展为观点+宏观洞察
- ai_gaming 新增 AI Native 玩法

### 第二轮（2026-04-15）：产品优先收敛
- 除 ai_business 和 opinion 外，所有垂直板块限定为"具体产品/项目/模型的事实性新闻"
- 解读/分析/教程/争议全部归 opinion（兜底板块）
- ai_agent 新增排除 B 端企业 SaaS

### 第三轮（2026-04-16）
- ai_agent 剔除开发框架/安全相关 → not_relevant
- ai_gaming 新增桌面宠物/助手
- ai_social 新增传统社交+AI / AI 聊天
- ai_core 剔除论文和训练框架 → ai_product，新增世界模型论文
- ai_product 剔除 AI 硬件 → not_relevant
- not_relevant 新增明确排除清单

### 第四轮（2026-04-17）
- ai_agent 剔除 Agent 基础设施（沙箱/治理/编排）和 Agent 合规风险 → not_relevant
- rescue() 新增 dup_of 检查防止重复报道被捞回
- **补丁**：TTS/语音模型从 ai_core → ai_video
- **补丁**：世界模型从 ai_core → ai_gaming（按应用场景归属）

### 第五轮（2026-04-18）✅ 当前
- ai_core 和所有垂直板块剔除具身智能 / Physical AI / 人形机器人 / 自动驾驶，统一归 not_relevant
- ai_gaming 明确保留"桌面宠物 / AI 桌面助手（机器人宠物）"不在剔除范围内
- ai_agent 新增"大厂官方 Agent 运行时重大里程碑 → q=2"例外条款（OpenAI Agents SDK / MS agent-framework / Google ADK / Anthropic Harness 的战略级更新）

---

## 9. 质量控制门槛（2026-04-14）

在标签配额竞争之前，先淘汰低质量内容：

| 管道 | 门槛 | 计算公式 | 说明 |
|---|---|---|---|
| **Twitter** | `min_heat: 50` | `likes×1.0 + retweets×3.0 + views×0.01` | 低于 50 的推文直接淘汰，避免冷门推文凑数 |
| **GitHub** | `min_stars: 5` | 当前 star 总数 | 低于 5 stars 的项目直接淘汰，避免 spam 项目 |

**参考数值**：
- likes=7 views=489 → heat≈11.9（不过门槛）
- likes=140 retweets=42 views=24760 → heat≈513.6（轻松过门槛）

---

## 10. 冷门保护机制（2026-04-14）

### 问题
Simon Willison、Lilian Weng 等大牛的文章可能因为发布时间晚导致热度还没起来，在配额竞争中被淘汰。

### 方案

```yaml
cold_protection:
  enabled: true
  threshold_override: 2        # 受保护文章的通过阈值（正常核心是 4）
  max_protected_per_day: 3     # 每天最多保护 3 篇，防止噪声
  protected_sources:
    - "Simon Willison"
    - "Lilian Weng"
    - "Jay Alammar"
  protected_tags:
    - "ai_core"
    - "ai_gaming"
    - "ai_agent"
```

### 2026-04-18 实证
当天多篇 Simon Willison 文章入选，实证冷门保护机制（`threshold_override=2` + `max_protected_per_day=3`）配合"opinion 独立板块 VIP 优先"规则工作正常，无需特殊权重。

---

## 11. 事件级去重（2026-04-14）

### 问题
Step 2 的标题去重（阈值 0.85）无法捕获同一事件的不同角度报道 —— "马斯克版微信亮相" vs "马斯克版微信，终于来了！" 标题相似度仅 0.4，但讲的是同一产品。

### 解决方案
在 `_select_by_tag_quota` 的配额选择循环中，对每篇候选文章检查是否和已入选文章是同一事件：

```
候选文章 → 是否已有同事件入选？
              │
              ├── 标题相似度 > 0.5 → 同事件，跳过
              │
              ├── 共享核心实体关键词 → 同事件，跳过
              │   （≥ 4 字符中文实体 or ≥ 4 字符英文实体）
              │   排除通用词：Agent/Model/AI/大模型/开源/发布 等
              │
              └── 无匹配 → 不同事件，正常入选
```

**跨管道去重**：main 管道入选的标题传递给 twitter 管道，同一事件不会在两个管道各入选一次。

### 误杀控制
- 通用词排除列表（Agent, Model, AI, Microsoft, OpenAI, 大模型, 人工智能 等）
- 实体长度门槛 ≥ 4 字符
- 2026-04-15 扩充：补充 Anthropic/Claude/Gemini/DeepMind/NVIDIA 等 AI 公司名，防止仅因共享公司名误判同一事件
- 实证：4-14 数据 OpenClaw 2→1、马斯克版微信 3→2，误杀 2 篇（可接受）

---

## 12. rescue 扫描范围扩展（2026-04-15）
- 预过滤从只扫标题 → 扫描标题+摘要
- 触发词补充讯飞/Manus/Lovable/Gemini/Kimi/豆包/通义/文心/Harness/Hermes 等国内外 AI 产品名

---

## 13. 防伪 URL 双重防线（2026-04-17）

### 问题
Layer 3 的 LLM 结果 URL 可能手写错误，导致日报链接到错误的文章。

### 方案
- `filter.py` 自动生成 `llm_results_template.json`（URL 从 `filtered.json` 预填）
- `editor.py` 新增 `_validate_llm_urls()` 校验，URL 不匹配则报错终止

### 模板增强（2026-04-17）
- `llm_results_template` 新增 `_excerpt` / `MUST_FETCH` 标记
- 新增 `_tag_source` / `_priority`（`keyword_fallback=low`）
- `llm_filter_results_template` 新增标题聚类（同事件排一起）

---

## 14. Token 压缩（2026-04-17）

| 代号 | 改动 | 节省 |
|---|---|---|
| **T1** | 移除 `llm_filter_input.json` 中内嵌的 `CLASSIFY_PROMPT` 字段 | ~3,200 token |
| **T2** | 移除 `llm_filter_input.json` 中内嵌的 `RESCUE_PROMPT` 字段 | ~650 token |
| **T3** | 移除 classify 候选中的 `url` 字段 | ~3,100 token/次 |

**理由**：
- T1+T2: CLASSIFY/RESCUE Prompt 字段仅供人工阅读，CodeBuddy 直接从 `filter.py` 读取 Prompt，JSON 副本无消费者
- T3: LLM 分类不访问 URL，`channel` 字段已提供来源信息，URL 对分类决策贡献为零

---

## 15. Bug 修复记录（2026-04-17）

| Bug | 修复 |
|---|---|
| `_generate_llm_results_template` 字段名不一致 | 读 `output_section` 改为 `_output_section` |
| Twitter 文章识别错误 | 改用 `channel=="twitter"` |
| `_github_subpipe` 标记范围过大 | 仅标记 GitHub 文章 |

### C1 占位符拦截（2026-04-17）
`editor.py` 三个 `_render_*` 函数中增加占位符检测：
- summary 含 `__TODO__` 或 `__MUST_FETCH__` 时 fallback 到 title
- 打印 `[C1]` warning
- 防止占位符渲染到日报

### C2 schema 宽容型校验（2026-04-17）
`filter.py load_results()` 加载 `llm_filter_results.json` 后做字段类型修正：
- `relevant` 强制转 bool
- `quality` 强制转 int
- 自动修正并打印 `[C2]` warning，不 raise error

---

## 📎 相关文档

- [当前 Layer 2 设计](../architecture.md)
- 每日变更日志：`~/.codebuddy/memory/{YYYY-MM-DD}.md`
- [已废弃方案](./deprecated.md)
