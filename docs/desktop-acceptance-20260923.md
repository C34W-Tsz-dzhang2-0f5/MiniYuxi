# MiniYuxi 桌面端 · 可用性与体验验收报告

- 验收时间：2026-09-23 15:20–15:50 · 版本：0.2.0（MSI 安装版）
- 验收脚本：`tests/_acceptance_desktop.py`（可复跑）· 明细：`docs/_acceptance_desktop.json` · 截图：`docs/_shots/`
- 驱动方式：桌面端内核就绪后导航的就是 `http://127.0.0.1:<port>/`，与 Web 端同一份 `web/index.html`。
  用 Chromium 打开**桌面端 sidecar 实际服务的那个地址**做验收，页面/JS/接口与桌面端窗口内完全一致，
  不是拿网页端当替身。

## 结论

**登录流程 5/5 全通过，9 个导航入口全部可点，流畅度达标（首屏 443ms、页面切换最慢 839ms），
无 JS 运行时异常。发现 4 个功能性缺陷，其中 2 个 P0——打包漏文件导致 HRM 人事与岗位工作台
两个模块在桌面端完全不可用；这 2 个 P0 已修复、已装进装机版并复验通过。**

⚠️ **两个 P0 是"模块级不可用"，不是体验瑕疵**：点进去就是 500，功能等于没上线。

### 修复后复验（装机版，2026-09-23 晚）

| 项 | 修前 | 修后 |
|---|---|---|
| `/api/hrm/forms` | 🔴 500 | 🟢 **200（49 张表单）** |
| `/api/hrm/meta/*` | 🔴 500 | 🟢 200 |
| `/api/taskflow/roles` | 🔴 500 | 🟢 200 |
| `/api/taskflow/list` | 🔴 500 | 🟢 200 |
| 文档解析（上传真实 .docx / .pdf） | 未验 | 🟢 均 200，`n_chunks: 1` |
| 验收脚本 HTTP ≥400 次数 | 多次 500 | 🟢 **仅剩 1 次故意的错误口令 401** |
| 首屏可交互 | 443ms | 🟢 **309ms** |
| 验收通过率 | — | **通过 20 项 / 失败 2 项**（2 项即下节 D3/D4） |

### 一致性对齐已解除阻塞

原先"拿不到 WorkBuddy 基准"的结论只对了一半——界面挂不上 CDP，但**其前端文案与配置以明文内嵌在 `app.asar`**，可直接提取。已拿到导航注册表（7 项）、侧边栏文案全表、**18 条快捷键注册表**、会话恢复机制原文。
→ 详见 **`docs/desktop-consistency-baseline-20260923.md`**

**关键发现：MiniYuxi 的顶部导航与 WorkBuddy 桌面端零重合**（`岗位工作台`/`成本管理` 在桌面端 0 命中），两者 IA 不同源——导航轴**不存在可比对象**，要"对齐"需先定基准产品（产品决策，非缺陷修复）。可对齐的三条轴（侧边栏 / 快捷键 / 会话恢复）已定位到具体缺口。

---

## 一、已通过验证的功能清单

| # | 模块/项 | 结果 | 实测 |
|---|---|---|---|
| A1 | 未登录：登录入口可见 | ✅ | `#btnLogin` 可见，底部显示「未登录」 |
| A2 | 错误口令：异常提示 | ✅ | 提示「登录失败：HTTP 401」 |
| A3 | 正确口令：登录成功落 token | ✅ | token 188 字符 |
| A4 | 刷新页面：登录态保持 | ✅ | token 从 localStorage 恢复 |
| A5 | 退出后重新登录 | ✅ | 可再次登录 |
| B1 | 导航「新建」 | ✅ | 770ms |
| B2 | 导航「导入」 | ✅ | 775ms，弹出功能弹层 |
| B3 | 导航「知识库」 | ✅ | 782ms |
| B4 | 导航「HRM人事」 | ✅ 入口可点 | 795ms（⚠️ 但接口 500，见 D1） |
| B5 | 导航「流程」 | ✅ | 839ms；`/api/agent/flows` 200 |
| B6 | 导航「模型切换」 | ✅ | 764ms |
| B7 | 导航「成本管理」 | ✅ | 775ms |
| B8 | 导航「管理」 | ✅ | 762ms |
| B9 | 导航「岗位工作台」 | ✅ 入口可点 | 765ms（⚠️ 但接口 500，见 D2） |
| B10 | 核心操作：发送消息 | ✅ | 2654ms，回显正常 |
| B11 | 设置：主题切换 | ✅ | light → dark 生效 |
| B12 | 通知：Toast 提示 | ✅ | 可正常展示 |
| C1 | 首屏可交互 | ✅ | 443ms（< 5000ms） |
| C2 | 页面切换均 < 1500ms | ✅ | 最慢 839ms |
| E1 | 无 JS 运行时异常 | ✅ | pageerror 0 条 |

