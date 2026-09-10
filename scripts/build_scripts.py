#!/usr/bin/env python3
"""
03-a · 词 → 4 句台词 + 4 条分镜 + 亲子互动话术 → data/scripted.json
消费 judged.json 的 wordcard 队列;断点续跑,已 scripted 的词自动跳过。

用法:
  python3 build_scripts.py
  python3 build_scripts.py --word apple      # 强制重跑某词(会覆盖该词记录)
"""
import argparse
import sys

from common_llm import (DATA, call_llm, flatten_words, load_config,
                        load_json, load_providers, now_iso, parse_json,
                        save_json)

JUDGED_PATH = DATA / "judged.json"
SCRIPTED_PATH = DATA / "scripted.json"


def build_prompt(item):
    host_note = f"注意:这个词用「{item['host']}」承载,主角始终是它。\n" if item.get("host") else ""
    draw_note = f"画面特殊要求:{item['draw_note']}\n" if item.get("draw_note") else ""
    en, zh = item["en"], item["zh"]
    if item.get("uncountable"):
        # 不可数名词(milk/bread 等):不加 a/an,第1/4句无 this
        grammar = f"""- 【{en} 是不可数名词,全程不加 a/an,不要写成 a {en}】
  第1句命名:This is {en}.(不要 a/an)
  第2句特征:The {en} is ...(从造型选一个简单特征,如 white/soft/long)
  第3句颜色:Its color is ...(只选一个最具代表性的颜色)
  第4句喜好:I like {en}.(不加 this)"""
        first_en, first_zh = f"This is {en}.", f"这是{zh}。"
    else:
        # a/an 按发音选择:元音音素开头用 an
        article = "an" if en[0].lower() in "aeiou" else "a"
        grammar = f"""- 全文严格 4 句,每句英文不超过 8 个基础单词,句式固定:
  第1句命名:This is {article} {en}.
  第2句特征:The {en} is ...(从造型选一个简单特征,如 round/soft/long)
  第3句颜色:Its color is ...(只选一个最具代表性的颜色)
  第4句喜好:I like this {en}."""
        first_en, first_zh = f"This is {article} {en}.", f"这是一个{zh}。"
    return f"""你是有 10 年经验的幼儿英语启蒙教研专家与短视频编剧。
为单词【{en} {zh}】创作 15-20 秒磨耳朵内容。
主体造型(分镜必须沿用):{item['slot']}
{host_note}{draw_note}
语言规则:
{grammar}
- 中文翻译为标准普通话,适合 2-4 岁孩子听。
分镜规则:4 个分镜一一对应 4 句台词;蜡笔手绘、马卡龙色、画面干净;
每条分镜不超过 50 个汉字,只写主体+一个简单动作+背景;
严禁描述任何文字、字母、数字、水印出现(单词字母后期才加)。

严格只输出 JSON:
{{
  "lines": [
    {{"en": "{first_en}", "zh": "{first_zh}"}},
    {{"en": "...", "zh": "..."}},
    {{"en": "...", "zh": "..."}},
    {{"en": "...", "zh": "..."}}
  ],
  "phonetic": "音标,含两侧斜杠",
  "color": "一个代表性颜色的中文,如 红色",
  "scenes": ["分镜1中文画面描述(主体造型+动作+背景,无文字)", "...(共4条)"],
  "interaction": "一句亲子互动话术(给家长一个具体动作,如:吃水果时让孩子找一找{zh}在哪里)"
}}"""


