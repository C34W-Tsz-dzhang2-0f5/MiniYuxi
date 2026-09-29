"""MiniYuxi × RuoYi MCP 集成端到端验证（离线 / 本地，exit 0 = 全绿）。

闭环验证 docs/mcp-integration-design-20260928.md 的改造落地：
  1. mcp_client SSE 连通 + list_tools 拉到远程工具；
  2. _meta 解析生效（risk / confirm_required → tools_registry requires_approval）；
  3. high_risk 工具经 run_tool_governed 自动挂 HITL（status=pending）；
  4. 远程 MCP 调用经 egress 出境闸门收口（默认放行 / LOCKDOWN 拒绝，降级不崩）；
  5. 审计落 egress_log（connector 类）。

DB 用临时文件隔离，不污染项目库；Adapter 为本地 mock（tools/mcp_ruoyi_adapter.py）。
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- DB 隔离：指向临时文件，避免污染项目 data/miniyuxi.db ----
import core.config as _cfg
_TMPDB = os.path.join(tempfile.gettempdir(), f"mcp_verify_{os.getpid()}.db")
_cfg.DB_PATH = _TMPDB

import core.db as db
db.init_db()
import core.connectors as connectors
connectors.init()
import core.egress as egress
egress.init()
import core.tools_registry as tr
tr.init()
import core.mcp_client as mc
import core.approval as approval
approval.init()

# ---- 启动本地 mock MCP-Adapter（SSE） ----
_adapter_file = os.path.join(ROOT, "tools", "mcp_ruoyi_adapter.py")
_spec = importlib.util.spec_from_file_location("mcp_ruoyi_adapter", _adapter_file)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)
srv, port = adapter.serve(0)
time.sleep(0.4)
ENDPOINT = f"http://127.0.0.1:{port}"


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    return bool(cond)


results = []

# ---- 插入 mcp 连接器（A3：mcp 类型已放行） ----
cid = connectors.register("ruoyi-verify", "mcp", {"transport": "sse", "endpoint": ENDPOINT})

# 1. SSE 拉到远程工具
tools = mc.discover_connector_tools()
names = {t["name"] for t in tools}
results.append(_ok("mcp.erp.create_purchase_order" in names, "SSE 连通并拉到远程 MCP 工具（含 erp.create_purchase_order）"))
results.append(_ok(len(names) >= 6, f"远程工具数量达标（{len(names)} 个）"))

# 2. _meta 解析：采购单 risk=high_risk / requires_approval=True
po = next((t for t in tools if t["name"] == "mcp.erp.create_purchase_order"), None)
results.append(_ok(po and po.get("risk") == "high_risk" and po.get("requires_approval") is True,
                   "_meta 解析生效：采购单 risk=high_risk / confirm_required=True"))

# 3. high_risk 工具经 run_tool_governed 自动挂 HITL（返回 pending）
res = tr.run_tool_governed("mcp.erp.create_purchase_order", {"order": {"sku": "X", "qty": 5}},
                           tenant_id="default", session_id="verify")
results.append(_ok(res.get("status") == "pending" and res.get("approval_id"),
                   "high_risk 工具自动挂 HITL（run_tool_governed → status=pending）"))

# 4a. 默认策略下普通工具调用经 egress 放行并执行成功
res2 = tr.run_tool_governed("mcp.hrm.get_employee", {"employee_id": "E1"},
                            tenant_id="default", session_id="verify")
res2r = res2.get("result", {})
results.append(_ok("error" not in res2r and "content" in res2r,
                   "默认策略：hrm.get_employee 经 egress 放行并调用成功（返回业务数据）"))

# 4b. LOCKDOWN 下远程 MCP 调用被 egress 拒绝（降级不崩）
os.environ["MINIYUXI_EGRESS_LOCKDOWN"] = "1"
res3 = tr.run_tool_governed("mcp.hrm.get_employee", {"employee_id": "E1"},
                            tenant_id="default", session_id="verify")
os.environ["MINIYUXI_EGRESS_LOCKDOWN"] = ""
res3r = res3.get("result", {})
results.append(_ok("error" in res3r and "出境" in res3r.get("error", ""),
                   "LOCKDOWN：远程 MCP 调用被 egress 拒绝并降级（不崩链路）"))

# 5. 审计：egress_log 有 connector 类出境记录
egress_recs = egress.list_log(dest_class="connector")
results.append(_ok(len(egress_recs) >= 1, f"egress_log 记录 connector 出境（{len(egress_recs)} 条）"))

# 6. HITL 续跑闭环（B2 防御纵深）：批准审批单 → 带 approved aid 重调 → 高危工具真正提交
def _content_text(result):
    try:
        return (result.get("content") or [{}])[0].get("text", "")
    except Exception:
        return ""

aid = res.get("approval_id")
_a = approval.get(aid)
results.append(_ok(_a and _a.get("status") == "pending", "续跑前置：审批单已建且处于 pending"))
approval.decide(aid, True, by="verify")
resume = tr.run_tool_governed("mcp.erp.create_purchase_order", {"order": {"sku": "X", "qty": 5}},
                              tenant_id="default", session_id="verify", approved_aid=aid)
results.append(_ok("error" not in resume and resume.get("status") != "pending",
                   "HITL 续跑：带 approved aid 重调不再 pending，直接执行"))
_rj = {}
try:
    _rj = json.loads(_content_text(resume.get("result", {})))
except Exception:
    pass
results.append(_ok(_rj.get("committed") is True,
                   "B2 防御纵深：续跑注入 __commit，Adapter 真正提交（committed=True，非预览）"))

# 6b. 防护：未带 approved aid 重调同一高危工具 → 重新挂 HITL（不绕过审批门）
resume2 = tr.run_tool_governed("mcp.erp.create_purchase_order", {"order": {"sku": "Y", "qty": 1}},
                               tenant_id="default", session_id="verify")
results.append(_ok(resume2.get("status") == "pending", "防护：未带 approved aid 重调仍挂 HITL（不绕过审批门）"))

# 7. B4 字段脱敏：id_card / phone / email 被遮蔽
_masked = adapter.desensitize({"id_card": "440300199001011234", "phone": "13800138000",
                               "email": "a@example.com", "name": "张三"})
results.append(_ok("****" in _masked.get("phone", "") and "***" in _masked.get("email", "")
                   and "****" in _masked.get("id_card", ""), "B4 脱敏：手机/邮箱/身份证被遮蔽"))

# 8. B1 配置驱动：RUOYI_ENDPOINTS 覆盖合并；默认含 13 个业务路径
os.environ["RUOYI_ENDPOINTS"] = json.dumps({"hrm.get_employee": ["GET", "/custom/emp/{employee_id}"]})
_ov = adapter._load_endpoints()
del os.environ["RUOYI_ENDPOINTS"]
results.append(_ok(_ov.get("hrm.get_employee") == ["GET", "/custom/emp/{employee_id}"]
                   and len(_ov) >= 13, "B1 配置驱动：RUOYI_ENDPOINTS 覆盖合并（默认 13 条路径）"))

# 9. B3 TokenVault 加密 roundtrip（仅当 cryptography 可用）
try:
    from cryptography.fernet import Fernet as _Fernet
    _fk = _Fernet.generate_key().decode()
    os.environ["RUOYI_FERNET_KEY"] = _fk
    _v = adapter.TokenVault(db_path=os.path.join(tempfile.gettempdir(), f"vault_{os.getpid()}.db"))
    _v.put("u1", "secret-ruoyi-token", ruoyi_user="admin")
    _got = _v.get("u1")
    results.append(_ok(_got == "secret-ruoyi-token", "B3 TokenVault：Fernet 加密 roundtrip（明文不出进程）"))
    _raw = open(_v._db, "rb").read()
    results.append(_ok(b"secret-ruoyi-token" not in _raw, "B3 TokenVault：明文未落库（加密存储）"))
    del os.environ["RUOYI_FERNET_KEY"]
except ImportError:
    results.append(_ok(True, "B3 TokenVault：cryptography 未装，跳过（ruoyi 模式需安装）"))

# ---- 清理 ----
try:
    db.connect().execute("DELETE FROM connectors WHERE id=?", (cid,))
    db.connect().commit()
except Exception:
    pass
srv._stop = True
try:
    srv.shutdown()
except Exception:
    pass

print("\n==== SUMMARY ====")
print(f"PASS {sum(results)} / {len(results)}")
sys.exit(0 if all(results) else 1)
