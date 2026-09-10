#!/usr/bin/env python3
"""
03-b · 固定蜡笔画风批量生图 → data/images/{word_id}/raw_1..4.png
prompt = base_style 固定骨架 + 词族 slot 主体插槽 + 该句分镜;负面词内嵌到 prompt 尾部。
断点续跑:已存在的 raw 图不重复生成;全部 4 张就绪后状态置 images_done。

用法:
  python3 gen_images.py
  python3 gen_images.py --word apple
  python3 gen_images.py --force        # 缺失重生成之外,连已有图也重出
"""
import argparse
import sys
from pathlib import Path

from common_llm import (DATA, IMAGES, ROOT, bl_image, load_config, load_json,
                        now_iso, save_json)

SCRIPTED_PATH = DATA / "scripted.json"


def compose_prompt(base, word, scene):
    """固定画风骨架 + 主体插槽 + 本分镜动作;负面词走 --negative-prompt。"""
    prompt = base.replace("【SUBJECT】", word["slot"]).strip()
    prompt += f" 本句画面:{scene}。"
    return prompt


def stable_seed(word):
    """同词 4 张共用一个稳定 seed(跨进程可复现),提升角色/配色一致性。"""
    import hashlib
    return int(hashlib.md5(f"v1/{word['word_id']}".encode()).hexdigest()[:8], 16) % 1_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word", help="只跑指定英文单词")
    ap.add_argument("--force", action="store_true", help="已有图也重新生成")
    args = ap.parse_args()

    cfg = load_config()
    img_cfg = cfg["production"]["image"]
    base = (ROOT / img_cfg["style_file"]).read_text(encoding="utf-8")
    negative = (ROOT / img_cfg["negative_file"]).read_text(encoding="utf-8")
    size = img_cfg["size"]
    per_word = img_cfg["per_word"]

    scripted = load_json(SCRIPTED_PATH, {"words": []})
    targets = [w for w in scripted["words"]
               if (not args.word or w["en"].lower() == args.word.lower())]
    if args.word and not targets:
        print(f"[ERR] scripted.json 没有 {args.word},先跑 build_scripts.py --word {args.word}")
        sys.exit(1)

    ok_words, fail_words = 0, 0
    for word in targets:
        wid = word["word_id"]
        out_dir = IMAGES / wid
        paths = [out_dir / f"raw_{i}.png" for i in range(1, per_word + 1)]

        if all(p.exists() for p in paths) and not args.force:
            word["status"] = "images_done"
            print(f"[SKIP] {wid} {word['en']} 4 张图已存在")
            ok_words += 1
            continue

        print(f"[IMG] {wid} {word['en']} {word['zh']} (seed={stable_seed(word)})")
        made_all = True
        seed = stable_seed(word)
        for i in range(per_word):
            if paths[i].exists() and not args.force:
                print(f"    raw_{i+1} 已存在")
                continue
            scene = word["scenes"][i] if i < len(word.get("scenes", [])) else ""
            prompt = compose_prompt(base, word, scene)
            path = bl_image(prompt, out_dir, f"raw_{i+1}_", size=size,
                            negative_prompt=negative.strip(), seed=seed)
            # bl 输出带随机后缀,统一重命名为 raw_i.png
            if path:
                generated = Path(path)
                if generated != paths[i]:
                    generated.rename(paths[i])
                print(f"    raw_{i+1} ok")
            else:
                made_all = False
                break

        if made_all and all(p.exists() for p in paths):
            word["status"] = "images_done"
            word["images_at"] = now_iso()
            ok_words += 1
        else:
            fail_words += 1
            print(f"    [FAIL] {wid} 未出齐 4 张,保持 scripted 状态,重跑本命令即可续上")
        save_json(SCRIPTED_PATH, scripted)

    save_json(SCRIPTED_PATH, scripted)
    print(f"\n[DONE] 出词 {ok_words} | 失败 {fail_words}")


if __name__ == "__main__":
    sys.exit(main())
