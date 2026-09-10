<?php
/**
 * AI蜡笔英语启蒙 · 小红书内容工坊 - 只读 API
 * 提供:成品列表/详情(合并台词音标)/脚本源码/流程漏斗/图片代理/统计
 * 所有数据从 data/ 目录读,不写任何文件。
 */
declare(strict_types=1);

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);
header('X-Content-Type-Options: nosniff');

if (!function_exists('str_starts_with')) {
    function str_starts_with(string $haystack, string $needle): bool {
        return $needle !== '' && substr($haystack, 0, strlen($needle)) === $needle;
    }
}

define('PLAN_DIR', __DIR__);
define('DATA_DIR', PLAN_DIR . '/data');
define('PRODUCED_PATH', DATA_DIR . '/produced.json');
define('SCRIPTED_PATH', DATA_DIR . '/scripted.json');
define('JUDGED_PATH', DATA_DIR . '/judged.json');

$action = $_GET['action'] ?? '';
$id     = $_GET['id'] ?? '';
$name   = $_GET['name'] ?? '';
$path   = $_GET['path'] ?? '';

// 安全白名单:只允许查看这些源码
$ALLOWED_SCRIPTS = [
    'expand_keywords.py'  => PLAN_DIR . '/scripts/expand_keywords.py',
    'scrape_xhs.py'       => PLAN_DIR . '/scripts/scrape_xhs.py',
    'judge.py'            => PLAN_DIR . '/scripts/judge.py',
    'build_scripts.py'    => PLAN_DIR . '/scripts/build_scripts.py',
    'gen_images.py'       => PLAN_DIR . '/scripts/gen_images.py',
    'compose_cards.py'    => PLAN_DIR . '/scripts/compose_cards.py',
    'execute.py'          => PLAN_DIR . '/scripts/execute.py',
    'common_llm.py'       => PLAN_DIR . '/scripts/common_llm.py',
    'collect_config.yaml' => PLAN_DIR . '/collect_config.yaml',
];

// ============ 路由 ============
switch ($action) {
    case 'list':    echo_json(list_posts()); break;
    case 'post':    echo_json(get_post($id)); break;
    case 'scripts': echo_json(list_scripts($ALLOWED_SCRIPTS)); break;
    case 'script':  echo_json(get_script($name, $ALLOWED_SCRIPTS)); break;
    case 'flow':    echo_json(get_flow()); break;
    case 'image':   serve_image($path); break;
    case 'stats':   echo_json(get_stats()); break;
    default:
        http_response_code(400);
        echo_json(['error' => 'unknown action', 'available' => [
            'list', 'post', 'scripts', 'script', 'flow', 'image', 'stats'
        ]]);
}

// ============ 业务函数 ============

function img_url(string $rel): string {
    return 'api.php?action=image&path=' . urlencode($rel);
}

function find_scripted_word(string $id): ?array {
    $data = load_json(SCRIPTED_PATH);
    foreach ($data['words'] ?? [] as $w) {
        if (($w['word_id'] ?? '') === $id) return $w;
    }
    return null;
}

function list_posts(): array {
    $data = load_json(PRODUCED_PATH);
    $posts = [];
    foreach ($data['posts'] ?? [] as $p) {
        $paths = $p['image_paths'] ?? [];
        $posts[] = [
            'topic_id'      => $p['topic_id'] ?? '',
            'track'         => $p['track'] ?? '',
            'status'        => $p['status'] ?? '',
            'word_en'       => $p['word_en'] ?? '',
            'word_zh'       => $p['word_zh'] ?? '',
            'collection'    => $p['collection'] ?? '',
            'title'         => $p['title'] ?? '',
            'tags'          => $p['tags'] ?? [],
            'image_count'   => count($paths),
            'raw_count'     => count($p['raw_image_paths'] ?? []),
            'cover_url'     => $paths ? img_url($paths[0]) : '',
            'post_time_hint'=> $p['post_time_hint'] ?? '',
            'note_url'      => $p['note_url'] ?? '',
            'body_len'      => mb_strlen($p['body'] ?? ''),
        ];
    }
    return ['total' => count($posts), 'posts' => $posts];
}

