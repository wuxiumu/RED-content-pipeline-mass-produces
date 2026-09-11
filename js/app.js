const API = 'api.php';
let POSTS = [], SCRIPTS = [], STATS = {}, CURRENT_POST = null;

// 词族配色
const COL_COLORS = {
  '水果系列':'#ff9f43','动物系列':'#6bbf59','食物系列':'#f4b942','交通工具系列':'#4ea8e8',
  '身体部位系列':'#a78bfa','颜色系列':'#ec6aa0','数字系列':'#34bfa3','天气系列':'#5dade2',
  '家人系列':'#f07892','自然系列':'#7cb342'
};
const colColor = c => COL_COLORS[c] || '#8b7bf0';

// ============ Tab ============
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    if (!t.dataset.view) return;
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.view').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('view-' + t.dataset.view).classList.add('active');
    if (t.dataset.view === 'flow' && !document.getElementById('flow-content').innerHTML) loadFlow();
  });
});

// ============ 统计 ============
fetch(API + '?action=stats').then(r => r.json()).then(d => {
  STATS = d;
  const by = d.by_collection || {};
  const f = d.funnel || {};
  document.getElementById('stats').innerHTML = `
    <span>成品 <b>${d.total}</b></span>
    ${Object.entries(by).map(([k,v]) => `<span style="color:${colColor(k)}">${k.replace('系列','')} <b>${v}</b></span>`).join('')}
    <span>九页卡 <b>${d.total_cards}</b></span>
    <span>AI原图 <b>${d.total_raws}</b></span>
    <span style="color:#46b981">台词库 <b>${(f.scripted||0)+(f.images_done||0)+(f.cards_done||0)+(f.ready||0)}</b></span>
  `;
  document.getElementById('count-posts').textContent = d.total;
});

// ============ 列表 ============
async function loadPosts() {
  const d = await (await fetch(API + '?action=list')).json();
  POSTS = d.posts || [];
  // 动态合集筛选按钮
  const cols = [...new Set(POSTS.map(p => p.collection).filter(Boolean))];
  document.getElementById('collection-filters').innerHTML = cols.map(c =>
    `<button class="filter-btn" data-col="${esc(c)}" style="border-color:${colColor(c)}55;color:${colColor(c)}">${esc(c)}</button>`
  ).join('');
  document.querySelectorAll('.filter-btn[data-col]').forEach(b =>
    b.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderPosts();
    }));
  renderPosts();
}