**流畅度体感**：首屏 443ms、9 个导航切换 764–839ms、消息发送 2.65s（离线兜底模式）。
无卡顿、无卡死、无崩溃。

---

## 一点五、两个 P0 已修复并验证 ✅

### 改动（`scripts/build_sidecar.py`，5 处）

| # | 改动 | 说明 |
|---|---|---|
| 1 | `add_data` 补 `core/hrm_schema.json` | 新增 `HRM_SCHEMA` 常量 + `f"{HRM_SCHEMA}{sep}core"` 条目 |
| 2 | **`--add-data` 改为循环传全部** | 原来只传 `add_data[0]`，导致 skills 声明了却没进包 |
| 3 | 修 `--no-install` 声明了不生效 | `build()` 里 `install` 写死 True，参数从未接线 |
| 4 | **修 triple 判定用错依据** | `platform.machine()` 在 Windows 上读的是 `PROCESSOR_ARCHITECTURE` 环境变量，被 32 位父进程启动时误报 x86，产物名变成 `i686-pc-windows-msvc.exe`，Tauri 按 host triple 找 `x86_64-...` 就找不到 sidecar。改用 `struct.calcsize("P")` 判位宽（产物架构 = 解释器架构） |
| + | 加待打包文件缺失自检 | `add_data` 里任一路径不存在直接报错退出，避免再次静默漏包 |

第 4 项是**打包过程中新暴露的缺陷**：同一个命令，第一次打出 `x86_64-...`（对），第二次打出
`i686-...`（错），全看父进程环境。已加对照复测——把 `PROCESSOR_ARCHITECTURE` 污染成 `x86` 后，
修复前后判定结果分别是 `i686-...` / `x86_64-...`。

### 验证（新 sidecar 实测，与旧版逐项对照）

| 端点 | 旧包（已装桌面端） | 新包 | 结论 |
|---|---|---|---|
| `/api/health` | 200 | 200 | 一致 |
| `/api/hrm/forms` | **500** | **200** | ✅ 修复；返回 **49 张表单**（与代码注释「49 张表单」吻合） |
| `/api/hrm/meta/app_help` | **500** | **200** | ✅ 修复 |
| `/api/hrm/meta/contract` | **500** | 404 | ✅ 正确行为（路由通了，`contract` 非合法 key） |
| `/api/taskflow/roles` | **500** | **200** | ✅ 修复 |
| `/api/taskflow/list` | **500** | **200** | ✅ 修复 |

冻结产物里也能搜到 `hrm_schema.json` 与 `task_library.json` 了（旧包两个都搜不到）。

### 最终产物全量复测（`miniyuxi-sidecar-x86_64-pc-windows-msvc.exe` · 49.6 MB）

| 端点 | 结果 | 端点 | 结果 |
|---|---|---|---|
| `/api/health` | 200 | `/api/kb/docs` | 200 |
| `/api/hrm/forms` | 200（49 张表单） | `/api/tools/list` | 200 |
| `/api/taskflow/roles` | 200 | `/api/agent/flows` | 200 |
| `/api/taskflow/list` | 200 | `/api/experts/list` | 200 |
| `/api/recruit/dashboard` | 200 | `/api/labor/dashboard` | 200 |

**文档解析功能级验证**：生成真实 `.docx` / `.pdf` 上传 `/api/kb/upload` →
**两个都 200**（`n_chunks: 1`）。说明文档解析依赖在冻结内核里真的可用，不只是"打进包了"。

### ⚠️ 过程中发现并规避的一个回归风险

新 venv 是我按需建的，**没装 `requirements.txt` 里的文档解析依赖**（`python-docx` / `pymupdf` /
`pypdf` / `rank-bm25`）。`core/rag.py::parse_file` 里 `import docx` **没有容错保护**，
漏打就会让 `.docx/.pdf` 上传解析直接抛错——第一版新包只有 16.3MB（旧包 82.7MB）就是这个信号。
已补齐全部依赖后重打，**打包前务必确认 venv 与 `requirements.txt` 一致**。

### 剩余步骤（需你决定）

