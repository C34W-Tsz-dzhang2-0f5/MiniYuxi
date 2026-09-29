/* ================================================================
   MiniYuxi · 流程画布（Dify 风格可视化编排）
   - 左侧节点面板 / 中间 SVG 连线画布（平移·缩放·拖拽连线）/ 右侧属性面板
   - 后端：/api/flow/save|list|{id}|delete（flow_store.py，additive）
   - 复用工作台 token：localStorage.miniyuxi_token
   - 红线：仅新增前端页面，不触碰 core 红线文件
   ================================================================ */
(function () {
  'use strict';

  var NODE_W = 184, NODE_H = 60;

  var NODE_TYPES = {
    start:     { label: '开始',       color: 'var(--start)', fields: [] },
    llm:       { label: 'LLM 推理',   color: 'var(--llm)',   fields: [
                  { key: 'system', label: '系统提示词', type: 'textarea', ph: '你是 MiniYuxi…' },
                  { key: 'model',  label: '模型（可选）', type: 'input', ph: '留空用默认' } ] },
    tool:      { label: '工具调用',   color: 'var(--tool)',  fields: [
                  { key: 'tool', label: '工具名', type: 'input', ph: '如 web_search' },
                  { key: 'args', label: '参数(JSON/文本)', type: 'textarea', ph: '{}' } ] },
    condition: { label: '条件分支',   color: 'var(--cond)',  fields: [
                  { key: 'expression', label: '条件表达式', type: 'input', ph: '如 score > 60' } ] },
    human:     { label: '人工审批',   color: 'var(--human)', fields: [
                  { key: 'approval_prompt', label: '审批提示', type: 'textarea', ph: '请 HR 确认…' } ] },
    knowledge: { label: '知识检索',   color: 'var(--know)',  fields: [
                  { key: 'query', label: '检索问句', type: 'input', ph: '…' },
                  { key: 'top_k', label: 'Top-K', type: 'input', ph: '5' } ] },
    flowref:   { label: '引用现有流程', color: 'var(--end)', fields: [
                  { key: 'flow_id', label: '流程 ID', type: 'input', ph: '如 recruit' },
                  { key: 'note',    label: '备注', type: 'input', ph: '' } ] },
    end:       { label: '结束',       color: 'var(--end)',  fields: [] }
  };

  var state = {
    nodes: [], edges: [], selected: null,
    view: { x: 80, y: 80, scale: 1 },
    connecting: null,  // {from, x, y}
    currentId: '', currentName: '未命名流程'
  };

  var $ = function (s) { return document.querySelector(s); };
  var viewport = $('#viewport'), edgeLayer = $('#edgeLayer'), nodeLayer = $('#nodeLayer'), stage = $('#stage');

  /* ---------------- token / api ---------------- */
  function token() { try { return localStorage.getItem('miniyuxi_token') || ''; } catch (e) { return ''; } }
  function api(path, opts) {
    opts = opts || {};
    var h = { 'Content-Type': 'application/json' };
    var t = token(); if (t) h['Authorization'] = 'Bearer ' + t;
    return fetch(path, Object.assign({ headers: h }, opts)).then(function (r) {
      if (r.status === 401) throw new Error('未登录或登录失效（请先在工作台登录）');
      return r;
    });
  }
  function toast(msg) {
    var t = $('#toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.classList.remove('show'); }, 2200);
  }
  function setStatus(s) { $('#status').textContent = s || ''; }

  /* ---------------- 坐标变换 ---------------- */
  function applyView() {
    viewport.style.transform = 'translate(' + state.view.x + 'px,' + state.view.y + 'px) scale(' + state.view.scale + ')';
  }
  function toWorld(clientX, clientY) {
    var r = stage.getBoundingClientRect();
    return { x: (clientX - r.left - state.view.x) / state.view.scale,
             y: (clientY - r.top - state.view.y) / state.view.scale };
  }

  /* ---------------- 节点操作 ---------------- */
  function uid(p) { return (p || 'n') + '_' + Math.random().toString(36).slice(2, 8); }
  function addNode(type, x, y) {
    var t = NODE_TYPES[type]; if (!t) return;
    var n = { id: uid(type), type: type, x: x, y: y, title: t.label, props: {} };
    t.fields.forEach(function (f) { n.props[f.key] = ''; });
    if (type === 'flowref') n.props.flow_id = 'recruit';
    state.nodes.push(n);
    render(); select(n.id);
  }
  function nodeById(id) { return state.nodes.filter(function (n) { return n.id === id; })[0]; }
  function deleteNode(id) {
    state.nodes = state.nodes.filter(function (n) { return n.id !== id; });
    state.edges = state.edges.filter(function (e) { return e.from !== id && e.to !== id; });
    if (state.selected === id) state.selected = null;
    render(); renderProps();
  }
  function addEdge(from, to) {
    if (from === to) return;
    if (state.edges.some(function (e) { return e.from === from && e.to === to; })) return;
    state.edges.push({ id: uid('e'), from: from, to: to });
    render();
  }

  /* ---------------- 渲染 ---------------- */
  function nodeSummary(n) {
    var t = NODE_TYPES[n.type];
    if (!t.fields.length) return n.type === 'start' ? '流程起点' : '流程终点';
    var f = t.fields[0]; var v = (n.props[f.key] || '').toString().trim();
    return v ? (v.length > 22 ? v.slice(0, 22) + '…' : v) : '（未配置）';
  }
  function render() {
    nodeLayer.innerHTML = '';
    state.nodes.forEach(function (n) {
      var el = document.createElement('div');
      el.className = 'node' + (state.selected === n.id ? ' selected' : '');
      el.style.left = n.x + 'px'; el.style.top = n.y + 'px';
      el.dataset.nid = n.id;
      var col = NODE_TYPES[n.type].color;
      el.innerHTML =
        '<div class="nh"><span class="dot" style="background:' + col + '"></span>' + NODE_TYPES[n.type].label + '</div>' +
        '<div class="nt">' + escapeHtml(n.title || NODE_TYPES[n.type].label) + '</div>' +
        '<div class="badge">' + escapeHtml(nodeSummary(n)) + '</div>' +
        '<div class="port in" data-nid="' + n.id + '"></div>' +
        '<div class="port out" data-nid="' + n.id + '"></div>';
      nodeLayer.appendChild(el);
      n._h = el.offsetHeight || NODE_H;
      bindNode(el, n);
    });
    renderEdges();
  }
  function renderEdges() {
    var svg = '';
    state.edges.forEach(function (e) {
      var a = nodeById(e.from), b = nodeById(e.to); if (!a || !b) return;
      var x1 = a.x + NODE_W, y1 = a.y + (a._h || NODE_H) / 2;
      var x2 = b.x, y2 = b.y + (b._h || NODE_H) / 2;
      var dx = Math.max(40, Math.abs(x2 - x1) / 2);
      svg += '<path d="M' + x1 + ' ' + y1 + ' C' + (x1 + dx) + ' ' + y1 + ',' + (x2 - dx) + ' ' + y2 + ',' + x2 + ' ' + y2 +
             '" fill="none" stroke="#94a3b8" stroke-width="2"/>';
    });
    if (state.connecting) {
      var a2 = nodeById(state.connecting.from);
      if (a2) {
        var x1 = a2.x + NODE_W, y1 = a2.y + (a2._h || NODE_H) / 2;
        svg += '<path d="M' + x1 + ' ' + y1 + ' L' + state.connecting.x + ' ' + state.connecting.y +
               '" fill="none" stroke="#3370ff" stroke-width="2" stroke-dasharray="5 4"/>';
      }
    }
    edgeLayer.innerHTML = svg;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  /* ---------------- 交互：拖拽节点 / 平移 / 缩放 / 连线 ---------------- */
  function bindNode(el, n) {
    var portOut = el.querySelector('.port.out'), portIn = el.querySelector('.port.in');
    el.addEventListener('mousedown', function (e) {
      if (e.target.classList.contains('port')) return;  // 端口单独处理
      e.preventDefault(); select(n.id);
      var w = toWorld(e.clientX, e.clientY);
      var ox = w.x - n.x, oy = w.y - n.y;
      function move(ev) { var p = toWorld(ev.clientX, ev.clientY); n.x = p.x - ox; n.y = p.y - oy; render(); }
      function up() { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
    });
    el.addEventListener('dblclick', function (e) { e.preventDefault(); deleteNode(n.id); });
    portOut.addEventListener('mousedown', function (e) {
      e.preventDefault(); e.stopPropagation();
      state.connecting = { from: n.id, x: n.x + NODE_W, y: n.y + (n._h || NODE_H) / 2 };
      function move(ev) { var p = toWorld(ev.clientX, ev.clientY); state.connecting.x = p.x; state.connecting.y = p.y; renderEdges(); }
      function up(ev) {
        document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up);
        var tgt = ev.target;
        if (tgt.classList && tgt.classList.contains('port') && tgt.classList.contains('in')) {
          addEdge(state.connecting.from, tgt.dataset.nid);
        }
        state.connecting = null; renderEdges();
      }
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
    });
  }
  // 画布平移
  stage.addEventListener('mousedown', function (e) {
    if (e.target !== stage && e.target !== viewport && e.target.id !== 'edges' && e.target.id !== 'edgeLayer') return;
    var sx = state.view.x, sy = state.view.y;
    var mx = e.clientX, my = e.clientY;
    function move(ev) { state.view.x = sx + (ev.clientX - mx); state.view.y = sy + (ev.clientY - my); applyView(); }
    function up() { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
    document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
  });
  stage.addEventListener('wheel', function (e) {
    e.preventDefault();
    var r = stage.getBoundingClientRect();
    var cx = e.clientX - r.left, cy = e.clientY - r.top;
    var wx = (cx - state.view.x) / state.view.scale, wy = (cy - state.view.y) / state.view.scale;
    var k = e.deltaY < 0 ? 1.1 : 0.9;
    state.view.scale = Math.min(2.5, Math.max(0.3, state.view.scale * k));
    state.view.x = cx - wx * state.view.scale; state.view.y = cy - wy * state.view.scale;
    applyView();
  }, { passive: false });

  function select(id) { state.selected = id; render(); renderProps(); }

  /* ---------------- 属性面板 ---------------- */
  function renderProps() {
    var box = $('#props'); var n = nodeById(state.selected);
    if (!n) { box.innerHTML = '<div class="empty-hint">未选中节点。<br/>从左侧面板添加节点，或在画布中点击选中。</div>'; return; }
    var t = NODE_TYPES[n.type];
    var html = '<div class="field"><label>节点类型</label><div style="font-weight:600">' + t.label + '</div></div>';
    html += '<div class="field"><label>标题</label><input id="p_title" value="' + escapeHtml(n.title || '') + '"/></div>';
    t.fields.forEach(function (f) {
      var val = n.props[f.key] || '';
      html += '<div class="field"><label>' + f.label + '</label>';
      if (f.type === 'textarea')
        html += '<textarea id="p_' + f.key + '" placeholder="' + escapeHtml(f.ph || '') + '">' + escapeHtml(val) + '</textarea>';
      else
        html += '<input id="p_' + f.key + '" placeholder="' + escapeHtml(f.ph || '') + '" value="' + escapeHtml(val) + '"/>';
      html += '</div>';
    });
    html += '<button class="tb-btn" id="p_del" style="width:100%;color:#e11d48;border-color:#fecdd3">删除该节点</button>';
    box.innerHTML = html;
    $('#p_title').addEventListener('input', function (e) { n.title = e.target.value; render(); });
    t.fields.forEach(function (f) {
      $('#p_' + f.key).addEventListener('input', function (e) { n.props[f.key] = e.target.value; render(); });
    });
    $('#p_del').addEventListener('click', function () { deleteNode(n.id); });
  }

  /* ---------------- 工具栏 ---------------- */
  function buildPalette() {
    var p = $('#palette'); p.innerHTML = '';
    Object.keys(NODE_TYPES).forEach(function (type) {
      var t = NODE_TYPES[type];
      var el = document.createElement('div'); el.className = 'palette-item';
      el.innerHTML = '<span class="dot" style="background:' + t.color + '"></span><span class="lab">' + t.label + '</span>';
      el.addEventListener('click', function () {
        var c = toWorld(stage.getBoundingClientRect().left + stage.clientWidth / 2,
                        stage.getBoundingClientRect().top + stage.clientHeight / 2);
        addNode(type, c.x - NODE_W / 2 + (Math.random() * 40 - 20), c.y - NODE_H / 2 + (Math.random() * 40 - 20));
      });
      p.appendChild(el);
    });
  }
  function toDefinition() {
    return {
      meta: { name: state.currentName, id: state.currentId },
      nodes: state.nodes.map(function (n) { return { id: n.id, type: n.type, x: Math.round(n.x), y: Math.round(n.y), title: n.title, props: n.props }; }),
      edges: state.edges.map(function (e) { return { id: e.id, from: e.from, to: e.to }; })
    };
  }
  function fromDefinition(def) {
    if (!def) return;
    state.currentId = (def.meta && def.meta.id) || '';
    state.currentName = (def.meta && def.meta.name) || '未命名流程';
    state.nodes = (def.nodes || []).map(function (n) {
      var t = NODE_TYPES[n.type] ? n.type : 'llm';
      var nn = { id: n.id, type: t, x: n.x || 0, y: n.y || 0, title: n.title || NODE_TYPES[t].label, props: n.props || {} };
      NODE_TYPES[t].fields.forEach(function (f) { if (!(f.key in nn.props)) nn.props[f.key] = ''; });
      return nn;
    });
    state.edges = (def.edges || []).filter(function (e) { return nodeById(e.from) && nodeById(e.to); })
      .map(function (e) { return { id: e.id || uid('e'), from: e.from, to: e.to }; });
    state.selected = null; render(); renderProps();
  }
  function fitView() {
    if (!state.nodes.length) { state.view = { x: 80, y: 80, scale: 1 }; applyView(); return; }
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    state.nodes.forEach(function (n) { minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + NODE_W); maxY = Math.max(maxY, n.y + (n._h || NODE_H)); });
    var pad = 60, rw = stage.clientWidth, rh = stage.clientHeight;
    var sx = (rw - pad * 2) / (maxX - minX || 1), sy = (rh - pad * 2) / (maxY - minY || 1);
    state.view.scale = Math.min(1.2, Math.max(0.3, Math.min(sx, sy)));
    state.view.x = pad - minX * state.view.scale + (rw - pad * 2 - (maxX - minX) * state.view.scale) / 2;
    state.view.y = pad - minY * state.view.scale + (rh - pad * 2 - (maxY - minY) * state.view.scale) / 2;
    applyView();
  }
  function save() {
    var name = window.prompt('流程名称：', state.currentName);
    if (name === null) return;
    state.currentName = name || '未命名流程';
    var def = toDefinition(); def.meta.name = state.currentName;
    api('/api/flow/save', { method: 'POST', body: JSON.stringify({ id: state.currentId, name: state.currentName, definition: def }) })
      .then(function (r) { return r.json(); }).then(function (d) {
        state.currentId = d.id; setStatus('已保存：' + d.id); toast('保存成功');
      }).catch(function (e) { toast('保存失败：' + e.message); });
  }
  function loadList() {
    api('/api/flow/list').then(function (r) { return r.json(); }).then(function (d) {
      var flows = d.flows || [];
      if (!flows.length) { toast('暂无已保存流程'); return; }
      var sel = window.prompt('已保存流程（输入 id 载入）：\n' + flows.map(function (f) { return f.id + '  ' + f.name; }).join('\n'), flows[0].id);
      if (!sel) return;
      api('/api/flow/' + encodeURIComponent(sel)).then(function (r) { return r.json(); }).then(function (f) {
        if (f.detail) { toast('未找到：' + sel); return; }
        fromDefinition(f.definition); state.currentId = f.id; state.currentName = f.name || '未命名';
        setStatus('已载入：' + f.id); toast('载入成功'); fitView();
      }).catch(function (e) { toast('载入失败：' + e.message); });
    }).catch(function (e) { toast('列表失败：' + e.message); });
  }
  function exportJSON() {
    var def = toDefinition();
    var blob = new Blob([JSON.stringify(def, null, 2)], { type: 'application/json' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = (state.currentName || 'flow') + '.json'; a.click();
    toast('已导出 JSON');
  }
  function importJSON() {
    var inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'application/json';
    inp.onchange = function () {
      var f = inp.files[0]; if (!f) return;
      var rd = new FileReader(); rd.onload = function () { try { fromDefinition(JSON.parse(rd.result)); toast('导入成功'); fitView(); } catch (e) { toast('JSON 解析失败'); } };
      rd.readAsText(f);
    };
    inp.click();
  }
  function importExistingFlows() {
    api('/api/agent/flows').then(function (r) { return r.json(); }).then(function (d) {
      var map = d.flows || d;  // 兼容数组 / 对象
      var keys = Array.isArray(map) ? map.map(function (x) { return x.id; }) : Object.keys(map);
      if (!keys.length) { toast('无现有流程'); return; }
      keys.forEach(function (k, i) {
        var meta = Array.isArray(map) ? map[i] : map[k];
        var n = { id: uid('flowref'), type: 'flowref', x: 80 + i * 60, y: 80 + i * 40,
          title: '引用·' + k, props: { flow_id: k, note: ((meta && meta.stages) ? (meta.stages + ' 阶段') : '') } };
        state.nodes.push(n);
      });
      render(); toast('已加入 ' + keys.length + ' 个现有流程引用节点');
    }).catch(function (e) { toast('导入失败：' + e.message); });
  }

  /* ---------------- 绑定 ---------------- */
  $('#btnNew').addEventListener('click', function () { state.nodes = []; state.edges = []; state.selected = null; state.currentId = ''; state.currentName = '未命名流程'; render(); renderProps(); setStatus(''); });
  $('#btnSave').addEventListener('click', save);
  $('#btnLoad').addEventListener('click', loadList);
  $('#btnExport').addEventListener('click', exportJSON);
  $('#btnImport').addEventListener('click', importJSON);
  $('#btnImportFlow').addEventListener('click', importExistingFlows);
  $('#btnFit').addEventListener('click', fitView);

  buildPalette(); applyView(); render(); renderProps();
  setStatus(token() ? '已登录' : '未检测到登录态（保存/载入需先在工作台登录）');
})();
