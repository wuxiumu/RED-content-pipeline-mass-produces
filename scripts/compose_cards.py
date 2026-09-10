#!/usr/bin/env python3
"""
03-c · Pillow 九页卡排版(1080×1440)→ data/images/{word_id}/cards/01..09.png
铁律:AI 原图无文字,所有英文字母/中文全部在此脚本后期叠加,字体全系列统一。

用法:
  python3 compose_cards.py                  # 给所有 images_done 的词排卡
  python3 compose_cards.py --word apple
  python3 compose_cards.py --word apple --cover-title "2岁娃看完主动开口"
"""
import argparse
import glob
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common_llm import (DATA, IMAGES, load_config, load_json, now_iso,
                        save_json)

SCRIPTED_PATH = DATA / "scripted.json"

# 每族一套马卡龙配色:(背景, 字板/卡片, 强调色, 深色文字)
PALETTES = {
    "fruits":    ((255, 244, 230), (255, 255, 255), (240, 110, 96),  (90, 70, 60)),
    "animals":   ((240, 248, 235), (255, 255, 255), (120, 175, 96),  (70, 86, 60)),
    "food":      ((255, 246, 226), (255, 255, 255), (235, 160, 60),  (96, 74, 48)),
    "vehicles":  ((234, 244, 252), (255, 255, 255), (80, 150, 210),  (58, 78, 96)),
    "body":      ((245, 240, 252), (255, 255, 255), (150, 120, 210), (74, 64, 96)),
    "colors":    ((252, 242, 248), (255, 255, 255), (225, 110, 170), (96, 66, 86)),
    "numbers":   ((238, 250, 246), (255, 255, 255), (70, 180, 150),  (58, 90, 82)),
    "weather":   ((236, 244, 252), (255, 255, 255), (96, 150, 220),  (58, 78, 100)),
    "family":    ((253, 240, 242), (255, 255, 255), (224, 120, 140), (96, 66, 72)),
    "nature":    ((238, 248, 232), (255, 255, 255), (110, 170, 80),  (64, 84, 56)),
}
DEFAULT_PALETTE = ((255, 248, 236), (255, 255, 255), (240, 160, 90), (90, 70, 60))


def find_font(patterns, fallback):
    for pat in patterns:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return fallback


def font(size, bold_en=False):
    path = EN_BOLD if bold_en else (EN_FONT if size > 40 else ZH_FONT)
    return ImageFont.truetype(path, size)


def zh_font(size):
    return ImageFont.truetype(ZH_FONT, size)


def text_size(draw, t, f):
    b = draw.textbbox((0, 0), t, font=f)
    return b[2] - b[0], b[3] - b[1]


def draw_center(draw, xy_center, t, f, fill):
    w, h = text_size(draw, t, f)
    draw.text((xy_center[0] - w / 2, xy_center[1] - h / 2), t, font=f, fill=fill)


def has_glyph(f, ch):
    bbox = f.getmask(ch).getbbox()
    return bbox is not None


def _glyph_sig(f, ch):
    """把单字画到固定小画布取像素签名,用于和 .notdef 比对。"""
    im = Image.new("L", (120, 120), 0)
    ImageDraw.Draw(im).text((10, 25), ch, font=f, fill=255)
    return im.tobytes()


def _is_tofu(f, ch, notdef_sig):
    """字形为空,或渲染结果与 .notdef(私用区 U+E000)完全一致 → 豆腐块。"""
    return _glyph_sig(f, ch) == notdef_sig


def draw_center_mixed(draw, xy_center, text, fonts, fill, font_size=48):
    """逐字符挑第一个真正含该字形的字体(Arial Rounded 的 .notdef 有框,
    光看 bbox 会误判,必须与私用区缺字渲染结果比对)。"""
    chosen = [ImageFont.truetype(fp, font_size) for fp in fonts]
    notdef = [_glyph_sig(f, "") for f in chosen]
    runs, cur_font, cur = [], chosen[0], ""
    for ch in text:
        f = next((cf for cf, nd in zip(chosen, notdef)
                  if not _is_tofu(cf, ch, nd)), chosen[-1])
        if f != cur_font and cur:
            runs.append((cur_font, cur))
            cur_font, cur = f, ch
        else:
            cur_font = f
            cur += ch
    if cur:
        runs.append((cur_font, cur))
    total_w = sum(text_size(draw, s, f)[0] for f, s in runs)
    x, (_, cy) = xy_center[0] - total_w / 2, xy_center
    for f, s in runs:
        w, h = text_size(draw, s, f)
        draw.text((x, cy - h / 2), s, font=f, fill=fill)
        x += w


