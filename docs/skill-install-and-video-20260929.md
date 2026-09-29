# 技能安装 / 卸载 + 视频生成 设计方案（T6 闭环 + V1）

> 来源：用户实测反馈「让 MiniYuxi 安装 skill，无法安装；让它生成视频，无法生成」→ 补全两条能力。
> 关联：`skills/SKILL_CONTRACT.md`（字段契约）· `CONTRIBUTING.md` §4（core 单一可信源）· 本报告 §审计
> 红线：不碰 `core/agent.py` / `core/db.py` / `core/rag.py` 指纹；技能正文**只作提示词注入、不执行代码**。
> 日期：2026-09-29 ｜ 版本：0.4.0 后（未发布）

---

## 结论先行

两条能力此前**根本没接线**（UI 有入口、后端无实现），故「都用不了」。本方案**新增** `core/skills_install.py`
承载技能安装/卸载逻辑，`api.py` 仅做 HTTP 传输；**新增** `video.generate` 工具，把视频能力**转发给用户自挂的
`capability=video` MCP 连接器**（MiniYuxi 不自带视频模型）。全部改动满足 CONTRIBUTING §4（逻辑在 core、外部命令过
`core.security`、工具用 `@tool` 注册），并以 **49 项自包含测试 + 真实服务 e2e** 验收。

---

## 背景与现状（已核实）

| 能力 | 反馈前现状 | 根因 |
|---|---|---|
| 安装技能 | UI「安装/管理技能」抽屉存在，点安装报错/无效 | `api.py` **无 `/api/skills/install` 端点**；无安装实现 |
| 生成视频 | 对话要求生成视频无响应 | `tools_registry` **无 `video.generate` 工具**；无视频模型/转发 |

既有基础（可复用）：
- `core/skills_catalog.py`：递归扫描 `skills/**/SKILL.md`，`list_skills()` / `load_skill()` / `inject_text()`；
  **顶层目录 mtime 缓存**（性能优化）。
- `core/connectors.py` + `core/mcp_client.py`：已支持任意 MCP 连接器的发现与调用（含 SSE）。
- `web/wb_workbench.js`：已有技能抽屉骨架与连接器管理面板。

---

## 目标

1. 技能可从 **三种来源**安装：粘贴正文 / 本地文件夹路径 / https 链接（git 仓库或 zip）；
2. 支持**嵌套技能集合仓库**（根目录无 `SKILL.md`，如 `github.com/mattpocock/skills`）；
3. 技能可**按名卸载**，且不连带误删同级技能；
4. 安装/卸载后技能列表**立即刷新**；
5. 视频生成经**用户自挂的 `capability=video` MCP 连接器**转发；未配置时给**明确接入指引**（不崩、不误导）；
6. 守红线：不碰指纹文件；外部命令/路径全过 `core.security`；逻辑归 core。

---

## 关键设计决策

### D1 · 逻辑下沉 core（CONTRIBUTING §4）
业务逻辑全部放 `core/skills_install.py`；`api.py` 端点只做「入参 → 调 core → `SkillInstallError` 转 400」。
**理由**：三端（web/desktop/cli）共用，避免各端重复实现导致行为漂移。

### D2 · staging 落 `skills/` 的**同级目录**（Windows 关键）
临时区用 `tempfile.mkdtemp(prefix="_skill_stage_", dir=<skills 的父目录>)`：
- **不在 `skills/` 内** → 半成品不会被 catalog 扫到、崩溃不残留（早期版本放 `skills/` 内，真留下过 `_install_stage_*`）；
- **与 `SKILLS_DIR` 同盘** → 终态用 `shutil.move`（**不用 `os.replace`**：Windows 跨盘会报 `WinError 17`；
  系统 TEMP 在 C:、目标在 E: 时必炸）；
- `try/finally` 兜底 `shutil.rmtree(stage, ignore_errors=True)`，异常路径也不留残留。

