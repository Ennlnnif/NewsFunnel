"""
Layer 4: 产品深度分析报告（Archiver）

职责：对产品进行多信息源深度分析，产出策略级洞察报告
触发：两种方式手动触发

方式一：从日报选择产品
  python -m layers.archiver --product "Archon"           # 从当天日报中匹配
  python -m layers.archiver --list                       # 列出当天日报可选产品
  python -m layers.archiver                              # 交互式选择

方式二：手动输入链接
  python -m layers.archiver --url "https://github.com/xxx"               # GitHub 链接
  python -m layers.archiver --url "https://twitter.com/xxx/status/123"   # Twitter 链接
  python -m layers.archiver --url "https://techcrunch.com/xxx"           # 文章链接
  python -m layers.archiver --url "https://reddit.com/r/xxx"            # Reddit 链接
  python -m layers.archiver --url "/path/to/image.png"                  # 图片路径

工作流：
  1. 识别输入来源（日报文章 / 外部链接）
  2. 构建素材信息
  3. 加载 report_template.md 中的 REPORT_PROMPT
  4. 填充素材 → 导出 llm_report_input.json
  5. CodeBuddy 读取 → 多源信息采集 → 生成报告
  6. 报告写入 data/{date}/reports/{product_name}.md
"""

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
except ImportError:
    console = None

logger = logging.getLogger("archiver")

# ── 路径 ──
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "layers" / "report_template.md"
CONFIG_PATH = BASE_DIR / "config.yaml"

# ── 链接类型识别 ──
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def _load_prompt() -> str:
    """从 report_template.md 提取 REPORT_PROMPT（``` 代码块内的内容）"""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    match = re.search(r"## REPORT_PROMPT\s*\n\s*```\n(.*?)```", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"无法从 {TEMPLATE_PATH} 提取 REPORT_PROMPT")
    return match.group(1).strip()


def _load_filtered(date: str) -> list[dict]:
    """加载当天 filtered.json 中的入选文章"""
    data_dir = BASE_DIR / "data" / date
    filtered_path = data_dir / "filtered.json"
    if not filtered_path.exists():
        raise FileNotFoundError(f"未找到 {filtered_path}，请先运行 Layer 2 筛选")

    data = json.loads(filtered_path.read_text(encoding="utf-8"))
    articles = data.get("articles", [])
    return [a for a in articles if not a.get("filtered_out", True)]


def _detect_source_type(url: str) -> str:
    """识别链接类型"""
    # 本地文件路径
    if not url.startswith("http"):
        path = Path(url)
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            return "image"
        return "local_file"

    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "github.com" in host:
        return "github"
    elif "twitter.com" in host or "x.com" in host:
        return "twitter"
    elif "reddit.com" in host:
        return "reddit"
    elif path_ext := Path(parsed.path).suffix.lower():
        if path_ext in IMAGE_EXTENSIONS:
            return "image"

    return "article"


def _extract_product_name_from_url(url: str, source_type: str) -> str:
    """从 URL 提取产品名"""
    parsed = urlparse(url)

    if source_type == "github":
        # https://github.com/user/repo → user/repo
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return parts[0] if parts else "unknown"

    elif source_type == "twitter":
        # https://twitter.com/username/status/123 → @username
        parts = parsed.path.strip("/").split("/")
        if parts:
            return f"@{parts[0]}"
        return "unknown"

    elif source_type == "reddit":
        # https://reddit.com/r/subreddit/... → r/subreddit
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "r":
            return f"r/{parts[1]}"
        return "unknown"

    elif source_type == "image":
        return Path(url).stem

    else:
        # 文章类：用域名
        return parsed.hostname or "unknown"


