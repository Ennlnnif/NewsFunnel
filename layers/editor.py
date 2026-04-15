"""
Layer 3: 编辑（Editor）

职责：读取 filtered.json + llm_results.json，按板块渲染 Markdown 日报
结构：四大板块 —— 主日报（按 relevance_tag 分节）+ 行业观点 + Twitter 热门 + GitHub 热门项目
原则：板块顺序固定，标题由 CodeBuddy 预生成，洞察说出"so what"

工作流：
  1. CodeBuddy 读取 filtered.json 中的文章
  2. CodeBuddy 按 prompt 模板为每个板块生成 LLM 结果（标题/摘要/关键词/洞察）
  3. 写入 data/{date}/llm_results.json
  4. 本模块读取 llm_results.json → 渲染输出 daily.md

观点板块（2026-04-14 新增）：
  opinion 文章从 main/twitter 管道分流而来，不参与原板块配额竞争。
  排序：VIP 作者优先 > 综合评分。固定输出 3 篇。
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger("editor")


# ══════════════════════════════════════════
# LLM 调用
# ══════════════════════════════════════════


class LLMResultLoader:
    """LLM 结果加载器 — 从 CodeBuddy 预生成的 llm_results.json 读取

    工作流：
      1. CodeBuddy 读取 filtered.json 中的文章
      2. CodeBuddy 按 prompt 模板为每个板块生成 LLM 结果（标题/摘要/关键词/洞察）
      3. 写入 data/{date}/llm_results.json
      4. editor.py 通过此 Loader 读取，渲染 Markdown 日报

    不依赖任何外部 API，所有 LLM 工作由 CodeBuddy 在对话中完成。
    """

    def __init__(self):
        self._data: dict | None = None

    def load(self, json_path: str | Path):
        """加载预生成的 LLM 结果文件"""
        path = Path(json_path)
        if not path.exists():
            raise FileNotFoundError(
                f"LLM 结果文件不存在: {path}\n"
                "请先让 CodeBuddy 读取 filtered.json 并生成 llm_results.json"
            )
        self._data = json.loads(path.read_text(encoding="utf-8"))
        logger.info(f"已加载 LLM 结果: {path}（{len(self._data)} 个板块）")

    def get_section(self, section_key: str) -> dict | None:
        """获取指定板块的 LLM 结果"""
        if self._data and section_key in self._data:
            return self._data[section_key]
        return None

    @property
    def is_loaded(self) -> bool:
        return self._data is not None


# ══════════════════════════════════════════
# Prompt 模板（参考标准）
# ══════════════════════════════════════════
# 以下 Prompt 模板不被代码直接调用。
# 它们是 CodeBuddy 在对话中为每个板块生成 LLM 结果时的参考标准。
# 生成的结果写入 llm_results.json，由 LLMResultLoader 读取。

SECTION_PROMPT = """你是一个 AI 行业资讯编辑。请为以下「{section_title}」领域的 {count} 篇文章生成日报内容。

任务：
1. 为每篇文章生成：
   - summary: 一句话概括（≤40字中文），格式要求见下方
   - keywords: 2-3 个亮点关键词（如：企业客户争夺 | 灵魂校准 | Anthropic）
2. 为整个板块生成：
   - insight: 一句话洞察（≤60字，提炼板块今日趋势 + "so what"——即对行业或从业者意味着什么）

## summary 写作规范（核心要求，必须严格遵守）

结构公式：**[主体] + [做了什么/发生了什么] + [关键结果/影响]**

具体规则：
1. **必须出现具体产品名/公司名/人名**——"某AI产品"、"新工具"、"一位创业者"等模糊表述一律禁止
2. **不允许重复表达同一信息**——一句话中不得用不同措辞说同一件事（如"获取企业客户"和"企业信任突围"是同义重复）
3. **不要加渲染修饰**——删掉"全面突围""标志着""引爆市场"等空洞描述，只保留事实
4. **≤40字**——逼自己只保留最核心的一个事件，不要试图塞入多个事件
5. **summary 和 keywords 信息互补、不重叠**——keywords 承载产品名/技术名/公司名等实体，summary 聚焦动态事件

好的示例：
- ✅ "Anthropic发布Managed Agents架构，将推理与执行解耦提升Agent扩展性"
- ✅ "Cisco拟3.5亿美元收购AI安全公司Astrix Security"
- ✅ "Jack Dorsey开源编程Agent工具GOOSE，对标Claude Code"

