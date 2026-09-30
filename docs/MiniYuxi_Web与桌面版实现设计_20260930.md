# MiniYuxi · 网页版 + 桌面版 完整实现设计文档

> **版本**：v0.4.0　|　**日期**：2026-09-30　|　**状态**：两端**已实测可运行**
> **实测基线**：`cli.py doctor` 5/5 通过；Web 端 `run.py` → 8801 端口 `/api/health` HTTP 200；桌面 sidecar exe → 8811 端口 HTTP 200。
> **定位**：企业级 Agent · 零 Docker · 数据可出本机 · 可商用（依据 `CONTEXT.md` §一）
> **关联文档**：《OpenClaw Agent 调度机制五阶段技术文档_20260930.md》

---

## 0. 一句话结论 + 交付概览

**MiniYuxi Web 与桌面版共用同一个 Python 内核（`api.py` + `core/`），桌面端只是 Tauri 外壳拉起内核 sidecar 并导航到工作台——两端功能天然一致，不存在两套实现。**

| 项 | 值 |
|---|---|
| 架构模式 | **单内核 + 双外壳**（Web 走浏览器；桌面走 Tauri 窗口 → 127.0.0.1） |
| 内核入口 | `api.py`（FastAPI）→ `core/`（58 个模块） |
| 前端 | 单页工作台 `web/index.html` + `web/wb_workbench.js`（**零构建、无框架**） |
| 桌面外壳 | Tauri 2 + `tauri-plugin-shell` + Rust 1.77.2 |
| 数据 | SQLite（WAL）+ sqlite-vec 向量 + FTS5 全文，**单文件** |
| 外部服务 | **零**（不依赖任何云服务 / 容器） |
| 两端一致性 | ✅ **代码级一致**——同一 `api.py`、同一 `web/`、同一 `core/` |

---

## 1. 技术选型与理由

| 层 | 选型 | 版本 | 为什么是它 |
|---|---|---|---|
| **后端框架** | FastAPI + Uvicorn | `>=0.110` / `>=0.27`（实测 0.141.1 / 0.53.0） | 轻量、原生 async、自动 OpenAPI；企业级可审计路由清晰 |
| **数据库** | SQLite（WAL 模式） | 标准库 | **零部署**、单文件可备份、ACID 够用；企业级小团队完全够 |
| **向量检索** | sqlite-vec | `>=0.1.6`（实测 v0.1.9） | SQLite 扩展，**纯 C 无服务进程**，避免引入 Milvus/Qdrant 的运维负担 |
| **全文检索** | SQLite FTS5 | 内置 | 中文 bigram 分词，零外部依赖 |
| **前端** | 原生 HTML + JS，**无框架无构建** | — | **免 npm install / 免打包**，桌面端 `frontendDist` 直接指静态目录；启动即用、零供应链风险 |
| **桌面外壳** | Tauri 2 | `2.x` | 安装包小（vs Electron 100MB+）、内存低、官方 sidecar 插件成熟 |
| **sidecar 打包** | PyInstaller | — | 冻结成单文件 exe，桌面端免装 Python |
| **LLM 接入** | 可插拔 provider | — | 未配 Key 走离线兜底，**核心功能不依赖 LLM** |

**关键选型哲学**：**所有外部依赖都是"增强"而非"前提"**。没装 PyInstaller 就跑 Web 版，没配 LLM Key 就走 BM25 兜底，`cli.py doctor` 全绿即可交付。这与 OpenClaw 强依赖 Node 生态、Dify 强依赖 Docker 形成对比。

---

## 2. 项目目录结构