def wrap_cjk(draw, text, f, max_width):
    """按像素宽度对中文混排文本折行(英文不断词)。"""
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if text_size(draw, trial, f)[0] > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def fit_en(draw, text, max_width, start=92, min_size=48):
    size = start
    while size > min_size:
        f = font(size, bold_en=True)
        if text_size(draw, text, f)[0] <= max_width:
            return f
        size -= 4
    return font(min_size, bold_en=True)


def cover_crop(img, w, h):
    src_ratio, dst_ratio = img.width / img.height, w / h
    if src_ratio > dst_ratio:
        nh = h
        nw = int(h * src_ratio)
    else:
        nw = w
        nh = int(w / src_ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    return img.crop(((nw - w) // 2, (nh - h) // 2,
                     (nw + w) // 2, (nh + h) // 2))


def rounded_paste(base, img, box, radius):
    """把 PIL 图以圆角贴到 base。box=(x1,y1,x2,y2)。"""
    x1, y1, x2, y2 = box
    img = cover_crop(img, x2 - x1, y2 - y1)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width, img.height),
                                           radius=radius, fill=255)
    base.paste(img, (x1, y1), mask)


def rounded_rect(img, box, radius, fill):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, radius=radius, fill=fill)
    img.alpha_composite(overlay)


def page_bg(bg):
    return Image.new("RGBA", (W, H), bg + (255,))


# ---------- 9 个页面 ----------