function renderPosts() {
  const col = document.querySelector('.filter-btn.active')?.dataset.col || '';
  const q = document.getElementById('search').value.toLowerCase().trim();
  const list = POSTS.filter(p => {
    if (col && p.collection !== col) return false;
    if (q) {
      const hay = [p.title, p.word_en, p.word_zh, (p.tags||[]).join(' '), p.collection].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  document.getElementById('post-empty').style.display = list.length ? 'none' : 'block';
  document.getElementById('post-grid').innerHTML = list.map(p => {
    const cc = colColor(p.collection);
    const cover = p.cover_url
      ? `<img src="${p.cover_url}" loading="lazy" onerror="this.parentNode.innerHTML='<div class=&quot;thumb-fallback&quot;>🍇</div>'">`
      : `<div class="thumb-fallback">🍇</div>`;
    return `
    <div class="post-card" onclick="loadDetail('${p.topic_id}')">
      <div class="thumb">
        ${cover}
        <span class="track-tag" style="background:${cc}">${esc(p.collection || '单词卡')}</span>
        <span class="status-tag">${p.note_url ? '已发布' : '待发布'}</span>
      </div>
      <div class="body">
        <div class="word-row">
          <span class="word-en">${esc(p.word_en)}</span>
          <span class="word-zh">${esc(p.word_zh)}</span>
        </div>
        <div class="title">${esc(p.title)}</div>
        <div class="meta">
          <span class="chip">📷 ${p.image_count}页</span>
          <span class="chip">🕐 ${esc(p.post_time_hint || '')}</span>
          ${(p.tags||[]).slice(0,2).map(t => `<span class="chip tag">${esc(t)}</span>`).join('')}
        </div>
      </div>
    </div>`;
  }).join('');
}
document.getElementById('search').addEventListener('input', renderPosts);

// ============ 详情 ============
async function loadDetail(id) {
  const d = await (await fetch(API + `?action=post&id=${encodeURIComponent(id)}`)).json();
  const p = d.post;
  if (!p) return;
  CURRENT_POST = p;
  const cc = colColor(p.collection);
  const wd = p.word_detail || null;

  const cards = (p.image_urls || []).map((u, i) => `
    <div class="pg" onclick="window.open('${u}')">
      <img src="${u}" loading="lazy"><span class="pg-no">P${i+1}</span>
    </div>`).join('');
  const raws = (p.raw_image_urls || []).map((u, i) =>
    `<img src="${u}" loading="lazy" title="AI 原图 raw_${i+1}" onclick="window.open('${u}')">`).join('');

  const wordPanel = wd ? `
    <div class="detail-section">
      <h3>🎓 单词学习内容</h3>
      <div class="word-panel">
        <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
          <span style="font-size:26px;font-weight:800;font-family:Georgia,serif;color:#4a3f38">${esc(wd.en)}</span>
          <span class="phonetic">${esc(wd.phonetic)}</span>
          <span style="color:var(--muted);font-size:14px">${esc(wd.zh)}${wd.color ? ' · '+esc(wd.color) : ''}</span>
        </div>
        <div class="line-list">
          ${(wd.lines||[]).map((l,i) => `
            <div class="line-item">
              <span class="idx">${i+1}</span>
              <span class="en">${esc(l.en)}</span>
              <span class="zh">${esc(l.zh)}</span>
            </div>`).join('')}
        </div>
        <div class="interact-box">👩‍👧 <b>亲子互动:</b>${esc(wd.interaction)}</div>
        <details class="scene-list">
          <summary>查看 4 条 AI 分镜描述</summary>
          <ol>${(wd.scenes||[]).map(s => `<li>${esc(s)}</li>`).join('')}</ol>
        </details>
      </div>
    </div>` : '';

  document.getElementById('detail-modal').innerHTML = `
    <div class="detail-header">
      <button class="detail-close" onclick="closeDetail()">×</button>
      <div class="detail-title">${esc(p.title)}</div>
      <div class="detail-sub">
        <span class="word-big">${esc(p.word_en)}</span><span>${esc(p.word_zh)}</span>
        <span class="track-tag" style="position:static;background:${cc}">${esc(p.collection)}</span>
        <span>🕐 建议 ${esc(p.post_time_hint)}</span>
        <span>${p.note_url ? '✅ 已发布' : '🟡 待发布（本系统不会自动发帖）'}</span>
      </div>
      <div class="detail-tags">${(p.tags||[]).map(t => `<span class="tag">#${esc(t)}</span>`).join('')}</div>
    </div>
    <div class="detail-body">
      <div class="detail-section">
        <h3>📝 发帖文案</h3>
        <div class="copy-row">
          <button class="copy-btn" onclick="copyPost('full', this)">⧉ 复制完整发帖文案（标题+正文+标签）</button>
          <button class="copy-btn ghost" onclick="copyPost('title', this)">仅复制标题</button>
          <button class="copy-btn ghost" onclick="copyPost('body', this)">仅复制正文</button>
        </div>
        <div class="detail-body-text">${esc(p.body)}</div>
      </div>
      <div class="detail-section">
        <h3>📑 九页成品卡（发布按此顺序上传，共 ${(p.image_urls||[]).length} 张）</h3>
        <div class="card-strip">${cards}</div>
      </div>
      ${wordPanel}
      ${raws ? `<div class="detail-section">
        <h3>🎨 AI 无文字原图（4 张，留档/视频轨复用）</h3>
        <div class="raw-grid">${raws}</div>
      </div>` : ''}
    </div>`;
  document.getElementById('detail-overlay').classList.add('show');
}

function copyPost(kind, btn) {
  const p = CURRENT_POST;
  if (!p) return;
  const tagLine = (p.tags || []).map(t => '#' + t).join(' ');
  const text = kind === 'title' ? p.title
             : kind === 'body'  ? p.body
             : `${p.title}\n\n${p.body}\n\n${tagLine}`;
  const done = () => {
    const old = btn.textContent;
    btn.textContent = '✓ 已复制，去小红书粘贴即可';
    btn.classList.add('ok');
    setTimeout(() => { btn.textContent = old; btn.classList.remove('ok'); }, 1800);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch(e) { showToast('复制失败，请手动选择文本'); }
  document.body.removeChild(ta);
}

function closeDetail(){ document.getElementById('detail-overlay').classList.remove('show'); }
document.getElementById('detail-overlay').addEventListener('click', e => {
  if (e.target.id === 'detail-overlay') closeDetail();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

// ============ 流程 ============
async function loadFlow() {
  const d = await (await fetch(API + '?action=flow')).json();
  const f = (STATS.funnel || {});
  const funnelHtml = `
    <div class="funnel-bar">
      <div class="fb"><div class="n">${f.queued||0}</div><div class="l">排产队列</div></div>
      <div class="fb"><div class="n">${(f.scripted||0)+(f.images_done||0)+(f.cards_done||0)+(f.ready||0)}</div><div class="l">台词分镜</div></div>
      <div class="fb"><div class="n">${(f.images_done||0)+(f.cards_done||0)+(f.ready||0)}</div><div class="l">AI 原图出齐</div></div>
      <div class="fb"><div class="n">${(f.cards_done||0)+(f.ready||0)}</div><div class="l">九页卡排完</div></div>
      <div class="fb"><div class="n">${f.ready||0}</div><div class="l">待发布成品</div></div>
    </div>`;
  document.getElementById('flow-content').innerHTML = (d.steps || []).map((s, i, arr) => `
    <div class="flow-step">
      <div class="flow-num">${s.id}</div>
      <div class="flow-step-content">
        <h3>${s.name}</h3>
        <div>脚本 <span class="script">${s.script || ''}</span></div>
        <div class="meta-row">
          <span>输入: <b>${s.input || ''}</b></span>
          <span>输出: <b>${s.output || ''}</b></span>
        </div>
        <div class="stats-row">${Object.entries(s.stats || {}).map(([k,v]) =>
          `<span class="stat-pill">${esc(k)}: ${esc(String(v))}</span>`).join('')}</div>
        <div class="purpose">${esc(s.purpose || '')}</div>
      </div>
    </div>
    ${i < arr.length - 1 ? '<div class="flow-arrow">↓</div>' : ''}
  `).join('') + funnelHtml + `
    <div style="margin-top:22px;padding:15px 18px;background:#fff7e8;border-radius:12px;color:#92600e;font-size:13px;line-height:1.7">
      <b>🔁 反馈闭环:</b> ${esc(d.feedback_loop || '')}<br>
      <b>🔒 合规红线:</b> 只发 AI 原创蜡笔形象与自制资源，绝不使用小猪佩奇等第三方 IP；不在正文/图片留微信号或外链；包装为 0-6 岁素质启蒙，避开“课程/培训/教材”词。
    </div>`;
}

// ============ 源代码 ============
let CURRENT_CODE = '';

async function openCodeViewer() {
  document.getElementById('code-overlay').classList.add('show');
  if (!SCRIPTS.length) await loadScripts();
}
function closeCodeViewer() {
  document.getElementById('code-overlay').classList.remove('show');
}
document.getElementById('code-overlay').addEventListener('click', e => {
  if (e.target.id === 'code-overlay') closeCodeViewer();
});
async function loadScripts() {
  const d = await (await fetch(API + '?action=scripts')).json();
  SCRIPTS = d.scripts || [];
  document.getElementById('script-list').innerHTML = SCRIPTS.map((s, i) => `
    <div class="script-item ${i === 0 ? 'active' : ''}" onclick="loadScript('${s.name}', this)">
      ${s.name}<span class="size">${(s.size/1024).toFixed(1)}K</span>
    </div>`).join('');
  if (SCRIPTS[0]) loadScript(SCRIPTS[0].name);
}
async function loadScript(name, el) {
  document.querySelectorAll('.script-item').forEach(x => x.classList.remove('active'));
  if (el) el.classList.add('active');
  const d = await (await fetch(API + `?action=script&name=${encodeURIComponent(name)}`)).json();
  document.getElementById('code-file').textContent = name + ' · ' + (d.size || 0) + ' bytes';
  const lines = (d.content || '').split('\n');
  CURRENT_CODE = lines.join('\n');
  document.getElementById('code-table').innerHTML = lines.map((l, i) =>
    `<tr><td>${i + 1}</td><td>${esc(l)}</td></tr>`
  ).join('');
  document.getElementById('code-copy-btn').textContent = '复制代码';
  document.getElementById('code-copy-btn').classList.remove('copied');
}
async function copyCode() {
  const btn = document.getElementById('code-copy-btn');
  try {
    await navigator.clipboard.writeText(CURRENT_CODE);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = CURRENT_CODE;
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  }
  btn.textContent = '✓ 已复制';
  btn.classList.add('copied');
  setTimeout(() => { btn.textContent = '复制代码'; btn.classList.remove('copied'); }, 2000);
}

// ============ 工具 ============
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1800);
}

loadPosts();