```
14_自研MiniYuxi/
├── api.py                      # ★ FastAPI 应用：所有 HTTP 路由（Web/桌面共用）
├── run.py                      # ★ 启动器：初始化 DB → 起 uvicorn → 开浏览器
│                               #   兼作 PyInstaller 冻结入口（桌面 sidecar）
├── cli.py                      # 命令行：chat / ask / doctor / kb / tools / skills / serve
│
├── core/                       # ★ 内核（58 个模块，业务逻辑全在此）
│   ├── agent_loop.py           #   ReAct 反思循环内核（一切工具执行的唯一入口）
│   ├── agent_runtime.py        #   会话保活 + 线程池并发
│   ├── gateway.py              #   LLM 网关（流式 / tool calling / 重试）
│   ├── provider_router.py      #   多供应商注册 + 故障转移
│   ├── tools_registry.py       #   工具注册 + 四段式治理管线
│   ├── security.py             #   hardline 黑名单 + 路径校验
│   ├── approval.py             #   审批卡 + resume_token 断点续跑
│   ├── egress.py               #   出境唯一收口（allow/deny/approval 三态）
│   ├── soc_audit.py            #   哈希防篡改审计链
│   ├── citation_gate.py        #   法条闸门（法律意见依据链）
│   ├── multitenant.py          #   配额/驻留/MLPS/CMK 闸门
│   ├── circuit_breaker.py      #   预算硬熔断（六闸门）
│   ├── observability.py        #   trace/span 可观测
│   ├── usage.py                #   token / 成本记账
│   ├── memory.py / _v2 / _slim #   记忆与上下文压缩
│   ├── rag.py / rag_adapter.py #   RAG 检索 + 外部 RAG 桥（RAGFlow/FastGPT）
│   ├── skills_catalog.py       #   技能唯一加载器
│   ├── subagent.py             #   生成-评审编排 / Agent 注册表
│   ├── taskflow.py / canvas.py #   显式 DAG 流程
│   ├── scheduler.py            #   定时任务
│   ├── db.py / config.py       #   SQLite 封装 / 配置
│   └── （HR/法务垂直：labor_relations / salary_* / resume_* / talent_map / interview / hrm）
│
├── web/                        # ★ 前端（单页工作台，零构建）
│   ├── index.html              #   主工作台（48KB）
│   ├── wb_workbench.js         #   交互逻辑（164KB）
│   ├── wb_workbench.css
│   ├── flow-canvas.html/js     #   流程画布（Dify 风格编排）
│   ├── experts-market.html/js  #   专家/技能市场
│   ├── office/                 #   办公套件
│   └── vendor/                 #   第三方库（本地化，不走 CDN）
│
├── apps/desktop/               # ★ 桌面外壳
│   ├── src/                    #   外壳启动页（index.html + main.js，等待内核就绪）
│   └── src-tauri/
│       ├── tauri.conf.json     #   frontendDist: "../src"  ← 指向启动页而非 web/
│       ├── Cargo.toml          #   Rust 1.77.2 + Tauri 2 + tauri-plugin-shell
│       ├── src/                #   Rust 侧：拉起/监控/停止 sidecar，就绪后导航内核
│       └── binaries/
│           └── miniyuxi-sidecar-x86_64-pc-windows-msvc.exe   # PyInstaller 产物（67MB）
│
├── scripts/build_sidecar.py    # PyInstaller 打包脚本（产物名规则有坑，见 §5.3）
├── skills/                     # 45 个技能（SKILL.md 体系）
├── data/                       # 运行时数据（DB / 密钥，gitignore）
├── tools/                      # 业务工具与适配器
├── workflows/                  # 流程定义
├── tests/                      # 测试（⚠️ test_*.py 被 .gitignore 忽略，需 git add -f）
├── requirements.txt            # pip 依赖
├── environment.yml             # conda 环境（python=3.13 + requirements）
├── pyproject.toml              # 包元数据（miniyuxi = cli:main）
└── CONTEXT.md                  # ★ 共享语言词典（唯一真相源）
```

> ⚠️ **注意 `tauri.conf.json` 的 `frontendDist: "../src"`**：桌面窗口首屏加载的是 `apps/desktop/src/index.html`（一个"等待内核就绪"的过渡页，含进度条 + 实时日志），Rust 侧探到 `/api/health` 返回 200 后才 `navigate` 到 `http://127.0.0.1:<port>`，此时加载的是 `web/index.html` 完整工作台。**这是"同一份工作台、两种入口"的关键设计。**

---

## 3. 核心功能清单

### 3.1 两端共有（同一 `api.py` 暴露）

