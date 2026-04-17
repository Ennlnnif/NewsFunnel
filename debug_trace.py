#!/usr/bin/env python3
"""
AI Daily Debug Trace — 生成 Layer1/2/3 全流程中间产物
用法: cd ai-daily && .venv/bin/python debug_trace.py [--date 2026-04-14]
输出: data/{date}/debug/*.md
"""
import json, sys, yaml
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

DATE = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else datetime.now().strftime("%Y-%m-%d")
BASE = Path(__file__).parent / "data" / DATE
DEBUG = BASE / "debug"
DEBUG.mkdir(exist_ok=True)
CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text("utf-8"))

def load_json(name):
    p = BASE / name
    return json.loads(p.read_text("utf-8")) if p.exists() else None

raw = load_json("raw.json")
filt = load_json("filtered.json")
llm_input = load_json("llm_filter_input.json")
llm_results = load_json("llm_filter_results.json")
if not raw or not filt:
    print(f"❌ 缺少 raw.json 或 filtered.json: {BASE}"); sys.exit(1)

hist_arts = []
for d in [1, 2]:
    prev = BASE.parent / (datetime.strptime(DATE, "%Y-%m-%d") - timedelta(days=d)).strftime("%Y-%m-%d") / "filtered.json"
    if prev.exists(): hist_arts.extend(json.loads(prev.read_text("utf-8")).get("articles", []))

raw_arts = raw["articles"]
filt_arts = filt["articles"]
stats = filt.get("stats", {})

def write_md(fn, lines):
    (DEBUG / fn).write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅ {fn}")

def pub_str(a):
    p = a.get("published_at", "")
    return p[:16].replace("T", " ") if p else "无日期"

def ch_icon(ch):
    return {"rss":"📰","wechat":"💬","github":"🐙","twitter":"🐦","exa":"🔍","manual":"✏️"}.get(ch,"?")

# ══ 01: Layer1 采集总览 ══
def gen_01():
    L = [f"# Layer1 采集总览", f"**日期**: {DATE} | **采集时间**: {raw.get('collected_at','')[:19]} | **总计**: {len(raw_arts)} 篇", ""]
    by_ch = raw["stats"]["by_channel"]
    L += ["| 渠道 | 篇数 |", "|------|------|"]
    for ch in ["rss","wechat","github","twitter","exa","manual"]:
        L.append(f"| {ch_icon(ch)} {ch} | {by_ch.get(ch,0)} |")
    L.append(f"| **总计** | **{len(raw_arts)}** |")
    write_md("01_layer1_采集总览.md", L)

# ══ 02-05: 各渠道 latest ══
def gen_channel(channel, fn, title):
    arts = [a for a in raw_arts if a["channel"] == channel]
    L = [f"# {title}", f"**总计**: {len(arts)} 篇", ""]
    if channel == "wechat":
        by_mp = defaultdict(list)
        for a in arts: by_mp[a["extra"]["mp_name"]].append(a)
        L += ["| # | 公众号 | 篇数 |", "|---|--------|------|"]
        for i,(mp,ma) in enumerate(sorted(by_mp.items(), key=lambda x:-len(x[1])),1):
            L.append(f"| {i} | {mp} | {len(ma)} |")
        L.append("")
        for mp in sorted(by_mp, key=lambda x:-len(by_mp[x])):
            ma = sorted(by_mp[mp], key=lambda x:x.get("published_at",""), reverse=True)
            L += [f"### {mp}（{len(ma)}篇）", "", "| 发布时间 | 标题 |", "|---------|------|"]
            for a in ma: L.append(f"| {pub_str(a)} | {a['title']} |")
            L.append("")
    elif channel == "twitter":
        arts_s = sorted(arts, key=lambda x:-(x.get("extra",{}).get("likes",0) or 0))
        L += ["| # | 时间 | 来源 | 内容 | ❤️ | 👁️ |", "|---|------|------|------|-----|-----|"]
        for i,a in enumerate(arts_s,1):
            ex = a.get("extra",{})
            L.append(f"| {i} | {pub_str(a)} | {a['source_name'][:18]} | {a['title'][:35]} | {ex.get('likes',0)} | {ex.get('views',0)} |")
    elif channel == "github":
        arts_s = sorted(arts, key=lambda x:-(x.get("extra",{}).get("stars",0) or 0))
        L += ["| # | 来源 | 标题 | ⭐ |", "|---|------|------|-----|"]
        for i,a in enumerate(arts_s,1):
            L.append(f"| {i} | {a['source_name'][:18]} | {a['title'][:42]} | {a.get('extra',{}).get('stars','?')} |")
    else:  # rss, exa
        by_src = defaultdict(list)
        for a in arts: by_src[a["source_name"]].append(a)
        L += ["| # | 来源 | 篇数 |", "|---|------|------|"]
        for i,(src,sa) in enumerate(sorted(by_src.items(), key=lambda x:-len(x[1])),1):
            L.append(f"| {i} | {src} | {len(sa)} |")
        L.append("")
        for src in sorted(by_src, key=lambda x:-len(by_src[x])):
            sa = sorted(by_src[src], key=lambda x:x.get("published_at",""), reverse=True)
            L += [f"### {src}（{len(sa)}篇）", ""]
            for a in sa: L.append(f"- `{pub_str(a)}` {a['title'][:55]}")
            L.append("")
    write_md(fn, L)