新 sidecar 目前落在 `apps/desktop/src-tauri/binaries/`（开发位置）。**已安装的桌面端仍在用旧内核**，
要让装机版生效有两条路：① `cd apps/desktop && npm run build` 重出 MSI 后覆盖安装（正规）；
② 直接替换 `C:\Program Files\MiniYuxi\binaries\` 下的同名 exe（快，但需管理员权限、且偏离安装包记录）。

## 二、未通过项

### 🔴 D1｜HRM 人事模块全线 500（P0）

| 项 | 内容 |
|---|---|
| 现象 | 桌面端点「HRM人事」后触发 `GET /api/hrm/forms` → **500**，`/api/hrm/meta/{key}` 同样 500 |
| 复现 | 启动桌面端 → 点顶部导航「HRM人事」；或直接 `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8801/api/hrm/forms` → 持续 500（连测 6 轮均 500） |
| 根因 | **PyInstaller 打包漏了 `core/hrm_schema.json`**。`core/hrm.py:25` 用 `os.path.dirname(__file__)` 拼路径读它，冻结后该文件不在包里。证据：① 冻结产物中搜不到 `hrm_schema.json` 字符串，而 `index.html` 有；② 源码环境把 `_SCHEMA_PATH` 指向不存在的文件 → 精确复现 500；③ `scripts/build_sidecar.py` 的 `add_data` 只声明了 `web` 和 `skills`，**根本没有 `core/hrm_schema.json`** |
| 影响范围 | 桌面端 HRM 人事模块全部不可用（49 张表单的表单列表、元数据、CRUD 入口）。**Web 端/源码运行正常**，是打包环境专属缺陷 |
| 与 WorkBuddy 差异 | **无同类功能可比**（2026-09-23 取证）：WorkBuddy 桌面端导航 7 项（home/claw/project/market/automation/space/more）中**不含 HRM 模块**，故此项属 MiniYuxi 自有模块的打包缺陷，非对齐问题 |
| 建议修法 | `scripts/build_sidecar.py` 的 `add_data` 增加 `f"{CORE_HRM_SCHEMA}{sep}core"`，并**把只传 `add_data[0]` 改成循环传全部**（见 D2） |

### 🔴 D2｜岗位工作台（taskflow）接口 500（P0）

| 项 | 内容 |
|---|---|
| 现象 | `GET /api/taskflow/roles`、`GET /api/taskflow/list` → **500** |
| 复现 | 启动桌面端 → 点顶部导航「岗位工作台」；或直接请求上述两个接口 |
| 根因 | `core/taskflow.py:24` 读 `ROOT/skills/task_library.json`（`ROOT` 由 `__file__` 上溯两级得到）。冻结后该路径指向 `_MEIPASS/skills/`，但 **skills 实际没打进包**。根因在构建脚本：`scripts/build_sidecar.py` 第 102 行 `add_data` 声明了 **2 项**，第 115 行却**只传了 `add_data[0]`（web）**，`add_data[1]`（skills）声明了从未传给 PyInstaller。证据：冻结产物中搜不到 `task_library.json` |
| 影响范围 | 桌面端岗位工作台不可用；同时 `core/skills_catalog.py` 扫描 `skills/` 取技能，技能库在桌面端大概率也是空的（连带影响） |
| 与 WorkBuddy 差异 | **无同类功能可比**（2026-09-23 取证）：`岗位工作台` 一词在 WorkBuddy 桌面端 asar 中 **0 命中**，桌面端无对应入口，属 MiniYuxi 自有模块的打包缺陷 |
| 建议修法 | 把 `"--add-data", add_data[0]` 改成循环：`for d in add_data: args += ["--add-data", d]`（一行修复，同时解决 skills 遗漏） |

### 🟡 D3｜刷新后不自动恢复上次会话（P1）

| 项 | 内容 |
|---|---|
| 现象 | 发过消息后刷新页面，消息区**变成空白**，需要手动从会话列表点回去才看得到历史 |
| 复现 | 展开侧边栏 → 输入「持久化验证XYZ」→ 发送（消息区 660 字符）→ 刷新 → 消息区 **0 字符** → 手动点开会话列表第一条 → 恢复 606 字符，XYZ 仍在 |
| 根因 | 数据**没有丢**（localStorage 持久化本身是好的），是前端未在加载时恢复「上次活动会话」。`wb_workbench.js:130` `activeConvo: ''` 初值即空，`init()` 也未读回 |
| 影响范围 | 所有用户每次刷新都要多点一次；体感像"对话丢了"，容易误判为数据丢失 |
| 与 WorkBuddy 差异 | **已取证（2026-09-23）**：WorkBuddy 把会话恢复做成显式设计——欢迎页显示条件含 `!isRestoringSession`（恢复期间**主动抑制欢迎页**，避免闪屏），会话标识走 URL（`taskId`/`sessionId`），另有 `sessionTabsCache` 按 session 恢复打开的 tab。**MiniYuxi 完全缺失该机制 → 确认为一致性缺口** |
| 建议修法 | 最小改动：把 `state.activeConvo` 持久化到 localStorage，`init()` 中读回并调 `selectConvo(id)`。**涉及"是否自动打开上次会话"的行为选择，需产品确认后再改** |

### 🟡 D4｜折叠态下「新建会话」不可达（P1）

| 项 | 内容 |
|---|---|
| 现象 | 默认侧边栏处于折叠态（宽 48px），此时 `#btnNewChat` 尺寸为 **0×0**，点不到；必须先展开侧边栏 |
| 复现 | 打开桌面端（默认折叠）→ 直接找「新建会话」→ 无入口且点击超时；点 `#btnExpand` 展开后按钮变为 236×36，可正常点击 |
| 根因 | **（2026-09-23 修正）** `#btnNewChat` 位于 `web/index.html:289`，而它属于 **`#expandedBody`（展开态容器，275–302 行）**，不在折叠容器内。折叠态 `.conversation-list-expanded { display: none }` 使其尺寸归零——**属设计使然，不是元素缺失**。折叠态仅有 logo + `#btnExpand`（点 `#collapsedUpper` 任意处可展开，`wb_workbench.js:1823`），故实际是 **2 次点击可达**，不是"完全无法新建" |
| 影响范围 | 默认态用户需先猜到"要展开侧边栏"才能新建对话；可发现性差 |
| 与 WorkBuddy 差异 | **已取证（2026-09-23）**：WorkBuddy 在应用层把 `new-conversation` 绑定为 **Ctrl+N**（`scope: "app"`, `editable: true`），**与侧边栏是否折叠无关**——即它用快捷键保证了新建对话的恒定可达性。MiniYuxi 既无折叠态入口、也无 Ctrl+N → 确认为一致性缺口 |
| 建议修法 | ① 绑定 **Ctrl+N**（键位与 WorkBuddy 完全一致，纯增量、零行为改动）；② 可选：折叠态 `#collapsedUpper` 补一个新建对话图标按钮。**建议先做 ①** |