| 分类 | 端点 | 功能 |
|---|---|---|
| **健康/生命周期** | `GET /api/health` · `POST /api/desktop/shutdown` | 健康探针（含存储/模型/检索模式）；桌面端优雅停机 |
| **认证授权** | `/api/auth/login` · `/api/me` · `/api/tenants` · `/api/users` | 登录（JWT）、租户与用户管理、密码改/重置 |
| **知识库 RAG** | `/api/kb/docs` · `/api/kb/search` · `/api/kb/upload` | 文档增删查、检索、上传（docx/pdf） |
| **对话** | `POST /api/chat`（SSE）· `POST /api/rag/ask` | 自主 Agent 循环问答 / 纯检索问答 |
| **Agent 运行时** | `/api/agent/session` · `/{sid}/submit` · `/{sid}` · `/{sid}/cancel` · `/api/agent/sessions` | 长会话创建、异步提交、状态轮询、取消、会话列表 |
| **工具** | `/api/tools/list` · `/api/tools/call` | 工具清单与治理版调用 |
| **流程画布** | `/api/flow/save` · `/api/flow/list` · `/api/flow/{fid}` | Dify 风格可视化编排持久化 |
| **专家市场** | `/api/experts/manifest` · `/api/market/*` | 专家清单、市场安装/启停 |
| **出境管控** | `/api/egress/inventory` · `/policy` · `/preset` · `/log` · `/classify` | 数据出境清单、策略、姿态预设、日志 |
| **成本** | `/api/usage/stats` | token / 成本统计 |
| **渠道** | `/api/channels/wecom/webhook` | 企业微信接入（webhook 触发） |
| **模型** | `/api/gateway/models` | 供应商模型列表 |
| **定时任务** | `core/scheduler` | cron / 间隔 / 一次性任务调度 |

### 3.2 桌面版专有

| 能力 | 实现 |
|---|---|
| 内核常驻 | Tauri 经 `tauri-plugin-shell` 拉起 sidecar exe，窗口关闭时停止 |
| 启动过渡页 | 进度条 + 实时内核日志（`sidecar://log` 事件）+ 手动重启/打开数据目录 |
| 就绪探针 | Rust 侧轮询 `/api/health`，200 后导航进工作台 |
| 数据目录隔离 | `%LOCALAPPDATA%\MiniYuxi\`（data + skills + 日志），**冻结后不落临时解压目录** |
| 无 Python 依赖 | 用户机无需装 Python（PyInstaller 已冻结） |

### 3.3 CLI（第三条腿）

```bash
python cli.py doctor      # 环境体检（5 项）
python cli.py chat        # 交互式对话
python cli.py ask "问题"  # 单次问答
python cli.py kb list     # 知识库管理
python cli.py tools       # 工具清单
python cli.py skills      # 技能清单
python cli.py serve       # 起服务（同 run.py）
```

---

## 4. 环境依赖与版本要求

| 项 | 要求 | 实测本机 |
|---|---|---|
| **Python** | `>=3.11`（conda 环境用 3.13；`.venv` 实测 3.12.14） | ✅ 3.12.14 |
| **FastAPI** | `>=0.110` | ✅ 0.141.1 |
| **Uvicorn** | `>=0.27` | ✅ 0.53.0 |
| **sqlite-vec** | `>=0.1.6` | ✅ v0.1.9 |
| **requests** | `>=2.31` | ✅ |
| **httpx** | `>=0.27`（测试用 `fastapi.testclient`） | ✅ |
| **文档解析** | `python-docx>=1.1` · `pymupdf>=1.24` · `pypdf>=4.2`（按需） | ✅ |
| **Rust**（仅桌面构建） | `>=1.77.2` + `rustfmt`/`clippy` | 需装 |
| **Node.js**（仅桌面构建） | Tauri CLI 需 Node，`@tauri-apps/cli@^2.0.0` | 需装 |
| **PyInstaller**（仅 sidecar 打包） | 由 `build_sidecar.py` 自动装 | — |
| **LLM Key** | **可选**（不配走离线兜底） | 未配，功能正常 |

**⚠️ 许可红线**：引入新依赖前必跑 `scripts/audit_licenses.py`——**零 copyleft**（GPL/AGPL/SSPL 禁用）。

---

## 5. 配置、构建、运行与打包

### 5.1 环境准备（一次性）

```bash
cd E:\HR有关AI\AI应用基座最佳实践\14_自研MiniYuxi

# 方式 A：用已有 .venv（推荐，本机已就绪）
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 方式 B：新建 venv
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 方式 C：conda
conda env create -f environment.yml
conda activate miniyuxi
```

### 5.2 运行

#### Web 端

```bash
# 默认 8801，自动开浏览器
.venv\Scripts\python.exe run.py

# 不开浏览器 + 指定端口
.venv\Scripts\python.exe run.py --no-open --port 8899

