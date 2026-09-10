#!/usr/bin/env python3
"""共享工具:路径、配置、词族表、LLM 调用、JSON 容错、合规检查、bl image 封装。"""
import json
import re
import subprocess
import time
from pathlib import Path

import requests
import yaml

# 脚本在 scripts/ 下,根目录是上一级
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = DATA / "images"
CONFIG_PATH = ROOT / "collect_config.yaml"
WORDLISTS_PATH = ROOT / "assets" / "wordlists" / "word_families.yaml"
OPENCLAW_PATH = Path.home() / ".openclaw" / "openclaw.json"

DATA.mkdir(exist_ok=True)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_providers():
    with open(OPENCLAW_PATH, "r", encoding="utf-8") as f:
        oc = json.load(f)
    return oc.get("models", {}).get("providers", {})


def call_llm(providers, provider_name, model, prompt,
             max_tokens=2000, json_mode=False, retries=2, timeout=180):
    """调用 LLM。anthropic-messages 与 openai 兼容两种格式;zhipu 开 JSON 模式。"""
    p = providers[provider_name]
    base_url = p["baseUrl"].rstrip("/")
    api_key = p["apiKey"]
    api_type = p.get("api", "openai")

    last_err = None
    for i in range(retries + 1):
        try:
            if "anthropic" in api_type:
                url = f"{base_url}/v1/messages"
                headers = {"x-api-key": api_key,
                           "anthropic-version": "2023-06-01",
                           "content-type": "application/json"}
                payload = {"model": model, "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": prompt}]}
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
                r.raise_for_status()
                # anthropic 兼容(如百炼 token-plan)可能先返回 thinking 块,
                # text 在后续块,拼接所有 type=text 的块
                blocks = r.json().get("content", [])
                texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                if texts:
                    return "".join(texts)
                return blocks[0].get("text", "") if blocks else ""
            url = f"{base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}",
                       "Content-Type": "application/json"}
            payload = {"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            print(f"    [LLM retry {i+1}/{retries+1}] {e}")
            time.sleep(3)
    raise last_err


def parse_json(text):
    """容错解析 LLM JSON(去代码块,截取最外层 {} 或 [])。"""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    text = text.strip()
    for l, r in (("{", "}"), ("[", "]")):
        s, e = text.find(l), text.rfind(r)
        if s >= 0 and e > s:
            return json.loads(text[s:e + 1])
    raise ValueError("no JSON found in LLM output")


def load_word_families():
    """返回 (families, words_map)。
    families: 词族原始列表(按 priority 排好序)
    words_map: {en_lower: {..., family_id, family_zh, family_index, word_index, host, draw_note}}
    """
    with open(WORDLISTS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    families = sorted(data["families"], key=lambda x: x["priority"])
    words_map = {}
    for fi, fam in enumerate(families):
        for wi, w in enumerate(fam["words"]):
            words_map[w["en"].lower()] = {
                **w,
                "family_id": fam["id"],
                "family_zh": fam["zh"],
                "family_index": fi,
                "word_index": wi,
                "host": fam.get("host", ""),
                "draw_note": fam.get("draw_note", ""),
            }
    return families, words_map


def flatten_words():
    """按排产顺序展平全部词:[word_info,...],并赋全局 word_id(wc_001...)。"""
    families, words_map = load_word_families()
    out = []
    n = 0
    for fam in families:
        for wi, w in enumerate(fam["words"]):
            n += 1
            info = dict(words_map[w["en"].lower()])
            info["word_id"] = f"wc_{n:03d}"
            info["family_size"] = len(fam["words"])
            out.append(info)
    return out


def banned_terms(cfg=None):
    cfg = cfg or load_config()
    return [t.lower() for t in cfg.get("compliance", {}).get("banned_terms", [])]


def check_compliance(text, cfg=None):
    """返回命中的违规词列表(小写匹配)。"""
    low = text.lower()
    return [t for t in banned_terms(cfg) if t in low]


def bl_image(prompt, out_dir, prefix, size="3:4", negative_prompt=None,
             seed=None, timeout=240):
    """调百炼 bl image generate,返回首个匹配文件路径或 None。
    - --watermark false:默认加水印,做无文字原图必须关
    - --prompt-extend false:锁定我们的画风骨架,不让模型扩写跑偏
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["bl", "image", "generate",
           "--prompt", prompt,
           "--size", size,
           "--watermark", "false",
           "--prompt-extend", "false",
           "--out-dir", str(out_dir),
           "--out-prefix", prefix,
           "--quiet"]
    if negative_prompt:
        cmd += ["--negative-prompt", negative_prompt]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        files = list(out_dir.glob(f"{prefix}*.png")) + \
                list(out_dir.glob(f"{prefix}*.jpg")) + \
                list(out_dir.glob(f"{prefix}*.jpeg"))
        if files:
            return str(max(files, key=lambda p: p.stat().st_mtime))
        print(f"    [IMG WARN] 无文件输出: {r.stdout[-200:]} {r.stderr[-200:]}")
    except Exception as e:
        print(f"    [IMG FAIL] {e}")
    return None


def load_json(path, default):
    path = Path(path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
