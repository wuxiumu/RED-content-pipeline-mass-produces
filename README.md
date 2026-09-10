# AI 蜡笔英语启蒙单词卡 · 小红书内容生产流水线

> 一条「市场研究 → 台词分镜 → AI 生图 → 九页卡排版 → 发帖文案」的全自动化内容工厂：为 2–6 岁英语启蒙账号批量产出**原创蜡笔风拟人单词卡**（每个单词 4 张 AI 原图 + 9 页 1080×1440 小红书卡片 + 一键复制的标题正文标签）。Python + LLM + 阿里云百炼文生图 + Pillow + PHP 看板，**系统永远不自动发帖**，所有 IP 形象均为 AI 原创。

**English:** An end-to-end Xiaohongshu (RED) content pipeline that mass-produces original crayon-style English vocabulary flashcards for toddler English-learning accounts (ages 2–6): keyword research → bilingual scripts & storyboards → Bailian/Qwen text-to-image (4 raw illustrations per word with a stable seed) → Pillow 9-page card composition → ready-to-post copy. A zero-frame PHP + static HTML dashboard reviews everything; nothing is auto-published.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![PHP](https://img.shields.io/badge/PHP-7.4%2B-777BB4)](https://www.php.net/)
[![Content](https://img.shields.io/badge/Ready%20posts-20-success)]()
[![Cards](https://img.shields.io/badge/Card%20pages-180-orange)]()

---

## 这是什么（30 秒概览）

- **10 个词族 / 100 个启蒙单词**：水果、动物、食物、交通工具等词族在 [word_families.yaml](assets/wordlists/word_families.yaml) 中声明（milk/bread/corn/cheese 已标不可数名词）
- **一个单词 = 一套完整物料**：4 句中英双语台词 + 4 个分镜 + 音标 + 亲子互动话术 → 4 张 AI 蜡笔原图 → 9 页成品卡 → 1 篇带 8 个标签的发帖文案
- **画风一致性工程**：固定蜡笔画风骨架 prompt + 词族主体插槽 + 同词 md5 稳定 seed；`--watermark false --prompt-extend false` 锁死风格；负面词独立参数传入
- **逐字一致性校验**：execute 阶段校验正文 4 句台词必须与卡面逐字一致，缺句自动重试
- **断点续跑**：`scripted.json → images → cards → produced.json` 全程文件状态机，任意一步失败重跑同一命令即可续上（已验证：文生图接口超时后断点重跑零废片）
- **合规优先**：只用 AI 原创拟人形象，知名 IP（佩奇等）仅用于竞品研究、绝不进自产素材；不生成站外导流话术

## 成品长什么样（九页卡结构）

| 页码 | 内容 |
|---|---|
| P1 | 封面：词族系列 +「XX 英语启蒙」+ 年龄/编号胶囊 |
| P2–P5 | 4 张分镜台词页：AI 蜡笔原图 + 英文句 + 中文翻译（如 *This is a grape. 这是一个葡萄。*）|
| P6 | 单词页：单词 + IPA 音标（含 ɡ/ɪ 等特殊字符字体兜底）|
| P7 | 亲子互动页：生活场景跟读话术 |
| P8 | 合集页：词族追更进度（只按真实排卡文件判定，不虚标）|
| P9 | CTA 页：合规的资源领取表述 |

## 流水线（6 步，对应三智能体）

```
01 收集  expand_keywords.py / scrape_xhs.py   种子词 → 长尾词 → 小红书爆款样本
02 判断  judge.py                              评分排优先级 → judged.json 选题队列
03a     build_scripts.py    LLM 生成台词/分镜/音标/互动话术 → scripted.json
03b     gen_images.py       bl image generate 每词 4 张蜡笔原图（稳定 seed，断点续跑）
03c     compose_cards.py    Pillow 把原图排成 1080×1440 九页卡
03d     execute.py          LLM 写标题/正文/8 标签，台词逐字校验 → produced.json
                ↓
        index.html + api.php 本地内容工坊（人工复制发布，系统不发帖）
```

## 目录结构

```
_plan_ai_img/
├── index.html              # 马卡龙风看板：作品墙/九页详情/一键复制文案/生产漏斗/源码
├── api.php                 # 只读 JSON API + 图片白名单代理（单文件）
├── collect_config.yaml     # 赛道/词族/LLM provider 与兜底模型（不含密钥）
├── assets/
│   ├── style/base_style.txt    # 固定蜡笔画风 prompt 骨架（【SUBJECT】插槽）
│   ├── style/negative.txt      # 负面词
│   └── wordlists/word_families.yaml  # 10 词族 100 词
├── scripts/
│   ├── common_llm.py       # LLM/生图公共封装（OpenAI 兼容 + anthropic thinking 块兼容）
│   ├── expand_keywords.py / scrape_xhs.py / judge.py   # 01–02 收集与判断
│   ├── build_scripts.py    # 03a 台词分镜
│   ├── gen_images.py       # 03b 批量生图
│   ├── compose_cards.py    # 03c 九页卡排版
│   └── execute.py          # 03d 发帖文案
└── data/                   # JSON 状态入库；images/ 体积大已 gitignore
    ├── scripted.json  judged.json  produced.json
    └── images/{word_id}/raw_1..4.png + cards/01..09.png（跑脚本生成）
```

## 快速开始

### 1. 环境依赖

```bash
python3 -m pip install pyyaml requests pillow playwright
playwright install chromium        # 仅市场研究抓取需要
# 文生图需要阿里云百炼 CLI：bl（bl skill init 完成鉴权）
# 看板需要本地 PHP（macOS 自带或 brew install php）
```

### 2. 配置 LLM Provider

密钥不写进项目，统一放 `~/.openclaw/openclaw.json`，项目配置只引用 provider 名：

```json
{
  "models": {
    "providers": {
      "zhipu": { "apiKey": "你的智谱Key", "baseUrl": "https://open.bigmodel.cn/api/paas/v4" }
    }
  }
}
```

### 3. 跑完整流水线

```bash
cd scripts
python3 expand_keywords.py          # 01 词库（也可直接用 assets/wordlists 的固定词族）
python3 judge.py                    # 02 选题队列
python3 build_scripts.py            # 03a 台词/分镜/音标（可 --word apple 跑单词）
python3 gen_images.py               # 03b 每词 4 张原图（断点续跑，约 25 秒/张）
python3 compose_cards.py            # 03c 九页卡（纯本地，零费用）
python3 execute.py                  # 03d 发帖文案
```

### 4. 打开本地内容工坊

```bash
php -S 127.0.0.1:8080
# 浏览器打开 http://127.0.0.1:8080/index.html
```

看板能力：按合集筛选/搜索作品 → 详情弹窗按 P1–P9 检查卡片 → 一键复制「完整发帖文案 / 仅标题 / 仅正文」→ 查看 4 张 AI 原图留档 → 生产漏斗（队列→台词→原图→九页卡→成品）→ 在线查看脚本源码。

## API 一览（api.php，全部只读）

| Action | 说明 |
|---|---|
| `?action=stats` | 成品数、合集分布、生产漏斗 |
| `?action=list` | 成品列表（封面/词族色标/待发布状态） |
| `?action=post&id=wc_004` | 成品详情，合并台词/音标/分镜/互动话术 |
| `?action=flow` | 6 步流水线元数据与反馈闭环 |
| `?action=scripts` / `?action=script&name=execute.py` | 白名单脚本源码查看 |
| `?action=image&path=data/images/...` | 图片代理，realpath 限定 data/images，防目录穿越 |

## 工程细节（踩坑沉淀）

- **文生图参数**：尺寸 `3:4`；必须显式关水印与 prompt 扩写；负面词走独立 `--negative-prompt`
- **IPA 音标豆腐块**：圆润字体缺 ɡ(U+0261)/ɪ(U+026A)，排版时对音标段回退 Arial Unicode 等全字符字体，并用私用区像素签名检测 .notdef 字形
- **主模型空返回兜底**：智谱对营销类 prompt 偶发空字符串（内容策略，非报错），execute 自动切百炼 token-plan / qwen3.8-max；anthropic 兼容分支拼接所有 text 块（跳过 thinking 块）
- **合集页防虚标**：「已更新 x/y」必须检测 `cards/01.png` 与 `09.png` 真实存在，总数实时取词表长度
- **不可数名词**：yaml 标记 `uncountable: true`，台词模板自动用 *This is ~.* 而非 *a/an*

## 设计原则

1. **人在环路**：终点永远是本地待发布物料，不调任何平台发布接口
2. **原创合规**：AI 原创角色 + 无水印 + 无文字原图；第三方 IP 只研究不使用
3. **确定性与 LLM 分工**：评分/排版/校验用代码，创意生成用 LLM
4. **文件即数据库**：JSON 中间产物可读可 diff，失败可续跑
5. **密钥与仓库分离**：仓库内零 API Key

## 技术栈

Python 3.9+ · 智谱 GLM-5.3/Flash + 百炼 qwen3.8-max 兜底 · 阿里云百炼 `bl image generate`（qwen-image）· Pillow · Playwright（研究阶段）· PHP 7.4+ 内置 server · 原生 HTML/CSS/JS 马卡龙单页

## 常见问题（FAQ）

**Q：这套流水线会自动发小红书吗？**
不会。系统只产出本地图片与文案，看板提供一键复制，发布动作、发布时间完全由人决定。

**Q：生成的角色会不会侵权（比如长得像佩奇）？**
所有形象由固定原创蜡笔 prompt + 稳定 seed 生成，词表与画风文件不含任何第三方 IP 名称；知名 IP 只在市场研究环节出现。上线前仍建议人工目检。

**Q：跑一轮多少钱 / 多久？**
只有 03b 文生图付费：每词 4 张，实测约 25 秒/张（19 词 76 张约 30 分钟）；03a/03d 是文本调用，成本很低；03c Pillow 排版纯本地免费。

**Q：生图中途接口超时怎么办？**
直接重跑 `python3 gen_images.py [--word xxx]`，已存在的 raw 图自动跳过；单词 4 张出齐才会把状态置为 images_done。

**Q：能换词表/换画风吗？**
能。词族改 `assets/wordlists/word_families.yaml`（支持 family/slot/uncountable），画风改 `assets/style/base_style.txt` 的固定骨架与 `negative.txt`。

**Q：没有图片看板是空的？**
生成产物（80 张原图 + 180 张卡片约 800MB）未纳入 git，跑完 03b/03c 后自动展示。

## License

MIT。生成内容请自行遵守各平台规则与当地法律；本仓库不含任何第三方平台素材与 IP 形象。