差的示例：
- ❌ "Anthropic获取70%新增企业客户，Claude推出灵魂校准对齐策略，从工程师口碑到企业信任全面突围"（重复+渲染+超长）
- ❌ "新款AI男友产品上线，标志着AI情感陪伴从女性市场延伸到全性别覆盖"（没产品名+空洞描述）
- ❌ "聚焦一位深耕海外市场的中国游戏创业者"（没人名没公司名+不是新闻事件）

要求：
- summary 是日报中每条新闻的**唯一展示文本**
- summary 必须基于原标题和摘要的事实，不要推测
- 如果原文缺乏具体产品名/人名，从原标题和摘要中提取；如果确实没有，如实写出事件即可
- 英文文章用中文概括，保留英文产品名/术语
- **聚合新闻拆分**（标记 is_aggregate=true 的文章）：从中提取与本板块最相关的**单条事件**写 summary，忽略不相关的其他事件。例如"氪星晚报｜MOMOTOY融资；马斯克X版微信上线"在 ai_business 板块只写 MOMOTOY 融资

文章列表：
{articles_text}

输出 JSON（严格遵守格式）：
{{
  "articles": [
    {{"id": "1", "summary": "...", "keywords": ["k1", "k2", "k3"]}},
    ...
  ],
  "insight": "板块一句话洞察..."
}}
"""

TWITTER_PROMPT = """你是一个 AI 行业资讯编辑。请为以下 {count} 条 Twitter 热门推文生成日报摘要。

任务：
1. 为每条推文生成：
   - summary: 一句话概括（≤40字中文），格式：[谁] + [说了什么/做了什么] + [关键信息]
   - keywords: 2-3 个亮点关键词
2. 为整个 Twitter 板块生成：
   - insight: 一句话趋势洞察（≤60字）

## summary 写作规范
1. **必须出现具体人名/产品名**——禁止"研究人员""新工具"等模糊表述
2. **不允许重复表达**——一句话中不得用不同措辞说同一件事
3. **不加渲染修饰**——只保留事实
4. **≤40字**——只保留最核心的一个信息点
5. **summary 和 keywords 信息互补、不重叠**

推文列表：
{articles_text}

输出 JSON：
{{
  "articles": [
    {{"id": "1", "summary": "...", "keywords": ["k1", "k2", "k3"]}},
    ...
  ],
  "insight": "Twitter 热点一句话洞察..."
}}
"""

GITHUB_PROMPT = """你是一个 AI 行业资讯编辑。请为以下 {count} 个 GitHub 热门项目生成日报摘要。

任务：
1. 为每个项目生成：
   - summary: 一句话概括（≤40字中文），格式：[项目名] + [做什么/解决什么问题]
   - keywords: 2-3 个亮点关键词
2. 为整个 GitHub 板块生成：
   - insight: 一句话趋势洞察（≤60字）

## summary 写作规范
1. **必须以项目名开头**——如 "markitdown: 微软开源的多格式转Markdown工具"
2. **说清楚项目做什么**——不要说"已成为最热门工具"等评价，说它的功能
3. **不允许重复表达**——一句话中不得用不同措辞说同一件事
4. **≤40字**——只保留核心功能描述
5. **summary 和 keywords 信息互补、不重叠**

项目列表：
{articles_text}

输出 JSON：
{{
  "articles": [
    {{"id": "1", "summary": "...", "keywords": ["k1", "k2", "k3"]}},
    ...
  ],
  "insight": "GitHub 热门趋势一句话洞察..."
}}
"""

OPINION_PROMPT = """你是一个 AI 行业资讯编辑。请为以下 {count} 篇行业观点/评论文章生成日报摘要。

任务：
1. 为每篇文章生成：
   - summary: 一句话概括（≤40字中文），格式：[谁] + [核心观点] + [为什么值得关注]
   - keywords: 2-3 个亮点关键词
2. 为整个观点板块生成：
   - insight: 一句话趋势洞察（≤60字）

## summary 写作规范
1. **必须出现具体人名/公司名**——禁止"业内人士""专家"等模糊表述
2. **提炼核心观点**——说出"他认为什么"，不要说"他发表了看法"
3. **不允许重复表达**——一句话中不得用不同措辞说同一件事
4. **≤40字**——只保留最核心的一个观点
5. **summary 和 keywords 信息互补、不重叠**

