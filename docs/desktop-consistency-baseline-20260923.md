# 桌面端一致性对齐：WorkBuddy 基准提取与逐项比对

> 日期：2026-09-23　对象：MiniYuxi 桌面端（Tauri 2 + PyInstaller sidecar）
> 基准：WorkBuddy 桌面端 `C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar`（296,579,386 bytes）
> 存证：`docs/_wb_baseline.json`　提取脚本：`scripts/extract_wb_baseline.py`（可复跑）

---

## 一句话结论

**「一致性对齐」从「阻塞」变为「可逐项比对」**——WorkBuddy 桌面端的导航注册表、侧边栏文案全表、18 条快捷键注册表已从 asar 中原样提取；比对后发现 **MiniYuxi 的顶部导航与 WorkBuddy 桌面端零重合（架构性差异，无法 1:1 对齐）**，但**会话侧边栏、快捷键、会话恢复三条轴可对齐，且已定位到具体缺口**。

---

## 一、基准是怎么拿到的（方法说明）

原先判定「阻塞」的理由是：WorkBuddy 桌面端是闭源 Electron 应用，无自动化接口、无法挂 CDP 遍历、无法可靠截图。**这个判断对了一半**——界面确实挂不上，但**它的前端文案与配置以明文内嵌在 `app.asar` 中，没有加密也没有编译成字节码**，可以直接抠出来。

| 步骤 | 做法 | 坑 |
|---|---|---|
| 1 | `grep -a` 直接在 asar 上搜关键词 | asar 内是**超长压缩行**，`grep -oE ".{90}关键词.{90}"` 这类上下文匹配**必然失败**（返回空） |
| 2 | 改用 Python 读字节 → `bytes.find()` 定位 → 切片窗口 → `decode("utf-8","replace")` | 可靠，能取到任意宽度上下文 |
| 3 | 对 `键名: {` 做**花括号配平**，整块导出 i18n / 注册表 | 一次拿到完整文案表，不用逐条猜 |

**局限（必须说明）**：这是**静态文案与配置**级别的取证，能证明「有哪些功能入口、叫什么名字、绑什么快捷键」，**不能证明**「入口在屏幕上的绝对位置、视觉层级、动效」。所以本报告解决的是**功能与文案一致性**，像素级布局一致性仍需真实界面截图。

---

## 二、基准事实（WorkBuddy 桌面端实测）

### 2.1 顶部导航注册表 —— 7 项

原文（`docs/_wb_baseline.json` → `nav_registry_raw`）：

| 顺序 | id | target | 说明 |
|---|---|---|---|
| 10 | `home` | `builtin:new_task` | **默认选中**（`defaultSelected: "home"`），内部 `modes.defaultSelected = "work"` |
| 20 | `claw` | `builtin:claw` | |
| 30 | `project` | `builtin:project` | |
| 40 | `market` | `builtin:experts` | 含 3 个子项：`experts` / `skills` / `connectors` |
| 50 | `automation` | `builtin:automation` | |
| 70 | `space` | `builtin:space` | |
| 9000 | `more` | `builtin:more` | 含 6 个子项：`my-files` / `agent-mail` / `tencent-docs` / `ima` / `lexiang` / `inspiration` |

### 2.2 会话侧边栏文案全表（英文基准原文）

```json
sidebar: {
  "newChat": "New Chat",
  "recentChats": "Recent Chats",
  "loading": "Loading...",
  "noChats": "No chats yet",
  "untitledChat": "New Chat",
  "yesterday": "Yesterday",
  "daysAgo": "{{days}} days ago",
  "confirmDelete": "Are you sure you want to delete this chat?",
  "rename": "Rename",
  "delete": "Delete",
  "settings": "Settings",
  "loadError": "Failed to load, please retry"
}
```

同命名空间另有：`sidebar.collapse`=收起侧边栏、`sidebar.expand`=展开侧边栏、`sidebar.taskList`=任务列表、`sidebar.settings`=系统设置、`sidebar.version`=版本、`sidebar.themeLight`=浅色…

### 2.3 快捷键注册表 —— 18 条（全部 `editable: true`）

原文结构 `{ id, labelKey, category, scope, defaultMac, defaultWin, editable }`：