# 只起服务不开浏览器（推荐用于验证）
.venv\Scripts\python.exe run.py --no-open
```

**Windows 快捷方式**：双击 `run.bat` 或 `start_miniyuxi.bat`（`run.py` 已强制 stdout 为 UTF-8，避免 GBK 控制台输出 `⚠` 崩溃）。

#### 桌面端

```bash
# 前置：装 Rust + Node，sidecar exe 已存在则可跳过 npm run sidecar
cd apps\desktop
npm install                 # 首次
npm run dev                 # 开发模式（热重载）
npm run build               # 打包安装包（.msi / .exe）
```

`main.js` 说明（`apps/desktop/src/main.js:1-8`）：**无构建步骤，纯静态**。仅通过 `withGlobalTauri` 暴露的 `window.__TAURI__` 接收三类事件——`sidecar://log`（内核日志）、`sidecar://status`（就绪状态）、`sidecar://exit`（退出）——并提供"重启内核 / 打开数据目录"两个按钮。浏览器直接打开会提示"请用 npm run dev 启动桌面外壳"。

### 5.3 打包 sidecar（⚠️ 有坑）

```bash
# 在仓库根目录执行
.venv\Scripts\python.exe scripts\build_sidecar.py
# 或指定解释器 / 假设已装 PyInstaller
.venv\Scripts\python.exe scripts\build_sidecar.py --python "C:\path\to\python.exe"
.venv\Scripts\python.exe scripts\build_sidecar.py --no-install
```

**⚠️ 命名规则（`build_sidecar.py:10-16` 明确警告）**：Tauri 把 `externalBin` 条目名当**前缀**、target triple 当**后缀**拼接，即 `<entry>-<triple>`：

```
binaries/miniyuxi-sidecar  +  x86_64-pc-windows-msvc
→ 实际找：binaries/miniyuxi-sidecar-x86_64-pc-windows-msvc.exe
```

**写反了 cargo 会报**：`resource path 'binaries/xxx' doesn't exist`。

**⚠️ 另一个已修的坑**：`core/hrm.py` 用 `os.path.dirname(__file__)` 拼路径读 `hrm_schema.json`，冻结后必须落在 `_MEIPASS/core/` 下——**漏了它桌面端 `/api/hrm/*` 全线 500**（源码环境正常，打包专属缺陷）。已在 `build_sidecar.py` 显式打包（`HRM_SCHEMA`）。

**⚠️ skills 目录**：`run.py` 的 `_frozen_bootstrap()`（`run.py:30-40`）在冻结时把 `MINIYUXI_DATA_DIR` / `MINIYUXI_SKILLS_DIR` 指向 `%LOCALAPPDATA%\MiniYuxi\`，**避免每次启动都像全新安装**。实测该目录下 skills 已就位（`admin_office` / `administrative_value_judgment` / `billing_and_litigation_budget` 等）。

---

## 6. 端到端可验证启动说明

### 6.1 Web 端验证（4 步）

```bash
# ① 环境体检 —— 期望 5/5 通过
.venv\Scripts\python.exe cli.py doctor
#   期望：[PASS] SQLite WAL / [PASS] sqlite-vec v0.1.9 / [PASS] 知识库检索
#         [PASS] 工具注册表 10 个 / [PASS] 技能目录 45 个
#         [WARN] LLM 凭证未配置 → 走离线兜底（属正常，不影响功能）

# ② 启动
.venv\Scripts\python.exe run.py --no-open
#   期望：Application startup complete. / Uvicorn running on http://127.0.0.1:8801

# ③ 健康检查
curl http://127.0.0.1:8801/api/health
#   期望：{"ok":true,"service":"MiniYuxi","version":"0.4.0",
#          "storage":{"db":"SQLite","vector":"sqlite-vec v0.1.9","fts":"FTS5"},...}

# ④ 首页
curl -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8801/
#   期望：HTTP 200
```

**浏览器验收**：打开 `http://127.0.0.1:8801` → 默认账号 `default / admin / admin123` 登录 → 左侧导航（新建任务/助理/项目/专家·技能·连接器/定时任务/资料库）→ 顶部场景 Tab → 技能快捷卡片 → 输入框（`@` 引用资料库 / `/` 唤起技能 / `+` 弹出菜单）→ 底部工作空间选择 + "允许完全访问"开关。

### 6.2 桌面端验证（4 步）

