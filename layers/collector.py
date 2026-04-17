"""
Layer 1: 收集（Collector）

职责：从所有渠道拉取原始信息，统一格式，输出 raw.json
原则：只管"拿到"，不做任何筛选判断

支持的渠道：
  - RSS（含资讯/博客/AI巨头/游戏/VC 等 ~60 个源）
  - GitHub（Trending RSS + 官方 Blog RSS）
  - Exa Search（无 RSS 网站 + 通用关键词搜索）
  - Twitter/X（搜索关键词 + 重点账号）
  - WeChat（微信公众号，通过 we-mp-rss 本地服务）
  - Manual（手工输入 manual_input/ 目录）
"""

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import feedparser
import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

# 自动加载项目根目录的 .env（保证 EXA_API_KEY、GITHUB_TOKEN 等可用）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger("collector")
console = Console()

# ══════════════════════════════════════════
# 统一文章数据模型
# ══════════════════════════════════════════


@dataclass
class RawArticle:
    """Layer 1 统一输出结构"""

    # ── 必填 ──
    source_name: str  # 信息源名称（如 "36氪"、"OpenAI Blog"）
    channel: str  # 渠道：rss / github / exa / twitter / wechat / manual
    title: str  # 文章标题
    url: str  # 原文链接
    fetched_at: str  # 采集时间（ISO 8601）

    # ── 可选 ──
    published_at: Optional[str] = None  # 原文发布时间
    author: Optional[str] = None
    summary: Optional[str] = None  # 原文摘要/description
    content: Optional[str] = None  # 全文（如果能拿到）
    category: Optional[str] = None  # 来源分类（来自 config.yaml）
    language: Optional[str] = None  # zh / en
    extra: Optional[dict] = field(default_factory=dict)  # 渠道特有字段


# ══════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════


def now_iso() -> str:
    """返回当前时间的 ISO 8601 字符串（带时区）"""
    return datetime.now(timezone.utc).astimezone().isoformat()


def clean_title(title: str) -> str:
    """清理文章标题中的多余空白"""
    if not title:
        return "无标题"
    return " ".join(title.strip().split())


def parse_feed_date(entry: dict) -> Optional[str]:
    """解析 RSS 条目的发布时间

    feedparser 的 published_parsed/updated_parsed 返回的是 UTC 时间的 time.struct_time，
    必须用 calendar.timegm()（而非 time.mktime()）转换为 timestamp，
    否则会被当成本地时间导致偏移错误。
    """
    time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if time_struct:
        try:
            from calendar import timegm
            utc_ts = timegm(time_struct)
            dt = datetime.fromtimestamp(utc_ts, tz=timezone.utc)
            # 转为 UTC+8 输出，与微信公众号的实际发布时间一致
            dt_local = dt.astimezone(timezone(timedelta(hours=8)))
            return dt_local.isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return None


def extract_feed_url(entry: dict) -> Optional[str]:
    """从 RSS 条目中提取 URL（按优先级尝试多个字段）"""
    url = (
        entry.get("link")
        or entry.get("id")
        or entry.get("feedburner_origlink")
    )
    if url and url.startswith("http"):
        return url
    return None


# ══════════════════════════════════════════
# Fetcher 基类
# ══════════════════════════════════════════


class BaseFetcher:
    """所有 Fetcher 的基类"""

    def __init__(self, config: dict, timeout: int = 15, max_retries: int = 2,
                 retry_delay: int = 5):
        self.config = config
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def fetch(self) -> list[RawArticle]:
        """子类实现此方法"""
        raise NotImplementedError

    async def _request_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs
    ) -> httpx.Response:
        """带重试的 HTTP 请求"""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.get(
                    url, timeout=self.timeout, follow_redirects=True, **kwargs
                )
                resp.raise_for_status()
                return resp
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"请求失败（第 {attempt + 1} 次）: {url} → {e}"
                    )
                    await asyncio.sleep(self.retry_delay)
        raise last_error


# ══════════════════════════════════════════
# RSS Fetcher
# ══════════════════════════════════════════