好的示例：
- ✅ "Karpathy认为当前LLM编码习惯会导致技术债，建议用CLAUDE.md约束生成行为"
- ✅ "Matthew Ball分析AI游戏变现难在用户预期与技术成熟度的错配"

差的示例：
- ❌ "业内专家对AI前景发表看法"（没人名+没具体观点）
- ❌ "Sam Altman发表演讲，分享对AI未来的思考和展望"（空洞+重复）

文章列表：
{articles_text}

输出 JSON：
{{
  "articles": [
    {{"id": "1", "summary": "...", "keywords": ["k1", "k2", "k3"]}},
    ...
  ],
  "insight": "行业观点一句话洞察..."
}}
"""





def _assign_primary_tag(article: dict, section_order: list[str]) -> str:
    """为文章选出主板块标签

    优先使用 LLM 分类的 primary_tag（精准）。
    fallback 到关键词多标签按 sections 顺序选择（兼容无 LLM 结果的情况）。
    """
    # 优先 LLM 分类结果
    llm_primary = article.get("_primary_tag_llm", "")
    if llm_primary and llm_primary in section_order:
        return llm_primary

    # fallback: 关键词多标签
    tags = article.get("relevance_tags", [])
    if not tags:
        return ""
    for sec_tag in section_order:
        if sec_tag in tags:
            return sec_tag
    return tags[0]


def _group_main_articles(articles: list[dict], section_order: list[str]) -> dict[str, list[dict]]:
    """将主日报管道文章按 primary_tag 分组，每篇只归一个板块"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for art in articles:
        primary = _assign_primary_tag(art, section_order)
        if primary:
            art["_primary_tag"] = primary
            groups[primary].append(art)
    # 每组按 score 降序
    for tag in groups:
        groups[tag].sort(key=lambda a: a.get("score", 0), reverse=True)
    return groups


# ══════════════════════════════════════════
# Markdown 渲染
# ══════════════════════════════════════════


def _format_date(published_at: str) -> str:
    """将 published_at 格式化为 MM-DD（月+日）"""
    if not published_at:
        return ""
    try:
        from dateutil import parser as dateutil_parser
        dt = dateutil_parser.parse(published_at)
        return dt.strftime("%m-%d")
    except Exception:
        # fallback: 尝试截取月日部分
        if len(published_at) >= 10:
            return published_at[5:10]
        return published_at


def _render_main_article(art: dict, llm_data: dict) -> str:
    """渲染主日报管道的单条新闻

    格式：一句话概括 + 关键词 + 日期(月-日) + 原文链接
    不展示原标题、标签、热度、来源名
    """
    # 优先使用 LLM 生成的 summary 作为一句话概括
    # 如果没有 summary，fallback 到 title
    summary = llm_data.get("summary", "")
    title = llm_data.get("title") or art.get("title", "无标题")
    headline = summary if summary else title

    keywords = llm_data.get("keywords", [])
    url = art.get("url", "")
    date_str = _format_date(art.get("published_at", ""))

    lines = []
    lines.append(f"- **{headline}**")

    meta_parts = []
    if keywords:
        meta_parts.append(f"关键词: {' | '.join(keywords)}")
    if date_str:
        meta_parts.append(date_str)
    if url:
        meta_parts.append(f"[原文]({url})")
    if meta_parts:
        lines.append(f"  {' · '.join(meta_parts)}")

    lines.append("")
    return "\n".join(lines)


def _render_twitter_article(art: dict, llm_data: dict) -> str:
    """渲染 Twitter 单条推文

    格式：一句话概括 + 关键词 + 日期(月-日) + 热度(转发/浏览) + 原文链接
    """
    summary = llm_data.get("summary", "")
    title = llm_data.get("title") or art.get("title", "无标题")
    headline = summary if summary else title

    keywords = llm_data.get("keywords", [])
    url = art.get("url", "")
    date_str = _format_date(art.get("published_at", ""))
    extra = art.get("extra") or {}
    retweets = extra.get("retweets", 0) or 0
    views = extra.get("views", 0) or 0

    lines = []
    lines.append(f"- **{headline}**")

    meta_parts = []
    if keywords:
        meta_parts.append(f"关键词: {' | '.join(keywords)}")
    if date_str:
        meta_parts.append(date_str)
    # 热度
    heat_parts = []
    if retweets:
        heat_parts.append(f"🔁{retweets:,}")
    if views:
        heat_parts.append(f"👁{views:,}")
    if heat_parts:
        meta_parts.append(" ".join(heat_parts))
    if url:
        meta_parts.append(f"[原文]({url})")
    if meta_parts:
        lines.append(f"  {' · '.join(meta_parts)}")

    lines.append("")
    return "\n".join(lines)