# ══ 06: 去重 ══
def gen_06():
    L = [f"# Layer2 去重过程", f"**输入**: {len(raw_arts)} → **输出**: {stats.get('after_dedup','?')}", ""]
    # 模拟去重
    hist_urls = set()
    hist_wc_titles = set()
    for a in hist_arts:
        u = (a.get("_normalized_url") or a.get("url","")).rstrip("/")
        if u: hist_urls.add(u)
        if a.get("channel") == "wechat": hist_wc_titles.add(a.get("title",""))

    # 2a URL历史
    url_killed, url_survived = [], []
    seen_url = set(hist_urls)
    for a in raw_arts:
        u = a["url"].rstrip("/")
        if u in seen_url: url_killed.append((a, "URL在历史中"))
        else: seen_url.add(u); url_survived.append(a)

    L += [f"## Step 2a: URL 历史去重", f"{len(raw_arts)} → **{len(url_survived)}**（淘汰 {len(url_killed)}）", ""]
    by_ch = Counter(a["channel"] for a,_ in url_killed)
    L.append(f"淘汰渠道分布: {' | '.join(f'{ch_icon(c)} {c}:{n}' for c,n in by_ch.most_common())}")
    L += ["", "<details><summary>展开淘汰明细</summary>", "", "| 渠道 | 来源 | 标题 | 原因 |", "|------|------|------|------|"]
    for a,reason in url_killed:
        L.append(f"| {ch_icon(a['channel'])} {a['channel']} | {a['source_name'][:14]} | {a['title'][:32]} | {reason} |")
    L += ["", "</details>"]

    # 2b 微信标题历史
    wc_title_killed, after_wc_title = [], []
    seen_wc = set(hist_wc_titles)
    for a in url_survived:
        if a["channel"] == "wechat":
            t = a["title"]
            if t in seen_wc: wc_title_killed.append((a, "标题在历史中")); continue
            seen_wc.add(t)
        after_wc_title.append(a)

    L += ["", f"## Step 2b: 微信标题历史去重", f"{len(url_survived)} → **{len(after_wc_title)}**（淘汰 {len(wc_title_killed)}）"]
    if wc_title_killed:
        L += ["", "| 来源 | 标题 | 原因 |", "|------|------|------|"]
        for a,reason in wc_title_killed:
            L.append(f"| {a['source_name'][:14]} | {a['title'][:35]} | {reason} |")

    # 2c 标题模糊去重
    threshold = 0.85
    groups = []
    used = [False] * len(after_wc_title)
    for i in range(len(after_wc_title)):
        if used[i]: continue
        grp = [after_wc_title[i]]
        used[i] = True
        for j in range(i+1, len(after_wc_title)):
            if used[j]: continue
            if SequenceMatcher(None, after_wc_title[i]["title"], after_wc_title[j]["title"]).ratio() >= threshold:
                grp.append(after_wc_title[j]); used[j] = True
        groups.append(grp)

    merged_groups = [g for g in groups if len(g) > 1]
    title_killed = sum(len(g)-1 for g in merged_groups)
    L += ["", f"## Step 2c: 标题模糊去重（阈值 {threshold}）"]
    L.append(f"{len(after_wc_title)} → **{len(groups)}**（合并 {len(merged_groups)} 组，淘汰 {title_killed} 篇）")
    if merged_groups:
        L += ["", "合并的组：", ""]
        for g in merged_groups:
            rep = max(g, key=lambda a: len(a.get("summary","") or ""))
            L.append(f"- **代表**: [{ch_icon(rep['channel'])}] {rep['source_name'][:14]} | {rep['title'][:35]}")
            for a in g:
                if a is not rep:
                    L.append(f"  - 淘汰: [{ch_icon(a['channel'])}] {a['source_name'][:14]} | {a['title'][:35]}")

    # 最终去重结果
    final_count = stats.get("after_dedup", len(groups))
    L += ["", f"## 去重总结", "", "```"]
    L.append(f"原始输入:        {len(raw_arts)} 篇")
    L.append(f"URL历史去重:     -{len(url_killed)} → {len(url_survived)}")
    L.append(f"微信标题去重:    -{len(wc_title_killed)} → {len(after_wc_title)}")
    L.append(f"标题模糊去重:    -{title_killed} → {len(groups)}")
    L.append(f"最终去重后:      {final_count} 篇")
    L.append("```")

    # 去重后各渠道分布
    dedup_result = [max(g, key=lambda a: len(a.get("summary","") or "")) for g in groups]
    ch_after = Counter(a["channel"] for a in dedup_result)
    L += ["", f"去重后渠道分布: {' | '.join(f'{ch_icon(c)} {c}:{n}' for c,n in ch_after.most_common())}"]
    write_md("06_layer2_去重.md", L)