### 🟢 D5｜重复启动无单实例保护（P2）

| 项 | 内容 |
|---|---|
| 现象 | 连续启动桌面端会起出多个实例：实测同一时刻存在 **3 个 `miniyuxi-desktop.exe` + 4 个 `miniyuxi-sidecar.exe`** |
| 复现 | 连续运行 `miniyuxi-desktop.exe` 三次 → `tasklist \| grep miniyuxi` 可见多组进程并存 |
| 影响范围 | 每个实例各占一个 sidecar（82MB 内核、各自 60–85MB 内存），`data/sidecar.json` 被互相覆盖，端口契约指向的实例不确定；用户关掉一个窗口后台仍有内核常驻 |
| 与 WorkBuddy 差异 | **已取证（2026-09-23）**：WorkBuddy asar 中 `requestSingleInstanceLock` **5 命中**、`second-instance` **16 命中** → 它**有**单实例锁与"第二实例转交主实例"处理。MiniYuxi 无此机制 → 确认为一致性缺口 |
| 建议修法 | Tauri 侧接 `tauri-plugin-single-instance`（等价能力）；或外壳启动时先探测 `data/sidecar.json` 的 pid 存活则聚焦已有窗口 |

---

## 三、附带发现（工程侧，非功能验收项）

| 项 | 说明 |
|---|---|
| 清理命令失效 | `verify_desktop.sh` 里的 `taskkill /F /IM` 在 Git Bash 下会被路径转换吃掉参数，表现为「命令不报错但进程还在」——这是 D5 实例堆积的帮凶。已修：加 `MSYS_NO_PATHCONV=1` |
| Playwright 版本错配 | 本机 `ms-playwright` 缓存 chromium-1234，pip 装到的 playwright 要 1243，直接 `launch()` 报 "Executable doesn't exist"。已改为自动探测缓存/系统 Chrome，**不必下 150MB 浏览器** |
| 弹层遮挡导致误判 | 遍历时若某步弹窗不关掉，后续点击全部超时，很容易被误报成「功能点不了」。脚本已加统一的弹层探测+关闭 |