def _render_github_article(art: dict, llm_data: dict) -> str:
    """渲染 GitHub 单个项目

    格式：一句话概括 + 关键词 + 语言 + Stars + 原文链接
    """
    summary = llm_data.get("summary", "")
    title = llm_data.get("title") or art.get("title", "无标题")
    headline = summary if summary else title

    keywords = llm_data.get("keywords", [])
    url = art.get("url", "")
    extra = art.get("extra") or {}
    stars = extra.get("stars", 0) or 0
    repo_lang = extra.get("repo_language", "")

    lines = []
    lines.append(f"- **{headline}**")

    meta_parts = []
    if keywords:
        meta_parts.append(f"关键词: {' | '.join(keywords)}")
    if repo_lang:
        meta_parts.append(repo_lang)
    if stars:
        meta_parts.append(f"⭐{stars:,}")
    if url:
        meta_parts.append(f"[原文]({url})")
    if meta_parts:
        lines.append(f"  {' · '.join(meta_parts)}")

    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════
# 核心逻辑：按板块批量 LLM + 拼装 Markdown
# ══════════════════════════════════════════


def _build_articles_text(articles: list[dict]) -> str:
    """将文章列表格式化为 LLM prompt 中的文本块

    注意：此函数不再被 editor.py 内部调用。
    保留作为 CodeBuddy 生成 llm_results.json 时构建 prompt 的参考实现。
    """
    lines = []
    for i, art in enumerate(articles, 1):
        title = art.get("title", "")
        summary = (art.get("summary_clean", "") or "")[:200]
        source = art.get("source_name", "")
        lines.append(f"[id: {i}] 标题: {title}")
        if summary:
            lines.append(f"  摘要: {summary}")
        if source:
            lines.append(f"  来源: {source}")
        lines.append("")
    return "\n".join(lines)


def _load_section_results(
    loader: LLMResultLoader,
    articles: list[dict],
    section_title: str,
    section_key: str,
) -> tuple[dict[int, dict], str]:
    """
    从 LLMResultLoader 读取指定板块的预生成 LLM 结果。

    Args:
        loader: LLM 结果加载器
        articles: 该板块的文章列表（用于 fallback 计数）
        section_title: 板块标题（用于日志）
        section_key: 板块在 llm_results.json 中的 key

    Returns:
        (idx->llm_data, insight): 文章索引 → LLM 数据映射 + 板块洞察
    """
    section_data = loader.get_section(section_key)
    if not section_data:
        logger.warning(f"llm_results.json 中未找到板块: {section_key} ({section_title})")
        return {}, ""

    all_llm_data: dict[int, dict] = {}
    llm_articles = section_data.get("articles", [])

    # 优先用 url 精确匹配，其次用 title 模糊匹配
    for item in llm_articles:
        item_url = item.get("url", "")
        item_title = item.get("title", "")
        item_id = item.get("id", "")

        matched_idx = None

        # 方式1：URL精确匹配
        if item_url:
            for idx, art in enumerate(articles):
                if art.get("url", "").rstrip("/") == item_url.rstrip("/"):
                    matched_idx = idx
                    break

        # 方式2：标题精确匹配
        if matched_idx is None and item_title:
            for idx, art in enumerate(articles):
                if art.get("title", "")[:30] == item_title[:30]:
                    matched_idx = idx
                    break

        # 方式3：旧式顺序ID fallback（兼容旧格式）
        if matched_idx is None:
            try:
                fallback_idx = int(item_id) - 1
                if 0 <= fallback_idx < len(articles):
                    matched_idx = fallback_idx
            except (ValueError, TypeError):
                pass

        if matched_idx is not None:
            all_llm_data[matched_idx] = item

    insight = section_data.get("insight", "")
    matched = len(all_llm_data)
    total = len(articles)
    if matched < total:
        logger.warning(f"{section_title}: LLM 结果 {matched}/{total} 篇，{total - matched} 篇将 fallback 到原标题")
    else:
        logger.info(f"{section_title}: 加载了 {matched} 篇 LLM 结果")

    return all_llm_data, insight


