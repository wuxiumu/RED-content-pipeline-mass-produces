#!/usr/bin/env python3
"""
03-d · 组装发布物料 → data/produced.json
对每个已排卡(cards_done)的词:LLM 生成 5 个封面标题候选并自评、正文、标签;
合规词强制拦截(命中重生成 1 次);用选定标题重渲染封面 P1。

用法:
  python3 execute.py
  python3 execute.py --word apple
"""
import argparse
import subprocess
import sys
from pathlib import Path

from common_llm import (DATA, IMAGES, call_llm, check_compliance,
                        load_config, load_json, load_providers, now_iso,
                        parse_json, save_json)

SCRIPTED_PATH = DATA / "scripted.json"
PRODUCED_PATH = DATA / "produced.json"
SCRIPTS_DIR = Path(__file__).resolve().parent


def build_prompt(word, pool, banned):
    if word.get("uncountable"):
        lines_desc = f'This is {word["en"]} → 特征 → 颜色 → "I like {word["en"]}" 四句跟读卡(不可数名词,不加 a/an)'
    else:
        en = word["en"]
        article = "an" if en[0].lower() in "aeiou" else "a"
        lines_desc = f'This is {article} {en} → 特征 → 颜色 → "I like this {en}" 四句跟读卡'
    # 注入该词卡片上的真实台词,正文引用必须逐字一致,不许自创句式
    actual = "\n".join(f"  {i+1}. {ln['en']} ({ln['zh']})"
                       for i, ln in enumerate(word.get("lines", [])))
    interaction = word.get("interaction", "")
    return f"""你是小红书母婴启蒙爆款作者,人设是"陪娃英语启蒙的宝妈"。
为单词【{word['en']} {word['zh']}】的 9 页蜡笔风图文笔记写发布物料。
笔记内容:{lines_desc} + 亲子互动玩法。

【卡片上的真实四句台词,正文里出现台词时必须与此逐字一致,严禁改写或换句式】:
{actual}
【可直接化用的亲子互动玩法】:{interaction}

严格只输出 JSON:
{{
  "titles": ["封面标题1", "...共5个,各不相同"],
  "pick_index": 0,
  "body": "正文200-350字",
  "tags": ["标签", "必须给满8个,不带#号"]
}}

要求:
1. 标题≤20字,公式=年龄锚点(2岁/3岁)+结果承诺(开口/跟读/不费妈)+低成本动作(每天5分钟)+情绪或悬念;封面无文字时更要有点击欲
2. pick_index 给出你判断点击率最高的标题下标(0-4)
3. 正文结构:一句痛点钩子 → 怎么用(每天5分钟跟读上面4句原句,可用①②③④列出)→ 化用亲子互动玩法 → 提醒"先收藏免得找不到"→ 一句资源引导;口语化、有温度,不堆砌
4. tags 必须 8 个,前3个必须从这些大词里选,其余围绕单词卡/启蒙年龄/亲子场景:{pool}
5. 合规铁律:不得出现以下任何词:{banned};不写集数夸大承诺;不引导站外
"""


