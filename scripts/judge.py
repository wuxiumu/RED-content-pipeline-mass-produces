#!/usr/bin/env python3
"""
02 判断智能体 Judge
- wordcard 轨:词族表展平 → 规则打分排产(冷启动无样本也能跑),跳过已在 scripted.json 的词
- video / resource 轨:样本驱动,top 关键词 LLM 提炼范式 + 生成选题(无样本则跳过)
输出 data/judged.json。

用法:
  python3 judge.py                # 按配置 daily_limit 排产
  python3 judge.py --limit 20     # 一次排 20 个词(批量囤货)
"""
import argparse
import math
import sys
import time
from collections import defaultdict

from common_llm import (DATA, call_llm, flatten_words, load_config,
                        load_json, load_providers, now_iso, parse_json,
                        save_json)

COLLECTED_PATH = DATA / "collected.json"
SCRIPTED_PATH = DATA / "scripted.json"
JUDGED_PATH = DATA / "judged.json"
FEEDBACK_PATH = DATA / "feedback.json"

# 抽象/特殊词族视觉可画性微调
DRAWBILITY = {"colors": 80, "numbers": 75, "body": 80, "weather": 85}
DEFAULT_DRAWBILITY = 95


def score_word(word, samples_by_kw, feedback_kws, done_ids):
    """词族候选打分 0-100。"""
    if word["word_id"] in done_ids:
        return -1, {}

    # 1. 词族常见度/认知顺序:priority 越靠前越高,族内位置轻微衰减
    fam = max(0, 100 - word["family_index"] * 6)
    order = max(0.0, 1.0 - word["word_index"] * 0.04)
    common = fam * 0.6 + 100 * order * 0.4

    # 2. 收藏/热度信号:样本标题命中该词(中/英)时用最大点赞代理
    hot = 0
    hits = samples_by_kw.get(word["zh"], []) + samples_by_kw.get(word["en"], [])
    if hits:
        max_like = max(s.get("likes", 0) for s in hits)
        hot = min(100, math.log10(max_like + 1) * 20)

    # 3. 历史反馈
    feedback = 50
    if word["en"] in feedback_kws or word["zh"] in feedback_kws:
        feedback = 85

    # 4. 竞争留白:命中样本越少越好
    compete = max(40, 100 - len(hits) * 12)

    # 5. 视觉可画性
    draw = DRAWBILITY.get(word["family_id"], DEFAULT_DRAWBILITY)

    score = (common * 0.25 + hot * 0.30 + feedback * 0.20 +
             compete * 0.15 + draw * 0.10)
    return round(score), {"common": round(common), "hot": round(hot),
                          "feedback": feedback, "compete": compete,
                          "draw": draw, "sample_hits": len(hits)}


def extract_pattern(providers, provider, model, keyword, samples, track):
    top = sorted(samples, key=lambda x: x.get("likes", 0), reverse=True)[:5]
    lines = "\n".join(f"- {s.get('title','')} | 赞:{s.get('likes',0)}" for s in top)
    angle_hint = {
        "video": "前3秒钩子、封面大字、标签簇;内容是15-20秒磨耳朵视频",
        "resource": "资源钩子类型(可打印/可投屏/原创/清单)、封面与合规导流话术;严禁盗版与IP名",
    }.get(track, "")
    prompt = f"""你是小红书母婴爆款分析师。关键词「{keyword}」高赞样本:
{lines}
提炼{angle_hint}。严格只输出 JSON:
{{"title_structures": ["...","...","..."],
  "tag_clusters": ["...","...","..."],
  "cover_style": "...",
  "hook_first_3s": "..."}}"""
    try:
        return parse_json(call_llm(providers, provider, model, prompt, max_tokens=1200))
    except Exception as e:
        print(f"    [WARN] 范式提炼失败 {keyword}: {e}")
        return {"title_structures": [], "tag_clusters": [],
                "cover_style": "", "hook_first_3s": ""}


def generate_topics(providers, provider, model, keyword, pattern, track, n):
    cta_rule = ('导流话术只能引导"评论区扣1/主页粉丝群/小红书店铺",'
                '禁止微信、外链、网盘、盗版动画集数与知名IP名称。')
    prompt = f"""你是小红书母婴启蒙选题策划师。为「{keyword}」生成 {n} 个{track}轨差异化选题。
爆款范式:{pattern}
要求:标题≤20字,带年龄锚点(2岁/3岁)或结果词(开口/跟读/省妈);{cta_rule}
严格只输出 JSON 数组:
[{{"title_hint":"标题","angle":"一句话角度","tags_hint":["标签"],"target_audience":"目标宝妈",
   "reuse_word_id":"video轨可复用的词族单词(如apple),其他轨留空",
   "cross_sell_hint":"合规导流话术"}}]"""
    try:
        arr = parse_json(call_llm(providers, provider, model, prompt, max_tokens=3000))
        return arr if isinstance(arr, list) else [arr]
    except Exception as e:
        print(f"    [WARN] 选题生成失败 {keyword}: {e}")
        return []


