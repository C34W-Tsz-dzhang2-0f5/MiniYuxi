"""端到端 HTTP 冒烟（需先起服务：python -m uvicorn api:app --port 8802）。

历史问题：本文件是「模块级直接发 HTTP」的裸脚本，pytest 收集时立刻
Connection refused 127.0.0.1:8802，把整轮测试拖成 error。
现改为函数式 + 仅在 `__main__` 下执行，pytest 收集时干净跳过。

    python tests/smoke_test.py                  # 脚本跑法（需 8802 活服务）
    MINIYUXI_SMOKE_PORT=8802 python tests/smoke_test.py
"""
import os
import sys
import time

import requests

PORT = int(os.getenv("MINIYUXI_SMOKE_PORT", "8802"))
B = f"http://127.0.0.1:{PORT}"


def _headers() -> dict:
    r = requests.post(B + "/api/auth/login",
                      json={"tenant": "default", "username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def run() -> int:
    time.sleep(2)
    H = _headers()

    def call(method, path, body=None):
        return requests.request(method, B + path, headers=H, json=body).json()

    print("health            ", requests.get(B + "/api/health").json()["ok"])
    print("workbench         ", call("GET", "/api/workbench")["total"])
    a = call("POST", "/api/approvals", {"tool_name": "kb.delete", "args": {"doc_id": "x"}})
    print("approval create   ", a["id"], a["status"])
    dec = call("POST", f"/api/approvals/{a['id']}/decide", {"approve": True, "by": "me"})
    print("approval decide   ", dec["status"])
    call("POST", "/api/memory_v2/experience", {"text": "年假按工龄折算，满1年5天"})
    notes = call("GET", "/api/memory_v2/distill?top_n=3")["notes"]
    print("memory distill    ", notes[:1] if notes else "empty")
    wf = {"nodes": [{"id": "s", "type": "start"}, {"id": "a", "type": "llm", "prompt": "年假规则"}, {"id": "e", "type": "end"}],
          "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "e"}]}
    print("canvas validate   ", call("POST", "/api/canvas/validate", {"workflow": wf})["ok"])
    print("canvas run        ", call("POST", "/api/canvas/run", {"workflow": wf})["ok"])
    j = call("POST", "/api/schedules", {"name": "t", "spec": {"kind": "interval", "seconds": 3600}, "payload": {}})
    print("schedule create   ", j["id"])
    print("schedules list    ", len(call("GET", "/api/schedules")))
    print("subagent passed   ", call("POST", "/api/subagent/run", {"task": "写离职审查"})["passed"])
    sk = call("POST", "/api/evolution/propose", {"topic": "年假", "sources": ["年假按工龄折算"]})
    print("evo propose       ", sk["name"])
    print("evo review accept ", call("POST", "/api/evolution/review", sk)["accept"])
    sid = call("POST", "/api/evolution/skills", sk)["id"]
    print("evo save          ", sid)
    print("evo prune backup  ", call("POST", "/api/evolution/prune", {"skill_id": sid, "reason": "test"})["backup_id"])
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    sys.exit(run())

