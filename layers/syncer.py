"""
Layer 4: 同步（Syncer）—— 将入选产品同步到飞书多维表格

双入口：
  1. 从日报批量选产品：syncer --date 2026-04-18 --products "Archon, OpenClaw"
  2. 手动链接输入：    syncer --url "https://github.com/xxx/yyy"
  3. 仅更新深度报告：  syncer --date 2026-04-18 --update "Archon"

字段映射（飞书表格字段名与下列保持一致）：
  产品名 / 日期 / 板块 / 一句话简讯 / 关键词 / 原文链接 / 深度报告 / 稳定ID / 创建时间

幂等策略：
  稳定 ID = md5(产品名 + 原文url)[:16]，命中即更新，未命中即新建。

深度报告存储方案（2026-04-19 重构）：
  - 存储位置：独立 GitHub 仓库（由 .env 的 PRODUCT_ANALYSIS_OWNER / PRODUCT_ANALYSIS_REPO 指定）
  - 本地工作目录：由 PRODUCT_ANALYSIS_REPO_DIR 指定（在主仓库外，避免被 NewsFunnel 追踪）
  - 目录结构：{repo}/{YYYY-MM-DD}/{产品}.md  + {repo}/{YYYY-MM-DD}/daily.md
  - 飞书表格中"深度报告"字段写入 GitHub blob URL
  - 同一份报告反复 sync 时会 git commit --amend 合并到当天 commit，避免污染历史

降级策略：
  - 深度报告 .md 不存在 → 对应字段留空，其他字段照常同步
  - GitHub 推送失败 → 打印 warning，跳过深度报告字段
  - LLM 字段缺失 → 留空，不中断

依赖：
  httpx（已在 requirements.txt）
  系统 git（走本机已配置的 SSH 凭证，无需额外 PAT）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import httpx
import yaml
from dotenv import load_dotenv

logger = logging.getLogger("syncer")

BASE_DIR = Path(__file__).parent.parent
FEISHU_HOST = "https://open.feishu.cn"


# ══════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════

@dataclass
class SyncRecord:
    """待同步到飞书的一条产品记录"""
    product_name: str
    date: str                           # YYYY-MM-DD
    section: str                        # 中文板块名（单选）
    summary: str = ""
    keywords: str = ""                  # "k1 | k2 | k3"
    article_url: str = ""
    report_url: str = ""                # GitHub blob URL（可空）
    report_local_path: Optional[Path] = None  # 本地 md 路径，供上传
    stable_id: str = field(init=False)

    def __post_init__(self):
        base = f"{self.product_name}::{self.article_url}"
        self.stable_id = hashlib.md5(base.encode("utf-8")).hexdigest()[:16]

    # syncer 写入的字段白名单。飞书表上任何不在此列表里的字段（如 "进度" "备注" 等
    # 手工管理字段、以及 "创建时间" 等系统字段）都不会被 syncer 触碰——create/update
    # 时不会传递，飞书 API 对未传字段保持原值不变。
    MANAGED_FIELDS: tuple[str, ...] = (
        "产品名", "日期", "板块", "一句话简讯", "关键词",
        "原文链接", "深度报告", "稳定ID",
    )

    def to_feishu_fields(self, field_map: dict) -> dict:
        """
        转换为飞书 API 的 fields dict。

        契约：
        1. 只输出 MANAGED_FIELDS 列表中的字段，其他字段（如手工填的"进度"）不动。
        2. 字段名与飞书表头一一对应（飞书支持 field_name 直接调用，无需 field_id）。
        3. 字段在飞书"隐藏"只是视图层设置，API 读写不受影响。
        """
        date_ts = _date_to_ms(self.date)
        fields: dict = {}
        fields["产品名"] = self.product_name
        fields["日期"] = date_ts
        if self.section:
            fields["板块"] = self.section
        if self.summary:
            fields["一句话简讯"] = self.summary
        if self.keywords:
            fields["关键词"] = self.keywords
        if self.article_url:
            fields["原文链接"] = {"link": self.article_url, "text": self.article_url}
        if self.report_url:
            # 文案：优先用产品名，fallback 到通用 "📄 深度报告"
            link_text = self.product_name or "📄 深度报告"
            fields["深度报告"] = {"link": self.report_url, "text": link_text}
        fields["稳定ID"] = self.stable_id
        return fields


def _date_to_ms(date_str: str) -> int:
    """YYYY-MM-DD → 当日 00:00 东八区的毫秒时间戳（飞书 date 字段要求）"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
    return int(dt.timestamp() * 1000)


