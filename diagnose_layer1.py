#!/usr/bin/env python3
"""
Layer 1 诊断脚本 — 逐源检查每个 source 的采集状态
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 设置日志，捕获所有 warning/error
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("diagnose")

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

config = yaml.safe_load(open(ROOT_DIR / "config.yaml"))
today = datetime.now().strftime("%Y-%m-%d")
today_dt = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)


def is_today(published_at: str) -> bool:
    """判断文章是否是今天发布的"""
    if not published_at:
        return False
    try:
        from dateutil import parser as dp
        dt = dp.parse(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        dt_local = dt.astimezone(timezone(timedelta(hours=8)))
        return dt_local.date() == today_dt.date()
    except:
        return False


def print_section(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def print_source_result(name, status, count, today_count, error=None, details=None):
    if status == "ok":
        icon = "✅"
    elif status == "warn":
        icon = "⚠️"
    else:
        icon = "❌"
    
    today_str = f" (今日: {today_count})" if today_count is not None else ""
    print(f"  {icon} {name:<40} → {count:>3} 篇{today_str}")
    if error:
        print(f"     💥 错误: {error}")
    if details:
        print(f"     📝 {details}")


async def diagnose_rss():
    """诊断所有 RSS 源"""
    from layers.collector import RSSFetcher
    
    print_section("📡 RSS Fetcher 诊断")
    fetcher = RSSFetcher(config, timeout=15, max_retries=1, retry_delay=2)
    
    total = 0
    total_today = 0
    errors = []
    
    import httpx
    import feedparser
    
    for src in fetcher.sources:
        name = src["name"]
        url = src["url"]
        group = src.get("_group", "")
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url, timeout=15, follow_redirects=True,
                    headers={"User-Agent": "AI-Daily-News/1.0 (RSS Reader)"}
                )
                resp.raise_for_status()
                content = resp.text
            
            feed = feedparser.parse(content)
            
            if feed.bozo and not feed.entries:
                print_source_result(f"[{group}] {name}", "error", 0, 0, 
                                   error=f"RSS 解析失败: {feed.bozo_exception}")
                errors.append((name, str(feed.bozo_exception)))
                continue
            
            # 统计文章数和今日文章数
            entry_count = len(feed.entries)
            today_articles = []
            
            from layers.collector import parse_feed_date
            for entry in feed.entries:
                pub = parse_feed_date(entry)
                if is_today(pub):
                    today_articles.append(entry.get("title", "")[:50])
            
            today_count = len(today_articles)
            total += entry_count
            total_today += today_count
            
            status = "ok" if today_count > 0 else "warn"
            details = None
            if today_count > 0 and today_count <= 3:
                details = "今日: " + " | ".join(today_articles)
            elif today_count == 0 and entry_count > 0:
                # 看最新的文章日期
                latest = None
                for entry in feed.entries[:3]:
                    pub = parse_feed_date(entry)
                    if pub:
                        latest = pub
                        break
                details = f"最新文章日期: {latest or '未知'}"
            
            print_source_result(f"[{group}] {name}", status, entry_count, today_count, details=details)
            
        except httpx.TimeoutException:
            print_source_result(f"[{group}] {name}", "error", 0, 0, error="请求超时 (15s)")
            errors.append((name, "请求超时"))
        except httpx.HTTPStatusError as e:
            print_source_result(f"[{group}] {name}", "error", 0, 0, error=f"HTTP {e.response.status_code}")
            errors.append((name, f"HTTP {e.response.status_code}"))
        except Exception as e:
            print_source_result(f"[{group}] {name}", "error", 0, 0, error=str(e)[:80])
            errors.append((name, str(e)[:80]))
    
    print(f"\n  📊 RSS 合计: {total} 篇 (今日: {total_today}), 源: {len(fetcher.sources)}, 报错: {len(errors)}")
    return errors


async def diagnose_github():
    """诊断 GitHub 源"""
    from layers.collector import GitHubFetcher
    
    print_section("🐙 GitHub Fetcher 诊断")
    fetcher = GitHubFetcher(config, timeout=15, max_retries=1, retry_delay=2)
    
    try:
        articles = await fetcher.fetch()
        today_count = sum(1 for a in articles if is_today(a.published_at))
        print_source_result("GitHub (全部)", "ok", len(articles), today_count)
        
        # 按来源细分
        by_source = defaultdict(list)
        for a in articles:
            by_source[a.source_name].append(a)
        for src_name, arts in by_source.items():
            tc = sum(1 for a in arts if is_today(a.published_at))
            print_source_result(f"  └ {src_name}", "ok" if tc > 0 else "warn", len(arts), tc)
        
        return []
    except Exception as e:
        print_source_result("GitHub", "error", 0, 0, error=str(e)[:80])
        return [("GitHub", str(e)[:80])]


async def diagnose_exa():
    """诊断 Exa 搜索源"""
    from layers.collector import ExaFetcher
    
    print_section("🔎 Exa Fetcher 诊断")
    
    api_key = os.getenv("EXA_API_KEY", "")
    if not api_key:
        print("  ❌ EXA_API_KEY 未设置!")
        return [("Exa", "API Key 未设置")]
    else:
        print(f"  🔑 EXA_API_KEY: {api_key[:8]}...{api_key[-4:]}")
    
    fetcher = ExaFetcher(config, timeout=15, max_retries=1, retry_delay=2)
    
    errors = []
    try:
        articles = await fetcher.fetch()
        today_count = sum(1 for a in articles if is_today(a.published_at))
        print_source_result("Exa (全部)", "ok" if articles else "warn", len(articles), today_count)
        
        # 按来源细分
        by_source = defaultdict(list)
        for a in articles:
            by_source[a.source_name].append(a)
        for src_name, arts in sorted(by_source.items()):
            tc = sum(1 for a in arts if is_today(a.published_at))
            print_source_result(f"  └ {src_name}", "ok" if tc > 0 else "warn", len(arts), tc)
        
    except Exception as e:
        print_source_result("Exa", "error", 0, 0, error=str(e)[:120])
        errors.append(("Exa", str(e)[:80]))
    
    return errors


async def diagnose_twitter():
    """诊断 Twitter 源"""
    from layers.collector import TwitterFetcher
    
    print_section("🐦 Twitter Fetcher 诊断")
    
    fetcher = TwitterFetcher(config, timeout=15, max_retries=1, retry_delay=2)
    
    # 先检查 xreach 是否可用
    available = await fetcher._check_xreach()
    if not available:
        print("  ❌ xreach CLI 不可用!")
        print("  💡 安装方式: agent-reach install --env=auto")
        return [("Twitter", "xreach 不可用")]
    
    errors = []
    try:
        articles = await fetcher.fetch()
        today_count = sum(1 for a in articles if is_today(a.published_at))
        print_source_result("Twitter (全部)", "ok" if articles else "warn", len(articles), today_count)
        
        # 按搜索词/账号细分
        by_source = defaultdict(list)
        for a in articles:
            by_source[a.source_name].append(a)
        for src_name, arts in sorted(by_source.items()):
            tc = sum(1 for a in arts if is_today(a.published_at))
            print_source_result(f"  └ {src_name}", "ok" if tc > 0 else "warn", len(arts), tc)
        
    except Exception as e:
        print_source_result("Twitter", "error", 0, 0, error=str(e)[:120])
        errors.append(("Twitter", str(e)[:80]))
    
    return errors


async def diagnose_wechat():
    """诊断微信公众号源"""
    from layers.collector import WeChatFetcher
    
    print_section("💬 WeChat Fetcher 诊断")
    
    fetcher = WeChatFetcher(config, timeout=15, max_retries=1, retry_delay=2)
    
    # 先检查服务是否可用
    service_ok = await fetcher._check_service()
    base_url = fetcher.base_url
    if not service_ok:
        print(f"  ❌ we-mp-rss 服务不可用! (URL: {base_url})")
        print("  💡 请确认 Docker 容器正在运行")
        return [("WeChat/全部", "服务不可用")]
    else:
        print(f"  ✅ we-mp-rss 服务在线 ({base_url})")
    
    # 逐个公众号检查
    accounts = fetcher.wechat_config.get("accounts", [])
    enabled = [a for a in accounts if a.get("enabled", True)]
    
    print(f"  📊 公众号总数: {len(accounts)}, 启用: {len(enabled)}")
    
    errors = []
    total = 0
    total_today = 0
    
    import httpx
    import feedparser
    from layers.collector import extract_feed_url, parse_feed_date
    
    for acct in enabled:
        name = acct["name"]
        mp_id = acct.get("mp_id", "")
        
        if not mp_id:
            print_source_result(f"微信: {name}", "error", 0, 0, error="缺少 mp_id")
            errors.append((f"微信: {name}", "缺少 mp_id"))
            continue
        
        feed_url = f"{base_url}/feed/{mp_id}.rss"
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(feed_url, timeout=10, follow_redirects=True,
                                       headers={"User-Agent": "AI-Daily-News/1.0"})
                resp.raise_for_status()
                content = resp.text
            
            # 检查是否返回 HTML
            if content.strip().startswith("<!DOCTYPE") or content.strip().startswith("<html"):
                print_source_result(f"微信: {name}", "error", 0, 0, 
                                   error="返回 HTML 而非 RSS XML")
                errors.append((f"微信: {name}", "返回 HTML"))
                continue
            
            feed = feedparser.parse(content)
            
            if feed.bozo and not feed.entries:
                print_source_result(f"微信: {name}", "error", 0, 0,
                                   error=f"RSS 解析失败: {feed.bozo_exception}")
                errors.append((f"微信: {name}", str(feed.bozo_exception)[:60]))
                continue
            
            entry_count = len(feed.entries)
            today_articles = []
            
            for entry in feed.entries:
                pub = parse_feed_date(entry)
                title = entry.get("title", "")[:50]
                if is_today(pub):
                    today_articles.append(title)
            
            today_count = len(today_articles)
            total += entry_count
            total_today += today_count
            
            status = "ok" if today_count > 0 else "warn"
            details = None
            if today_count > 0:
                details = "今日: " + " | ".join(today_articles[:3])
                if today_count > 3:
                    details += f" ... (+{today_count-3})"
            elif entry_count > 0:
                latest = None
                for entry in feed.entries[:1]:
                    latest = parse_feed_date(entry)
                details = f"最新文章: {latest or '日期未知'}, 共 {entry_count} 篇缓存"
            else:
                details = "RSS feed 为空"
            
            print_source_result(f"微信: {name}", status, entry_count, today_count, details=details)
            
        except httpx.TimeoutException:
            print_source_result(f"微信: {name}", "error", 0, 0, error="请求超时")
            errors.append((f"微信: {name}", "请求超时"))
        except Exception as e:
            print_source_result(f"微信: {name}", "error", 0, 0, error=str(e)[:80])
            errors.append((f"微信: {name}", str(e)[:80]))
    
    print(f"\n  📊 微信合计: {total} 篇 (今日: {total_today}), 启用: {len(enabled)}, 报错: {len(errors)}")
    return errors


async def diagnose_manual():
    """诊断手工输入"""
    print_section("📝 Manual Fetcher 诊断")
    
    manual_dir = ROOT_DIR / config.get("global", {}).get("manual_input_dir", "./manual_input")
    if not manual_dir.exists():
        print(f"  ℹ️  手工输入目录不存在: {manual_dir}")
        return []
    
    files = [f for f in manual_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
    if files:
        print(f"  📁 发现 {len(files)} 个待处理文件:")
        for f in files:
            print(f"     • {f.name}")
    else:
        print(f"  ℹ️  手工输入目录为空")
    
    return []


async def main():
    start = time.time()
    
    print(f"\n{'#'*80}")
    print(f"  🔍 Layer 1 诊断报告 — {today}")
    print(f"  ⏰ 开始时间: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'#'*80}")
    
    all_errors = []
    
    # 1. RSS
    errors = await diagnose_rss()
    all_errors.extend(errors)
    
    # 2. GitHub
    errors = await diagnose_github()
    all_errors.extend(errors)
    
    # 3. Exa
    errors = await diagnose_exa()
    all_errors.extend(errors)
    
    # 4. Twitter
    errors = await diagnose_twitter()
    all_errors.extend(errors)
    
    # 5. WeChat
    errors = await diagnose_wechat()
    all_errors.extend(errors)
    
    # 6. Manual
    errors = await diagnose_manual()
    all_errors.extend(errors)
    
    # 汇总
    elapsed = time.time() - start
    print_section(f"📋 诊断汇总 (耗时 {elapsed:.1f}s)")
    
    if all_errors:
        print(f"\n  ❌ 共 {len(all_errors)} 个错误源:")
        for name, err in all_errors:
            print(f"     • {name}: {err}")
    else:
        print("\n  ✅ 所有源运行正常!")
    
    print()


if __name__ == "__main__":
    asyncio.run(main())