# ══ 07-09: 三管道筛选 ══
def gen_pipeline(pipe_name, fn, title, channels):
    L = [f"# {title}", ""]
    pipe_arts = [a for a in filt_arts if a["channel"] in channels]
    L.append(f"**去重后进入本管道**: {len(pipe_arts)} 篇")
    L.append("")

    # Step 3: Relevance
    relevant = [a for a in pipe_arts if a.get("relevance_priority","none") != "none"]
    not_relevant = [a for a in pipe_arts if a.get("relevance_priority","none") == "none"]
    L += [f"## Step 3: 相关性筛选", f"{len(pipe_arts)} → **{len(relevant)}** 篇通过", ""]

    # 通过方式统计
    pass_types = Counter()
    for a in relevant:
        tags = a.get("relevance_tags", [])
        if "_channel_pass" in tags: pass_types["渠道通行证"] += 1
        elif tags: pass_types["signals关键词"] += 1
        else: pass_types["其他"] += 1
    L.append(f"通过方式: {' | '.join(f'{k}:{v}' for k,v in pass_types.most_common())}")

    if relevant:
        L += ["", "### 通过的文章", "", "| # | 渠道 | 来源 | 标题 | 通过方式 | 标签 |", "|---|------|------|------|---------|------|"]
        for i,a in enumerate(relevant,1):
            tags = a.get("relevance_tags",[])
            way = "通行证" if "_channel_pass" in tags else "signals"
            tag_str = ",".join(t for t in tags if not t.startswith("_"))
            L.append(f"| {i} | {ch_icon(a['channel'])} | {a['source_name'][:14]} | {a['title'][:30]} | {way} | {tag_str} |")

    if not_relevant:
        L += ["", f"<details><summary>未通过的 {len(not_relevant)} 篇</summary>", "",
               "| 渠道 | 来源 | 标题 |", "|------|------|------|"]
        for a in not_relevant:
            L.append(f"| {ch_icon(a['channel'])} | {a['source_name'][:14]} | {a['title'][:40]} |")
        L += ["", "</details>"]

    # Step 3b: LLM classify
    if llm_results:
        classify_map = {r["id"]: r for r in llm_results.get("classify", [])}
        cands = llm_input.get("classify_candidates", []) if llm_input else []
        pipe_cands = [c for c in cands if c.get("channel","") in channels]

        passed_llm, rejected_llm = [], []
        for c in pipe_cands:
            r = classify_map.get(c["id"], {})
            (passed_llm if r.get("relevant", True) else rejected_llm).append((c, r))

        L += ["", f"## Step 3b: LLM 分类", f"{len(pipe_cands)} 篇候选 → **{len(passed_llm)} 通过**，{len(rejected_llm)} 踢掉", ""]

        if rejected_llm:
            L += ["### ❌ 被踢掉", "", "| 渠道 | 来源 | 标题 | 原因 |", "|------|------|------|------|"]
            for c,r in rejected_llm:
                L.append(f"| {ch_icon(c.get('channel',''))} | {c['source_name'][:14]} | {c['title'][:30]} | {r.get('reason','')} |")

        if passed_llm:
            L += ["", "### ✅ 通过", "", "| # | 渠道 | 来源 | 标题 | primary_tag |", "|---|------|------|------|-------------|"]
            for i,(c,r) in enumerate(passed_llm,1):
                L.append(f"| {i} | {ch_icon(c.get('channel',''))} | {c['source_name'][:14]} | {c['title'][:28]} | `{r.get('primary_tag','?')}` |")

        # rescue
        rescue_results = llm_results.get("rescue", [])
        rescue_in_pipe = []
        rescue_cands = llm_input.get("rescue_candidates", []) if llm_input else []
        rescue_map = {c["id"]: c for c in rescue_cands}
        for r in rescue_results:
            c = rescue_map.get(r["id"])
            if c and c.get("channel","") in channels and r.get("relevant"):
                rescue_in_pipe.append((c, r))
        if rescue_in_pipe:
            L += ["", f"### 🎣 LLM 捞回 {len(rescue_in_pipe)} 篇", "",
                   "| 渠道 | 来源 | 标题 | primary_tag | 原因 |", "|------|------|------|-------------|------|"]
            for c,r in rescue_in_pipe:
                L.append(f"| {ch_icon(c.get('channel',''))} | {c['source_name'][:14]} | {c['title'][:28]} | `{r.get('primary_tag','?')}` | {r.get('reason','')} |")

    # Step 4+5: 评分+配额
    scored = sorted([a for a in pipe_arts if a.get("score",0) > 0], key=lambda a:-a["score"])
    selected = [a for a in pipe_arts if a.get("filtered_out") == False]

    L += ["", f"## Step 4-5: 评分 → 配额竞争", f"**有评分**: {len(scored)} 篇 | **最终入选**: {len(selected)} 篇", ""]

    # 配额表
    qs = stats.get("quota_stats", {}).get(pipe_name, {})
    # opinion 独立池的配额统计在 quota_stats["opinion"] 中，合并显示
    opinion_qs = stats.get("quota_stats", {}).get("opinion", {})
    if opinion_qs and pipe_name == "main":
        qs = {**qs, **opinion_qs}
    if qs:
        L += ["### 配额", "", "| 板块 | 配额 | 供给 | 入选 |", "|------|------|------|------|"]
        for tag, ts in sorted(qs.items()):
            low = " ⚠️" if ts.get("low_supply") else ""
            L.append(f"| {tag} | {ts.get('quota',0)} | {ts.get('supply',0)} | {ts.get('filled',0)}{low} |")

    if selected:
        L += ["", "### 🎉 入选文章", "", "| # | score | 渠道 | 来源 | 标题 |",
               "|---|-------|------|------|------|"]
        for i,a in enumerate(sorted(selected, key=lambda x:-x.get("score",0)),1):
            L.append(f"| {i} | **{a['score']:.1f}** | {ch_icon(a['channel'])} | {a['source_name'][:14]} | {a['title'][:38]} |")

    # 未入选但有分的
    not_sel = [a for a in scored if a.get("filtered_out") != False]
    if not_sel:
        L += ["", f"<details><summary>有评分但未入选的 {len(not_sel)} 篇</summary>", "",
               "| score | 渠道 | 来源 | 标题 | 原因 |", "|-------|------|------|------|------|"]
        for a in not_sel:
            L.append(f"| {a['score']:.1f} | {ch_icon(a['channel'])} | {a['source_name'][:14]} | {a['title'][:30]} | {a.get('filter_reason','?')} |")
        L += ["", "</details>"]

    write_md(fn, L)