def run_editor(date: str | None = None, config: dict | None = None) -> dict:
    """
    Layer 3 主入口：读取 filtered.json，生成 Markdown 日报。

    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天
        config: 完整配置字典，如果为 None 则自动加载

    Returns:
        统计信息字典
    """
    from rich.console import Console
    console = Console()

    # ── 确定日期 ──
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # ── 加载配置 ──
    if config is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        else:
            config = {}

    editor_cfg = config.get("editor", {})

    # ── 路径 ──
    data_dir = Path(__file__).parent.parent / "data"
    today_dir = data_dir / date
    filtered_path = today_dir / "filtered.json"
    output_path = today_dir / "daily.md"

    if not filtered_path.exists():
        console.print(f"[red]filtered.json 不存在: {filtered_path}[/red]")
        return {"error": f"filtered.json not found: {filtered_path}"}

    # ── 加载 filtered.json ──
    console.print(f"\n[bold cyan]═══ Layer 3: 编辑 ({date}) ═══[/bold cyan]\n")
    data = json.loads(filtered_path.read_text(encoding="utf-8"))
    articles = [a for a in data.get("articles", []) if not a.get("filtered_out", True)]
    # 恢复 LLM 分类的 primary_tag 到内部字段（filtered.json 中是公开字段）
    for a in articles:
        if a.get("primary_tag_llm"):
            a["_primary_tag_llm"] = a["primary_tag_llm"]
    total = len(articles)
    console.print(f"输入: {total} 篇入选文章")

    # ── 分管道 ──
    main_articles = [a for a in articles if a.get("channel") in ("rss", "wechat", "exa", "manual")]
    twitter_articles = [a for a in articles if a.get("channel") == "twitter"]
    github_articles = [a for a in articles if a.get("channel") == "github"]

    # ── Opinion 分流：从 main + twitter 中提取观点文章 ──
    opinion_articles = [a for a in main_articles + twitter_articles
                        if a.get("output_section") == "opinion"]
    main_articles = [a for a in main_articles if a.get("output_section") != "opinion"]
    twitter_articles = [a for a in twitter_articles if a.get("output_section") != "opinion"]

    # Opinion 按 VIP > score 排序
    opinion_articles.sort(
        key=lambda a: (1 if a.get("content_type_vip") else 0, a.get("score", 0)),
        reverse=True,
    )
    op_max = editor_cfg.get("opinion_section", {}).get("max_items", 3)
    opinion_articles = opinion_articles[:op_max]

    # Twitter/GitHub 按热度排序
    twitter_articles.sort(key=lambda a: a.get("score", 0), reverse=True)
    github_articles.sort(
        key=lambda a: (a.get("extra") or {}).get("stars", 0) or 0,
        reverse=True,
    )

    # Twitter/GitHub 限制条数
    tw_max = editor_cfg.get("twitter_section", {}).get("max_items", 10)
    gh_max = editor_cfg.get("github_section", {}).get("max_items", 10)
    twitter_articles = twitter_articles[:tw_max]
    github_articles = github_articles[:gh_max]

    console.print(f"  主日报: {len(main_articles)} 篇")
    console.print(f"  行业观点: {len(opinion_articles)} 篇")
    console.print(f"  Twitter: {len(twitter_articles)} 条")
    console.print(f"  GitHub: {len(github_articles)} 个项目")

    # ── 主日报按标签分组 ──
    sections = editor_cfg.get("sections", [])
    section_order = [s["tag"] for s in sections if isinstance(s, dict)]
    section_titles = {s["tag"]: s["title"] for s in sections if isinstance(s, dict)}
    main_groups = _group_main_articles(main_articles, section_order)

    # ── 初始化 LLM 结果加载器 ──
    loader = LLMResultLoader()
    llm_results_path = today_dir / "llm_results.json"
    loader.load(llm_results_path)
    console.print(f"[green]已加载 LLM 结果: {llm_results_path}[/green]")

    # ── 逐板块加载 LLM 结果 ──
    md_parts = []
    stats = {"sections": {}, "total_articles": total}

    # 日报头部
    md_parts.append(f"# AI 日报 — {date}\n")
    active_main_sections = len([t for t in section_order if main_groups.get(t)])
    extra_sections = []
    if opinion_articles:
        extra_sections.append("行业观点")
    if twitter_articles:
        extra_sections.append("Twitter")
    if github_articles:
        extra_sections.append("GitHub")
    extra_str = (" + " + " + ".join(extra_sections)) if extra_sections else ""
    md_parts.append(f"> 共 {total} 条资讯 | 覆盖 {active_main_sections} 个领域{extra_str}\n")
    md_parts.append("---\n")

    # 主日报板块
    for sec_tag in section_order:
        sec_title = section_titles.get(sec_tag, sec_tag)
        group = main_groups.get(sec_tag, [])
        if not group:
            continue

        console.print(f"\n  处理板块: {sec_title} ({len(group)} 篇)")
        llm_data_map, insight = _load_section_results(
            loader, group, sec_title, section_key=sec_tag,
        )
        stats["sections"][sec_tag] = {"count": len(group), "insight": insight}

        md_parts.append(f"## {sec_title}\n")
        if insight:
            md_parts.append(f"> **洞察**: {insight}\n")
        md_parts.append("")

        for idx, art in enumerate(group):
            llm_item = llm_data_map.get(idx, {})
            md_parts.append(_render_main_article(art, llm_item))

        md_parts.append("---\n")

    # 行业观点板块（主日报板块之后，Twitter 之前）
    if opinion_articles:
        op_title = editor_cfg.get("opinion_section", {}).get("title", "行业观点")
        console.print(f"\n  处理板块: {op_title} ({len(opinion_articles)} 篇)")

        op_llm_map, op_insight = _load_section_results(
            loader, opinion_articles, op_title, section_key="opinion",
        )
        stats["sections"]["opinion"] = {
            "count": len(opinion_articles), "insight": op_insight,
        }

        md_parts.append(f"## {op_title}\n")
        if op_insight:
            md_parts.append(f"> **洞察**: {op_insight}\n")
        md_parts.append("")

        for idx, art in enumerate(opinion_articles):
            llm_item = op_llm_map.get(idx, {})
            md_parts.append(_render_main_article(art, llm_item))

        md_parts.append("---\n")

    # Twitter 板块
    if twitter_articles:
        tw_title = editor_cfg.get("twitter_section", {}).get("title", "Twitter 热门")
        console.print(f"\n  处理板块: {tw_title} ({len(twitter_articles)} 条)")

        tw_llm_map, tw_insight = _load_section_results(
            loader, twitter_articles, tw_title, section_key="twitter",
        )
        stats["sections"]["twitter"] = {
            "count": len(twitter_articles), "insight": tw_insight,
        }

        md_parts.append(f"## {tw_title}\n")
        if tw_insight:
            md_parts.append(f"> **洞察**: {tw_insight}\n")
        md_parts.append("")

        for idx, art in enumerate(twitter_articles):
            llm_item = tw_llm_map.get(idx, {})
            md_parts.append(_render_twitter_article(art, llm_item))

        md_parts.append("---\n")

    # GitHub 板块（始终输出，无新项目时给兜底提示）
    gh_title = editor_cfg.get("github_section", {}).get("title", "GitHub 热门项目")
    if github_articles:
        console.print(f"\n  处理板块: {gh_title} ({len(github_articles)} 个项目)")

        gh_llm_map, gh_insight = _load_section_results(
            loader, github_articles, gh_title, section_key="github",
        )
        stats["sections"]["github"] = {
            "count": len(github_articles), "insight": gh_insight,
        }

        md_parts.append(f"## {gh_title}\n")
        if gh_insight:
            md_parts.append(f"> **洞察**: {gh_insight}\n")
        md_parts.append("")

        for idx, art in enumerate(github_articles):
            llm_item = gh_llm_map.get(idx, {})
            md_parts.append(_render_github_article(art, llm_item))

    else:
        console.print(f"\n  处理板块: {gh_title} (今日无新增)")
        stats["sections"]["github"] = {"count": 0, "insight": ""}

        # 计算昨日日期
        from datetime import timedelta
        yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_daily = data_dir / yesterday / "daily.md"
        has_yesterday = yesterday_daily.exists()

        md_parts.append(f"## {gh_title}\n")
        md_parts.append("> 今日 GitHub Trending 无新增 AI 相关项目（多数为昨日延续上榜）\n")
        if has_yesterday:
            md_parts.append(f"> 可查阅昨日日报：`data/{yesterday}/daily.md`\n")
        md_parts.append("")

    md_parts.append("---\n")

    # ── 写入 ──
    markdown = "\n".join(md_parts)
    today_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    console.print(f"\n[green]已保存日报: {output_path}[/green]")
    console.print(f"\n[bold cyan]═══ Layer 3 完成 ═══[/bold cyan]")

    return stats


# ══════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    run_editor(date=target_date)