function get_post(string $id): array {
    $data = load_json(PRODUCED_PATH);
    foreach ($data['posts'] ?? [] as $p) {
        if (($p['topic_id'] ?? '') !== $id) continue;

        $p['image_urls'] = array_map('img_url', $p['image_paths'] ?? []);
        $p['raw_image_urls'] = array_map('img_url', $p['raw_image_paths'] ?? []);

        // 关联 scripted.json:音标 / 四句台词 / 分镜 / 亲子互动 / 代表色
        $w = find_scripted_word($id);
        if ($w) {
            $p['word_detail'] = [
                'word_id'     => $w['word_id'],
                'en'          => $w['en'],
                'zh'          => $w['zh'],
                'phonetic'    => $w['phonetic'] ?? '',
                'color'       => $w['color'] ?? '',
                'family_zh'   => $w['family_zh'] ?? '',
                'family_index'=> $w['family_index'] ?? 0,
                'lines'       => $w['lines'] ?? [],
                'scenes'      => $w['scenes'] ?? [],
                'interaction' => $w['interaction'] ?? '',
            ];
        }
        return ['post' => $p];
    }
    http_response_code(404);
    return ['error' => 'post not found', 'id' => $id];
}

function list_scripts(array $allowed): array {
    $scripts = [];
    foreach ($allowed as $name => $path) {
        $scripts[] = [
            'name'  => $name,
            'size'  => is_file($path) ? filesize($path) : 0,
            'mtime' => is_file($path) ? filemtime($path) : 0,
        ];
    }
    return ['scripts' => $scripts];
}

function get_script(string $name, array $allowed): array {
    if (!isset($allowed[$name])) {
        http_response_code(404);
        return ['error' => 'script not allowed or not found', 'name' => $name];
    }
    $path = $allowed[$name];
    if (!is_file($path)) {
        http_response_code(404);
        return ['error' => 'file not exists', 'name' => $name];
    }
    $content = file_get_contents($path);
    return ['name' => $name, 'content' => $content, 'size' => strlen($content)];
}

function get_flow(): array {
    $judged    = load_json(JUDGED_PATH);
    $scripted  = load_json(SCRIPTED_PATH);
    $produced  = load_json(PRODUCED_PATH);

    $queue_len = 0;
    foreach ($judged['tracks'] ?? [] as $t) {
        $queue_len += count($t['queue'] ?? []);
    }

    // 执行阶段各状态在库词数
    $stage = ['scripted' => 0, 'images_done' => 0, 'cards_done' => 0, 'ready' => 0];
    foreach ($scripted['words'] ?? [] as $w) {
        $st = $w['status'] ?? 'scripted';
        if (isset($stage[$st])) $stage[$st]++;
    }
    $posts_n = count($produced['posts'] ?? []);

    return [
        'steps' => [
            [
                'id' => '01',
                'name' => '收集智能体 Collector',
                'script' => 'expand_keywords.py + scrape_xhs.py',
                'config' => 'collect_config.yaml',
                'input'  => '三轨种子词(单词卡/视频/资源)',
                'output' => 'collected.json',
                'stats'  => ['note' => '需扫码跑 scrape_xhs.py 后有样本'],
                'purpose' => '关键词 LLM 扩展 + 小红书搜索结果抓取(登录态保存),只做市场研究,知名 IP 词绝不进自产内容',
            ],
            [
                'id' => '02',
                'name' => '判断智能体 Judge',
                'script' => 'judge.py',
                'input'  => 'collected.json(无样本时走词族冷启动)',
                'output' => 'judged.json',
                'stats'  => ['排产队列' => $queue_len],
                'purpose' => '按认知顺序与视觉可画性给词族排产,水果/动物先行,抽象词族(颜色/数字)靠后',
            ],
            [
                'id' => '03a',
                'name' => '执行① 台词分镜 build_scripts',
                'script' => 'scripts/build_scripts.py',
                'input'  => 'judged.json 队列 + word_families.yaml',
                'output' => 'scripted.json',
                'stats'  => ['已产台词' => $stage['scripted'] + $stage['images_done']
                            + $stage['cards_done'] + $stage['ready']],
                'purpose' => '每词 4 句磨耳朵台词(命名/特征/颜色/喜好)+ 音标 + 4 条无文字分镜 + 亲子互动;不可数名词硬校验',
            ],
            [
                'id' => '03b',
                'name' => '执行② 蜡笔原图 gen_images',
                'script' => 'scripts/gen_images.py (百炼 bl image)',
                'input'  => 'scripted.json + assets/style 画风骨架',
                'output' => 'data/images/{id}/raw_1..4.png',
                'stats'  => ['images_done' => $stage['images_done'] + $stage['cards_done'] + $stage['ready']],
                'purpose' => '固定蜡笔画风骨架 + 主体插槽,3:4、关水印、关 prompt 扩写,同词 4 张共用稳定 seed',
            ],
            [
                'id' => '03c',
                'name' => '执行③ 九页卡 compose_cards',
                'script' => 'scripts/compose_cards.py (Pillow)',
                'input'  => 'raw_1..4.png + 台词',
                'output' => 'data/images/{id}/cards/01..09.png',
                'stats'  => ['cards_done' => $stage['cards_done'] + $stage['ready']],
                'purpose' => '封面大字 + 4 句跟读卡 + 单词音标页 + 亲子互动 + 合集进度 + 扣1福利页;文字全部后期叠加,AI 图零文字',
            ],
            [
                'id' => '03d',
                'name' => '执行④ 发帖物料 execute',
                'script' => 'scripts/execute.py',
                'input'  => '九页卡 + 台词',
                'output' => 'produced.json (不自动发布)',
                'stats'  => ['ready 成品' => $posts_n],
                'purpose' => '5 个封面标题候选自评 + 正文(台词逐字一致)+ 8 标签 + 发布时段,选定标题重渲染封面;智谱空返回自动切百炼',
            ],
        ],
        'feedback_loop' => '发布后回收点赞/收藏/扣1数到 feedback.json,02 判断智能体给收藏率与扣1数高权重,高收藏词族自动扩量',
    ];
}