def score_topic(t, track):
    s = 50
    title = t.get("title_hint", "")
    if any(c.isdigit() for c in title):
        s += 15
    if any(w in title for w in ["岁", "开口", "跟读", "省妈", "亲测", "零基础", "每天"]):
        s += 10
    if 12 <= len(title) <= 20:
        s += 5
    if 4 <= len(t.get("tags_hint", [])) <= 6:
        s += 5
    if track == "resource" and t.get("cross_sell_hint"):
        s += 15
    if track == "video" and t.get("reuse_word_id"):
        s += 10
    return round(min(100, s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="wordcard 当日排产词数")
    args = ap.parse_args()

    cfg = load_config()
    limit = args.limit or cfg["production"]["daily_limit"]
    collected = load_json(COLLECTED_PATH, {"tracks": {}})
    scripted = load_json(SCRIPTED_PATH, {"words": []})
    done_ids = {w["word_id"] for w in scripted.get("words", [])
                if w.get("status") in ("scripted", "images_done", "cards_done", "ready")}

    feedback_kws = set()
    fb = load_json(FEEDBACK_PATH, {})
    for r in fb.get("records", []):
        for k in (r.get("word_en"), r.get("word_zh"), r.get("keyword")):
            if k:
                feedback_kws.add(k)

    result = {"judged_at": now_iso(), "niche": cfg["niche"], "tracks": {}}

    # ---- wordcard:词族排产 ----
    samples_by_kw = defaultdict(list)
    for s in collected.get("tracks", {}).get("wordcard", {}).get("samples", []):
        samples_by_kw[s.get("keyword", "")].append(s)

    queue = []
    for w in flatten_words():
        score, detail = score_word(w, samples_by_kw, feedback_kws, done_ids)
        if score < 0:
            continue
        queue.append((score, w, detail))
    queue.sort(key=lambda x: x[0], reverse=True)
    queue = queue[:limit]

    wc = []
    for i, (score, w, detail) in enumerate(queue):
        wc.append({
            "id": w["word_id"], "track": "wordcard",
            "family": w["family_id"], "family_zh": w["family_zh"],
            "word_en": w["en"], "word_zh": w["zh"], "slot": w["slot"],
            "host": w.get("host", ""), "draw_note": w.get("draw_note", ""),
            "score": score, "priority": i + 1,
            "angle": "命名→特征→颜色→喜好,4句认知公式",
            "title_formula": "年龄锚点+结果承诺+每天5分钟+悬念",
            "score_detail": detail,
        })
    result["tracks"]["wordcard"] = {"queue": wc}
    print(f"[wordcard] 排产 {len(wc)} 词:" +
          ", ".join(f"{x['word_zh']}({x['score']})" for x in wc))

    # ---- video / resource:样本驱动 ----
    providers = load_providers()
    provider = cfg["llm"]["provider"]
    model = cfg["llm"]["model_flash"]

    for track in ("video", "resource"):
        track_data = collected.get("tracks", {}).get(track, {})
        kw_samples = defaultdict(list)
        for s in track_data.get("samples", []):
            kw_samples[s.get("keyword", "")].append(s)

        keyword_cards, all_topics = [], []
        if kw_samples:
            ranked = sorted(
                ((kw, ss) for kw, ss in kw_samples.items() if kw),
                key=lambda x: max(s.get("likes", 0) for s in x[1]), reverse=True)[:5]
            for kw, ss in ranked:
                hot = min(100, math.log10(max(s.get("likes", 0) for s in ss) + 1) * 20)
                print(f"[{track}] 范式+选题: {kw}")
                pattern = extract_pattern(providers, provider, model, kw, ss, track)
                keyword_cards.append({"keyword": kw, "score": round(hot), "pattern": pattern})
                topics = generate_topics(providers, provider, model, kw, pattern, track, 4)
                for t in topics:
                    t["keyword"] = kw
                    t["track"] = track
                    t["score"] = score_topic(t, track)
                    all_topics.append(t)
                time.sleep(0.4)
            all_topics.sort(key=lambda x: x.get("score", 0), reverse=True)
            for i, t in enumerate(all_topics[:8]):
                t["id"] = f"{track[:3]}_{i+1:03d}"
                t["priority"] = i + 1
        else:
            print(f"[{track}] 无样本,跳过(先跑 scrape_xhs.py)")
        result["tracks"][track] = {"keyword_cards": keyword_cards, "topics": all_topics[:8]}

    save_json(JUDGED_PATH, result)
    print(f"\n[DONE] -> {JUDGED_PATH}")


if __name__ == "__main__":
    sys.exit(main())