### D3 · 命名唯一：目录名 == frontmatter `name` == catalog 主键
- 根目录有 `SKILL.md`：显式 `name` 优先（并**回写** frontmatter）；否则取 frontmatter `name`。
- 纯嵌套集合仓库（根无 `SKILL.md`）：用**容器名**（显式 `name` 或 URL/路径基名）。
- 显式名一律过 `safe_skill_name` 白名单（`[A-Za-z0-9_.\-]`、≤64、拒绝 `..`/`/`/`\`）。
**理由**：catalog 以目录名为键、UI 以 name 选中加载，三者必须一致，否则「装上了但选不到」。

### D4 · 卸载经 catalog 解析真实子目录
`uninstall_skill(name)` 先 `skills_catalog.load_skill(name)` 拿真实 `path`，删其**父目录**；
解析失败再退回顶层目录直删。**理由**：嵌套集合仓库里技能在 `skills/<容器>/<分类>/<名>/`，
按顶层名删会误伤，按解析路径删才精准。

### D5 · 缓存失效收口
`core/skills_catalog.invalidate_cache()`：安装/卸载后调用。
**理由**：`list_skills` 用顶层目录 mtime 做缓存键，而**嵌套增删只改子目录 mtime**，顶层 mtime 不变 →
不失效就会返回过期列表（「卸了还在」「装了不显示」）。

### D6 · URL 归一
`normalize_url`：`github.com/owner/repo` 补 `https://`；GitHub/GitLab/Gitee 仓库页补 `.git`（走 clone）；
仅接受 https（http 明确拒绝）；`.zip` 走下载。**理由**：用户习惯直接贴仓库页地址，不归一就 400。

### D7 · 安全边界（全过 `core.security`）
- URL 过 `hardline_block` / `is_dangerous_command`；
- zip 逐条 `validate_within_dir(dest, stage)` 防目录穿越；且校验 `PK` 头（防下到 HTML 错误页）；
- 目标路径过 `validate_within_dir(target, SKILLS_DIR)`；
- 技能正文**只注入 system prompt（见 `core/wb_workbench.py`），永不执行**。

### D8 · 视频：不自带模型，转发 MCP 连接器
`video.generate`（`@tool`，toolset=`video`，`requires_approval=False`）：
扫描 `connectors.list_connectors()` 找 `kind=mcp & enabled & config.capability=='video'` →
连 `MCPClientSSE` → 发现视频工具（`cfg.video_tool` 或按名匹配 `video/t2v/text_to_video/生成视频`）→ 转发 `{prompt,...}`。
未配置 → 返回**接入指引**（提示添加连接器），不抛异常、不误导。
**理由**：MiniYuxi 定位零 Docker/可商用，不自带视频权重；用「连接器挂载」解耦（阿长拍板）。

---

## 文件清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `core/skills_install.py` | **新建** | `install_skill` / `uninstall_skill` / `safe_skill_name` / `name_from_frontmatter` / `set_frontmatter_name` / `has_skill_md` / `normalize_url` / `SkillInstallError` |
| `core/skills_catalog.py` | 编辑 | 新增 `invalidate_cache()` |
| `core/tools_registry.py` | 编辑 | 新增 `@tool video.generate` + `_video_generate` |
| `api.py` | 编辑（薄） | `POST /api/skills/install`（`agent.run`）· `DELETE /api/skills/{name}`（`agent.run`）· `GET /api/skills/scan`（`chat`）；`/api/skills/list` 维持 |
| `web/wb_workbench.js` | 编辑 | 技能抽屉底部「＋ 安装 / 管理技能」→ `openSkillInstall()` 三 Tab + 已装列表；连接器新增表单加 `capability` 输入 |
| `web/index.html` | 编辑 | `.skill-install` / `.si-*` / `.skill-drawer-foot` 样式 |
| `skills/SKILL_CONTRACT.md` | 新建 | `SKILL.md` 字段契约（对齐 LibreChat） |
| `tests/_verify_skill_install_and_video.py` | **新建** | 49 项自包含验证 |

---

## 接口契约

| 方法 | 路径 | 权限 | 入参 | 出参 |
|---|---|---|---|---|
| POST | `/api/skills/install` | `agent.run` | `{method: paste\|path\|url, value, name?}` | `{ok,name,path,description,count}` / 400 |
| DELETE | `/api/skills/{name}` | `agent.run` | path 参数 | `{ok,name,removed}` / 400 |
| GET | `/api/skills/scan` | `chat` | — | 扫描结果 |
| GET | `/api/skills/list` | `chat` | — | `{skills:[…]}`（含 folder 技能，字段过 `normalize_contract`） |

工具：`video.generate` · toolset `video` · 入参 `{prompt: string}`（必填）· 出参 MCP 原始结果 / `{error}`。

---