# ══════════════════════════════════════════
# GitHub 报告仓库（深度报告 + 日报 md 存储）
# ══════════════════════════════════════════

class GitHubReportsRepo:
    """
    独立 GitHub 仓库形式存放深度分析报告 & 日报 md。

    设计：
      - 通过本地 git clone 进行读写，走系统 SSH 凭证
      - 目录结构：{repo_dir}/{YYYY-MM-DD}/{产品名}.md（深度报告）
                  {repo_dir}/{YYYY-MM-DD}/daily.md（日报）
      - 写入后自动 commit + push（失败打 warning 不抛）
      - 飞书表格里的"深度报告"链接使用 GitHub blob URL

    URL 格式：
      https://github.com/{owner}/{repo}/blob/{branch}/{date}/{file}.md
    """

    def __init__(
        self,
        repo_dir: Path,
        owner: str,
        repo: str,
        branch: str = "main",
        enable_push: bool = True,
    ):
        self.repo_dir = repo_dir
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.enable_push = enable_push

    @classmethod
    def from_env(cls) -> Optional["GitHubReportsRepo"]:
        """从 .env 构造；任一关键项缺失返回 None"""
        repo_dir = os.getenv("PRODUCT_ANALYSIS_REPO_DIR", "").strip()
        owner = os.getenv("PRODUCT_ANALYSIS_OWNER", "").strip()
        repo = os.getenv("PRODUCT_ANALYSIS_REPO", "").strip()
        branch = os.getenv("PRODUCT_ANALYSIS_BRANCH", "main").strip()
        if not (repo_dir and owner and repo):
            if repo_dir and not (owner and repo):
                logger.warning(
                    "PRODUCT_ANALYSIS_REPO_DIR 已配置，但 PRODUCT_ANALYSIS_OWNER/REPO 未配置，跳过 GitHub 同步"
                )
            return None
        rd = Path(repo_dir).expanduser()
        if not (rd / ".git").exists():
            logger.warning(f"PRODUCT_ANALYSIS_REPO_DIR={rd} 不是 git 仓库，跳过 GitHub 同步")
            return None
        return cls(repo_dir=rd, owner=owner, repo=repo, branch=branch)

    # ─────────── git 封装 ───────────

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """在 repo_dir 下执行 git 命令"""
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=check,
        )

    def _pull_latest(self) -> bool:
        """push 前先 pull，降低冲突概率"""
        try:
            self._git("pull", "--rebase", "--autostash", "origin", self.branch, check=False)
            return True
        except Exception as e:
            logger.warning(f"git pull 失败（首次推送空仓库时正常）: {e}")
            return False

    def _has_changes(self) -> bool:
        """检查工作区是否有变更"""
        r = self._git("status", "--porcelain", check=False)
        return bool(r.stdout.strip())

    def _commit_and_push(self, message: str) -> bool:
        """add + commit + push；无变更时返回 True"""
        if not self._has_changes():
            return True
        try:
            self._git("add", "-A")
            self._git("-c", "user.name=ai-daily-syncer",
                      "-c", "user.email=ai-daily-syncer@local",
                      "commit", "-m", message)
        except subprocess.CalledProcessError as e:
            logger.warning(f"git commit 失败: {e.stderr}")
            return False

        if not self.enable_push:
            return True

        try:
            self._pull_latest()
            r = self._git("push", "origin", self.branch, check=False)
            if r.returncode != 0:
                logger.warning(f"git push 失败: {r.stderr}")
                return False
            return True
        except Exception as e:
            logger.warning(f"git push 异常: {e}")
            return False

    # ─────────── 对外 API ───────────

    def put_report(self, date: str, product_name: str, local_md: Path) -> str:
        """
        上传深度报告到 GitHub。
        返回 GitHub blob URL；失败返回空字符串。
        """
        if not local_md.exists():
            return ""
        safe = _safe_name(product_name)
        rel_path = f"{date}/{safe}.md"
        dst = self.repo_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_md, dst)

        if not self._commit_and_push(f"syncer: 深度报告 {date}/{safe}"):
            logger.warning(f"推送深度报告失败: {rel_path}")
            return ""

        return self._blob_url(rel_path)

    def put_daily(self, date: str, local_md: Path) -> str:
        """
        推送日报 md 到 GitHub（文件名固定为 daily.md，覆盖写入）。
        返回 blob URL；失败返回空字符串。
        """
        if not local_md.exists():
            return ""
        rel_path = f"{date}/daily.md"
        dst = self.repo_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_md, dst)

        if not self._commit_and_push(f"syncer: 日报 {date}"):
            logger.warning(f"推送日报失败: {rel_path}")
            return ""

        return self._blob_url(rel_path)

    def _blob_url(self, rel_path: str) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/blob/{self.branch}/{rel_path}"