# ══ 10: Layer3 ══
def gen_10():
    daily_path = BASE / "daily.md"
    L = [f"# Layer3 编辑结果", ""]
    if daily_path.exists():
        content = daily_path.read_text("utf-8")
        line_count = len(content.splitlines())
        L += [f"**daily.md**: {line_count} 行", "", "```markdown"]
        L += content.splitlines()[:100]
        if line_count > 100: L.append(f"... (截断，共 {line_count} 行)")
        L.append("```")
    else:
        L.append("*daily.md 尚未生成*")
    write_md("10_layer3_编辑结果.md", L)

# ══ 11: 全流程漏斗 ══
def gen_11():
    L = [f"# 全流程漏斗", f"**日期**: {DATE}", ""]

    # 各渠道漏斗
    selected = [a for a in filt_arts if a.get("filtered_out") == False]
    sel_ch = Counter(a["channel"] for a in selected)
    raw_ch = Counter(a["channel"] for a in raw_arts)
    dedup_ch = Counter(a["channel"] for a in filt_arts)

    L += ["## 各渠道漏斗", "", "| 渠道 | 采集 | 去重后 | 入选 |", "|------|------|--------|------|"]
    for ch in ["rss","wechat","github","twitter","exa","manual"]:
        L.append(f"| {ch_icon(ch)} {ch} | {raw_ch.get(ch,0)} | {dedup_ch.get(ch,0)} | {sel_ch.get(ch,0)} |")
    L.append(f"| **总计** | **{len(raw_arts)}** | **{len(filt_arts)}** | **{len(selected)}** |")

    # 管道漏斗
    L += ["", "## 管道漏斗", "", "```"]
    L.append(f"Layer1 采集         {len(raw_arts)} 篇")
    L.append(f"  ↓ 去重            {stats.get('after_dedup','?')} 篇")
    L.append(f"  ↓ 相关性筛选      {stats.get('after_relevance','?')} 篇")
    L.append(f"  ↓ LLM分类+捞漏    (见各管道)")
    L.append(f"  ↓ 评分+配额       {stats.get('after_filter','?')} 篇")
    L.append(f"Layer2 输出         {len(selected)} 篇入选")
    L.append("```")

    # 入选文章总表
    L += ["", "## 最终入选文章", "", "| # | score | 渠道 | 来源 | 标题 |", "|---|-------|------|------|------|"]
    for i,a in enumerate(sorted(selected, key=lambda x:-x.get("score",0)),1):
        L.append(f"| {i} | **{a['score']:.1f}** | {ch_icon(a['channel'])} {a['channel']} | {a['source_name'][:14]} | {a['title'][:40]} |")

    write_md("11_全流程漏斗.md", L)

# ══ 执行 ══
print(f"\n📊 生成 debug trace: {DEBUG}\n")
gen_01()
gen_channel("wechat", "02_layer1_微信_latest.md", "Layer1 微信公众号采集")
gen_channel("rss", "03_layer1_rss_latest.md", "Layer1 RSS 采集")
gen_channel("github", "04_layer1_github_latest.md", "Layer1 GitHub 采集")
gen_channel("twitter", "05_layer1_twitter_latest.md", "Layer1 Twitter 采集")
exa_arts = [a for a in raw_arts if a["channel"] == "exa"]
if exa_arts:
    gen_channel("exa", "03b_layer1_exa_latest.md", "Layer1 Exa 搜索采集")
gen_06()
gen_pipeline("main", "07_layer2_筛选_主日报.md", "Layer2 筛选 — 主日报管道", {"rss","wechat","exa","manual"})
gen_pipeline("twitter", "08_layer2_筛选_twitter.md", "Layer2 筛选 — Twitter 管道", {"twitter"})
gen_pipeline("github", "09_layer2_筛选_github.md", "Layer2 筛选 — GitHub 管道", {"github"})
gen_10()
gen_11()
print(f"\n✅ 全部生成完毕: {DEBUG}")