## 测试要点

自包含（不绑端口、沙箱安全），`tests/_verify_skill_install_and_video.py`：
- 纯函数：`safe_skill_name` 边界、`name_from_frontmatter`、`normalize_url` 归一/拒绝；
- 粘贴安装 → 写 `SKILL.md` → frontmatter 校验 → catalog 可见 → 卸载；
- 本地路径安装；显式 `name` 覆盖并回写 frontmatter；
- **嵌套集合仓库**：显式名（count=2 + 按名卸载不误删）；**无显式名**（回归旧版 `UnboundLocalError`）；
- **卸载后 catalog 立即刷新**（回归旧版 mtime 缓存）；
- 校验拒绝：缺 name / http / 非仓库 zip 的 https / 越界 name → 均 `SkillInstallError`；
- 视频：未配置连接器→指引、缺 prompt→error、已配置→正确转发到 `video_tool`、`video.generate` 已注册。

真实环境 e2e（`tests/_e2e_install_github_skills.py`）：打真实服务，`POST /api/skills/install`
（plain URL `github.com/mattpocock/skills`）→ **200, count=38**，38 个 `SKILL.md` 全进 `/api/skills/list`。

---

## 红线合规自检

- ✅ 不碰 `core/agent.py` / `core/db.py` / `core/rag.py`（本特性未改指纹）；
- ✅ 外部命令/路径全过 `core.security`（`hardline_block` / `is_dangerous_command` / `validate_within_dir`）；
- ✅ 逻辑在 `core/`（单一可信源），`api.py` 端点变薄；
- ✅ 工具用 `@tool` 装饰器注册（非 imperative `register`）；
- ✅ 技能正文只作提示词注入，不执行代码。

---

## 风险

- 🟡 **依赖 git**：URL 安装走 `git clone --depth 1`，主机无 git 时报错（已给友好提示；可改用「本地路径」Tab）。
- 🟡 **第三方技能内容**：装的是外部仓库的提示词，可能含不可信指令。当前**不执行代码**降低了风险，但提示词注入仍可能影响行为；建议安装前人工过一眼（本轮已对 mattpocock/skills 做过安全检查）。
- 🟡 **无显式 name 的纯嵌套仓库**：容器名取 URL/路径基名，可能与预期不符（建议 UI 提示填 name）。
- 🟢 **视频工具名匹配**：按 `video/t2v/...` 关键词猜工具名，特殊命名需在连接器 `config.video_tool` 显式指定。

---

## 验收记录

| 项 | 结果 |
|---|---|
| 自包含单测 | **49/49 PASS** |
| 契约测试 | `tests/_verify_skills_contract.py` 通过 |
| 真实服务 e2e | install 200 · count=38 · 无 staging 残留 |
| 前端符号扫描 | `tests/_scan_undef.py` 通过 |
| 全量闸门 | `python scripts/verify.py` **6/6 绿**（含本特性步骤，已接入 CI） |

---

## 补记（2026-09-29 · MSI 干净环境试装发现，已修）

设计初版只覆盖了「源码 / 网页环境」的行为。把 MSI 抽出来在干净目录试装后，暴露 2 个
**打包 / 装机专属**的缺陷——二者在源码环境 100% 正常，只在冻结 / 装机态发作。

### D9 · 冻结态技能目录必须持久化（否则「重启就丢」）

**问题**：`SKILLS_DIR` 原为 `<core 的父目录>/skills`。PyInstaller `--onefile` 下 `__file__` 落在
临时解压目录 `_MEIPASS`（`%TEMP%\_MEIxxxxxx`），**进程退出即删除** → 装进去的技能下次启动就没了。

**实测证据**：
```
POST /api/skills/install → path = C:\Users\ADMINI~1\AppData\Local\Temp\_MEI000019002\skills\clean-verify-demo
重启后 GET /api/skills/list → count=83（内置），has clean-verify-demo? False
```

**决策**：与 `MINIYUXI_DATA_DIR` 同构——新增 `MINIYUXI_SKILLS_DIR` 覆盖；
`run.py::_frozen_bootstrap()`（**必须在 `import core` 之前**）指向 `<数据目录同级>/skills`，
首次启动从内置 `_MEIPASS/skills` **播种一次**（已存在则不动，保住用户自装技能）。

