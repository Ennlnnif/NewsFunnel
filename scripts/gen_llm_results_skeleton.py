#!/usr/bin/env python3
"""从 filtered.json 自动生成 llm_results.json 骨架。

用法：
    python scripts/gen_llm_results_skeleton.py [--date 2026-04-15]

功能：
    1. 读取 filtered.json 中 filtered_out=false 的入选文章
    2. 按板块分组（primary_tag_llm / opinion / twitter / github）
    3. 生成 llm_results.json 骨架（URL/title 保证来自 filtered.json）
    4. summary/keywords/insight 留空待填充

输出：
    data/{date}/llm_results.json（如已存在则备份为 .bak）
"""

import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def gen_skeleton(date: str | None = None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    data_dir = Path(__file__).parent.parent / "data" / date
    filtered_path = data_dir / "filtered.json"
    output_path = data_dir / "llm_results.json"

    if not filtered_path.exists():
        print(f"❌ filtered.json 不存在: {filtered_path}")
        return

    filt = json.loads(filtered_path.read_text(encoding="utf-8"))
    sel = [a for a in filt["articles"] if a.get("filtered_out") == False]

    # 按板块分组
    by_section: dict[str, list[dict]] = defaultdict(list)
    for a in sel:
        if a.get("opinion_diverted"):
            by_section["opinion"].append(a)
        elif a["channel"] == "twitter":
            by_section["twitter"].append(a)
        elif a["channel"] == "github":
            by_section["github"].append(a)
        else:
            tag = a.get("primary_tag_llm", "other")
            by_section[tag].append(a)

    # 生成骨架
    result = {}
    for section in ["ai_agent", "ai_core", "ai_business", "ai_video",
                     "ai_gaming", "ai_social", "ai_product", "opinion",
                     "twitter", "github"]:
        arts = by_section.get(section, [])
        if not arts:
            continue
        # 按 score 降序
        arts.sort(key=lambda a: -a.get("score", 0))
        result[section] = {
            "articles": [
                {
                    "id": i + 1,
                    "url": a["url"],
                    "title": a["title"],
                    "summary": "",  # 待填充
                    "keywords": [],  # 待填充
                }
                for i, a in enumerate(arts)
            ],
            "insight": "",  # 待填充
        }

    # 备份已有文件
    if output_path.exists():
        bak = output_path.with_suffix(".json.bak")
        shutil.copy2(output_path, bak)
        print(f"📦 已备份: {bak}")

    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 统计
    total = sum(len(s["articles"]) for s in result.values())
    print(f"✅ 已生成骨架: {output_path}")
    print(f"   {total} 篇文章，{len(result)} 个板块")
    for sec, data in result.items():
        n = len(data["articles"])
        print(f"   {sec}: {n} 篇")
        for a in data["articles"]:
            print(f"     - {a['title'][:50]}")

    # 输出操作清单：逐篇 web_fetch URL
    print(f"\n{'='*60}")
    print(f"📋 操作清单：请用以下 URL 逐篇 web_fetch 抓取全文后填写 summary")
    print(f"   ⚠️ 必须用下面的 URL 抓取，不要用记忆中的旧 URL")
    print(f"{'='*60}")
    idx = 0
    for sec, data in result.items():
        print(f"\n## {sec}")
        for a in data["articles"]:
            idx += 1
            title_short = a["title"][:45]
            print(f"  {idx:>2}. {title_short}")
            print(f"      URL: {a['url']}")


if __name__ == "__main__":
    target_date = None
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            target_date = sys.argv[idx + 1]
    gen_skeleton(target_date)