def validate(obj, item):
    assert isinstance(obj.get("lines"), list) and len(obj["lines"]) == 4, "lines 必须 4 句"
    en = item["en"]
    for i, ln in enumerate(obj["lines"]):
        assert ln.get("en") and ln.get("zh"), f"第{i+1}句缺中英文"
        assert len(ln["en"].split()) <= 8, f"第{i+1}句超过 8 词"
    # 句式硬校验:不可数名词不得出现 a/an,可数名词第1句必须带 a/an
    first = obj["lines"][0]["en"].lower()
    if item.get("uncountable"):
        assert f"a {en}" not in first and f"an {en}" not in first, f"不可数名词不能加 a/an:{first}"
        assert first.startswith(f"this is {en}"), f"第1句应为 This is {en}."
        assert obj["lines"][3]["en"].lower().startswith("i like"), "第4句应以 I like 开头"
    else:
        article = "an" if en[0].lower() in "aeiou" else "a"
        assert first.startswith(f"this is {article} {en}"), f"第1句应为 This is {article} {en}."
        assert obj["lines"][3]["en"].lower().startswith(f"i like this {en}"), "第4句应为 I like this..."
    assert isinstance(obj.get("scenes"), list) and len(obj["scenes"]) == 4, "scenes 必须 4 条"
    assert obj.get("interaction"), "缺 interaction"
    assert obj.get("phonetic"), "缺 phonetic"
    # 分镜不得含字母描述(简单拦截:不得出现全大写英文单词,除颜色名外)
    for sc in obj["scenes"]:
        for token in sc.replace("，", " ").replace("。", " ").split():
            if token.isalpha() and token.isupper() and len(token) >= 2:
                raise AssertionError(f"分镜出现疑似字母文字:{token}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word", help="只跑指定英文单词(覆盖)")
    args = ap.parse_args()

    cfg = load_config()
    providers = load_providers()
    provider = cfg["llm"]["provider"]
    model = cfg["llm"]["model_flash"]

    judged = load_json(JUDGED_PATH, {})
    queue = judged.get("tracks", {}).get("wordcard", {}).get("queue", [])
    flat = {w["en"].lower(): w for w in flatten_words()}

    if args.word:
        key = args.word.lower()
        if key not in flat:
            print(f"[ERR] 词族表没有 {args.word}")
            sys.exit(1)
        targets = [flat[key]]
    else:
        if not queue:
            print("[ERR] judged.json 无 wordcard 队列,先跑 judge.py(冷启动可直接 judge --limit 5)")
            sys.exit(1)
        targets = []
        for q in queue:
            w = flat.get(q["word_en"].lower())
            if w:
                w = dict(w)
                w["slot"] = q.get("slot") or w["slot"]
                w["host"] = q.get("host", "")
                w["draw_note"] = q.get("draw_note", "")
                targets.append(w)

    scripted = load_json(SCRIPTED_PATH, {"words": []})
    by_id = {w["word_id"]: i for i, w in enumerate(scripted["words"])}
    done = {w["word_id"] for w in scripted["words"] if w.get("status") == "scripted"}

    made, skipped, failed = 0, 0, 0
    for item in targets:
        wid = item["word_id"]
        if wid in done and not args.word:
            skipped += 1
            continue
        print(f"[SCRIPT] {wid} {item['en']} {item['zh']}")
        obj = None
        for attempt in range(3):
            try:
                raw = call_llm(providers, provider, model, build_prompt(item),
                               max_tokens=3000, json_mode=True)
                obj = parse_json(raw)
                validate(obj, item)
                break
            except Exception as e:
                print(f"    [retry {attempt+1}/3] {e}")
                obj = None
        if not obj:
            failed += 1
            continue

        record = {
            "word_id": wid, "family": item["family_id"], "family_zh": item["family_zh"],
            "family_index": item["family_index"], "word_index": item["word_index"],
            "family_size": item["family_size"],
            "en": item["en"], "zh": item["zh"], "slot": item["slot"],
            "uncountable": bool(item.get("uncountable", False)),
            "host": item.get("host", ""), "draw_note": item.get("draw_note", ""),
            "phonetic": obj["phonetic"], "color": obj.get("color", ""),
            "lines": obj["lines"], "scenes": obj["scenes"],
            "interaction": obj["interaction"],
            "status": "scripted", "built_at": now_iso(),
        }
        if wid in by_id:
            scripted["words"][by_id[wid]] = record
        else:
            scripted["words"].append(record)
        save_json(SCRIPTED_PATH, scripted)  # 逐词落盘防丢进度
        made += 1
        print(f"    ok: {obj['lines'][0]['en']}")

    scripted["built_at"] = now_iso()
    save_json(SCRIPTED_PATH, scripted)
    print(f"\n[DONE] 生成 {made} | 跳过 {skipped} | 失败 {failed} -> {SCRIPTED_PATH}")


if __name__ == "__main__":
    sys.exit(main())
