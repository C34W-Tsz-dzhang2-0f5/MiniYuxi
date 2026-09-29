"""验证 ④ 可观测性：trace_id 贯穿 + span 落库 + 指标导出。离线可跑，不依赖 LLM。

跑法：python tests/_verify_observability.py
"""
import os
import sys
import time
import tempfile
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import observability  # noqa: E402

FAIL = []


def check(cond, msg):
    if cond:
        print("[PASS]", msg)
    else:
        print("[FAIL]", msg)
        FAIL.append(msg)


tmp = tempfile.mkdtemp()
conn = sqlite3.connect(os.path.join(tmp, "obs_test.db"))

tid = observability.start_trace("test-trace-123")
check(observability.current_trace_id() == "test-trace-123", "start_trace 设置 trace_id")

with observability.span("llm", kind="llm", conn=conn) as sp:
    sp.set_tokens(120)
    time.sleep(0.005)
with observability.span("tool:kb.search", kind="tool", conn=conn) as sp2:
    sp2.set_status("ok")
    time.sleep(0.005)

rows = conn.execute("SELECT trace_id, span_name, duration_ms, tokens FROM traces ORDER BY id").fetchall()
check(len(rows) == 2, "两条 span 已落库")
check(all(r[0] == "test-trace-123" for r in rows), "两条 span 共享同一 trace_id（贯穿 retrieval→tool）")
check(rows[0][1] == "llm" and rows[1][1] == "tool:kb.search", "span 名称正确")
check(all((r[2] or 0) >= 0 for r in rows), "duration_ms 已记录")
check(rows[0][3] == 120, "token 已记录到 span")

m = observability.get_metrics(conn=conn)
check(m["total_spans"] == 2, "get_metrics total_spans=2")
check(m["success_rate"] == 1.0, "get_metrics success_rate=1.0")
check("llm" in m["by_span"] and "tool:kb.search" in m["by_span"], "get_metrics by_span 聚合")
check(m["avg_latency_ms"] is not None and m["avg_latency_ms"] >= 0, "get_metrics avg_latency_ms 有值")

conn.close()
if FAIL:
    print("OBSERVABILITY VERIFY FAILED:", len(FAIL))
    sys.exit(1)
print("OBSERVABILITY VERIFY ALL PASS")
