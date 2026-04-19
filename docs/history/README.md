# 📜 项目演进历史

> 本目录归档 NewsFunnel 项目从 2026-04-13 到现在的全部演进史、已废弃方案、中间形态。
> **当前最新设计**请看 [docs/architecture.md](../architecture.md)；
> **每日变更日志**位于 `~/.codebuddy/memory/{YYYY-MM-DD}.md`（CodeBuddy Agent 全局记忆，跨项目共享，未随仓库提交）。

---

## 🎯 6 个关键里程碑

| 里程碑 | 日期 | 标志性事件 |
|---|---|---|
| **架构定型** | 2026-04-13 | 从"配置层+采集层+AI层"三层伪架构合并为真正的四层流水线（Collector → Filter → Editor → Archiver）；Layer 1 全部 6 种 Fetcher 完成；评分架构改为三渠道独立评分 + 独立板块输出 |
| **Layer 3 完成** | 2026-04-14 | editor.py 实现完整工作流（LLM 结果加载 → 三管道渲染 → Markdown 输出）；LLM 匹配从顺序索引升级为 URL 精确匹配；summary 规范首次成文；LLM 工作统一由 CodeBuddy 在对话中完成，移除所有外部 API 调用 |
| **Layer 4 完成** | 2026-04-16 | archiver.py 实现产品深度分析报告；两种触发方式（从日报选择产品 / 手动输入链接）；10 模块结构报告；按产品归档（`data/reports/{product}/{date}.md`）；飞书迁移预埋 YAML front matter |
| **板块定义收敛** | 2026-04-18 | 第 5 轮板块收敛：剔除具身智能/Physical AI/人形机器人/自动驾驶；ai_agent 加"大厂官方 Agent 运行时里程碑"例外条款；Layer 3 summary 字数统一为 15-80 字硬约束；AGENTS.md 与 user-guide.md 的 Layer 2 权威来源指向修正 |
| **Syncer 上线** | 2026-04-19 | Layer 4 新增 syncer.py；飞书多维表格作为索引；深度报告/日报 md 移至独立 GitHub 仓库（替换早期飞书云文档上传方案）；三种同步模式：--products / --update / --push-daily |
| **开源化脱敏** | 2026-04-19 | NewsFunnel 主仓库 public push 前准备：代码默认值全部移至 .env；新增 .env.example 模板；run.sh 从硬编码 Python 路径改为自动探测 3.10+；pipeline.py shebang 改为 env；中术语路径全部清零（真·密钥从未进过 commit）|

---

## 📂 目录结构

| 文件 | 内容 |
|---|---|
| [README.md](./README.md) | 本文：演进时间线 + 里程碑索引 |
| [layer1-evolution.md](./layer1-evolution.md) | Layer 1 收集层演进：Twitter 方案（twikit→xreach）、失效 RSS 迁移、GitHub Trending 修复、launchd 迁移等 |
| [layer2-evolution.md](./layer2-evolution.md) | Layer 2 筛选层演进：10 次改进、LLM 轻筛方案 C、quota 演进、板块定义 5 轮、冷门保护、事件级去重等 |
| [layer3-evolution.md](./layer3-evolution.md) | Layer 3 编辑层演进：URL 匹配机制升级、summary 规范 3 轮迭代、4 个 PROMPT 全文阅读强制要求等 |
| [deprecated.md](./deprecated.md) | 已废弃/已替代的方案：twikit / API 自动调用 / 单一 quota_per_tag / 观点降权策略 / prompt_template 字段等 |

---

## 📅 完整时间线

### 2026-04-13 — 架构定型日

