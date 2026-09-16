# WorkBuddy 工作台复刻（MiniYuxi）交付说明

> 目标页面：`https://www.workbuddy.cn/app`（未登录态）
> 复刻产物：MiniYuxi 内的独立工作台页面 `/wb`
> 逆向工具：`auto-js-reverse` + Chrome CDP（实测）
> 验证：`selftest 20/20` + 页面截图 + `/api/wb/chat` 端到端跑通

---

## 一句话结论

已用 **auto-js-reverse** 对 `www.workbuddy.cn/app` 做真实浏览器逆向，把页面的 DOM 结构、CSS 视觉、交互逻辑完整复刻进 MiniYuxi；产物是可独立访问的 `/wb` 页面，视觉与交互高度一致，后端接入了 MiniYuxi 自己的 RAG+LLM（支持引用来源），无法复刻的部分已给出明确降级方案。

---

## ⚠️ 关键风险与边界

| 项 | 说明 | 级别 |
|---|---|---|
| 未登录态 | 原站 `/app` 在未登录下只展示「欢迎态」，会话列表、右侧详情面板实际为空；复刻默认让右侧面板**可交互展开** | 🟡 中 |
| 账号/后端 | 原站登录态、用户会话、支付等依赖 WorkBuddy 账号体系，本复刻为本地/单机模式 | 🟡 中 |
| 版权/合规 | 图标、logo 直链原站 CDN；仅供内部产品学习与 MiniYuxi 集成参考，不对外发布 | 🟡 中 |
| 静态资源失效 | 若原站 CDN 禁用外链，图标/logo 会触发 onerror 降级为占位文字 | 🟢 低 |

---

## 1. 逆向过程摘要

| 步骤 | 工具 | 成果 |
|---|---|---|
| 启动 CDP Chrome | `--remote-debugging-port=9222 --remote-allow-origins=* --headless=new` | 可用 |
| 修复 auto-js-reverse 兼容 Bug | 删除 `browser_connector.py` 手动注入的 `Host` 头（Chrome 152 会因此 HTTP 500） | MCP 握手通过，12 工具可用 |
| 抓取 DOM/CSS | `execute_js` 取 `outerHTML` / `styleSheets.cssRules` / `getComputedStyle` | 得 `dom_full.html`（133 KB）、`css_external.css`（932 KB）、`css_variables.txt`、`computed_styles.txt`（20 KB） |
| 提取资源清单 | `querySelectorAll('img/src')` + 字体/CSS 链接 | 原站 logo、默认头像、外链 CSS 均定位 |
| 交互分析 | `outerHTML` 解构输入区、场景 tab、右侧面板 | 确认 contenteditable 输入框、10 个快捷入口、概览/产物 tab、引用来源面板 |
| 验证截图 | Headless Chrome 1600×900 | 复刻页与原站布局/配色/字体高度一致 |

---

## 2. 文件清单

| 路径 | 作用 | 说明 |
|---|---|---|
| `web/wb_workbench.html` | 复刻页主 HTML | 三栏布局：侧边栏 / 主聊天区 / 右侧面板 |
| `web/wb_workbench.css` | 样式表 | 按实测 computed style 还原配色、字体、间距、动效、响应式 |
| `web/wb_workbench.js` | 交互脚本 | 展开/收起侧边栏、场景 tab、快捷入口、contenteditable 输入、发送、流式回复、主题切换 |
| `web/wb_icons.json` | 原站快捷入口 SVG 图标 | auto-js-reverse 抓取，前端注入 |
| `core/wb_workbench.py` | 后端模块 | 静态配置 + `/api/wb/chat`（RAG 引用 + LLM 生成）+ stats |
| `api.py`（改动） | 路由挂载 | `/wb`、静态资源、`/api/wb/bootstrap\|chat\|stats` |
| `web/index.html`（改动） | 主入口 Tab | 新增「WB 工作台」标签，点击新开 `/wb` |
| `WB_工作台复刻_交付说明.md` | 本文档 | 交付说明与降级方案 |
| 外部：`C:/Users/Administrator/WorkBuddy/_reverse/` | 逆向原始素材 | DOM/CSS/资源清单/图标/关键元素样式 |
| 外部：`C:/Users/Administrator/WorkBuddy/_shot/replica_1600.png` | 复刻页截图 | 1600×900 headless 截图 |

---

## 3. 关键实现说明

### 3.1 视觉还原（数值来源：auto-js-reverse 实测 computed style）

| 元素 | 实测值 | 复刻实现 |
|---|---|---|
| 页面底/侧栏背景 | `rgb(242,242,242)` → `#f2f2f2` | `--wb-canvas` |
| 主按钮 / 激活 Pill | `rgb(26,26,26)` → `#1a1a1a` / `rgba(0,0,0,.75)` | `--wb-primary` / `--wb-primary-soft` |
| 主面板背景 | `rgb(255,255,255)` → `#fff` | `--wb-panel` |
| 次要文字 | `rgba(0,0,0,.7)` | `--wb-text-secondary` |
| 边框 | `#e0e0e0` | `--wb-border` |
| 字体 | 西文 `Inter...` + 中文 `PingFang SC` | `--wb-font` |
| Header | 高 56px、sticky、z-index 100、padding 0 24px | `.cloud-welcome__header` |
| Nav item | 14px/500、padding 8 12、radius 6 | `.cloud-welcome__nav-item` |
| 输入槽 | width 800、radius 18、padding 2px 2px 4px | `.wb-home-composer__input-slot` |
| 场景 Pill | h 32、radius 100px、padding 0 12、gap 4 | `.wb-scene-tabs__pill` |
| 侧边栏折叠 | w 48、transition width .25s ease-out | `.conversation-list` |
| 右侧展开 | transition padding-top .18s cubic-bezier(.05,.7,.1,1) | `.sidebar-next` |

