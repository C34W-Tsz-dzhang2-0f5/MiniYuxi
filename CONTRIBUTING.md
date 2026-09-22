# 贡献指南 (Contributing)

感谢你考虑为 MiniYuxi 做贡献！本文覆盖本地环境、测试、提交规范与 PR 流程。

## 1. 环境准备（Conda + uv，与 learn-workbuddy 一致）

```bash
conda env create -f environment.yml
conda activate miniyuxi
uv sync --python "$CONDA_PREFIX/bin/python" --no-python-downloads
```

无 Conda 时也可用：`python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`。

## 2. 跑起来

```bash
cp .env.example .env        # 填入 LLM_API_KEY / EMB_API_KEY（也可留空走离线兜底）
python run.py               # http://127.0.0.1:8801
python tests/selftest.py    # 期望 20/20
```

## 3. 测试约定（提交前必过）

```bash
python tests/selftest.py                  # 端到端 20/20
python tests/test_hermes_landing.py       # 13 passed
python tests/test_perf_optimizations.py   # 5 passed
```

CI（`.github/workflows/verify.yml`）会在 push / PR 自动跑上述卡点 + 前端未定义符号扫描 + 法条闸门。

## 4. 代码规范

- **core/ 是单一可信源**：新增能力优先放进 `core/`，三端外壳只做传输，不重复业务逻辑。
- 新增工具：用 `core/tools_registry.py` 的 `@tool(requires_approval=..., toolset=...)` 装饰器注册，并在 `run_tool_governed` 路径下执行。
- 任何调用外部命令的地方必须过 `core/security.py` 的 `hardline_block` / `is_dangerous_command` / `validate_within_dir` / `validate_script`。
- 法条与本地司法口径引用前必须做效力核验（「无引用不出文」闸门）。

## 5. PR 流程

1. Fork → 新建分支（`feat/...`、`fix/...`、`docs/...`）。
2. 保持提交小而聚焦，信息用中文或英文均可，说明「为什么」。
3. 跑通第 3 节测试。
4. 开 PR，填好 `PULL_REQUEST_TEMPLATE.md` 模板，关联相关 Issue。
5. 等待 Review；请积极回应 Review 意见。

## 6. 发 Issue

- Bug → `bug_report` 模板；新功能 → `feature_request` 模板。
- 安全漏洞**请勿公开 Issue**，按 `SECURITY.md` 私信上报。

## 7. 行为准则

友善、就事论事、尊重不同意见。共建一个对 HR / 企业落地友好的开源助手。
