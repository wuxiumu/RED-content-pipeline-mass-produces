#!/usr/bin/env python3
"""
01 收集智能体 · 小红书爆款样本抓取(自 _plan/scrape_xhs.py 适配)
读 data/collected.json,对三轨 top N 关键词搜索小红书,抓标题/作者/点赞/封面/链接。

登录:首次有头浏览器扫码,检测 web_session cookie 后自动保存 data/xhs_state.json。
反爬:关键词间隔 5-8 秒、有头模式、单关键词 15 条、断点续抓(按 keyword 去重)。
冷启动可不跑:02 judge 支持直接用词族表排产。
"""
import random
import sys
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from common_llm import DATA, load_json, now_iso, save_json

STATE_PATH = DATA / "xhs_state.json"
COLLECTED_PATH = DATA / "collected.json"

KEYWORDS_PER_TRACK = 7
SAMPLES_PER_KEYWORD = 15
SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={}&source=web_search_result_notes"
LOGIN_URL = "https://www.xiaohongshu.com/explore"
LOGIN_WAIT_SECONDS = 600


def ensure_login():
    print("[LOGIN] 启动浏览器,请扫码登录小红书,成功后自动继续...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        for i in range(LOGIN_WAIT_SECONDS // 3):
            time.sleep(3)
            try:
                cookies = ctx.cookies()
                ws = next((c for c in cookies if c["name"] == "web_session"), None)
                if ws and len(ws.get("value", "")) > 10:
                    print("[LOGIN] 登录成功!")
                    time.sleep(3)
                    ctx.storage_state(path=str(STATE_PATH))
                    browser.close()
                    return
            except Exception:
                pass
            if i % 10 == 0:
                print(f"[LOGIN] 等待扫码... ({(i+1)*3}s)", flush=True)
        print("[LOGIN] 超时,保存当前 state")
        ctx.storage_state(path=str(STATE_PATH))
        browser.close()


def parse_likes(s):
    if not s:
        return 0
    s = s.strip().replace("+", "")
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        if "k" in s.lower():
            return int(float(s.lower().replace("k", "")) * 1000)
        return int(s)
    except Exception:
        return 0


def parse_note_card(card):
    try:
        title = ""
        for sel in [".note-title", "[class*='title']", ".desc", ".footer .title", ".note-text"]:
            el = card.query_selector(sel)
            if el and el.inner_text().strip():
                title = el.inner_text().strip()
                break
        if not title:
            lines = [l.strip() for l in card.inner_text("compact").split("\n") if l.strip()]
            title = max(lines, key=len) if lines else ""

        author = ""
        el = card.query_selector("[class*='author'] .name, .author .name, .user .name, [class*='name']")
        if el:
            author = el.inner_text().strip()

        likes_str = ""
        for sel in [".like-wrapper .count", ".like .count", "[class*='like'] [class*='count']"]:
            el = card.query_selector(sel)
            if el:
                likes_str = el.inner_text().strip()
                break

        href = ""
        a = card.query_selector("a.cover, a[href*='/explore/'], a[href*='/note/']")
        if a:
            href = a.get_attribute("href") or ""
        if href and not href.startswith("http"):
            href = "https://www.xiaohongshu.com" + href

        cover = ""
        img = card.query_selector("img")
        if img:
            cover = img.get_attribute("src") or ""

        return {"title": title[:80], "author": author, "likes_text": likes_str,
                "likes": parse_likes(likes_str), "cover_url": cover, "note_url": href,
                "published_at": "", "body_preview": "", "tags": [],
                "cover_type": "", "has_cta": False}
    except Exception as e:
        return {"title": "", "error": str(e)}


def search_keyword(page, keyword, n):
    page.goto(SEARCH_URL.format(keyword), wait_until="domcontentloaded", timeout=30000)
    # quote 在调用处做:这里 keyword 已编码
    page.goto(SEARCH_URL.format(__import__("urllib.parse", fromlist=["quote"]).quote(keyword)),
              wait_until="domcontentloaded", timeout=30000)
    time.sleep(random.uniform(3, 5))
    print(f"     URL={page.url[:80]} | title={page.title()[:40]}")
    for _ in range(2):
        page.mouse.wheel(0, 800)
        time.sleep(random.uniform(1.5, 2.5))

    cards, used_sel = [], ""
    for sel in ["section.note-item", "div.note-item", "[class*='note-item']",
                "a.cover", "section[class*='note']"]:
        cards = page.query_selector_all(sel)
        if cards:
            used_sel = sel
            break
    print(f"     cards={len(cards)} (selector={used_sel})")
    if not cards:
        try:
            print(f"     [DIAG] {page.inner_text('body')[:200]}")
        except Exception:
            pass

    samples = []
    for c in cards[:n * 2]:
        data = parse_note_card(c)
        if data.get("title") and not data.get("error"):
            data["keyword"] = keyword
            samples.append(data)
        if len(samples) >= n:
            break
    return samples


def main():
    if not COLLECTED_PATH.exists():
        print(f"[ERR] {COLLECTED_PATH} 不存在,先跑 expand_keywords.py")
        sys.exit(1)
    collected = load_json(COLLECTED_PATH, {})
    if not STATE_PATH.exists():
        ensure_login()

    total_new = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            storage_state=str(STATE_PATH),
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        for track_name, track in collected["tracks"].items():
            existing = track.get("samples", [])
            scraped_kws = {s.get("keyword") for s in existing if s.get("keyword")}
            existing_titles = {s.get("title") for s in existing}
            seeds = [k["word"] for k in track["keywords"] if k["source"] == "seed"]
            expanded = [k["word"] for k in track["keywords"] if k["source"] != "seed"]
            to_scrape = [w for w in seeds + expanded if w not in scraped_kws][:KEYWORDS_PER_TRACK]
            print(f"\n[Track] {track_name} - 已抓 {len(scraped_kws)} 词,本次 {len(to_scrape)} 词")

            new_samples = []
            for kw in to_scrape:
                try:
                    samples = search_keyword(page, kw, SAMPLES_PER_KEYWORD)
                    unique, local_titles = [], set()
                    for s in samples:
                        t = s.get("title", "")
                        if t and t not in existing_titles and t not in local_titles:
                            local_titles.add(t)
                            unique.append(s)
                    print(f"     {kw}: {len(samples)} -> {len(unique)} 条")
                    new_samples.extend(unique)
                    total_new += len(unique)
                except Exception as e:
                    print(f"     {kw}: FAILED {e}")
                time.sleep(random.uniform(5, 8))
            track["samples"] = existing + new_samples
        browser.close()

    save_json(COLLECTED_PATH, collected)
    total_all = sum(len(t.get("samples", [])) for t in collected["tracks"].values())
    print(f"\n[DONE] 新增 {total_new},合计 {total_all}")
    for t, d in collected["tracks"].items():
        print(f"  {t}: {len(d.get('samples', []))} samples")


if __name__ == "__main__":
    main()