- **项目更名**：`ai-daily` → `ai-daily-news`（后续会社再统一为 `NewsFunnel`）
- **三层伪架构 → 四层真架构**：配置层+采集层+AI层 → Collector → Filter → Editor → Archiver
- **Layer 1 完成**：全部 6 种 Fetcher（RSS / GitHub / Exa / Twitter / WeChat / Manual）集成测试通过
- **评分架构三渠道独立**：RSS/微信 / GitHub / Twitter 各自独立评分排序
- **主日报四维度评分**：移除"互动数据"假维度，重分配为时效 3+覆盖 3+多标签 1.5+内容类型
- **LLM 轻筛方案 C 引入**：关键词主力 + LLM 去噪/捞漏
- **双层关键词体系**：信号词（领域通用概念）+ 品牌词（具体产品名）
- **RSSFetcher 无日期文章跳过**：避免 Paul Graham 等无 pubDate 源历史全量灌入
- **4 个失效 RSS 迁移到 Exa**：a16z / Unreal Engine / Rachel by the Bay / Dwarkesh Patel
- **GitHub Trending 日期增强**：feed-level published_parsed + GitHub API 补充 repo_created_at/stars/language

### 2026-04-14 — Layer 3 完成日

- **Layer 3 工作流打通**：editor.py 完整实现
- **LLM 匹配机制升级**：顺序索引 → URL 精确匹配 → 标题前缀匹配 → 顺序索引 fallback
- **Summary 规范首次成文**：强制结构公式 [主体]+[动作]+[结果]、≤40 字、禁重复、禁渲染、正反示例
- **GitHub 通行证移除**：Search API 扩展后需要关键词/LLM 验证相关性
- **三管道独立配额**：`pipeline_quotas` 替代旧的单一 `quota_per_tag`
- **Twitter/GitHub 质量门槛**：`min_heat: 50` + `min_stars: 5` 淘汰低质内容
- **冷门保护机制**：优质源/核心标签的低热度文章 threshold_override=2 保护，每日最多 3 篇
- **行业观点独立池**：opinion 文章从 main/twitter 管道分流到独立板块，VIP 优先，取 top-3，不再降权竞争
- **LLM ID 稳定化**：classify/rescue 候选 ID 从顺序编号改为基于标题的 sha256 哈希
- **单标签分类**：去掉 secondary_tags，每篇文章只保留一个 primary_tag
- **Quality 0-3 维度**：LLM classify 时同步打质量分，替代旧的"多标签加成"评分维度
- **板块定义第一轮重构**：ai_social 限定 AI 社交产品、ai_agent 扩展游戏化社交/创作人格、opinion 扩展为观点+宏观洞察、ai_gaming 新增 AI Native 玩法
- **ai_agent 配额扩容**：主日报从 5 提升到 10
- **事件级去重**：配额选择阶段新增标题相似度 >0.5 OR 共享核心实体检查，同管道+跨管道均生效
- **Summary 基于全文生成**：web_fetch 抓取原文后写摘要，不再仅靠标题推测
- **Quality=0 强制规则**：榜单征集/申报/投票一律 q=0；纯拼接聚合新闻 q=0（垂直周报除外）

### 2026-04-15 — 规则稳定化日

- **ai_core 配额扩容**：主日报从 3 提升到 5
- **事件去重通用词扩充**：排除 Anthropic/Claude/Gemini/DeepMind/NVIDIA 等公司名，防止仅因共享公司名误判同一事件
- **板块定义第二轮（产品优先收敛）**：除 ai_business 和 opinion 外，所有垂直板块限定为"具体产品/项目/模型的事实性新闻"；解读/分析/教程/争议全部归 opinion
- **CLASSIFY_PROMPT 全面升级**：新增同事件去重提示、quality 可信度说明、rescue 候选说明
- **rescue 扫描范围扩展**：从只扫标题改为扫描标题+摘要
- **Layer 3 Prompt 放宽**：summary ≤100 字（从 ≤40 放宽）、必须厂商+产品名主语、关键词 3-4 个
- **gen_llm_results_skeleton 操作清单**：脚本输出末尾追加逐篇 web_fetch URL 清单，固化操作纪律
- **RSS 失败历史持久化**：新增 `rss_fail_history.json`，连续 ≥3 天失败的源自动降级为 Exa 永久替代
- **launchd 替代 crontab**：macOS 定时任务迁移到 launchd（支持睡眠后补跑）
- **Twitter 采集修复**：xreach-cli@0.3.3 通过 nvm node 全局安装，launchd PATH 含 nvm 路径，采集从 0→81 篇

