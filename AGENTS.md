# AGENTS.md — MiniYuxi 代理协作说明

> 写给 agent（WorkBuddy / CodeBuddy / 同类）的"装配说明"：约束、命令、禁忌。人类读者见 `README.md`。

## 项目一句话

MiniYuxi = 企业级 Agent · 零 Docker · 数据可出本机 · 可商用。三端：桌面版（Tauri）、网页版（`web/`+`run.py`）、共用 `core/`（Python 业务单一可信源）。

## 常用命令

- 起服务（网页版）：`python run.py`（默认 8801）
- 全量质量闸门：`python scripts/verify.py`（6/6 绿）
- 版本一致性校验：`python scripts/check_version_consistency.py`
- 商用授权审计：`python scripts/audit_licenses.py --pkg tools/office-bundle --bundle <file>`
- 桌面版构建：`cd apps/desktop && npm run sidecar && npm run build`（需 WiX v3.14 在 PATH）
- 测试：组件级 `_verify_*.py` / 真实浏览器回归 `tests/_e2e_browser_skill_install.py`

## 禁忌（红线）

- 不写语义扩散的别名（见 `CONTEXT.md`）。
- 任何数据出本机必须过 `core/egress.py::guard()`。
- 不可逆动作必须走 `core/approval.py` 审批卡，禁止模型自审。
- 引入新依赖（尤其 kev 模型权重）前必跑 `scripts/audit_licenses.py`（零 copyleft 红线）。
- 绝不用 `git add -A`（避免把 `node_modules/`、密钥带上远端）；已忽略 `tools/.ruoyi_fernet_key`。
- 桌面版默认单租户；写"多租户隔离"前先确认是网页版对外部署形态。

## Agent skills

### Issue tracker

Issues and specs live as local markdown files in `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root plus `docs/adr/`. See `docs/agents/domain.md`.
