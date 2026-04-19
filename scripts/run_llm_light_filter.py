"""
LLM 轻筛手动执行脚本
使用 CodeBuddy 主模型的判断结果，替代 OpenAI API 调用。
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from layers.filter import (
    Normalizer, DedupEngine, RelevanceFilter, LLMLightFilter,
    HeatScorer, apply_filter,
)

config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
filter_cfg = config.get("filter", {})
now = datetime.now(timezone(timedelta(hours=8)))
date = "2026-04-13"

# ── 加载 raw.json ──
raw = json.loads((ROOT / f"data/{date}/raw.json").read_text(encoding="utf-8"))
articles = raw.get("articles", [])
print(f"📥 总文章: {len(articles)}")

# ── Step 1: Normalize ──
norm = Normalizer(url_strip_params=filter_cfg.get("url_strip_params", []))
for a in articles:
    norm.normalize(a)

# ── Step 2: Dedup ──
scorer = HeatScorer(filter_cfg)
dedup = DedupEngine(
    window_hours=72,
    similarity_threshold=0.85,
    source_weight_fn=scorer.get_source_weight,
)
unique = dedup.process(articles)
print(f"🔄 去重后: {len(unique)}")

# ── Step 3: Relevance ──
rel = RelevanceFilter(filter_cfg)
keyword_passed = []
keyword_rejected = []
relevance_stats = defaultdict(int)
priority_stats = defaultdict(int)

for a in unique:
    is_rel, tags, priority = rel.check(a)
    a["_relevance_tags"] = tags
    a["_relevance_priority"] = priority
    a["relevance_tags"] = [t for t in tags if not t.startswith("_")]
    a["relevance_priority"] = priority
    if is_rel:
        keyword_passed.append(a)
        for tag in tags:
            relevance_stats[tag] += 1
        priority_stats[priority] += 1
    elif not a.get("is_duplicate", False):
        keyword_rejected.append(a)

print(f"🎯 关键词通过: {len(keyword_passed)}, 拒绝: {len(keyword_rejected)}")

# ══════════════════════════════════════════
# Step 3b: 去噪 — CodeBuddy 主模型判断结果
# ══════════════════════════════════════════

needs_review = [
    a for a in keyword_passed
    if a.get("_match_type") == "brand_only"
    and a.get("_match_count", 0) == 1
    and not a.get("_match_in_title", True)
    and a.get("channel", "") in ("rss", "wechat", "exa")
]

# 主模型判定为不相关的标题模式
denoise_remove_patterns = [
    "quoting bryan cantrill",
    "viktor orban",
    "黑客松",
]

to_remove_ids = set()
for a in needs_review:
    title_lower = a.get("title", "").lower()
    for pattern in denoise_remove_patterns:
        if pattern in title_lower:
            to_remove_ids.add(id(a))
            a["_llm_denoise_reason"] = f"CodeBuddy主模型判定不相关"
            a["_llm_denoised"] = True
            a["_relevance_tags"] = []
            a["_relevance_priority"] = "none"
            a["relevance_tags"] = []
            a["relevance_priority"] = "none"
            print(f"  ✂️ 去噪踢掉: {a['title'][:50]}")
            break

keyword_passed = [a for a in keyword_passed if id(a) not in to_remove_ids]
print(f"✅ 去噪完成: 踢掉 {len(to_remove_ids)} 篇假阳性")

# ══════════════════════════════════════════
# Step 3c: 捞漏 — CodeBuddy 主模型判断结果
# ══════════════════════════════════════════

valid_tags = set(filter_cfg.get("relevance_tags", {}).keys())

rescue_decisions = [
    {"pattern": "mark zuckerberg", "extra": "ai clone", "tags": ["ai_agent"],
     "reason": "Zuckerberg用AI替身处理会议，AI Agent应用"},
    {"pattern": "微软", "extra": "游戏交互", "tags": ["ai_gaming"],
     "reason": "微软AI重塑游戏交互"},
    {"pattern": "minimax m2.7", "tags": ["ai_core"],
     "reason": "MiniMax M2.7重要AI模型开源"},
    {"pattern": "清华2年前预言", "tags": ["ai_core"],
     "reason": "AI研究趋势，Meta等机构印证"},
    {"pattern": "谷歌实锤ai越乖", "tags": ["ai_core"],
     "reason": "AI安全/对齐重要发现"},
    {"pattern": "米哈游刘伟", "extra": "ai时代焦虑", "tags": ["ai_gaming"],
     "reason": "游戏行业领袖谈AI影响"},
    {"pattern": "阿里搞了款ai原生", "tags": ["ai_gaming"],
     "reason": "AI原生游戏"},
]

trigger_lower = [n.lower() for n in LLMLightFilter.LOOSE_TRIGGER_NAMES]
maybe_relevant = [
    a for a in keyword_rejected
    if a.get("channel", "") in ("rss", "wechat", "exa")
    and any(t in a.get("title", "").lower() for t in trigger_lower)
]

rescued = []
for a in maybe_relevant:
    title_lower = a.get("title", "").lower()
    for decision in rescue_decisions:
        if decision["pattern"] in title_lower:
            extra = decision.get("extra", "")
            if extra and extra not in title_lower:
                continue
            valid_suggested = [t for t in decision["tags"] if t in valid_tags]
            if valid_suggested:
                a["_relevance_tags"] = valid_suggested
                a["_relevance_priority"] = "supplementary"
                a["relevance_tags"] = valid_suggested
                a["relevance_priority"] = "supplementary"
                a["_llm_rescued"] = True
                a["_llm_rescue_reason"] = decision["reason"]
                rescued.append(a)
                for tag in valid_suggested:
                    relevance_stats[tag] += 1
                priority_stats["supplementary"] = priority_stats.get("supplementary", 0) + 1
                print(f"  🎣 捞回: {a['title'][:50]} → {valid_suggested}")
                break

print(f"✅ 捞漏完成: 捞回 {len(rescued)} 篇")
after_relevance = sum(1 for a in unique if a["_relevance_priority"] != "none")
print(f"📊 相关性总计: {after_relevance} 篇")

# ── Step 4: Score ──
for a in unique:
    if a["_relevance_priority"] == "none":
        a["score"] = 0
        a["score_details"] = {}
        continue
    score, details = scorer.score(a, now)
    a["score"] = score
    a["score_details"] = {k: round(v, 1) for k, v in details.items()}

# ── Step 5: Filter ──
twitter_cfg = filter_cfg.get("twitter_quality", {})
_, quota_stats = apply_filter(
    unique,
    pipeline_quotas=filter_cfg.get("pipeline_quotas"),
    quota_per_tag=filter_cfg.get("quota_per_tag"),
    default_quota=filter_cfg.get("default_quota", 5),
    min_articles_warning=filter_cfg.get("min_articles_warning", 3),
    twitter_min_heat=twitter_cfg.get("min_heat", 30.0),
)

passed = [a for a in unique if not a.get("filtered_out", True)]
print(f"✅ 配额筛选完成: {after_relevance} → {len(passed)} 篇入选")

# ── 统计 ──
score_ranges = {"7-8": 0, "5-6": 0, "3-4": 0, "1-2": 0}
for a in passed:
    s = a.get("score", 0)
    if s >= 7: score_ranges["7-8"] += 1
    elif s >= 5: score_ranges["5-6"] += 1
    elif s >= 3: score_ranges["3-4"] += 1
    else: score_ranges["1-2"] += 1

channel_stats = defaultdict(int)
for a in passed:
    channel_stats[a.get("channel", "unknown")] += 1

tag_passed_stats = defaultdict(int)
for a in passed:
    for tag in a.get("relevance_tags", []):
        tag_passed_stats[tag] += 1

stats = {
    "input": len(articles),
    "after_dedup": len(unique),
    "after_relevance": after_relevance,
    "after_filter": len(passed),
    "by_relevance_tag": dict(relevance_stats),
    "by_tag_passed": dict(tag_passed_stats),
    "by_priority": dict(priority_stats),
    "by_score_range": score_ranges,
    "by_channel": dict(channel_stats),
    "quota_stats": quota_stats,
    "llm_light_filter": {
        "method": "CodeBuddy主模型手动执行",
        "denoised_count": len(to_remove_ids),
        "rescued_count": len(rescued),
    },
}

# ── 清理内部字段 ──
output_articles = []
for art in unique:
    out = {k: v for k, v in art.items() if not k.startswith("_")}
    out.pop("content", None)
    out.pop("summary", None)
    output_articles.append(out)

output_articles.sort(
    key=lambda a: (not a.get("filtered_out", True), a.get("score", 0)),
    reverse=True,
)

# ── 写入 filtered.json ──
output = {
    "date": date,
    "filtered_at": now.isoformat(),
    "config_snapshot": {
        "scoring_dimensions": "四维度（时效+覆盖+互动+多标签）满分8",
        "pipeline_quotas": filter_cfg.get("pipeline_quotas", {}),
        "quota_per_tag": filter_cfg.get("quota_per_tag", {}),
        "default_quota": filter_cfg.get("default_quota", 5),
        "dedup_window_hours": filter_cfg.get("dedup_window_hours", 72),
        "llm_light_filter": "由CodeBuddy主模型手动执行（去噪+捞漏）",
    },
    "stats": stats,
    "articles": output_articles,
}

out_path = ROOT / f"data/{date}/filtered.json"
out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n💾 已保存: {out_path}")

# ── 打印变化对比 ──
print(f"\n{'='*50}")
print(f"📊 LLM 轻筛结果:")
print(f"  去噪踢掉: {len(to_remove_ids)} 篇假阳性")
print(f"  捞漏捞回: {len(rescued)} 篇")
print(f"  最终入选: {len(passed)} 篇")
print(f"  渠道分布: {dict(channel_stats)}")
print(f"  标签分布: {dict(tag_passed_stats)}")

if rescued:
    print(f"\n🎣 捞回的 {len(rescued)} 篇文章:")
    for i, a in enumerate(rescued, 1):
        in_final = not a.get("filtered_out", True)
        status = "✅入选" if in_final else "❌配额满"
        print(f"  {i}. [{a['channel']}] {a['title'][:55]} {status}")
        print(f"     → {a.get('relevance_tags', [])} | 分数: {a.get('score', 0)}")
