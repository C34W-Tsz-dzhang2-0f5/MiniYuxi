# Hermes 原则落地 MiniYuxi：方案与实施记录

> 知识库来源：微信公众号「Jerry聊AI」《Hermes 源码解读》12 篇（已入库 `E:\HR有关AI\知识库\hermes源码解读系列\`）
> 归纳文档：`E:\HR有关AI\知识库\hermes源码解读系列\归纳.md`
> 本文档：落地方案 + 代码改动 + 验证结果 + 未实施方案
> 日期：2026-09-22

---

## 📌 结论先行

按「价值高 × 安全可实装」筛选，本次**彻底落地三块**（加层/接线式，不翻转运行基线）：

- **B-1 工具治理**：`toolset` 过滤 + `run_tool_governed` 审批门（对应原则③）
- **B-4 Cron=Agent 任务**：`run.py _run_job` 通用化（agent/script/fail-closed）（对应原则⑩）
- **B-5 安全分层**：`security.py` hardline block + `validate_within_dir` + `validate_script`（对应原则⑪）

验证：**13 个回归测试全过**（`$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pytest tests/test_hermes_landing.py -q` → `13 passed in 3.11s`）；4 个改动文件 `py_compile` 全过。

下列三块因**重写核心调用链 / 改变模型行为**，列入具体可行方案但**本次不实施**：B-2 审批 resume 续跑、B-3 Prompt 三层重构、B-6 多平台网关归一。

---

## 一、落地总览表

| 模块 | 对应原则 | 改动文件 | 是否本次实装 | 验证 |
|---|---|---|---|---|
| B-1 工具治理 | ③ | `core/tools_registry.py`、`core/security.py`、`core/agent_loop.py` | ✅ 实装 | 测试覆盖 |
| B-4 Cron=Agent 任务 | ⑩ | `run.py` | ✅ 实装 | 测试覆盖 |
| B-5 安全分层 | ⑪ | `core/security.py` | ✅ 实装 | 测试覆盖 |
| B-2 审批 resume 续跑 | ②⑪ | `core/approval.py`、`core/agent_loop.py` | ❌ 列方案 | — |
| B-3 Prompt 三层重构 | ④ | `core/agent_loop.py`、`core/prompt_builder`（待建） | ❌ 列方案（后半段已顺手做） | — |
| B-6 多平台网关归一 | ⑥ | 新增 `core/gateway/`（待建） | ❌ 列方案 | — |

---

## 二、已落地（本次实装）

### B-1 工具治理（原则③）：注册 → 治理

**改动 1 · `core/tools_registry.py`**
- `tool(name, description, schema=None, toolset="builtin", requires_approval=False)` 装饰器新增 `toolset` 与 `requires_approval` 参数，写入 `_REGISTRY` 条目元信息。
- `call_tool` 内新增**执行前 hardline 兜底**：遍历 args 字符串值，命中 `security.hardline_block` 直接拒绝（双保险，不依赖调用方）。
- 新增 `run_tool_governed(name, args=None, tenant_id=None, session_id=None)`，执行顺序：
  1. 未知工具 → 返回安全兜底（不静默执行未知能力）；
  2. 参数 hardline 兜底（遍历 args 字符串值查 `hardline_block`）；
  3. **审批门**：`spec.get("requires_approval") or approval.needs_approval(name)` → 调 `approval.create(...)` 返回 `{status:"pending", approval_id, tool_name}`，**不执行**；
  4. 否则等价于 `call_tool`（对未标记 `requires_approval` 的内置工具行为完全不变，向后兼容）。

**改动 2 · `core/agent_loop.py`**
- `_to_openai_tools(allowed_toolsets=None)`：新增 toolset 过滤。`allowed_toolsets=None` → 全量暴露（向后兼容）；否则仅暴露 `toolset in allowed_toolsets` 的工具（对应 Hermes 按入口/子 Agent 收窄能力，工具 schema 占上下文，越少每轮越轻）。
- 长期记忆注入由 `role:"system"` 改为拼入 **user message 末尾段**（修复「双 system」隐患 + 顺原则④「临时/可变上下文注入 user message」护 prompt cache）。

**改动 3 · `core/security.py`**
- 提供 `hardline_block(cmd)` 供工具执行前兜底（见 B-5）。

> 设计取舍：Hermes 的 `tool_search` 渐进式披露、check_fn 30s TTL＋抖动容错、并发结果按原序写回，本次**未照搬**——MiniYuxi 工具集规模尚小、自注册＋MCP 已够，渐进披露属「工具多到超阈值」才需要；但 toolset 过滤 + 审批门这条治理主干已就位，后续工具膨胀可直接接 `tool_search`。

### B-4 Cron=Agent 任务（原则⑩）：Trigger/Execution/Delivery 拆分

**改动 · `run.py` `_run_job(payload)` 通用化**
- 旧式 `action`（`labor_sync` / `daily_backup`）向后兼容。
- 新增 `kind:"agent"`：用 `rag.answer("default", prompt, history=None)` 跑一个 **fresh session**（对应 Hermes「每个 cron job = fresh session，prompt 必须自包含」），可选 `deliver:"log"` 写 `data/cron_agent_runs.log`。
- 新增 `kind:"script"`：`security.validate_within_dir(script_path, allowed_root=BASE_DIR/scripts)` 限 `scripts/` 根目录 + `security.validate_script(open(...).read())` 安全校验后 `subprocess.run([sys.executable, script_path], cwd=BASE_DIR, timeout=300)`。
- **未知 kind → fail-closed**：记审计日志，不静默跳过、也不盲执行（对应 Hermes「定时 Agent 任务必须比即时对话更保守」）。

> 设计取舍：Hermes 的 `no_agent` 模式（脚本即任务、stdout 直投不经 LLM）本次未单列，但 `kind:"script"` 已等价于「不经 Agent 的固定检查」，且 `kind:"agent"` 已覆盖「采集+判断」；`skills canonicalization` / `prompt threat scan` 在 Cron 创建侧（API/前端）待补，执行侧已做路径与脚本安全校验。

### B-5 安全分层（原则⑪）：动手之前先有边界

**改动 · `core/security.py` 新增执行层安全**
- `_COMMAND_BLOCKLIST`（正则）：`rm -rf /`、`rm -rf --no-preserve-root`、`mkfs`、裸设备 `/dev/sd[a-z]`、`shutdown|reboot|halt|poweroff`、`fork bomb`（`(){:|:&};:`）、`dd if=/dev/(zero|random|urandom)`、`chmod|chown -R 777|0`。
- `hardline_block(cmd: str) -> bool`：**不可恢复命令，无条件拦截**（在 yolo/审批之前，对应 Hermes hardline 第一层）。
- `_DANGEROUS_PATTERNS`：`rm -rf`（非根）、`sudo`、重定向到 `/dev/sd*`、`curl|wget ... | sh`、写 `/etc/(passwd|shadow|hosts)`。
- `is_dangerous_command(cmd: str) -> bool`：**可恢复但有风险，应走审批**（对应 Hermes「可恢复→审批」）。
- `validate_within_dir(path: str, root: str) -> bool`：防 `../../` 穿越 / 绝对路径 / symlink，用 `os.path.commonpath` 解析后比对允许根目录（对应 Hermes `path_security.validate_within_dir` 防 `../../.ssh/id_rsa`、`~/.env`、`/etc/passwd`）。
- `_SENSITIVE_PATH_HINTS`：`c:\windows`、`/etc/passwd`、`/etc/shadow`、`/boot`、`/sys/`、`/proc/`、`/root/`、`id_rsa`、`.env`、`config.yaml`。
- `validate_script(script: str) -> tuple[bool, str]`：(ok, reason)——hardline 命中→拒；敏感路径→拒。供 B-4 `kind:"script"` 与未来 shell 工具复用。

> 设计取舍：Hermes 的 sandbox 后端（docker/ssh/modal/daytona）、网络出口隔离（egress allowlist proxy）、tool guardrail（同命令失败 5 次喂 synthetic result）、Gateway 异步审批队列，本次**未照搬**——MiniYuxi 当前 local 执行、无多平台后台线程，sandbox/网络隔离属部署层改造；guardrail 可与 `approval.needs_approval` 后续合并。安全分层「hardline→审批→path 校验→audit」主干已就位。

---

## 三、验证结果

| 项 | 命令 | 结果 |
|---|---|---|
| 编译 | `python -m py_compile core/security.py core/tools_registry.py core/agent_loop.py run.py tests/test_hermes_landing.py` | ✅ compile OK |
| 回归 | 隔离 venv `pytest tests/test_hermes_landing.py -q` | ✅ **13 passed in 3.11s** |

**测试覆盖点（`tests/test_hermes_landing.py`，13 用例）**
- B-5：`hardline_block`（`rm -rf /` 拦截、普通命令放行）、`is_dangerous_command`、`validate_within_dir`（越权返回 False）、`validate_script`（hardline→拒、敏感路径→拒）。
- B-1：`agent_loop._to_openai_tools` 的 toolset 过滤（注册 `_demo_admin_tool` toolset=admin 验证真生效）；`run_tool_governed` 审批门挂起（返回 pending）、安全拦截（hardline 拒绝）、普通执行（等价于 call_tool）。
- B-4：`_run_job` 的 agent fresh session（monkeypatch 隔离 `rag.answer`）、未知 kind fail-closed（记日志不盲执行）、脚本路径越权拦截（monkeypatch 隔离 `BASE_DIR`）。

---

## 四、待实施（具体可行方案，本次未做）

### B-2 审批 resume 续跑（原则②⑪）
- **具体方案**：在 `core/approval.py` 增加「审批完成 → 唤醒挂起工具循环」机制。当前 `run_tool_governed` 返回 `{status:"pending", approval_id}`，需在 `approval.create` 落库后由审批通过事件回调/轮询，把原 tool name+args 重新喂回 `call_tool` 执行，并把结果写回原会话 messages（对应 Hermes「审批结果必须能从用户平台回到正在执行的 Agent 线程」）。Gateway 场景需异步队列（线程阻塞等 `/approve`/`/deny`，带 timeout 与队列清理），CLI 场景可直接问用户。
- **本次未实施理由**：需重写工具执行-审批的耦合方式，且 MiniYuxi 当前会话为同步 SSE 流式，审批「挂起-续跑」会牵动 `agent_loop.run()` 的主循环与前端事件协议；属核心调用链改动，独立排期更安全。

### B-3 Prompt 三层重构（原则④）
- **具体方案**：在 `core/agent_loop.py` 或新建 `core/prompt_builder.py` 把 system prompt 拆 `stable`（SOUL/工具规则/skills 索引/环境提示，字节稳定护缓存前缀）→ `context`（用户 system_message/项目上下文，按优先级 first match wins）→ `volatile`（MEMORY/USER profile/外部 snapshot/日期，做快照）；session 内 system prompt 不重建（仅压缩事件触发）；外部 recall/plugin 上下文注入 user message 不写 system prompt；项目上下文当不可信输入做扫描/截断/frontmatter 处理。
- **本次未实施理由**：重构 system prompt 组装链会改变模型每轮收到的前缀，影响所有对话行为，需全量回归 + 成本对比（prompt cache 命中率）。**本次已顺手完成后半段**：长期记忆注入改为拼入 user message 末尾（不再写 system），已护住缓存边界。
- MiniYuxi 当前已有「法条闸门」「SOC 审计」等强约束，重构时须保证这些硬规则仍在 stable 层不被临时上下文冲掉。

### B-6 多平台网关归一（原则⑥）
- **具体方案**：新增 `core/gateway/`：①`MessageEvent`（text/attachments/source/reply anchor 归一）；②`SessionSource` + `build_session_key()`（平台:聊天:线程:参与者，控制隔离/复用粒度）；③两层 running guard（adapter 层 pending queue＋interrupt event；GatewayRunner 层 `_running_agents`＋`/stop /approve /deny /queue /status`）；④授权在入口先判断（allow-all→allowlist→DM pairing→默认拒绝）；⑤`Delivery` 抽象（对话上下文≠投递目标，Cron 结果不混进会话历史）。
- **本次未实施理由**：MiniYuxi 当前入口为 FastAPI＋SSE 流式＋企微 webhook（单入口），多平台归一需新增一整层适配层，且会改变「入口→AIAgent」的接线方式；属架构新增而非加层。当前企微入口已通过 webhook 接入，多平台（Telegram/Discord/邮件）优先级低，列第 4 阶段路线。

---

## 五、风险分级

| 落地项 | 价值 | 改动范围 | 风险 | 敞口/备注 |
|---|---|---|---|---|
| B-1 工具治理 | 🔴 高 | 加层式（registry/agent_loop） | 🟡 中 | 审批门对未标记工具无感，需逐步标记 `requires_approval`；后续可接 `tool_search` |
| B-4 Cron=Agent 任务 | 🔴 高 | 通用化 `run.py` | 🟡 中 | 未知 kind fail-closed 已兜底；Cron 创建侧 threat scan 待补 |
| B-5 安全分层 | 🔴 高 | 加层式 `security.py` | 🟡 中 | hardline 正则需随新危险模式迭代；sandbox/网络隔离属部署层待补 |
| B-2 审批续跑 | 🟡 中 | 核心调用链 | 🔴 高 | 牵动主循环+前端事件协议，独立排期 |
| B-3 Prompt 重构 | 🟡 中 | 核心 prompt 链 | 🔴 高 | 改变模型每轮前缀，需全量回归+成本对比 |
| B-6 多平台网关 | 🟡 中 | 新增适配层 | 🔴 高 | 当前单入口，多平台优先级低，列第 4 阶段 |

> 图例：🔴 高｜🟡 中｜🟢 低。安全分层「hardline→审批→path 校验→audit」主干已就位，yolo 不是底线绕过券。

---

## 六、后续建议

1. **提交本次改动**：4 文件（`core/agent_loop.py`、`core/security.py`、`core/tools_registry.py`、`run.py`）+ 测试 `tests/test_hermes_landing.py`（注：`.gitignore` 第 49 行 `test_*.py` 默认忽略测试文件，如需入库可 `git add -f`）。
2. **逐步标记审批工具**：把高危内置工具（shell/文件删除/网络）在 `tool()` 注册时置 `requires_approval=True`，让 B-1 审批门真正生效。
3. **排期 B-2/B-3/B-6**：建议顺序 B-3（Prompt 重构，收益含成本下降）→ B-2（审批续跑，体验闭环）→ B-6（多平台，扩张期）。
4. **TypeSafe 技能可用性**：已按用户要求在 user-level 安装 `typesafe-ai` 技能（审计结论 P2 安全，仅 SKILL.md+LICENSE，零脚本零 hook）。本次落地为 Python 运行时改动，未直接触发该技能；后续迭代（如给工具 args 加 typed guard、给 `run_tool_governed` 加类型化返回）可调用 TypeSafe 提升类型安全。
5. **知识库联动**：12 篇文章已落库并归纳（`归纳.md`），MiniYuxi 的 Skill（`skills/` 扫描）可在「Agent 架构治理」类任务中引用本归纳作为 SOP。