def make_post(word, cfg, providers):
    post_cfg = cfg["production"]["post"]
    pool = post_cfg["tags_pool"]
    banned = cfg["compliance"]["banned_terms"]
    llm_cfg = cfg["llm"]
    # 主模型;若配了 fallback(如智谱营销类空返回→百炼),依次尝试
    candidates = [(llm_cfg["provider"], llm_cfg["model_pro"])]
    if llm_cfg.get("fallback_provider") and llm_cfg.get("fallback_model"):
        candidates.append((llm_cfg["fallback_provider"], llm_cfg["fallback_model"]))

    obj = None
    for attempt in range(2):
        warn = ""
        if attempt == 1:
            must = " / ".join(ln["en"] for ln in word.get("lines", []))
            warn = ("\n上一版不合规或台词没逐字引用。这次务必:①正文①②③④必须原样逐字包含这4句:"
                    f"{must} ②只用允许的表述,资源引导统一写成「原创磨耳朵资源已整理,评论区扣1」"
                    "③tags 必须给满 8 个。")
        prompt = build_prompt(word, pool, banned) + warn
        raw = ""
        for prov_name, model_name in candidates:
            raw = call_llm(providers, prov_name, model_name, prompt,
                           max_tokens=4000, json_mode=True)
            if raw and raw.strip():
                break
            print(f"    [FALLBACK] {prov_name}/{model_name} 空返回,换下一模型")
        if not raw or not raw.strip():
            continue
        try:
            obj = parse_json(raw)
        except Exception as e:
            print(f"    [JSON retry] {e}")
            continue
        # 选标题:优先 LLM 的 pick,过滤违规标题
        titles = [t for t in obj.get("titles", []) if t and not check_compliance(t, cfg)]
        if not titles:
            print("    [RETRY] 标题全部命中合规词")
            continue
        idx = obj.get("pick_index", 0)
        title = titles[0]
        for t in obj.get("titles", []):
            if idx < len(obj["titles"]) and obj["titles"][idx] in titles:
                title = obj["titles"][idx]
                break
        body = obj.get("body", "")
        hits = check_compliance(title + body, cfg)
        if hits:
            print(f"    [RETRY] 正文命中违规词: {hits}")
            continue
        # 台词逐字一致性:正文必须原样包含卡片上的 4 句英文
        missing = [ln["en"] for ln in word.get("lines", []) if ln["en"] not in body]
        if missing:
            print(f"    [RETRY] 正文未逐字引用台词: {missing}")
            # 把缺失原句塞进重试警告
            extra = "".join(missing)
            if extra:  # 仅本轮日志提示,下一轮 warn 已含指引;再失败放行人工审
                pass
            continue
        # 标签:去重 → 保前3大词 → 用标签池补满 8 个
        raw_tags = [t.lstrip("#").strip() for t in obj.get("tags", []) if t.strip()]
        tags = []
        for t in raw_tags:
            if t not in tags:
                tags.append(t)
        for big in pool:
            if len(tags) >= 8:
                break
            if big not in tags:
                tags.append(big)
        tags = tags[:8]
        return title, body, tags

    return None


def rerender_cover(word_en, title):
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "compose_cards.py"),
         "--word", word_en, "--cover-title", title],
        capture_output=True, text=True, cwd=str(SCRIPTS_DIR))
    if r.returncode != 0:
        print(f"    [COVER WARN] 封面重渲染失败:{r.stderr[-200:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word")
    args = ap.parse_args()

    cfg = load_config()
    providers = load_providers()
    scripted = load_json(SCRIPTED_PATH, {"words": []})
    produced = load_json(PRODUCED_PATH, {"posts": []})
    existing = {p["topic_id"]: i for i, p in enumerate(produced["posts"])}

    targets = [w for w in scripted["words"]
               if w.get("status") in ("cards_done", "ready")
               and (not args.word or w["en"].lower() == args.word.lower())]
    if not targets:
        print("[INFO] 没有已排卡的词,先依次跑 build_scripts / gen_images / compose_cards")

    made = 0
    for word in targets:
        wid = word["word_id"]
        cards_dir = IMAGES / wid / "cards"
        card_paths = [f"data/images/{wid}/cards/{i:02d}.png" for i in range(1, 10)]
        if not all((DATA.parent / p).exists() for p in card_paths):
            print(f"[SKIP] {wid} 九页卡不齐")
            continue
        if wid in existing and not args.word:
            continue

        print(f"[POST] {wid} {word['en']} {word['zh']}")
        result = make_post(word, cfg, providers)
        if not result:
            print("    [BLOCKED] 两次仍不合规,跳过")
            continue
        title, body, tags = result
        rerender_cover(word["en"], title)

        post = {
            "topic_id": wid, "track": "wordcard", "status": "ready",
            "word_en": word["en"], "word_zh": word["zh"],
            "title": title, "body": body,
            "tags": tags,
            "collection": f"{word['family_zh']}系列",
            "image_paths": card_paths,
            "raw_image_paths": [f"data/images/{wid}/raw_{i}.png" for i in range(1, 5)],
            "cross_sell_hint": cfg["production"]["post"]["cta_template"],
            "post_time_hint": cfg["production"]["post"]["post_time_hint"],
            "note_url": "",
            "produced_at": now_iso(),
        }
        if wid in existing:
            produced["posts"][existing[wid]] = post
        else:
            produced["posts"].append(post)
        word["status"] = "ready"
        save_json(PRODUCED_PATH, produced)
        save_json(SCRIPTED_PATH, scripted)
        made += 1
        print(f"    标题: {title}")

    produced["produced_at"] = now_iso()
    save_json(PRODUCED_PATH, produced)
    print(f"\n[DONE] 新组装 {made} 篇,累计 {len(produced['posts'])} 篇 -> {PRODUCED_PATH}")


if __name__ == "__main__":
    sys.exit(main())