| # | id | category | Win | Mac |
|---|---|---|---|---|
| 1 | `new-conversation` | navigation | **Ctrl+N** | Meta+N |
| 2 | `toggle-sidebar` | window | **Ctrl+B** | Meta+B |
| 3 | `toggle-artifacts` | window | Ctrl+Shift+B | Meta+Shift+B |
| 4 | `open-settings` | window | Ctrl+, | Meta+, |
| 5 | `toggle-fullscreen` | window | F11 | Ctrl+Meta+F |
| 6 | `toggle-window` | window | Shift+Alt+W | Shift+Alt+W |
| 7 | `prev-task` | navigation | Ctrl+[ | Meta+[ |
| 8 | `next-task` | navigation | Ctrl+] | Meta+] |
| 9 | `search-in-conversation` | editing | Ctrl+F | Meta+F |
| 10 | `toggle-voice-recording` | editing | Ctrl+D | Meta+D |
| 11 | `send-message` | editing | Enter | Enter |
| 12 | `newline` | editing | Shift+Enter | Shift+Enter |
| 13 | `stop-generation` | editing | Escape | Escape |
| 14 | `trigger-picker` | editing | `@` | `@` |
| 15 | `trigger-slash-command` | editing | `/` | `/` |
| 16 | `font-size-increase` | general | Ctrl+= | Meta+= |
| 17 | `font-size-decrease` | general | Ctrl+- | Meta+- |
| 18 | `font-size-reset` | general | Ctrl+0 | Meta+0 |

> ⚠️ 注意：**WorkBuddy 应用层没有 Ctrl+K 命令面板**。asar 里的「命令面板」有两处，均非全局快捷键面板：
> ① 输入框打 `/` 唤起的**斜杠命令面板**（issue #56021 提到要过滤内置预置 skill）；
> ② 内嵌 VSCode/Monaco 编辑器自带的 `Command Palette`（`GotoLineAction.ID`，属编辑器组件遗产）。
> 所以审计报告 U10 把「全局命令面板 ⌘K」当作对齐目标，**方向是错的**。

### 2.4 会话恢复机制 —— WorkBuddy 有，且是显式设计

欢迎页显示条件（原文）：

```js
showWelcome = isNotLoggedIn
  || (!account && accountInitialized)
  || (!isClawView && !currentConversation && !isCreatingConversation
      && !isRestoringSession && !hasTaskIdInUrl);
```

关键点三条：
1. **`!isRestoringSession`** —— 恢复会话期间**主动抑制欢迎页**，避免"闪一下欢迎页再跳走"；
2. `isRestoringSession` 初值取自 `router?.params.taskId` 或 `new URLSearchParams(location.search).get("sessionId")` —— **会话标识走 URL 持久化**，刷新后能凭 URL 复原；
3. 另有 `restoreSessionTabs(resetKey)` + `sessionTabsCache` —— **按 session 维度缓存并恢复打开的 tab**。

### 2.5 场景标签交叉验证（用来核对 MiniYuxi 场景分组的来源可信度）

| 分组 | 标签命中情况 |
|---|---|
| MiniYuxi「日常办公」10 项 | 幻灯片 46 / 视频生成 15 / 深度研究 12 / 文档处理 10 / 数据分析 28 / 可视化 43 / 金融服务 9 / 产品管理 9 / 设计 1328 / 邮件编辑 8 → **10/10 全部命中** ✅ |
| MiniYuxi「代码开发」8 项 | 代码补全 17 / 单元测试 21 / 代码审查 9 / 接口联调 1 / 性能分析 6 命中；**重构建议 / Bug 定位 / SQL 优化 未命中** → 5/8 |

**结论**：MiniYuxi 源码注释「日常办公 = 原站实测 10 项；代码开发 = 同构补充」**完全被基准验证**——日常办公 10 项确系实测来源，代码开发 8 项中有 3 项是自造。分组来源可信，无编造。

---

## 三、逐项比对

### 3.1 顶部导航轴 —— ❌ 无法 1:1 对齐（架构性差异）