### 3.2 布局与响应式

- 三栏 flex 布局，左侧 48px ↔ 260px 可展开，右侧 320px 可收起。
- 响应式断点：
  - `max-width: 1279px`：右侧 280px、内容区 760px
  - `max-width: 1024px`：隐藏右侧，nav 部分收起
  - `max-width: 768px`：左侧变抽屉、nav 隐藏、欢迎区 padding 缩小
  - `max-width: 640px`：footer hint 隐藏、间距收紧
  - `max-width: 480px`：标题/输入区进一步缩小

### 3.3 交互还原

| 交互 | 复刻实现 |
|---|---|
| 侧边栏展开/收起 | 点击左上角菜单按钮，width .25s ease-out |
| 场景 Tab 切换 | 日常办公 ↔ 代码开发，切换快捷入口分组 |
| 快捷入口点击 | 把对应名称填入输入框并聚焦 |
| 输入框 | `contenteditable` 模拟原站，支持 Enter 发送、Shift+Enter 换行 |
| 发送消息 | 进入对话态，渲染用户气泡 + AI 回复 |
| 流式回复 | 后端 `llm_chat` 一次返回，前端按字符流式显示 |
| 引用来源 | 后端 `rag.search` 命中片段 → 右侧「引用来源」面板展示 |
| 右侧面板 | 概览/产物 Tab + 引用来源抽屉 + 收起/展开 |
| 主题切换 | Light/Dark 手动切换，localStorage 持久；支持 `prefers-reduced-motion` |
| 搜索过滤 | 展开侧边栏时按关键词过滤本地会话列表 |

### 3.4 后端集成（MiniYuxi 原生）

`core/wb_workbench.py` 遵循现有 core 模块风格：
- `init()` 内 `CREATE TABLE IF NOT EXISTS wb_replica_events`（不动 `core/db.py`，符合项目红线）。
- `/api/wb/bootstrap`：返回导航、场景分组、概览数据。
- `/api/wb/chat`：
  1. `rag.search(tenant_id, message, top_k=4)` 检索知识库；
  2. 拼接上下文后调 `rag.llm_chat(...)`；
  3. 返回 `{ok, reply, sources, degraded, err}`；
  4. LLM/RAG 任何异常都降级为本地占位回复，保证前端可用。
- `/api/wb/stats`：统计复刻页事件数。

---

## 4. 与原站的差异与降级方案

| 原站能力 | 本复刻状态 | 降级/替代方案 |
|---|---|---|
| WorkBuddy 账号登录 | ❌ 未接入（需 WorkBuddy 账号体系） | 本地模式，登录按钮提示"本地模式" |
| 真实会话历史 | ❌ 无法调用原站 `/console/accounts` | 本地 mock 6 条会话 + SQLite 事件表持久化 |
| 真实后端对话 | ❌ 不连 WorkBuddy 后端 | 接 MiniYuxi `/api/wb/chat`（RAG+LLM），异常时返回降级占位文本 |
| 原站 fetch 单飞缓存（`__accountsSingleFlightInstalled`） | ❌ 未复刻 | 该逻辑与账号/鉴权相关，本地模式无需复刻 |
| 未登录态右侧面板折叠 | 🟡 已展开以便展示交互 | 顶部按钮可收起；1024px 以下自动隐藏 |
| 主题偏好持久化 | 🟡 用 `localStorage` 本地持久 | 未接入账号级偏好 |
| 真实图标/logo | ✅ 直链原站 CDN；失效降级 | `onerror` 隐藏并显示占位文字 |
| 响应式断点 | ✅ 按原站 `@media` 还原 | 细节按 MiniYuxi 使用习惯微调 |
| 加密/反爬参数 | 未登录态未触发签名 | 无需处理 |

---

## 5. 验证结果

| 验证项 | 结果 |
|---|---|
| `selftest.py` | **20/20 通过**（三指纹未动） |
| `/wb` 页面加载 | HTTP 200，38 KB，图标注入成功 |
| `/api/wb/bootstrap` | 返回 8 个 nav、2 个场景分组、概览数据 |
| `/api/wb/chat` | 真实返回 LLM 回复 + 4 条引用来源，非降级 |
| `/api/wb/stats` | 返回事件统计（修复 sqlite 连接关闭顺序后通过） |
| 截图对比 | 1600×900 下与原站布局/配色/字体/交互元素高度一致 |

---

## 6. 如何访问

- 主界面：`http://127.0.0.1:8801/` → 左侧 Tab 栏点「WB 工作台」
- 直接访问：`http://127.0.0.1:8801/wb`

---

## 7. 后续可扩展点

1. 接入真实 LLM streaming：用 `gateway.chat_stream` 替换一次性 `rag.llm_chat`。
2. 登录态：若 WorkBuddy 开放 OAuth/SSO，可替换本地 mock。
3. 会话同步：把 `wb_replica_events` 升级到完整会话表，支持多轮历史。
4. 快捷入口模板：为「代码开发」分组补齐真实 SVG（当前用简笔画占位，可从登录态抓取）。
5. 深色主题：进一步细调暗色 token（当前基于原站 `--cr-*` 暗色变量）。
