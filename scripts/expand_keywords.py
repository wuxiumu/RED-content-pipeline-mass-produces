#!/usr/bin/env python3
"""
01 收集智能体 · 关键词扩展
读 collect_config.yaml,用 LLM 把三轨种子词扩成长尾词,输出 data/collected.json。
冷启动阶段可完全不跑本脚本,02 支持直接用词族表排产。
"""
import sys
import time

from common_llm import (DATA, ROOT, call_llm, load_config, load_providers,
                        now_iso, save_json)

COLLECTED_PATH = DATA / "collected.json"


def expand_seed(providers, provider, model, seed, n):
    prompt = f"""你是小红书母婴垂类运营专家。基于种子词「{seed}」扩展 {n} 个小红书长尾搜索词。
要求:
1. 贴合 2-6 岁宝妈真实搜索习惯(口语化、带年龄/场景,如"2岁英语启蒙日常")
2. 与种子词不重复,彼此不重复
3. 优先有具体场景、有收藏动机的词(资料/清单/打卡/跟练)
4. 不要泛词;不要出现任何具体动画 IP 名称

只输出关键词,每行一个,不编号不解释。"""
    text = call_llm(providers, provider, model, prompt, max_tokens=800)
    words, seen = [], set()
    for line in text.splitlines():
        line = line.strip().lstrip("0123456789.、- )(").strip()
        if line and len(line) <= 20 and line not in seen and line != seed:
            seen.add(line)
            words.append(line)
    return words[:n]


def main():
    cfg = load_config()
    providers = load_providers()
    provider = cfg["llm"]["provider"]
    model = cfg["llm"]["model_flash"]
    print(f"[INFO] LLM: {provider} / {model}")

    result = {
        "collected_at": now_iso(),
        "niche": cfg["niche"],
        "tracks": {},
        "competitors": [],
        "feedback_weighted": {"wordcard": [], "video": [], "resource": []},
    }

    for track_name, track_cfg in cfg["tracks"].items():
        print(f"\n[Track] {track_name} - {len(track_cfg['seeds'])} seeds")
        keywords, seed_set = [], set(track_cfg["seeds"])
        for s in track_cfg["seeds"]:
            keywords.append({"word": s, "source": "seed",
                             "hot_score": 0, "trend": "unknown", "samples_count": 0})
        for seed in track_cfg["seeds"]:
            try:
                for w in expand_seed(providers, provider, model,
                                     seed, track_cfg["expand_per_seed"]):
                    if w not in seed_set:
                        seed_set.add(w)
                        keywords.append({"word": w,
                                         "source": f"llm_expand_from:{seed}",
                                         "hot_score": 0, "trend": "unknown",
                                         "samples_count": 0})
                print(f"  {seed} ok")
            except Exception as e:
                print(f"  [WARN] {seed} 扩展失败: {e}")
            time.sleep(0.3)
        result["tracks"][track_name] = {"keywords": keywords, "samples": []}
        print(f"  合计 {len(keywords)} 词")

    save_json(COLLECTED_PATH, result)
    print(f"\n[DONE] -> {COLLECTED_PATH}")


if __name__ == "__main__":
    sys.exit(main())
