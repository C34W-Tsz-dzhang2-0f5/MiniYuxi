/* ================================================================
   MiniYuxi · 智能工作台 —— 交互逻辑
   依赖：window.__WB_ICONS__（快捷入口图标 SVG，由服务端注入）
   后端：POST /api/wb/chat（自动携带 Bearer Token，静默登录）；
        未登录/登录失败降级为本地模拟流式回复。
   ================================================================ */
(function () {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };

  /* ---------------- 鉴权（U1：不再静默登录，未登录由交互引导） ---------------- */
  var TOKEN = (function () {
    try { return localStorage.getItem('miniyuxi_token') || ''; } catch (e) { return ''; }
  })();

  /* U3：被「未登录」拦下的待发消息，登录成功后自动续发，避免用户重打一遍 */
  var pendingSend = null;

  function setToken(t) {
    TOKEN = t || '';
    try { if (TOKEN) localStorage.setItem('miniyuxi_token', TOKEN); } catch (e) {}
  }

  function login(tenant, user, pass) {
    return fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenant: tenant, username: user, password: pass })
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (d) {
      if (!d || !d.token) throw new Error('no token');
      setToken(d.token);
      try { if (d.role) localStorage.setItem('miniyuxi_role', d.role); } catch (e) {}
      return d;
    });
  }

  /* U1：不再用默认账号静默登录。
     无 token 时返回空串，由调用方引导登录；登录态与 LAN 口令守卫联动。 */
  function ensureToken() {
    if (TOKEN) return Promise.resolve(TOKEN);
    return Promise.resolve('');
  }

  /* ---------------- 静态数据（文案） ---------------- */
  var NAV_ITEMS = [
    { label: '新建', action: 'new' },
    { label: '导入', action: 'import' },
    { label: '知识库', action: 'kb' },
    { label: 'HRM人事', action: 'hrm' },
    { label: '流程', action: 'flow' },
    { label: '模型切换', action: 'model' },
    { label: '成本管理', action: 'cost' },
    { label: '管理', action: 'admin' },
    { label: '岗位工作台', action: 'roles' }
  ];

  // 场景分组：日常办公 = 原站实测 10 项；代码开发 = 同构补充
  var SCENES = {
    '日常办公': ['幻灯片', '视频生成', '深度研究', '文档处理', '数据分析',
                 '可视化', '金融服务', '产品管理', '设计', '邮件编辑'],
    '代码开发': ['代码补全', '重构建议', '单元测试', '代码审查', 'Bug 定位',
                 '接口联调', '性能分析', 'SQL 优化']
  };

  var ICONS = window.__WB_ICONS__ || {};
  var ICON_MAP = {};
  (ICONS.quickActions || []).forEach(function (q) { ICON_MAP[q.label] = q.svg; });

  /* ---------------- U2：会话与消息 localStorage 持久化 ----------------
     会话列表键 miniyuxi_convos；单会话消息键 miniyuxi_msgs_<id>。
     读写全部 try/catch 兜底（隐私模式 / 配额满时不致崩溃）。          */
  var CONV_STORE_KEY = 'miniyuxi_convos';
  var MSG_STORE_PREFIX = 'miniyuxi_msgs_';

  function loadConvos() {
    try {
      var raw = localStorage.getItem(CONV_STORE_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.filter(function (c) { return c && c.id; }) : [];
    } catch (e) { return []; }
  }
  function saveConvos(list) {
    try {
      localStorage.setItem(CONV_STORE_KEY, JSON.stringify((list || []).slice(0, 50)));
    } catch (e) {}
  }
  function msgsKey(id) { return MSG_STORE_PREFIX + id; }
  function loadMsgs(id) {
    if (!id) return [];
    try {
      var raw = localStorage.getItem(msgsKey(id));
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }
  function saveMsgs(id, msgs) {
    if (!id) return;
    try {
      localStorage.setItem(msgsKey(id), JSON.stringify((msgs || []).slice(-80)));
    } catch (e) {}
  }
  function dropMsgs(id) {
    if (!id) return;
    try { localStorage.removeItem(msgsKey(id)); } catch (e) {}
  }

  var CONVERSATIONS = loadConvos();

  var OVERVIEW = [
    { key: '会话数', val: CONVERSATIONS.length, pct: 60 },
    { key: '知识库文档', val: 26, pct: 78 },
    { key: '已注册工具', val: 12, pct: 45 },
    { key: '评估结果（Pass@1）', val: '87%', pct: 87 }
  ];

  // 模型中心缓存 + 策略名映射（供路由条/对比渲染）
  var MODEL_CATALOG = null;
  var STRAT_NAMES = { economy: '经济', balanced: '均衡', premium: '强力' };

  var state = {
    scene: '日常办公',
    messages: [],
    activeConvo: '',
    busy: false,
    sources: [],
    modelMode: 'workbench',   // workbench | auto | single | compare
    singleModelId: '',
    compareIds: [],
    strategy: 'balanced',     // economy | balanced | premium
    autoJudge: true
  };
  /* 恢复多模型用户偏好 */
  (function restoreMX() {
    try {
      var mm = localStorage.getItem('mx_modelMode');
      if (mm && /^(workbench|auto|single|compare)$/.test(mm)) state.modelMode = mm;
      var sm = localStorage.getItem('mx_singleModelId');
      if (sm) state.singleModelId = sm;
      var ci = localStorage.getItem('mx_compareIds');
      if (ci) { var a = JSON.parse(ci); if (Array.isArray(a)) state.compareIds = a; }
      var st = localStorage.getItem('mx_strategy');
      if (st && /^(economy|balanced|premium)$/.test(st)) state.strategy = st;
    } catch (e) {}
  })();
  function saveMX() {
    try {
      localStorage.setItem('mx_modelMode', state.modelMode);
      localStorage.setItem('mx_singleModelId', state.singleModelId);
      localStorage.setItem('mx_compareIds', JSON.stringify(state.compareIds));
      localStorage.setItem('mx_strategy', state.strategy);
    } catch (e) {}
  }

  /* ---------------- Toast ---------------- */
  var toastTimer = null;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg;
    t.hidden = false;
    requestAnimationFrame(function () { t.classList.add('is-show'); });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      t.classList.remove('is-show');
      setTimeout(function () { t.hidden = true; }, 220);
    }, 2000);
  }

  /* ---------------- L1：抽屉断点判定（与 CSS @media max-width:1024px 对齐） ---------------- */
  var detailDrawer = null;
  function isDrawerMode() {
    try { return window.matchMedia('(max-width: 1024px)').matches; } catch (e) { return window.innerWidth <= 1024; }
  }

  /* ---------------- 渲染：顶部导航（L2：窄屏溢出进「更多」菜单） ---------------- */
  function renderNav() {
    var nav = $('#topNav');
    nav.innerHTML = NAV_ITEMS.map(function (n) {
      return '<a class="cloud-welcome__nav-item" data-action="' + n.action + '" href="javascript:void(0)">' + n.label + '</a>';
    }).join('') +
      '<button class="nav-more" id="btnNavMore" aria-haspopup="true" aria-expanded="false" title="更多功能">更多' +
      '<svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
      '<path d="M8 11.5 2.5 6h11L8 11.5Z"/></svg></button>' +
      '<div class="nav-more-menu" id="navMoreMenu" hidden>' +
      NAV_ITEMS.map(function (n) {
        return '<button type="button" data-action="' + n.action + '">' + n.label + '</button>';
      }).join('') + '</div>';

    $$('#topNav .cloud-welcome__nav-item').forEach(function (a) {
      a.addEventListener('click', function () { handleNavAction(a.dataset.action); });
    });

    var moreBtn = $('#btnNavMore'), menu = $('#navMoreMenu');
    if (moreBtn && menu) {
      var closeMenu = function () {
        if (!menu.hidden) { menu.hidden = true; moreBtn.setAttribute('aria-expanded', 'false'); }
      };
      moreBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        var willOpen = menu.hidden;
        menu.hidden = !willOpen;
        moreBtn.setAttribute('aria-expanded', String(willOpen));
      });
      $$('#navMoreMenu button').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          closeMenu();
          handleNavAction(b.dataset.action);
        });
      });
      document.addEventListener('click', closeMenu);
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });
    }
  }

  /* ---------------- 顶部导航动作分发 ---------------- */
  function handleNavAction(action) {
    switch (action) {
      case 'new': startNewChat(); break;
      case 'import': openImportModal(); break;
      case 'kb': openKbModal(); break;
      case 'hrm': openHrmModal(); break;
      case 'flow': openFlowModal(); break;
      case 'model': openModelCenter(); break;
      case 'cost': openCostModal(); break;
      case 'admin': openAdminModal(); break;
      case 'roles': openTaskFlowModal(); break;
      default: toast('功能入口：' + action);
    }
  }

  /* ---------------- 岗位工作台：左列表（页签+搜索）右运行双栏 ---------------- */
  var TF_STATE = { tasks: [], names: {}, role: 'all' };

  function openTaskFlowModal() {
    var body =
      '<div class="tf-wrap">' +
        '<div class="tf-left">' +
          '<div class="tf-bar">' +
            '<div id="tfTabs"></div>' +
            '<input class="tf-search" id="tfQ" placeholder="搜索任务名 / 模块…">' +
          '</div>' +
          '<div class="tf-list" id="tfList"><div class="fm-empty">加载任务目录中…</div></div>' +
        '</div>' +
        '<div class="tf-right" id="tfRun"><div class="tf-hint">点左侧任务卡的「运行」开始<br>表单和结果都显示在这一栏</div></div>' +
      '</div>';
    openFeatureModal('岗位工作台（提示词 → 自动执行）', body,
      '<button class="fm-btn secondary" id="tfClose">关闭</button>', { wide: true });
    $('#tfClose').addEventListener('click', closeFeatureModal);
    TF_STATE = { tasks: [], names: {}, role: 'all' };
    loadTaskFlowAll();
  }

  // 一次性加载全部任务；页签切换岗位、搜索框过滤，点运行在右侧面板操作
  function loadTaskFlowAll() {
    Promise.all([
      wbFetch('/api/taskflow/roles').then(function (r) { return r.json(); }),
      wbFetch('/api/taskflow/list').then(function (r) { return r.json(); })
    ]).then(function (rs) {
      (rs[0].roles || []).forEach(function (r) { TF_STATE.names[r.role] = r.display || r.role_line || r.role; });
      TF_STATE.tasks = rs[1].tasks || [];
      if (!TF_STATE.tasks.length) { $('#tfList').innerHTML = '<div class="fm-empty">任务库为空</div>'; return; }
      $('#tfTabs').innerHTML = ['all'].concat(Object.keys(TF_STATE.names)).map(function (r) {
        var label = r === 'all' ? '全部' : (TF_STATE.names[r] || r);
        var n = r === 'all' ? TF_STATE.tasks.length : TF_STATE.tasks.filter(function (t) { return t.role === r; }).length;
        return '<button class="tf-tab' + (r === TF_STATE.role ? ' on' : '') + '" data-role="' + r + '">' + label + ' ' + n + '</button>';
      }).join('');
      $$('#tfTabs .tf-tab').forEach(function (b) {
        b.addEventListener('click', function () {
          TF_STATE.role = b.dataset.role;
          $$('#tfTabs .tf-tab').forEach(function (x) { x.classList.toggle('on', x === b); });
          renderTaskFlowList();
        });
      });
      $('#tfQ').addEventListener('input', renderTaskFlowList);
      renderTaskFlowList();
    }).catch(function (e) { $('#tfList').innerHTML = '<div class="fm-empty">加载失败：' + e + '</div>'; });
  }

  function renderTaskFlowList() {
    var q = ($('#tfQ').value || '').trim().toLowerCase();
    var ts = TF_STATE.tasks.filter(function (t) {
      if (TF_STATE.role !== 'all' && t.role !== TF_STATE.role) return false;
      if (q && (t.title + t.module + t.id).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    if (!ts.length) { $('#tfList').innerHTML = '<div class="fm-empty">没有匹配的任务</div>'; return; }
    var groups = {};
    ts.forEach(function (t) { (groups[t.role] = groups[t.role] || []).push(t); });
    $('#tfList').innerHTML = Object.keys(groups).map(function (role) {
      var cards = groups[role].map(function (t) {
        return '<div class="fm-card" data-id="' + t.id + '"><div class="n">' + t.title + '</div>' +
               '<div class="m">' + t.module + '</div>' +
               '<button class="fm-btn sm" data-run="' + t.id + '">运行</button></div>';
      }).join('');
      var head = TF_STATE.role === 'all'
        ? '<div class="fm-sub"><b>' + (TF_STATE.names[role] || role) + '（' + groups[role].length + '）</b></div>' : '';
      return head + '<div class="fm-grid">' + cards + '</div>';
    }).join('');
    $$('#tfList .fm-card').forEach(function (c) {
      c.addEventListener('click', function () { openTaskFlowRun(c.dataset.id); });
    });
    $$('#tfList .fm-card [data-run]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); openTaskFlowRun(b.dataset.run); });
    });
  }

  function openTaskFlowRun(taskId) {
    var t = null;
    for (var i = 0; i < TF_STATE.tasks.length; i++) { if (TF_STATE.tasks[i].id === taskId) { t = TF_STATE.tasks[i]; break; } }
    $$('#tfList .fm-card').forEach(function (c) { c.classList.toggle('on', c.dataset.id === taskId); });
    $('#tfRun').innerHTML =
      '<div class="tf-run-title">' + (t ? t.title : taskId) + '</div>' +
      '<div class="fm-sub">' + (t ? (TF_STATE.names[t.role] || t.role) + ' · ' + t.module : '') + '</div>' +
      '<div class="fm-form">' +
      '企业/部门<input id="tfDept" placeholder="车务通科技">' +
      '本次目标<input id="tfGoal" placeholder="如：发布中秋放假通知">' +
      '使用对象<input id="tfAud" placeholder="全体员工">' +
      '截止时间<input id="tfDue" placeholder="2026-09-18">' +
      '材料清单(逗号分隔)<input id="tfMat" placeholder="放假安排.xlsx">' +
      '</div>' +
      '<div class="fm-row">' +
      '<button class="fm-btn" id="tfRunBtn">运行</button>' +
      '<button class="fm-btn secondary" id="tfDryBtn">试运行(不调LLM)</button>' +
      '</div>' +
      '<pre id="tfOut" class="fm-log">—</pre>';
    $('#tfRun').scrollTop = 0;
    $('#tfRunBtn').addEventListener('click', function () { postTaskFlowRun(taskId, false); });
    $('#tfDryBtn').addEventListener('click', function () { postTaskFlowRun(taskId, true); });
  }

  function postTaskFlowRun(taskId, dry) {
    var payload = {
      task_id: taskId,
      dry: dry,
      variables: {
        dept: $('#tfDept').value || '（未填写）',
        goal: $('#tfGoal').value || '（未填写）',
        audience: $('#tfAud').value || '（未填写）',
        deadline: $('#tfDue').value || '（未填写）'
      },
      materials: ($('#tfMat').value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean)
    };
    $('#tfOut').textContent = '执行中…';
    wbFetch('/api/taskflow/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); }).then(function (d) {
      var out = d.answer || '(无输出)';
      var fol = (d.followups || []).map(function (f) { return '· ' + f; }).join('\n');
      var mc = d.materials_check || {};
      $('#tfOut').textContent =
        '【材料核验】已提供 ' + ((mc.provided || []).length) + ' 项，缺失 ' + (mc.missing_count || 0) + ' 项\n' +
        '【结果】\n' + out + '\n\n【建议追问】\n' + fol + '\n\n【审计】' + (d.audit || '—');
    }).catch(function (e) { $('#tfOut').textContent = '执行失败：' + e; });
  }

  function startNewChat() {
    carryDraft('#composerInputDock', '#composerInput');   // L5：把对话态草稿带回欢迎态
    state.activeConvo = null;   // U2：置空会话，下一条消息触发 newConvo 开新会话
    state.messages = [];
    state.sources = [];
    $('#messageList').innerHTML = '';
    $('#welcomeStage').hidden = false;
    $('#messageScroll').hidden = true;
    $('#chatDock').hidden = true;
    $$('#convListBody .conv-item').forEach(function (x) { x.classList.remove('is-active'); });
    if (window.innerWidth <= 768) collapseSidebar();
    toast('已新建对话');
  }

  /* U1/U3：401 只做「非阻塞」登录态提示——不自动弹遮罩，
     否则首页初始化的一串请求会在首屏盖一层登录弹窗，把欢迎页整个挡掉。
     真正需要凭据的动作（发送消息 / 点登录按钮）才唤起弹窗。 */
  var _authToastAt = 0;
  function markUnauthorized() {
    state.unauthorized = true;
    var fu = $('#footerUser');
    if (fu) fu.textContent = '未登录';
    var btn = $('#btnLogin');
    if (btn) { btn.hidden = false; var c = btn.querySelector('.wb-button__content'); if (c) c.textContent = '登录'; }
    var now = Date.now();
    if (now - _authToastAt > 8000) {   // 8s 内只提示一次，避免刷屏
      _authToastAt = now;
      toast('未登录：部分数据需登录后加载，点右上角「登录」');
    }
  }

  function wbFetch(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = 'Bearer ' + TOKEN;
    return fetch(url, opts).then(function (r) {
      if (r.status === 401) {
        markUnauthorized();
        throw new Error('未登录');
      }
      return r;
    });
  }

  /* ---------------- 通用功能弹窗 ---------------- */
  function openFeatureModal(title, bodyHtml, footHtml, opts) {
    opts = opts || {};
    // wide=true 时放宽卡片宽度（HRM 这类需要左右分栏的模块），否则回落默认 560px
    var card = $('#featureModal .my-modal__card');
    if (card) {
      card.style.width = opts.wide ? '94vw' : '';
      card.style.maxWidth = opts.wide ? '1180px' : '';
      card.style.maxHeight = opts.wide ? '86vh' : '';
    }
    $('#fmTitle').textContent = title;
    $('#fmBody').innerHTML = bodyHtml || '';
    $('#fmFoot').innerHTML = footHtml || '';
    $('#featureModal').hidden = false;
  }
  function closeFeatureModal() { $('#featureModal').hidden = true; }
  $('#fmClose').addEventListener('click', closeFeatureModal);
  $('#featureModal').addEventListener('click', function (e) { if (e.target === $('#featureModal')) closeFeatureModal(); });

  /* ---------------- 知识库弹窗 ---------------- */
  function openKbModal() {
    openFeatureModal('HR 知识库',
      '<div class="fm-ask"><input class="fm-input" id="fmKbQ" placeholder="向知识库提问（制度 / 流程 / 政策）">' +
        '<button class="fm-btn" id="fmKbAsk">提问</button></div>' +
      '<div class="fm-ask-res" id="fmKbRes" hidden></div>' +
      '<div id="fmKbList"><div class="fm-empty">加载中…</div></div>',
      '<button class="fm-btn secondary" id="fmKbRefresh">刷新文档列表</button>');
    $('#fmKbRefresh').addEventListener('click', loadKbDocs);
    $('#fmKbAsk').addEventListener('click', kbAsk);
    $('#fmKbQ').addEventListener('keydown', function (e) { if (e.key === 'Enter') kbAsk(); });
    loadKbDocs();
  }
  function loadKbDocs() {
    var body = $('#fmKbList');
    if (!body) body = $('#fmBody');
    body.innerHTML = '<div class="fm-empty">加载中…</div>';
    wbFetch('/api/kb/docs')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (docs) {
        if (!docs || !docs.length) {
          body.innerHTML = '<div class="fm-empty">知识库暂无文档，可通过「导入」上传制度文件。</div>';
          return;
        }
        body.innerHTML = '<ul class="fm-list">' + docs.map(function (d) {
          return '<li><div class="t"><div>' + (d.title || '未命名') + '</div>' +
                 '<div class="s">' + (d.source || d.id || '') + ' · ' + (d.n_chunks || 0) + ' chunks · ' + (d.created_at || '') + '</div></div></li>';
        }).join('') + '</ul>';
      })
      .catch(function (e) { body.innerHTML = '<div class="fm-empty">加载失败：' + (e.message || e) + '</div>'; });
  }
  function kbAsk() {
    var q = ($('#fmKbQ').value || '').trim();
    if (!q) { toast('请输入问题'); return; }
    var res = $('#fmKbRes');
    res.hidden = false;
    res.innerHTML = '<div class="fm-empty">思考中…</div>';
    wbFetch('/api/rag/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, top_k: 5, prefer: 'auto' })
    })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        var ans = d.answer || '(无答案)';
        var cites = (d.citations || []).slice(0, 5).map(function (c) {
          var t = c.title || c.source || (c.content || '').toString().slice(0, 120) || '';
          return '<li>' + esc(t) + '</li>';
        }).join('');
        res.innerHTML = '<div class="fm-ans">' + esc(ans) + '</div>' +
          (cites ? '<div class="fm-cites">参考：<ul>' + cites + '</ul></div>' : '') +
          '<div class="fm-meta">来源：' + esc(d.mode || 'native') + '</div>';
      })
      .catch(function (e) { res.innerHTML = '<div class="fm-empty">提问失败：' + (e.message || e) + '</div>'; });
  }

  /* ---------------- HRM 人事管理系统（简道云迁移：49 表单数据驱动） ----------------
     左：表单清单（可搜索）｜右：该表单数据表格 + 按 schema 动态生成的新建表单。
     字段键统一用 fields[].col（w_xxx），与后端 /api/hrm/* 一致。            */
  var HRM_FORMS = [], HRM_CUR = null, HRM_META = null;

  function openHrmModal() {
    openFeatureModal('HRM 人事管理系统',
      '<div class="hrm-wrap">' +
        '<div class="hrm-side">' +
          '<input class="hrm-search" id="hrmSearch" placeholder="搜索表单（中文名 / key）">' +
          '<ul class="hrm-forms" id="hrmForms"><li class="fm-empty">加载中…</li></ul>' +
        '</div>' +
        '<div class="hrm-main">' +
          '<div class="hrm-bar">' +
            '<span class="hrm-title" id="hrmTitle">请选择左侧表单</span>' +
            '<span id="hrmMeta"></span><span class="sp"></span>' +
            '<button class="fm-btn secondary" id="hrmNew">新建</button>' +
            '<button class="fm-btn secondary" id="hrmRefresh">刷新</button>' +
          '</div>' +
          '<div class="hrm-scroll" id="hrmTable"><div class="fm-empty">—</div></div>' +
          '<div id="hrmEdit"></div>' +
        '</div>' +
      '</div>',
      '<span style="font-size:12px;color:#999">共 <b id="hrmCount">0</b> 张表单 · 数据来自 /api/hrm</span>' +
      '<button class="fm-btn secondary" id="hrmClose">关闭</button>',
      { wide: true });

    $('#hrmClose').addEventListener('click', closeFeatureModal);
    $('#hrmRefresh').addEventListener('click', function () { hrmLoadForms(); });
    $('#hrmNew').addEventListener('click', function () { if (HRM_CUR) hrmOpenCreate(); });
    $('#hrmSearch').addEventListener('input', function (e) { hrmRenderForms(e.target.value || ''); });
    hrmLoadForms();
  }

  function hrmLoadForms() {
    var box = $('#hrmForms');
    if (box) box.innerHTML = '<li class="fm-empty">加载中…</li>';
    wbFetch('/api/hrm/forms')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        HRM_FORMS = (d && d.forms) || [];
        var el = $('#hrmCount'); if (el) el.textContent = HRM_FORMS.length;
        hrmRenderForms(($('#hrmSearch') || {}).value || '');
      })
      .catch(function (e) {
        if (box) box.innerHTML = '<li class="fm-empty">加载失败：' + (e.message || e) + '</li>';
      });
  }

  function hrmRenderForms(kw) {
    var box = $('#hrmForms');
    if (!box) return;
    kw = (kw || '').trim().toLowerCase();
    var list = HRM_FORMS.filter(function (f) {
      return !kw || (f.name || '').toLowerCase().indexOf(kw) >= 0 || (f.key || '').toLowerCase().indexOf(kw) >= 0;
    });
    if (!list.length) { box.innerHTML = '<li class="fm-empty">无匹配表单</li>'; return; }
    box.innerHTML = list.map(function (f) {
      return '<li data-key="' + f.key + '" class="' + (HRM_CUR === f.key ? 'on' : '') + '">' +
             '<span>' + esc(f.name) + '</span>' +
             '<span class="k">' + (f.has_flow ? '流程 ' : '') + f.field_count + '</span></li>';
    }).join('');
    $$('#hrmForms li').forEach(function (li) {
      li.addEventListener('click', function () { hrmSelect(li.dataset.key); });
    });
  }

  function hrmSelect(key) {
    HRM_CUR = key; HRM_META = null;
    $('#hrmEdit').innerHTML = '';
    hrmRenderForms(($('#hrmSearch') || {}).value || '');
    var fm = HRM_FORMS.filter(function (f) { return f.key === key; })[0];
    $('#hrmTitle').textContent = fm ? fm.name : key;
    $('#hrmMeta').innerHTML = fm ? '<span class="hrm-tag' + (fm.has_flow ? ' flow' : '') + '">' +
      (fm.has_flow ? '审批流' : '数据表') + '</span> <span class="hrm-tag">' + fm.field_count + ' 字段</span>' +
      (fm.subform_count ? ' <span class="hrm-tag">' + fm.subform_count + ' 子表单</span>' : '') : '';
    $('#hrmTable').innerHTML = '<div class="fm-empty">加载中…</div>';
    Promise.all([
      wbFetch('/api/hrm/meta/' + key).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      wbFetch('/api/hrm/' + key + '?size=50').then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    ]).then(function (res) {
      HRM_META = res[0];
      hrmRenderTable(res[1] && res[1].rows ? res[1].rows : []);
    }).catch(function (e) {
      $('#hrmTable').innerHTML = '<div class="fm-empty">加载失败：' + (e.message || e) + '</div>';
    });
  }

  function hrmRenderTable(rows) {
    var box = $('#hrmTable');
    if (!box) return;
    var meta = HRM_META || {};
    var fields = (meta.fields || []).filter(function (f) { return f.type !== 'separator' && f.type !== 'subform'; });
    if (!rows.length) { box.innerHTML = '<div class="fm-empty">该表单暂无数据</div>'; return; }
    var head = fields.slice(0, 12).map(function (f) { return '<th>' + esc(f.label) + '</th>'; }).join('');
    var body = rows.map(function (r) {
      return '<tr>' + fields.slice(0, 12).map(function (f) {
        var v = r[f.col];
        if (v && typeof v === 'object') v = JSON.stringify(v);
        return '<td title="' + esc(String(v == null ? '' : v)) + '">' + esc(String(v == null ? '' : v)) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    box.innerHTML = '<table class="hrm-tbl"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>' +
      '<div style="padding:8px;font-size:12px;color:#999">显示 ' + rows.length + ' 条（最多 50）' +
      (fields.length > 12 ? ' · 仅显示前 12 个字段，共 ' + fields.length + ' 个' : '') + '</div>';
  }

  function hrmOpenCreate() {
    var meta = HRM_META;
    if (!meta) { toast('表单结构未加载完成'); return; }
    var fields = (meta.fields || []).filter(function (f) { return f.type !== 'separator' && f.type !== 'subform'; });
    var opts = function (f) {
      var os = f.options || [];
      if (!os.length) return '';
      return '<datalist id="dl_' + f.col + '">' + os.map(function (o) {
        return '<option value="' + esc(String(o.label || o.value)) + '"></option>';
      }).join('') + '</datalist>';
    };
    $('#hrmEdit').innerHTML =
      '<div class="fm-sub">新建「' + esc(meta.name || HRM_CUR) + '」记录' +
      (fields.filter(function (f) { return f.required; }).length ? '（<span style="color:#b26a00">* 为必填</span>）' : '') + '</div>' +
      '<div class="hrm-edit">' + fields.slice(0, 20).map(function (f) {
        var t = (f.type === 'number') ? 'number' : (f.type === 'datetime' ? 'text' : 'text');
        return '<div><label>' + esc(f.label) + (f.required ? ' *' : '') +
               ' <span style="color:#bbb">' + esc(f.type) + '</span></label>' +
               '<input id="nf_' + f.col + '" type="' + t + '"' +
               (f.type === 'datetime' ? ' placeholder="YYYY-MM-DD"' : '') +
               ' list="dl_' + f.col + '">' + opts(f) + '</div>';
      }).join('') + '</div>' +
      '<div class="fm-row" style="margin-top:10px">' +
        '<button class="fm-btn" id="hrmSubmit">提交</button>' +
        '<button class="fm-btn secondary" id="hrmCancel">取消</button>' +
        '<span id="hrmMsg" style="font-size:12px;color:#999"></span></div>' +
      (fields.length > 20 ? '<div style="font-size:12px;color:#999">共 ' + fields.length + ' 字段，此处仅展示前 20 个，其余可用 API 写入</div>' : '');
    $('#hrmCancel').addEventListener('click', function () { $('#hrmEdit').innerHTML = ''; });
    $('#hrmSubmit').addEventListener('click', hrmSubmitCreate);
  }

  function hrmSubmitCreate() {
    var meta = HRM_META; if (!meta) return;
    var fields = (meta.fields || []).filter(function (f) { return f.type !== 'separator' && f.type !== 'subform'; });
    var data = {}, missing = [];
    fields.slice(0, 20).forEach(function (f) {
      var el = $('#nf_' + f.col); if (!el) return;
      var v = (el.value || '').trim();
      if (!v) { if (f.required) missing.push(f.label); return; }
      data[f.col] = (f.type === 'number') ? Number(v) : v;
    });
    var msg = $('#hrmMsg');
    if (missing.length) { msg.textContent = '请填写必填项：' + missing.join('、'); msg.style.color = '#d33'; return; }
    msg.textContent = '提交中…'; msg.style.color = '#999';
    wbFetch('/api/hrm/' + HRM_CUR, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
    }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status)); return j; });
    }).then(function () {
      msg.textContent = '已保存'; msg.style.color = '#1a7f37';
      $('#hrmEdit').innerHTML = '';
      hrmSelect(HRM_CUR);
    }).catch(function (e) { msg.textContent = '保存失败：' + (e.message || e); msg.style.color = '#d33'; });
  }

  /* ---------------- 系统管理弹窗（B 方案：自助改密 + 用户管理）---------------- */
  function openAdminModal() {
    openFeatureModal('系统管理',
      '<div class="fm-sec"><h4>修改我的密码</h4>' +
        '<div class="fm-row"><input class="fm-input" id="amOld" type="password" placeholder="旧密码"></div>' +
        '<div class="fm-row"><input class="fm-input" id="amNew" type="password" placeholder="新密码（≥6 位）"></div>' +
        '<div class="fm-row"><input class="fm-input" id="amNew2" type="password" placeholder="确认新密码"></div>' +
        '<button class="fm-btn" id="amChg">修改密码</button></div>' +
      '<div class="fm-sec"><h4>用户管理（仅本租户）</h4>' +
        '<div class="fm-log" id="amUsers" style="max-height:260px;overflow:auto">加载中…</div></div>',
      '<button class="fm-btn secondary" id="amClose">关闭</button>');
    $('#amClose').addEventListener('click', closeFeatureModal);
    $('#amChg').addEventListener('click', function () {
      var o = $('#amOld').value, n = $('#amNew').value, n2 = $('#amNew2').value;
      if (n !== n2) { toast('两次新密码不一致'); return; }
      if (n.length < 6) { toast('新密码至少 6 位'); return; }
      wbFetch('/api/me/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: o, new_password: n })
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function () { toast('密码已修改，建议重新登录'); $('#amOld').value = $('#amNew').value = $('#amNew2').value = ''; })
        .catch(function (e) { toast('改密失败：' + (e.message || e)); });
    });
    loadUsers();
  }
  function loadUsers() {
    var box = $('#amUsers');
    if (!box) return;
    wbFetch('/api/users')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (us) {
        if (!us || !us.length) { box.innerHTML = '<div class="fm-empty">暂无其他用户</div>'; return; }
        box.innerHTML = '<table class="fm-table"><tr><th>用户</th><th>角色</th><th>创建</th><th></th></tr>' +
          us.map(function (u) {
            return '<tr><td>' + esc(u.username) + '</td><td>' + esc(u.role) + '</td><td>' + esc(u.created_at || '') + '</td>' +
              '<td><button class="fm-btn small" data-u="' + esc(u.username) + '">重置口令</button></td></tr>';
          }).join('') + '</table>';
        $$('#amUsers .fm-btn.small').forEach(function (b) {
          b.addEventListener('click', function () {
            var un = b.dataset.u;
            var np = window.prompt('为 ' + un + ' 设置新密码（≥6 位）：');
            if (!np) return;
            wbFetch('/api/users/reset', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username: un, new_password: np })
            })
              .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
              .then(function () { toast('已重置 ' + un + ' 的密码'); })
              .catch(function (e) { toast('重置失败：' + (e.message || e)); });
          });
        });
      })
      .catch(function (e) { box.innerHTML = '<div class="fm-empty">加载失败：' + (e.message || e) + '</div>'; });
  }

  /* ---------------- 导入弹窗 ---------------- */
  function openImportModal() {
    openFeatureModal('导入制度文档',
      '<div class="fm-drop" id="fmDrop">点击选择，或把文件拖到这里（.docx / .pdf / .txt / .md）</div>' +
      '<input type="file" id="fmFile" accept=".docx,.pdf,.txt,.md" multiple class="hidden">' +
      '<div class="fm-log" id="fmImportLog">等待选择文件…</div>',
      '<button class="fm-btn secondary" id="fmImportClose">关闭</button>');
    var drop = $('#fmDrop'), fileInput = $('#fmFile'), log = $('#fmImportLog');
    drop.addEventListener('click', function () { fileInput.click(); });
    drop.addEventListener('dragover', function (e) { e.preventDefault(); drop.style.borderColor = '#1a1a1a'; });
    drop.addEventListener('dragleave', function () { drop.style.borderColor = '#d0d0d0'; });
    drop.addEventListener('drop', function (e) { e.preventDefault(); drop.style.borderColor = '#d0d0d0'; uploadFiles(e.dataTransfer.files); });
    fileInput.addEventListener('change', function () { uploadFiles(fileInput.files); });
    $('#fmImportClose').addEventListener('click', closeFeatureModal);

    function uploadFiles(files) {
      if (!files || !files.length) return;
      var lines = [];
      var done = 0;
      Array.prototype.slice.call(files).forEach(function (f) {
        lines.push('开始导入：' + f.name);
        var fd = new FormData();
        fd.append('file', f);
        wbFetch('/api/kb/upload', { method: 'POST', body: fd })
          .then(function (r) { return r.json().then(function (j) { return { r: r, j: j }; }); })
          .then(function (res) {
            if (res.r.ok) lines.push('✅ ' + f.name + ' → ' + (res.j.doc_id || 'ok') + ' / chunks=' + (res.j.n_chunks || '?'));
            else lines.push('❌ ' + f.name + ' → ' + (res.j.detail || res.r.status));
          })
          .catch(function (e) { lines.push('❌ ' + f.name + ' → ' + (e.message || e)); })
          .finally(function () {
            done++;
            log.textContent = lines.join('\n');
            if (done === files.length) lines.push('全部完成，可去「知识库」查看。');
          });
      });
      log.textContent = lines.join('\n');
    }
  }

  /* ---------------- 流程弹窗 ---------------- */
  function openFlowModal() {
    openFeatureModal('Agent 流程编排',
      '<div class="fm-row"><select class="fm-input" id="fmFlowSel"><option value="recruit">招聘 19 阶段</option></select>' +
      '<button class="fm-btn" id="fmFlowStart">启动</button>' +
      '<button class="fm-btn secondary" id="fmFlowRun">跑到结束</button></div>' +
      '<div class="fm-log" id="fmFlowLog">未启动流程</div>',
      '<button class="fm-btn secondary" id="fmFlowClose">关闭</button>');
    var runId = '';
    wbFetch('/api/agent/flows')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        // /api/agent/flows 返回 {flowId:{stages,hitl,entry}} 或 {flows:[...]}，两种都兼容
        var opts = '';
        if (Array.isArray(d.flows)) {
          opts = d.flows.map(function (f) { return '<option value="' + f.id + '">' + f.name + '</option>'; }).join('');
        } else if (d && typeof d === 'object') {
          opts = Object.keys(d).map(function (k) {
            var v = d[k] || {};
            return '<option value="' + k + '">' + k + '（' + (v.stages || '?') + ' 阶段' +
                   (v.hitl && v.hitl.length ? ' · HITL ' + v.hitl.join('/') : '') + '）</option>';
          }).join('');
        }
        if (opts) $('#fmFlowSel').innerHTML = opts;
      }).catch(function () {});
    function log(msg) { var b = $('#fmFlowLog'); b.textContent = b.textContent + '\n' + msg; b.scrollTop = b.scrollHeight; }
    $('#fmFlowStart').addEventListener('click', function () {
      wbFetch('/api/agent/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ flow: $('#fmFlowSel').value }) })
        .then(function (r) { return r.json(); })
        .then(function (d) { runId = d.run_id; $('#fmFlowLog').textContent = '已启动：' + runId + '（当前 ' + d.current + '）'; })
        .catch(function (e) { log('启动失败：' + (e.message || e)); });
    });
    $('#fmFlowRun').addEventListener('click', function () {
      if (!runId) { log('请先点击「启动」'); return; }
      wbFetch('/api/agent/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: runId, approve: true }) })
        .then(function (r) { return r.json(); })
        .then(function (d) { log('状态：' + d.status + ' / 步数 ' + (d.history || []).length); })
        .catch(function (e) { log('执行失败：' + (e.message || e)); });
    });
    $('#fmFlowClose').addEventListener('click', closeFeatureModal);
  }

  /* ---------------- 多模型：工具函数 ---------------- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function modelNameOf(id) {
    if (!id) return '—';
    if (MODEL_CATALOG) {
      var m = (MODEL_CATALOG.models || []).filter(function (x) { return x.id === id; })[0];
      if (m) return m.name || id;
    }
    return id;
  }
  function _provName(provs, pid) {
    var p = (provs || []).filter(function (x) { return x.id === pid; })[0];
    return p ? p.name : pid;
  }
  function modelModeLabel() {
    if (state.modelMode === 'workbench') return '工作台（Agent）';
    if (state.modelMode === 'auto') return '自动路由（' + (STRAT_NAMES[state.strategy] || state.strategy) + '）';
    if (state.modelMode === 'single') return '指定模型：' + modelNameOf(state.singleModelId);
    if (state.modelMode === 'compare') return '对比 ' + state.compareIds.length + ' 个模型';
    return '—';
  }
  function updateModelBar() {
    var bar = $('#modelBar'); if (!bar) return;
    var sum = $('#mxSummary'); if (sum) sum.textContent = modelModeLabel();
    $$('#mxSeg button').forEach(function (b) {
      if (b.dataset.mode) b.classList.toggle('on', b.dataset.mode === state.modelMode);
    });
  }

  /* ---------------- 多模型中心弹窗 ---------------- */
  function openModelCenter() {
    openFeatureModal('多模型中心',
      '<div class="fm-empty">加载模型目录中…</div>',
      '<button class="fm-btn secondary" id="fmModelClose">关闭</button>' +
      '<button class="fm-btn primary" id="fmModelApply">应用当前选择</button>');
    $('#fmModelClose').addEventListener('click', closeFeatureModal);
    $('#fmModelApply').addEventListener('click', function () {
      updateModelBar();
      closeFeatureModal();
      toast('已更新模型模式：' + modelModeLabel());
    });
    wbFetch('/api/models/catalog')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (cat) { MODEL_CATALOG = cat; renderModelCenter(cat); })
      .catch(function (e) { $('#fmBody').innerHTML = '<div class="fm-empty">加载失败：' + (e.message || e) + '</div>'; });
  }

  function renderModelCenter(cat) {
    var provs = cat.providers || [], models = cat.models || [], strs = cat.strategies || {}, tts = cat.task_types || {};
    var modelHtml = models.map(function (m) {
      var cls = [];
      if (state.singleModelId === m.id) cls.push('on');
      if (state.compareIds.indexOf(m.id) >= 0) cls.push('cmp');
      cls.push(m.available ? 'ready' : 'off');
      var tag = (m.caps || []).map(function (c) { return '<span class="mx-cap">' + esc(c) + '</span>'; }).join('');
      return '<div class="mx-card ' + cls.join(' ') + '" data-id="' + esc(m.id) + '">' +
        '<div class="mx-card__top"><b>' + esc(m.name || m.id) + '</b>' +
        (m.available ? '<i class="mx-dot ok"></i>' : '<i class="mx-dot no"></i>') + '</div>' +
        '<div class="mx-card__meta">' + esc(_provName(provs, m.provider)) + ' · tier' + (m.tier != null ? m.tier : '-') + '</div>' +
        '<div class="mx-caps">' + tag + '</div></div>';
    }).join('');
    var stratHtml = Object.keys(strs).map(function (k) {
      return '<button class="mx-strat' + (state.strategy === k ? ' on' : '') + '" data-strat="' + k + '">' +
        esc(strs[k].name) + '<span>' + esc(strs[k].desc || '') + '</span></button>';
    }).join('');
    var ttHtml = Object.keys(tts).map(function (k) {
      return '<span class="mx-tt">' + esc(tts[k].name) + '</span>';
    }).join('');
    var provHtml = provs.map(function (p) {
      return '<div class="mx-prov' + (p.configured ? ' ok' : '') + '" data-pid="' + esc(p.id) + '" title="点击配置 ' + esc(p.name) + ' 的 API Key">' +
        '<b>' + esc(p.name) + '</b>' +
        '<span>' + (p.configured ? ('就绪 ' + p.models_ready + '/' + p.models_total) : '未配置 Key · 点击配置') + '</span></div>';
    }).join('');

    $('#fmBody').innerHTML =
      '<div class="mx-wrap">' +
        '<div class="mx-block"><div class="mx-block__h">供应商状态</div><div class="mx-provs">' + provHtml + '</div></div>' +
        '<div class="mx-block"><div class="mx-block__h">调度策略（自动路由 / 对比合并用）</div><div class="mx-strats">' + stratHtml + '</div></div>' +
        '<div class="mx-block"><div class="mx-block__h">任务类型画像（自动路由识别依据）</div><div class="mx-tts">' + ttHtml + '</div></div>' +
        '<div class="mx-block"><div class="mx-block__h">模型目录（单击=选「指定模型」；Ctrl/⌘ 点击=加入「对比」）</div>' +
          '<div class="mx-cards">' + modelHtml + '</div></div>' +
        '<p class="mx-tip">当前模式：<b id="fmModeLabel">' + modelModeLabel() + '</b></p>' +
      '</div>';

    $$('#fmBody .mx-strat').forEach(function (b) {
      b.addEventListener('click', function () {
        state.strategy = b.dataset.strat;
        saveMX();
        $$('#fmBody .mx-strat').forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on');
        var lbl = $('#fmModeLabel'); if (lbl) lbl.textContent = modelModeLabel();
      });
    });
    $$('#fmBody .mx-card').forEach(function (c) {
      c.addEventListener('click', function (e) {
        var id = c.dataset.id;
        if (e.metaKey || e.ctrlKey) {
          var idx = state.compareIds.indexOf(id);
          if (idx >= 0) { state.compareIds.splice(idx, 1); c.classList.remove('cmp'); }
          else { state.compareIds.push(id); c.classList.add('cmp'); }
          state.modelMode = 'compare';
        } else {
          state.singleModelId = id;
          state.modelMode = 'single';
          $$('#fmBody .mx-card').forEach(function (x) { x.classList.remove('on'); });
          c.classList.add('on');
          state.compareIds = state.compareIds.filter(function (x) { return x !== id; });
        }
        saveMX();
        var lbl = $('#fmModeLabel'); if (lbl) lbl.textContent = modelModeLabel();
      });
    });
    $$('#fmBody .mx-prov').forEach(function (el) {
      el.addEventListener('click', function () {
        var pid = el.dataset.pid;
        var p = (cat.providers || []).filter(function (x) { return x.id === pid; })[0];
        if (p) openProviderKeyModal(p);
      });
    });
  }

  /* ---------------- 供应商 Key 配置弹窗 ---------------- */
  function openProviderKeyModal(prov) {
    var isOffline = prov.id === 'offline';
    var homeLink = prov.home
      ? '<a class="mx-kf-link" href="' + esc(prov.home) + '" target="_blank" rel="noopener">前往申请 Key ↗</a>'
      : '';
    var statusTxt = prov.configured
      ? ('当前：已配置（' + prov.models_ready + '/' + prov.models_total + ' 模型就绪）')
      : '当前：未配置 Key，该供应商模型暂不可用';
    var body =
      '<div class="mx-key-form">' +
        '<div class="mx-kf-row">' +
          '<label>供应商：' + esc(prov.name) + '</label>' +
          '<span class="mx-kf-hint">' + statusTxt + (homeLink ? (' · ' + homeLink) : '') + '</span>' +
        '</div>' +
        (isOffline
          ? '<div class="mx-kf-secure">离线兜底无需 Key，开箱即用。</div>'
          : '<div class="mx-kf-row">' +
              '<label for="mxKeyInput">API Key</label>' +
              '<input id="mxKeyInput" type="password" autocomplete="off" placeholder="粘贴 ' + esc(prov.name) + ' 的 API Key" />' +
              '<span class="mx-kf-hint">保存后即时生效并持久化到本地数据库，重启服务不丢失。已配置供应商留空则保持原 Key 不变。</span>' +
            '</div>' +
            '<div class="mx-kf-row">' +
              '<label for="mxBaseInput">Base URL（OpenAI 兼容）</label>' +
              '<input id="mxBaseInput" type="text" placeholder="https://..." value="' + esc(prov.base_url || '') + '" />' +
            '</div>') +
        '<div class="mx-kf-actions">' +
          '<span class="mx-kf-status" id="mxKeyStatus"></span>' +
          '<button class="fm-btn secondary" id="mxKeyCancel">取消</button>' +
          (isOffline ? '' : '<button class="fm-btn" id="mxKeyTest">测试连接</button>') +
          (isOffline ? '' : '<button class="fm-btn primary" id="mxKeySave">保存</button>') +
        '</div>' +
      '</div>';
    openFeatureModal('配置供应商：' + prov.name, body,
      '<button class="fm-btn secondary" id="mxKeyBack">返回模型中心</button>');
    $('#mxKeyBack').addEventListener('click', function () {
      if (MODEL_CATALOG) renderModelCenter(MODEL_CATALOG); else openModelCenter();
    });
    if (isOffline) return;
    function back() { if (MODEL_CATALOG) renderModelCenter(MODEL_CATALOG); else openModelCenter(); }
    $('#mxKeyCancel').addEventListener('click', back);
    $('#mxKeySave').addEventListener('click', function () {
      var key = $('#mxKeyInput').value.trim();
      var base = $('#mxBaseInput').value.trim();
      var st = $('#mxKeyStatus');
      if (!key && !prov.configured) { st.className = 'mx-kf-status err'; st.textContent = '请填写 API Key'; return; }
      if (!key && !base) { st.className = 'mx-kf-status err'; st.textContent = '请填写 API Key 或 Base URL'; return; }
      st.className = 'mx-kf-status'; st.textContent = '保存中…';
      wbFetch('/api/models/providers', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: prov.id, api_key: key, base_url: base, enabled: true })
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function () {
          st.className = 'mx-kf-status ok'; st.textContent = '已保存并持久化 ✓';
          toast('已保存 ' + prov.name + ' 的 Key');
          return wbFetch('/api/models/catalog').then(function (r) { return r.json(); });
        })
        .then(function (cat) {
          MODEL_CATALOG = cat;
          renderModelCenter(cat);
        })
        .catch(function (e) {
          st.className = 'mx-kf-status err';
          st.textContent = '保存失败：' + (e.message || e);
        });
    });
    $('#mxKeyTest').addEventListener('click', function () {
      var key = $('#mxKeyInput').value.trim();
      var base = $('#mxBaseInput').value.trim();
      var st = $('#mxKeyStatus');
      if (!key && !prov.configured) { st.className = 'mx-kf-status err'; st.textContent = '请先填写 API Key'; return; }
      if (!key && !base) { st.className = 'mx-kf-status err'; st.textContent = '请先填写 API Key 或 Base URL'; return; }
      st.className = 'mx-kf-status'; st.textContent = '保存并测试中…';
      wbFetch('/api/models/providers', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: prov.id, api_key: key, base_url: base, enabled: true })
      })
        .then(function () { return wbFetch('/api/models/catalog').then(function (r) { return r.json(); }); })
        .then(function (cat) {
          MODEL_CATALOG = cat;
          var mid = (cat.models || []).filter(function (m) { return m.provider === prov.id; })[0];
          if (!mid) { st.className = 'mx-kf-status err'; st.textContent = '该供应商无可用模型'; return; }
          return wbFetch('/api/models/test', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: mid.id })
          }).then(function (r) { return r.json(); }).then(function (t) {
            if (t.ok) { st.className = 'mx-kf-status ok'; st.textContent = '连接正常 ✓ 延迟 ' + (t.latency_ms || 0) + 'ms'; }
            else { st.className = 'mx-kf-status err'; st.textContent = '连接失败：' + (t.err || '未知错误'); }
            renderModelCenter(MODEL_CATALOG);
          });
        })
        .catch(function (e) { st.className = 'mx-kf-status err'; st.textContent = '测试失败：' + (e.message || e); });
    });
  }

  /* ---------------- 多模型：自动路由 / 指定模型 回复 ---------------- */
  function routeModelReply(text) {
    var thinking = addMessage('assistant', '<span class="typing-dot"><i></i><i></i><i></i></span>');
    var body = { message: text, strategy: state.strategy };
    if (state.modelMode === 'single' && state.singleModelId) body.model_id = state.singleModelId;
    wbFetch('/api/models/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        // 后端以 ok:false + err 表达「模型不可用」，不能吞成「（无返回）」让用户干瞪眼
        if (d && d.ok === false) {
          var why = ({
            'no_key': '该模型所属服务商尚未配置 API Key',
            'timeout': '模型调用超时',
            'http_error': '服务商返回错误',
            'empty': '模型返回为空'
          })[d.err] || ('调用失败（' + (d.err || '未知原因') + '）');
          var cur = (d.model_name || d.model_id || '');
          thinking.querySelector('.msg-bubble').innerHTML =
            '<span class="mx-err">⚠ ' + why + '：' + cur + '</span><br>' +
            '<span class="mx-err__hint">已自动切回「工作台」模式，可直接重发；' +
            '或到「模型中心」为该服务商填入 Key 后再选它。</span>';
          // 关键：把死掉的"指定模型/自动路由"模式复位，避免用户每条都撞墙
          state.modelMode = 'workbench';
          try { localStorage.setItem('mx_modelMode', 'workbench'); } catch (e) {}
          state.busy = false; syncSend(); updateModelBar();
          toast('该模型不可用，已切回工作台模式');
          return;
        }
        var ans = (d && d.text) ? d.text : ((d && d.reply) || '（无返回）');
        var routed = d.routed || {};
        thinking.querySelector('.msg-bubble').textContent = '';
        return streamBubble(thinking, ans).then(function () {
          var note = document.createElement('div');
          note.className = 'mx-route-note';
          note.textContent = '▸ ' + (routed.model_name || (d.model_name || '')) +
            (d.auto ? '（自动路由）' : '（指定）') + ' · ' + (routed.reason || '');
          thinking.appendChild(note);
          state.busy = false; syncSend(); $('#composerInputDock').focus();
        });
      })
      .catch(function (e) {
        thinking.querySelector('.msg-bubble').textContent = '调用失败：' + (e.message || e);
        state.busy = false; syncSend();
      });
  }

  /* ---------------- 多模型：并行对比 + 仲裁合并 ---------------- */
  function runCompare(text) {
    var ids = state.compareIds.slice();
    var thinking = addMessage('assistant', '<span class="typing-dot"><i></i><i></i><i></i></span>');
    wbFetch('/api/models/compare', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, model_ids: ids, merge: true, strategy: state.strategy })
    })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        thinking.querySelector('.msg-bubble').innerHTML = renderCompareBlock(d);
        scrollBottom();
        state.busy = false; syncSend(); $('#composerInputDock').focus();
      })
      .catch(function (e) {
        thinking.querySelector('.msg-bubble').textContent = '对比失败：' + (e.message || e);
        state.busy = false; syncSend();
      });
  }

  function renderCompareBlock(d) {
    var parts = [];
    (d.results || []).forEach(function (r) {
      var cls = r.ok ? 'ok' : 'fail';
      parts.push('<div class="mx-cmp-item ' + cls + '"><div class="mx-cmp-h">' +
        esc(r.model_name || r.model_id) + ' · ' + (r.latency_ms || 0) + 'ms' +
        (r.ok ? '' : ' · 失败') + '</div><div class="mx-cmp-body">' +
        esc(r.text || (r.err || '无结果')) + '</div></div>');
    });
    if (d.merged && d.merged.ok) {
      parts.push('<div class="mx-cmp-merged"><div class="mx-cmp-h">仲裁合并（' + esc(d.merged.judge || '裁判') + '）</div>' +
        '<div class="mx-cmp-body">' + esc(d.merged.text || '') + '</div></div>');
    }
    return '<div class="mx-cmp">' + parts.join('') + '</div>';
  }

  /* ---------------- 多模型：任务管理区数据 ---------------- */
  function loadModelTasks() {
    var box = $('#mxTaskList'); if (!box) return;
    var statsBox = $('#mxStats');
    if (statsBox) statsBox.innerHTML = '<div class="empty-state">加载中…</div>';
    wbFetch('/api/models/tasks?limit=30')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        var st = d.stats || {};
        if (statsBox) statsBox.innerHTML = '<div class="mx-stat-row">' +
          '<span>任务总数 ' + (st.total || 0) + '</span>' +
          '<span>成功 ' + (st.ok || 0) + '</span>' +
          '<span>累计成本 ¥' + (st.cost || 0) + '</span>' +
          '<span>平均延时 ' + (st.avg_latency || 0) + 'ms</span></div>';
        var tasks = d.tasks || [];
        if (!tasks.length) { box.innerHTML = '<div class="empty-state">暂无任务</div>'; return; }
        box.innerHTML = tasks.map(function (t) {
          return '<div class="mx-task"><div class="mx-task__h"><b>' + esc(t.kind || '') + '</b> · ' +
            esc(t.task_type || '') + ' · ' + esc(t.model_used || '') + '</div>' +
            '<div class="mx-task__msg">' + esc((t.message || '').slice(0, 120)) + '</div>' +
            '<div class="mx-task__meta">' + (t.ok ? '✓' : '✗') + ' · ' + (t.latency_ms || 0) + 'ms · ¥' + (t.cost || 0) + '</div></div>';
        }).join('');
      })
      .catch(function (e) {
        if (statsBox) statsBox.innerHTML = '<div class="empty-state">加载失败</div>';
        box.innerHTML = '<div class="empty-state">加载失败：' + (e.message || e) + '</div>';
      });
  }

  /* ---------------- 成本管理弹窗 ---------------- */
  function openCostModal() {
    openFeatureModal('成本管理',
      '<div class="fm-empty">加载中…</div>',
      '<button class="fm-btn secondary" id="fmCostClose">关闭</button>');
    Promise.all([
      wbFetch('/api/usage/stats').then(function (r) { return r.json(); }),
      wbFetch('/api/wb/stats').then(function (r) { return r.json(); })
    ]).then(function (arr) {
      var u = arr[0], s = arr[1];
      var tot = u.total || u || {};
      var pt = tot.prompt_tokens || 0, ct = tot.completion_tokens || 0;
      var cost = typeof tot.cost === 'number' ? tot.cost : 0;
      var rows = [];
      rows.push('累计调用：' + (tot.calls || 0) + ' 次');
      rows.push('Token：' + pt + '（入） + ' + ct + '（出） = ' + (pt + ct));
      rows.push('累计成本：¥' + cost.toFixed(4));
      rows.push('工作台事件：' + (s.events || 0) + ' 条');
      var byModel = u.by_model || [];
      if (byModel.length) {
        rows.push('—— 分模型 ——');
        byModel.forEach(function (m) {
          rows.push((m.model || '?') + '：' + (m.calls || 0) + ' 次 · ¥' +
                    (typeof m.cost === 'number' ? m.cost.toFixed(4) : '0.0000'));
        });
      }
      $('#fmBody').innerHTML = '<ul class="fm-list">' + rows.map(function (x) { return '<li><div class="t">' + x + '</div></li>'; }).join('') + '</ul>';
    }).catch(function (e) {
      $('#fmBody').innerHTML = '<div class="fm-empty">加载失败：' + (e.message || e) + '</div>';
    });
    $('#fmCostClose').addEventListener('click', closeFeatureModal);
  }

  /* ---------------- 渲染：场景 Tabs ---------------- */
  function renderSceneTabs() {
    $('#sceneTabs').innerHTML = Object.keys(SCENES).map(function (s) {
      return '<button class="wb-scene-tabs__pill' + (s === state.scene ? ' wb-scene-tabs__pill--active' : '') +
             '" data-scene="' + s + '">' + s + '</button>';
    }).join('');
    $$('#sceneTabs .wb-scene-tabs__pill').forEach(function (b) {
      b.addEventListener('click', function () {
        state.scene = b.dataset.scene;
        renderSceneTabs();
        renderQuickActions();
      });
    });
  }

  /* ---------------- 渲染：快捷入口（原站 SVG） ---------------- */
  function renderQuickActions() {
    var list = SCENES[state.scene] || [];
    $('#quickActions').innerHTML = list.map(function (name) {
      var svg = ICON_MAP[name] ||
        '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="8" r="6" opacity=".35"/></svg>';
      return '<button class="quick-actions__item" type="button" data-name="' + name + '">' +
             '<span class="quick-actions__item-icon" aria-label="' + name + '" role="img">' + svg + '</span>' +
             name + '</button>';
    }).join('');
    $$('#quickActions .quick-actions__item').forEach(function (b) {
      b.addEventListener('click', function () {
        var box = $('#composerInput');
        box.textContent = '帮我完成「' + b.dataset.name + '」：';
        syncSend();
        box.focus();
        placeCaretEnd(box);
      });
    });
  }

  function placeCaretEnd(el) {
    var range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  /* ---------------- 渲染：会话列表 ---------------- */
  function renderConversations(kw) {
    var items = CONVERSATIONS.filter(function (c) {
      return !kw || c.title.indexOf(kw) >= 0;
    });
    $('#convListBody').innerHTML = items.length ? items.map(function (c, i) {
      return '<div class="conv-item' + (i === 0 ? ' is-active' : '') + '" data-id="' + c.id + '">' +
             '<span class="conv-dot"></span><span class="conv-title">' + c.title + '</span></div>';
    }).join('') : '<div class="empty-state">' + (kw ? '无匹配对话' : '暂无对话，发送消息后自动创建') + '</div>';

    $$('#convListBody .conv-item').forEach(function (el) {
      el.addEventListener('click', function () { selectConvo(el.dataset.id, el); });
    });
  }

  /* U2：切换到某会话：加载其历史消息（localStorage 持久化） */
  /* L5：欢迎态 ↔ 对话态草稿互通，避免切换/打开历史会话时把已输入内容弄丢 */
  function carryDraft(fromSel, toSel) {
    var from = $(fromSel), to = $(toSel);
    if (!from || !to) return;
    var txt = (from.textContent || '').trim();
    if (!txt) return;
    if ((to.textContent || '').trim()) return;   // 目标已有内容则不覆盖
    to.textContent = txt;
    from.textContent = '';
    if (typeof syncSend === 'function') syncSend();
  }

  function selectConvo(id, el) {
    // L5：打开历史会话前，把欢迎态草稿带到对话态输入框
    carryDraft('#composerInput', '#composerInputDock');
    $$('#convListBody .conv-item').forEach(function (x) { x.classList.remove('is-active'); });
    if (el) el.classList.add('is-active');
    state.activeConvo = id;
    state.messages = loadMsgs(id) || [];
    $('#messageList').innerHTML = '';
    if (state.messages.length) {
      state.messages.forEach(function (m) { renderMessage(m.role, m.text); });
      enterChatMode();
    } else {
      $('#welcomeStage').hidden = false;
      $('#messageScroll').hidden = true;
      $('#chatDock').hidden = true;
    }
    if (window.innerWidth <= 768) collapseSidebar();
  }

  /* U2：新建会话（首条消息触发） */
  function newConvo(firstText) {
    var id = 'c' + Date.now();
    var title = (firstText || '新对话').replace(/\s+/g, ' ').slice(0, 18) || '新对话';
    CONVERSATIONS.unshift({ id: id, title: title, time: '刚刚' });
    saveConvos(CONVERSATIONS);
    state.activeConvo = id;
    state.messages = [];
    renderConversations();
    return id;
  }

  /* ---------------- 渲染：概览 ---------------- */
  function renderOverview() {
    // V4：先静态占位，再尝试实时回填（/api/wb/stats 需鉴权，未登录则保留占位）
    var rows = [
      { key: '会话数', val: CONVERSATIONS.length, pct: Math.min(100, CONVERSATIONS.length * 12) },
      { key: '知识库文档', val: 26, pct: 78 },
      { key: '已注册工具', val: 12, pct: 45 },
      { key: '评估结果（Pass@1）', val: '87%', pct: 87 }
    ];
    function paint(rs) {
      $('#overviewPanel').innerHTML = rs.map(function (o) {
        return '<div class="ov-card"><div class="ov-row"><span class="ov-key">' + o.key +
               '</span><span class="ov-val">' + o.val + '</span></div>' +
               '<div class="ov-progress"><i style="width:' + o.pct + '%"></i></div></div>';
      }).join('');
    }
    paint(rows);
    if (!TOKEN) return;   // U1：未登录不打必然 401 的请求，避免首屏控制台噪音
    fetch('/api/wb/stats', { headers: { 'Authorization': 'Bearer ' + TOKEN } })
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) {
        if (!d) return;
        if (d.kb_docs != null) { rows[1].val = d.kb_docs; rows[1].pct = Math.min(100, d.kb_docs * 3); }
        if (d.tool_count != null) { rows[2].val = d.tool_count; rows[2].pct = Math.min(100, d.tool_count * 5); }
        if (d.pass_rate != null) { rows[3].val = d.pass_rate + '%'; rows[3].pct = Math.min(100, d.pass_rate); }
        paint(rows);
      }).catch(function () {});
  }

  /* ---------------- 侧边栏 ---------------- */
  function expandSidebar() { $('#convList').classList.add('is-expanded'); }
  function collapseSidebar() { $('#convList').classList.remove('is-expanded'); }

  /* ---------------- 输入与发送 ---------------- */
  function getText(el) { return (el.textContent || '').replace(/\u00a0/g, ' ').trim(); }

  function syncSend() {
    var main = getText($('#composerInput'));
    var dock = getText($('#composerInputDock'));
    $('#btnSend').disabled = !main || state.busy;
    $('#btnSendDock').disabled = !dock || state.busy;
  }

  function enterChatMode() {
    $('#welcomeStage').hidden = true;
    $('#messageScroll').hidden = false;
    $('#chatDock').hidden = false;
  }

  /* U8：极简 Markdown → HTML（转义优先，避免 XSS） */
  function escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function mdToHtml(src) {
    if (!src) return '';
    var s = escHtml(src);
    s = s.replace(/```([\s\S]*?)```/g, function (_, c) {
      return '<pre class="md-pre"><code>' + c.replace(/^\n/, '').replace(/\n$/, '') + '</code></pre>';
    });
    s = s.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>');
    s = s.replace(/^###\s+(.*)$/gm, '<h4>$1</h4>')
         .replace(/^##\s+(.*)$/gm, '<h3>$1</h3>')
         .replace(/^#\s+(.*)$/gm, '<h2>$1</h2>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/^\s*[-*]\s+(.*)$/gm, '<li>$1</li>');
    s = s.replace(/(<li>[\s\S]*?<\/li>)(?=\s*<li>|$)/g, function (m) { return '<ul>' + m + '</ul>'; });
    return s;
  }

  /* 渲染单条消息（U7 操作条：复制 / 重试；U8 Markdown） */
  function renderMessage(role, text) {
    var wrap = document.createElement('div');
    wrap.className = 'msg msg--' + (role === 'user' ? 'user' : 'assistant');
    var avatar = role === 'user'
      ? '<div class="msg-avatar">我</div>'
      : '<div class="msg-avatar msg-avatar--ai">M</div>';
    wrap.innerHTML = avatar + '<div class="msg-body"><div class="msg-bubble"></div><div class="msg-meta">' +
      new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) + '</div></div>';
    wrap.querySelector('.msg-bubble').innerHTML = mdToHtml(text);
    var bar = document.createElement('div');
    bar.className = 'msg-actions';
    bar.innerHTML = '<button class="msg-act" data-act="copy">复制</button><button class="msg-act" data-act="retry">重试</button>';
    wrap.querySelector('.msg-body').appendChild(bar);
    bar.querySelector('[data-act="copy"]').addEventListener('click', function () {
      if (navigator.clipboard) navigator.clipboard.writeText(text);
      toast('已复制');
    });
    bar.querySelector('[data-act="retry"]').addEventListener('click', function () {
      var last = null;
      for (var i = state.messages.length - 1; i >= 0; i--) {
        if (state.messages[i].role === 'user') { last = state.messages[i].text; break; }
      }
      if (last) send(last, $('#composerInput'));
    });
    $('#messageList').appendChild(wrap);
    scrollBottom();
    return wrap;
  }

  function addMessage(role, text) {
    state.messages.push({ role: role, text: text });
    saveMsgs(state.activeConvo, state.messages);   // U2：持久化到本会话
    return renderMessage(role, text);
  }

  function scrollBottom() {
    var s = $('#messageScroll');
    s.scrollTop = s.scrollHeight;
  }

  /* 后端降级：本地模拟流式回复 */
  function localReply(prompt) {
    return new Promise(function (resolve) {
      var answer = '【本地降级回复】未连接到 MiniYuxi 后端 /api/wb/chat，以下为占位输出。\n\n' +
        '你输入的是：' + prompt + '\n\n' +
        '接入真实后端后，此处将返回模型生成的流式回答，并在「引用来源」中回填检索命中的文档片段。';
      resolve(answer);
    });
  }

  /* L8：流式渲染优化——rAF 对齐帧 + 自适应步长 + 滚动降频 */
  function streamBubble(node, text) {
    return new Promise(function (resolve) {
      var bubble = node.querySelector('.msg-bubble');
      if (!bubble) { resolve(); return; }
      var len = text.length;
      var reduce = false;
      try { reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
      if (reduce || len < 48) { bubble.innerHTML = mdToHtml(text); scrollBottom(); resolve(); return; }

      var step = Math.max(4, Math.ceil(len / 150));   // 长文本约 150 帧走完，不再线性拖沓
      var i = 0, lastScroll = 0;
      var raf = window.requestAnimationFrame || function (cb) { return setTimeout(function () { cb(Date.now()); }, 16); };

      function tick(ts) {
        ts = ts || Date.now();
        i = Math.min(len, i + step);
        bubble.textContent = text.slice(0, i);
        if (!lastScroll || ts - lastScroll > 80) { scrollBottom(); lastScroll = ts; }
        if (i < len) { raf(tick); return; }
        bubble.innerHTML = mdToHtml(text);   // 收尾一次性渲染 Markdown
        scrollBottom();
        resolve();
      }
      raf(tick);
    });
  }

  function send(text, inputEl) {
    if (!text || state.busy) return;
    if (!TOKEN) { showLoginModal(); toast('请先登录后再对话'); pendingSend = { text: text }; return; }   // U1：无 token 引导登录
    // U2：首条消息自动建会话（否则消息无法归属、无从持久化）
    if (!state.activeConvo) newConvo(text);

    // ===== 多模型：对比模式 =====
    if (state.modelMode === 'compare') {
      if (!state.compareIds.length) { toast('请先到「模型中心」选择对比模型'); openModelCenter(); return; }
      state.busy = true; syncSend();
      enterChatMode();
      addMessage('user', text);
      inputEl.textContent = ''; syncSend();
      runCompare(text);
      return;
    }
    // ===== 多模型：自动路由 / 指定模型 =====
    if (state.modelMode === 'auto' || state.modelMode === 'single') {
      state.busy = true; syncSend();
      enterChatMode();
      addMessage('user', text);
      inputEl.textContent = ''; syncSend();
      routeModelReply(text);
      return;
    }

    state.busy = true;
    syncSend();
    enterChatMode();
    addMessage('user', text);
    inputEl.textContent = '';
    syncSend();

    var thinking = addMessage('assistant', '');
    thinking.querySelector('.msg-bubble').innerHTML =
      '<span class="typing-dot"><i></i><i></i><i></i></span>';

    var provider = '', model = '';
    try {
      provider = localStorage.getItem('wb_provider') || '';
      model = localStorage.getItem('wb_model') || '';
    } catch (e) {}
    var api = ensureToken().then(function () {
      if (!TOKEN) {   // U1：无 token 不再静默降级，直接引导登录
        throw new Error('未登录');
      }
      return fetch('/api/wb/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN },
        body: JSON.stringify({
          message: text, scene: state.scene,
          provider: provider || undefined, model: model || undefined,
          mode: state.mode,
          allow_full_access: state.allowFullAccess,
          expert: state.expert || undefined,
          skill: state.skill || undefined,
          connector_ids: state.connectorIds,
          attached_doc_ids: state.files.filter(function (f) { return f.id; }).map(function (f) { return f.id; })
        })
      });
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (d) {
      if (d && d.reply) {
        if (d.sources && d.sources.length) { state.sources = d.sources; renderSources(); }
        return d.reply;
      }
      throw new Error('bad payload');
    }).catch(function () { return localReply(text); });

    api.then(function (answer) {
      thinking.querySelector('.msg-bubble').textContent = '';
      return streamBubble(thinking, answer);
    }).then(function () {
      state.busy = false;
      syncSend();
      $('#composerInputDock').focus();
    });
  }

  /* ---------------- 引用来源 ---------------- */
  function renderSources() {
    $('#srcCount').textContent = state.sources.length;
    var box = $('#sourcesList');
    if (!state.sources.length) {
      box.innerHTML = '<div class="empty-state">暂无引用来源</div>';
      return;
    }
    box.innerHTML = state.sources.map(function (s) {
      return '<div class="source-item"><div class="source-title">' + (s.title || '未命名') +
             '</div><div class="source-url">' + (s.url || s.snippet || '') + '</div></div>';
    }).join('');
  }

  /* ---------------- 主题 ---------------- */
  function toggleTheme() {
    var dark = document.body.classList.toggle('dark');
    document.body.classList.toggle('light', !dark);
    try { localStorage.setItem('wb_theme', dark ? 'dark' : 'light'); } catch (e) {}
  }

  /* ---------------- 登录弹窗 ---------------- */
  function showLoginModal() {
    var existing = $('#loginModal');
    if (existing) { existing.hidden = false; return; }

    /* U1：默认口令提示只在回环地址（本机开发）显示，对外暴露时不再打印凭据 */
    var isLoopback = false;
    try {
      isLoopback = /^(localhost|127\.0\.0\.1|\[::1\]|::1)$/.test(location.hostname);
    } catch (e) {}

    var modal = document.createElement('div');
    modal.className = 'my-modal';
    modal.id = 'loginModal';
    modal.innerHTML =
      '<div class="my-modal__card">' +
        '<p class="my-modal__title">登录 MiniYuxi</p>' +
        '<div class="my-modal__row"><label>租户</label><input id="lmTenant" value="default"></div>' +
        '<div class="my-modal__row"><label>用户名</label><input id="lmUser" value="admin"></div>' +
        '<div class="my-modal__row"><label>密码</label><input id="lmPass" type="password" placeholder="' +
          (isLoopback ? '默认 admin123' : '请输入密码') + '"></div>' +
        '<div class="my-modal__err" id="lmErr"></div>' +
        '<div class="my-modal__actions">' +
          '<button class="my-modal__btn my-modal__btn--ghost" id="lmCancel">取消</button>' +
          '<button class="my-modal__btn my-modal__btn--primary" id="lmOk">登录</button>' +
        '</div>' +
        '<div class="my-modal__hint">' +
          (isLoopback
            ? '本机默认账号：default / admin / admin123，登录后请及时改密'
            : '请使用管理员分配的账号登录；对外访问请先在服务端完成口令加固') +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);

    function close() { modal.hidden = true; }
    $('#lmCancel').addEventListener('click', close);
    modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
    $('#lmOk').addEventListener('click', function () {
      var t = $('#lmTenant').value.trim() || 'default';
      var u = $('#lmUser').value.trim();
      var p = $('#lmPass').value;
      $('#lmErr').textContent = '登录中…';
      login(t, u, p).then(function (d) {
        close();
        var name = (d && d.username) ? d.username : u;
        var fu = $('#footerUser'); if (fu) fu.textContent = name + '（' + (d.role || '') + '）';
        toast('登录成功：' + name);
        state.unauthorized = false;
        renderOverview();      // 登录后补齐需鉴权的概览数据
        renderConversations();
        // U3：把登录前被拦下的那条消息自动续发出去
        if (pendingSend && pendingSend.text) {
          var queued = pendingSend.text;
          pendingSend = null;
          setTimeout(function () {
            var el = $('#composerInputDock');
            if (!el || el.offsetParent === null) el = $('#composerInput');
            send(queued, el);
          }, 120);
        }
      }).catch(function (e) {
        $('#lmErr').textContent = '登录失败：' + (e && e.message ? e.message : e);
      });
    });
    modal.hidden = false;
  }

  /* ================================================================
     左侧功能菜单（添加文件 / 引用对话中的文件 / 模式 / 专家 / 技能 / 连接器 / 允许完全访问）
     1:1 复刻 WorkBuddy 输入区「+」工具面板的交互与逻辑。
     ================================================================ */
  var MODES = [
    { id: 'agent', label: '默认', desc: 'Agent 模式：自主规划步骤、调用工具完成目标' },
    { id: 'plan',  label: '计划', desc: '仅输出可执行的分步骤计划，不执行工具' },
    { id: 'ask',   label: '问答', desc: '仅问答，不调用工具' }
  ];
  state.mode = 'agent';
  state.expert = '';
  state.expertName = '';
  state.skill = '';
  state.connectorIds = [];
  state.allowFullAccess = false;   // L4：默认受限，需用户显式开启「允许完全访问」
  state.files = []; // {id,name,status}

  function modeLabel(m) { for (var i=0;i<MODES.length;i++) if (MODES[i].id===m) return MODES[i].label; return '默认'; }

  function openToolMenu(anchor) {
    var menu = $('#toolMenu');
    var panel = menu.querySelector('.tool-menu__panel');
    menu.hidden = false;
    // 面板经 --tm-x/--tm-y 定位（见 index.html 内联样式：遮罩全屏 + 面板绝对定位）
    var r = anchor.getBoundingClientRect();
    var pw = panel.offsetWidth || 240;
    var ph = panel.offsetHeight || 380;
    var left = Math.max(12, r.left - (pw - r.width) / 2);
    left = Math.min(left, window.innerWidth - pw - 12);
    var top = r.top - ph - 8;                       // 默认：按钮上方
    if (top < 8) top = Math.min(r.bottom + 8, window.innerHeight - ph - 12);
    panel.style.setProperty('--tm-x', Math.round(Math.max(12, left)) + 'px');
    panel.style.setProperty('--tm-y', Math.round(Math.max(8, top)) + 'px');
    panel.focus();
  }
  function closeToolMenu() { $('#toolMenu').hidden = true; $('#toolDrawer').hidden = true; }

  /* 二级抽屉：复用 #toolDrawer，按类别渲染列表 */
  function escAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function openDrawer(title, items, opts) {
    opts = opts || {};
    $('#toolDrawerTitle').textContent = title;
    var body = $('#toolDrawerBody');
    if (!items || !items.length) {
      body.innerHTML = '<div class="tool-menu__empty">暂无可选' + escHtml(title) + '</div>';
    } else {
      body.innerHTML = items.map(function (it) {
        var active = opts.isActive ? opts.isActive(it) : false;
        var ttl = it.title || it.name || '未命名';
        return '<button class="tool-menu__option' + (active ? ' on' : '') +
               '" data-id="' + escAttr(it.id) + '" data-title="' + escAttr(ttl) + '">' +
               '<span class="tool-menu__option-main">' +
               '<span class="tool-menu__option-title">' + escHtml(ttl) + '</span>' +
               (it.sub ? '<span class="tool-menu__option-desc">' + escHtml(it.sub) + '</span>' : '') +
               '</span></button>';
      }).join('');
      $$('#toolDrawerBody .tool-menu__option').forEach(function (el) {
        el.addEventListener('click', function () {
          if (opts.onPick) opts.onPick(el.dataset.id, el.dataset.title);
          closeToolMenu();
        });
      });
    }
    $('#toolMenu').hidden = true;
    $('#toolDrawer').hidden = false;
  }

  function refreshToolHints() {
    $('#modeHint').textContent = modeLabel(state.mode);
    $('#expertHint').textContent = state.expertName || '未选择';
    $('#skillHint').textContent = state.skill ? ('已选 ' + state.skill) : '未选择';
    $('#connectorHint').textContent = state.connectorIds.length ? ('已选 ' + state.connectorIds.length + ' 个') : '未选择';
  }

  function refreshToolFooter() {
    try {
      var prov = localStorage.getItem('wb_provider') || '';
      var mod = localStorage.getItem('wb_model') || '';
      $('#toolMenuModel').textContent = (prov ? (prov + ' · ') : '均衡 · ') + (mod || '—');
    } catch (e) {}
    if (!TOKEN) return;   // U1：未登录不打必然 401 的请求
    wbFetch('/api/usage/stats').then(function (r) { return r.json(); }).then(function (u) {
      var tot = u.total || u || {};
      var cost = typeof tot.cost === 'number' ? tot.cost : 0;
      $('#toolMenuCost').textContent = cost.toFixed(4);
    }).catch(function () {});
  }

  /* 文件：添加 / 引用 */
  function handleAddFile(files) {
    if (!files || !files.length) return;
    Array.prototype.slice.call(files).forEach(function (f) {
      var rec = { id: '', name: f.name, status: '上传中' };
      state.files.push(rec);
      renderRefList();
      var fd = new FormData(); fd.append('file', f);
      wbFetch('/api/kb/upload', { method: 'POST', body: fd })
        .then(function (r) { return r.json().then(function (j) { return { r: r, j: j }; }); })
        .then(function (res) {
          if (res.r.ok) { rec.id = res.j.doc_id || ''; rec.status = '已附加'; }
          else { rec.status = '失败'; }
        })
        .catch(function () { rec.status = '失败'; })
        .finally(function () { renderRefList(); });
    });
  }

  function renderRefList() {
    [['#composerInput', '#refListMain'], ['#composerInputDock', '#refListDock']].forEach(function (pair) {
      var host = $(pair[1]);
      if (!host) return;
      if (!state.files.length) { host.innerHTML = ''; return; }
      host.innerHTML = '<div class="ref-list">' + state.files.map(function (f, idx) {
        var st = f.status === '已附加' ? '' : ' · ' + f.status;
        return '<span class="ref-list__item" data-idx="' + idx + '">' +
               '<span class="ref-name">' + f.name + '</span>' + st +
               '<button class="ref-remove" data-idx="' + idx + '" title="移除" aria-label="移除">×</button></span>';
      }).join('') + '</div>';
      $$('#' + pair[1].slice(1) + ' .ref-list__item').forEach(function (el) {
        el.addEventListener('click', function (e) {
          if (e.target.classList.contains('ref-remove')) return;
          insertAtCursor($(pair[0]), '@' + el.querySelector('.ref-name').textContent + ' ');
        });
      });
      $$('#' + pair[1].slice(1) + ' .ref-remove').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          state.files.splice(parseInt(btn.dataset.idx, 10), 1);   // U9：移除附件
          renderRefList();
        });
      });
    });
  }

  function insertAtCursor(el, text) {
    el.focus();
    var sel = window.getSelection();
    if (sel && sel.rangeCount && el.contains(sel.anchorNode)) {
      var range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(document.createTextNode(text));
      range.collapse(false);
    } else {
      el.textContent += text;
    }
    syncSend();
  }

  function openRefFileDrawer() {
    var items = state.files.map(function (f) {
      return { id: f.name, title: f.name, sub: f.status };
    });
    openDrawer('引用对话中的文件', items, {
      onPick: function (id) { insertAtCursor(document.activeElement && document.activeElement.isContentEditable ? document.activeElement : $('#composerInput'), '@' + id + ' '); }
    });
    if (!items.length) {
      // 仍允许关闭；空态已渲染
    }
  }

  function openModeDrawer() {
    openDrawer('模式', MODES.map(function (m) { return { id: m.id, title: m.label, sub: m.desc }; }), {
      isActive: function (it) { return it.id === state.mode; },
      onPick: function (id) { state.mode = id; refreshToolHints(); toast('模式：' + modeLabel(id)); }
    });
  }

  function openExpertDrawer() {
    wbFetch('/api/experts/list').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.experts) || [];
      openDrawer('专家', list.map(function (e) {
        return { id: e.id, title: e.name || e.id, sub: e.description || e.category || '' };
      }), {
        isActive: function (it) { return it.id === state.expert; },
        onPick: function (id, title) {
          state.expert = id; state.expertName = title; refreshToolHints();
          toast('已选择专家：' + title);
        }
      });
    }).catch(function (e) { toast('专家列表加载失败：' + (e.message || e)); });
  }

  function openSkillDrawer() {
    wbFetch('/api/skills/list').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.skills) || [];
      openDrawer('技能', list.map(function (s) {
        if (s.type === 'folder') {
          var trig = s.trigger ? (' · 触发：' + s.trigger) : '';
          return { id: s.name, title: s.name, sub: '【文件夹技能】' + (s.description || '') + trig };
        }
        return { id: s.id, title: ('question' in s ? s.question : (s.name || s.id)), sub: (s.tags && s.tags.join(', ')) || '' };
      }), {
        isActive: function (it) { return String(it.id) === String(state.skill); },
        onPick: function (id, title) {
          state.skill = id; refreshToolHints();
          insertAtCursor($('#composerInput'), '/' + title + ' ');
          toast('已调用技能：' + title);
        }
      });
    }).catch(function (e) { toast('技能列表加载失败：' + (e.message || e)); });
  }

  function openConnectorDrawer() {
    wbFetch('/api/connectors').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.connectors) || [];
      openDrawer('连接器', list.map(function (c) {
        return { id: c.id, title: c.name || c.id, sub: (c.kind || '') + ' · ' + (c.status || '') };
      }), {
        isActive: function (it) { return state.connectorIds.indexOf(it.id) >= 0; },
        onPick: function (id) {
          var i = state.connectorIds.indexOf(id);
          if (i >= 0) state.connectorIds.splice(i, 1); else state.connectorIds.push(id);
          refreshToolHints();
          toast('连接器：' + (i >= 0 ? '取消' : '已选') + ' ' + id);
        }
      });
    }).catch(function (e) { toast('连接器列表加载失败：' + (e.message || e)); });
  }

  function handleToolAction(action, anchor) {
    switch (action) {
      case 'add-file': $('#fileInput').click(); closeToolMenu(); break;
      case 'ref-file': openRefFileDrawer(); break;
      case 'mode': openModeDrawer(); break;
      case 'expert': openExpertDrawer(); break;
      case 'skill': openSkillDrawer(); break;
      case 'connector': openConnectorDrawer(); break;
      case 'allow-access': {
        var cb = $('#allowFullAccess');
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event('change'));
        break;
      }
      default: toast('功能：' + action);
    }
  }

  /* ---------------- 绑定 ---------------- */
  function bind() {
    $('#btnExpand').addEventListener('click', expandSidebar);
    $('#btnCollapse').addEventListener('click', collapseSidebar);
    $('#collapsedUpper').addEventListener('click', expandSidebar);

    $('#btnTheme').addEventListener('click', toggleTheme);
    $('#btnTheme2').addEventListener('click', toggleTheme);

    $('#btnLogin').addEventListener('click', showLoginModal);

    $('#btnNewChat').addEventListener('click', function () {
      carryDraft('#composerInputDock', '#composerInput');   // L5
      state.messages = [];
      state.activeConvo = '';
      $('#messageList').innerHTML = '';
      $('#welcomeStage').hidden = false;
      $('#messageScroll').hidden = true;
      $('#chatDock').hidden = true;
      renderConversations();
      if (window.innerWidth <= 768) collapseSidebar();
    });

    $('#convSearch').addEventListener('input', function (e) {
      renderConversations(e.target.value.trim());
    });

    // 输入联动
    ['#composerInput', '#composerInputDock'].forEach(function (sel) {
      var el = $(sel);
      el.addEventListener('input', syncSend);
      el.addEventListener('keyup', syncSend);
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          send(getText(el), el);
        }
      });
    });

    $('#btnSend').addEventListener('click', function () { send(getText($('#composerInput')), $('#composerInput')); });
    $('#btnSendDock').addEventListener('click', function () { send(getText($('#composerInputDock')), $('#composerInputDock')); });

    // 快捷插入 @ /
    $$('.composer-tool').forEach(function (b) {
      b.addEventListener('click', function () {
        var target = $(b.dataset.target ? '#' + b.dataset.target : '#composerInput');
        target.textContent += b.dataset.insert;
        target.focus();
        placeCaretEnd(target);
        syncSend();
      });
    });

    // 详情面板
    $('#btnToggleDetail').addEventListener('click', function () {
      // L1：窄屏下该按钮语义变为「关闭抽屉」
      if (isDrawerMode() && detailDrawer.open()) { detailDrawer.close(); return; }
      $('#detailPanelContainer').classList.add('is-collapsed');
    });
    var dtPanels = { overview: '#panelOverview', artifacts: '#panelArtifacts', models: '#panelModelTasks' };
    $$('#detailTabs .detail-tab').forEach(function (t) {
      t.addEventListener('click', function () {
        var tab = t.dataset.tab;
        $$('#detailTabs .detail-tab').forEach(function (x) { x.classList.remove('detail-tab--active'); });
        t.classList.add('detail-tab--active');
        Object.keys(dtPanels).forEach(function (k) {
          var el = $(dtPanels[k]); if (el) el.hidden = (k !== tab);
        });
        if (tab === 'models') loadModelTasks();
      });
    });

    /* L1：≤1024px 右栏改抽屉——头部按钮唤出、遮罩点击/Esc 关闭 */
    var drawer = $('#detailPanelContainer');
    var drawerBtn = $('#btnDetailDrawer');
    var drawerMask = $('#detailPanelDrawerBackdrop');

    detailDrawer = {
      open: function () { return !!(drawer && drawer.classList.contains('is-drawer-open')); },
      close: function () {
        if (drawer) drawer.classList.remove('is-drawer-open');
        if (drawerMask) {
          drawerMask.classList.remove('is-open');
          setTimeout(function () { if (!drawerMask.classList.contains('is-open')) drawerMask.hidden = true; }, 240);
        }
        if (drawerBtn) drawerBtn.setAttribute('aria-expanded', 'false');
      },
      toggle: function () {
        if (!drawer) return;
        var willOpen = !drawer.classList.contains('is-drawer-open');
        drawer.classList.toggle('is-drawer-open', willOpen);
        if (willOpen) drawer.classList.remove('is-collapsed');
        if (drawerMask) {
          if (willOpen) {
            drawerMask.hidden = false;
            requestAnimationFrame(function () { drawerMask.classList.add('is-open'); });
          } else { detailDrawer.close(); }
        }
        if (drawerBtn) drawerBtn.setAttribute('aria-expanded', String(willOpen));
      }
    };

    if (drawerBtn) drawerBtn.addEventListener('click', function () { detailDrawer.toggle(); });
    if (drawerMask) drawerMask.addEventListener('click', function () { detailDrawer.close(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && detailDrawer.open()) detailDrawer.close();
    });
    // 视口变宽离开抽屉断点时复位，避免固定定位残留
    window.addEventListener('resize', function () {
      if (!isDrawerMode() && detailDrawer.open()) detailDrawer.close();
    });

    $('#btnSources').addEventListener('click', function () { $('#sourcesPanel').hidden = false; });
    $('#btnSourcesClose').addEventListener('click', function () { $('#sourcesPanel').hidden = true; });

    // 多模型：路由条模式切换 + 模型中心入口
    $$('#mxSeg button').forEach(function (b) {
      b.addEventListener('click', function () {
        state.modelMode = b.dataset.mode;
        $$('#mxSeg button').forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on');
        updateModelBar();
      });
    });
    $('#btnModelCenter').addEventListener('click', openModelCenter);

    // 图片降级占位
    $$('img').forEach(function (img) {
      img.addEventListener('error', function () {
        img.style.display = 'none';
        if (!img.nextElementSibling || !img.nextElementSibling.classList.contains('img-fallback')) {
          var span = document.createElement('span');
          span.className = 'img-fallback';
          span.textContent = img.alt || '资源不可用';
          span.style.cssText = 'font-size:12px;color:var(--wb-text-tertiary)';
          if (img.parentNode) img.parentNode.insertBefore(span, img.nextSibling);
        }
      });
    });

    // 移动端：初始收起侧边栏
    if (window.innerWidth <= 768) collapseSidebar();

    /* ---- 左侧功能菜单（工具面板） ---- */
    function toggleToolMenu(btn) {
      if (!$('#toolMenu').hidden) { closeToolMenu(); return; }
      openToolMenu(btn);
    }
    $('#btnToolMenu').addEventListener('click', function (e) { e.stopPropagation(); toggleToolMenu(this); });
    $('#btnToolMenuDock').addEventListener('click', function (e) { e.stopPropagation(); toggleToolMenu(this); });

    // 菜单项点击分发
    $$('#toolMenu .tool-menu__item').forEach(function (it) {
      it.addEventListener('click', function (e) {
        e.stopPropagation();
        // 点击开关本体时交给 switch 自身处理，避免整行再触发一次导致抵消
        if (it.dataset.action === 'allow-access' && e.target.closest('.wb-switch')) return;
        handleToolAction(it.dataset.action, this);
      });
    });

    // 关闭：点击菜单外部 / 点击 footer 模型按钮
    document.addEventListener('click', function (e) {
      var menu = $('#toolMenu'), drawer = $('#toolDrawer');
      if (!menu.hidden && !menu.contains(e.target) && e.target.id !== 'btnToolMenu' && e.target.id !== 'btnToolMenuDock') closeToolMenu();
    });
    $('#toolMenu').addEventListener('click', function (e) { e.stopPropagation(); });

    // 二级抽屉返回
    $('#toolDrawerBack').addEventListener('click', function () { $('#toolDrawer').hidden = true; $('#toolMenu').hidden = false; });
    $('#toolDrawer').addEventListener('click', function (e) { if (e.target === $('#toolDrawer')) closeToolMenu(); });

    // 允许完全访问开关
    var allow = $('#allowFullAccess');
    allow.checked = state.allowFullAccess;
    allow.addEventListener('change', function () {
      state.allowFullAccess = allow.checked;
      toast('允许完全访问：' + (allow.checked ? '已开启' : '已关闭'));
    });

    // 添加文件 → 隐藏 input
    $('#fileInput').addEventListener('change', function () { handleAddFile(this.files); this.value = ''; });

    // U10：⌘K / Ctrl+K 聚焦输入框（快捷命令入口）
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        var box = (state.activeConvo ? $('#composerInputDock') : $('#composerInput'));
        if (box) box.focus();
      }
    });

    // 底部消耗/模型按钮：打开成本管理弹窗
    $('#toolMenuModelBtn').addEventListener('click', function () { closeToolMenu(); openCostModal(); });
  }

  /* ---------------- 初始化 ---------------- */
  function init() {
    try {
      var saved = localStorage.getItem('wb_theme');
      if (saved === 'dark') { document.body.classList.remove('light'); document.body.classList.add('dark'); }
    } catch (e) {}
    renderNav();
    renderSceneTabs();
    renderQuickActions();
    renderConversations();
    renderOverview();
    renderSources();
    refreshToolHints();
    bind();
    updateModelBar();
    syncSend();
    refreshToolFooter();
    // U1/U3：不再静默登录；已登录显示状态，否则提示「未登录」
    var fu = $('#footerUser');
    if (TOKEN) {
      if (fu) { try { var r = localStorage.getItem('miniyuxi_role'); fu.textContent = r ? ('管理员（' + r + '）') : '已登录'; } catch (e) {} }
    } else if (fu) {
      fu.textContent = '未登录';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