**为何放数据目录同级而非 `data/` 内**：避免 83 个内置技能目录灌进 `daily_backup` 的 data 快照。
**注意**：技能段落必须写在 `if os.getenv("MINIYUXI_DATA_DIR"): return` **之外**，
否则外部预设数据目录时（测试 / 企业 IT 指盘）技能目录不会被设置。

### D10 · 打包态 sidecar 名：`externalBin` 的路径 ≠ 运行期相对路径

**问题**：`tauri.conf.json` 的 `externalBin: ["binaries/miniyuxi-sidecar"]` 是**构建期源路径**；
打包器只保留**文件名**放到主 exe 同目录（MSI File 表确证：`<Directory Id="INSTALLDIR">` 下
`Name="miniyuxi-sidecar.exe"`，**无 `binaries` 子目录**）。
而 `tauri-plugin-shell::relative_command_path()` 做的是 `exe_dir.join(name)`，
旧代码 `.sidecar("binaries/miniyuxi-sidecar")` 会去找 `<INSTALLDIR>/binaries/...` → **干净装机必失败**。

**决策**：`lib.rs` 改为候选名按序尝试：`["miniyuxi-sidecar", "binaries/miniyuxi-sidecar"]`，
裸名（安装器实际落盘位置）优先，旧 `binaries\` 手工布局兜底。

**副作用说明**：装机目录 `binaries\` 下的三份 sidecar 是**手工补的**，非安装器产物；
修复后不再依赖它，但保留兜底以免旧装机机器失效。

**验证手法（无需真装机器）**：WiX `dark.exe -x <抽出目录> -o dump.wxs <msi>` 反编译看 File 表，
再用抽出的 payload 在隔离 `MINIYUXI_DATA_DIR` 下独立运行 sidecar 打 `/api/health`。

---

## 补记 2（2026-09-29 · 对话内「装技能」闭环 + 集合仓库选择，已修）

阿长反馈：**「对话框输入指令还是无法安装 skill」**（截图：输入
`npx skills add https://github.com/vercel-labs/skills --skill find-skills`，模型只把命令解释了一遍）。

### 根因分层

| 层 | 问题 | 处理 |
|---|---|---|
| ① 能力缺失 | 技能安装只有「UI 抽屉」和 HTTP 接口两条入口，**没有注册成工具** → Agent Loop 工具清单里没有对应能力，模型只能解释 | 新增 `skill.install` / `skill.uninstall` / `skill.list` 三个工具 |
| ② 提示缺失 | 系统提示没告诉模型「装技能要调工具、而不是解释命令」 | `_agent_system` 第 6 条 + 工具描述里的强制指令 |
| ③ 命令形态 | `npx skills add <url> --skill <名>` 是**机器语法**，不该让 LLM 猜 | `_detect_tool` 加确定性快路径（在知识库闸门**之前**） |

### D11 · `install_skill(skills_dir=X)` 却拿默认目录校验 → 误报 frontmatter 错并回滚

**问题**：`core/skills_catalog` 的扫描函数原先**只认模块级 `SKILLS_DIR`**，
而 `install_skill` 接受 `skills_dir=` 参数。于是「装到 X、却拿默认目录去校验」→
`installed` 恒为空 → 抛 `SkillInstallError("SKILL.md 缺少合法 frontmatter")`
**并把刚装好的技能 `rmtree` 掉**。

**实测证据**（`vercel-labs/skills` 克隆体，38 个技能）：
```
install_skill("path", <clone>, "mattpocock-skills", skills_dir=tmp)
  → SkillInstallError: SKILL.md 缺少合法 frontmatter（需 name + description）
  → tmp/ 里只剩被回滚的空目录
同一份代码改用环境变量隔离（catalog.SKILLS_DIR == tmp）→ ok=True, count=38
```

**决策**：`_scan_with_skips` / `list_skills` / `scan_skills` / `load_skill` 全部加
`skills_dir=None` 参数；缓存键从 `mtime` 改为 `(目录绝对路径, mtime)`，允许对不同目录各缓存一份。
`install_skill` / `uninstall_skill` 一律用**自己的 `SKILLS_DIR`** 去校验/解析。

**顺带修的隐藏坑**：原校验用 `path.startswith(target_abs + os.sep)`。
`SKILLS_DIR` 来自环境变量时是正斜杠、`glob` 返回的是反斜杠 → 在 Windows 上会误判「不在树内」。
改用 `_same_tree()`（`normcase(abspath())` 双规范化后比较）。