### 2026-04-16 — Layer 4 完成日

- **LLM 去重覆盖回填**：Step 3b 踢掉的重复文章，渠道/源信息回填到保留文章的 coverage_count
- **聚合新闻评级调整**：纯拼接聚合类（晚报/早报）从 quality=0 提升到 quality=1
- **Layer 3 Prompt 全文阅读强制**：四个 Prompt 新增全文阅读要求 + 所有英文 summary 必须翻译中文 + 技术细节下沉到 keywords
- **GitHub 优先读 README**：GITHUB_PROMPT 加"优先读 README.md 无需逐行读源码"指引
- **GitHub 持久化去重**：新增 `github_seen.json` 永久记录已入选 URL
- **GitHub 管道拆分**：单一 github → github_trending（Trending Daily+Weekly）+ github_new（Search+Blog），独立评分+配额
- **launchd 触发时间调整**：微信采集 12:00/22:00，ai-daily 12:05/22:05
- **板块定义第三轮**：ai_agent 剔除开发框架/安全、ai_gaming 加桌面宠物、ai_core 剔除论文训练框架+加世界模型、ai_product 剔除 AI 硬件
- **Layer 4 实现**：archiver.py 完整实现产品深度分析报告
- **报告按产品归档**：`data/{date}/reports/` → `data/reports/{product}/{date}.md`
- **飞书迁移预埋**：报告头部自动生成 YAML front matter

### 2026-04-17 — 工程化加固日

- **Layer 3 summary 规范收敛**：四个 Prompt 统一 ≤80 字、必须产品名、不堆数字、副标题写法、summary 与 keywords 不重复
- **防伪 URL 双重防线**：filter.py 自动生成 `llm_results_template.json`（URL 从 filtered.json 预填）；editor.py 新增 `_validate_llm_urls()` 校验
- **板块定义第四轮**：ai_agent 剔除 Agent 基础设施（沙箱/治理/编排）和 Agent 合规风险；rescue() 新增 dup_of 检查
- **板块定义第四轮补丁**：TTS/语音模型从 ai_core → ai_video，世界模型从 ai_core → ai_gaming（按应用场景归属）
- **Bug 修复×3**：字段名不一致（output_section → _output_section）、Twitter 识别改用 channel=="twitter"、_github_subpipe 仅标记 GitHub
- **模板增强**：llm_results_template 新增 _excerpt/MUST_FETCH + _tag_source/_priority
- **classify fallback**：LLM 分类缺失时从关键词标签补 _primary_tag_llm
- **Token 压缩 T1+T2**：移除 llm_filter_input.json 内嵌 CLASSIFY/RESCUE PROMPT（~3,850 token/次）
- **Token 压缩 T3**：移除 classify 候选中的 url 字段（~3,100 token/次）
- **C1 占位符拦截**：editor.py 三个 _render_* 函数新增占位符检测，summary 含 __TODO__/__MUST_FETCH__ 时 fallback 到 title
- **C2 schema 宽容校验**：filter.py load_results() 加载后做字段类型修正（relevant→bool, quality→int）
- **ai-daily-collector launchd 禁用**：Layer 1 改为纯手动触发；wechat-auto-fetch 保留

### 2026-04-18 — 板块定义收敛日

