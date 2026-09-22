/* MiniYuxi 桌面启动壳 —— 无构建步骤，纯静态。
   Tauri 侧通过 withGlobalTauri 暴露 window.__TAURI__，这里只用来：
     1) 接收内核日志（sidecar://log）与状态（sidecar://status / sidecar://exit）；
     2) 手动重启内核 / 打开数据目录。
   内核就绪后 Rust 会把窗口导航到 http://127.0.0.1:<port>，本页随即被替换。
*/
const $ = (id) => document.getElementById(id);
const TAURI = typeof window !== 'undefined' ? window.__TAURI__ : null;

const dot = $('dot');
const phase = $('phase');
const bar = $('bar');
const logEl = $('log');
const logWrap = $('logWrap');

function setPhase(text, kind = 'run') {
  phase.textContent = text;
  dot.className = 'dot ' + kind;
  bar.style.width = kind === 'ok' ? '100%' : kind === 'err' ? '100%' : '60%';
  if (kind === 'err') bar.classList.add('err');
}

let lines = [];
function pushLog(text) {
  if (!text) return;
  lines.push(text.replace(/\s+$/, ''));
  if (lines.length > 300) lines = lines.slice(-300);
  logEl.textContent = lines.join('\n');
  logWrap.hidden = false;
  logEl.scrollTop = logEl.scrollHeight;
}

async function invoke(cmd, args) {
  if (!TAURI || !TAURI.core) throw new Error('当前不在 Tauri 外壳中运行');
  return TAURI.core.invoke(cmd, args);
}

async function listen(evt, cb) {
  if (!TAURI || !TAURI.event) return () => {};
  return TAURI.event.listen(evt, cb);
}

(async function boot() {
  if (!TAURI) {
    setPhase('浏览器直开：请用 npm run dev 启动桌面外壳', 'err');
    $('btnRestart').disabled = true;
    $('btnData').disabled = true;
    return;
  }

  await listen('sidecar://status', (e) => {
    const p = e.payload || {};
    if (p.url) setPhase(`内核就绪（${p.url}），正在进入工作台…`, 'ok');
    else if (p.phase) setPhase(p.phase, p.kind || 'run');
  });

  await listen('sidecar://log', (e) => pushLog((e.payload || {}).line || ''));

  await listen('sidecar://exit', (e) => {
    const p = e.payload || {};
    setPhase(`内核已退出（code=${p.code ?? '?'}，signal=${p.signal ?? '?'}）`, 'err');
  });

  // 兜底：若 20s 后还没被导航走，说明内核没起来，展开日志给用户看
  setTimeout(() => {
    if (!document.hidden && phase.textContent.startsWith('正在启动')) {
      setPhase('内核启动超时，请查看日志或重启内核', 'err');
      logWrap.hidden = false;
    }
  }, 20000);

  $('btnRestart').onclick = async () => {
    setPhase('正在重启内核…', 'run');
    try {
      await invoke('restart_sidecar');
    } catch (e) {
      setPhase('重启失败：' + e, 'err');
    }
  };

  $('btnData').onclick = async () => {
    try {
      const p = await invoke('open_data_dir');
      pushLog('打开数据目录：' + p);
    } catch (e) {
      pushLog('打开失败：' + e);
    }
  };

  try {
    const info = await invoke('sidecar_status');
    $('meta').textContent = info
      ? `内核 ${info.url} · 端口 ${info.port}`
      : '内核未运行';
    if (info) setPhase(`内核已就绪（${info.url}），正在进入工作台…`, 'ok');
  } catch (e) {
    $('meta').textContent = String(e);
  }
})();
