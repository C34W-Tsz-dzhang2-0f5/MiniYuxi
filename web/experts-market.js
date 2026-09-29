/* ================================================================
   MiniYuxi · 专家市场前端（域15）
   - 消费 /api/experts/manifest（experts_manifest.build_manifest）
   - 卡片网格 + 分类筛选 + 关键词搜索 + 详情抽屉
   - 复用工作台 token：localStorage.miniyuxi_token
   - 红线：仅新增前端页面，不触碰 core 红线文件
   ================================================================ */
(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var state = { experts: [], cats: [], filter: 'all', q: '' };

  function token() { try { return localStorage.getItem('miniyuxi_token') || ''; } catch (e) { return ''; } }
  function api(path) {
    var h = {}; var t = token(); if (t) h['Authorization'] = 'Bearer ' + t;
    return fetch(path, { headers: h }).then(function (r) {
      if (r.status === 401) throw new Error('未登录或登录失效（请先在工作台登录）');
      return r.json();
    });
  }
  function toast(m) { var t = $('#toast'); t.textContent = m; t.classList.add('show'); setTimeout(function () { t.classList.remove('show'); }, 2200); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function load() {
    api('/api/experts/manifest').then(function (d) {
      state.experts = d.experts || []; state.cats = d.categories || [];
      setStatus('共 ' + state.experts.length + ' 个专家 · ' + (state.cats.length) + ' 类');
      renderCats(); renderGrid();
    }).catch(function (e) { toast('加载失败：' + e.message); setStatus('加载失败'); });
  }
  function setStatus(s) { $('#status').textContent = s || (token() ? '已登录' : '未检测到登录态'); }

  function renderCats() {
    var html = '<span class="chip' + (state.filter === 'all' ? ' active' : '') + '" data-c="all">全部</span>';
    state.cats.forEach(function (c) {
      html += '<span class="chip' + (state.filter === c.category ? ' active' : '') + '" data-c="' + esc(c.category) + '">' +
        esc(c.category) + ' (' + c.count + ')</span>';
    });
    $('#cats').innerHTML = html;
    Array.prototype.forEach.call($('#cats').querySelectorAll('.chip'), function (el) {
      el.addEventListener('click', function () { state.filter = el.dataset.c; renderCats(); renderGrid(); });
    });
  }

  function visible() {
    var q = state.q.trim().toLowerCase();
    return state.experts.filter(function (e) {
      if (state.filter !== 'all' && e.category !== state.filter) return false;
      if (!q) return true;
      return (e.name + ' ' + e.display_name + ' ' + e.description + ' ' + (e.tags || []).join(' ') + ' ' + e.category).toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderGrid() {
    var list = visible();
    if (!list.length) { $('#grid').innerHTML = '<div class="empty">没有匹配的专家。</div>'; return; }
    $('#grid').innerHTML = list.map(function (e) {
      var tags = (e.tags || []).slice(0, 4).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('');
      return '<div class="card" data-id="' + esc(e.id) + '">' +
        '<div class="top"><span class="ic">' + (e.icon || '🧩') + '</span><span class="nm">' + esc(e.display_name || e.name) + '</span>' +
        '<span class="ver">v' + esc(e.version) + '</span></div>' +
        '<div class="desc">' + esc(e.description || '（暂无描述）') + '</div>' +
        '<span class="badge b-cat">' + esc(e.category) + '</span>' +
        '<span class="badge b-risk-' + esc(e.risk) + '">风险 ' + esc(e.risk) + '</span>' +
        '<div>' + tags + '</div></div>';
    }).join('');
    Array.prototype.forEach.call($('#grid').querySelectorAll('.card'), function (el) {
      el.addEventListener('click', function () { openDetail(el.dataset.id); });
    });
  }

  function openDetail(id) {
    var e = state.experts.filter(function (x) { return x.id === id; })[0]; if (!e) return;
    $('#dBody').innerHTML =
      '<div style="font-size:30px">' + (e.icon || '🧩') + '</div>' +
      '<h3>' + esc(e.display_name || e.name) + '</h3>' +
      '<div class="row"><span class="k">ID / 版本</span>' + esc(e.id) + ' · v' + esc(e.version) + '</div>' +
      '<div class="row"><span class="k">分类</span><span class="badge b-cat">' + esc(e.category) + '</span> <span class="badge b-risk-' + esc(e.risk) + '">风险 ' + esc(e.risk) + '</span></div>' +
      '<div class="row"><span class="k">能力说明</span>' + esc(e.description || '（暂无）') + '</div>' +
      '<div class="row"><span class="k">触发场景</span>' + (e.trigger ? esc(e.trigger) : '（未声明，按需调用）') + '</div>' +
      '<div class="row"><span class="k">允许工具</span>' + ((e.allowed_tools && e.allowed_tools.length) ? e.allowed_tools.map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('') : '（默认 []）') + '</div>' +
      '<div class="row"><span class="k">标签</span>' + ((e.tags && e.tags.length) ? e.tags.map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('') : '（无）') + '</div>' +
      '<div class="row"><span class="k">授权</span>' + esc(e.license) + '</div>' +
      '<div class="row"><span class="k">入口文件</span><code>' + esc(e.entrypoint) + '</code></div>';
    $('#detail').classList.add('open');
  }

  $('#search').addEventListener('input', function (e) { state.q = e.target.value; renderGrid(); });
  $('#dClose').addEventListener('click', function () { $('#detail').classList.remove('open'); });

  load();
})();