def _format_article_content(article: dict) -> str:
    """将日报文章信息格式化为 Prompt 素材"""
    parts = []
    parts.append(f"**标题**: {article.get('title', '未知')}")
    parts.append(f"**URL**: {article.get('url', '无')}")
    parts.append(f"**来源**: {article.get('source_name', '未知')} ({article.get('channel', '?')})")

    tags = article.get("relevance_tags", [])
    if tags:
        parts.append(f"**板块标签**: {', '.join(tags)}")

    primary_tag = article.get("primary_tag_llm", "")
    if primary_tag:
        parts.append(f"**LLM主标签**: {primary_tag}")

    score = article.get("score", 0)
    quality = article.get("quality", "?")
    parts.append(f"**评分**: {score} (quality={quality})")

    summary = article.get("summary_clean", "") or article.get("summary", "")
    if summary:
        parts.append(f"**摘要**: {summary[:500]}")

    extra = article.get("extra") or {}
    if extra.get("stars"):
        parts.append(f"**GitHub Stars**: {extra['stars']:,}")
    if extra.get("language"):
        parts.append(f"**编程语言**: {extra['language']}")

    return "\n".join(parts)


def _format_external_content(url: str, source_type: str, product_name: str) -> str:
    """将外部链接格式化为 Prompt 素材"""
    type_labels = {
        "github": "GitHub 项目",
        "twitter": "Twitter/X 推文",
        "reddit": "Reddit 帖子",
        "article": "文章/报道",
        "image": "图片",
        "local_file": "本地文件",
    }

    parts = [
        f"**产品/主题**: {product_name}",
        f"**来源链接**: {url}",
        f"**来源类型**: {type_labels.get(source_type, '未知')}",
    ]

    # 按来源类型给 LLM 额外指引
    if source_type == "github":
        parts.append("**采集指引**: 请优先阅读 README.md，获取项目定位、功能、技术栈等信息")
    elif source_type == "twitter":
        parts.append("**采集指引**: 请阅读完整推文串及引用内容，如有外部链接也请打开阅读")
    elif source_type == "reddit":
        parts.append("**采集指引**: 请阅读帖子正文和高赞评论，提取产品信息和社区反馈")
    elif source_type == "image":
        parts.append("**采集指引**: 请通过 read_file 读取图片内容，识别其中的产品信息后展开分析")
    elif source_type == "article":
        parts.append("**采集指引**: 请通过 web_fetch 阅读全文，提取产品相关的核心信息")

    return "\n".join(parts)


def _safe_filename(name: str) -> str:
    """生成安全文件名"""
    return re.sub(r'[^\w\u4e00-\u9fff\-]', '_', name[:40]).strip('_')


# ══════════════════════════════════════════
# 方式一：从日报选择产品
# ══════════════════════════════════════════


def list_products(articles: list[dict]) -> None:
    """列出可选产品"""
    if console:
        table = Table(title="可选产品")
        table.add_column("#", style="bold", width=4)
        table.add_column("渠道", width=10)
        table.add_column("板块", width=12)
        table.add_column("标题", width=50)
        table.add_column("分数", width=6)
        table.add_column("来源", width=15)

        for i, art in enumerate(articles, 1):
            ch = art.get("channel", "?")
            tag = art.get("primary_tag_llm", "") or (
                art.get("relevance_tags", ["?"])[0] if art.get("relevance_tags") else "?"
            )
            title = art.get("title", "")[:48]
            score = str(art.get("score", 0))
            source = art.get("source_name", "")[:13]
            table.add_row(str(i), ch, tag, title, score, source)
        console.print(table)
    else:
        print("\n可选产品：")
        for i, art in enumerate(articles, 1):
            print(f"  {i:2d}. [{art.get('channel','?'):7s}] {art.get('title','')[:55]}")