### D12 · 只读文件让 `rmtree` 静默留残留（卸载删不干净）

**问题**：`git clone` 会把 `.git/objects/pack/*.pack|.idx` 标成只读（`-r--r--r--`）。
Windows 上 `os.unlink` 直接 `PermissionError`；而旧代码用的是
`shutil.rmtree(target, ignore_errors=True)` → **静默**留下半截目录。

**实测证据**：
```
uninstall 后残留: <skills>/find-skills/.git/objects/pack/{pack,idx,rev}（共 7 个条目）
只读位探测: -r--r--r--  pack-20d176b6….pack
裸 rmtree: PermissionError（残留=True）; 清只读位后 rmtree: 残留=False
```

**决策**：
- 新增 `_rmtree()`：**先裸删，失败再 `_clear_readonly()` 重试，最后才 `ignore_errors` 兜底**
  （正常路径零额外开销，不做预扫描）。所有删除点（回滚 / 卸载 / staging 清理）统一走它。
- staging 阶段**丢弃 `.git` / `__pycache__` / `*.pyc`**（`_STAGE_IGNORE`）：
  技能只需要正文，版本库既没用又是删除失败的根源。`path` 走 copytree 的 ignore，
  `url` clone 后在 stage 里补一次 `_rmtree(stage/.git)`。

> ⚠️ **别用 `onexc=` / `onerror=` 版本的 rmtree**：实测在 Windows 上「吞错」模式会让
> rmtree 退化到 ~0.4s/文件（198 文件 71s），而「先裸删、失败再清位」只要 ~1s。
> 本沙箱里连**成功**的删除也是 ~0.2s/文件（C: / E: 都如此）——那是沙箱文件系统过滤器的特性，
> 不是代码问题；在真机上是毫秒级。写测试时**别用大仓库做夹具**，用 2~3 个技能的小夹具。

### D13 · `--skill <名>` 的语义：从集合仓库里**挑一个**，而不是容器名

**问题**：旧实现把 `--skill` 的值当 `name`（容器目录名）→
`npx skills add <仓库> --skill find-skills` 会**把整个仓库 38 个技能装进一个叫 `find-skills` 的容器**。
而且 `vercel-labs/skills` 里**根本没有** `find-skills` 这个技能（该仓库实为 `mattpocock-skills`，
`package.json` 可证），旧实现会「静默装错东西还报成功」。

**决策**：
- 新增独立参数 **`select`**（HTTP 层 `SkillInstallIn.select`，工具层 `skill.install.select`），
  `--skill <名>` 映射到它，语义 = **只装集合仓库里的这一个**：
  命中 → 把该子目录**平铺**装到 `SKILLS_DIR/<名>/`；未命中 → **明确报错并列出可用技能**（绝不静默整装）。
- **`name` 语义保持不变**（容器名 / 单技能仓库的技能名覆盖），确保向后兼容：
  现有 `install_skill("path", src, "mattpocock-skills")`、`("...", "coll")` 等调用与测试不受影响。
- 附带好处：`name` 若恰好等于某个子技能名，也会自动走「只装那一个」——符合直觉且不破坏上述用例。

### 本轮验收

| 项 | 结果 |
|---|---|
| 新增自包含测试 | `tests/_verify_skill_tools.py` **65/65 PASS**（含 D11/D12/D13 回归） |
| 既有技能测试 | `tests/_verify_skill_install_and_video.py` **49/49 PASS**（向后兼容未破） |
| 真实命令行形态 | `npx skills add <本地集合仓库> --skill tdd` 经 `rag.answer` 端到端装到磁盘，且**只装那一个** |
| e2e 清场 | `_e2e_install_github_skills.py` 补第 6 步：验完自动 `DELETE`，不在真实 `skills/` 留痕 |

### 尚未闭环

- 🔴 **装机版（MSI）不含本轮改动**：`C:\Program Files\MiniYuxi\` 里仍是 0.4.0 旧包，
  对话里装技能要在**网页版**验证；装机版需重出 MSI（见 MEMORY 的 WiX 说明）。
- 🟡 `vercel-labs/skills` 与 `mattpocock/skills` 是同一个仓库（前者为组织名下的镜像/转移），
  文档与提示词里不要再把 `find-skills` 当成该仓库的技能名举例。