# ══════════════════════════════════════════
# 飞书 API 客户端
# ══════════════════════════════════════════

class FeishuClient:
    """轻量飞书 API 客户端：tenant token + bitable"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        app_token: str,
        table_id: str,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.table_id = table_id
        self._client = httpx.Client(timeout=30.0)
        self._tenant_token = ""
        self._token_expire_at = 0.0

    # ─────────── 认证 ───────────

    def _get_tenant_token(self) -> str:
        """获取 tenant_access_token，带缓存（有效期 2 小时）"""
        if self._tenant_token and time.time() < self._token_expire_at - 60:
            return self._tenant_token

        url = f"{FEISHU_HOST}/open-apis/auth/v3/tenant_access_token/internal"
        resp = self._client.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
        self._tenant_token = data["tenant_access_token"]
        self._token_expire_at = time.time() + int(data.get("expire", 7200))
        return self._tenant_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """统一请求入口，自动附带 auth header，401 时重试一次"""
        url = f"{FEISHU_HOST}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        for attempt in range(3):
            resp = self._client.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 401:
                # token 失效，强制刷新
                self._tenant_token = ""
                headers.update(self._headers())
                continue
            if resp.status_code >= 500:
                time.sleep(1.5 ** attempt)
                continue
            break

        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            raise
        if data.get("code") not in (0, None):
            raise RuntimeError(f"[{method} {path}] 飞书 API 错误: {data}")
        return data

    # ─────────── Bitable：查询 / 新建 / 更新 ───────────

    def find_record_by_stable_id(self, stable_id: str) -> Optional[str]:
        """按稳定ID 查找记录，返回 record_id 或 None"""
        path = (
            f"/open-apis/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records/search"
        )
        body = {
            "filter": {
                "conjunction": "and",
                "conditions": [{
                    "field_name": "稳定ID",
                    "operator": "is",
                    "value": [stable_id],
                }],
            },
            "automatic_fields": False,
        }
        data = self._request("POST", path, params={"page_size": 1}, json=body)
        items = data.get("data", {}).get("items", []) or []
        if items:
            return items[0].get("record_id")
        return None

    def create_record(self, fields: dict) -> str:
        path = (
            f"/open-apis/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records"
        )
        data = self._request("POST", path, json={"fields": fields})
        return data["data"]["record"]["record_id"]

    def update_record(self, record_id: str, fields: dict) -> None:
        path = (
            f"/open-apis/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records/{record_id}"
        )
        self._request("PUT", path, json={"fields": fields})


# ══════════════════════════════════════════
# 数据源：从 filtered.json + llm_results.json 构建 SyncRecord
# ══════════════════════════════════════════

class DataLoader:
    """负责按日期/产品名定位文章 + LLM 结果，拼装 SyncRecord"""

    def __init__(self, date: str, config: dict):
        self.date = date
        self.config = config
        self.today_dir = BASE_DIR / "data" / date

        filtered_path = self.today_dir / "filtered.json"
        llm_path = self.today_dir / "llm_results.json"

        if not filtered_path.exists():
            raise FileNotFoundError(f"filtered.json 不存在: {filtered_path}")

        self.filtered = json.loads(filtered_path.read_text(encoding="utf-8"))
        self.articles: list[dict] = [
            a for a in self.filtered.get("articles", []) if not a.get("filtered_out", True)
        ]

        self.llm_results = {}
        if llm_path.exists():
            self.llm_results = json.loads(llm_path.read_text(encoding="utf-8"))

        # 构建 URL → LLM 项的反查
        self._llm_by_url: dict[str, dict] = {}
        for section_key, section_data in self.llm_results.items():
            if not isinstance(section_data, dict):
                continue
            for item in section_data.get("articles", []) or []:
                url = item.get("url", "")
                if url:
                    self._llm_by_url[url] = item

        # 板块 tag → 中文 title 映射
        editor_cfg = config.get("editor", {})
        self.tag_to_title: dict[str, str] = {
            s["tag"]: s["title"]
            for s in editor_cfg.get("sections", []) if isinstance(s, dict)
        }
        self.opinion_title = editor_cfg.get("opinion_section", {}).get("title", "行业观点")

    def find_article_by_product(self, product: str) -> Optional[dict]:
        """按产品名（模糊匹配 title）找文章"""
        p = product.strip().lower()
        # 优先精确匹配
        for a in self.articles:
            title = (a.get("title") or "").lower()
            if p == title:
                return a
        # 其次子串匹配
        for a in self.articles:
            title = (a.get("title") or "").lower()
            if p in title:
                return a
        return None

    def build_record(self, article: dict, override_product: Optional[str] = None) -> SyncRecord:
        """从 filtered 的单篇 article 构建 SyncRecord"""
        url = article.get("url", "")
        llm_item = self._llm_by_url.get(url, {})

        # 产品名：优先用参数传入（用户指定），否则用 title
        product_name = override_product or article.get("title", "").strip()

        # 板块：主日报看 primary_tag_llm；opinion 用 opinion_title
        tag = article.get("primary_tag_llm", "") or article.get("_primary_tag_llm", "")
        if article.get("output_section") == "opinion" or tag == "opinion":
            section = self.opinion_title
        else:
            section = self.tag_to_title.get(tag, "")

        # 简讯 / 关键词
        summary = llm_item.get("summary", "") or article.get("summary", "")
        kw_list = llm_item.get("keywords", []) or []
        keywords = " | ".join(k for k in kw_list if k)

        # 深度报告路径（archiver 按产品归档：data/reports/{product}/{date}.md）
        safe_name = _safe_name(product_name)
        report_path = BASE_DIR / "data" / "reports" / safe_name / f"{self.date}.md"
        if not report_path.exists():
            report_path = None

        return SyncRecord(
            product_name=product_name,
            date=self.date,
            section=section,
            summary=summary,
            keywords=keywords,
            article_url=url,
            report_local_path=report_path,
        )


def _safe_name(name: str) -> str:
    """产品名 → 安全文件夹名（与 archiver.py 保持一致的风格）"""
    import re
    return re.sub(r"[^\w\-]", "_", name).strip("_")[:64]


# ══════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════

def run_syncer(
    date: Optional[str] = None,
    products: Optional[list[str]] = None,
    url: Optional[str] = None,
    update_only: Optional[list[str]] = None,
    dry_run: bool = False,
    force: bool = False,
    push_daily: bool = False,
    config: Optional[dict] = None,
) -> dict:
    """
    Layer 4 同步主入口。

    Args:
        date: 日期（YYYY-MM-DD），--products / --update / --push-daily 模式必填
        products: 产品名列表（从日报选取）
        url: 单条外部链接（手动输入模式，与 archiver 逻辑相同）
        update_only: 仅更新已有记录的深度报告字段
        dry_run: 只打印 record，不调飞书 / 不 push git
        force: 强制覆盖所有字段
        push_daily: 仅推送日报 md 到 GitHub 仓库（不动飞书表格）
        config: 预加载的 config，None 时自动加载

    Returns:
        {"created": n, "updated": n, "skipped": n, "failed": n, "details": [...]}
    """
    from rich.console import Console
    console = Console()

    load_dotenv(BASE_DIR / ".env")

    if config is None:
        config_path = BASE_DIR / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

    # ── 读凭证 ──
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    app_token = os.getenv("FEISHU_BITABLE_APP_TOKEN", "").strip()
    table_id = os.getenv("FEISHU_BITABLE_TABLE_ID", "").strip()

    # GitHub 报告仓库（可选，未配则深度报告/日报不上传）
    gh_repo = None if dry_run else GitHubReportsRepo.from_env()

    # ── push_daily 专用分支：只推日报 md，不碰飞书表格 ──
    if push_daily:
        if not date:
            console.print("[red]--push-daily 必须配合 --date[/red]")
            return {"error": "date_required"}
        daily_md = BASE_DIR / "data" / date / "daily.md"
        if not daily_md.exists():
            console.print(f"[red]日报文件不存在: {daily_md}[/red]")
            return {"error": "daily_not_found"}
        if dry_run:
            console.print(f"[cyan]DRY-RUN[/cyan] 将推送 {daily_md} → GitHub")
            return {"dry_run": True}
        if gh_repo is None:
            console.print("[red]未配置 PRODUCT_ANALYSIS_REPO_DIR，无法推送日报[/red]")
            return {"error": "no_repo"}
        console.print(f"[bold cyan]═══ Layer 4 Syncer · 日报推送模式 ({date}) ═══[/bold cyan]")
        url = gh_repo.put_daily(date, daily_md)
        if url:
            console.print(f"[green]✓ 已推送日报到 GitHub[/green] {url}")
            return {"daily_url": url}
        else:
            console.print("[red]日报推送失败[/red]")
            return {"error": "push_failed"}

    if not dry_run and not all([app_id, app_secret, app_token, table_id]):
        console.print("[red]飞书凭证不完整，请检查 .env 中的 FEISHU_* 变量[/red]")
        return {"error": "missing_credentials"}

    client = None if dry_run else FeishuClient(
        app_id, app_secret, app_token, table_id
    )

    # ── 路由到对应模式 ──
    stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "details": []}

    if url:
        console.print(f"[bold cyan]═══ Layer 4 Syncer · URL 模式 ═══[/bold cyan]")
        _sync_by_url(url, date, client, gh_repo, dry_run, force, config, stats, console)
    elif products or update_only:
        if not date:
            console.print("[red]--date 必填[/red]")
            return {"error": "date_required"}
        loader = DataLoader(date, config)
        console.print(f"[bold cyan]═══ Layer 4 Syncer · 产品模式 ({date}) ═══[/bold cyan]")

        target_list = products or update_only
        only_report = bool(update_only)

        for product in target_list:
            product = product.strip()
            if not product:
                continue
            article = loader.find_article_by_product(product)
            if not article:
                console.print(f"  [yellow]未在日报中找到产品: {product}[/yellow]")
                stats["skipped"] += 1
                stats["details"].append({"product": product, "action": "skip", "reason": "not_found"})
                continue

            record = loader.build_record(article, override_product=product)
            _sync_single(record, client, gh_repo, dry_run, force, only_report, stats, console)
    else:
        console.print("[red]必须指定 --products / --url / --update / --push-daily 其中一个[/red]")
        return {"error": "no_input"}

    # ── 汇总 ──
    console.print(
        f"\n[bold green]═══ 完成 ═══[/bold green] "
        f"新建 {stats['created']} | 更新 {stats['updated']} | "
        f"跳过 {stats['skipped']} | 失败 {stats['failed']}"
    )
    return stats


def _sync_single(
    record: SyncRecord,
    client: Optional[FeishuClient],
    gh_repo: Optional[GitHubReportsRepo],
    dry_run: bool,
    force: bool,
    only_report: bool,
    stats: dict,
    console,
) -> None:
    """同步单条 record"""
    # 上传深度报告到 GitHub（如果有本地 md 且配置了仓库）
    if record.report_local_path and gh_repo:
        console.print(f"  [dim]推送深度报告 → GitHub: {record.product_name}[/dim]")
        record.report_url = gh_repo.put_report(
            record.date, record.product_name, record.report_local_path
        )
    elif record.report_local_path and dry_run:
        record.report_url = "<DRY-RUN:GitHub-blob-URL>"

    fields = record.to_feishu_fields({})

    # only_report 模式：只保留深度报告字段（和稳定ID）
    if only_report:
        fields = {k: v for k, v in fields.items() if k in ("深度报告", "稳定ID", "产品名")}
        if "深度报告" not in fields:
            console.print(f"  [yellow]无深度报告可更新: {record.product_name}[/yellow]")
            stats["skipped"] += 1
            return

    if dry_run:
        console.print(f"  [cyan]DRY-RUN[/cyan] {record.product_name}")
        console.print(f"    fields: {json.dumps(fields, ensure_ascii=False, indent=2)[:500]}")
        stats["details"].append({"product": record.product_name, "action": "dry_run"})
        return

    # 幂等检查
    try:
        existing_id = client.find_record_by_stable_id(record.stable_id)
    except Exception as e:
        console.print(f"  [red]查询失败 {record.product_name}: {e}[/red]")
        stats["failed"] += 1
        return

    try:
        if existing_id:
            client.update_record(existing_id, fields)
            console.print(f"  [green]✓ 更新[/green] {record.product_name} (record={existing_id[:8]})")
            stats["updated"] += 1
            stats["details"].append({"product": record.product_name, "action": "update", "record_id": existing_id})
        else:
            rid = client.create_record(fields)
            console.print(f"  [green]✓ 新建[/green] {record.product_name} (record={rid[:8]})")
            stats["created"] += 1
            stats["details"].append({"product": record.product_name, "action": "create", "record_id": rid})
    except Exception as e:
        console.print(f"  [red]写入失败 {record.product_name}: {e}[/red]")
        stats["failed"] += 1


def _sync_by_url(
    url: str,
    date: Optional[str],
    client: Optional[FeishuClient],
    gh_repo: Optional[GitHubReportsRepo],
    dry_run: bool,
    force: bool,
    config: dict,
    stats: dict,
    console,
) -> None:
    """
    URL 手动输入模式：暂不在线抓取元数据，仅把 URL 作为基础信息写入；
    产品名取 URL 末段 path 或用户后续手动在飞书编辑。
    如需完整流程（抓取+分析+归档），请先跑 archiver.py --url，然后用 --products 模式同步。
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    product_name = parsed.path.strip("/").split("/")[-1] or parsed.netloc
    d = date or datetime.now().strftime("%Y-%m-%d")

    record = SyncRecord(
        product_name=product_name,
        date=d,
        section="",
        article_url=url,
    )
    _sync_single(record, client, gh_repo, dry_run, force, only_report=False, stats=stats, console=console)


# ══════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="layers.syncer",
        description="Layer 4: 同步入选产品到飞书多维表格（深度报告/日报存入独立 GitHub 仓库）",
    )
    p.add_argument("--date", help="日期 YYYY-MM-DD（--products / --update / --push-daily 必填）")
    p.add_argument("--products", help="产品名列表，逗号分隔")
    p.add_argument("--url", help="手动输入外部链接（单条）")
    p.add_argument("--update", help="仅更新已有记录的深度报告字段（产品名列表，逗号分隔）")
    p.add_argument("--push-daily", action="store_true", help="仅推送日报 md 到 GitHub（不动飞书表格）")
    p.add_argument("--dry-run", action="store_true", help="不调飞书 API / 不 push git，仅打印")
    p.add_argument("--force", action="store_true", help="强制覆盖（保留给未来扩展）")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = _build_argparser().parse_args(argv)

    products = [s.strip() for s in args.products.split(",")] if args.products else None
    update = [s.strip() for s in args.update.split(",")] if args.update else None

    result = run_syncer(
        date=args.date,
        products=products,
        url=args.url,
        update_only=update,
        dry_run=args.dry_run,
        push_daily=args.push_daily,
    )
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