def card_cover(word, raws, cover_title, pal):
    bg, plate, accent, dark = pal
    img = page_bg(bg)
    img.paste(cover_crop(raws[0], W, H), (0, 0))
    # 顶部奶白半透明字板
    rounded_rect(img, (60, 90, W - 60, 470), 48, (255, 252, 246, 238))
    d = ImageDraw.Draw(img)
    draw_center(d, (W // 2, 168), f"{word['family_zh']}系列 · 每天5分钟磨耳朵",
                zh_font(40), tuple(accent))
    # 主标题:传入封面标题,否则用默认 "{zh}英语启蒙"
    title = cover_title or f"{word['zh']}英语启蒙"
    tf = zh_font(96)
    lines = wrap_cjk(d, title, tf, W - 200)
    if len(lines) > 2:  # 过长则缩一档
        tf = zh_font(78)
        lines = wrap_cjk(d, title, tf, W - 200)
    total_h = sum(text_size(d, ln, tf)[1] for ln in lines) + 12 * (len(lines) - 1)
    y = 300 - total_h / 2
    for ln in lines:
        h = text_size(d, ln, tf)[1]
        draw_center(d, (W // 2, y + h / 2), ln, tf, tuple(dark))
        y += h + 12
    # 底部胶囊(奶白底 + 强调色字,避免与彩色底图撞色)
    rounded_rect(img, (240, H - 170, W - 240, H - 90), 40,
                 (255, 252, 246, 238))
    draw_center(d, (W // 2, H - 130),
                f"2岁+ 零基础跟读  {word['family_zh']}{word['word_index']+1:02d}",
                zh_font(38), tuple(accent))
    return img.convert("RGB")


def card_line(word, raws, idx, pal):
    bg, plate, accent, dark = pal
    img = page_bg(bg)
    rounded_paste(img, raws[idx], (80, 60, W - 80, 1000), 44)
    rounded_rect(img, (80, 1020, W - 80, 1380), 40, tuple(plate) + (255,))
    d = ImageDraw.Draw(img)
    en, zh = word["lines"][idx]["en"], word["lines"][idx]["zh"]
    ef = fit_en(d, en, W - 240)
    draw_center(d, (W // 2, 1135), en, ef, tuple(dark))
    draw_center(d, (W // 2, 1290), zh, zh_font(46), tuple(accent))
    # 角标(半透明深色小胶囊保证在任何图上可读)
    rounded_rect(img, (W - 215, 78, W - 95, 162), 40, (60, 50, 40, 110))
    draw_center(d, (W - 155, 120), f"{idx+1}/4", zh_font(34), (255, 255, 255))
    return img.convert("RGB")


def card_word(word, raws, pal):
    bg, plate, accent, dark = pal
    img = page_bg(bg)
    rounded_paste(img, raws[0], (W // 2 - 200, 170, W // 2 + 200, 570), 400)
    d = ImageDraw.Draw(img)
    ef = fit_en(d, word["en"], W - 160, start=170, min_size=80)
    draw_center(d, (W // 2, 770), word["en"], ef, tuple(dark))
    # 音标准确呈现 ˈˌ 重音与 IPA 字符,整串用 IPA_FONT(Arial Unicode,全覆盖)
    phonetic = word.get("phonetic", "")
    draw_center_mixed(d, (W // 2, 900), phonetic,
                      [IPA_FONT, EN_BOLD, ZH_FONT], tuple(accent), font_size=48)
    draw_center(d, (W // 2, 1000), word["zh"], zh_font(64), tuple(dark))
    rounded_rect(img, (W // 2 - 190, 1090, W // 2 + 190, 1180), 45,
                 tuple(accent) + (255,))
    draw_center(d, (W // 2, 1135), "跟着读 3 遍", zh_font(42), (255, 255, 255))
    return img.convert("RGB")


def card_interaction(word, raws, pal):
    bg, plate, accent, dark = pal
    img = page_bg(bg)
    d = ImageDraw.Draw(img)
    draw_center(d, (W // 2, 230), "今天就这样玩", zh_font(76), tuple(dark))
    rounded_rect(img, (90, 340, W - 90, 880), 44, tuple(plate) + (255,))
    f = zh_font(56)
    lines = wrap_cjk(d, word["interaction"], f, W - 240)
    y = 430
    for ln in lines:
        draw_center(d, (W // 2, y + 40), ln, f, tuple(dark))
        y += 90
    rounded_paste(img, raws[0], (W // 2 - 160, 950, W // 2 + 160, 1270), 320)
    return img.convert("RGB")


def card_collection(word, scripted, pal):
    bg, plate, accent, dark = pal
    img = page_bg(bg)
    d = ImageDraw.Draw(img)
    all_words = [w for w in load_family_words() if w["family_id"] == word["family"]]
    total = len(all_words)

    def has_deck(w):
        # "已更新"只认真正排完九页卡的词,不能把'写完台词'算作已发布
        cdir = IMAGES / w["word_id"] / "cards"
        return (cdir / "01.png").exists() and (cdir / "09.png").exists()

    done_words = {w["en"] for w in all_words if has_deck(w)}
    draw_center(d, (W // 2, 200), f"{word['family_zh']}系列", zh_font(80), tuple(dark))
    draw_center(d, (W // 2, 300), f"已更新 {len(done_words)}/{total} · 点主页合集追更",
                zh_font(40), tuple(accent))
    rows = (total + 1) // 2
    f = zh_font(42)
    for i, w in enumerate(all_words):
        col, row = i // rows, i % rows
        x, yy = 110 + col * 475, 420 + row * 90
        done = w["en"] in done_words
        current = w["en"] == word["en"]
        # 用全角 √(中文字体含此字形),避免 ✓ 在部分字体里变豆腐块
        d.text((x, yy), "√" if done else "·", font=f,
               fill=tuple(accent if done else (185, 185, 185)))
        text_color = accent if current else (dark if done else (175, 175, 175))
        d.text((x + 52, yy), f"{w['zh']} {w['en']}", font=f, fill=tuple(text_color))
    return img.convert("RGB")


def card_cta(pal, resource_claim):
    bg, plate, accent, dark = pal
    img = page_bg((255, 248, 236))
    d = ImageDraw.Draw(img)
    draw_center(d, (W // 2, 250), "磨耳朵资源包", zh_font(92), tuple(dark))
    draw_center(d, (W // 2, 360), "原创自制 · 持续更新", zh_font(42), tuple(accent))
    rounded_rect(img, (100, 470, W - 100, 860), 44, tuple(plate) + (255,))
    f = zh_font(52)
    y = 540
    for ln in wrap_cjk(d, resource_claim, f, W - 260):
        draw_center(d, (W // 2, y + 36), ln, f, tuple(dark))
        y += 84
    rounded_rect(img, (220, 960, W - 220, 1100), 70, tuple(accent) + (255,))
    draw_center(d, (W // 2, 1030), "评论区扣【1】领取", zh_font(60), (255, 255, 255))
    draw_center(d, (W // 2, 1210), "点关注,每天一个新单词", zh_font(40), tuple(dark))
    return img.convert("RGB")


def load_family_words():
    from common_llm import flatten_words
    return flatten_words()


def compose(word, scripted, cover_title, cfg):
    wid = word["word_id"]
    wdir = IMAGES / wid
    raw_paths = [wdir / f"raw_{i}.png" for i in range(1, 5)]
    missing = [str(p) for p in raw_paths if not p.exists()]
    if missing:
        print(f"[SKIP] {wid} {word['en']} 缺原图,先跑 gen_images.py")
        return False
    raws = [Image.open(p).convert("RGBA") for p in raw_paths]
    pal = PALETTES.get(word["family"], DEFAULT_PALETTE)

    out_dir = wdir / "cards"
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = (
        [card_cover(word, raws, cover_title, pal)] +
        [card_line(word, raws, i, pal) for i in range(4)] +
        [card_word(word, raws, pal),
         card_interaction(word, raws, pal),
         card_collection(word, scripted, pal),
         card_cta(pal, cfg["compliance"]["resource_claim"])]
    )
    for i, page in enumerate(pages, 1):
        page.save(out_dir / f"{i:02d}.png", quality=95)
    print(f"[CARD] {wid} {word['en']} -> {out_dir} (9 页)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word")
    ap.add_argument("--cover-title", default="")
    args = ap.parse_args()

    cfg = load_config()
    global W, H, EN_FONT, EN_BOLD, ZH_FONT, IPA_FONT
    W = cfg["production"]["card"]["width"]
    H = cfg["production"]["card"]["height"]

    ZH_FONT = find_font(
        ["/System/Library/Fonts/PingFang.ttc",
         "/System/Library/Fonts/Hiragino Sans GB.ttc",
         "/System/Library/Fonts/STHeiti Medium.ttc",
         "/System/Library/Fonts/Supplemental/Songti.ttc"], "")
    if not ZH_FONT:
        print("[ERR] 未找到任何中文字体(PingFang/Hiragino/STHeiti)")
        sys.exit(1)
    EN_BOLD = find_font(
        ["/System/Library/Fonts/Supplemental/*ounded*.ttf",
         "/System/Library/Fonts/SFNSRounded.ttf"], ZH_FONT)
    EN_FONT = find_font(
        ["/System/Library/Fonts/Supplemental/Helvetica*Bold*.ttf"], ZH_FONT)
    # IPA 音标专用字体:Arial Rounded 缺 ɡ ɪ 等字形会出豆腐块,
    # Arial Unicode/Times/Helvetica 对 IPA 全覆盖(已实测)
    IPA_FONT = find_font(
        ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
         "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
         "/System/Library/Fonts/Helvetica.ttc"], EN_FONT)

    scripted = load_json(SCRIPTED_PATH, {"words": []})
    targets = [w for w in scripted["words"]
               if (not args.word or w["en"].lower() == args.word.lower())]
    if args.word and not targets:
        print(f"[ERR] scripted.json 没有 {args.word}")
        sys.exit(1)

    done = 0
    for word in targets:
        if not (IMAGES / word["word_id"] / "raw_1.png").exists():
            print(f"[SKIP] {word['word_id']} {word['en']} 未生图")
            continue
        if compose(word, scripted, args.cover_title, cfg):
            word["status"] = "cards_done"
            word["cards_at"] = now_iso()
            done += 1
            save_json(SCRIPTED_PATH, scripted)
    print(f"\n[DONE] 排卡 {done} 个词")


if __name__ == "__main__":
    main()
