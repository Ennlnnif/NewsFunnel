"""
Layer 2: 筛选（Filter）

职责：对 raw.json 去重、相关性筛选、热度评分、过滤，输出 filtered.json
原则：去噪声、排优先级，但不生成新内容
约束：规则为主、CodeBuddy 为辅。关键词硬筛是主力，CodeBuddy 仅用于边界去噪/捞漏。
      CodeBuddy 不可用时自动 fallback 到纯关键词筛选。

两道漏斗：
  第一道：相关性硬筛（是不是我关注的领域？）+ CodeBuddy 轻筛（去噪 + 捞漏）
  第二道：热度软排（在关注的领域里，哪些值得看？）

CodeBuddy 轻筛工作流（不依赖任何外部 API）：
  1. filter.py 运行 Step 3 后，导出候选文章到 llm_filter_input.json
  2. CodeBuddy 在对话中读取候选文章，按 Prompt 模板生成判断结果
  3. 写入 data/{date}/llm_filter_results.json
  4. 重新运行 filter.py → 自动加载结果 → 应用去噪/捞漏
"""

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from rich.console import Console
from rich.table import Table

logger = logging.getLogger("filter")
console = Console()

# 微信公众号源名称前缀（格式："微信: 量子位"）
# len("微信: ") = 4（两个中文字符 + 冒号 + 空格）
WECHAT_PREFIX = "微信: "


def _stable_id(prefix: str, art: dict) -> str:
    """基于标题的稳定哈希ID，不随文章顺序变化"""
    content = art.get('title', '')
    return f"{prefix}{hashlib.sha256(content.encode()).hexdigest()[:8]}"


# ══════════════════════════════════════════
# Step 1: Normalize（标准化）
# ══════════════════════════════════════════


class Normalizer:
    """标准化单篇文章：时间、HTML、URL、标题"""

    def __init__(self, url_strip_params: list[str] | None = None):
        self.url_strip_params = set(url_strip_params or [])
        # 标题噪声前缀
        self._title_noise = re.compile(
            r"^(转载\s*[|｜]\s*|【[^】]{1,6}】\s*|\[[^\]]{1,6}\]\s*)"
        )

    def normalize(self, article: dict) -> dict:
        """标准化单篇文章，返回修改后的 article（原地修改）"""
        # 1. 时间格式统一
        article["_published_dt"] = self._parse_time(article.get("published_at"))
        article["_fetched_dt"] = self._parse_time(article.get("fetched_at"))

        # 2. HTML 清洗 → summary_clean
        raw_summary = article.get("summary") or ""
        article["summary_clean"] = self._clean_html(raw_summary)

        # 3. URL 归一化
        article["_normalized_url"] = self._normalize_url(article.get("url", ""))

        # 4. 标题清洗
        article["title"] = self._clean_title(article.get("title", ""))

        return article

    def _parse_time(self, time_str: str | None) -> datetime | None:
        if not time_str:
            return None
        try:
            dt = dateutil_parser.parse(time_str)
            # 如果没有时区信息，假设为 UTC+8
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            return dt
        except (ValueError, TypeError):
            return None

    def _clean_html(self, html: str) -> str:
        if not html or "<" not in html:
            return html.strip()
        try:
            soup = BeautifulSoup(html, "html.parser")
            # 移除 script/style/img 标签
            for tag in soup.find_all(["script", "style", "img"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # 压缩连续空行
            text = re.sub(r"\n{3,}", "\n\n", text)
            # 截断过长摘要（保留前 500 字符）
            if len(text) > 500:
                text = text[:500] + "..."
            return text
        except Exception:
            return html[:500]

    def _normalize_url(self, url: str) -> str:
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            # 去除 tracking 参数
            if parsed.query:
                params = parse_qs(parsed.query, keep_blank_values=True)
                cleaned = {
                    k: v for k, v in params.items() if k not in self.url_strip_params
                }
                new_query = urlencode(cleaned, doseq=True) if cleaned else ""
            else:
                new_query = ""
            # 去除 fragment，去除尾部斜杠
            normalized = urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"),
                 parsed.params, new_query, "")
            )
            return normalized
        except Exception:
            return url

    def _clean_title(self, title: str) -> str:
        if not title:
            return "无标题"
        title = " ".join(title.strip().split())  # 压缩空白
        title = self._title_noise.sub("", title)  # 去噪声前缀
        if len(title) > 200:
            title = title[:200] + "..."
        return title


class TitleBlacklist:
    """标题黑名单过滤器：识别并标记论坛列表页、聚合页等非文章内容

    设计原则：
      - 仅拦截论坛列表页、标签聚合页等**技术性非文章页面**
      - 多事件聚合栏目（晚报/周报/速递等）不在此拦截，
        这些内容包含有价值的独立新闻，由 Layer 3 LLM 编辑阶段拆分处理
    """

    # 标题黑名单模式（正则，大小写不敏感）
    TITLE_PATTERNS = [
        # ── 论坛/聚合页（技术性非文章页面）──
        r"^Latest\s+\w+\s+topics",          # 论坛列表页
        r"^Tag\s*:",                          # 标签聚合页
        r"^Category\s*:",                     # 分类聚合页
        r"^Archive",                          # 归档页
        r"^Page\s+\d+",                       # 分页
        r"^Index\s+of\s+",                    # 目录页
        r"^All\s+(posts|articles|topics)",    # 全部文章页
        r"^\d+\s+new\s+topics",              # 论坛新帖汇总
        r"^Forum\s*[-–:]\s",                 # 论坛首页
        r"^(Home|首页)\s*[-–|]",             # 网站首页
    ]

    def __init__(self):
        self._patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TITLE_PATTERNS
        ]

    def is_blacklisted(self, title: str) -> bool:
        """检查标题是否命中黑名单"""
        for pattern in self._patterns:
            if pattern.search(title):
                return True
        return False


class AggregateDetector:
    """聚合新闻检测器：标记多事件拼盘类文章，供 Layer 3 拆分处理

    这些文章包含多条独立新闻（如晚报、周报、速递），不应被拦截，
    但需要在 LLM 编辑阶段拆分为独立事件再生成 summary。
    """

    AGGREGATE_PATTERNS = [
        r"[|｜丨].*晚报",
        r"晚报[|｜丨]",
        r"[|｜丨].*早报",
        r"早报[|｜丨]",
        r"[|｜丨].*周报",
        r"周报[|｜丨$]",
        r"一周(要闻|回顾|速览|盘点|热点)",
        r"一周说",
        r"^速递[|｜]",
        r"速递[|｜]",
        r"Tech周报",
        r"weekly\s*(roundup|digest|recap|wrap)",
        r"daily\s*(digest|brief|wrap)",
    ]

    def __init__(self):
        self._patterns = [
            re.compile(p, re.IGNORECASE) for p in self.AGGREGATE_PATTERNS
        ]

    def is_aggregate(self, title: str) -> bool:
        """检查标题是否为聚合新闻"""
        for pattern in self._patterns:
            if pattern.search(title):
                return True
        return False


# ══════════════════════════════════════════
# Step 2: Dedup（去重 + 覆盖广度计算）
# ══════════════════════════════════════════