```bash
# ① 确认 sidecar 存在
ls apps\desktop\src-tauri\binaries\
#   期望：miniyuxi-sidecar-x86_64-pc-windows-msvc.exe（约 67MB）

# ② 独立验证 sidecar 二进制能起（不依赖 Tauri）
MINIYUXI_PORT=8811 apps\desktop\src-tauri\binaries\miniyuxi-sidecar-x86_64-pc-windows-msvc.exe
#   另开终端验证：
curl http://127.0.0.1:8811/api/health     # 期望 HTTP 200
#   正常日志：数据库 %LOCALAPPDATA%\MiniYuxi\data\miniyuxi.db / 向量 sqlite-vec v0.1.9
#   默认账号：default / admin / admin123
#   ⚠️ 报 [Errno 10048] 端口占用 → 换端口（8080 被占），非缺陷

# ③ 桌面开发模式
cd apps\desktop && npm install && npm run dev
#   期望：先显示"等待内核就绪"过渡页（进度条 + 日志），
#        数秒后自动导航到工作台；日志出现 "内核就绪（http://127.0.0.1:<port>）"

# ④ 打包
npm run build
#   期望：产出安装包于 src-tauri/target/release/bundle/
```

### 6.3 两端一致性验证

| 检查项 | 方法 | 期望 |
|---|---|---|
| 同一内核 | 两端各查 `/api/health` 的 `version` 与 `storage` | 完全相同 |
| 同一前端 | 桌面工作台右键查看源代码 | 与 `web/index.html` 一致 |
| 数据互通 | Web 端上传文档 → 桌面端检索 | 桌面端能检索到（同一 `%LOCALAPPDATA%\MiniYuxi\data\` 或仓库 `data/`） |
| 端点覆盖 | 对比两端可访问的 `/api/*` | 集合相同（同一 `api.py`） |

> ⚠️ **数据目录差异**：源码跑 `run.py` 用仓库 `data/`；打包 sidecar 冻结后用 `%LOCALAPPDATA%\MiniYuxi\data\`。**这是刻意的**——源码开发不该污染用户安装数据。验收时注意区分。

---

## 7. 两端功能一致性保证机制

| 机制 | 说明 |
|---|---|
| **单内核** | 两端都跑同一个 `api.py` + `core/`，**无任何业务逻辑复制** |
| **单前端** | 桌面 `frontendDist` 启动后导航到同一 `web/` 目录 |
| **版本单一源** | `core/version.py` 为唯一版本号来源；`/api/health` 与 `sidecar.json` 都读它（历史教训：曾写死 `"0.2.0"`/`"0.1.0"` 导致两端报不同版本） |
| **就绪探针** | `run.py:327` `READY` 机器可读行 + `/api/health` 双保险，Rust 侧据此导航 |
| **优雅停机** | 桌面外壳退出前 `POST /api/desktop/shutdown` → `setattr(server, "should_exit", True)`，不留孤儿进程 |

---

## 8. 当前状态与后续工作

### 8.1 ✅ 已就绪

- 两端可独立运行并功能一致（已实测）
- 环境体检 5/5
- 45 个技能 + 10 个工具 + 企业级八要素模块（egress / approval / soc_audit / citation_gate / multitenant / circuit_breaker / observability / usage）
- HR/法务垂直模块（劳动争议 / 薪资 / 简历 / 人才地图 / 面试 / 社保审计）

### 8.2 🔴 运行时应补（详见五阶段文档 §5.5）

按性价比排序，前 5 项均为"小改动高收益"：

| # | 缺口 | 文件:行 | 成本 |
|---|---|---|---|
| 1 | 审批卡被当工具结果回喂，HITL 形同虚设 | `agent_loop.py:141-148` | 极小 |
| 2 | 取消不生效，用户无法中止长任务 | `agent_runtime.py:75-80` | 小 |
| 3 | `max_cost` 闸门失效（`record_cost` 无调用点） | `circuit_breaker.py:72` | 极小 |
| 4 | Agent 路径无供应商故障转移 | `agent_loop.py:101` | 中 |
| 5 | 工具 schema 全租户暴露（`allowed_toolsets` 未传） | `agent_loop.py:70` | 小 |

### 8.3 📌 架构红线（新增功能必守）

1. **内核单一可信源**——任何端都不得重写业务逻辑，只做外壳
2. **出境唯一收口**——所有外部调用必过 `egress.guard()`
3. **上下文可压、账本不可压**——compaction 不得丢弃 `soc_audit` / `approval` / `egress` 事件
4. **零 Docker / 零外部服务**——不引入需要常驻进程的中间件
5. **零 copyleft**——新依赖必过 `scripts/audit_licenses.py`
6. **安全不分端**——hardline → 审批 → 路径校验 → 审计 全在 `core/security.py`