class RSSFetcher(BaseFetcher):
    """RSS/Atom 订阅源采集器

    覆盖信息源（来自 config.yaml）：
    - 资讯媒体: GameLook、TechCrunch AI、The Verge AI、AI News、量子位、VentureBeat
    - AI 巨头: OpenAI、NVIDIA、Google AI、Meta AI、Microsoft Research、DeepMind
    - 游戏引擎: Unity、Unreal Engine
    - VC/投资: a16z
    - HN 热门博客: Simon Willison、Paul Graham、Gary Marcus 等 ~30 个

    RSS 可靠性机制：
    - 单次失败 → 当次由 Exa site:domain 兜底
    - 连续 ≥3 天失败 → 自动降级为 Exa 永久源（跳过 RSS，直接走 Exa）
    - 失败计数持久化在 data/rss_fail_history.json
    """

    # 连续失败多少天后，自动降级为 Exa 永久替代
    DEGRADE_AFTER_DAYS = 3

    def __init__(self, config: dict, **kwargs):
        super().__init__(config, **kwargs)
        self.sources = self._collect_rss_sources()
        self.failed_sources: list[dict] = []  # 记录失败的源，供 Exa 兜底
        self.degraded_sources: list[dict] = []  # 已降级为 Exa 的源（连续失败≥3天）
        self._fail_history_path = Path("data/rss_fail_history.json")
        self._fail_history = self._load_fail_history()

    def _collect_rss_sources(self) -> list[dict]:
        """从 config 中收集所有 RSS 源（扁平化各子分类）"""
        rss_config = self.config.get("collector", {}).get("sources", {}).get("rss", {})
        sources = []
        for group_name, group_sources in rss_config.items():
            if isinstance(group_sources, list):
                for src in group_sources:
                    src["_group"] = group_name
                    sources.append(src)
        return sources

    def _load_fail_history(self) -> dict:
        """加载 RSS 失败历史记录

        格式: {source_name: {"consecutive_days": N, "last_fail_date": "2026-04-15", "url": "..."}}
        """
        if self._fail_history_path.exists():
            try:
                with open(self._fail_history_path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_fail_history(self):
        """保存 RSS 失败历史"""
        self._fail_history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._fail_history_path, "w", encoding="utf-8") as f:
            json.dump(self._fail_history, f, ensure_ascii=False, indent=2)

    def _update_fail_history(self, succeeded_names: set[str], failed_names: set[str]):
        """更新失败计数：成功的清零，失败的+1

        规则：
        - 成功采集 → 连续失败计数归零（恢复健康）
        - 失败 → 如果和上次失败是不同日期，consecutive_days +1
        - 同一天多次失败只计1次
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 成功的源：清除失败记录
        for name in succeeded_names:
            if name in self._fail_history:
                logger.info(f"RSS [{name}] 恢复成功，清除连续失败记录")
                del self._fail_history[name]

        # 失败的源：更新计数
        for src in self.failed_sources:
            name = src["name"]
            if name not in self._fail_history:
                self._fail_history[name] = {
                    "consecutive_days": 1,
                    "last_fail_date": today,
                    "url": src.get("url", ""),
                    "last_error": src.get("error", "")[:100],
                }
            else:
                record = self._fail_history[name]
                if record.get("last_fail_date") != today:
                    record["consecutive_days"] += 1
                    record["last_fail_date"] = today
                record["last_error"] = src.get("error", "")[:100]

        self._save_fail_history()

    def _get_degraded_sources(self) -> list[dict]:
        """获取连续失败 ≥ DEGRADE_AFTER_DAYS 天的源（应降级为 Exa 永久替代）"""
        degraded = []
        for name, record in self._fail_history.items():
            if record.get("consecutive_days", 0) >= self.DEGRADE_AFTER_DAYS:
                degraded.append({
                    "name": name,
                    "url": record.get("url", ""),
                    "language": "en",
                    "consecutive_days": record["consecutive_days"],
                })
        return degraded

    def _should_skip_rss(self, source_name: str) -> bool:
        """是否应跳过该 RSS 源（已降级为 Exa 永久替代）"""
        record = self._fail_history.get(source_name, {})
        return record.get("consecutive_days", 0) >= self.DEGRADE_AFTER_DAYS

    async def fetch(self) -> list[RawArticle]:
        """并发采集所有 RSS 源

        已降级的源（连续失败 ≥3 天）会被跳过，由 Exa 永久替代。
        """
        articles = []
        semaphore = asyncio.Semaphore(
            self.config.get("collector", {}).get("max_concurrent_fetches", 10)
        )

        # 分离：已降级的源 vs 正常源
        active_sources = []
        for src in self.sources:
            if self._should_skip_rss(src["name"]):
                self.degraded_sources.append({
                    "name": src["name"],
                    "url": src.get("url", ""),
                    "category": src.get("category", ""),
                    "language": src.get("language", "en"),
                })
                days = self._fail_history[src["name"]]["consecutive_days"]
                logger.warning(
                    f"RSS [{src['name']}] 已降级为 Exa（连续失败 {days} 天），跳过 RSS 采集"
                )
            else:
                active_sources.append(src)

        async def fetch_one(source: dict) -> list[RawArticle]:
            async with semaphore:
                return await self._fetch_single_rss(source)

        tasks = [fetch_one(src) for src in active_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        succeeded_names = set()
        failed_names = set()

        for src, result in zip(active_sources, results):
            if isinstance(result, Exception):
                logger.error(f"RSS 采集失败 [{src['name']}]: {result}")
                failed_names.add(src["name"])
                # 记录失败源，供 Exa 兜底搜索
                self.failed_sources.append({
                    "name": src["name"],
                    "url": src.get("url", ""),
                    "category": src.get("category", ""),
                    "language": src.get("language", "en"),
                    "error": str(result),
                })
            else:
                articles.extend(result)
                if result:
                    succeeded_names.add(src["name"])
                    logger.info(
                        f"RSS 采集成功 [{src['name']}]: {len(result)} 篇"
                    )

        # 更新失败历史（持久化）
        self._update_fail_history(succeeded_names, failed_names)

        return articles

    async def _fetch_single_rss(self, source: dict) -> list[RawArticle]:
        """采集单个 RSS 源（仅保留近 max_entry_age_days 天的条目）"""
        url = source["url"]
        name = source["name"]
        max_age_days = self.config.get("collector", {}).get("max_entry_age_days", 7)

        async with httpx.AsyncClient() as client:
            try:
                # ETag/Last-Modified 条件请求（TODO: 后续可缓存上次的值）
                headers = {
                    "User-Agent": "AI-Daily-News/1.0 (RSS Reader)"
                }
                resp = await self._request_with_retry(
                    client, url, headers=headers
                )
                content = resp.text
            except Exception as e:
                logger.error(f"HTTP 请求失败 [{name}]: {e}")
                return []

        # feedparser 解析
        feed = feedparser.parse(content)
        if feed.bozo and not feed.entries:
            logger.warning(f"RSS 解析异常 [{name}]: {feed.bozo_exception}")
            return []

        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        skipped_old = 0

        for entry in feed.entries:
            entry_url = extract_feed_url(entry)
            if not entry_url:
                continue

            published_at = parse_feed_date(entry)

            # 跳过没有发布日期的文章（如 Paul Graham 的 RSS 不含 pubDate）
            if not published_at and max_age_days > 0:
                skipped_old += 1
                continue

            # 过滤掉过旧的条目
            if published_at and max_age_days > 0:
                try:
                    from dateutil import parser as dateutil_parser
                    pub_dt = dateutil_parser.parse(published_at)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone(timedelta(hours=8)))
                    if pub_dt.astimezone(timezone.utc) < cutoff:
                        skipped_old += 1
                        continue
                except (ValueError, TypeError):
                    pass  # 解析失败的保留

            article = RawArticle(
                source_name=name,
                channel="rss",
                title=clean_title(entry.get("title", "无标题")),
                url=entry_url,
                fetched_at=now_iso(),
                published_at=published_at,
                author=entry.get("author"),
                summary=entry.get("summary", ""),
                category=source.get("category", ""),
                language=source.get("language", ""),
                extra={
                    "group": source.get("_group", ""),
                    "note": source.get("note", ""),
                },
            )
            articles.append(article)

        if skipped_old:
            logger.info(f"RSS [{name}]: 跳过 {skipped_old} 篇（无日期或超过 {max_age_days} 天）")

        return articles


# ══════════════════════════════════════════
# GitHub Fetcher
# ══════════════════════════════════════════


class GitHubFetcher(BaseFetcher):
    """GitHub 信息渠道采集器

    覆盖信息源：
    - GitHub Trending 每日全语言热门仓库（RSS）
    - GitHub Trending 每周全语言热门仓库（RSS）
    - GitHub Search API（按兴趣领域主动搜索近期新项目）
    - GitHub 官方博客（RSS）
    """

    def __init__(self, config: dict, **kwargs):
        super().__init__(config, **kwargs)
        self.gh_config = (
            self.config.get("collector", {})
            .get("sources", {})
            .get("github", {})
        )
        # GitHub token（可选，提升 Search API 速率限制 10→30 req/min）
        self._gh_token = os.getenv("GITHUB_TOKEN", "")

    def _gh_headers(self) -> dict:
        """构建 GitHub API 请求头"""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Daily-News/1.0",
        }
        if self._gh_token:
            headers["Authorization"] = f"token {self._gh_token}"
        return headers

    async def fetch(self) -> list[RawArticle]:
        """采集 GitHub Trending RSS + Search API + Blog RSS"""
        articles = []
        all_sources = []

        # Trending RSS
        for src in self.gh_config.get("trending", []):
            all_sources.append(
                {**src, "category": "GitHub Trending", "_type": "trending"}
            )

        # Blog RSS
        for src in self.gh_config.get("blog", []):
            all_sources.append({**src, "_type": "blog"})

        semaphore = asyncio.Semaphore(5)

        async def fetch_one(source: dict) -> list[RawArticle]:
            async with semaphore:
                return await self._fetch_github_rss(source)

        tasks = [fetch_one(src) for src in all_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for src, result in zip(all_sources, results):
            if isinstance(result, Exception):
                logger.error(f"GitHub 采集失败 [{src['name']}]: {result}")
            else:
                articles.extend(result)
                if result:
                    logger.info(
                        f"GitHub 采集成功 [{src['name']}]: {len(result)} 篇"
                    )

        # GitHub Search API（领域定向搜索）
        search_articles = await self._fetch_github_search()
        if search_articles:
            articles.extend(search_articles)
            logger.info(f"GitHub Search API: 共采集 {len(search_articles)} 个项目")

        # URL 级去重（Trending 和 Search 可能有重叠）
        seen_urls = set()
        deduped = []
        for art in articles:
            norm_url = art.url.rstrip("/").lower()
            if norm_url in seen_urls:
                continue
            seen_urls.add(norm_url)
            deduped.append(art)
        if len(articles) != len(deduped):
            logger.info(
                f"GitHub 内部去重: {len(articles)} → {len(deduped)} "
                f"(移除 {len(articles) - len(deduped)} 个重复项目)"
            )
        return deduped

    async def _fetch_github_rss(self, source: dict) -> list[RawArticle]:
        """复用 RSS 解析逻辑采集 GitHub 源（仅保留近 max_entry_age_days 天的条目）"""
        url = source["url"]
        name = source["name"]
        max_age_days = self.config.get("collector", {}).get("max_entry_age_days", 7)

        async with httpx.AsyncClient() as client:
            try:
                headers = {"User-Agent": "AI-Daily-News/1.0"}
                resp = await self._request_with_retry(
                    client, url, headers=headers
                )
                content = resp.text
            except Exception as e:
                logger.error(f"GitHub RSS 请求失败 [{name}]: {e}")
                return []

        feed = feedparser.parse(content)
        if feed.bozo and not feed.entries:
            logger.warning(
                f"GitHub RSS 解析异常 [{name}]: {feed.bozo_exception}"
            )
            return []

        # Trending RSS entry 没有日期字段，用 feed 级别的更新时间作为榜单捕捉日期
        feed_updated = None
        if source.get("_type") == "trending":
            feed_pub = feed.feed.get("published_parsed") or feed.feed.get("updated_parsed")
            if feed_pub:
                from calendar import timegm
                feed_updated = datetime.fromtimestamp(
                    timegm(feed_pub), tz=timezone.utc
                ).astimezone().isoformat()

        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        skipped_old = 0

        for entry in feed.entries:
            entry_url = extract_feed_url(entry)
            if not entry_url:
                continue

            title = clean_title(entry.get("title", "无标题"))
            published_at = parse_feed_date(entry)

            # Trending 条目没有日期：用 feed 更新时间作为"榜单捕捉日期"
            is_trending_date = False
            if not published_at and feed_updated:
                published_at = feed_updated
                is_trending_date = True

            # 过滤掉过旧的条目
            if published_at and max_age_days > 0:
                try:
                    from dateutil import parser as dateutil_parser
                    pub_dt = dateutil_parser.parse(published_at)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone(timedelta(hours=8)))
                    if pub_dt.astimezone(timezone.utc) < cutoff:
                        skipped_old += 1
                        continue
                except (ValueError, TypeError):
                    pass

            # Trending 条目特殊处理：从 description 提取 stars 等信息
            extra = {
                "type": source.get("_type", ""),
                "period": source.get("period", ""),
            }
            summary = entry.get("summary", "")

            # 尝试从 Trending RSS 的 description 中提取 stars
            if source.get("_type") == "trending" and summary:
                extra["raw_description"] = summary

            # 标记日期类型，让下游知道这不是项目的发布日期
            if is_trending_date:
                extra["date_type"] = "trending_capture"  # 榜单捕捉日期，非项目发布日期

            article = RawArticle(
                source_name=name,
                channel="github",
                title=title,
                url=entry_url,
                fetched_at=now_iso(),
                published_at=published_at,
                author=entry.get("author"),
                summary=summary,
                category=source.get("category", "GitHub"),
                language=source.get("language", "en"),
                extra=extra,
            )
            articles.append(article)

        if skipped_old:
            logger.info(f"GitHub [{name}]: 跳过 {skipped_old} 篇超过 {max_age_days} 天的旧文章")

        # Trending 项目：批量调 GitHub API 补充 created_at / stars / language
        if source.get("_type") == "trending" and articles:
            await self._enrich_trending_repos(articles)

        return articles

    async def _enrich_trending_repos(self, articles: list[RawArticle]) -> None:
        """为 Trending 项目补充 GitHub API 信息（created_at / stars / language）"""
        async with httpx.AsyncClient(timeout=10) as client:
            tasks = []
            for art in articles:
                # 从 URL 提取 owner/repo，如 https://github.com/owner/repo
                parts = art.url.rstrip("/").split("/")
                if len(parts) >= 2:
                    repo_slug = f"{parts[-2]}/{parts[-1]}"
                    tasks.append((art, repo_slug))

            async def _fetch_repo_info(art: RawArticle, slug: str):
                try:
                    resp = await client.get(
                        f"https://api.github.com/repos/{slug}",
                        headers=self._gh_headers(),
                    )
                    if resp.status_code == 200:
                        d = resp.json()
                        art.extra["repo_created_at"] = d.get("created_at")
                        art.extra["stars"] = d.get("stargazers_count")
                        art.extra["repo_language"] = d.get("language")
                except Exception as e:
                    logger.debug(f"GitHub API 查询失败 [{slug}]: {e}")

            await asyncio.gather(*[_fetch_repo_info(a, s) for a, s in tasks])
            enriched = sum(1 for a in articles if "stars" in a.extra)
            logger.info(f"GitHub Trending: 已补充 {enriched}/{len(articles)} 个项目的 API 信息")

    async def _fetch_github_search(self) -> list[RawArticle]:
        """通过 GitHub Search API 按兴趣领域搜索近期新项目

        每条 query 对应一个关注领域（ai_agent, ai_video 等），
        搜索结果自动标记 search_query_tag，供下游相关性验证使用。
        """
        search_config = self.gh_config.get("search", [])
        if not search_config:
            return []

        articles = []
        async with httpx.AsyncClient(timeout=15) as client:
            for sq in search_config:
                query = sq["query"]
                tag = sq.get("tag", "")
                max_results = sq.get("max_results", 10)
                sort = sq.get("sort", "stars")
                order = sq.get("order", "desc")
                created_after_days = sq.get("created_after_days", 90)

                # 构建 created:> 日期限制
                since_date = (
                    datetime.now(timezone.utc) - timedelta(days=created_after_days)
                ).strftime("%Y-%m-%d")
                full_query = f"{query} created:>{since_date}"

                try:
                    resp = await client.get(
                        "https://api.github.com/search/repositories",
                        params={
                            "q": full_query,
                            "sort": sort,
                            "order": order,
                            "per_page": max_results,
                        },
                        headers=self._gh_headers(),
                    )

                    if resp.status_code == 403:
                        logger.warning(
                            f"GitHub Search API 速率限制，跳过: {query[:40]}"
                        )
                        continue
                    if resp.status_code != 200:
                        logger.error(
                            f"GitHub Search API 失败 [{resp.status_code}]: {query[:40]}"
                        )
                        continue

                    data = resp.json()
                    items = data.get("items", [])
                    total_count = data.get("total_count", 0)

                    for repo in items:
                        html_url = repo.get("html_url", "")
                        if not html_url:
                            continue

                        # 构建标题：owner/name — description
                        full_name = repo.get("full_name", "")
                        desc = repo.get("description") or ""
                        title = f"{full_name}: {desc[:80]}" if desc else full_name

                        # topics 列表（用于下游关键词匹配）
                        topics = repo.get("topics", [])

                        article = RawArticle(
                            source_name=f"GitHub Search: {tag or query[:20]}",
                            channel="github",
                            title=clean_title(title),
                            url=html_url,
                            fetched_at=now_iso(),
                            published_at=repo.get("created_at"),
                            author=repo.get("owner", {}).get("login"),
                            summary=desc,
                            category="GitHub Search",
                            language=repo.get("language") or "en",
                            extra={
                                "type": "search",
                                "search_query": query,
                                "search_query_tag": tag,
                                "stars": repo.get("stargazers_count", 0),
                                "repo_created_at": repo.get("created_at"),
                                "repo_language": repo.get("language"),
                                "topics": topics,
                                "forks": repo.get("forks_count", 0),
                                "open_issues": repo.get("open_issues_count", 0),
                                "updated_at": repo.get("updated_at"),
                                "search_total_count": total_count,
                            },
                        )
                        articles.append(article)

                    if items:
                        logger.info(
                            f"GitHub Search [{tag or query[:30]}]: "
                            f"{len(items)} 个项目 (总匹配 {total_count})"
                        )
                except Exception as e:
                    logger.error(f"GitHub Search API 异常 [{query[:30]}]: {e}")

        return articles


# ══════════════════════════════════════════
# Exa Fetcher
# ══════════════════════════════════════════


class ExaFetcher(BaseFetcher):
    """Exa 搜索采集器 — 两种功能：

    ① 固定替代源（config 中配置）：
       RSS 稳定失败的网站，Exa 定向搜索作为永久替代
       - IT桔子、Reuters AI、Anthropic、Roblox
       - a16z Blog、Unreal Engine Blog、Rachel by the Bay、Dwarkesh Patel

    ② 偶发兜底（自动触发）：
       RSS 本次采集失败的源，自动用 site:domain 精确搜索兜底
       由 run_collector 将 RSSFetcher.failed_sources 注入 fallback_sources
       必须有 URL 才能兜底（确保 site:domain 精确匹配，不搜转载站）
    """

    def __init__(self, config: dict, **kwargs):
        super().__init__(config, **kwargs)
        self.exa_config = (
            self.config.get("collector", {})
            .get("sources", {})
            .get("exa_search", {})
        )
        self.api_key = os.getenv("EXA_API_KEY", "")
        self.fallback_sources: list[dict] = []  # 由 run_collector 注入的 RSS 偶发失败源
        self.degraded_sources: list[dict] = []  # 由 run_collector 注入的 RSS 永久降级源

    async def fetch(self) -> list[RawArticle]:
        """采集所有 Exa 搜索源"""
        if not self.api_key:
            logger.warning("EXA_API_KEY 未设置，跳过 Exa 搜索")
            return []

        articles = []

        # 定向站点搜索
        for site in self.exa_config.get("sites", []):
            try:
                result = await self._search_exa(
                    query=site["search_query"],
                    source_name=site["name"],
                    language=site.get("language", "en"),
                    num_results=5,
                )
                articles.extend(result)
                if result:
                    logger.info(
                        f"Exa 定向搜索成功 [{site['name']}]: {len(result)} 篇"
                    )
            except Exception as e:
                logger.error(f"Exa 搜索失败 [{site['name']}]: {e}")

        # 通用关键词搜索
        for gq in self.exa_config.get("general_queries", []):
            try:
                result = await self._search_exa(
                    query=gq["query"],
                    source_name=f"Exa搜索: {gq['query'][:20]}",
                    language=gq.get("language", "en"),
                    num_results=5,
                )
                articles.extend(result)
                if result:
                    logger.info(
                        f"Exa 通用搜索成功 [{gq['query'][:30]}]: {len(result)} 篇"
                    )
            except Exception as e:
                logger.error(f"Exa 搜索失败 [{gq['query'][:30]}]: {e}")

        # RSS 偶发失败兜底搜索
        # 规则：必须用 site:domain 精确限定域名，避免搜到转载站
        # 无 URL 的源不做兜底（无法确定原站域名）
        if self.fallback_sources:
            logger.info(f"Exa 兜底: {len(self.fallback_sources)} 个 RSS 失败源")
            for src in self.fallback_sources:
                try:
                    if not src.get("url"):
                        logger.warning(f"Exa 兜底跳过 [{src['name']}]: 无 URL，无法确定域名")
                        continue
                    from urllib.parse import urlparse
                    domain = urlparse(src["url"]).netloc
                    if not domain:
                        logger.warning(f"Exa 兜底跳过 [{src['name']}]: 无法解析域名")
                        continue
                    search_query = f"site:{domain}"
                    result = await self._search_exa(
                        query=search_query,
                        source_name=f"{src['name']}(Exa兜底)",
                        language=src.get("language", "en"),
                        num_results=5,
                    )
                    articles.extend(result)
                    if result:
                        logger.info(
                            f"Exa 兜底成功 [{src['name']}]: {len(result)} 篇 (site:{domain})"
                        )
                except Exception as e:
                    logger.error(f"Exa 兜底失败 [{src['name']}]: {e}")

        # RSS 降级源永久替代搜索（连续 ≥3 天失败的源）
        if self.degraded_sources:
            logger.info(f"Exa 永久替代: {len(self.degraded_sources)} 个降级 RSS 源")
            for src in self.degraded_sources:
                try:
                    if not src.get("url"):
                        logger.warning(f"Exa 永久替代跳过 [{src['name']}]: 无 URL")
                        continue
                    from urllib.parse import urlparse
                    domain = urlparse(src["url"]).netloc
                    if not domain:
                        logger.warning(f"Exa 永久替代跳过 [{src['name']}]: 无法解析域名")
                        continue
                    search_query = f"site:{domain}"
                    result = await self._search_exa(
                        query=search_query,
                        source_name=f"{src['name']}(Exa替代)",
                        language=src.get("language", "en"),
                        num_results=5,
                    )
                    articles.extend(result)
                    if result:
                        logger.info(
                            f"Exa 永久替代成功 [{src['name']}]: {len(result)} 篇 (site:{domain})"
                        )
                except Exception as e:
                    logger.error(f"Exa 永久替代失败 [{src['name']}]: {e}")

        return articles

    async def _search_exa(
        self,
        query: str,
        source_name: str,
        language: str = "en",
        num_results: int = 5,
    ) -> list[RawArticle]:
        """调用 Exa API 搜索"""
        try:
            from exa_py import Exa

            exa = Exa(api_key=self.api_key)

            # 搜索近 24 小时内的结果
            from datetime import timedelta

            start_date = (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            result = exa.search_and_contents(
                query=query,
                num_results=num_results,
                start_published_date=start_date,
                text={"max_characters": 500},
            )

            articles = []
            for item in result.results:
                article = RawArticle(
                    source_name=source_name,
                    channel="exa",
                    title=clean_title(item.title or "无标题"),
                    url=item.url,
                    fetched_at=now_iso(),
                    published_at=item.published_date,
                    author=item.author if hasattr(item, "author") else None,
                    summary=(
                        item.text[:300] if hasattr(item, "text") and item.text else ""
                    ),
                    category="Exa搜索",
                    language=language,
                    extra={
                        "search_query": query,
                        "score": item.score if hasattr(item, "score") else None,
                    },
                )
                articles.append(article)

            return articles

        except ImportError:
            logger.error("exa-py 未安装，请运行: pip install exa-py")
            return []
        except Exception as e:
            logger.error(f"Exa API 调用失败: {e}")
            return []


# ══════════════════════════════════════════
# Twitter Fetcher
# ══════════════════════════════════════════


class TwitterFetcher(BaseFetcher):
    """Twitter/X 采集器（通过 xreach CLI，即 agent-reach 的 Twitter 通道）

    覆盖信息源：
    - 搜索: "AI OR LLM OR GPT min_faves:200"、中文 AI 推文、AI Agent 方向
    - 重点账号: @OpenAI、@AnthropicAI、@GoogleDeepMind、@sama、@ylecun

    工作原理：
    使用 xreach CLI（agent-reach skill 安装）通过 Twitter 内部接口采集推文。
    无需配置 Twitter 账号密码或 API Key，开箱即用。
    支持搜索（xreach search）和用户时间线（xreach tweets）两种模式。
    """

    def __init__(self, config: dict, **kwargs):
        super().__init__(config, **kwargs)
        self.tw_config = (
            self.config.get("collector", {})
            .get("sources", {})
            .get("twitter", {})
        )
        self._xreach_available = None  # 延迟检测

    async def _check_xreach(self) -> bool:
        """检查 xreach CLI 是否可用"""
        if self._xreach_available is not None:
            return self._xreach_available

        try:
            proc = await asyncio.create_subprocess_exec(
                "xreach", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            self._xreach_available = proc.returncode == 0
            if self._xreach_available:
                version = stdout.decode().strip()
                logger.info(f"Twitter: xreach 可用 ({version})")
            else:
                logger.error(
                    "xreach 未安装或不可用。"
                    "请通过 agent-reach skill 安装: agent-reach install --env=auto"
                )
        except (FileNotFoundError, asyncio.TimeoutError):
            self._xreach_available = False
            logger.error(
                "xreach 未安装。"
                "请通过 agent-reach skill 安装: agent-reach install --env=auto"
            )

        return self._xreach_available

    async def fetch(self) -> list[RawArticle]:
        """采集 Twitter 信息（通过 xreach CLI）"""
        if not await self._check_xreach():
            return []

        articles = []

        # 搜索关键词
        for sq in self.tw_config.get("search_queries", []):
            try:
                result = await self._xreach_search(
                    query=sq["query"],
                    count=sq.get("count", 20),
                )
                articles.extend(result)
                if result:
                    logger.info(
                        f"Twitter 搜索成功 [{sq['query'][:30]}]: {len(result)} 条"
                    )
            except Exception as e:
                logger.error(f"Twitter 搜索失败 [{sq['query'][:30]}]: {e}")

        # 重点账号（使用 xreach tweets @username）
        for acct in self.tw_config.get("accounts", []):
            try:
                handle = acct["handle"].lstrip("@")
                result = await self._xreach_user_tweets(
                    username=handle,
                    count=10,
                )
                articles.extend(result)
                if result:
                    logger.info(
                        f"Twitter 用户采集成功 [@{handle}]: {len(result)} 条"
                    )
            except Exception as e:
                logger.error(
                    f"Twitter 用户采集失败 [{acct['handle']}]: {e}"
                )

        return articles

    async def _run_xreach(self, args: list[str]) -> Optional[dict]:
        """执行 xreach 命令并返回解析后的 JSON"""
        cmd = ["xreach"] + args + ["--json"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30
            )

            if proc.returncode != 0:
                err_msg = stderr.decode().strip()
                logger.error(f"xreach 命令失败: {' '.join(cmd)} → {err_msg}")
                return None

            output = stdout.decode().strip()
            if not output:
                return None

            return json.loads(output)

        except asyncio.TimeoutError:
            logger.error(f"xreach 命令超时: {' '.join(cmd)}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"xreach 输出 JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"xreach 执行异常: {e}")
            return None

    async def _xreach_search(
        self,
        query: str,
        count: int = 20,
    ) -> list[RawArticle]:
        """通过 xreach search 搜索推文

        Args:
            query: 搜索关键词（支持 Twitter 高级搜索语法，如 min_faves:200）
                   支持 {today} 占位符，运行时替换为当天日期（YYYY-MM-DD）
            count: 最大返回数
        """
        # 将 {today} 替换为当天日期，限制搜索范围
        today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        query = query.replace("{today}", today_str)
        data = await self._run_xreach(["search", query, "-n", str(count)])
        if not data:
            return []

        items = data.get("items", [])
        return self._parse_tweets(items, search_query=query)

    async def _xreach_user_tweets(
        self,
        username: str,
        count: int = 10,
    ) -> list[RawArticle]:
        """通过 xreach tweets 获取用户时间线

        Args:
            username: Twitter 用户名（不含 @）
            count: 最大返回数
        """
        data = await self._run_xreach(
            ["tweets", f"@{username}", "-n", str(count)]
        )
        if not data:
            return []

        items = data.get("items", [])
        return self._parse_tweets(items, search_query=f"from:{username}")

    def _parse_tweets(
        self, items: list[dict], search_query: str = ""
    ) -> list[RawArticle]:
        """将 xreach 返回的推文 items 解析为 RawArticle 列表"""
        articles = []

        for tweet in items:
            try:
                tweet_id = tweet.get("id", "")
                text = tweet.get("text", "")

                # 用户信息（搜索模式下 user 可能只有 id/restId，没有 screenName）
                user = tweet.get("user", {})
                username = (
                    user.get("screenName")
                    or user.get("name")
                    or user.get("restId")
                    or "unknown"
                )
                display_name = user.get("name") or username

                # 互动数据
                likes = tweet.get("likeCount", 0) or 0
                retweets = tweet.get("retweetCount", 0) or 0
                replies = tweet.get("replyCount", 0) or 0
                views = tweet.get("viewCount", 0) or 0
                bookmarks = tweet.get("bookmarkCount", 0) or 0
                quotes = tweet.get("quoteCount", 0) or 0

                # 时间
                created_at = tweet.get("createdAt")

                # 语言
                lang = tweet.get("lang")

                # 跳过转发（只保留原创和引用）
                if tweet.get("isRetweet", False):
                    continue

                # 提取推文中的外部链接（从文本中的 https://t.co/ 展开链接）
                urls_in_tweet = []
                # xreach 返回的 media 中可能有链接
                for media in tweet.get("media", []):
                    media_url = media.get("url", "")
                    if media_url:
                        urls_in_tweet.append(media_url)

                article = RawArticle(
                    source_name=f"Twitter @{username}",
                    channel="twitter",
                    title=clean_title(text[:100]),
                    url=f"https://x.com/{username}/status/{tweet_id}",
                    fetched_at=now_iso(),
                    published_at=created_at,
                    author=display_name,
                    summary=text,
                    category="Twitter",
                    language=lang,
                    extra={
                        "likes": likes,
                        "retweets": retweets,
                        "replies": replies,
                        "views": views,
                        "bookmarks": bookmarks,
                        "quotes": quotes,
                        "linked_urls": urls_in_tweet,
                        "search_query": search_query,
                        "is_quote": tweet.get("isQuote", False),
                    },
                )
                articles.append(article)
            except Exception as e:
                logger.debug(f"解析推文失败: {e}")
                continue

        return articles


# ══════════════════════════════════════════
# WeChat Fetcher
# ══════════════════════════════════════════


class WeChatFetcher(BaseFetcher):
    """微信公众号采集器（通过 we-mp-rss 本地服务）

    覆盖公众号（共 36 个，启用 29 个）：
    - AI/科技: 数字生命卡兹克、量子位、机器之心、Founder Park、新智元、白鲸出海、
              极客公园、扬帆出海、AI新榜、AIGC Studio、Tech星球、铼三实验室、
              Z Potentials、暗涌Waves、DataEye、葬AI
    - 游戏: 游戏葡萄、GameLook、竞核、游戏研究社、LitGate
    - 娱乐/短剧: 短剧自习室
    - 游戏官方: 原神、崩坏星穹铁道、网易蛋仔派对、逆水寒手游
    - 其他: 微信公开课、抖音、我的世界Minecraft开发者
    - 禁用: 猫笔刀、寻瑕记、沧海一土狗、冷眼局中人、培风客、沪上十三少、猫笔叨的读后感专区

    工作原理：
    we-mp-rss (v1.4.9) 在 Docker 中运行 RSS 服务，端口 8001。
    RSS feed 路由（无需认证）：
      - 全部 RSS 列表：GET /rss
      - 单个公众号 RSS：GET /feed/{mp_id}.rss
    每个公众号在 config.yaml 中配有 mp_id，直接拼接 feed URL 即可。
    """

    def __init__(self, config: dict, **kwargs):
        super().__init__(config, **kwargs)
        self.wechat_config = (
            self.config.get("collector", {})
            .get("sources", {})
            .get("wechat", {})
        )
        self.base_url = os.getenv(
            "WEMPRSS_BASE_URL",
            self.wechat_config.get("base_url", "http://localhost:8001"),
        )

    async def fetch(self) -> list[RawArticle]:
        """通过 we-mp-rss 本地服务的 RSS feed 采集微信公众号文章"""
        articles = []
        accounts = self.wechat_config.get("accounts", [])
        enabled_accounts = [a for a in accounts if a.get("enabled", True)]

        if not enabled_accounts:
            logger.info("没有启用的微信公众号")
            return []

        # 首先检查 we-mp-rss 服务是否可用
        if not await self._check_service():
            logger.warning(
                f"we-mp-rss 服务不可用 ({self.base_url})，跳过微信采集。"
                f"请确认 Docker 容器正在运行: cd we-mp-rss && ./start.sh status"
            )
            return []

        # ── 微信 RSS 时效性检查（2026-04-16 新增）──
        # 检查 RSS 中最新文章的 pubDate，如果超过 48h 未更新则截停采集
        stale = await self._check_rss_freshness()
        if stale:
            logger.error(
                f"⛔ 微信采集截停: we-mp-rss 数据已过期！\n"
                f"  最新 pubDate: {stale}\n"
                f"  可能原因: Playwright 浏览器崩溃（Event loop is closed）/ 微信登录过期\n"
                f"  修复步骤:\n"
                f"    1. cd we-mp-rss && docker compose restart\n"
                f"    2. bash auto_fetch.sh\n"
                f"    3. 检查 docker compose logs --tail 20 是否有 'Event loop is closed' 错误\n"
                f"    4. 如果仍有错误，尝试 docker compose down && docker compose up -d"
            )
            console.print(
                f"  [red]⛔ 微信采集截停: RSS 数据已过期 (最新 pubDate: {stale})[/red]\n"
                f"  [yellow]请检查 we-mp-rss: cd we-mp-rss && docker compose restart && bash auto_fetch.sh[/yellow]"
            )
            return []

        # 过滤掉没有 mp_id 的账号
        valid_accounts = [
            a for a in enabled_accounts if a.get("mp_id")
        ]
        skipped = len(enabled_accounts) - len(valid_accounts)
        if skipped:
            logger.warning(
                f"跳过 {skipped} 个缺少 mp_id 的公众号"
            )

        semaphore = asyncio.Semaphore(5)

        async def fetch_one(account: dict) -> list[RawArticle]:
            async with semaphore:
                return await self._fetch_account(account)

        tasks = [fetch_one(acct) for acct in valid_accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for acct, result in zip(valid_accounts, results):
            if isinstance(result, Exception):
                logger.error(
                    f"微信采集失败 [{acct['name']}]: {result}"
                )
            else:
                articles.extend(result)
                if result:
                    logger.info(
                        f"微信采集成功 [{acct['name']}]: {len(result)} 篇"
                    )

        return articles

    async def _check_service(self) -> bool:
        """检查 we-mp-rss 服务是否在运行（访问首页）"""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self.base_url, timeout=5, follow_redirects=True
                )
                return resp.status_code < 500
            except Exception:
                return False

    async def _check_rss_freshness(self) -> str | None:
        """检查 we-mp-rss 中最新文章的 pubDate 是否过期（2026-04-16 新增）

        注意：/rss 总览的 pubDate 有缓存问题，不可靠。
        改为抽样检查 3 个活跃公众号的单独 feed。

        Returns:
            None: 数据新鲜，正常继续
            str: 最新 pubDate 字符串（过期时返回，用于报错）
        """
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime

        # 抽样 3 个活跃公众号检查
        accounts = self.wechat_config.get("accounts", [])
        sample_accounts = [
            a for a in accounts
            if a.get("enabled", True) and a.get("mp_id")
        ][:3]

        if not sample_accounts:
            return None

        latest_dt = None
        latest_str = ""

        try:
            async with httpx.AsyncClient() as client:
                for acct in sample_accounts:
                    mp_id = acct["mp_id"]
                    try:
                        resp = await client.get(
                            f"{self.base_url}/feed/{mp_id}.rss", timeout=10
                        )
                        if resp.status_code != 200:
                            continue
                        root = ET.fromstring(resp.text)
                        for item in root.iter("item"):
                            pub_el = item.find("pubDate")
                            if pub_el is not None and pub_el.text:
                                try:
                                    dt = parsedate_to_datetime(pub_el.text)
                                    if latest_dt is None or dt > latest_dt:
                                        latest_dt = dt
                                        latest_str = pub_el.text
                                except Exception:
                                    continue
                    except Exception:
                        continue

            if latest_dt is None:
                return None  # 无法解析，不截停

            # 检查是否超过 48 小时
            now = datetime.now(timezone.utc)
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.replace(
                    tzinfo=timezone(timedelta(hours=8))
                )
            age = now - latest_dt
            if age > timedelta(hours=48):
                return latest_str

            return None  # 数据新鲜
        except Exception as e:
            logger.warning(f"微信 RSS 时效性检查失败: {e}")
            return None  # 检查失败不截停，继续采集

    async def _fetch_account(self, account: dict) -> list[RawArticle]:
        """采集单个微信公众号（仅保留近 max_entry_age_days 天的条目）
        
        通过 we-mp-rss 的 /feed/{mp_id}.rss 路径直接获取 RSS XML。
        该路由无需认证。
        """
        name = account["name"]
        mp_id = account["mp_id"]
        feed_url = f"{self.base_url}/feed/{mp_id}.rss"
        max_age_days = self.config.get("collector", {}).get("max_entry_age_days", 7)

        async with httpx.AsyncClient() as client:
            try:
                resp = await self._request_with_retry(
                    client, feed_url,
                    headers={"User-Agent": "AI-Daily-News/1.0"},
                )
                content = resp.text
            except Exception as e:
                logger.error(f"微信 RSS 请求失败 [{name}]: {e}")
                return []

        # 检查是否返回了 HTML 而非 XML（说明路径不正确或 feed 不存在）
        if content.strip().startswith("<!DOCTYPE") or content.strip().startswith("<html"):
            logger.warning(
                f"微信 RSS [{name}] 返回 HTML 而非 XML，可能 mp_id 不正确: {mp_id}"
            )
            return []

        # feedparser 解析
        feed = feedparser.parse(content)
        if feed.bozo and not feed.entries:
            logger.warning(
                f"微信 RSS 解析异常 [{name}]: {feed.bozo_exception}"
            )
            return []

        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        skipped_old = 0
        seen_titles: set[str] = set()  # 同标题去重（we-mp-rss 同篇文章可能有多个短链URL）
        skipped_dup_title = 0

        for entry in feed.entries:
            entry_url = extract_feed_url(entry)
            if not entry_url:
                continue

            published_at = parse_feed_date(entry)

            # 过滤掉过旧的条目
            if published_at and max_age_days > 0:
                try:
                    from dateutil import parser as dateutil_parser
                    pub_dt = dateutil_parser.parse(published_at)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone(timedelta(hours=8)))
                    if pub_dt.astimezone(timezone.utc) < cutoff:
                        skipped_old += 1
                        continue
                except (ValueError, TypeError):
                    pass  # 解析失败的保留

            # 同标题去重：we-mp-rss 对同一篇推文可能生成多个短链URL（不同群发批次）
            # 同一公众号内，标题相同的只保留第一条
            title = clean_title(entry.get("title", "无标题"))
            if title in seen_titles:
                skipped_dup_title += 1
                continue
            seen_titles.add(title)

            # 提取 description 作为摘要（去掉 HTML 标签）
            summary = entry.get("summary", "") or entry.get("description", "")
            # 简单去 HTML（详细清洗留给 Layer 2）
            if summary and "<" in summary:
                import re
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]

            article = RawArticle(
                source_name=f"微信: {name}",
                channel="wechat",
                title=title,
                url=entry_url,
                fetched_at=now_iso(),
                published_at=published_at,
                author=name,
                summary=summary,
                category="微信公众号",
                language="zh",
                extra={
                    "mp_name": name,
                    "mp_id": mp_id,
                },
            )
            articles.append(article)

        if skipped_old:
            logger.info(f"微信 [{name}]: 跳过 {skipped_old} 篇超过 {max_age_days} 天的旧文章")
        if skipped_dup_title:
            logger.info(f"微信 [{name}]: 跳过 {skipped_dup_title} 篇同标题副本（多URL去重）")

        return articles


# ══════════════════════════════════════════
# Manual Fetcher
# ══════════════════════════════════════════


class ManualFetcher(BaseFetcher):
    """手工输入采集器

    扫描 manual_input/ 目录，支持 3 种格式：
    - .json: 标准 RawArticle JSON 或 JSON 数组
    - .md:   Markdown 格式（# 标题 + [链接](url) + 正文）
    - .txt:  纯文本（每行一个 URL）

    处理完成后移入 manual_input/.processed/
    """

    def __init__(self, config: dict, **kwargs):
        super().__init__(config, **kwargs)
        self.manual_dir = Path(
            self.config.get("global", {}).get(
                "manual_input_dir", "./manual_input"
            )
        )

    async def fetch(self) -> list[RawArticle]:
        """扫描 manual_input/ 目录并解析"""
        if not self.manual_dir.exists():
            logger.debug("manual_input/ 目录不存在")
            return []

        articles = []
        processed_dir = self.manual_dir / ".processed"
        processed_dir.mkdir(exist_ok=True)

        files = list(self.manual_dir.glob("*"))
        for file_path in files:
            if file_path.is_dir():
                continue
            if file_path.name.startswith("."):
                continue

            try:
                result = self._parse_file(file_path)
                articles.extend(result)

                if result:
                    logger.info(
                        f"手工输入解析成功 [{file_path.name}]: {len(result)} 篇"
                    )
                    # 移入已处理目录
                    dest = processed_dir / file_path.name
                    # 如果目标存在，加时间戳避免覆盖
                    if dest.exists():
                        stem = file_path.stem
                        suffix = file_path.suffix
                        ts = datetime.now().strftime("%H%M%S")
                        dest = processed_dir / f"{stem}_{ts}{suffix}"
                    shutil.move(str(file_path), str(dest))
            except Exception as e:
                logger.error(f"手工输入解析失败 [{file_path.name}]: {e}")

        return articles

    def _parse_file(self, file_path: Path) -> list[RawArticle]:
        """根据文件扩展名选择解析方式"""
        suffix = file_path.suffix.lower()
        content = file_path.read_text(encoding="utf-8").strip()

        if not content:
            return []

        if suffix == ".json":
            return self._parse_json(content, file_path.name)
        elif suffix == ".md":
            return self._parse_markdown(content, file_path.name)
        elif suffix == ".txt":
            return self._parse_txt(content, file_path.name)
        else:
            logger.warning(f"不支持的文件格式: {suffix}")
            return []

    def _parse_json(self, content: str, filename: str) -> list[RawArticle]:
        """解析 JSON 格式"""
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]

        articles = []
        for item in data:
            article = RawArticle(
                source_name=item.get("source_name", f"手工: {filename}"),
                channel="manual",
                title=clean_title(item.get("title", "无标题")),
                url=item.get("url", ""),
                fetched_at=now_iso(),
                published_at=item.get("published_at"),
                author=item.get("author"),
                summary=item.get("summary", ""),
                category=item.get("category", "手工输入"),
                language=item.get("language"),
                extra={"source_file": filename},
            )
            if article.url:
                articles.append(article)

        return articles

    def _parse_markdown(self, content: str, filename: str) -> list[RawArticle]:
        """解析 Markdown 格式

        预期格式：
        # 文章标题
        [链接文字](url)
        正文/摘要...
        """
        import re

        articles = []
        # 按 Markdown 标题分割
        sections = re.split(r"^#\s+", content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n", 1)
            title = clean_title(lines[0])
            body = lines[1].strip() if len(lines) > 1 else ""

            # 提取链接
            url_match = re.search(r"\[.*?\]\((https?://[^\)]+)\)", body)
            url = url_match.group(1) if url_match else ""

            if not url:
                # 尝试直接找 URL
                url_match = re.search(r"(https?://\S+)", body)
                url = url_match.group(1) if url_match else ""

            if url:
                article = RawArticle(
                    source_name=f"手工: {filename}",
                    channel="manual",
                    title=title,
                    url=url,
                    fetched_at=now_iso(),
                    summary=body[:300] if body else "",
                    category="手工输入",
                    extra={"source_file": filename},
                )
                articles.append(article)

        return articles

    def _parse_txt(self, content: str, filename: str) -> list[RawArticle]:
        """解析纯文本（每行一个 URL）"""
        import re

        articles = []
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            url_match = re.search(r"(https?://\S+)", line)
            if url_match:
                url = url_match.group(1)
                article = RawArticle(
                    source_name=f"手工: {filename}",
                    channel="manual",
                    title=url,  # 暂用 URL 做标题，后续 Layer 2 可抓取真实标题
                    url=url,
                    fetched_at=now_iso(),
                    category="手工输入",
                    extra={"source_file": filename},
                )
                articles.append(article)

        return articles


# ══════════════════════════════════════════
# 主入口：run_collector
# ══════════════════════════════════════════


def run_collector(config: dict, data_dir: Path) -> dict:
    """
    Layer 1 主函数：运行所有 Fetcher，汇总输出 raw.json

    Args:
        config: 全局配置字典（来自 config.yaml）
        data_dir: 当日数据目录（如 data/2026-04-13/）

    Returns:
        raw.json 的内容字典
    """
    return asyncio.run(_async_run_collector(config, data_dir))


async def _async_run_collector(config: dict, data_dir: Path) -> dict:
    """异步执行所有 Fetcher"""
    collector_config = config.get("collector", {})
    timeout = collector_config.get("request_timeout_seconds", 15)
    max_retries = collector_config.get("max_retries", 2)
    retry_delay = collector_config.get("retry_delay_seconds", 5)

    fetcher_kwargs = {
        "timeout": timeout,
        "max_retries": max_retries,
        "retry_delay": retry_delay,
    }

    # 初始化所有 Fetcher
    rss_fetcher = RSSFetcher(config, **fetcher_kwargs)
    exa_fetcher = ExaFetcher(config, **fetcher_kwargs)
    fetchers = {
        "rss": rss_fetcher,
        "github": GitHubFetcher(config, **fetcher_kwargs),
        "exa": exa_fetcher,
        "twitter": TwitterFetcher(config, **fetcher_kwargs),
        "wechat": WeChatFetcher(config, **fetcher_kwargs),
        "manual": ManualFetcher(config, **fetcher_kwargs),
    }

    all_articles: list[RawArticle] = []
    stats_by_channel: dict[str, int] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("采集中...", total=len(fetchers))

        # 按渠道依次运行
        for channel_name, fetcher in fetchers.items():
            progress.update(task, description=f"采集: {channel_name}")

            # RSS 完成后，将失败源和降级源注入 Exa 进行兜底/永久替代
            if channel_name == "exa":
                # 偶发兜底：本次失败的源
                if rss_fetcher.failed_sources:
                    exa_fetcher.fallback_sources = rss_fetcher.failed_sources
                    console.print(
                        f"  🔄 {len(rss_fetcher.failed_sources)} 个 RSS 失败源将由 Exa 兜底"
                    )
                # 永久替代：连续 ≥3 天失败的源
                if rss_fetcher.degraded_sources:
                    exa_fetcher.degraded_sources = rss_fetcher.degraded_sources
                    console.print(
                        f"  ⚠️ {len(rss_fetcher.degraded_sources)} 个 RSS 源已降级为 Exa 永久替代"
                    )
                    for ds in rss_fetcher.degraded_sources:
                        console.print(f"     → {ds['name']}")

            try:
                articles = await fetcher.fetch()
                all_articles.extend(articles)
                stats_by_channel[channel_name] = len(articles)
                console.print(
                    f"  📡 {channel_name}: {len(articles)} 篇"
                )
            except Exception as e:
                logger.error(f"Fetcher [{channel_name}] 异常: {e}")
                stats_by_channel[channel_name] = 0
                console.print(
                    f"  ❌ {channel_name}: 失败 ({e})"
                )
            progress.advance(task)

    # ── 公众号与 RSS 去重：同名源优先公众号 ──
    # 定义公众号与 RSS 同名映射（公众号名 → RSS source_name）
    wechat_rss_overlap = {
        "GameLook": ["GameLook"],
        "量子位": ["量子位"],
        "游戏研究社": ["游戏研究社"],
        "白鲸出海": ["白鲸出海"],
        "极客公园": ["极客公园"],
        "竞核": ["竞核"],
        "新智元": ["新智元"],
        "机器之心": ["机器之心"],
        "扬帆出海": ["扬帆出海"],
    }
    # 检查哪些公众号实际采到了文章
    wechat_sources_with_articles = set()
    for a in all_articles:
        if a.channel == "wechat":
            # source_name 格式为 "微信: XXX"
            mp_name = a.source_name.replace("微信: ", "")
            wechat_sources_with_articles.add(mp_name)

    # 如果公众号有文章，去掉同名 RSS 的文章
    rss_names_to_remove = set()
    for mp_name, rss_names in wechat_rss_overlap.items():
        if mp_name in wechat_sources_with_articles:
            rss_names_to_remove.update(rss_names)

    if rss_names_to_remove:
        before_count = len(all_articles)
        all_articles = [
            a for a in all_articles
            if not (a.channel == "rss" and a.source_name in rss_names_to_remove)
        ]
        deduped = before_count - len(all_articles)
        if deduped:
            console.print(
                f"\n  🔀 公众号优先去重: 移除 {deduped} 篇同名 RSS 文章 "
                f"({', '.join(rss_names_to_remove)})"
            )

    # 构建输出
    date_str = data_dir.name
    output = {
        "date": date_str,
        "collected_at": now_iso(),
        "stats": {
            "total": len(all_articles),
            "by_channel": stats_by_channel,
        },
        "articles": [asdict(a) for a in all_articles],
    }

    # 写入 raw.json
    output_path = data_dir / "raw.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    console.print(f"\n  💾 已保存: {output_path}")
    console.print(f"  📊 总计: {len(all_articles)} 篇文章")
    for ch, count in stats_by_channel.items():
        console.print(f"      {ch}: {count}")

    return output
