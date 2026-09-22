"""单进程内端到端验收（绕开 PowerShell 进程启动限制）。
后台线程起 uvicorn 服务，主线程用 requests 做等价 curl 验收 T1-T5。
不创建任何子进程/后台作业，仅一个 python 进程内完成。
"""
import sys, os, threading, time, json

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["PYTHONPATH"] = ROOT
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
# 安全：真实 Key 一律走环境变量或根目录 .env（已 gitignore），禁止硬编码进仓库。
# 本机跑法：set LLM_API_KEY=xxx && set DOUBAO_API_KEY=xxx && python tests/verify_agent.py
for _k in ("LLM_API_KEY", "DOUBAO_API_KEY"):
    if not os.environ.get(_k):
        print(f"[warn] 未设置 {_k}，相关能力将不可用（请用 .env 或环境变量注入）")
os.environ.setdefault("DOUBAO_BASE_URL", "https://open.feedcoopapi.com")   # 企业搜索后端（中文更准）
os.environ["MINIYUXI_PORT"] = "8802"   # 避开可能的 8801 残留
os.environ["MINIYUXI_HOST"] = "127.0.0.1"
sys.path.insert(0, ROOT)

import run  # noqa: E402
import sqlite3  # noqa: E402

def serve():
    sys.argv = ["run.py", "--no-open"]
    run.main()

threading.Thread(target=serve, daemon=True).start()

import requests  # noqa: E402
B = "http://127.0.0.1:8802"

ok = False
for i in range(80):
    try:
        r = requests.get(B + "/api/health", timeout=5)
        if r.status_code == 200:
            ok = True
            break
    except Exception:
        pass
    time.sleep(1)
print("HEALTH_OK=", ok)
if not ok:
    print("SERVICE_FAILED")
    sys.exit(1)

r = requests.post(B + "/api/auth/login", json={"tenant": "default", "username": "admin", "password": "admin123"}, timeout=20)
tok = r.json().get("token", "")
H = {"Authorization": f"Bearer {tok}"}
print("TOK_LEN=", len(tok))

m = requests.get(B + "/api/gateway/models", headers=H, timeout=20).json()
print("T1 models_count=", len(m.get("models", [])))

tl = requests.get(B + "/api/tools/list", headers=H, timeout=20).json()
print("T2 tools=", [x["name"] for x in tl.get("tools", [])])

a = requests.post(B + "/api/chat", headers=H,
                 json={"question": "现在几点，顺便帮我算 100 加 200 乘以 3 等于多少", "top_k": 2}, timeout=150).json()
print("T1(loop) mode=", a.get("mode"), "tools=", a.get("tool_calls_used"))
print("T1(loop) ans=", (a.get("answer") or "")[:160])

b = requests.post(B + "/api/chat", headers=H,
                 json={"question": "请用 web_search 工具搜索 2026年 企业级 AI Agent 平台 最新趋势", "top_k": 2}, timeout=150).json()
print("T2(search) mode=", b.get("mode"), "tools=", b.get("tool_calls_used"))
print("T2(search) ans=", (b.get("answer") or "")[:200])

c = sqlite3.connect(os.path.join(ROOT, "data", "miniyuxi.db"))
print("T3 memories_rows=", c.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
s = requests.get(B + "/api/skills/list", headers=H, timeout=20).json()
print("T6 skills_count=", len(s.get("skills", [])))
print("integrity docs=", c.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
      "chunks=", c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
print("DONE")