def select_product(articles: list[dict], product_name: str | None = None) -> dict | None:
    """选择要分析的产品"""
    if product_name:
        matches = [
            a for a in articles
            if product_name.lower() in a.get("title", "").lower()
        ]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            print(f"\n找到 {len(matches)} 个匹配 '{product_name}' 的产品：")
            for i, a in enumerate(matches, 1):
                print(f"  {i}. {a.get('title', '')[:60]}")
            try:
                idx = int(input("\n请选择编号: ")) - 1
                return matches[idx]
            except (ValueError, IndexError):
                print("无效选择")
                return None
        else:
            print(f"未找到匹配 '{product_name}' 的产品")
            return None

    list_products(articles)
    try:
        idx = int(input("\n请输入产品编号: ")) - 1
        if 0 <= idx < len(articles):
            return articles[idx]
        print("编号超出范围")
    except (ValueError, KeyboardInterrupt):
        print("\n已取消")
    return None


# ══════════════════════════════════════════
# 统一：生成报告输入
# ══════════════════════════════════════════


def generate_report_input(
    date: str,
    prompt_template: str,
    product_name: str,
    product_url: str,
    article_content: str,
    source_mode: str,
    source_type: str = "",
    tags: list[str] | None = None,
    article_meta: dict | None = None,
) -> Path:
    """生成 LLM 报告输入文件

    输出路径按产品归档：data/reports/{product_name}/{date}.md
    报告头部包含 YAML front matter，为未来迁移飞书多维表格预留结构化元数据。
    """
    data_dir = BASE_DIR / "data" / date
    safe_name = _safe_filename(product_name)

    # 按产品归档：data/reports/{product_name}/{date}.md
    reports_dir = BASE_DIR / "data" / "reports" / safe_name
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / f"{date}.md"

    # 构建 YAML front matter（供未来飞书多维表格同步）
    front_matter_lines = [
        "---",
        f"product: {product_name}",
        f"date: {date}",
        f"source_mode: {source_mode}",
        f"source_url: {product_url}",
    ]
    if source_type:
        front_matter_lines.append(f"source_type: {source_type}")
    if tags:
        front_matter_lines.append(f"tags: [{', '.join(tags)}]")
    front_matter_lines.append("---")
    front_matter = "\n".join(front_matter_lines)

    # 填充 Prompt，追加 front matter 要求
    filled_prompt = prompt_template.replace(
        "{product_name}", product_name
    ).replace(
        "{article_content}", article_content
    )
    # 在输出要求后追加 front matter 指引
    filled_prompt += f"\n\n**报告头部必须包含以下 YAML front matter（原样输出）**：\n```\n{front_matter}\n```"

    input_data = {
        "source_mode": source_mode,
        "product_name": product_name,
        "product_url": product_url,
        "output_path": str(output_path),
        "front_matter": front_matter,
        "prompt": filled_prompt,
    }

    if article_meta:
        input_data["article"] = article_meta

    input_path = data_dir / "llm_report_input.json"
    input_path.write_text(
        json.dumps(input_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return input_path


# ══════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════


def run_archiver(
    date: str | None = None,
    product_name: str | None = None,
    url: str | None = None,
    list_only: bool = False,
):
    """Layer 4 主入口

    两种触发方式：
      1. 从日报选择产品：--product / --list / 交互式
      2. 手动输入链接：--url
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  Layer 4: 产品深度分析报告 — {date}")
    print(f"{'='*60}")

    # 加载 Prompt 模板
    try:
        prompt_template = _load_prompt()
    except RuntimeError as e:
        print(f"\n❌ {e}")
        return

    # ── 方式二：手动输入链接 ──
    if url:
        source_type = _detect_source_type(url)
        detected_name = _extract_product_name_from_url(url, source_type)

        type_labels = {
            "github": "🐙 GitHub 项目",
            "twitter": "🐦 Twitter/X 推文",
            "reddit": "📋 Reddit 帖子",
            "article": "📰 文章/报道",
            "image": "🖼️  图片",
            "local_file": "📁 本地文件",
        }
        print(f"\n  来源类型: {type_labels.get(source_type, '未知')}")
        print(f"  检测名称: {detected_name}")

        # 允许用户覆盖产品名
        final_name = product_name or detected_name
        if not product_name:
            try:
                user_input = input(f"  产品名 (回车使用 \"{detected_name}\"): ").strip()
                if user_input:
                    final_name = user_input
            except (KeyboardInterrupt, EOFError):
                print("\n已取消")
                return

        print(f"\n✅ 产品: {final_name}")
        print(f"   链接: {url}")
        print(f"   类型: {source_type}")

        article_content = _format_external_content(url, source_type, final_name)
        input_path = generate_report_input(
            date=date,
            prompt_template=prompt_template,
            product_name=final_name,
            product_url=url,
            article_content=article_content,
            source_mode="external",
            source_type=source_type,
            article_meta={"url": url, "source_type": source_type},
        )

        _print_next_steps(input_path)
        return

    # ── 方式一：从日报选择产品 ──
    try:
        articles = _load_filtered(date)
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        return

    if not articles:
        print("\n❌ 当天无入选文章")
        return

    print(f"\n📋 当天入选 {len(articles)} 篇文章\n")

    if list_only:
        list_products(articles)
        return

    article = select_product(articles, product_name)
    if not article:
        return

    title = article.get("title", "unknown")
    print(f"\n✅ 已选择: {title[:60]}")
    print(f"   URL: {article.get('url', '')}")

    article_content = _format_article_content(article)
    primary_tag = article.get("primary_tag_llm", "")
    input_path = generate_report_input(
        date=date,
        prompt_template=prompt_template,
        product_name=title,
        product_url=article.get("url", ""),
        article_content=article_content,
        source_mode="daily",
        source_type=article.get("channel", ""),
        tags=[primary_tag] if primary_tag else [],
        article_meta={
            "title": article.get("title"),
            "url": article.get("url"),
            "channel": article.get("channel"),
            "source_name": article.get("source_name"),
            "primary_tag": primary_tag,
            "score": article.get("score", 0),
            "quality": article.get("quality", "?"),
            "summary": (article.get("summary_clean", "") or article.get("summary", ""))[:500],
        },
    )

    _print_next_steps(input_path)


def _print_next_steps(input_path: Path):
    """打印下一步操作提示"""
    print(f"\n{'='*60}")
    print(f"  📄 已导出: {input_path}")
    print(f"{'='*60}")
    print(f"\n下一步：")
    print(f"  1. CodeBuddy 读取 {input_path}")
    print(f"  2. 按 prompt 字段中的指令生成报告")
    print(f"  3. 报告输出到 output_path 指定的路径")
    print(f"\n💡 提示: 在 CodeBuddy 中输入:")
    print(f'   "读取 {input_path} 中的 prompt，按指令生成报告并保存到 output_path"')


def main():
    parser = argparse.ArgumentParser(
        description="Layer 4: 产品深度分析报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
两种触发方式：

  方式一：从日报选择产品
    python -m layers.archiver                          # 交互式选择
    python -m layers.archiver --product "Archon"       # 指定产品名
    python -m layers.archiver --list                   # 列出可选产品

  方式二：手动输入链接
    python -m layers.archiver --url "https://github.com/user/repo"
    python -m layers.archiver --url "https://twitter.com/user/status/123"
    python -m layers.archiver --url "https://techcrunch.com/article"
    python -m layers.archiver --url "https://reddit.com/r/sub/post"
    python -m layers.archiver --url "/path/to/screenshot.png"
    python -m layers.archiver --url "https://..." --product "自定义产品名"

  通用选项：
    --date 2026-04-16                                  # 指定日期
        """,
    )
    parser.add_argument("--date", "-d", help="日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--product", "-p", help="产品名（方式一：模糊匹配日报标题；方式二：覆盖自动检测的名称）")
    parser.add_argument("--url", "-u", help="外部链接（方式二：文章/Twitter/Reddit/GitHub/图片）")
    parser.add_argument("--list", "-l", action="store_true", help="仅列出当天日报可选产品")

    args = parser.parse_args()
    run_archiver(
        date=args.date,
        product_name=args.product,
        url=args.url,
        list_only=args.list,
    )


if __name__ == "__main__":
    main()