- **板块定义第五轮**：ai_core 和所有垂直板块剔除具身智能 / Physical AI / 人形机器人 / 自动驾驶 → not_relevant；ai_gaming 明确保留桌面宠物/AI 桌面助手
- **ai_agent 大厂运行时例外**：CLASSIFY_PROMPT 新增"大厂官方 Agent 运行时里程碑 → q=2"例外（OpenAI Agents SDK / MS agent-framework / Google ADK / Anthropic Harness 的战略级更新）
- **Layer 3 summary 字数统一**：四个 PROMPT 原本"任务处≤100 / 规范处≤80"自相矛盾，统一为 15-80 字硬约束（下限 15 字避免输出碎片）
- **Layer 2 权威来源修正**：AGENTS.md & user-guide.md 的权威来源从不存在的 `prompt_template` 字段改为 `layers/filter.py` 的 `CLASSIFY_PROMPT` / `RESCUE_PROMPT` 常量
- **debug 工具固化**：新增 `data/{date}/debug/_collect_debug.py` / `_render_debug.py` + `layer2_debug.md`
- **优质源保护实证**：当天多篇 Simon Willison 文章入选，冷门保护机制（threshold_override=2 + max_protected_per_day=3）配合 opinion 独立板块规则工作正常
- **文档重构**：architecture.md 瘦身到只描述当前形态；新建本目录归档全部演进史；每日变更日志迁往 `~/.codebuddy/memory/{date}.md`（全局记忆）

### 2026-04-19 — 同步层上线 + 开源化脱敏

#### Syncer 上线（上午）

- **Layer 4 新增 syncer.py**：深度报告/日报 md 存储从"飞书云文档导入"切换为独立 GitHub 仓库，飞书多维表格只写 blob URL 作为索引
- **幂等策略**：稳定 ID = md5(产品名 + 原文 url)[:16]，命中更新，未命中新建
- **三种同步模式**：`--products`（产品批量）/ `--update`（仅更新深度报告字段）/ `--push-daily`（仅推日报）
- **废弃飞书云文档方案**：清理 7 个收干美脊脚本（add_folder_member / create_app_folder / locate_app_folder / probe_create_folder / probe_drive_permissions / transfer_folder_owner / cleanup_md_residue）
- **字段保护**：飞书表格用户手工添加的字段（如"进度"）不在 `MANAGED_FIELDS` 白名单中，syncer 不触碰

#### 开源化脱敏（下午）

- **决策**：NewsFunnel 主仓库保持 Public，采用"代码默认值留空 + .env 承载真实值"的方案（主流开源项目标准做法）
- **6 个文件脱敏**：`layers/syncer.py`（默认值留空 + 字段文案改为产品名）/ `pipeline.py`（shebang）/ `run.sh`（硬编码路径→自动探测）/ `requirements.txt`（删个人路径注释）/ `.env.example`（重写为开源模板）/ `docs/architecture.md`（占位符替换）
- **Python 自动探测**：`run.sh` 按 `PYTHON_BIN` env → `python3.14→python3.10` → `python3`（校验版本≥ 3.10）三级 fallback；实测命中 `.venv/bin/python3.14`
- **历史 commit 核查**：`git log -S` 扣测所有敏感字符串 → 真·密钥（token/secret/API key）**从未进入过 commit**（.env 一直被 gitignore 保护）；弱敏感（用户名/本地路径）在 `1bca260`、`3ffada3` 两个 commit 中有残留，按决策不做 rebase
- **端到端验证**：`syncer --update "CodeFuse"` → GitHub push `2026-04-18/CodeFuse.md` 成功 + 飞书新建 record `recvhejww1mAuE` + 回读字段 text="CodeFuse" link 指向 blob URL + `curl` 返回 200

---
## 🔄 如何添加新演进记录

1. **新的每日变更**：写到 `~/.codebuddy/memory/{YYYY-MM-DD}.md`（全局记忆目录，跨项目共享），不要加到这里
2. **重大里程碑**：
   - 更新本文件顶部的"关键里程碑"表
   - 在本文件的完整时间线追加
   - 根据改动性质，同步到 `layer{N}-evolution.md` 或 `deprecated.md`
3. **已废弃方案**：把旧方案描述 + 废弃原因 + 替代方案写到 [`deprecated.md`](./deprecated.md)
