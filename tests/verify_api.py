"""MiniYuxi 多模型中枢 · 接口级验证（需服务在 8801 运行）。

登录 default/admin/admin123 → 依次验证 catalog / route / chat(自动) / compare(merge) / tasks。
"""
import requests

BASE = "http://127.0.0.1:8801"


def login():
    r = requests.post(BASE + "/api/auth/login",
                      json={"tenant": "default", "username": "admin", "password": "admin123"}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def main():
    tok = login()
    h = {"Authorization": "Bearer " + tok}
    G = lambda p: requests.get(BASE + p, headers=h, timeout=30)
    P = lambda p, b: requests.post(BASE + p, headers=h, json=b, timeout=90)

    c = G("/api/models/catalog").json()
    print("CATALOG providers=%d models=%d default=%s" % (len(c["providers"]), len(c["models"]), c["default_model"]))
    avail = [m["id"] for m in c["models"] if m["available"]]
    print("AVAILABLE(%d): %s" % (len(avail), avail[:6]))

    rt = P("/api/models/route", {"message": "帮我用 python 写一个列表去重函数", "strategy": "balanced"}).json()
    print("ROUTE type=%s model=%s | %s" % (rt["task_type"], rt["model_id"], rt.get("reason", "")[:50]))

    ch = P("/api/models/chat", {"message": "用一句话解释什么是最低工资标准", "strategy": "balanced"}).json()
    print("CHAT ok=%s model=%s cost=%s text=%s" % (ch.get("ok"), ch.get("model_name"), ch.get("cost"), (ch.get("text") or "")[:50]))

    if len(avail) >= 2:
        cmp = P("/api/models/compare", {"message": "深圳法定年假最少几天", "model_ids": avail[:2], "merge": True}).json()
        print("COMPARE results=%d merged=%s cost=%s" % (len(cmp.get("results", [])), bool(cmp.get("merged")), cmp.get("total_cost")))
        for r in cmp.get("results", []):
            print("   - %s ok=%s %dms" % (r.get("model_name"), r.get("ok"), r.get("latency_ms", 0)))
        if cmp.get("merged"):
            print("   MERGED(%s): %s" % (cmp["merged"].get("judge"), (cmp["merged"].get("text") or "")[:80]))
    else:
        print("COMPARE skipped: available<2")

    ts = G("/api/models/tasks").json()
    print("TASKS total=%d ok=%d cost=%s avg_lat=%dms" % (ts["stats"]["total"], ts["stats"]["ok"], ts["stats"]["cost"], ts["stats"]["avg_latency"]))
    print("API_VERIFY_DONE")


if __name__ == "__main__":
    main()