---

## 四、一致性对齐（与 WorkBuddy 桌面端）—— ✅ 已解除阻塞，详见专项报告

**原判定「阻塞」只对了一半**：界面确实挂不上 Playwright/CDP，但 WorkBuddy 的**前端文案与配置以明文内嵌在 `app.asar`**（无加密、无字节码），可直接抠出来做功能与文案级比对。

> 📄 **专项报告：`docs/desktop-consistency-baseline-20260923.md`**（含完整基准原文与逐项比对表）
> 🔧 存证：`docs/_wb_baseline.json`　复跑：`scripts/extract_wb_baseline.py`

### 4.1 已提取到的基准

| 基准 | 内容 |
|---|---|
| 顶部导航注册表 | **7 项**：home / claw / project / market(专家·技能·连接器) / automation / space / more(6 子项)，`defaultSelected: home` |
| 会话侧边栏文案全表 | `newChat` 新对话、`recentChats` 最近对话、`noChats` 暂无对话、`loading` 加载中、`loadError` 加载失败请重试、`rename` 重命名、`delete` 删除、`confirmDelete` 确定要删除这个对话吗？、`yesterday`/`daysAgo` 时间分组、`settings` 系统设置、`expand`/`collapse` 展开/收起侧边栏 |
| 快捷键注册表 | **18 条**，含 `new-conversation`=**Ctrl+N**、`toggle-sidebar`=**Ctrl+B**，全部 `editable: true` |
| 会话恢复机制 | 欢迎页条件含 `!isRestoringSession`；会话标识走 URL（`taskId`/`sessionId`）+ `sessionTabsCache` 按 session 恢复 tab |

### 4.2 比对结论

| 轴 | 可比性 | 结论 | 优先级 |
|---|---|---|---|
| 顶部导航 | ❌ **不可比** | MiniYuxi 9 项与桌面端 7 项**零重合**；`岗位工作台`、`成本管理` 在桌面端 **0 命中**——两产品 IA 不同源 | 🔴 需先定基准产品 |
| 场景标签 | ✅ 可比 | 「日常办公」10 项 **10/10 命中**、「代码开发」8 项 5/8 命中 → 与源码注释「实测＋同构补充」完全吻合，来源可信 | 🟢 通过 |
| 会话侧边栏 | ✅ 可比 | 文案层「新对话」「展开/收起侧边栏」**完全一致**；缺 删除/重命名/空态/时间分组/加载失败重试 | 🔴 删除（U2 遗留） |
| 快捷键 | ✅ 可比 | 18 条中 4 条一致；**缺 Ctrl+N、Ctrl+B**（纯增量、零行为改动） | 🔴 Ctrl+N / Ctrl+B |
| 会话恢复 | ✅ 可比 | WorkBuddy 有显式恢复设计，MiniYuxi 缺失 | 🟡 P1（见 D3） |

### 4.3 一条重要纠偏

**WorkBuddy 应用层没有 Ctrl+K 全局命令面板**。asar 里的「命令面板」只有两处，均非全局快捷键面板：① 输入框打 `/` 唤起的斜杠命令面板；② 内嵌 VSCode/Monaco 编辑器自带的 `Command Palette`（编辑器组件遗产）。故审计报告 U10 把「全局命令面板 ⌘K」当对齐目标**方向是错的**——MiniYuxi 现在把 Ctrl+K 绑成"聚焦输入框"属**新增**，与 WorkBuddy 不冲突。

### 4.4 仍无法覆盖的部分

本次是**静态文案与配置级**取证，能证明"有哪些入口、叫什么、绑什么键"，**不能证明**"入口在屏幕上的绝对位置、视觉层级、动效"。像素级布局一致性仍需：① WorkBuddy 各功能页截图；② 允许我对 WorkBuddy 界面截图取证；③ 其 UX/交互规格文档。

---

## 五、复跑方式

```bash
cd "E:/HR有关AI/AI应用基座最佳实践/14_自研MiniYuxi"
.venv/Scripts/python.exe tests/_acceptance_desktop.py     # 需先启动桌面端
```

退出码 0 = 无 P0/P1 失败。当前实测：**通过 20 项 / 失败 2 项（另有 2 个 P0 从接口错误中捕获，均已修复并复验）**。

重新提取 WorkBuddy 一致性基准（WorkBuddy 升级后需重跑以刷新基准）：

```bash
C:/Users/Administrator/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe scripts/extract_wb_baseline.py
```