| | WorkBuddy 桌面端 | MiniYuxi |
|---|---|---|
| 结构 | 7 项（含 2 个带子项的分组，共 16 个可到达目标） | 9 项，扁平无分组 |
| 条目 | home / claw / project / market / automation / space / more | 新建 / 导入 / 知识库 / HRM人事 / 流程 / 模型切换 / 成本管理 / 管理 / 岗位工作台 |
| 重合度 | **仅「新建」≈「home(new_task)」概念相近，其余零重合** | — |

**判定**：MiniYuxi 的 9 项导航**不是 WorkBuddy 桌面端的复刻**。经 asar 反查，`岗位工作台`、`成本管理` 两个词在桌面端**一次都不出现**（计数 0），说明这套 IA 来自**另一个来源**（WorkBuddy 网页控制台／早期工作台规格），而非用户指定的桌面端基准。

> 这一条是本次最重要的发现：**用户要求的「以 WorkBuddy 桌面端为基准逐一比对相同功能入口位置」，在导航轴上没有可比对象**——不是我没做，是两个产品在这一层没有相同功能。**要真正对齐导航，需要先确认以哪个产品为准**（桌面端 or 网页控制台），这是产品定位决策，不是缺陷修复。

### 3.2 会话侧边栏轴 —— 🟡 可对齐，缺口明确

| 能力 | WorkBuddy 文案键 | MiniYuxi 现状 | 判定 |
|---|---|---|---|
| 新建对话 | `newChat` = 新对话 | ✅ `#btnNewChat` 文案「新对话」 | 🟢 **完全一致** |
| 展开/收起侧边栏 | `sidebar.expand` / `sidebar.collapse` | ✅ `title="展开侧边栏"` / `"收起侧边栏"` | 🟢 **完全一致** |
| 最近对话分组 | `recentChats` = 最近对话 | ❌ 无分组标题，列表直出 | 🟡 缺 |
| 空态 | `noChats` = 暂无对话 | ❌ 无空态文案 | 🟡 缺 |
| 加载中 | `loading` = 加载中… | ❌ 无 | 🟡 缺 |
| 加载失败重试 | `loadError` = 加载失败，请重试 | ❌ 无 | 🟡 缺 |
| 时间分组 | `yesterday` = 昨天 / `daysAgo` = N 天前 | ❌ 无（仅存 `time:'刚刚'` 静态串） | 🟡 缺 |
| 重命名 | `rename` = 重命名 | ❌ 无 | 🟡 缺 |
| 删除 + 二次确认 | `delete` = 删除 / `confirmDelete` = 确定要删除这个对话吗？ | ❌ 无删除入口 | 🔴 缺（审计报告 U2 明确要求「新建/切换/删除实时同步」，**删除这一项没落地**） |
| 系统设置 | `sidebar.settings` = 系统设置 | ❌ 无「系统设置」入口（只有顶部「管理」nav） | 🟡 缺 |

### 3.3 快捷键轴 —— 🔴 18 条中 MiniYuxi 只有 2 条对齐

| WorkBuddy 快捷键 | MiniYuxi 实测 | 判定 |
|---|---|---|
| Enter = 发送 | ✅ `wb_workbench.js:1852` `e.key==='Enter' && !e.shiftKey` | 🟢 一致 |
| Shift+Enter = 换行 | ✅ 同上分支 | 🟢 一致 |
| `@` = 引用选择器 | ✅ `:1703` / `:1735` `insertAtCursor('@'+id)` | 🟢 一致 |
| `/` = 斜杠命令 | ✅ `:1777` `insertAtCursor('/'+title)` | 🟢 一致 |
| **Ctrl+N = 新建对话** | ❌ **未绑定**（全文件无 Ctrl+N） | 🔴 **缺** |
| **Ctrl+B = 切换侧边栏** | ❌ **未绑定**（只能点 `#btnExpand`/`#btnCollapse`） | 🔴 **缺** |
| Escape = 停止生成 | 🟡 `:218` Escape 只做 `closeMenu()`，未绑定停止生成 | 🟡 语义不全 |
| Ctrl+F = 会话内搜索 | ❌ 无（有 `#convSearch` 但那是**会话列表搜索**，非会话内搜索） | 🟡 缺 |
| Ctrl+, = 打开设置 | ❌ 无 | 🟡 缺 |
| Ctrl+Shift+B = 切换产物面板 | ❌ 无（有 `#detailPanelContainer` 但无快捷键） | 🟡 缺 |
| Ctrl+[ / Ctrl+] = 上/下一任务 | ❌ 无 | 🟡 缺 |
| Ctrl+D = 语音录制 | ❌ 无（能力本身可能未实现） | ⚪ 不适用 |
| F11 / Shift+Alt+W = 全屏/切窗 | ❌ 无（属 Tauri 外壳能力） | 🟡 缺 |
| Ctrl+= / Ctrl+- / Ctrl+0 = 字号 | ❌ 无 | 🟡 缺 |
| （MiniYuxi 独有）Ctrl+K = 聚焦输入框 | WorkBuddy **未绑定 Ctrl+K** | ⚪ 属新增，非冲突 |

