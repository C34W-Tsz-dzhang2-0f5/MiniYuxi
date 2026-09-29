/* =====================================================================
 *  MiniYuxi 办公操作面（Office Surface）· Univer 宿主
 *  ------------------------------------------------------------------
 *  职责：懒加载 Univer 离线包 → 挂载全屏编辑器 → 与 /api/office/* 互通存档。
 *
 *  合规红线（与后端一致）：
 *    - 快照只经 /api/office/* 写入本机 SQLite，不触达任何外部服务；
 *    - 资产（univer.bundle.js / .css）全部由本机 /vendor/univer/ 提供，
 *      不存在时不回退 CDN（后端未构建时返回 503），离线可用。
 *
 *  用法（由 wb_workbench.js 调用）：
 *    MiniYuxiOffice.open();            // 打开办公套件（默认表格）
 *    MiniYuxiOffice.open('doc');       // 打开并切到文档
 *
 *  依赖：window.UniverOffice（由 tools/office-bundle 打包产出）
 * ===================================================================== */
(function (global) {
  'use strict';

  var BUNDLE_JS = '/vendor/univer/univer.bundle.js';
  var BUNDLE_CSS = '/vendor/univer/univer.bundle.css';
  // 公式引擎 Worker。**必须传**：preset 工厂里是 `notExecuteFormula: !!workerURL`，
  // 不传就等于显式关掉公式执行 —— HR 表格里 SUM/AVG 填了不出结果。
  var WORKER_JS = '/vendor/univer/univer.worker.js';
  var HOST_CSS = '/office/office-host.css';
  var CONTAINER_ID = 'mxofUniverContainer';

  var api = null;          // FUniver 实例
  var univer = null;       // Univer 实例
  var overlay = null;      // 全屏容器 DOM
  var curKind = 'sheet';   // sheet | doc
  var curId = '';          // 当前文档 doc_id（空 = 未保存）
  var dirty = false;
  var listPanel = null;

  /* ---------------- 基础工具 ---------------- */
  function tok() {
    try { return localStorage.getItem('miniyuxi_token') || ''; } catch (e) { return ''; }
  }

  function req(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = 'Bearer ' + tok();
    if (opts.body && typeof opts.body === 'object') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
        return d;
      });
    });
  }

  function loadScriptOnce(src) {
    if (document.querySelector('script[data-mxof="' + src + '"]')) return Promise.resolve();
    return new Promise(function (res, rej) {
      var s = document.createElement('script');
      s.src = src; s.async = false; s.setAttribute('data-mxof', src);
      s.onload = res;
      s.onerror = function () { rej(new Error('加载失败：' + src)); };
      document.head.appendChild(s);
    });
  }

  function loadCssOnce(href) {
    if (document.querySelector('link[data-mxof="' + href + '"]')) return;
    var l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = href; l.setAttribute('data-mxof', href);
    document.head.appendChild(l);
  }

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function status(msg, isErr) {
    var s = document.getElementById('mxofStatus');
    if (!s) return;
    s.textContent = msg || '';
    s.className = 'mxof-status' + (isErr ? ' is-err' : '');
    if (msg) {
      clearTimeout(s._t);
      s._t = setTimeout(function () { s.textContent = ''; }, 4000);
    }
  }

  /* ---------------- 懒加载 Univer ---------------- */
  function ensureUniver() {
    if (global.UniverOffice) return Promise.resolve(global.UniverOffice);
    status('正在加载办公内核…');
    return loadScriptOnce(BUNDLE_JS).then(function () {
      if (!global.UniverOffice) throw new Error('办公内核未就绪（bundle 未导出 UniverOffice）');
      return global.UniverOffice;
    });
  }

  /* ---------------- 挂载编辑器 ---------------- */
  function mountEditor() {
    return ensureUniver().then(function (U) {
      loadCssOnce(BUNDLE_CSS);
      var host = document.getElementById(CONTAINER_ID);
      if (!host) throw new Error('容器不存在');
      host.innerHTML = '';

      var inst = U.createUniver({
        locale: U.LocaleType.ZH_CN,
        locales: (function () {
          var m = {};
          m[U.LocaleType.ZH_CN] = U.mergeLocales(U.sheetsLocale, U.docsLocale);
          return m;
        })(),
        presets: [
          // workerURL 是"打开公式执行"的开关（见顶部注释），不是可选优化项
          U.UniverSheetsCorePreset({ container: host, workerURL: WORKER_JS }),
          U.UniverDocsCorePreset({ container: host })
        ]
      });
      univer = inst.univer;
      api = inst.univerAPI;
      newUnit(curKind);
      status('就绪');
    }).catch(function (e) {
      var host = document.getElementById(CONTAINER_ID);
      if (host) host.innerHTML = '<div class="mxof-error">办公内核加载失败：' +
        String(e && e.message || e).replace(/</g, '&lt;') +
        '<br><small>若为「资产未构建」，请执行：cd tools/office-bundle &amp;&amp; npm install &amp;&amp; npm run build</small></div>';
      status('加载失败', true);
    });
  }

  function newUnit(kind, data) {
    if (!api) return;
    // 复用同一容器：先卸掉已有单元（sheet 与 doc 都试一次，
    // 否则从表格切到文档时旧 workbook 仍占着 active，getActiveDocument() 取不到新单元）
    try {
      var w = api.getActiveWorkbook();
      if (w && w.getId && w.getId()) api.disposeUnit(w.getId());
    } catch (e) { /* 无单元时忽略 */ }
    try {
      var d = api.getActiveDocument();
      if (d && d.getId && d.getId()) api.disposeUnit(d.getId());
    } catch (e) { /* 无单元时忽略 */ }

    var id, displayName;
    if (data) {
      // 加载存档：保留数据本体，只补齐 id / name / title
      id = data.id || data.doc_id || (kind + '-' + Date.now());
      displayName = data.name || data.title || (kind === 'sheet' ? '未命名表格' : '未命名文档');
    } else {
      // 新建单元（doNew / 切换类型时）：清空 doc_id 与名称输入，避免上一份污染
      curId = '';
      id = kind + '-' + Date.now();
      displayName = (kind === 'sheet') ? '未命名表格' : '未命名文档';
    }
    var seed = (kind === 'sheet')
      ? Object.assign({}, data || {}, { id: id, name: displayName })
      : Object.assign({}, data || {}, { id: id, title: displayName });
    if (kind === 'sheet') {
      api.createWorkbook(seed);
    } else {
      api.createDocument(seed);
    }
    curKind = kind;
    dirty = false;
    var nameEl = document.getElementById('mxofName');
    if (nameEl) nameEl.value = displayName;
    syncTabs();
    updateBar();
  }

  function switchKind(kind) {
    if (kind === curKind) return;
    if (dirty && !confirm('当前文档有未保存的修改，切换会丢失。是否继续？')) return;
    newUnit(kind);
  }

  function snapshot() {
    if (!api) return null;
    try {
      if (curKind === 'sheet') {
        var wb = api.getActiveWorkbook();
        return wb ? wb.save() : null;
      }
      var doc = api.getActiveDocument();
      return doc ? doc.save() : null;
    } catch (e) { return null; }
  }

  /* ---------------- 存档交互 ---------------- */
  function doSave() {
    if (!tok()) { status('请先登录', true); return; }
    var data = snapshot();
    if (!data) { status('没有可保存的内容', true); return; }
    var nameEl = document.getElementById('mxofName');
    var name = (nameEl && nameEl.value.trim()) ||
      ((curKind === 'sheet' ? data.name : data.title) || (curKind === 'sheet' ? '未命名表格' : '未命名文档'));
    status('保存中…');
    req('/api/office/save', {
      method: 'POST',
      body: { data: data, kind: curKind, name: name, doc_id: curId }
    }).then(function (d) {
      curId = d.doc_id || curId;
      dirty = false;
      updateBar();
      status('已保存 · ' + (d.doc_id || ''));
    }).catch(function (e) { status('保存失败：' + e.message, true); });
  }

  function doNew() {
    if (dirty && !confirm('当前文档有未保存的修改，新建会丢失。是否继续？')) return;
    curId = '';
    var nameEl = document.getElementById('mxofName');
    if (nameEl) nameEl.value = curKind === 'sheet' ? '未命名表格' : '未命名文档';
    newUnit(curKind);
    status('已新建');
  }

  function toggleList() {
    if (listPanel) { closeList(); return; }
    if (!tok()) { status('请先登录', true); return; }
    req('/api/office/list').then(function (d) {
      var docs = d.docs || [];
      listPanel = el('div', 'mxof-list');
      if (!docs.length) {
        listPanel.appendChild(el('div', 'mxof-list-empty', '暂无存档'));
      } else {
        docs.forEach(function (it) {
          var row = el('div', 'mxof-list-row');
          var meta = el('div', 'mxof-list-meta');
          meta.appendChild(el('span', 'mxof-kind', it.kind === 'sheet' ? '表格' : '文档'));
          meta.appendChild(el('span', 'mxof-list-name', it.name));
          meta.appendChild(el('span', 'mxof-list-time', it.updated_at || ''));
          row.appendChild(meta);
          var del = el('button', 'mxof-list-del', '删除');
          del.onclick = function (ev) {
            ev.stopPropagation();
            if (!confirm('确认删除「' + it.name + '」？')) return;
            req('/api/office/' + encodeURIComponent(it.doc_id), { method: 'DELETE' })
              .then(function () { closeList(); toggleList(); status('已删除'); })
              .catch(function (e) { status('删除失败：' + e.message, true); });
          };
          row.appendChild(del);
          row.onclick = function () { loadDoc(it.doc_id); };
          listPanel.appendChild(row);
        });
      }
      document.getElementById(CONTAINER_ID).parentNode.appendChild(listPanel);
    }).catch(function (e) { status('读取列表失败：' + e.message, true); });
  }

  function closeList() {
    if (listPanel && listPanel.parentNode) listPanel.parentNode.removeChild(listPanel);
    listPanel = null;
  }

  function loadDoc(docId) {
    closeList();
    status('打开中…');
    req('/api/office/' + encodeURIComponent(docId)).then(function (d) {
      curId = d.doc_id;
      newUnit(d.kind || 'sheet', d.data || {});
      var nameEl = document.getElementById('mxofName');
      if (nameEl) nameEl.value = d.name || '';
      status('已打开');
    }).catch(function (e) { status('打开失败：' + e.message, true); });
  }

  /* ---------------- 界面骨架 ---------------- */
  function syncTabs() {
    var tabs = document.querySelectorAll('#mxofTabs button');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].className = 'mxof-tab' + (tabs[i].getAttribute('data-kind') === curKind ? ' is-on' : '');
    }
  }

  function updateBar() {
    var badge = document.getElementById('mxofBadge');
    if (badge) badge.textContent = curId ? ('已存档 · ' + curId) : '未保存';
    var saveBtn = document.getElementById('mxofSave');
    if (saveBtn) saveBtn.disabled = false;
  }

  function buildOverlay() {
    overlay = el('div', 'mxof-overlay');
    overlay.id = 'mxofOverlay';
    // 明暗主题跟随主界面（wb_theme：'dark' | 'light'）
    try { overlay.setAttribute('data-theme', localStorage.getItem('wb_theme') || 'light'); } catch (e) {}

    var bar = el('div', 'mxof-bar');
    var tabs = el('div', 'mxof-tabs');
    tabs.id = 'mxofTabs';
    [['sheet', '表格'], ['doc', '文档']].forEach(function (p) {
      var b = el('button', 'mxof-tab', p[1]);
      b.setAttribute('data-kind', p[0]);
      b.onclick = function () { switchKind(p[0]); };
      tabs.appendChild(b);
    });
    bar.appendChild(tabs);

    var nameIn = el('input', 'mxof-name');
    nameIn.id = 'mxofName';
    nameIn.placeholder = '文档名称';
    nameIn.value = '未命名表格';
    nameIn.oninput = function () { dirty = true; };
    bar.appendChild(nameIn);

    var badge = el('span', 'mxof-badge', '未保存');
    badge.id = 'mxofBadge';
    bar.appendChild(badge);

    var st = el('span', 'mxof-status');
    st.id = 'mxofStatus';
    bar.appendChild(st);

    var acts = el('div', 'mxof-acts');
    var bNew = el('button', 'mxof-btn', '新建'); bNew.id = 'mxofNew'; bNew.onclick = doNew;
    var bOpen = el('button', 'mxof-btn', '打开'); bOpen.id = 'mxofOpen'; bOpen.onclick = toggleList;
    var bSave = el('button', 'mxof-btn is-primary', '保存'); bSave.id = 'mxofSave'; bSave.onclick = doSave;
    var bClose = el('button', 'mxof-btn', '关闭'); bClose.id = 'mxofClose'; bClose.onclick = close;
    acts.appendChild(bNew); acts.appendChild(bOpen); acts.appendChild(bSave); acts.appendChild(bClose);
    bar.appendChild(acts);
    overlay.appendChild(bar);

    var host = el('div', 'mxof-container');
    host.id = CONTAINER_ID;
    // 编辑器内的任何交互都视为「有改动」，用于关闭/切换时的未保存提醒。
    // Univer 的编辑发生在 canvas 上，不产生 DOM 变更事件，故按输入事件近似判定。
    ['mousedown', 'keydown', 'input', 'paste'].forEach(function (ev) {
      host.addEventListener(ev, function () { dirty = true; }, true);
    });
    overlay.appendChild(host);

    document.body.appendChild(overlay);
    syncTabs();
    updateBar();
  }

  function close() {
    if (dirty && !confirm('有未保存的修改，确认关闭？')) return;
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    overlay = null;
  }

  /* ---------------- 对外入口 ---------------- */
  function open(kind) {
    var want = kind || curKind || 'sheet';
    // 注意：不能在判断前把 curKind 改成 want，否则 switchKind 的
    // 「kind === curKind」恒真，已打开时切换类型会静默失效。
    if (overlay) { switchKind(want); return; }
    curKind = want;
    loadCssOnce(HOST_CSS);
    buildOverlay();          // 先建骨架，status() 才有落点
    if (!tok()) status('未登录：可先编辑，但保存会失败', true);
    mountEditor();
  }

  global.MiniYuxiOffice = {
    open: open,
    close: close,
    save: doSave,
    isOpen: function () { return !!overlay; },
    current: function () { return { kind: curKind, doc_id: curId, dirty: dirty }; }
  };
})(window);
