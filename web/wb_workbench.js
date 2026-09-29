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
    { label: '工具市场', action: 'market' },
    { label: '数据出境', action: 'egress' },
    { label: '业务集成', action: 'biz' },
    { label: 'HRM人事', action: 'hrm' },
    { label: '流程', action: 'flow' },
    { label: '模型切换', action: 'model' },
    { label: '成本管理', action: 'cost' },
    { label: '管理', action: 'admin' },
    { label: '岗位工作台', action: 'roles' }
  ];

  /* ---------------- 左侧主导航（对齐 WorkBuddy 中文桌面版 7 项）----------------
     基准：docs/_shots/wb-baseline-20260924/01-左侧导航.png
     与 app.asar 提取的注册表逐项吻合：home/claw/project/market/automation/space/more
     注：MiniYuxi 自有模块（HRM人事/流程/成本管理/管理/岗位工作台）仍留在顶部导航，
         左侧导航与顶部导航并存，互不替代。 */
  var RAIL_ICONS = {
    task: '<path d="M2.6 3.1h10.8a.9.9 0 0 1 .9.9v6.2a.9.9 0 0 1-.9.9H7.5l-2.6 2.2v-2.2H2.6a.9.9 0 0 1-.9-.9V4a.9.9 0 0 1 .9-.9Z"/><path d="M8 5.3v3.4M6.3 7h3.4"/>',
    assistant: '<circle cx="8" cy="6.1" r="2.3"/><path d="M3.5 13.3a4.7 4.7 0 0 1 9 0"/>',
    project: '<circle cx="8" cy="8" r="5.6"/><circle cx="8" cy="4.5" r="1.05"/><circle cx="4.9" cy="10.1" r="1.05"/><circle cx="11.1" cy="10.1" r="1.05"/>',
    market: '<path d="M8 2.6a5.4 5.4 0 1 1-5.4 5.4"/><path d="M8 5.2a2.8 2.8 0 1 1-2.8 2.8"/>',
    schedule: '<circle cx="8" cy="8" r="5.6"/><path d="M8 4.7V8l2.5 1.6"/>',
    library: '<path d="M8 4.1C6.9 3.2 5.3 2.9 3.2 3.1v8.6c2.1-.2 3.7.1 4.8 1 1.1-.9 2.7-1.2 4.8-1V3.1C10.7 2.9 9.1 3.2 8 4.1Z"/><path d="M8 4.1v8.6"/>',
    more: '<rect x="3" y="3" width="4.2" height="4.2" rx="1.1"/><rect x="8.8" y="3" width="4.2" height="4.2" rx="1.1"/><rect x="3" y="8.8" width="4.2" height="4.2" rx="1.1"/><rect x="8.8" y="8.8" width="4.2" height="4.2" rx="1.1"/>'
  };

  var RAIL_ITEMS = [
    { id: 'new-task',  label: '新建任务', icon: 'task',      run: function () { startNewChat(); } },
    { id: 'assistant', label: '助理',     icon: 'assistant', run: function () { openAssistantModal(); } },
    { id: 'project',   label: '项目',     icon: 'project',   run: function () { openProjectModal(); } },
    { id: 'market',    label: '专家·技能·连接器', icon: 'market', children: [
        { id: 'experts',    label: '专家',   run: function () { openExpertDrawer(); } },
        { id: 'skills',     label: '技能',   run: function () { openSkillDrawer(); } },
        { id: 'connectors', label: '连接器', run: function () { openConnectorDrawer(); } }
      ] },
    { id: 'schedule',  label: '定时任务', icon: 'schedule',  run: function () { openScheduleModal(); } },
    { id: 'library',   label: '资料库',   icon: 'library',   run: function () { openKbModal(); } },
    // 「更多」子项 = 顶部导航的自有模块入口，提供第二路径（WorkBuddy 的 more 同样是子菜单）
    { id: 'more',      label: '更多',     icon: 'more',      children: NAV_ITEMS
        .filter(function (n) { return n.action !== 'new'; })
        .map(function (n) { return { id: n.action, label: n.label, run: function () { handleNavAction(n.action); } }; }) }
  ];

  function railIcon(name) {
    return '<svg class="nav-rail__icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
           'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
           (RAIL_ICONS[name] || '') + '</svg>';
  }

  /* 展开态：图标 + 文字，带二级菜单；折叠态：仅图标 */
  function renderNavRail() {
    var expanded = $('#navRail'), collapsed = $('#navRailCollapsed');
    if (expanded) {
      expanded.innerHTML = RAIL_ITEMS.map(function (it) {
        var caret = it.children
          ? '<svg class="nav-rail__caret" width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
            '<path d="M4.5 6h7L8 10.5 4.5 6Z"/></svg>'
          : '';
        var sub = it.children
          ? '<div class="nav-rail__sub" id="railSub_' + it.id + '" hidden>' +
              it.children.map(function (c) {
                return '<button type="button" class="nav-rail__sub-item" data-rail-sub="' + c.id + '">' + c.label + '</button>';
              }).join('') + '</div>'
          : '';
        return '<button type="button" class="nav-rail__item" data-rail="' + it.id + '"' +
               (it.children ? ' aria-expanded="false"' : '') + '>' +
               railIcon(it.icon) + '<span class="nav-rail__label">' + it.label + '</span>' + caret +
               '</button>' + sub;
      }).join('');
    }
    if (collapsed) {
      collapsed.innerHTML = RAIL_ITEMS.map(function (it) {
        return '<button type="button" class="nav-rail__item" data-rail="' + it.id + '" title="' + it.label + '" aria-label="' + it.label + '">' +
               railIcon(it.icon) + '</button>';
      }).join('');
    }
    bindNavRail();
  }

  function bindNavRail() {
    $$('#navRail .nav-rail__item, #navRailCollapsed .nav-rail__item').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var it = RAIL_ITEMS.filter(function (x) { return x.id === btn.dataset.rail; })[0];
        if (!it) return;
        if (it.children) {                       // 有子项：就地展开/收起
          var sub = $('#railSub_' + it.id);
          if (sub) {
            var willOpen = sub.hidden;
            sub.hidden = !willOpen;
            btn.setAttribute('aria-expanded', String(willOpen));
            btn.classList.toggle('is-active', willOpen);
          }
          return;
        }
        $$('#navRail .nav-rail__item').forEach(function (x) { x.classList.remove('is-active'); });
        btn.classList.add('is-active');
        if (it.run) it.run();
      });
    });
    $$('#navRail .nav-rail__sub-item').forEach(function (b) {
      b.addEventListener('click', function () {
        var it = RAIL_ITEMS.filter(function (x) { return x.id === 'market' || x.id === 'more'; })
          .reduce(function (acc, x) { return acc.concat(x.children || []); }, [])
          .filter(function (c) { return c.id === b.dataset.railSub; })[0];
        $$('#navRail .nav-rail__sub-item').forEach(function (x) { x.classList.remove('is-active'); });
        b.classList.add('is-active');
        if (it && it.run) it.run();
      });
    });
  }


  // 场景分组：对齐 WorkBuddy 中文桌面版截图（docs/_shots/wb-baseline-20260924/）
  //   - 代码开发 / 设计创意 两组在截图里完整可见 → 逐项照搬
  //   - 日常办公 在截图里被横向截断（仅 3 项可见 + 右箭头）→ 已知项前置，其余保留，待补截图
  var SCENES = {
    '日常办公': ['数据分析及可视化', '个人工作台', '幻灯片', '视频生成', '深度研究',
                 '文档处理', '金融服务', '产品管理', '设计', '邮件编辑'],
    '代码开发': ['日常开发', '网站开发', '小程序', 'Agent 应用', 'Skill 开发', 'CI/CD'],
    '设计创意': ['生成图片', '生成视频', '品牌设计', '视觉海报', '运营海报', 'PPT设计']
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
      case 'office': openOfficeSurface(); break;
      case 'market': openMarketDrawer(); break;
      case 'experts': window.open('/experts-market.html', '_blank'); break;
      case 'egress': openEgressModal(); break;
      case 'biz': openBizPanel(); break;
      default: toast('功能入口：' + action);
    }
  }

  /* ---------------- 办公操作面（Univer 办公套件 · 纯本地） ----------------
     懒加载：仅首次点击才拉取 /office/office-host.js 与 Univer 离线包（数 MB），
     避免拖慢首屏；资产未构建时后端返回 503，此处给出可执行的构建指引。
     合规：快照只存本机 SQLite，不触达外部服务，也不回退任何 CDN。 */
  function openOfficeSurface(kind) {
    function boot() {
      if (!window.MiniYuxiOffice) { toast('办公套件未就绪：请先构建 Univer 资产'); return; }
      window.MiniYuxiOffice.open(kind || 'sheet');
    }
    if (window.MiniYuxiOffice) { boot(); return; }
    var s = document.createElement('script');
    s.src = '/office/office-host.js';
    s.onload = boot;
    s.onerror = function () {
      toast('办公套件未就绪：cd tools/office-bundle && npm install && npm run build');
    };
    document.head.appendChild(s);
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

  /* ---------------- 助理（对齐 WorkBuddy 左侧导航第 2 项）----------------
     如实呈现：后端有 /api/subagent（生成器/评判器分离），但无 WorkBuddy 那种
     「Agent 同事」实体。这里列出后端实际注册的子 Agent，不造数据。 */
  function openAssistantModal() {
    openFeatureModal('子 Agent（助理）',
      '<div class="fm-sub">可选用的 Agent 同事实体：内置只读「制度检索员」+ 你自定义的子 Agent。任务在主 Agent 之外隔离执行，结论摘要回传。</div>' +
      '<div id="asstList"><div class="fm-empty">加载中…</div></div>' +
      '<div class="asst-dispatch" id="asstDispatch" hidden>' +
        '<div class="asst-dispatch__head">派发任务给：<b id="asstPickName"></b></div>' +
        '<textarea id="asstTask" class="fm-input" rows="3" placeholder="描述要交给子 Agent 完成的任务…"></textarea>' +
        '<div style="margin-top:8px"><button class="fm-btn" id="asstRun">运行</button>' +
        '<button class="fm-btn secondary" id="asstClear">取消</button></div>' +
        '<div id="asstResult" class="fm-ask-res" hidden></div>' +
      '</div>' +
      '<details class="asst-new"><summary>＋ 新建子 Agent</summary>' +
        '<div class="asst-form">' +
          '<input id="newName" class="fm-input" placeholder="名称（如：薪酬核算员）">' +
          '<input id="newRole" class="fm-input" placeholder="角色说明（可选）">' +
          '<textarea id="newPrompt" class="fm-input" rows="3" placeholder="系统提示词：定义它的职责与口径"></textarea>' +
          '<label class="asst-ro"><input type="checkbox" id="newRO"> 只读（仅检索知识库，不外发 / 不写）</label>' +
          '<button class="fm-btn" id="newSave">保存子 Agent</button>' +
        '</div>' +
      '</details>',
      '<button class="fm-btn secondary" id="asstClose">关闭</button>');
    $('#asstClose').addEventListener('click', closeFeatureModal);
    $('#asstRun').addEventListener('click', asstRun);
    $('#asstClear').addEventListener('click', function () { var x = $('#asstDispatch'); if (x) x.hidden = true; });
    $('#newSave').addEventListener('click', asstCreate);
    window.__asstPickId = '';
    window.__asstPick = function (id, name) {
      window.__asstPickId = id;
      var n = $('#asstPickName'); if (n) n.textContent = name;
      var box = $('#asstDispatch'); if (box) box.hidden = false;
      var t = $('#asstTask'); if (t) t.focus();
    };
    loadAssistantAgents();
  }

  function loadAssistantAgents() {
    wbFetch('/api/subagent').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.agents) || [];
      var box = $('#asstList');
      if (!box) return;
      if (!list.length) { box.innerHTML = '<div class="fm-empty">无可用子 Agent</div>'; return; }
      box.innerHTML = list.map(function (a) {
        var ro = a.read_only ? ' · 只读' : '';
        var builtin = a.builtin ? ' · 内置' : '';
        var del = a.builtin ? '' : ' <button class="cmd-del" data-del="' + escAttr(a.id) + '">✕</button>';
        return '<div class="fm-card asst-card"><div class="fm-card-title">' + escHtml(a.name) +
               '<button class="fm-btn small" data-use="' + escAttr(a.id) + '" data-name="' + escAttr(a.name) + '">选用</button></div>' +
               '<div class="fm-sub">' + escHtml(a.role || a.system_prompt || '') + ro + builtin + del + '</div></div>';
      }).join('');
      $$('#asstList [data-use]').forEach(function (b) {
        b.addEventListener('click', function () { window.__asstPick(b.dataset.use, b.dataset.name); });
      });
      $$('#asstList [data-del]').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          wbFetch('/api/subagent/' + encodeURIComponent(b.dataset.del), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function () { toast('已删除子 Agent'); loadAssistantAgents(); })
            .catch(function (er) { toast('删除失败：' + (er.message || er)); });
        });
      });
    }).catch(function (e) {
      var box = $('#asstList'); if (box) box.innerHTML = '<div class="fm-empty">接口不可用：' + (e.message || e) + '</div>';
    });
  }

  function asstCreate() {
    var name = ($('#newName').value || '').trim();
    if (!name) { toast('请填写名称'); return; }
    var body = {
      name: name,
      role: ($('#newRole').value || '').trim(),
      system_prompt: ($('#newPrompt').value || '').trim(),
      read_only: !!(document.getElementById('newRO') && document.getElementById('newRO').checked)
    };
    wbFetch('/api/subagent', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function () {
        toast('已创建子 Agent');
        var n = document.getElementById('newName'); if (n) n.value = '';
        var r2 = document.getElementById('newRole'); if (r2) r2.value = '';
        var p = document.getElementById('newPrompt'); if (p) p.value = '';
        var ro = document.getElementById('newRO'); if (ro) ro.checked = false;
        loadAssistantAgents();
      })
      .catch(function (e) { toast('创建失败：' + (e.message || e)); });
  }

  function asstRun() {
    var task = ($('#asstTask').value || '').trim();
    var aid = window.__asstPickId || '';
    if (!task) { toast('请输入任务'); return; }
    var res = $('#asstResult');
    if (!res) return;
    res.hidden = false;
    res.innerHTML = '<div class="fm-empty">子 Agent 执行中…</div>';
    wbFetch('/api/subagent/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: task, agent_id: aid, max_rounds: 3, criteria: { min_len: 10, must_contain: [] } })
    })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        var verdict = d.passed ? '✅ 通过' : '⚠️ 未达标';
        var reasons = (d.verdict && d.verdict.reasons && d.verdict.reasons.length)
          ? '<div class="fm-sub">评判：' + esc(d.verdict.reasons.join('；')) + '</div>' : '';
        res.innerHTML = '<div class="fm-ans">' + esc(d.draft || '') + '</div>' +
          '<div class="fm-meta">轮次 ' + (d.rounds || 0) + ' · ' + verdict +
          ' · Agent：' + esc((d.agent && d.agent.name) || aid) + '</div>' + reasons;
      })
      .catch(function (e) { res.innerHTML = '<div class="fm-empty">执行失败：' + (e.message || e) + '</div>'; });
  }

  /* ---------------- 项目（对齐 WorkBuddy 左侧导航第 3 项）----------------
     ⚠️ 后端无 projects 模块。此页如实说明，不做假界面。 */
  function openProjectModal() {
    openFeatureModal('项目',
      '<div class="fm-sub">⚠️ 该模块后端尚未实现</div>' +
      '<div class="fm-note">' +
      'WorkBuddy 桌面版的「项目」是任务/文件的组织容器。MiniYuxi 后端目前<b>没有 projects 模块</b>' +
      '（<code>core/</code> 下无对应实现，<code>api.py</code> 无 <code>/api/projects</code> 路由）。' +
      '为不误导使用，此页不做界面填充。<br><br>' +
      '要落地需要：① 建 <code>projects</code> 表（id/name/owner/status）；② 加 <code>/api/projects</code> CRUD 路由；' +
      '③ 会话与项目关联。<b>属后端开发任务，需另行排期。</b>' +
      '</div>',
      '<button class="fm-btn secondary" id="projClose">关闭</button>');
    $('#projClose').addEventListener('click', closeFeatureModal);
  }

  /* ---------------- 定时任务（对齐 WorkBuddy 左侧导航第 5 项）---------------- */
  function openScheduleModal() {
    openFeatureModal('定时任务',
      '<div class="fm-sub">后端调度器已注册的任务（数据来自 <code>/api/schedules</code>）</div>' +
      '<div id="schList"><div class="fm-empty">加载中…</div></div>',
      '<button class="fm-btn secondary" id="schClose">关闭</button>');
    $('#schClose').addEventListener('click', closeFeatureModal);

    wbFetch('/api/schedules').then(function (r) { return r.json(); }).then(function (rows) {
      var list = Array.isArray(rows) ? rows : [];
      if (!list.length) { $('#schList').innerHTML = '<div class="fm-empty">暂无定时任务</div>'; return; }
      $('#schList').innerHTML = list.map(function (j) {
        var spec = j.spec || {};
        var desc = spec.kind === 'interval' ? ('每 ' + (spec.seconds || '?') + ' 秒')
                 : spec.kind === 'cron' ? ('cron: ' + (spec.expr || spec.cron || '?'))
                 : spec.kind === 'at' ? ('定时于 ' + (spec.at || '?')) : (spec.kind || '—');
        return '<div class="fm-card"><div class="fm-card-title">' + (j.name || j.id) + '</div>' +
               '<div class="fm-sub">' + desc + ' · 状态 ' + (j.status || '—') +
               ' · 上次运行 ' + (j.last_run || '从未') + '</div></div>';
      }).join('');
    }).catch(function () {
      $('#schList').innerHTML = '<div class="fm-empty">接口不可用，无法读取定时任务</div>';
    });
  }

  /* ---------------- 知识库弹窗（制度地图 + 可点击出处）----------------
     逆向自 ZCode 企业知识库检索：① 按场景分类找制度；② 每个结论带 [编号] 出处，
     可点击跳转查看原文；③ 上传即归类。 */
  var KB_DOMAINS = [
    { key: '招聘', icon: '🧲' }, { key: '薪酬', icon: '💰' }, { key: '社保', icon: '🛡' },
    { key: '离职', icon: '👋' }, { key: '绩效', icon: '📈' }, { key: '合同', icon: '📄' },
    { key: '合规', icon: '⚖️' }, { key: '其他', icon: '🗂' }
  ];
  var KB_FILTER = '';
  function openKbModal() {
    var domainCards = KB_DOMAINS.map(function (dm) {
      return '<button class="kb-domain" data-cat="' + escAttr(dm.key) + '">' + dm.icon + ' ' + dm.key + '</button>';
    }).join('');
    var catOpts = KB_DOMAINS.map(function (d) {
      return '<option value="' + escAttr(d.key) + '">' + d.key + '</option>';
    }).join('');
    openFeatureModal('HR 知识库 · 制度地图',
      '<div class="fm-sub">按场景找制度（点击下方分类筛选已上传文档）</div>' +
      '<div class="kb-domains" id="kbDomains">' + domainCards + '</div>' +
      '<div class="fm-ask"><input class="fm-input" id="fmKbQ" placeholder="向知识库提问（制度 / 流程 / 政策）">' +
        '<button class="fm-btn" id="fmKbAsk">提问</button></div>' +
      '<div class="fm-ask-res" id="fmKbRes" hidden></div>' +
      '<div id="fmKbDoc" class="fm-doc" hidden></div>' +
      '<div class="kb-upload"><span class="kb-upload__label">导入制度文件</span>' +
        '<input type="file" id="fmKbFile" accept=".txt,.md,.markdown,.docx,.pdf">' +
        '<select id="fmKbCat" class="fm-input">' + catOpts + '</select>' +
        '<button class="fm-btn" id="fmKbImport">导入</button></div>' +
      '<div id="fmKbList"><div class="fm-empty">加载中…</div></div>',
      '<button class="fm-btn secondary" id="fmKbRefresh">刷新文档列表</button>');
    $('#fmKbRefresh').addEventListener('click', function () { loadKbDocs(); });
    $('#fmKbAsk').addEventListener('click', kbAsk);
    $('#fmKbQ').addEventListener('keydown', function (e) { if (e.key === 'Enter') kbAsk(); });
    $('#fmKbImport').addEventListener('click', kbImport);
    $('#kbDomains').addEventListener('click', function (e) {
      var b = e.target.closest('.kb-domain'); if (!b) return;
      KB_FILTER = (KB_FILTER === b.dataset.cat) ? '' : b.dataset.cat;
      $$('#kbDomains .kb-domain').forEach(function (x) { x.classList.toggle('on', x.dataset.cat === KB_FILTER); });
      loadKbDocs();
    });
    loadKbDocs();
  }
  function loadKbDocs() {
    var body = $('#fmKbList');
    if (!body) body = $('#fmBody');
    body.innerHTML = '<div class="fm-empty">加载中…</div>';
    wbFetch('/api/kb/docs')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (docs) {
        if (KB_FILTER) docs = docs.filter(function (d) { return (d.category || '其他') === KB_FILTER; });
        if (!docs || !docs.length) {
          body.innerHTML = '<div class="fm-empty">知识库暂无' + (KB_FILTER ? ('「' + KB_FILTER + '」类') : '') + '文档，可通过上方「导入制度文件」上传。</div>';
          return;
        }
        body.innerHTML = '<ul class="fm-list">' + docs.map(function (d) {
          var cat = d.category || '其他';
          return '<li><div class="t"><div>' + (d.title || '未命名') + '</div>' +
                 '<div class="s">' + (d.source || d.id || '') + ' · ' + (d.n_chunks || 0) + ' chunks · ' + (d.created_at || '') +
                 ' · <span class="kb-cat">' + escHtml(cat) + '</span></div></div></li>';
        }).join('') + '</ul>';
      })
      .catch(function (e) { body.innerHTML = '<div class="fm-empty">加载失败：' + (e.message || e) + '</div>'; });
  }
  function kbImport() {
    var f = $('#fmKbFile');
    if (!f || !f.files || !f.files.length) { toast('请先选择文件'); return; }
    var cat = ($('#fmKbCat').value || '其他');
    var fd = new FormData();
    fd.append('file', f.files[0]);
    fd.append('category', cat);
    var btn = $('#fmKbImport');
    if (btn) { btn.disabled = true; btn.textContent = '导入中…'; }
    wbFetch('/api/kb/upload', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.doc_id) { toast('已导入：' + (j.title || '')); if (f) f.value = ''; KB_FILTER = cat; loadKbDocs(); }
        else { toast('导入失败：' + JSON.stringify(j)); }
      })
      .catch(function (e) { toast('导入失败：' + (e.message || e)); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = '导入'; } });
  }
  function kbAsk() {
    var q = ($('#fmKbQ').value || '').trim();
    if (!q) { toast('请输入问题'); return; }
    var res = $('#fmKbRes');
    var docPanel = $('#fmKbDoc');
    if (docPanel) docPanel.hidden = true;
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
        // 内联 [n] 高亮（与引用列表编号一致），可点击跳转
        var safe = esc(ans).replace(/\[(\d+)\]/g, function (m, n) {
          return '<mark class="cite-mark" data-cite="' + n + '">' + m + '</mark>';
        });
        var cites = (d.citations || []).slice(0, 5).map(function (c, i) {
          var idx = i + 1;
          var t = c.title || c.source || (c.text || '').toString().slice(0, 120) || '';
          var jump = c.doc_id ? '<button class="cite-jump" data-doc="' + escAttr(c.doc_id) + '" data-idx="' + idx + '">查看原文</button>' : '';
          return '<li><span class="cite-idx">[' + idx + ']</span> ' + esc(t) +
                 (c.doc_id ? ' <span class="cite-doc">' + esc(c.doc_id) + '</span>' : '') + ' ' + jump + '</li>';
        }).join('');
        res.innerHTML = '<div class="fm-ans">' + safe + '</div>' +
          (cites ? '<div class="fm-cites">参考来源：<ul>' + cites + '</ul></div>' : '') +
          '<div class="fm-meta">来源：' + esc(d.mode || 'native') + '</div>';
        $$('#fmKbRes .cite-jump').forEach(function (el) {
          el.addEventListener('click', function () { kbJump(el.dataset.doc, el.dataset.idx); });
        });
        $$('#fmKbRes .cite-mark').forEach(function (mk) {
          mk.addEventListener('click', function () {
            var j = document.querySelector('#fmKbRes .cite-jump[data-idx="' + mk.dataset.cite + '"]');
            if (j) kbJump(j.dataset.doc, mk.dataset.cite);
          });
        });
      })
      .catch(function (e) { res.innerHTML = '<div class="fm-empty">提问失败：' + (e.message || e) + '</div>'; });
  }
  function kbJump(docId, idx) {
    var panel = $('#fmKbDoc');
    if (!panel) return;
    panel.hidden = false;
    panel.innerHTML = '<div class="fm-empty">加载原文中…</div>';
    wbFetch('/api/kb/docs/' + encodeURIComponent(docId))
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (doc) {
        panel.innerHTML = '<div class="fm-doc-title">' + esc(doc.title || '') + ' <span class="kb-cat">' + escHtml(doc.category || '其他') + '</span></div>' +
          '<pre class="fm-doc-text">' + esc(doc.text || '(空)') + '</pre>';
        var mk = document.querySelector('#fmKbRes mark[data-cite="' + idx + '"]');
        if (mk) { mk.classList.add('cite-flash'); try { mk.scrollIntoView({ block: 'center' }); } catch (e) {} }
      })
      .catch(function (e) { panel.innerHTML = '<div class="fm-empty">原文加载失败：' + (e.message || e) + '</div>'; });
  }

  /* ---------------- 本地工具市场（抄 treg 理念 · 本地化 · 不接远端凭据） ----------------
     分类 chips + 关键词搜索 + 启停切换。所有数据经 /api/market/* 读本地 SQLite，
     启停接口要求 agent.run 权限并写审计；调用本身仍走 /api/tools/call（受审批门管理）。
     合规红线：不复制 treg 的 OpenRouter-for-tools 形态，也不引入远端工具目录拉取。 */
  var MARKET_STATE = { category: '', q: '', enabled_only: false };

  function openMarketDrawer() {
    openFeatureModal('本地工具市场',
      '<div class="fm-sub">浏览 / 启停本机注册的工具（内置 + 本地 MCP）。所有数据走本地 SQLite，不向任何远端服务注入凭据。</div>' +
      '<div class="kb-domains" id="marketCats"><span class="fm-empty">加载分类…</span></div>' +
      '<div class="fm-ask"><input class="fm-input" id="fmMarketQ" placeholder="按名称或描述关键词筛选">' +
        '<button class="fm-btn secondary" id="fmMarketEnabledOnly">仅看已启用</button>' +
        '<button class="fm-btn" id="fmMarketRefresh">刷新</button></div>' +
      '<div id="fmMarketList"><div class="fm-empty">加载中…</div></div>',
      '<span class="fm-sub" style="margin:0">提示：停用后工具仍存在注册表，但 /api/tools/call 调用时被拒。</span>');
    var eb = $('#fmMarketEnabledOnly');
    if (eb) {
      eb.addEventListener('click', function () {
        MARKET_STATE.enabled_only = !MARKET_STATE.enabled_only;
        eb.textContent = MARKET_STATE.enabled_only ? '查看全部' : '仅看已启用';
        loadMarket();
      });
    }
    var q = $('#fmMarketQ');
    if (q) q.addEventListener('input', function (e) { MARKET_STATE.q = e.target.value.trim(); loadMarket(); });
    var rf = $('#fmMarketRefresh');
    if (rf) rf.addEventListener('click', loadMarket);
    loadMarket();
  }

  function renderMarketCategories(cats) {
    var host = document.getElementById('marketCats');
    if (!host) return;
    var html = '<button class="kb-domain' + (MARKET_STATE.category === '' ? ' on' : '') + '" data-cat="">全部</button>';
    (cats || []).forEach(function (c) {
      html += '<button class="kb-domain' + (MARKET_STATE.category === c.category ? ' on' : '') +
              '" data-cat="' + escAttr(c.category) + '">' + esc(c.category) + ' <small>(' + c.count + ')</small></button>';
    });
    host.innerHTML = html;
    $$('#marketCats .kb-domain').forEach(function (b) {
      b.addEventListener('click', function () {
        MARKET_STATE.category = (MARKET_STATE.category === b.dataset.cat) ? '' : b.dataset.cat;
        renderMarketCategories(cats);  // 重画高亮
        loadMarket();
      });
    });
  }

  function loadMarket() {
    var body = $('#fmMarketList');
    if (!body) return;
    body.innerHTML = '<div class="fm-empty">加载中…</div>';
    var qs = '?';
    if (MARKET_STATE.category) qs += 'category=' + encodeURIComponent(MARKET_STATE.category) + '&';
    if (MARKET_STATE.q) qs += 'q=' + encodeURIComponent(MARKET_STATE.q) + '&';
    if (MARKET_STATE.enabled_only) qs += 'enabled_only=true&';
    wbFetch('/api/market/list' + qs)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        renderMarketCategories(d.categories || []);
        if (!d.tools || !d.tools.length) {
          body.innerHTML = '<div class="fm-empty">没有匹配的工具</div>';
          return;
        }
        body.innerHTML = d.tools.map(function (t) {
          var tags = (t.tags || []).map(function (x) {
            return '<span class="mkt-tag">' + esc(x) + '</span>';
          }).join('');
          var badges = '<span class="mkt-cat">' + esc(t.category || '未分类') + '</span>' +
            '<span class="mkt-src mkt-src--' + esc(t.source || 'unknown') + '">' + esc(t.source || 'unknown') + '</span>';
          if (t.requires_approval) badges += '<span class="mkt-badge">需审批</span>';
          if (t.risk === 'warn') badges += '<span class="mkt-badge mkt-badge--warn">warn</span>';
          if (t.risk === 'critical') badges += '<span class="mkt-badge mkt-badge--crit">critical</span>';
          var togCls = t.enabled ? 'mkt-toggle on' : 'mkt-toggle';
          var togLbl = t.enabled ? '已启用' : '已停用';
          return '<div class="mkt-card' + (t.enabled ? '' : ' is-off') + '">' +
            '<div class="mkt-head">' +
              '<span class="mkt-name">' + esc(t.name) + '</span>' +
              '<span class="' + togCls + '" data-name="' + escAttr(t.name) + '" role="button" tabindex="0">' + togLbl + '</span>' +
            '</div>' +
            '<div class="mkt-desc">' + esc(t.description || '') + '</div>' +
            '<div class="mkt-meta">' + badges + tags + '</div>' +
          '</div>';
        }).join('');
        $$('#fmMarketList .mkt-toggle').forEach(function (b) {
          b.addEventListener('click', function () { marketToggle(b.dataset.name, !b.classList.contains('on'), b); });
          b.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') marketToggle(b.dataset.name, !b.classList.contains('on'), b); });
        });
      })
      .catch(function (e) {
        body.innerHTML = '<div class="fm-empty">加载失败：' + esc(e.message) + '</div>';
      });
  }

  function marketToggle(name, wantEnabled, btn) {
    btn.textContent = '切换中…';
    wbFetch('/api/market/' + encodeURIComponent(name) + '/toggle?enabled=' + (wantEnabled ? 'true' : 'false'), { method: 'POST' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function () { loadMarket(); })
      .catch(function () {
        btn.textContent = '失败';
        setTimeout(function () { loadMarket(); }, 1200);
      });
  }

  /* ---------------- 数据出境管控（企业级定位落地：出境开关 + 出境日志） ----------------
     定位更正为「数据可以出本机」后，企业级的两条硬要求在此产品化：
       ① 出境可按**数据分级**配置（allow / deny / approval 三态，非全开全关）；
       ② 出境行为**可审计**（含被拒绝的）。
     合规红线：后端已保证日志只存脱敏截断摘要；前端只展示摘要，不放大任何载荷。 */
  var EG_STATE = { cls: '', decision: '' };
  var EG_MODE_LABEL = { allow: '放行', deny: '禁止', approval: '需审批' };
  var EG_LEVEL_LABEL = { public: '公开', internal: '内部', confidential: '机密' };

  function openEgressModal() {
    openFeatureModal('数据出境管控',
      '<div class="fm-sub">5 类目的地 · 10 个出境口全部过闸。<b>默认全放行</b>，可按数据分级收紧。</div>' +
      '<div class="kb-domains" id="egPresets"><span class="fm-empty">加载中…</span></div>' +
      '<div id="egClasses"><div class="fm-empty">加载中…</div></div>' +
      '<div class="fm-sub" style="margin-top:16px">出境日志（含被拒绝的）</div>' +
      '<div class="kb-domains" id="egFilters"></div>' +
      '<div id="egLogs"><div class="fm-empty">加载中…</div></div>',
      '<span class="fm-sub" style="margin:0">日志只记目的地主机 / 字节数 / 脱敏摘要 —— 不存载荷全文。</span>',
      { wide: true });
    loadEgress();
  }

  function loadEgress() {
    wbFetch('/api/egress/inventory')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(renderEgressInventory)
      .catch(function (e) {
        var h = document.getElementById('egClasses');
        if (h) h.innerHTML = '<div class="fm-empty">加载失败：' + esc(e.message) + '</div>';
      });
    loadEgressLog();
  }

  function renderEgressInventory(inv) {
    var ph = document.getElementById('egPresets');
    if (ph) {
      var keys = Object.keys(inv.presets || {});
      var cur = inv.lockdown ? 'lockdown' : '';
      ph.innerHTML = keys.map(function (k) {
        var p = inv.presets[k];
        return '<button class="kb-domain' + (cur === k ? ' on' : '') + '" data-preset="' + escAttr(k) +
          '" title="' + escAttr(p.desc) + '">' + esc(p.label) + '</button>';
      }).join('');
      $$('#egPresets .kb-domain').forEach(function (b) {
        b.addEventListener('click', function () { applyEgressPreset(b.dataset.preset); });
      });
    }
    var ch = document.getElementById('egClasses');
    if (!ch) return;
    ch.innerHTML = (inv.classes || []).map(function (c) {
      var modes = c.modes_by_level || {};
      var chips = ['public', 'internal', 'confidential'].map(function (lv) {
        var m = modes[lv] || c.default_mode || 'allow';
        var cls = m === 'deny' ? ' mkt-badge--crit' : (m === 'approval' ? ' mkt-badge--warn' : '');
        return '<span class="mkt-badge' + cls + '">' + esc(EG_LEVEL_LABEL[lv] || lv) + '：' +
          esc(EG_MODE_LABEL[m] || m) + '</span>';
      }).join('');
      return '<div class="mkt-card">' +
        '<div class="mkt-head"><span class="mkt-name">' + esc(c.label || c['class']) + '</span>' +
          '<span class="mkt-cat">' + esc(c['class']) + '</span></div>' +
        '<div class="mkt-desc">载荷：' + esc(c.payload || '') + '</div>' +
        '<div class="mkt-meta">' + chips + '</div>' +
        '<div class="mkt-desc" style="opacity:.65;font-size:12px">收口点：' +
          esc((c.sites || []).join(' · ')) + '</div>' +
      '</div>';
    }).join('');
  }

  function applyEgressPreset(name) {
    wbFetch('/api/egress/preset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function () { loadEgress(); })
      .catch(function (e) { alert('切换失败：' + (e.message || e)); });
  }

  function loadEgressLog() {
    var host = document.getElementById('egLogs');
    if (!host) return;
    host.innerHTML = '<div class="fm-empty">加载中…</div>';
    var qs = '?limit=60';
    if (EG_STATE.cls) qs += '&dest_class=' + encodeURIComponent(EG_STATE.cls);
    if (EG_STATE.decision) qs += '&decision=' + encodeURIComponent(EG_STATE.decision);
    wbFetch('/api/egress/log' + qs)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        var fh = document.getElementById('egFilters');
        if (fh) {
          var copts = [['', '全部类别'], ['llm', '大模型'], ['embedding', '向量化'],
                       ['search', '联网检索'], ['external_rag', '外部RAG'], ['connector', '外部系统']];
          var dopts = [['', '全部决策'], ['allow', '放行'], ['deny', '禁止'], ['pending', '待审批']];
          fh.innerHTML = copts.map(function (o) {
            return '<button class="kb-domain' + (EG_STATE.cls === o[0] ? ' on' : '') +
              '" data-f="cls" data-v="' + escAttr(o[0]) + '">' + esc(o[1]) + '</button>';
          }).join('') + '<span style="display:inline-block;width:12px"></span>' + dopts.map(function (o) {
            return '<button class="kb-domain' + (EG_STATE.decision === o[0] ? ' on' : '') +
              '" data-f="decision" data-v="' + escAttr(o[0]) + '">' + esc(o[1]) + '</button>';
          }).join('');
          $$('#egFilters .kb-domain').forEach(function (b) {
            b.addEventListener('click', function () {
              var f = b.dataset.f, v = b.dataset.v;
              EG_STATE[f] = (EG_STATE[f] === v) ? '' : v;
              loadEgressLog();
            });
          });
        }
        var logs = d.logs || [];
        if (!logs.length) { host.innerHTML = '<div class="fm-empty">暂无出境记录</div>'; return; }
        host.innerHTML = logs.map(function (l) {
          var sev = l.decision === 'deny' ? ' mkt-badge--crit'
                  : (l.decision === 'pending' ? ' mkt-badge--warn' : '');
          var lv = l.level === 'confidential' ? ' mkt-badge--warn' : '';
          return '<div class="mkt-card">' +
            '<div class="mkt-head"><span class="mkt-name">' + esc(l.dest_host || '—') + '</span>' +
              '<span class="mkt-badge' + sev + '">' + esc(l.decision) + '</span></div>' +
            '<div class="mkt-desc">' + esc(l.summary || '(空载荷)') + '</div>' +
            '<div class="mkt-meta">' +
              '<span class="mkt-cat">' + esc(l.dest_class) + '</span>' +
              '<span class="mkt-badge' + lv + '">' + esc(EG_LEVEL_LABEL[l.level] || l.level) + '</span>' +
              '<span class="mkt-tag">' + (l.bytes_out || 0) + ' B</span>' +
              '<span class="mkt-tag">' + esc(l.ts || '') + '</span>' +
            '</div></div>';
        }).join('');
      })
      .catch(function (e) { host.innerHTML = '<div class="fm-empty">加载失败：' + esc(e.message) + '</div>'; });
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
      '<button class="fm-btn secondary" id="fmFlowRun">跑到结束</button>' +
      '<button class="fm-btn secondary" id="fmFlowCanvas">可视化画布</button></div>' +
      '<div class="fm-log" id="fmFlowLog">未启动流程</div>',
      '<button class="fm-btn secondary" id="fmFlowClose">关闭</button>');
    $('#fmFlowCanvas').addEventListener('click', function () { window.open('/flow-canvas.html', '_blank'); });
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
    var cnt = $('#convGroupCount');
    if (cnt) cnt.textContent = String(CONVERSATIONS.length);
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
          insertAtCursor($('#composerInput'), '/' + (title || id) + ' ');
          toast('已调用技能：' + (title || id));
        }
      });
      _appendSkillDrawerFooter();
    }).catch(function (e) { toast('技能列表加载失败：' + (e.message || e)); });
  }

  // 在技能抽屉底部追加"安装/管理"入口（openDrawer 无 footer 钩子，故追加到 body 末尾）
  function _appendSkillDrawerFooter() {
    var body = $('#toolDrawerBody');
    if (!body || $('#skillInstallBtn')) return;
    var foot = document.createElement('div');
    foot.className = 'skill-drawer-foot';
    foot.innerHTML =
      '<button id="skillInstallBtn" class="fm-btn">＋ 安装 / 管理技能</button>' +
      '<div class="skill-foot-hint">文件夹技能安装后会出现在上方列表，选中即注入对话。视频生成请在「连接器」挂 capability=video 的 MCP。</div>';
    body.appendChild(foot);
    $('#skillInstallBtn').addEventListener('click', openSkillInstall);
  }

  /* ---------------- 技能安装 / 管理弹窗 ----------------
     三种来源：粘贴 SKILL.md 正文 / 本地含 SKILL.md 的文件夹 / https 链接（.git 或 .zip）。
     已安装的文件夹技能可在本弹窗内卸载。后端见 api.py 的 /api/skills/install 与 /api/skills/{name}。 */
  function openSkillInstall() {
    var html =
      '<div class="skill-install">' +
        '<div class="si-tabs">' +
          '<button class="si-tab on" data-m="paste">粘贴 SKILL.md</button>' +
          '<button class="si-tab" data-m="path">本地路径</button>' +
          '<button class="si-tab" data-m="url">https 链接</button>' +
        '</div>' +
        '<div class="si-pane" data-pane="paste">' +
          '<label class="si-label">SKILL.md 正文（必须含 name + description 的 YAML frontmatter）</label>' +
          '<textarea id="siPaste" class="fm-input si-ta" placeholder="---\nname: my-skill\ndescription: 一句话说明这个技能做什么\n---\n正文…"></textarea>' +
          '<label class="si-label">技能名（可选，留空则从 frontmatter 解析）</label>' +
          '<input id="siNamePaste" class="fm-input" placeholder="my-skill">' +
        '</div>' +
        '<div class="si-pane" data-pane="path" hidden>' +
          '<label class="si-label">本地文件夹绝对路径（目录内需含 SKILL.md）</label>' +
          '<input id="siPath" class="fm-input" placeholder="D:/skills/my-skill">' +
          '<label class="si-label">技能名（可选）</label>' +
          '<input id="siNamePath" class="fm-input" placeholder="my-skill">' +
        '</div>' +
        '<div class="si-pane" data-pane="url" hidden>' +
          '<label class="si-label">https 链接：.git 仓库 或 .zip 压缩包</label>' +
          '<input id="siUrl" class="fm-input" placeholder="https://github.com/owner/my-skill.git">' +
          '<label class="si-label">技能名（可选，留空则从 URL 推断）</label>' +
          '<input id="siNameUrl" class="fm-input" placeholder="my-skill">' +
        '</div>' +
        '<div class="si-err" id="siErr"></div>' +
        '<div class="si-installed">' +
          '<div class="si-sub">已安装文件夹技能（可卸载）</div>' +
          '<div id="siList"><span class="tool-menu__empty">加载中…</span></div>' +
        '</div>' +
      '</div>';
    openFeatureModal('安装 / 管理技能', html,
      '<button class="my-modal__btn my-modal__btn--ghost" id="siCancel">关闭</button>' +
      '<button class="my-modal__btn my-modal__btn--primary" id="siInstall">安装</button>');
    $$('#fmBody .si-tab').forEach(function (t) {
      t.addEventListener('click', function () {
        $$('#fmBody .si-tab').forEach(function (x) { x.classList.remove('on'); });
        t.classList.add('on');
        var m = t.dataset.m;
        $$('#fmBody .si-pane').forEach(function (p) { p.hidden = (p.dataset.pane !== m); });
      });
    });
    $('#siInstall').addEventListener('click', doSkillInstall);
    $('#siCancel').addEventListener('click', closeFeatureModal);
    _renderInstalledSkills();
  }

  function doSkillInstall() {
    var active = $('#fmBody .si-tab.on');
    var method = active ? active.dataset.m : 'paste';
    var value = '', name = '';
    if (method === 'paste') { value = ($('#siPaste').value || '').trim(); name = ($('#siNamePaste').value || '').trim(); }
    else if (method === 'path') { value = ($('#siPath').value || '').trim(); name = ($('#siNamePath').value || '').trim(); }
    else { value = ($('#siUrl').value || '').trim(); name = ($('#siNameUrl').value || '').trim(); }
    var err = $('#siErr');
    err.textContent = '';
    if (!value) { err.textContent = '请先填写 SKILL.md 内容 / 本地路径 / https 链接'; return; }
    var btn = $('#siInstall');
    btn.disabled = true;
    wbFetch('/api/skills/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method: method, value: value, name: name })
    }).then(function (r) { return r.json().then(function (j) { return { r: r, j: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.r.ok) { err.textContent = res.j.detail || '安装失败'; return; }
        toast('已安装技能：' + res.j.name);
        closeFeatureModal();
        openSkillDrawer();   // 刷新抽屉，新技能立即出现在列表
      })
      .catch(function (e) {
        btn.disabled = false;
        err.textContent = (e.message || String(e)) + '';
      });
  }

  function _renderInstalledSkills() {
    var wrap = $('#siList');
    if (!wrap) return;
    wbFetch('/api/skills/list').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.skills) || [];
      var folder = list.filter(function (s) { return s.type === 'folder'; });
      if (!folder.length) { wrap.innerHTML = '<span class="tool-menu__empty">暂无已安装的文件夹技能</span>'; return; }
      wrap.innerHTML = folder.map(function (s) {
        return '<div class="si-row"><span class="si-name">' + escHtml(s.name) + '</span>' +
          '<span class="si-desc">' + escHtml((s.description || '').slice(0, 60)) + '</span>' +
          '<button class="si-del" data-name="' + escAttr(s.name) + '">卸载</button></div>';
      }).join('');
      $$('#siList .si-del').forEach(function (b) {
        b.addEventListener('click', function () { uninstallSkill(b.dataset.name); });
      });
    }).catch(function () { wrap.innerHTML = '<span class="tool-menu__empty">列表加载失败</span>'; });
  }

  function uninstallSkill(name) {
    if (!window.confirm('确定卸载技能「' + name + '」？\n该操作会删除 skills/' + name + ' 目录，不可恢复。')) return;
    wbFetch('/api/skills/' + encodeURIComponent(name), { method: 'DELETE' })
      .then(function (r) { return r.json().then(function (j) { return { r: r, j: j }; }); })
      .then(function (res) {
        if (!res.r.ok) { toast('卸载失败：' + (res.j.detail || '')); return; }
        toast('已卸载技能：' + name);
        _renderInstalledSkills();
        openSkillDrawer();
      })
      .catch(function (e) { toast('卸载失败：' + (e.message || String(e))); });
  }

  /* ---------------- Command（指令模板）：逆向自 ZCode Command 能力 ----------------
     用户常用提示词一键插入；localStorage 持久化，按 token 隔离（多用户不串）。 */
  var CMD_KEY = 'miniyuxi_commands';
  var CMD_PRESETS = [
    { id: 'preset_offboard', title: '生成离职面谈提纲', prompt: '请基于公司制度生成一份《离职面谈提纲》，覆盖离职原因、工作交接、保密与竞业限制、未结薪酬、情绪安抚等要点，输出可直接打印的清单。' },
    { id: 'preset_social', title: '核算本月社保', prompt: '请按深圳最新社保/公积金缴费基数与比例，核算本月一名员工的社保与公积金个人与单位应缴金额，列出计算式与依据文件。' },
    { id: 'preset_offer', title: '起草录用通知', prompt: '请起草一份《录用通知书（Offer）》，包含岗位、薪资结构、报到时间、试用期、生效条件等，使用公司公文风格。' },
    { id: 'preset_probation', title: '试用期评估', prompt: '请生成一份《试用期员工评估表》及评估要点话术，覆盖胜任力、文化匹配、改进项，输出评分维度与结论模板。' },
    { id: 'preset_policy', title: '制度问答', prompt: '请基于知识库检索相关制度并给出带 [编号] 引用的解答；资料未提及的明说「资料未提及」。' }
  ];
  function _cmdScope() { return CMD_KEY + '_' + (TOKEN || 'anon'); }
  function getUserCommands() {
    var raw; try { raw = JSON.parse(localStorage.getItem(_cmdScope()) || '[]'); } catch (e) { raw = []; }
    if (!Array.isArray(raw)) raw = [];
    return CMD_PRESETS.concat(raw);
  }
  function addUserCommand(title, prompt) {
    var raw; try { raw = JSON.parse(localStorage.getItem(_cmdScope()) || '[]'); } catch (e) { raw = []; }
    if (!Array.isArray(raw)) raw = [];
    raw.push({ id: 'cmd_' + Date.now(), title: title, prompt: prompt });
    try { localStorage.setItem(_cmdScope(), JSON.stringify(raw)); } catch (e) {}
  }
  function delUserCommand(id) {
    var raw; try { raw = JSON.parse(localStorage.getItem(_cmdScope()) || '[]'); } catch (e) { raw = []; }
    if (!Array.isArray(raw)) raw = [];
    raw = raw.filter(function (c) { return c.id !== id; });
    try { localStorage.setItem(_cmdScope(), JSON.stringify(raw)); } catch (e) {}
  }
  function activeComposer() {
    var dock = $('#composerInputDock'), main = $('#composerInput');
    if (dock && dock.offsetParent !== null) return dock;   // 对话态可见
    return main || dock;
  }
  function getComposerText() {
    var a = $('#composerInput'), b = $('#composerInputDock');
    var ta = a ? (a.textContent || '') : '';
    var tb = b ? (b.textContent || '') : '';
    return (ta.trim() || tb.trim());
  }
  function openCmdDrawer() {
    $('#toolDrawerTitle').textContent = '指令 / 技能';
    var cmds = getUserCommands();
    var cmdHtml = cmds.length ? cmds.map(function (c) {
      var isPreset = String(c.id).indexOf('preset_') === 0;
      return '<button class="tool-menu__option cmd-opt" data-kind="cmd" data-id="' + escAttr(c.id) + '" data-title="' + escAttr(c.title) + '">' +
        '<span class="tool-menu__option-main">' +
        '<span class="tool-menu__option-title">' + escHtml(c.title) + '</span>' +
        '<span class="tool-menu__option-desc">' + escHtml(c.prompt) + '</span></span>' +
        (isPreset ? '' : '<span class="cmd-del" data-id="' + escAttr(c.id) + '" title="删除指令">✕</span>') +
        '</button>';
    }).join('') : '<div class="tool-menu__empty">暂无自定义指令，可在下方「存为指令」保存当前输入框。</div>';
    var body = $('#toolDrawerBody');
    body.innerHTML =
      '<div class="cmd-save">' +
        '<input id="cmdSaveTitle" class="fm-input" placeholder="指令标题（如：生成周报）">' +
        '<button class="fm-btn" id="cmdSaveBtn">存为指令</button>' +
      '</div>' +
      '<div class="tool-menu__group">我的指令（点击插入 · 预置不可删）</div>' + cmdHtml +
      '<div class="tool-menu__group">技能（点击插入 /技能名）</div>' +
      '<div id="cmdSkillWrap"><div class="tool-menu__empty">加载技能中…</div></div>';
    $('#cmdSaveBtn').addEventListener('click', function () {
      var title = ($('#cmdSaveTitle').value || '').trim();
      var prompt = getComposerText();
      if (!title) { toast('请填写指令标题'); return; }
      if (!prompt) { toast('输入框为空，无可保存内容'); return; }
      addUserCommand(title, prompt);
      toast('已保存指令：' + title);
      openCmdDrawer();
    });
    $$('#toolDrawerBody .cmd-del').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.stopPropagation();
        delUserCommand(el.dataset.id);
        openCmdDrawer();
      });
    });
    $$('#toolDrawerBody .cmd-opt').forEach(function (el) {
      el.addEventListener('click', function () {
        var c = cmds.filter(function (x) { return x.id === el.dataset.id; })[0];
        if (c) { insertAtCursor(activeComposer(), c.prompt); toast('已插入指令：' + c.title); }
        closeToolMenu();
      });
    });
    wbFetch('/api/skills/list').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.skills) || [];
      var wrap = $('#cmdSkillWrap');
      if (!wrap) return;
      if (!list.length) { wrap.innerHTML = '<div class="tool-menu__empty">暂无技能</div>'; return; }
      wrap.innerHTML = list.map(function (s) {
        var ttl = ('question' in s ? s.question : (s.name || s.id));
        var sub = (s.tags && s.tags.join(', ')) || '';
        var id = s.name || s.id;
        return '<button class="tool-menu__option" data-id="' + escAttr(id) + '" data-title="' + escAttr(ttl) + '">' +
          '<span class="tool-menu__option-main"><span class="tool-menu__option-title">' + escHtml(ttl) + '</span>' +
          (sub ? '<span class="tool-menu__option-desc">' + escHtml(sub) + '</span>' : '') + '</span></button>';
      }).join('');
      $$('#cmdSkillWrap .tool-menu__option').forEach(function (sel) {
        sel.addEventListener('click', function () {
          insertAtCursor(activeComposer(), '/' + (sel.dataset.title || sel.dataset.id) + ' ');
          toast('已调用技能：' + (sel.dataset.title || sel.dataset.id));
          closeToolMenu();
        });
      });
    }).catch(function () { var w = $('#cmdSkillWrap'); if (w) w.innerHTML = '<div class="tool-menu__empty">技能加载失败</div>'; });
    $('#toolMenu').hidden = true;
    $('#toolDrawer').hidden = false;
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
      // 对齐 WorkBuddy：键入 @ / 即唤起对应选择器（原站是键入触发，不是按钮触发）
      el.addEventListener('input', function (e) {
        syncSend();
        var d = e.data;
        if (d !== '@' && d !== '/') return;
        var txt = el.textContent || '';
        if (txt.slice(-1) !== d) return;
        el.textContent = txt.slice(0, -1);      // 吃掉触发符，由选择器回填完整引用
        placeCaretEnd(el);
        syncSend();
        if (d === '@') openRefFileDrawer(); else openCmdDrawer();
      });
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

    // 快捷插入 @ /（无 data-insert 的按钮——如「工具」菜单按钮——只开菜单，不插入文本）
    $$('.composer-tool').forEach(function (b) {
      b.addEventListener('click', function () {
        if (!b.dataset.insert) return;
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

    // 对齐 WorkBuddy：输入框下方「选择工作空间 ∨」「允许完全访问 ∨」
    var wsBtn = $('#btnWorkspace');
    if (wsBtn) {
      wsBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        // MiniYuxi 无「工作空间」建模，这里如实反映当前租户，不造多空间假数据
        var t = '';
        try { t = localStorage.getItem('miniyuxi_tenant') || ''; } catch (err) {}
        toast(t ? ('当前工作空间：' + t) : '当前为默认工作空间（单租户模式）');
      });
    }
    var acBtn = $('#btnAccessChip');
    if (acBtn) {
      // 与工具菜单里的「允许完全访问」开关联动，避免两处状态不一致
      acBtn.addEventListener('click', function (e) { e.stopPropagation(); toggleToolMenu($('#btnToolMenu')); });
    }

    // chips 行尾：搜索（打开技能与指令抽屉）/ 右移（横向滚动一屏）
    var chipSearch = $('#btnChipSearch');
    if (chipSearch) chipSearch.addEventListener('click', function () { openSkillDrawer(); });
    var chipNext = $('#btnChipNext');
    if (chipNext) {
      chipNext.addEventListener('click', function () {
        var list = $('#quickActions');
        if (!list) return;
        var max = list.scrollWidth - list.clientWidth;
        var next = list.scrollLeft >= max - 4 ? 0 : list.scrollLeft + Math.max(160, list.clientWidth * 0.8);
        list.scrollTo({ left: next, behavior: 'smooth' });
      });
    }
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
    renderNavRail();          // 左侧主导航（对齐 WorkBuddy 中文桌面版 7 项）
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

  /* ---------------- 业务集成：MiniYuxi × RuoYi-Office-Vben 适配器 ----------------
     左：MCP 连接器（增/健康）；右：4 模块工具面（HRM/CRM/ERP/OA），风险徽标 + 参数表单 + 调用；
     命中 HITL 审批门时弹审批卡，批准后续跑提交（B2 防御纵深：高危工具仅审批后才真正提交）。 */
  var BIZ = { connectors: [], tools: [], module: 'all' };
  var BIZ_MODULES = [
    { key: 'hrm', label: 'HRM 人事' },
    { key: 'crm', label: 'CRM 客户' },
    { key: 'erp', label: 'ERP 供应链' },
    { key: 'oa',  label: 'OA 办公' }
  ];

  function bizRiskClass(risk) {
    if (risk === 'high_risk') return 'biz-risk biz-risk--high';
    if (risk === 'warn') return 'biz-risk biz-risk--warn';
    return 'biz-risk biz-risk--info';
  }
  function bizRiskLabel(risk) {
    if (risk === 'high_risk') return '高危';
    if (risk === 'warn') return '中风险';
    return '低风险';
  }
  function bizModuleOf(name) {
    var m = /^mcp\.(hrm|crm|erp|oa)\./.exec(name || '');
    return m ? m[1] : '';
  }
  function bizBtnSel(name) {
    var v = (window.CSS && CSS.escape) ? CSS.escape(name) : name;
    return '#bizTools [data-call="' + v + '"]';
  }

  function openBizPanel() {
    openFeatureModal('业务集成 · RuoYi 适配器',
      '<div class="biz-wrap">' +
        '<div class="biz-side">' +
          '<div class="biz-side__head">连接器（MCP）</div>' +
          '<div id="bizConns"><span class="fm-empty">加载中…</span></div>' +
          '<details class="biz-add" id="bizAddBox">' +
            '<summary>＋ 添加 MCP 连接器</summary>' +
            '<div class="biz-form">' +
              '<input id="bizNewName" class="fm-input" placeholder="名称（如：ruoyi生产）">' +
              '<input id="bizNewEndpoint" class="fm-input" placeholder="SSE 地址（http://host:port/sse）">' +
              '<input id="bizNewToken" class="fm-input" placeholder="Bearer Token（可选）" autocomplete="off">' +
              '<input id="bizNewCap" class="fm-input" placeholder="能力标记 capability（可选，填 video 即作视频生成连接器）">' +
              '<button class="fm-btn" id="bizAddConn">保存连接器</button>' +
              '<span class="biz-hint">保存后点「刷新工具目录」拉取远端工具。</span>' +
            '</div>' +
          '</details>' +
          '<button class="fm-btn secondary" id="bizRefresh">刷新工具目录</button>' +
        '</div>' +
        '<div class="biz-main">' +
          '<div class="kb-domains" id="bizModules"></div>' +
          '<div id="bizTools"><span class="fm-empty">加载中…</span></div>' +
        '</div>' +
      '</div>',
      '<span class="fm-sub" style="margin:0">高危工具默认仅预览，须经 HITL 审批（审批卡）确认后才真正提交业务单据；' +
      '响应敏感字段（身份证/手机/邮箱/银行卡）已由适配器脱敏。</span>',
      { wide: true });
    $('#bizAddConn').addEventListener('click', bizAddConnector);
    $('#bizRefresh').addEventListener('click', function () { bizLoad(true); });
    bizLoad(false);
  }

  function bizLoad(refresh) {
    var q = refresh ? '?refresh=1' : '';
    Promise.all([
      wbFetch('/api/connectors').then(function (r) { return r.json(); }),
      wbFetch('/api/tools/list' + q).then(function (r) { return r.json(); })
    ]).then(function (res) {
      BIZ.connectors = (res[0] && res[0].connectors) || [];
      BIZ.tools = ((res[1] && res[1].tools) || []).filter(function (t) {
        return t.toolset === 'mcp-adapter';
      });
      bizRenderConns();
      bizRenderModules();
      bizRenderTools();
    }).catch(function (e) {
      var h = document.getElementById('bizTools');
      if (h) h.innerHTML = '<div class="fm-empty">加载失败：' + esc(e.message) + '</div>';
    });
  }

  function bizRenderConns() {
    var box = document.getElementById('bizConns');
    if (!box) return;
    var mc = BIZ.connectors.filter(function (c) { return c.kind === 'mcp'; });
    if (!mc.length) {
      box.innerHTML = '<div class="fm-empty">暂无 MCP 连接器。展开上方「＋ 添加」新建一个，' +
        '指向运行中的 RuoYi 适配器 SSE 地址。</div>';
      return;
    }
    box.innerHTML = mc.map(function (c) {
      var st = c.status || 'unknown';
      var cls = st === 'ready' ? 'biz-st biz-st--ok'
              : (st === 'disabled' ? 'biz-st biz-st--off'
              : (st === 'partial' ? 'biz-st biz-st--warn' : 'biz-st biz-st--bad'));
      var cfg = {};
      try { cfg = JSON.parse(c.config_json || '{}'); } catch (e) {}
      return '<div class="biz-conn">' +
        '<div class="biz-conn__top"><b>' + esc(c.name) + '</b>' +
          '<span class="' + cls + '">' + esc(st) + '</span></div>' +
        '<div class="biz-conn__ep">' + esc(cfg.endpoint || '（无 endpoint）') + '</div>' +
      '</div>';
    }).join('');
  }

  function bizAddConnector() {
    var name = $('#bizNewName').value.trim();
    var ep = $('#bizNewEndpoint').value.trim();
    var tok = $('#bizNewToken').value.trim();
    var cap = ($('#bizNewCap') ? $('#bizNewCap').value.trim() : '');
    if (!name || !ep) { toast('请填写名称与 SSE 地址'); return; }
    var config = { transport: 'sse', endpoint: ep };
    if (tok) config.token = tok;
    if (cap) config.capability = cap;
    wbFetch('/api/connectors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, kind: 'mcp', config: config })
    }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function () {
        toast('连接器已保存');
        var box = $('#bizAddBox'); if (box) box.open = false;
        $('#bizNewName').value = ''; $('#bizNewEndpoint').value = ''; $('#bizNewToken').value = '';
        if ($('#bizNewCap')) $('#bizNewCap').value = '';
        bizProbeHealth();
      })
      .catch(function (e) { alert('保存失败：' + (e.message || e)); });
  }

  function bizProbeHealth() {
    wbFetch('/api/connectors/health', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function () { bizLoad(false); })
      .catch(function () {});
  }

  function bizRenderModules() {
    var box = document.getElementById('bizModules');
    if (!box) return;
    var chips = [{ key: 'all', label: '全部' }].concat(BIZ_MODULES);
    box.innerHTML = chips.map(function (m) {
      return '<button class="kb-domain' + (BIZ.module === m.key ? ' on' : '') +
        '" data-mod="' + escAttr(m.key) + '">' + esc(m.label) + '</button>';
    }).join('');
    $$('#bizModules .kb-domain').forEach(function (b) {
      b.addEventListener('click', function () { BIZ.module = b.dataset.mod; bizRenderTools(); });
    });
  }

  function bizRenderTools() {
    var box = document.getElementById('bizTools');
    if (!box) return;
    if (!BIZ.tools.length) {
      box.innerHTML = '<div class="fm-empty">未发现 mcp-adapter 工具。请确认：① 已添加并指向运行中的适配器；' +
        '② 点过「刷新工具目录」。适配器未运行时此处为空属正常。</div>';
      return;
    }
    var list = BIZ.tools.filter(function (t) {
      return BIZ.module === 'all' || bizModuleOf(t.name) === BIZ.module;
    });
    if (!list.length) { box.innerHTML = '<div class="fm-empty">该模块暂无工具。</div>'; return; }
    box.innerHTML = list.map(function (t) {
      var props = (t.schema && t.schema.properties) || {};
      var req = (t.schema && t.schema.required) || [];
      var fields = Object.keys(props).map(function (k) {
        var ty = (props[k].type || 'string');
        var ph = props[k].description || ('参数 ' + k);
        var inp = ty === 'object'
          ? '<textarea id="arg_' + escAttr(t.name) + '_' + escAttr(k) + '" class="fm-input" rows="3" placeholder="JSON 对象，如 {&quot;a&quot;:1}"></textarea>'
          : '<input id="arg_' + escAttr(t.name) + '_' + escAttr(k) + '" class="fm-input" ' +
            'type="' + (ty === 'number' || ty === 'integer' ? 'number' : 'text') + '" placeholder="' + escAttr(ph) + '">';
        var star = req.indexOf(k) >= 0 ? ' <span class="biz-req">*</span>' : '';
        return '<label class="biz-field"><span>' + esc(k) + star + '</span>' + inp + '</label>';
      }).join('');
      var desc = (t.description || '').replace(/^\[MCP\]\s*/, '');
      return '<div class="mkt-card biz-tool">' +
        '<div class="mkt-head"><span class="mkt-name">' + esc(t.name) + '</span>' +
          '<span class="' + bizRiskClass(t.risk) + '">' + bizRiskLabel(t.risk) +
          (t.requires_approval ? ' · 需审批' : '') + '</span></div>' +
        '<div class="mkt-desc">' + esc(desc) + '</div>' +
        (fields || '<div class="biz-nofield">无参数</div>') +
        '<div class="biz-tool__foot">' +
          '<button class="fm-btn" data-call="' + escAttr(t.name) + '">' +
            (t.risk === 'high_risk' ? '预览 / 提交' : '调用') + '</button>' +
          '<span class="biz-tool__res" id="res_' + escAttr(t.name) + '"></span>' +
        '</div></div>';
    }).join('');
    $$('#bizTools [data-call]').forEach(function (b) {
      b.addEventListener('click', function () { bizCall(b.dataset.call); });
    });
  }

  function bizCollectArgs(name) {
    var t = BIZ.tools.filter(function (x) { return x.name === name; })[0];
    var props = (t && t.schema && t.schema.properties) || {};
    var args = {};
    Object.keys(props).forEach(function (k) {
      var el = document.getElementById('arg_' + name + '_' + k);
      if (!el) return;
      var raw = el.value.trim();
      if (!raw) return;
      var ty = props[k].type || 'string';
      if (ty === 'number' || ty === 'integer') {
        args[k] = Number(raw);
      } else if (ty === 'object') {
        try { args[k] = JSON.parse(raw); } catch (e) { throw new Error('参数 ' + k + ' 不是合法 JSON 对象'); }
      } else {
        args[k] = raw;
      }
    });
    return args;
  }

  function bizShowResult(name, html, isErr) {
    var el = document.getElementById('res_' + name);
    if (!el) return;
    el.innerHTML = '<span class="biz-res' + (isErr ? ' biz-res--err' : '') + '">' + html + '</span>';
  }

  function bizCall(name, approvalId) {
    var args;
    try { args = bizCollectArgs(name); } catch (e) { toast(e.message); return; }
    var payload = { name: name, args: args, session_id: 'web' };
    if (approvalId) payload.approval_id = approvalId;
    var btn = document.querySelector(bizBtnSel(name));
    if (btn) btn.disabled = true;
    wbFetch('/api/tools/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (btn) btn.disabled = false;
        if (d && d.status === 'pending') { bizShowHitl(name, args, d.approval_id, d.tool_name); return; }
        var txt = (d && (d.result !== undefined ? d.result : d.error)) || d;
        var s = (typeof txt === 'string') ? txt : JSON.stringify(txt, null, 2);
        bizShowResult(name, esc(s).slice(0, 1400), !!(d && d.error));
      })
      .catch(function (e) {
        if (btn) btn.disabled = false;
        bizShowResult(name, esc(e.message), true);
      });
  }

  function bizShowHitl(name, args, aid, toolName) {
    var html =
      '<div class="biz-hitl">' +
        '<div class="biz-hitl__title">⚠ HITL 审批：' + esc(toolName || name) + '</div>' +
        '<div class="biz-hitl__sub">该调用将真正提交业务单据，需人工确认。</div>' +
        '<pre class="biz-hitl__args">' + esc(JSON.stringify(args, null, 2)) + '</pre>' +
        '<div class="biz-hitl__foot">' +
          '<button class="fm-btn" id="hitlApprove">确认提交</button>' +
          '<button class="fm-btn secondary" id="hitlReject">拒绝</button>' +
        '</div>' +
        '<div class="biz-hitl__res" id="hitlRes"></div>' +
      '</div>';
    bizShowResult(name, html, false);
    $('#hitlApprove').addEventListener('click', function () {
      $('#hitlApprove').disabled = true; $('#hitlReject').disabled = true;
      wbFetch('/api/approvals/' + encodeURIComponent(aid) + '/decide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approve: true, by: 'web' })
      }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function () {
          var r2 = document.getElementById('hitlRes');
          if (r2) r2.textContent = '已批准，正在提交…';
          bizCall(name, aid);
        })
        .catch(function (e) {
          var r2 = document.getElementById('hitlRes');
          if (r2) r2.textContent = '审批失败：' + e.message;
          $('#hitlApprove').disabled = false; $('#hitlReject').disabled = false;
        });
    });
    $('#hitlReject').addEventListener('click', function () {
      wbFetch('/api/approvals/' + encodeURIComponent(aid) + '/decide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approve: false, by: 'web' })
      }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function () {
          bizShowResult(name, '<span class="biz-res biz-res--err">已拒绝该调用。</span>', true);
          var b2 = document.querySelector(bizBtnSel(name)); if (b2) b2.disabled = false;
        })
        .catch(function (e) { bizShowResult(name, esc(e.message), true); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