**判定**：**Ctrl+N 与 Ctrl+B 是最该补的两条**——纯增量、零行为改动、与 WorkBuddy 键位完全一致，且直接解决下节 D4 的可达性问题。

### 3.4 会话恢复轴 —— 🔴 一致性缺口（本条重新定性）

| | WorkBuddy | MiniYuxi |
|---|---|---|
| 机制 | URL 携带 `taskId`/`sessionId` + `isRestoringSession` 抑制欢迎页 + `sessionTabsCache` 按 session 恢复 tab | `state.activeConvo` 初值 `''`（`wb_workbench.js:130`），启动后**不读回上次会话** |
| 表现 | 刷新/重开 → 回到原会话 | 刷新 → 回欢迎页，需手动点回列表 |

**判定**：D3 **是一致性缺口，不只是"体验建议"**。WorkBuddy 把它做成了显式设计（连"恢复期间抑制欢迎页"这种细节都处理了），MiniYuxi 完全缺失。**数据没丢**（localStorage 持久化是好的），缺的是"加载时恢复上次活动会话"这一步。

---

## 四、比对结论汇总

| 轴 | 可比性 | 结论 | 优先级 |
|---|---|---|---|
| 顶部导航 | ❌ 不可比 | 两产品 IA 不同源；`岗位工作台`/`成本管理` 在桌面端 0 命中。需先定基准产品 | 🔴 **决策项** |
| 场景标签 | ✅ 可比 | 日常办公 10/10 命中、代码开发 5/8——来源可信，无编造 | 🟢 通过 |
| 会话侧边栏 | ✅ 可比 | 文案层 2 项完全一致；**缺 删除/重命名/空态/时间分组/加载失败重试** | 🔴 删除（U2 遗留）／🟡 其余 |
| 快捷键 | ✅ 可比 | 18 条中 4 条一致；**缺 Ctrl+N、Ctrl+B**（高价值低成本） | 🔴 Ctrl+N/Ctrl+B |
| 会话恢复 | ✅ 可比 | WorkBuddy 有显式恢复机制，MiniYuxi 缺失 | 🟡 P1 |

---

## 五、需要决策的事项

1. **导航基准以谁为准？** WorkBuddy 桌面端（7 项，home/claw/project/market/automation/space/more）与 MiniYuxi 现有 9 项完全不同源。若以桌面端为准 → 是**重构 IA**（大改）；若以网页控制台为准 → 需提供网页控制台基准。**这是产品定位决策，我不擅自改。**
2. **是否补齐 Ctrl+N / Ctrl+B？** 纯增量、键位与 WorkBuddy 一致、直接解决折叠态新建对话不可达。**低风险，建议做。**
3. **是否补齐会话侧边栏的删除/重命名？** 审计报告 U2 原本就要求「删除实时同步」，属**未落地项**（非新需求）。
4. **是否实现"加载时恢复上次会话"？** 对齐 WorkBuddy 的显式设计；做法最小化：把 `state.activeConvo` 持久化并在 `init()` 中读回。

---

## 六、复跑方式

```bash
cd "E:/HR有关AI/AI应用基座最佳实践/14_自研MiniYuxi"
C:/Users/Administrator/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe scripts/extract_wb_baseline.py
# → 重新生成 docs/_wb_baseline.json（WorkBuddy 升级后需重跑以刷新基准）
```

单关键词上下文速查（排查时用）：

```bash
python scripts/_asar_ctx.py "新建对话" "Ctrl+N"
python scripts/_asar_i18n.py sidebar nav
python scripts/_asar_shortcuts.py
```