class DedupEngine:
    """两级去重引擎 + 覆盖广度计算"""

    def __init__(self, window_hours: int = 72, similarity_threshold: float = 0.85,
                 source_weight_fn=None):
        self.window_hours = window_hours
        self.threshold = similarity_threshold
        self._source_weight_fn = source_weight_fn  # 可选：(source_name) -> int
        self._url_set: set[str] = set()
        # (title, url, source_name, channel, article_index)
        self._title_index: list[tuple[str, str, str, str, int]] = []
        # dup_group_id → list of article indices
        self._dup_groups: dict[str, list[int]] = defaultdict(list)
        # 微信历史标题集合：微信文章 URL 每次可能不同（we-mp-rss 多短链），
        # 但标题是稳定的，用标题做历史去重
        self._wechat_history_titles: set[str] = set()

    def load_history(self, past_filtered_files: list[Path]):
        """从前几天的 filtered.json 加载去重窗口"""
        for fpath in past_filtered_files:
            if not fpath.exists():
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                for art in data.get("articles", []):
                    url = art.get("_normalized_url") or art.get("url", "")
                    if url:
                        self._url_set.add(url)
                    title = art.get("title", "")
                    if title:
                        self._title_index.append(
                            (title, url, art.get("source_name", ""),
                             art.get("channel", ""), -1)
                        )
                        # 收集微信历史标题
                        if art.get("channel") == "wechat":
                            self._wechat_history_titles.add(title)
            except Exception as e:
                logger.warning(f"加载历史去重文件失败 {fpath}: {e}")
        if self._wechat_history_titles:
            logger.info(f"历史微信标题去重库: {len(self._wechat_history_titles)} 个标题")

    def load_github_seen(self, seen_path: Path):
        """加载 GitHub 持久化去重库（2026-04-16 新增）

        GitHub Trending 的同一项目会连续多天上榜，72h 滑动窗口会导致
        周期性"老项目"重新涌入。改用永久去重：已入选过的 GitHub URL 不再重复入选。

        存储格式（dict，含元数据供查阅概览）：
        {
            "https://github.com/user/repo": {
                "title": "user/repo",
                "first_seen": "2026-04-16",
                "stars": 18224
            }
        }
        """
        self._github_seen_path = seen_path
        self._github_seen_data: dict[str, dict] = {}
        self._github_seen_urls: set[str] = set()
        if seen_path.exists():
            try:
                raw = json.loads(seen_path.read_text(encoding="utf-8"))
                # 兼容旧格式（纯 URL 列表）
                if isinstance(raw, list):
                    self._github_seen_data = {url: {"title": "", "first_seen": "", "stars": 0} for url in raw}
                else:
                    self._github_seen_data = raw
                self._github_seen_urls = set(self._github_seen_data.keys())
                logger.info(f"GitHub 持久去重库: {len(self._github_seen_urls)} 个项目")
            except Exception as e:
                logger.warning(f"加载 GitHub 去重库失败: {e}")

    def save_github_seen(self, new_articles: list[dict], date: str):
        """将新入选的 GitHub 项目追加到持久去重库（含元数据）"""
        if not hasattr(self, '_github_seen_path'):
            return
        for art in new_articles:
            url = (art.get("_normalized_url") or art.get("url", "")).rstrip("/")
            if not url:
                continue
            if url not in self._github_seen_data:
                self._github_seen_data[url] = {
                    "title": art.get("title", ""),
                    "first_seen": date,
                    "stars": (art.get("extra") or {}).get("stars", 0) or 0,
                }
        self._github_seen_urls = set(self._github_seen_data.keys())
        # 按 first_seen 降序排列（最新的在前）
        sorted_data = dict(sorted(
            self._github_seen_data.items(),
            key=lambda x: x[1].get("first_seen", ""),
            reverse=True,
        ))
        self._github_seen_path.write_text(
            json.dumps(sorted_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"GitHub 持久去重库更新: +{len(new_articles)} → 共 {len(self._github_seen_data)} 个项目")

    def process(self, articles: list[dict]) -> list[dict]:
        """
        处理所有文章：去重 + 计算覆盖广度。
        返回去重后的唯一文章列表，每篇附带 coverage_count。
        重复文章中选择源权重最高的作为代表。
        """
        # 第一遍：URL 精确去重（跟历史）
        url_deduped = []
        for art in articles:
            norm_url = art.get("_normalized_url", "")
            if norm_url and norm_url in self._url_set:
                art["is_duplicate"] = True
                art["_dup_reason"] = f"url_history:{norm_url[:60]}"
                continue
            if norm_url:
                self._url_set.add(norm_url)
            url_deduped.append(art)

        # 第 1.3 遍：GitHub 持久化去重（2026-04-16 新增）
        # GitHub Trending 同一项目连续上榜多天，72h 窗口会周期性放行"老项目"
        # 改用永久去重：已入选过 filtered.json 的 GitHub URL 不再重复进入
        github_seen_urls = getattr(self, '_github_seen_urls', set())
        if github_seen_urls:
            github_persistent_deduped = []
            github_persistent_dup_count = 0
            for art in url_deduped:
                if art.get("channel") == "github":
                    norm_url = art.get("_normalized_url", "") or art.get("url", "")
                    if norm_url and norm_url.rstrip("/") in github_seen_urls:
                        art["is_duplicate"] = True
                        art["_dup_reason"] = f"github_seen:{norm_url[:60]}"
                        github_persistent_dup_count += 1
                        continue
                github_persistent_deduped.append(art)
            if github_persistent_dup_count:
                logger.info(f"GitHub 持久去重: 淘汰 {github_persistent_dup_count} 篇已入选过的项目")
            url_deduped = github_persistent_deduped

        # 第 1.5 遍：微信标题历史去重
        # we-mp-rss 对同一篇推文可能生成不同短链URL（不同群发批次），
        # 导致 URL 历史去重漏网。微信标题是稳定的，用标题补充去重。
        wechat_title_deduped = []
        wechat_title_dup_count = 0
        for art in url_deduped:
            if art.get("channel") == "wechat":
                title = art.get("title", "")
                if title in self._wechat_history_titles:
                    art["is_duplicate"] = True
                    art["_dup_reason"] = f"wechat_title_history:{title[:40]}"
                    wechat_title_dup_count += 1
                    continue
                # 加入历史，防止当天内部同标题重复
                self._wechat_history_titles.add(title)
            wechat_title_deduped.append(art)

        if wechat_title_dup_count:
            logger.info(f"微信标题历史去重: 淘汰 {wechat_title_dup_count} 篇")

        # 第二遍：标题模糊去重（当天内部）
        # 将文章分组：相似标题归为同一 group
        groups: list[list[dict]] = []
        used = [False] * len(wechat_title_deduped)

        for i, art_i in enumerate(wechat_title_deduped):
            if used[i]:
                continue
            group = [art_i]
            used[i] = True
            title_i = art_i["title"]
            for j in range(i + 1, len(wechat_title_deduped)):
                if used[j]:
                    continue
                title_j = wechat_title_deduped[j]["title"]
                # 快速过滤：长度差距太大直接跳过
                if abs(len(title_i) - len(title_j)) > max(len(title_i), len(title_j)) * 0.4:
                    continue
                ratio = SequenceMatcher(None, title_i, title_j).ratio()
                if ratio >= self.threshold:
                    group.append(wechat_title_deduped[j])
                    used[j] = True
            groups.append(group)

        # 第三遍：摘要级事件去重（2026-04-14 新增）
        # 标题不同但摘要高度相似的文章，很可能是同一事件的不同源/角度
        # 例如："荣耀发布AI PC" vs "AI智能体落地：个人电脑养虾" → 标题不像，但摘要核心相同
        summary_merged_groups: list[list[dict]] = []
        group_used = [False] * len(groups)
        SUMMARY_DEDUP_THRESHOLD = 0.50  # 摘要相似度阈值（低于标题，因为摘要更长更宽泛）
        SUMMARY_COMPARE_LEN = 150       # 只比较摘要前 N 字符

        for i, group_i in enumerate(groups):
            if group_used[i]:
                continue
            merged = list(group_i)
            group_used[i] = True
            summary_i = (group_i[0].get("summary_clean", "") or "")[:SUMMARY_COMPARE_LEN]
            if len(summary_i) < 30:  # 摘要太短不做摘要去重
                summary_merged_groups.append(merged)
                continue
            for j in range(i + 1, len(groups)):
                if group_used[j]:
                    continue
                summary_j = (groups[j][0].get("summary_clean", "") or "")[:SUMMARY_COMPARE_LEN]
                if len(summary_j) < 30:
                    continue
                ratio = SequenceMatcher(None, summary_i, summary_j).ratio()
                if ratio >= SUMMARY_DEDUP_THRESHOLD:
                    merged.extend(groups[j])
                    group_used[j] = True
            summary_merged_groups.append(merged)

        # 第四遍：从每个 group 选出代表，计算覆盖广度
        result = []
        for group in summary_merged_groups:
            # 覆盖广度
            unique_channels = len(set(a["channel"] for a in group))
            unique_sources = len(set(a["source_name"] for a in group))
            coverage_count = len(group)

            # 选代表：优先源权重高的，权重相同选最长 summary
            if self._source_weight_fn:
                representative = max(
                    group,
                    key=lambda a: (
                        self._source_weight_fn(a.get("source_name", "")),
                        len(a.get("summary_clean", "")),
                    ),
                )
            else:
                representative = max(group, key=lambda a: len(a.get("summary_clean", "")))
            representative["is_duplicate"] = False
            representative["coverage_count"] = coverage_count
            representative["_coverage_channels"] = unique_channels
            representative["_coverage_sources"] = unique_sources

            # 标记其余为重复
            for art in group:
                if art is not representative:
                    art["is_duplicate"] = True
                    art["_dup_reason"] = f"title_similar:{representative['title'][:40]}"

            result.append(representative)

        logger.info(
            f"去重完成: {len(articles)} → URL去重后 {len(url_deduped)} → "
            f"微信标题去重后 {len(wechat_title_deduped)} → "
            f"标题去重后 {len(groups)} 组 → 摘要去重后 {len(summary_merged_groups)} 组 → "
            f"最终 {len(result)} 篇"
        )
        return result


# ══════════════════════════════════════════
# Step 3: Relevance（相关性硬筛）
# ══════════════════════════════════════════


class RelevanceFilter:
    """双层关键词相关性筛选 + GitHub Search query 标签继承

    三路相关性信号（OR 关系）：
      ① Search query 标签继承 — GitHub Search API 来的项目自动获得 query 对应标签
      ② 双层关键词匹配 — signals + brands 对 title + summary + topics 做匹配
      ③ 渠道通行证 — manual 直接通过（GitHub 已移除通行证）

    双层关键词体系：
      signals — 领域通用概念词（覆盖新品）
      brands  — 具体产品/公司名（精确命中已知目标）
      两层 OR 关系：命中任意一个就匹配

    英文词边界保护：
      所有纯 ASCII 关键词自动启用词边界匹配（\\b），
      避免 "Unity" 匹配 "opportunity"、"Cohere" 匹配 "coherent" 等子串误命中。
      中文词始终用子串匹配（中文无自然词边界）。
    """

    def __init__(self, config: dict):
        self.tags_config = config.get("relevance_tags", {})
        self.always_pass = set(config.get("always_pass_sources", []))
        self.always_pass_channels = set(config.get("always_pass_channels", []))

        # 预编译关键词（只用 signals，brands 不参与硬筛）
        # brands 保留在 config 中作为 LLM 分类的参考，但不影响关键词匹配
        # 原因：brands 噪音大（如 "OpenAI" 出现在收购新闻中也命中 ai_core）
        self._compiled_tags: dict[str, dict] = {}
        for tag_name, tag_conf in self.tags_config.items():
            raw_signals = tag_conf.get("signals", [])
            raw_keywords = tag_conf.get("keywords", [])  # 兼容旧配置

            # 只编译 signals（不编译 brands）
            compiled = []
            for kw in raw_signals:
                compiled.append(self._compile_keyword(kw, "signal"))
            for kw in raw_keywords:
                compiled.append(self._compile_keyword(kw, "signal"))

            self._compiled_tags[tag_name] = {
                "matchers": compiled,
                "priority": tag_conf.get("priority", "core"),
                "require_signal": tag_conf.get("require_signal", False),
                "company_whitelist": [
                    c.lower() for c in tag_conf.get("company_whitelist", [])
                ],
            }

    def _compile_keyword(self, kw: str, layer: str) -> tuple:
        """编译单个关键词，返回 (match_type, pattern, kw_lower, layer)

        纯 ASCII 关键词一律用词边界匹配（\\b），避免子串误命中：
          - "Unity" 不会匹配 "opportunity"
          - "Cohere" 不会匹配 "coherent"
          - "o1" 不会匹配 "o1签证"

        含中文的关键词用子串匹配（中文无自然词边界）。
        """
        kw_lower = kw.lower()
        if self._is_ascii_keyword(kw):
            pattern = re.compile(r'\b' + re.escape(kw_lower) + r'\b', re.IGNORECASE)
            return ("regex", pattern, kw_lower, layer)
        else:
            return ("substr", None, kw_lower, layer)

    @staticmethod
    def _is_ascii_keyword(word: str) -> bool:
        """判断是否为纯 ASCII 关键词（需要词边界保护）

        所有纯 ASCII 关键词都启用词边界匹配，不限长度。
        中文/混合词返回 False，使用子串匹配。
        """
        return word.isascii() and len(word) > 0

    def _match_any(self, matchers: list, text: str) -> tuple[bool, list[str]]:
        """在 text 中尝试匹配任意一个关键词，返回 (hit, matched_layers)"""
        matched_layers = []
        for match_type, pattern, kw_lower, layer in matchers:
            if match_type == "regex":
                if pattern.search(text):
                    matched_layers.append(layer)
            else:
                if kw_lower in text:
                    matched_layers.append(layer)
        return len(matched_layers) > 0, matched_layers

    def check(self, article: dict) -> tuple[bool, list[str], str]:
        """
        检查文章是否通过相关性筛选。

        三路信号（OR 关系）：
          ① GitHub Search query tag 继承（search_query_tag → relevance_tag）
          ② 关键词匹配（title + summary + topics）
          ③ 渠道通行证（仅 manual）

        返回: (is_relevant, matched_tags, priority)
          priority: "core" | "supplementary" | "fyi" | "none"

        附加元数据（写入 article）：
          _match_type: "signal_only" | "none"
          _match_count: 命中关键词总数
          _match_in_title: 标题中是否有命中
        """
        source = article.get("source_name", "")
        channel = article.get("channel", "")
        extra = article.get("extra") or {}

        matched_tags = []
        best_priority = "none"
        priority_order = {"core": 0, "supplementary": 1, "fyi": 2, "none": 3}

        # 用于记录匹配元数据
        all_matched_layers: list[str] = []
        total_match_count = 0

        # ── 信号路 ①：GitHub Search query tag 继承 ──
        search_query_tag = extra.get("search_query_tag", "")
        if search_query_tag and search_query_tag in self._compiled_tags:
            matched_tags.append(search_query_tag)
            tag_priority = self._compiled_tags[search_query_tag]["priority"]
            if priority_order.get(tag_priority, 3) < priority_order.get(best_priority, 3):
                best_priority = tag_priority
            article["_search_tag_inherited"] = True

        # ── 信号路 ②：关键词匹配 ──
        topics_str = ""
        if channel == "github":
            topics = extra.get("topics", [])
            if topics:
                topics_str = " " + " ".join(topics)
            repo_lang = extra.get("repo_language", "")
            if repo_lang:
                topics_str += f" {repo_lang}"

        title_text = article["title"].lower()
        # 限制 summary_clean 匹配长度：只用前 500 字符
        # 防止 RSS 全文（如 Pluralistic 2万字）中偶然出现的关键词导致误命中
        summary_truncated = (article.get("summary_clean", "") or "")[:500]
        text = f"{article['title']} {summary_truncated}{topics_str}".lower()

        for tag_name, tag_info in self._compiled_tags.items():
            hit, layers = self._match_any(tag_info["matchers"], text)

            if not hit:
                continue

            # 对 fyi 标签（ai_business），还需检查公司白名单
            if tag_info["priority"] == "fyi" and tag_info["company_whitelist"]:
                company_hit = any(c in text for c in tag_info["company_whitelist"])
                if not company_hit:
                    continue

            if tag_name not in matched_tags:
                matched_tags.append(tag_name)
            tag_priority = tag_info["priority"]
            if priority_order.get(tag_priority, 3) < priority_order.get(best_priority, 3):
                best_priority = tag_priority

            all_matched_layers.extend(layers)
            total_match_count += len(layers)

        # 计算匹配元数据
        has_signal = "signal" in all_matched_layers
        match_type = "signal_only" if has_signal else "none"

        # 检查标题是否有命中
        title_hit = False
        for tag_info in self._compiled_tags.values():
            hit_t, _ = self._match_any(tag_info["matchers"], title_text)
            if hit_t:
                title_hit = True
                break

        article["_match_type"] = match_type
        article["_match_count"] = total_match_count
        article["_match_in_title"] = title_hit

        # ── 渠道通行证（manual + wechat）──
        # manual: 手工输入已是人工判断
        # wechat: 29个精选公众号，标题"吸睛体"+摘要极短导致signals命中率低，交给LLM分类
        is_channel_pass = channel in self.always_pass_channels
        is_always_pass = source in self.always_pass

        if is_channel_pass and not matched_tags:
            matched_tags = ["_channel_pass"]
            best_priority = "supplementary"
        elif is_channel_pass and best_priority == "none":
            best_priority = "supplementary"

        # 白名单源（旧逻辑兼容）
        if is_always_pass and not matched_tags:
            matched_tags = ["_always_pass"]
            best_priority = "core"
        elif is_always_pass and best_priority == "none":
            best_priority = "core"

        is_relevant = len(matched_tags) > 0
        return is_relevant, matched_tags, best_priority


# ══════════════════════════════════════════
# Step 3b/3c: LLM 轻筛（去噪 + 捞漏）
# ══════════════════════════════════════════


class LLMLightFilter:
    """LLM 智能分类：关键词粗筛 + CodeBuddy 精准分类

    两阶段工作流：
      Step 3b: 全量分类 — 对所有关键词通过的文章做语义分类
               判断相关性 + 主标签(primary_tag)
      Step 3c: 捞漏 — 扫描关键词未命中的文章找回间接表达的相关内容

    工作流（不依赖任何外部 API）：
      1. filter.py 运行到 Step 3b/3c 时，检查 llm_filter_results.json
      2. 如果文件存在 → 读取 CodeBuddy 预生成的分类结果
      3. 如果文件不存在 → 导出待审文章到 llm_filter_input.json
      4. CodeBuddy 根据 Prompt 模板生成判断结果，重新运行即可

    关键词硬筛只用 signals（判断"跟 AI 有没有关系"），板块归属由 LLM 决定。
    """

    # ── Prompt 模板（参考标准） ──

    CLASSIFY_PROMPT = """你是一个 AI 行业资讯分类器。严格按以下规则判断每篇文章。

我的日报有以下板块：
- ai_agent: AI Agent 具体产品/项目（限事实性新闻）。包括：Agent产品发布/更新/功能上线、Agent项目开源/demo、AI编程助手新版本（Cursor/Copilot/Claude Code功能更新）、Agent游戏化社交产品（斯坦福AI小镇/扣子养虾）。**不含**：Agent开发框架新版本发布（LangChain/CrewAI/Dify等→not_relevant）、Agent基础设施（沙箱/治理/编排/权限管控→not_relevant）、Agent合规风险（企业治理/合规框架→not_relevant）、Agent公司融资（→ai_business）、Agent产品的争议/吐槽/社区声讨（→opinion）
- ai_video: AI视频/影像/音频 具体产品/工具/作品（限事实性新闻）。包括：AI视频生成模型发布/更新（Sora/Vidu/Kling新版本）、AI短剧/动画作品发布、AI图像生成工具新版本、具体的AI视频制作工具上线、TTS/语音合成模型发布（Flash TTS/Fish Audio等）。**不含**：AI视频行业趋势分析（→opinion）
- ai_gaming: AI+游戏 具体产品/项目（限事实性新闻）。包括：AI原生游戏项目发布/demo、AI NPC/AI剧情生成工具上线、AI UGC关卡编辑器产品、AI桌面宠物、AI桌面助手、世界模型产品发布/开源（腾讯混元世界模型/Happy Oyster等）。**不含**：纯游戏行业新闻（营收/人事/评测）、AI游戏行业趋势分析（→opinion）
- ai_social: AI社交 具体产品（限事实性新闻）。包括：AI社交软件发布/更新（AI版微信/XChat等）、AI虚拟伴侣/角色扮演社交平台上线、AI+传统社交产品的功能结合（如社交App新增AI功能）、AI聊天产品。**不含**：宏观社会影响讨论（→opinion）
- ai_core: AI核心技术 具体模型/系统发布（限事实性新闻）。包括：大模型发布/开源（GPT-5/Claude/Gemma新版）、具身智能产品发布。**不含**：模型横评综述/行业报告（→opinion）、芯片硬件（→not_relevant）、世界模型（→ai_gaming）、TTS/语音模型（→ai_video）
- ai_business: AI商业动态（行业事件）。包括：投融资/收购/IPO/营收财报、公司竞争策略（内部信/定价/市场份额）、AI产品出海商业化数据
- ai_product: 其他AI产品/工具（限具体产品的事实性新闻）。不属于上面任何垂直板块的AI工具发布/更新。包括：AI办公工具、AI搜索产品、训练框架/推理引擎开源发布、具体的技术突破论文（CVPR/ICLR等顶会）。**不含**：AI工具使用体验/评测文（→opinion）
- opinion: 观点、解读与分析（所有非事实性内容的兜底板块）。包括：个人观点/评论/行业展望、产品解读/科普/教程/使用体验、社区争议/声讨/抄袭事件、行业趋势报告/综述、AI宏观议题（伦理/治理/哲学/就业影响）
- not_relevant: 与AI无关。也包括以下主题（日报不关注）：Agent开发框架更新、企业级安全防护SaaS/B端Agent工具、Agent安全分析/风险解读、Agent架构科普/教程、Agent可靠性研究/基准测试、AI安全合规政策、展会相关（逛展指南/招展推广/参展广告/门票福利）、AI硬件产品、Agent基础设施（沙箱/治理/编排/权限管控等底层架构新闻）、Agent合规风险（企业Agent治理/合规框架/风险评估）

**核心原则：除 ai_business 和 opinion 外，其他板块只收"某个具体产品/项目/模型做了什么事"的事实性新闻。解读、分析、教程、争议、观点一律归 opinion。**

对每篇文章判断：
1. relevant: 是否与AI相关（true/false）
2. primary_tag: 文章核心事件最匹配的**单个**板块
3. quality: 信息质量分（0-3整数）
   3 = 重大：产品首发/技术突破/独家深度/重要开源/重大融资收购
   2 = 常规：产品更新/公司动态/有价值新闻/垂直周报（聚焦单一主题且有数据）
   1 = 边缘：消费评测/泛科技/轻度相关/纯拼接型聚合新闻（晚报/早报/速递等，⚡TUNABLE：聚合新闻评级可能根据最终输出效果再调整）
   0 = 噪声：活动推广/榜单征集/申报/投票/招聘/广告/与AI无实质关系
4. reason: 一句话判断理由

### quality=0 强制规则（必须严格执行）

以下情况一律 quality=0，relevant=false，primary_tag=not_relevant：
- 标题含"申报""征集""报名""投票""评选启动"等行动号召词
- [Sponsor] 开头的赞助内容
- 纯游戏行业新闻（营收/人事/评测/攻略），无AI相关性

### 聚合拼接新闻规则（⚡TUNABLE：此规则可能根据最终输出效果再调整）

以下聚合类文章 quality=1，relevant=true，primary_tag 由你根据内容判断（可能是 opinion/ai_core/ai_agent 等任意板块）：
- 标题用分号（；/;）或竖线（丨/|）拼接 ≥2 条不相关新闻的聚合文章
  判断方法：如果分号/竖线两侧讲的是不同公司/不同事件 → 聚合拼接
  ✅ 例外：垂直领域周报聚焦单一主题（如"AI短剧周报"）→ q=2（常规）
- 标题含"晚报""早报""速递""快讯""一句话看"且拼接多条新闻

### 正确分类示例

产品/项目新闻 → 对应垂直板块：
✅ "Claude Code重构上线Routines，7x24小时云端自动执行" → ai_agent, q=3（具体功能发布）
✅ "Anthropic's Claude Managed Agents gives enterprises a new way to deploy AI" → ai_agent, q=3（新产品发布）
✅ "Vidu Q3参考生升级：特效音效场景全备好" → ai_video, q=3（模型新版本发布）
✅ "北大开源3D生成神器UltraShape" → ai_core, q=3（具体模型开源）
✅ "Chrome上线AI Skills功能" → ai_product, q=2（产品功能更新）
✅ "Discord新增AI聊天助手功能" → ai_social, q=2（传统社交+AI功能结合）
✅ "PyTorch 3.0发布，推理速度提升2倍" → ai_product, q=3（训练框架发布→ai_product）

解读/观点/分析 → opinion：
✅ "一文带你看懂Harness Engineering到底是个啥" → opinion, q=2（平台解读科普）
✅ "5分钟缓存清零，集体声讨Claude" → opinion, q=2（社区争议/用户吐槽）
✅ "Hermes Agent抄袭中国团队代码实锤" → opinion, q=2（伦理争议事件）

商业动态 → ai_business：
✅ "李开复、陆奇已重金入场Harness" → ai_business, q=3（投资人入场=商业事件）
✅ "德塔智能连续三轮融资超亿元" → ai_business, q=3（融资）

日报不关注 → not_relevant：
❌ "LangChain v0.4发布，新增多Agent编排" → not_relevant（Agent开发框架更新）
❌ "OpenClaw爆火暴露12类致命隐患" → not_relevant（Agent安全分析）
❌ "Databricks用更强模型测试Agent性能" → not_relevant（Agent可靠性基准测试）
❌ "SAP推出企业级Agent安全防护平台" → not_relevant（企业安全SaaS）
❌ "#PAGC2026逛展指南-AI剧篇" → not_relevant（展会逛展指南）
❌ "AI+万物，PAGC AI参展企业初曝光，找AI产品找融资就来5月展会" → not_relevant（展会招展推广）
❌ "欧盟AI安全法案正式生效" → not_relevant（AI安全合规政策）
❌ "Meta发布AI眼镜二代" → not_relevant（AI硬件产品）
❌ "OpenAI Agents SDK新增沙箱执行和治理能力" → not_relevant（Agent基础设施/治理）
❌ "企业Agent治理框架：如何管控AI代理的权限与合规" → not_relevant（Agent合规风险）
❌ "AI lowered the cost of building software. Enterprise governance is catching up" → not_relevant（Agent合规风险）

聚合拼接 → q=1（⚡TUNABLE）：
⚠️ "斯坦福报告：美国AI投资为中国23倍；Q1豆包...；OpenAI指控..." → ai_core, q=1（分号拼接聚合，主题偏AI核心）
⚠️ "群核科技港交所上市；源升智能融资丨扬帆晚报" → ai_business, q=1（晚报聚合，主题偏商业动态）

噪声 → not_relevant, q=0：
❌ "[Sponsor] WorkOS FGA" → q=0（赞助）

### 分类优先级规则

1. **先判断是"事实性新闻"还是"解读/分析/观点"**：
   - 事实性（某产品发了/开源了/上线了/融资了）→ 归入对应板块
   - 非事实性（解读/科普/教程/评测/争议/观点/展会导览）→ opinion
2. 收购/融资/IPO/营收/投资人入场 → ai_business
3. 通用大模型发布（GPT-5/Claude新版/Gemma）→ ai_core
4. 不确定归哪个垂直板块的AI产品 → ai_product
5. quality=0 → 必须标为 not_relevant（注意：聚合拼接新闻是 q=1 不是 q=0）
6. **同一事件多篇报道**：如果列表中有多篇文章讲的是同一件事（同一产品发布/同一收购/同一技术突破），只保留质量最高的那篇（quality最高、摘要最详细），其余标为 not_relevant，并在 dup_of 字段写入保留文章的 id（用于覆盖广度回填）。

### quality 打分可信度说明

quality 基于标题 + 摘要（最多300字）打分，**不读全文**。打分要务实：
- **标题夸张但摘要不具体** → quality 降一档（如标题"史上最强"但摘要无数据 → q=2不是3）
- **纯英文短标题看不出深度** → 参考摘要内容判断，摘要也不具体则 q=2
- **标题清晰说明了"首发/开源/重大突破"** → q=3是合理的，不要因为没读全文而刻意压低
- **摘要透露的信息优先于标题**：标题含AI关键词但摘要说的是无关事件，按摘要判断（如"龙虾从屏幕爬出"→摘要说"讯飞Claw全家桶登场"→按摘要分类为ai_agent）

### rescue 候选说明（仅用于 rescue 模式时参考）

以下文章未能命中AI关键词，但摘要或背景可能与AI相关：
- 国内AI产品名（讯飞/Claw/Kimi/豆包/通义/文心等）可能在摘要而非标题中出现
- 大公司（谷歌/微软/苹果等）发布的AI功能，标题可能只写产品名不写AI

输出 JSON（仅输出 JSON，不要输出其他内容）：
[
  {"id": "xxx", "relevant": true, "primary_tag": "ai_agent", "quality": 3, "reason": "一句话原因"},
  {"id": "yyy", "relevant": false, "primary_tag": "not_relevant", "quality": 0, "reason": "与AI无关"},
  {"id": "zzz", "relevant": false, "primary_tag": "not_relevant", "quality": 0, "reason": "与xxx报道同一事件，xxx摘要更详细", "dup_of": "xxx"},
  ...
]

文章列表：
"""

    RESCUE_PROMPT = """你是一个 AI 资讯相关性判断器。以下文章没有命中AI关键词，但可能与AI领域间接相关。

我高度关注以下具体领域：
- ai_agent: AI Agent产品、AI编程助手、自动化工作流、Agent游戏化社交（AI小镇/养虾）、AI创作人格。不含Agent基础设施（沙箱/治理/编排）和Agent合规风险
- ai_video: AI视频/图像生成模型、AI短剧/动画、TTS/语音合成模型
- ai_gaming: AI+游戏新玩法、AI Native游戏设计、AI NPC/AI剧情生成、世界模型
- ai_social: AI社交产品（AI微信/XChat）、AI虚拟伴侣社交平台
- ai_core: 通用大模型、训练推理、架构创新、具身智能、Physical AI。不含世界模型（→ai_gaming）、TTS（→ai_video）
- ai_business: AI公司融资/收购/IPO/营收/竞争策略
- ai_product: 其他AI产品/应用
- opinion: AI相关的观点/评论/行业展望/宏观议题（伦理/治理/就业影响）

判断规则：
- **只选与上述领域明确相关的文章**，泛泛提到科技公司但核心不是AI的不选
- quality 打分规则同 classify（0-3，聚合拼接/征集/推广 → 0）
- quality=0 的不要输出（直接跳过）

✅ 应该捞回: "Google's AI watermarking system SynthID reverse-engineered" → ai_core（AI水印系统安全事件）
✅ 应该捞回: "Gemini Robotics-ER 1.6: Powering real-world robotics tasks" → ai_core（具身智能产品发布）
❌ 不该捞回: "Google reports strong quarterly earnings" → 非AI核心，不捞
❌ 不该捞回: "TikTok全球MAU突破20亿丨一句话看出海新鲜事" → 聚合拼接，quality=0

输出 JSON（仅输出 JSON，只输出 relevant=true 且 quality≥1 的）：
[{"id": "xxx", "relevant": true, "primary_tag": "ai_agent", "quality": 3, "reason": "..."}]

文章标题列表：
"""

    # 宽松触发词（缩小捞漏扫描范围）
    LOOSE_TRIGGER_NAMES = [
        "Sam Altman", "Satya Nadella", "Jensen Huang", "Elon Musk",
        "Mark Zuckerberg", "Sundar Pichai", "Demis Hassabis",
        "Dario Amodei", "李彦宏", "黄仁勋", "马斯克",
        "微软", "Microsoft", "谷歌", "Google", "英伟达", "NVIDIA",
        "苹果", "Apple", "Meta", "Amazon", "亚马逊",
        "腾讯", "字节", "ByteDance", "阿里", "百度",
        "Epic Games", "Roblox", "米哈游", "网易游戏",
        "Discord", "Snap",
        "数据中心", "data center", "GPU",
        "机器人", "robot", "自动驾驶", "autonomous",
        "OpenAI", "Anthropic", "DeepSeek", "Claude", "GPT",
        # 国内AI产品和新兴Agent产品（标题不含AI关键词但内容相关）
        "讯飞", "科大讯飞", "Manus", "Lovable", "Cursor", "Copilot",
        "Gemini", "Grok", "Perplexity", "Mistral", "Cohere",
        "智谱", "月之暗面", "Kimi", "通义", "豆包", "文心",
        "Harness", "Hermes", "Notion",
    ]

    def __init__(self, config: dict, data_dir: Path | None = None):
        self._results: dict | None = None
        self._data_dir = data_dir

    def load_results(self, json_path: str | Path):
        """加载 CodeBuddy 预生成的 LLM 分类结果

        文件格式（llm_filter_results.json）：
        {
            "classify": [
                {"id": "c_hashid", "relevant": true, "primary_tag": "ai_agent",
                 "quality": 3, "reason": "..."},
                {"id": "c_hashid", "relevant": false, "primary_tag": "not_relevant",
                 "quality": 0, "reason": "..."}
            ],
            "rescue": [
                {"id": "r_hashid", "relevant": true, "primary_tag": "ai_gaming",
                 "quality": 2, "reason": "..."}
            ]
        }
        """
        path = Path(json_path)
        if not path.exists():
            logger.info(f"LLM 分类结果文件不存在: {path}")
            return False
        self._results = json.loads(path.read_text(encoding="utf-8"))
        logger.info(f"已加载 LLM 分类结果: {path}")
        return True

    def _export_filter_input(self, classify_candidates: list[dict],
                             rescue_candidates: list[dict]):
        """导出待分类文章到 llm_filter_input.json"""
        if self._data_dir is None:
            return

        export = {
            "classify_prompt": self.CLASSIFY_PROMPT.strip(),
            "rescue_prompt": self.RESCUE_PROMPT.strip(),
            "classify_candidates": [
                {
                    "id": _stable_id("c", a),
                    "title": a.get("title", ""),
                    "summary_clean": (a.get("summary_clean", "") or "")[:300],
                    "source_name": a.get("source_name", ""),
                    "channel": a.get("channel", ""),
                    "url": a.get("url", ""),
                    "keyword_tags": a.get("_relevance_tags", []),
                }
                for a in classify_candidates
            ],
            "rescue_candidates": [
                {
                    "id": _stable_id("r", a),
                    "title": a.get("title", ""),
                    "summary_clean": (a.get("summary_clean", "") or "")[:200],
                    "source_name": a.get("source_name", ""),
                    "channel": a.get("channel", ""),
                }
                for a in rescue_candidates
            ],
        }

        export_path = self._data_dir / "llm_filter_input.json"
        export_path.write_text(
            json.dumps(export, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ── 同时生成 results 模板（id 预填，分类字段待填）──
        # 防止手写 id 导致不匹配
        # 对 classify_candidates 做标题关键词聚类，同一事件的文章排在一起
        clustered_classify = _cluster_by_title_similarity(classify_candidates)
        template = {
            "classify": [
                {
                    "id": _stable_id("c", a),
                    "title": a.get("title", "")[:50],
                    "_group": a.get("_cluster_group", ""),
                    "relevant": "__TODO__",
                    "primary_tag": "__TODO__",
                    "quality": "__TODO__",
                    "reason": "__TODO__",
                }
                for a in clustered_classify
            ],
            "rescue": [
                {
                    "id": _stable_id("r", a),
                    "title": a.get("title", "")[:50],
                    "relevant": "__TODO__",
                    "primary_tag": "__TODO__",
                    "quality": "__TODO__",
                    "reason": "__TODO__",
                }
                for a in rescue_candidates
            ],
        }
        template_path = self._data_dir / "llm_filter_results_template.json"
        template_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        console.print(f"  📤 已导出待分类文章: {export_path}")
        console.print(f"  📋 已生成结果模板: {template_path}")
        console.print(f"     分类候选: {len(classify_candidates)} 篇, 捞漏候选: {len(rescue_candidates)} 篇")
        console.print("     请基于模板填写分类结果，保存为 llm_filter_results.json")

    def classify(self, keyword_passed: list[dict],
                 valid_tags: set[str]) -> list[dict]:
        """Step 3b: 全量分类 — 对所有关键词通过的文章做语义分类

        从 llm_filter_results.json 的 "classify" 字段读取 CodeBuddy 的分类结果。
        为每篇文章设置 primary_tag（覆盖关键词打的多标签）。

        LLM 去重覆盖回填（2026-04-16 新增）：
          当 LLM 标记某篇为"与另一篇重复"（dup_of 字段），
          将被踢文章的渠道/源信息累加到保留文章的覆盖广度上，
          使 Step 4 评分能反映 LLM 识别出的语义级重复覆盖。

        Returns:
            分类后的通过列表（不相关的文章已移除）。
        """
        classify_results = self._results.get("classify", []) if self._results else []

        # 构建 id → result 映射
        result_map = {}
        for item in classify_results:
            result_map[item.get("id", "")] = item

        # 构建 id → article 映射（使用稳定哈希ID）
        id_to_article: dict[str, dict] = {}
        for art in keyword_passed:
            id_to_article[_stable_id("c", art)] = art

        # ── 第一阶段：正常分类 ──
        classified = []
        removed_count = 0
        # 记录 LLM 去重踢掉的文章：{被踢文章id: (被踢文章, 保留文章id)}
        llm_dup_removed: list[tuple[dict, str]] = []

        for art in keyword_passed:
            aid = _stable_id("c", art)
            result = result_map.get(aid)
            if not result:
                # 没有 LLM 结果，fallback 到关键词标签选最佳主标签
                kw_tags = [t for t in art.get("_relevance_tags", []) if not t.startswith("_")]
                if kw_tags:
                    art["_primary_tag_llm"] = kw_tags[0]
                art["_tag_source"] = "keyword_fallback"
                classified.append(art)
                continue

            if not result.get("relevant", True):
                # LLM 判定不相关
                art["_relevance_tags"] = []
                art["_relevance_priority"] = "none"
                art["relevance_tags"] = []
                art["relevance_priority"] = "none"
                art["_llm_classified"] = "not_relevant"
                art["_llm_classify_reason"] = result.get("reason", "")
                removed_count += 1
                # 检查是否为 LLM 事件去重（有 dup_of 字段）
                dup_of = result.get("dup_of", "")
                if dup_of:
                    llm_dup_removed.append((art, dup_of))
                    logger.info(f"  分类踢掉(dup_of={dup_of}): {art.get('title', '')[:40]}")
                else:
                    logger.info(f"  分类踢掉: {art.get('title', '')[:40]} — {result.get('reason', '')}")
                continue

            # LLM 判定相关，设置主标签
            primary = result.get("primary_tag", "")
            quality = result.get("quality", 1)  # 默认1（边缘），未分类文章不应获得高质量加分

            # #2: quality=0 强制降级为 not_relevant（不依赖 LLM 是否正确标注）
            if quality == 0 or primary == "not_relevant":
                art["_relevance_tags"] = []
                art["_relevance_priority"] = "none"
                art["relevance_tags"] = []
                art["relevance_priority"] = "none"
                art["_llm_classified"] = "not_relevant"
                art["_llm_classify_reason"] = result.get("reason", "")
                removed_count += 1
                # quality=0 也可能带 dup_of
                dup_of = result.get("dup_of", "")
                if dup_of:
                    llm_dup_removed.append((art, dup_of))
                logger.info(f"  分类踢掉(q={quality}): {art.get('title', '')[:40]}")
                continue

            if primary and primary in valid_tags:
                art["_relevance_tags"] = [primary]
                art["_primary_tag_llm"] = primary
                art["_quality"] = quality
                art["relevance_tags"] = art["_relevance_tags"]
            elif primary == "opinion":
                # opinion 文章保留原有 tag（如果有的话），分流到独立观点池
                existing_tags = art.get("_relevance_tags", [])
                art["_relevance_tags"] = existing_tags if existing_tags else ["opinion"]
                art["_primary_tag_llm"] = "opinion"
                art["_quality"] = quality
                art["_opinion_diverted"] = True
                art["_content_type"] = "opinion"
                art["relevance_tags"] = art["_relevance_tags"]

            art["_llm_classified"] = primary
            art["_llm_classify_reason"] = result.get("reason", "")
            art["_tag_source"] = "llm_classified"
            classified.append(art)

        # ── 第二阶段：LLM 去重覆盖回填 ──
        # 被 LLM 标记为 dup_of 的文章，将其渠道/源信息累加到保留文章的覆盖广度上
        backfill_count = 0
        for removed_art, target_id in llm_dup_removed:
            target_art = id_to_article.get(target_id)
            if not target_art:
                continue
            # 累加覆盖广度
            removed_channel = removed_art.get("channel", "")
            removed_source = removed_art.get("source_name", "")
            target_art["coverage_count"] = target_art.get("coverage_count", 1) + 1
            # 检查是否新增了渠道
            existing_channels = set()
            existing_channels.add(target_art.get("channel", ""))
            # 用 _llm_dup_channels 追踪所有已合并的渠道
            llm_channels = set(target_art.get("_llm_dup_channels", []))
            llm_channels.add(target_art.get("channel", ""))
            llm_channels.add(removed_channel)
            target_art["_llm_dup_channels"] = list(llm_channels)
            target_art["_coverage_channels"] = max(
                target_art.get("_coverage_channels", 1), len(llm_channels)
            )
            # 追踪所有已合并的源
            llm_sources = set(target_art.get("_llm_dup_sources", []))
            llm_sources.add(target_art.get("source_name", ""))
            llm_sources.add(removed_source)
            target_art["_llm_dup_sources"] = list(llm_sources)
            target_art["_coverage_sources"] = max(
                target_art.get("_coverage_sources", 1), len(llm_sources)
            )
            backfill_count += 1
            logger.info(
                f"  覆盖回填: {removed_art.get('title', '')[:30]}({removed_channel}/{removed_source}) "
                f"→ {target_art.get('title', '')[:30]} "
                f"(coverage={target_art['coverage_count']}, "
                f"channels={target_art['_coverage_channels']}, "
                f"sources={target_art['_coverage_sources']})"
            )

        if removed_count > 0:
            console.print(
                f"  ✅ Step 3b 分类: 踢掉 {removed_count} 篇不相关，保留 {len(classified)} 篇"
                + (f"，覆盖回填 {backfill_count} 篇" if backfill_count > 0 else "")
            )
        else:
            console.print(f"  ✅ Step 3b 分类: {len(classified)} 篇全部相关")

        return classified

    def rescue(self, maybe_relevant: list[dict],
               valid_tags: set[str]) -> list[dict]:
        """Step 3c: 捞漏 — 从关键词未命中的文章中找回相关内容

        Args:
            maybe_relevant: 预过滤后的捞漏候选（由 run() 传入）
        """
        if not maybe_relevant:
            logger.info("Step 3c: 无需捞漏（预过滤后为空）")
            return []

        console.print(f"  🎣 Step 3c: 预过滤 {len(maybe_relevant)} 篇候选")

        rescue_map = {}
        for art in maybe_relevant:
            rid = _stable_id("r", art)
            rescue_map[rid] = art

        rescue_results = self._results.get("rescue", []) if self._results else []

        rescued = []
        for item in rescue_results:
            aid = item.get("id", "")
            if item.get("relevant", False) and aid in rescue_map:
                art = rescue_map[aid]
                primary = item.get("primary_tag", "")
                quality = item.get("quality", 1)
                # quality=0 强制跳过
                if quality == 0:
                    continue
                # dup_of 跳过：与另一篇是同一事件的重复报道
                dup_of = item.get("dup_of", "")
                if dup_of:
                    logger.info(f"  捞漏跳过(dup_of={dup_of}): {art.get('title', '')[:40]}")
                    continue
                if primary and primary in valid_tags:
                    art["_relevance_tags"] = [primary]
                    art["_relevance_priority"] = "supplementary"
                    art["_primary_tag_llm"] = primary
                    art["_quality"] = quality
                    art["relevance_tags"] = art["_relevance_tags"]
                    art["relevance_priority"] = "supplementary"
                    art["_llm_rescued"] = True
                    art["_llm_rescue_reason"] = item.get("reason", "")
                    rescued.append(art)
                    logger.info(f"  捞回: {art.get('title', '')[:40]} → {primary}")
                elif primary == "opinion":
                    # opinion 捞漏：分流到独立观点池
                    existing_tags = art.get("_relevance_tags", [])
                    art["_relevance_tags"] = existing_tags if existing_tags else ["opinion"]
                    art["_relevance_priority"] = "supplementary"
                    art["_primary_tag_llm"] = "opinion"
                    art["_quality"] = quality
                    art["_opinion_diverted"] = True
                    art["_content_type"] = "opinion"
                    art["relevance_tags"] = art["_relevance_tags"]
                    art["relevance_priority"] = "supplementary"
                    art["_llm_rescued"] = True
                    art["_llm_rescue_reason"] = item.get("reason", "")
                    rescued.append(art)
                    logger.info(f"  捞回(opinion): {art.get('title', '')[:40]}")

        if rescued:
            console.print(f"  ✅ Step 3c 捞漏: 捞回 {len(rescued)} 篇")
        else:
            console.print("  ✅ Step 3c 捞漏: 无漏网之鱼")

        return rescued

    def run(self, keyword_passed: list[dict],
            keyword_rejected: list[dict],
            valid_tags: set[str]) -> tuple[list[dict], list[dict]]:
        """执行完整 LLM 分类+捞漏流程"""
        # 计算捞漏候选：标题 OR 摘要中含触发词
        trigger_lower = [n.lower() for n in self.LOOSE_TRIGGER_NAMES]
        maybe_relevant = [
            a for a in keyword_rejected
            if a.get("channel", "") in ("rss", "wechat", "exa")
            and any(
                t in (a.get("title", "") + " " + (a.get("summary_clean", "") or "")).lower()
                for t in trigger_lower
            )
        ]

        if not self._results:
            console.print("  ⚠️ 未找到 llm_filter_results.json，使用纯关键词结果")
            if keyword_passed or maybe_relevant:
                self._export_filter_input(keyword_passed, maybe_relevant)
            return keyword_passed, []

        # 有预生成结果：执行分类 + 捞漏
        classified = self.classify(keyword_passed, valid_tags)
        rescued = self.rescue(maybe_relevant, valid_tags)
        return classified, rescued


# ══════════════════════════════════════════
# Step 4: Score（热度评分）
# 主日报：时效性 + 覆盖广度 + LLM质量分 + 内容类型调整（无互动数据）
# GitHub/Twitter：保留互动数据维度（stars/likes 有真实数据）
# ══════════════════════════════════════════


class ContentTypeClassifier:
    """内容类型分类器：区分技术/产品发布 vs 观点/评论类文章

    分类逻辑（基于标题+摘要的关键词信号）：
      tech_product — 技术发布、产品上线、模型发布、工具更新、开源项目
      opinion      — 观点文章、评论分析、行业展望、个人思考
      news         — 事实性新闻报道（融资、收购、数据、事件）
      unknown      — 无法判断

    设计原则：
      - 技术/产品 > 新闻 > 观点，反映"实质内容优先"的选稿偏好
      - 观点类不是"不要"，而是"同等条件下排后面"
      - 业界大牛（VIP 作者）的观点文章豁免降权
    """

    # 技术/产品发布信号词
    TECH_PRODUCT_SIGNALS = [
        # 发布/上线类动词
        "发布", "上线", "推出", "开源", "升级", "更新", "release", "launch",
        "announce", "introduce", "ship", "deploy", "open source", "open-source",
        # 产品/模型类名词
        "新模型", "新产品", "新版本", "新功能", "new model", "new feature",
        "v2", "v3", "v4", "2.0", "3.0", "首个", "首款", "全球首",
        "API", "SDK", "CLI", "框架", "framework", "平台", "platform",
        # 技术实现类
        "架构", "算法", "训练", "推理", "benchmark", "评测", "性能",
        "architecture", "training", "inference", "optimization", "优化",
        "论文", "paper", "研究", "research", "实验", "experiment",
        # 技术深度分析（与纯观点区分：聚焦"怎么做"而非"怎么看"）
        "底层", "原理", "逻辑", "运行", "实现", "源码", "代码",
        "implementation", "mechanism", "internals", "under the hood",
        "how it works", "technical", "deep dive", "解析", "拆解",
        "scaling", "scale", "decoupling", "管线", "pipeline",
        # 硬件/基建
        "芯片", "chip", "GPU", "数据中心", "data center", "算力",
        # 融资/收购（事实性事件，非观点）
        "融资", "收购", "acquisition", "funding", "IPO",
    ]

    # 观点/评论信号词
    OPINION_SIGNALS = [
        # 观点类动词/句式（注意：不包含"解析""拆解"等技术分析词）
        "认为", "表示", "谈", "看法", "观点", "评论", "分析", "解读",
        "思考", "反思", "展望", "预测", "预言", "判断", "讨论",
        "回应", "回顾", "探讨", "辩论",
        "argues", "opinion", "perspective", "view", "think", "believe",
        "predict", "forecast", "commentary", "essay",
        "debate", "reflect",
        # 观点类标题特征
        "为什么", "如何看待", "怎么看", "该不该", "会不会", "能不能",
        "吗？", "呢？", "的思考", "的观点", "的看法",
        "why", "should we", "how to think",
        # 演讲/访谈（非技术分享）
        "演讲", "对话", "访谈", "采访", "圆桌", "speech", "interview",
        "fireside",
        # 情绪/立场类
        "焦虑", "担忧", "乐观", "悲观", "颠覆", "末日", "泡沫",
        "失业", "取代", "威胁", "恐慌",
    ]

    # VIP 作者/源 — 这些作者的观点文章豁免降权
    DEFAULT_VIP_AUTHORS = [
        # 业界大牛（你提到的 Matthew Ball 等）
        "Matthew Ball", "matthew ball", "matthewball",
        "Sam Altman", "sama",
        "Jensen Huang", "黄仁勋",
        "Satya Nadella",
        "Mark Zuckerberg",
        "Demis Hassabis",
        "Dario Amodei",
        "Andrej Karpathy", "karpathy",
        "Yann LeCun", "ylecun",
        "Jim Fan",
        "Ilya Sutskever",
        "Geoffrey Hinton",
        "Andrew Ng", "吴恩达",
        "李彦宏",
        # 顶级博客作者
        "Simon Willison",
        "Paul Graham",
        "Ben Thompson", "stratechery",
        "Lilian Weng",
        "a16z",
    ]

    # VIP 源 — 这些源的观点文章豁免降权
    DEFAULT_VIP_SOURCES = [
        "OpenAI Blog", "Anthropic", "Google DeepMind", "Google AI Blog",
        "Simon Willison", "a16z Blog",
    ]

    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("content_type", {})
        self.opinion_penalty = cfg.get("opinion_penalty", -1.0)
        self.tech_product_bonus = cfg.get("tech_product_bonus", 0.5)
        self.vip_authors = set(
            a.lower() for a in cfg.get("vip_authors", self.DEFAULT_VIP_AUTHORS)
        )
        self.vip_sources = set(
            cfg.get("vip_sources", self.DEFAULT_VIP_SOURCES)
        )

    def classify(self, article: dict) -> str:
        """分类文章内容类型，返回 'tech_product' | 'opinion' | 'news' | 'unknown'

        分类策略：
          1. 标题中的信号权重翻倍（标题最能反映文章主旨）
          2. 当技术信号和观点信号都有时，偏向技术（技术深度文常包含分析类词汇）
          3. 只有观点信号明显占优时才判为观点
        """
        title = article.get("title", "").lower()
        summary = (article.get("summary_clean", "") or "").lower()
        text = f"{title} {summary}"

        tech_score = sum(1 for s in self.TECH_PRODUCT_SIGNALS if s.lower() in text)
        opinion_score = sum(1 for s in self.OPINION_SIGNALS if s.lower() in text)

        # 标题中的信号权重翻倍（标题比摘要更能反映文章主旨）
        tech_title_hits = sum(1 for s in self.TECH_PRODUCT_SIGNALS if s.lower() in title)
        opinion_title_hits = sum(1 for s in self.OPINION_SIGNALS if s.lower() in title)
        tech_score += tech_title_hits  # 标题命中 ×2
        opinion_score += opinion_title_hits

        # 分类判断（技术优先：相近分数偏向技术）
        if tech_score >= 2 and tech_score >= opinion_score:
            # 技术信号充足且不弱于观点 → 技术/产品
            return "tech_product"
        elif opinion_score >= 2 and opinion_score > tech_score + 1:
            # 观点信号必须明显占优（>tech+1）才判为观点
            return "opinion"
        elif tech_score >= 1 and opinion_score == 0:
            return "tech_product"
        elif opinion_score >= 2 and tech_score == 0:
            return "opinion"
        else:
            return "news"  # 两者都有或都没有 → 默认当新闻

    def is_vip(self, article: dict) -> bool:
        """检查文章作者/来源是否为 VIP（观点文章豁免降权）"""
        source = article.get("source_name", "")
        author = article.get("author", "") or ""

        # 检查源
        if source in self.vip_sources:
            return True
        # 微信源前缀匹配
        if source.startswith(WECHAT_PREFIX):
            bare_name = source[len(WECHAT_PREFIX):]
            if bare_name in self.vip_sources:
                return True

        # 检查作者
        author_lower = author.lower()
        if any(vip in author_lower for vip in self.vip_authors):
            return True

        # 检查 URL 中是否包含 VIP 标识（如 twitter 用户名）
        url = article.get("url", "").lower()
        for vip in self.vip_authors:
            if len(vip) > 4 and vip in url:  # 只检查较长的名字避免误匹配
                return True

        return False

    def score_adjustment(self, article: dict) -> tuple[float, str]:
        """计算内容类型的评分调整值

        Returns:
            (adjustment, content_type): 调整分数和分类结果

        观点类文章分流策略（2026-04-14）：
            opinion 文章不再降权 -1.0，改为标记 _opinion_diverted=True，
            由 apply_filter 从主板块移出，分流到独立的"行业观点"板块。
            VIP 作者的 opinion 文章也只出现在观点板块（不双重曝光）。

        LLM 优先原则（2026-04-14）：
            如果文章已被 LLM classify 标记了 _opinion_diverted，尊重 LLM 判断，不再用关键词覆盖。
            如果文章已被 LLM 标为非 opinion（如 ai_core），关键词分类器不应将其覆盖为 opinion。
        """
        # LLM 已分类的文章：尊重 LLM 判断
        if article.get("_llm_classified"):
            # LLM 已标为 opinion → 保持分流
            if article.get("_opinion_diverted"):
                article["_content_type"] = "opinion"
                if self.is_vip(article):
                    article["_content_type_vip"] = True
                return 0.0, "opinion"
            # LLM 标为其他 tag → 不覆盖为 opinion
            content_type = article.get("_content_type", "news")
            if content_type == "tech_product":
                return self.tech_product_bonus, content_type
            return 0.0, content_type

        # 未经 LLM 分类的文章：使用关键词判定
        content_type = self.classify(article)
        article["_content_type"] = content_type

        if content_type == "tech_product":
            return self.tech_product_bonus, content_type
        elif content_type == "opinion":
            if self.is_vip(article):
                article["_content_type_vip"] = True
            # opinion 文章不降权，标记分流到观点板块
            article["_opinion_diverted"] = True
            return 0.0, content_type
        else:
            return 0.0, content_type  # news/unknown 不调整


class HeatScorer:
    """四维度热度评分 + 内容类型调整（满分 8 分）

    主日报管道（rss/wechat/exa）四维度：
      时效性(0-3.0) + 覆盖广度(0-3.0) + LLM质量分(0-1.5)
      + 内容类型调整(技术/产品+0.5, 观点+0.0)

    GitHub/Twitter 管道保留互动数据维度（stars/likes 有真实数据）。

    源权重不参与评分，仅在去重选代表时使用。

    2026-04-13 优化：移除主日报管道的"互动数据"假维度（恒定 0.5，无区分度），
    将释放的权重重新分配给时效性(+0.5)、覆盖广度(+0.5)、多标签(+0.5)。
    """

    # 时效性差异化衰减曲线（小时 → 分数）
    # 2026-04-14 优化：统一主日报源的时效性曲线
    # 原因：日报每天跑一次，24h内的文章不应因发布时间早几小时就降分
    # official/media/wechat_media 统一为同一条曲线，消除渠道间系统性偏差
    # aggregate（未配置tier的源）保留快衰减，鼓励配置源tier
    TIMELINESS_CURVES = {
        "official": [(24, 3.0), (48, 2.0), (72, 1.0)],
        "media":    [(24, 3.0), (48, 2.0), (72, 1.0)],
        "wechat_media": [(24, 3.0), (48, 2.0), (72, 1.0)],
        "aggregate": [(12, 3.0), (24, 2.0), (48, 1.0)],
    }

    def __init__(self, config: dict):
        self.source_weights = config.get("source_weights", {})
        self.source_tiers = config.get("source_tiers", {})
        self.engagement_thresholds = config.get("engagement_thresholds", {})
        self.bonus_sources = set(config.get("bonus_sources", []))

        # 内容类型分类器
        self._content_classifier = ContentTypeClassifier(config)

        # 构建源 → tier 映射
        self._source_tier_map: dict[str, str] = {}
        for tier_name, sources in self.source_tiers.items():
            for s in sources:
                self._source_tier_map[s] = tier_name

    def score(self, article: dict, now: datetime) -> tuple[float, dict]:
        """返回 (总分, 各维度得分明细)，总分归一化到 1-8"""
        details = {}
        channel = article.get("channel", "")

        # 维度 1: 时效性（主日报 0-3.0，GitHub/Twitter 0-2.5）
        details["timeliness"] = self._score_timeliness(article, now)

        # 维度 2: 覆盖广度（主日报 0-3.0，GitHub/Twitter 0-2.5）
        details["coverage"] = self._score_coverage(article)

        # 维度 3: 互动数据 — 仅 GitHub/Twitter 管道（有真实互动数据）
        # 主日报管道无互动数据，跳过此维度（不再给恒定 0.5 假分）
        if channel in ("github", "twitter"):
            details["engagement"] = self._score_engagement(article)

        # 维度 4: LLM质量分（主日报 0-1.5，GitHub/Twitter 0-1.0）
        # quality: 3→1.5, 2→1.0, 1→0.5, 0→0.0
        quality = article.get("_quality", 1)  # 默认1（边缘），未分类文章不应获得高质量加分
        if channel in ("github", "twitter"):
            quality_score = min(quality, 3) * 0.33  # 最高1.0
        else:
            quality_score = min(quality, 3) * 0.5   # 最高1.5
        details["quality"] = round(quality_score, 1)

        # bonus: 优质源加分（0-0.5 分，不改变满分上限）
        source = article.get("source_name", "")
        bonus = 0.0
        if source in self.bonus_sources:
            bonus = 0.5
        # 微信源前缀匹配
        elif source.startswith(WECHAT_PREFIX):
            bare_name = source[len(WECHAT_PREFIX):]
            if bare_name in self.bonus_sources:
                bonus = 0.5
        details["bonus"] = bonus

        # 维度 5: 内容类型调整（技术/产品+0.5, 普通观点-1.0, VIP观点+0.0）
        # 对主日报管道（rss/wechat/exa）和 Twitter 管道生效
        # GitHub 管道不参与（项目本身就是技术产出，不存在"观点类"问题）
        if channel in ("rss", "wechat", "exa", "twitter"):
            ct_adj, ct_type = self._content_classifier.score_adjustment(article)
            details["content_type"] = ct_adj
        else:
            ct_adj = 0.0

        total = sum(details.values())
        # 归一化到 1-8
        score = max(1.0, min(8.0, total))
        return round(score, 1), details

    def _score_timeliness(self, article: dict, now: datetime) -> float:
        pub_dt = article.get("_published_dt")
        if not pub_dt:
            return 0.5  # 无时间信息给基础分

        hours_ago = (now - pub_dt).total_seconds() / 3600
        if hours_ago < 0:
            hours_ago = 0  # 未来时间当做刚发

        # 根据源级别选择衰减曲线
        source = article.get("source_name", "")
        tier = self._get_source_tier(source)
        curve = self.TIMELINESS_CURVES.get(tier, self.TIMELINESS_CURVES["aggregate"])

        for max_hours, score_val in curve:
            if hours_ago <= max_hours:
                return score_val
        return 0.0

    def _get_source_tier(self, source: str) -> str:
        """获取源级别，支持微信源前缀匹配和微信专用衰减"""
        # 先检查精确匹配
        if source in self._source_tier_map:
            return self._source_tier_map[source]
        # 微信源格式："微信: 量子位" → 尝试匹配 "量子位"
        if source.startswith(WECHAT_PREFIX):
            bare_name = source[len(WECHAT_PREFIX):]
            if bare_name in self._source_tier_map:
                base_tier = self._source_tier_map[bare_name]
                # 微信源用专用的慢衰减曲线（微信文章采集有延迟，价值更持久）
                if base_tier in ("media", "official"):
                    return "wechat_media"
                return base_tier
            # 未配置的微信源也用 wechat_media（比 aggregate 更宽松）
            return "wechat_media"
        return "aggregate"

    def get_source_weight(self, source: str) -> int:
        """获取源权重，支持微信源前缀匹配（公开方法，供去重选代表使用）"""
        if source in self.source_weights:
            return self.source_weights[source]
        # 微信源格式："微信: 量子位" → 尝试匹配 "量子位"
        if source.startswith(WECHAT_PREFIX):
            bare_name = source[len(WECHAT_PREFIX):]
            if bare_name in self.source_weights:
                return self.source_weights[bare_name]
        return 0

    def _score_coverage(self, article: dict) -> float:
        """覆盖广度评分（0-3.0 分）— 跨渠道覆盖比同渠道多源更有价值

        核心思路：同一事件同时出现在 RSS + Twitter + 微信 → 比只在 3 个 RSS 源更重要
        跨渠道覆盖（channels >= 2）直接给 2.5 分，体现更强的热度信号

        2026-04-13 调整：顶分从 2.5 提到 3.0，填补互动数据维度移除后的权重空间
        """
        channels = article.get("_coverage_channels", 1)
        sources = article.get("_coverage_sources", 1)
        count = article.get("coverage_count", 1)

        if channels >= 3 or sources >= 5 or count >= 6:
            return 3.0  # 3+渠道 or 5+源 → 重大事件
        elif channels >= 2 or sources >= 4 or count >= 4:
            return 2.5  # 2渠道（跨渠道）→ 热点事件
        elif sources >= 3 or count >= 3:
            return 1.5  # 3源同渠道 → 有热度
        elif sources >= 2 or count >= 2:
            return 0.5  # 2源覆盖 → 有一定关注度
        return 0.0

    @staticmethod
    def twitter_heat_score(extra: dict) -> float:
        """计算 Twitter 综合热度分（用于互动评分 + 热度门槛）。

        公式：likes×1.0 + retweets×3.0 + views×0.01
        三维度设计（聚焦 trending，不捞冷门）：
        - retweets 权重最高（3.0）：转发 = 传播 = trending 核心信号
        - likes 中等权重（1.0）：基础热度，广泛但相对廉价
        - views 极小权重（0.01）：量级大水分多，仅做基底兜底
        """
        likes = extra.get("likes", 0) or 0
        retweets = extra.get("retweets", 0) or 0
        views = extra.get("views", 0) or 0
        return likes * 1.0 + retweets * 3.0 + views * 0.01

    def _score_engagement(self, article: dict) -> float:
        extra = article.get("extra") or {}
        channel = article.get("channel", "")

        if channel == "twitter":
            heat = self.twitter_heat_score(extra)
            th = self.engagement_thresholds.get("twitter", {})
            # 综合热度梯度评分
            if heat >= th.get("heat_high", 500):
                return 2.0
            elif heat >= th.get("heat_medium", 150):
                return 1.5
            elif heat >= th.get("heat_low", 50):
                return 1.0
            return 0.0
        elif channel == "github":
            # GitHub 项目纯按 stars 梯度评分，无来源特权
            stars = extra.get("stars", 0) or 0
            th = self.engagement_thresholds.get("github", {})
            high = th.get("high", 100)
            medium = th.get("medium", 30)
            if stars >= high:
                return 2.0
            elif stars >= medium:
                return 1.0
            elif stars >= 10:
                return 0.5
            return 0.0  # 低 stars 项目不再有保底分
        else:
            # 此方法仅应被 GitHub/Twitter 管道调用
            # 主日报管道（rss/wechat/exa）无互动数据，在 score() 中已跳过
            raise ValueError(
                f"_score_engagement 不应被 channel={article.get('channel')} 调用，"
                f"仅支持 github/twitter 管道"
            )


# ══════════════════════════════════════════
# Step 5: Filter（过滤输出）
# ══════════════════════════════════════════


def _select_by_tag_quota(
    eligible: list[dict],
    quotas: dict[str, int],
    default_quota: int,
    min_articles_warning: int,
    cross_pipe_titles: list[str] | None = None,
) -> tuple[set[int], dict[str, dict]]:
    """在一组文章内按标签配额选取，返回 (selected_ids, quota_stats)。

    分组策略：
      - 如果文章有 _primary_tag_llm（LLM 分类结果），只归入主标签组
      - 否则 fallback 到关键词打的多标签（每个标签都归入）

    事件级去重：
      - 同管道内：已入选文章标题相似度>0.5的跳过
      - 跨管道：cross_pipe_titles 中的标题也参与去重
    """
    tag_groups: dict[str, list[dict]] = defaultdict(list)
    for art in eligible:
        primary_llm = art.get("_primary_tag_llm", "")
        if primary_llm and not primary_llm.startswith("_"):
            # LLM 分类结果：只归入主标签
            tag_groups[primary_llm].append(art)
        else:
            # fallback: 关键词多标签
            real_tags = [t for t in art.get("_relevance_tags", [])
                         if not t.startswith("_")]
            for tag in real_tags:
                tag_groups[tag].append(art)

    selected_ids: set[int] = set()
    selected_titles: list[str] = list(cross_pipe_titles or [])  # 包含跨管道已入选标题
    selected_by_tag: dict[str, set[int]] = defaultdict(set)
    quota_stats: dict[str, dict] = {}

    all_tags = set(quotas.keys()) | set(tag_groups.keys())

    for tag in sorted(all_tags, key=lambda t: len(tag_groups.get(t, []))):
        quota = quotas.get(tag, default_quota)
        group = tag_groups.get(tag, [])
        group_sorted = sorted(group, key=lambda a: a.get("score", 0), reverse=True)

        filled = 0
        for art in group_sorted:
            if filled >= quota:
                break
            art_id = id(art)
            if art_id in selected_ids:
                continue
            # 事件级去重：如果当前文章和已入选文章讲的是同一事件，跳过
            # 两种检测方式（OR）：
            #   1. 标题相似度 > 0.5
            #   2. 共享核心实体关键词（>= 3个中文字或英文单词的子串匹配）
            art_title = art.get("title", "")
            is_event_dup = False
            for st in selected_titles:
                # 方式1：标题相似度
                if SequenceMatcher(None, art_title, st).ratio() > 0.5:
                    is_event_dup = True
                    break
                # 方式2：提取标题中的实体短语（3+字符），检查是否有共同实体
                entities_a = set(re.findall(r'[\u4e00-\u9fff]{3,}', art_title))
                entities_b = set(re.findall(r'[\u4e00-\u9fff]{3,}', st))
                eng_a = set(re.findall(r'[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*', art_title))
                eng_b = set(re.findall(r'[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*', st))
                common_cn = entities_a & entities_b
                common_en = eng_a & eng_b
                # 过滤掉太通用的词
                generic_en = {'Agent', 'Model', 'Data', 'Code', 'Studio', 'Lab', 'Pro',
                              'Chat', 'The', 'New', 'For', 'How', 'What', 'Why',
                              'AI Agent', 'Google', 'Microsoft', 'Meta', 'Apple',
                              'Amazon', 'OpenAI', 'Anthropic', 'Claude', 'Gemini',
                              'DeepMind', 'NVIDIA', 'Samsung', 'Hugging Face',
                              'ByteDance', 'Tencent', 'Baidu'}
                generic_cn = {'大模型', '人工智能', '开源', '发布', '全球', '技术',
                              '产品', '公司', '中国', '美国', '市场', '行业'}
                common_en -= generic_en
                common_cn -= generic_cn
                # 至少有一个有意义的共同实体（>=4字符的英文或>=4汉字的中文）
                meaningful_cn = {e for e in common_cn if len(e) >= 4}
                meaningful_en = {e for e in common_en if len(e) >= 4}
                if meaningful_cn or meaningful_en:
                    is_event_dup = True
                    break
            if is_event_dup:
                art["filtered_out"] = True
                art["filter_reason"] = "event_duplicate"
                continue
            selected_ids.add(art_id)
            selected_titles.append(art_title)
            selected_by_tag[tag].add(art_id)
            filled += 1

        supply = len(group)
        low_supply = supply < min_articles_warning
        top_n_scores = sorted(
            [a.get("score", 0) for a in group_sorted[:quota]],
            reverse=True,
        )
        quota_stats[tag] = {
            "quota": quota,
            "supply": supply,
            "filled": filled,
            "low_supply": low_supply,
            "top_score": round(top_n_scores[0], 1) if top_n_scores else 0,
            "min_score": round(top_n_scores[-1], 1) if top_n_scores else 0,
        }

    return selected_ids, quota_stats


# 管道 → 渠道映射
# GitHub 拆分为两个子管道（2026-04-16）：
#   github_trending: Trending Daily + Weekly（热门趋势）
#   github_new: Search API + Blog（新品发现）
# 分流依据：source_name 前缀
PIPELINE_CHANNELS = {
    "main": {"rss", "wechat", "exa", "manual"},
    "github_trending": {"github"},  # 实际分流在 _split_github_subpipes 中
    "github_new": {"github"},       # 实际分流在 _split_github_subpipes 中
    "twitter": {"twitter"},
}

# GitHub 子管道分流：source_name 前缀 → 子管道
GITHUB_TRENDING_PREFIXES = ("GitHub Trending",)
GITHUB_NEW_PREFIXES = ("GitHub Search", "GitHub Blog")


def _split_github_subpipes(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """将 GitHub 渠道文章按 source_name 分流到 trending / new 子管道"""
    trending, new = [], []
    for art in articles:
        src = art.get("source_name", "")
        if any(src.startswith(p) for p in GITHUB_TRENDING_PREFIXES):
            trending.append(art)
        else:
            new.append(art)
    return trending, new


def apply_filter(
    articles: list[dict],
    pipeline_quotas: dict[str, dict] | None = None,
    quota_per_tag: dict[str, int] | None = None,
    default_quota: int = 5,
    min_articles_warning: int = 3,
    twitter_min_heat: float = 30.0,
    github_trending_min_stars: int = 100,
    github_new_min_stars: int = 30,
    opinion_max_items: int = 3,
) -> tuple[list[dict], dict]:
    """
    多管道独立配额制过滤 + 观点板块分流。

    管道结构（2026-04-16 GitHub 拆分）：
      main:             rss, wechat, exa, manual（排除 opinion 文章）
      github_trending:  GitHub Trending Daily + Weekly（热门趋势）
      github_new:       GitHub Search API + Blog（新品发现）
      twitter:          twitter（排除 opinion 文章）
      opinion:          从 main+twitter 中分流出的 opinion 文章，独立排序选取

    GitHub 两子管道独立评分+配额，防止新品被 trending 高 stars 洗掉。
    """
    fallback_quotas = quota_per_tag or {}
    pipe_quotas = pipeline_quotas or {}

    # ── 第一步：标记不可参选的文章 ──
    for art in articles:
        if art.get("is_duplicate", False):
            art["filtered_out"] = True
            art["filter_reason"] = "duplicate"
        elif art.get("_relevance_priority", "none") == "none":
            art["filtered_out"] = True
            art["filter_reason"] = "not_relevant"

    # ── 第二步：将有资格的文章按管道分组 ──
    eligible = [a for a in articles
                if not a.get("is_duplicate", False)
                and a.get("_relevance_priority", "none") != "none"]

    # 先收集各渠道文章
    github_all = []
    pipe_articles: dict[str, list[dict]] = {
        "main": [], "github_trending": [], "github_new": [], "twitter": [],
    }
    for art in eligible:
        ch = art.get("channel", "")
        if ch == "github":
            github_all.append(art)
        elif ch == "twitter":
            pipe_articles["twitter"].append(art)
        elif ch in ("rss", "wechat", "exa", "manual"):
            pipe_articles["main"].append(art)
        else:
            pipe_articles["main"].append(art)

    # GitHub 分流到两个子管道
    gh_trending, gh_new = _split_github_subpipes(github_all)
    pipe_articles["github_trending"] = gh_trending
    pipe_articles["github_new"] = gh_new

    # ── 第 2.5 步：Twitter 管道热度硬门槛 ──
    twitter_before = len(pipe_articles.get("twitter", []))
    twitter_filtered = []
    twitter_heat_rejected = 0
    for art in pipe_articles.get("twitter", []):
        extra = art.get("extra") or {}
        heat = HeatScorer.twitter_heat_score(extra)
        art["_twitter_heat"] = round(heat, 1)
        if heat >= twitter_min_heat:
            twitter_filtered.append(art)
        else:
            art["filtered_out"] = True
            art["filter_reason"] = "twitter_low_heat"
            twitter_heat_rejected += 1
    pipe_articles["twitter"] = twitter_filtered

    if twitter_heat_rejected > 0:
        logger.info(
            f"Twitter 热度门槛: {twitter_before} → {len(twitter_filtered)} 篇 "
            f"(淘汰 {twitter_heat_rejected} 篇低热度推文, 门槛={twitter_min_heat})"
        )

    # ── 第 2.6 步：GitHub 两子管道独立 stars 门槛 ──
    for pipe_name, min_stars in [
        ("github_trending", github_trending_min_stars),
        ("github_new", github_new_min_stars),
    ]:
        before = len(pipe_articles.get(pipe_name, []))
        filtered_list = []
        rejected = 0
        for art in pipe_articles.get(pipe_name, []):
            extra = art.get("extra") or {}
            stars = extra.get("stars")
            if stars is not None and stars < min_stars:
                art["filtered_out"] = True
                art["filter_reason"] = f"{pipe_name}_low_stars"
                rejected += 1
            else:
                filtered_list.append(art)
        pipe_articles[pipe_name] = filtered_list

        if rejected > 0:
            logger.info(
                f"{pipe_name} stars 门槛: {before} → {len(filtered_list)} 篇 "
                f"(淘汰 {rejected} 篇, 门槛={min_stars})"
            )

    # ── 第 2.7 步：Opinion 文章从 main/twitter 分流到独立观点池 ──
    opinion_pool: list[dict] = []
    for pipe_name in ("main", "twitter"):
        remaining = []
        for art in pipe_articles.get(pipe_name, []):
            if art.get("_opinion_diverted"):
                opinion_pool.append(art)
            else:
                remaining.append(art)
        pipe_articles[pipe_name] = remaining

    opinion_pool.sort(
        key=lambda a: (
            1 if a.get("_content_type_vip") else 0,
            a.get("score", 0),
        ),
        reverse=True,
    )
    opinion_selected = opinion_pool[:opinion_max_items]
    opinion_selected_ids = {id(a) for a in opinion_selected}

    for art in opinion_pool:
        if id(art) not in opinion_selected_ids:
            art["filtered_out"] = True
            art["filter_reason"] = "opinion_quota_exceeded"

    logger.info(
        f"Opinion 分流: {len(opinion_pool)} 篇观点文章 → 选取 {len(opinion_selected)} 篇 "
        f"(VIP {sum(1 for a in opinion_selected if a.get('_content_type_vip'))} 篇)"
    )

    # ── 第三步：每个管道独立选取（带跨管道事件去重）──
    all_selected_ids: set[int] = set()
    all_quota_stats: dict[str, dict] = {}
    cross_pipe_titles: list[str] = []

    for pipe_name in ["main", "github_trending", "github_new", "twitter"]:
        quotas = pipe_quotas.get(pipe_name, fallback_quotas)
        pipe_eligible = pipe_articles.get(pipe_name, [])

        selected_ids, quota_stats = _select_by_tag_quota(
            pipe_eligible, quotas, default_quota, min_articles_warning,
            cross_pipe_titles=cross_pipe_titles,
        )
        for art in pipe_eligible:
            if id(art) in selected_ids:
                cross_pipe_titles.append(art.get("title", ""))
                # 标记子管道归属（仅 GitHub 文章，供 editor 渲染分区）
                if art.get("channel") == "github":
                    art["_github_subpipe"] = pipe_name
        all_selected_ids |= selected_ids
        all_quota_stats[pipe_name] = quota_stats

    # ── 第四步：标记所有文章的 filtered_out ──
    all_selected_ids |= opinion_selected_ids
    for art in opinion_selected:
        art["_output_section"] = "opinion"

    for art in eligible:
        if id(art) in all_selected_ids:
            art["filtered_out"] = False
            art["filter_reason"] = None
        else:
            if not art.get("filtered_out"):
                art["filtered_out"] = True
                art["filter_reason"] = "quota_exceeded"

    # opinion 配额统计
    all_quota_stats["opinion"] = {
        "opinion": {
            "quota": opinion_max_items,
            "supply": len(opinion_pool),
            "filled": len(opinion_selected),
            "low_supply": len(opinion_pool) < min_articles_warning,
            "vip_count": sum(1 for a in opinion_selected if a.get("_content_type_vip")),
        }
    }

    return articles, all_quota_stats


# ══════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════


def _cluster_by_title_similarity(articles: list[dict]) -> list[dict]:
    """对文章按标题关键词做简单聚类，让同一事件的多篇报道排在一起

    算法：提取标题中的英文单词和中文关键短语，计算交集比例。
    交集 ≥ 3 个关键词的文章归为同一组。
    输出：按组排序，组内按 channel 优先级排序（exa > rss > wechat > twitter）。
    每篇文章增加 _cluster_group 字段标记组号。
    """
    import re

    def extract_keywords(title: str) -> set[str]:
        """提取标题中的关键词（英文单词 + 中文 2-4 字词）"""
        # 英文：提取 ≥3 字母的单词，转小写
        en_words = {w.lower() for w in re.findall(r'[a-zA-Z]{3,}', title)}
        # 中文：提取 2-4 字连续中文
        zh_words = set(re.findall(r'[\u4e00-\u9fff]{2,4}', title))
        # 去掉过于通用的词
        stop = {'the', 'and', 'for', 'with', 'how', 'new', 'has', 'its',
                'that', 'this', 'from', 'are', 'was', 'will', 'can',
                '发布', '推出', '上线', '正式', '宣布', '更新', '最新'}
        return (en_words | zh_words) - stop

    # 提取每篇文章的关键词
    art_kws = [(a, extract_keywords(a.get("title", ""))) for a in articles]

    # 聚类：贪心合并
    groups: list[list[int]] = []  # 每组的文章索引
    assigned = set()

    for i, (a_i, kw_i) in enumerate(art_kws):
        if i in assigned:
            continue
        group = [i]
        assigned.add(i)
        for j, (a_j, kw_j) in enumerate(art_kws):
            if j in assigned:
                continue
            overlap = kw_i & kw_j
            if len(overlap) >= 2:
                group.append(j)
                assigned.add(j)
        groups.append(group)

    # 按组大小降序排序（多篇报道的组优先显示）
    groups.sort(key=lambda g: (-len(g), g[0]))

    # 输出：按组排序，标记组号
    result = []
    for group_idx, group in enumerate(groups):
        group_label = f"GROUP_{group_idx + 1}" if len(group) > 1 else ""
        for idx in group:
            art = articles[idx].copy()
            art["_cluster_group"] = group_label
            result.append(art)

    return result


def _summary_hint(article: dict) -> str:
    """判断文章 summary 是否需要强制 web_fetch 全文

    规则：
    - 摘要 < 50 字 → __MUST_FETCH__（信息不足，必须读全文）
    - 标题是纯英文但无中文摘要 → __MUST_FETCH__（需翻译+提取产品名）
    - 微信文章标题不含明确产品名 → __MUST_FETCH__（标题党风险高）
    - 其他 → __TODO__（可基于摘要写，建议读全文）
    """
    title = article.get("title", "")
    excerpt = (article.get("summary_clean", "") or article.get("summary", "") or "")
    channel = article.get("channel", "")

    # 摘要太短
    if len(excerpt.strip()) < 50:
        return "__MUST_FETCH__（摘要不足50字）"

    # 纯英文标题 + 无中文摘要
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in title)
    excerpt_has_chinese = any('\u4e00' <= c <= '\u9fff' for c in excerpt)
    if not has_chinese and not excerpt_has_chinese:
        return "__MUST_FETCH__（英文文章需读全文翻译）"

    # 微信标题常见标题党模式
    if channel == "wechat":
        clickbait_patterns = ["！", "刚刚", "炸了", "疯了", "太强了", "颠覆", "史上最"]
        if any(p in title for p in clickbait_patterns) and len(excerpt) < 100:
            return "__MUST_FETCH__（微信标题党，需读全文提取产品名）"

    return "__TODO__"


def _generate_llm_results_template(passed: list[dict], today_dir: Path):
    """从入选文章的真实 URL 生成 llm_results_template.json（2026-04-17 新增）

    解决问题：手写 llm_results.json 时编造假 URL 导致 editor.py 匹配失败。
    方案：自动从 filtered.json 的入选文章中提取真实 URL + 标题，
    按 editor.py 的板块 key 分组，预填到模板中。
    CodeBuddy 只需在 __TODO__ 处填入 summary/keywords/insight，
    URL 是从源数据复制的，不可能出错。

    模板结构与 llm_results.json 完全一致，填完后直接重命名即可使用。
    """
    # editor.py 的板块 key 映射规则
    section_map: dict[str, list[dict]] = {}
    for a in passed:
        tag = a.get("_primary_tag_llm", "") or (
            a.get("relevance_tags", ["unknown"])[0]
            if a.get("relevance_tags")
            else "unknown"
        )
        sec = a.get("_output_section", "")
        pipe = a.get("_github_subpipe", "")
        channel = a.get("channel", "")

        # 确定板块 key（与 editor.py 一致）
        if sec == "opinion":
            key = "opinion"
        elif channel == "twitter":
            key = "twitter"
        elif pipe == "github_trending":
            key = "github_trending"
        elif pipe == "github_new":
            key = "github_new"
        else:
            key = tag

        if key not in section_map:
            section_map[key] = []

        tag_source = a.get("_tag_source", "keyword_fallback")
        priority = "normal" if tag_source == "llm_classified" else "low"

        section_map[key].append({
            "url": a.get("url", ""),
            "title": a.get("title", "")[:80],
            "channel": a.get("channel", ""),
            "_excerpt": (a.get("summary_clean", "") or a.get("summary", "") or "")[:200],
            "_tag_source": tag_source,
            "_priority": priority,
            "summary": _summary_hint(a),
            "keywords": [],
        })

    # 按 editor.py 的固定板块顺序输出
    ordered_keys = [
        "ai_agent", "ai_core", "ai_video", "ai_gaming", "ai_social",
        "ai_business", "ai_product", "opinion", "twitter",
        "github_trending", "github_new",
    ]

    template = {}
    for key in ordered_keys:
        articles = section_map.get(key, [])
        template[key] = {
            "articles": articles,
            "insight": "__TODO__" if articles else "",
        }

    # 添加 ordered_keys 中没有的板块
    for key in section_map:
        if key not in template:
            template[key] = {
                "articles": section_map[key],
                "insight": "__TODO__",
            }

    template_path = today_dir / "llm_results_template.json"
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total = sum(len(s["articles"]) for s in template.values())
    non_empty = sum(1 for s in template.values() if s["articles"])
    console.print(
        f"  📋 已生成 llm_results 模板: {template_path}\n"
        f"     {total} 篇文章 × {non_empty} 个板块，URL 已从 filtered.json 预填\n"
        f"     [yellow]请基于模板填写 summary/keywords/insight，保存为 llm_results.json[/yellow]\n"
        f"     [red]⚠️ 禁止修改 url 字段——editor.py 会校验 URL 必须与 filtered.json 一致[/red]"
    )


def run_filter(date: str | None = None, config: dict | None = None) -> dict:
    """
    Layer 2 主入口：读取 raw.json，执行五步流水线，输出 filtered.json。

    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天
        config: 完整配置字典（config.yaml 的内容），如果为 None 则自动加载

    Returns:
        统计信息字典
    """
    import yaml

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

    filter_cfg = config.get("filter", {})
    now = datetime.now(timezone(timedelta(hours=8)))

    # ── 路径 ──
    data_dir = Path(__file__).parent.parent / "data"
    today_dir = data_dir / date
    raw_path = today_dir / "raw.json"
    filtered_path = today_dir / "filtered.json"

    if not raw_path.exists():
        console.print(f"[red]❌ raw.json 不存在: {raw_path}[/red]")
        return {"error": f"raw.json not found: {raw_path}"}

    # ── 加载 raw.json ──
    console.print(f"\n[bold cyan]═══ Layer 2: 筛选 ({date}) ═══[/bold cyan]\n")
    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
    articles = raw_data.get("articles", [])
    total_input = len(articles)
    console.print(f"📥 输入: {total_input} 篇文章")

    # ══ Step 1: Normalize ══
    console.print("\n[bold]Step 1: Normalize[/bold]")
    normalizer = Normalizer(
        url_strip_params=filter_cfg.get("url_strip_params", [])
    )
    for art in articles:
        normalizer.normalize(art)
    console.print(f"  ✅ 标准化完成: {total_input} 篇")

    # ══ Step 2: Dedup ══
    console.print("\n[bold]Step 2: Dedup[/bold]")
    scorer = HeatScorer(filter_cfg)
    dedup = DedupEngine(
        window_hours=filter_cfg.get("dedup_window_hours", 72),
        similarity_threshold=filter_cfg.get("title_similarity_threshold", 0.85),
        source_weight_fn=scorer.get_source_weight,
    )
    # 加载历史去重窗口
    history_files = []
    for days_back in [1, 2]:
        prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
        history_files.append(data_dir / prev_date / "filtered.json")
    dedup.load_history(history_files)

    # 加载 GitHub 持久化去重库
    github_seen_path = data_dir / "github_seen.json"
    dedup.load_github_seen(github_seen_path)

    unique_articles = dedup.process(articles)
    after_dedup = len(unique_articles)
    console.print(f"  ✅ 去重完成: {total_input} → {after_dedup} 篇")

    # ══ Step 2.5: 标题黑名单过滤 ══
    console.print("\n[bold]Step 2.5: Title Blacklist（标题黑名单）[/bold]")
    title_blacklist = TitleBlacklist()
    blacklisted_count = 0
    for art in unique_articles:
        if title_blacklist.is_blacklisted(art.get("title", "")):
            art["is_duplicate"] = True  # 复用去重标记，让后续流程统一跳过
            art["_dup_reason"] = f"title_blacklist:{art.get('title', '')[:40]}"
            blacklisted_count += 1
    if blacklisted_count > 0:
        console.print(f"  ⚠️ 标题黑名单过滤: {blacklisted_count} 篇（论坛列表页/聚合页等）")
    else:
        console.print("  ✅ 标题黑名单: 无命中")

    # ══ Step 2.6: 聚合新闻标记（不拦截，标记供 Layer 3 拆分）══
    aggregate_detector = AggregateDetector()
    aggregate_count = 0
    for art in unique_articles:
        if aggregate_detector.is_aggregate(art.get("title", "")):
            art["_is_aggregate"] = True
            aggregate_count += 1
    if aggregate_count > 0:
        console.print(f"  📋 聚合新闻标记: {aggregate_count} 篇（供 Layer 3 拆分）")

    # ══ Step 3: Relevance ══
    console.print("\n[bold]Step 3: Relevance（相关性硬筛）[/bold]")
    relevance = RelevanceFilter(filter_cfg)

    relevance_stats = defaultdict(int)
    priority_stats = defaultdict(int)

    for art in unique_articles:
        is_relevant, matched_tags, priority = relevance.check(art)
        art["_relevance_tags"] = matched_tags
        art["_relevance_priority"] = priority
        art["relevance_tags"] = [t for t in matched_tags if not t.startswith("_")]
        art["relevance_priority"] = priority

        if is_relevant:
            for tag in matched_tags:
                relevance_stats[tag] += 1
            priority_stats[priority] += 1

    after_relevance = sum(
        1 for a in unique_articles if a["_relevance_priority"] != "none"
    )
    console.print(f"  ✅ 相关性筛选: {after_dedup} → {after_relevance} 篇")
    console.print(f"     标签分布: {dict(relevance_stats)}")
    console.print(f"     优先级: {dict(priority_stats)}")

    # ══ Step 3b/3c: LLM 智能分类 + 捞漏 ══
    llm_light_cfg = filter_cfg.get("llm_light_filter", {})
    llm_enabled = llm_light_cfg.get("enabled", True)
    if llm_enabled:
        console.print("\n[bold]Step 3b/3c: LLM 智能分类（全量分类 + 捞漏）[/bold]")
        llm_filter = LLMLightFilter(config, data_dir=today_dir)

        # 尝试加载 CodeBuddy 预生成的分类结果
        llm_filter_path = today_dir / "llm_filter_results.json"
        if llm_filter_path.exists():
            llm_filter.load_results(llm_filter_path)
            console.print(f"  [green]已加载 LLM 分类结果: {llm_filter_path}[/green]")
        else:
            console.print("  [dim]未找到 llm_filter_results.json，将导出候选文章供 CodeBuddy 分类[/dim]")

        keyword_passed = [a for a in unique_articles if a["_relevance_priority"] != "none"]
        keyword_rejected = [a for a in unique_articles if a["_relevance_priority"] == "none"
                           and not a.get("is_duplicate", False)]
        valid_tags = set(filter_cfg.get("relevance_tags", {}).keys())

        denoised, rescued = llm_filter.run(keyword_passed, keyword_rejected, valid_tags)

        # 更新统计
        if rescued:
            for art in rescued:
                for tag in art.get("_relevance_tags", []):
                    relevance_stats[tag] += 1
                priority_stats["supplementary"] = priority_stats.get("supplementary", 0) + 1

        after_llm = sum(
            1 for a in unique_articles if a["_relevance_priority"] != "none"
        )
        console.print(f"  📊 LLM 轻筛结果: {after_relevance} → {after_llm} 篇")
        after_relevance = after_llm
    else:
        console.print("\n[dim]Step 3b/3c: LLM 轻筛已关闭（config: llm_light_filter.enabled=false）[/dim]")

    # ══ Step 4: Score ══
    console.print("\n[bold]Step 4: Score（热度评分 — 主日报四维度 / GitHub+Twitter 含互动数据）[/bold]")
    # scorer 已在 Step 2 创建（供去重选代表使用）

    for art in unique_articles:
        if art["_relevance_priority"] == "none":
            art["score"] = 0
            art["score_details"] = {}
            continue
        score, details = scorer.score(art, now)
        art["score"] = score
        art["score_details"] = {k: round(v, 1) for k, v in details.items()}

    # ══ Step 5: Filter ══
    console.print("\n[bold]Step 5: Filter（多管道独立配额制）[/bold]")
    twitter_cfg = filter_cfg.get("twitter_quality", {})
    gh_trending_cfg = filter_cfg.get("github_trending_quality", {})
    gh_new_cfg = filter_cfg.get("github_new_quality", {})
    _, quota_stats = apply_filter(
        unique_articles,
        pipeline_quotas=filter_cfg.get("pipeline_quotas"),
        quota_per_tag=filter_cfg.get("quota_per_tag"),
        default_quota=filter_cfg.get("default_quota", 5),
        min_articles_warning=filter_cfg.get("min_articles_warning", 3),
        twitter_min_heat=twitter_cfg.get("min_heat", 30.0),
        github_trending_min_stars=gh_trending_cfg.get("min_stars", 100),
        github_new_min_stars=gh_new_cfg.get("min_stars", 30),
        opinion_max_items=filter_cfg.get("opinion_section", {}).get("max_items", 3),
    )

    passed = [a for a in unique_articles if not a.get("filtered_out", True)]
    console.print(f"  ✅ 配额筛选完成: {after_relevance} → {len(passed)} 篇入选")

    # 打印各管道各领域配额使用情况
    pipe_labels = {
        "main": "📰 主日报",
        "github_trending": "🐙 GitHub 热门趋势",
        "github_new": "🆕 GitHub 新品发现",
        "twitter": "🐦 Twitter",
        "opinion": "💡 行业观点",
    }
    for pipe_name in ["main", "github_trending", "github_new", "twitter", "opinion"]:
        pipe_qs = quota_stats.get(pipe_name, {})
        if not pipe_qs:
            continue

        # opinion 管道的统计格式不同于标签配额
        if pipe_name == "opinion":
            op = pipe_qs.get("opinion", {})
            console.print(
                f"\n  {pipe_labels[pipe_name]} (入选 {op.get('filled', 0)} 篇, "
                f"供给 {op.get('supply', 0)}, VIP {op.get('vip_count', 0)} 篇):"
            )
            continue

        pipe_total = sum(qs["filled"] for qs in pipe_qs.values())
        console.print(f"\n  {pipe_labels.get(pipe_name, pipe_name)} (入选 {pipe_total} 篇):")
        for tag, qs in sorted(pipe_qs.items()):
            if qs["supply"] == 0:
                continue  # 跳过该管道中没有供给的标签
            status = "⚠️ 低供给" if qs["low_supply"] else "✅"
            console.print(
                f"     {tag}: {qs['filled']}/{qs['quota']} 篇 "
                f"(供给 {qs['supply']}) "
                f"[{qs['min_score']}-{qs['top_score']}分] {status}"
            )

    # ── 统计 ──
    score_ranges = {"7-8": 0, "5-6": 0, "3-4": 0, "1-2": 0}
    for a in passed:
        s = a.get("score", 0)
        if s >= 7:
            score_ranges["7-8"] += 1
        elif s >= 5:
            score_ranges["5-6"] += 1
        elif s >= 3:
            score_ranges["3-4"] += 1
        else:
            score_ranges["1-2"] += 1

    channel_stats = defaultdict(int)
    for a in passed:
        channel_stats[a.get("channel", "unknown")] += 1

    # 按标签统计通过数
    tag_passed_stats = defaultdict(int)
    for a in passed:
        for tag in a.get("relevance_tags", []):
            tag_passed_stats[tag] += 1

    # 按内容类型统计（仅主日报管道）
    content_type_stats = defaultdict(int)
    for a in passed:
        ct = a.get("_content_type")
        if ct:
            content_type_stats[ct] += 1
    vip_opinion_count = sum(
        1 for a in passed
        if a.get("_content_type") == "opinion" and a.get("_content_type_vip")
    )

    stats = {
        "input": total_input,
        "after_dedup": after_dedup,
        "after_relevance": after_relevance,
        "after_filter": len(passed),
        "by_relevance_tag": dict(relevance_stats),
        "by_tag_passed": dict(tag_passed_stats),
        "by_priority": dict(priority_stats),
        "by_score_range": score_ranges,
        "by_channel": dict(channel_stats),
        "by_content_type": dict(content_type_stats),
        "vip_opinion_count": vip_opinion_count,
        "quota_stats": quota_stats,
    }

    # ── 清理内部字段，构建输出 ──
    output_articles = []
    for art in unique_articles:
        # 移除内部临时字段
        out = {k: v for k, v in art.items() if not k.startswith("_")}
        # 保留内容类型分类结果（从内部字段复制到公开字段）
        if "_content_type" in art:
            out["content_type"] = art["_content_type"]
        if art.get("_content_type_vip"):
            out["content_type_vip"] = True
        if "_output_section" in art:
            out["output_section"] = art["_output_section"]
        if art.get("_primary_tag_llm"):
            out["primary_tag_llm"] = art["_primary_tag_llm"]
        if art.get("_quality") is not None:
            out["quality"] = art["_quality"]
        if art.get("_opinion_diverted"):
            out["opinion_diverted"] = True
        if art.get("_llm_classified"):
            out["llm_classified"] = art["_llm_classified"]
        if art.get("_llm_classify_reason"):
            out["llm_classify_reason"] = art["_llm_classify_reason"]
        if art.get("_tag_source"):
            out["tag_source"] = art["_tag_source"]
        if art.get("_is_aggregate"):
            out["is_aggregate"] = True
        if art.get("_github_subpipe"):
            out["github_subpipe"] = art["_github_subpipe"]
        # 移除 content 和原始 summary（太大），保留 summary_clean
        out.pop("content", None)
        out.pop("summary", None)
        output_articles.append(out)

    # 按 score 降序排列（通过的在前）
    output_articles.sort(
        key=lambda a: (not a.get("filtered_out", True), a.get("score", 0)),
        reverse=True,
    )

    # ── 写入 filtered.json ──
    output = {
        "date": date,
        "filtered_at": now.isoformat(),
        "config_snapshot": {
            "scoring_dimensions": "主日报四维度（时效3+覆盖3+quality质量1.5+内容类型调整）满分8；GitHub/Twitter保留互动数据维度",
            "content_type_scoring": "tech_product:+0.5, opinion:分流到观点板块(不降权), news:+0.0",
            "pipeline_quotas": filter_cfg.get("pipeline_quotas", {}),
            "quota_per_tag": filter_cfg.get("quota_per_tag", {}),
            "default_quota": filter_cfg.get("default_quota", 5),
            "dedup_window_hours": filter_cfg.get("dedup_window_hours", 72),
        },
        "stats": stats,
        "articles": output_articles,
    }

    today_dir.mkdir(parents=True, exist_ok=True)
    filtered_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"\n[green]💾 已保存: {filtered_path}[/green]")

    # ── 自动生成 llm_results_template.json（2026-04-17 新增）──
    # 从 filtered.json 的入选文章中提取真实 URL，按板块分组预填模板
    # 杜绝手写编造 URL 导致 editor.py URL 不匹配的问题
    _generate_llm_results_template(passed, today_dir)

    # ── 更新 GitHub 持久化去重库 ──
    new_github_arts = [a for a in passed if a.get("channel") == "github"]
    if new_github_arts:
        dedup.save_github_seen(new_github_arts, date)
        console.print(f"  🐙 GitHub 持久去重库: +{len(new_github_arts)} 个项目")

    # ── 打印 Top 文章（按领域分组） ──
    _print_top_articles(passed[:20])

    console.print(f"\n[bold cyan]═══ Layer 2 完成 ═══[/bold cyan]")
    console.print(f"  📊 {total_input} → 去重 {after_dedup} → "
                  f"相关 {after_relevance} → 入选 {len(passed)}")

    return stats


def _print_top_articles(articles: list[dict]):
    """打印 Top 文章表格"""
    if not articles:
        return

    table = Table(title="🏆 Top 20 文章", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("分数", style="bold", width=5)
    table.add_column("标签", width=20)
    table.add_column("来源", width=15)
    table.add_column("标题", width=60)
    table.add_column("评分明细", width=30)

    for i, art in enumerate(articles[:20], 1):
        score = art.get("score", 0)
        tags = ", ".join(art.get("relevance_tags", []))
        source = art.get("source_name", "")[:15]
        title = art.get("title", "")[:60]
        details = art.get("score_details", {})
        detail_str = " | ".join(f"{k}:{v}" for k, v in details.items())

        # 颜色标记（满分 8）
        score_style = "green" if score >= 6 else "yellow" if score >= 3 else "red"
        table.add_row(
            str(i),
            f"[{score_style}]{score}[/{score_style}]",
            tags,
            source,
            title,
            detail_str,
        )

    console.print(table)


# ══════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    run_filter(date=target_date)