function get_stats(): array {
    $produced = load_json(PRODUCED_PATH);
    $scripted = load_json(SCRIPTED_PATH);
    $judged   = load_json(JUDGED_PATH);

    $stats = [
        'total'        => 0,
        'by_collection'=> [],
        'total_cards'  => 0,
        'total_raws'   => 0,
    ];
    foreach ($produced['posts'] ?? [] as $p) {
        $stats['total']++;
        $c = $p['collection'] ?? '未分组';
        $stats['by_collection'][$c] = ($stats['by_collection'][$c] ?? 0) + 1;
        $stats['total_cards'] += count($p['image_paths'] ?? []);
        $stats['total_raws']  += count($p['raw_image_paths'] ?? []);
    }

    // 生产漏斗:队列 → 台词 → 原图 → 九页卡 → 成品
    $funnel = ['queued' => 0, 'scripted' => 0, 'images_done' => 0,
               'cards_done' => 0, 'ready' => 0];
    foreach ($judged['tracks'] ?? [] as $t) {
        $funnel['queued'] += count($t['queue'] ?? []);
    }
    foreach ($scripted['words'] ?? [] as $w) {
        $st = $w['status'] ?? 'scripted';
        if (array_key_exists($st, $funnel)) $funnel[$st]++;
    }
    $stats['funnel'] = $funnel;
    return $stats;
}

function serve_image(string $path) {
    // 只允许 data/images 下的图片(raw 原图与 cards 成品卡)
    if ($path === '') { http_response_code(400); echo 'empty path'; return; }
    $real = realpath(PLAN_DIR . '/' . ltrim($path, '/'));
    $images_root = realpath(DATA_DIR . '/images');
    if (!$real || !$images_root || !str_starts_with($real, $images_root)) {
        http_response_code(403);
        echo 'forbidden path';
        return;
    }
    if (!is_file($real)) {
        http_response_code(404);
        echo 'image not found';
        return;
    }
    $ext = strtolower(pathinfo($real, PATHINFO_EXTENSION));
    $types = ['png' => 'image/png', 'jpg' => 'image/jpeg',
              'jpeg' => 'image/jpeg', 'gif' => 'image/gif', 'webp' => 'image/webp'];
    if (!isset($types[$ext])) {
        http_response_code(400);
        echo 'bad type';
        return;
    }
    header('Content-Type: ' . $types[$ext]);
    header('Content-Length: ' . filesize($real));
    header('Cache-Control: public, max-age=86400');
    readfile($real);
}

// ============ 工具 ============

function load_json(string $path): array {
    if (!is_file($path)) return [];
    $d = json_decode(file_get_contents($path), true);
    return is_array($d) ? $d : [];
}

function echo_json($data) {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
}
