"""端到端自检：直接验证四项对标能力（多租户 / 权限 / 知识库 / Agent 编排）。

用法：python selftest.py      （会自动起一个临时 HTTP 服务做接口级验证）
"""
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

from core import agent, auth, config, db, rag  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  → {detail}" if detail else ""))


def core_tests() -> None:
    print("\n── 核心层 ──")
    db.init_db()
    check("sqlite-vec 向量扩展可用", db.vec_version().startswith("v"), db.vec_version())

    toks = rag.tokenize("年假怎么算 Annual Leave")
    check("中文 bigram 分词", "年假" in toks and "annual" in toks, f"{toks[:6]}")

    # 租户隔离
    rag.add_document("t_a", "A公司年假制度", "A公司年假：司龄满1年享5天，满3年享10天。年假需提前3个工作日申请。")
    rag.add_document("t_b", "B公司年假制度", "B公司年假：统一为7天，无需提前申请。")
    hits_a = rag.search("t_a", "年假多少天")
    hits_b = rag.search("t_b", "年假多少天")
    check("知识库检索命中", len(hits_a) > 0, f"t_a 命中 {len(hits_a)} 条")
    ok_isolate = all("B公司" not in h["text"] for h in hits_a) and all("A公司" not in h["text"] for h in hits_b)
    check("多租户数据隔离", ok_isolate, "两租户检索结果互不串数据")

    ans = rag.answer("t_a", "年假怎么算")
    check("问答链路闭环", bool(ans["answer"]) and len(ans["citations"]) > 0,
          f"mode={ans['mode']} 引用 {len(ans['citations'])} 条")

    # 权限矩阵
    p_admin = auth.Principal("t_a", "admin", "admin")
    p_view = auth.Principal("t_a", "v", "viewer")
    check("RBAC 权限矩阵", p_admin.can("kb.write") and not p_view.can("kb.write") and p_view.can("kb.read"),
          "admin 可写 / viewer 只读")

    # Token
    tok = auth.make_token({"tid": "t_a", "sub": "admin", "role": "admin"})
    body = auth.parse_token(tok)
    check("JWT 签发与校验", bool(body) and body["role"] == "admin", "HMAC-SHA256 自签")
    check("Token 防篡改", auth.parse_token(tok[:-4] + "AAAA") is None, "签名不匹配即拒绝")

    # Agent 编排
    r = agent.start("t_a", "recruit")
    res = agent.run_all(r["run_id"], auto_approve=True)
    check("Agent 招聘流程跑通 S1→S19", res["status"] == "done" and len(res.get("history", [])) == 19,
          f"status={res['status']} 步数={len(res.get('history', []))}")
    r2 = agent.start("t_a", "recruit")
    agent.step(r2["run_id"])  # S1→S2
    g = agent.step(r2["run_id"], approve=False)  # S2 闸门拒绝
    check("HITL 人工闸门可中断", g["status"] == "waiting" and g["current"] == "S2", f"{g['current']} / {g['status']}")

    # 清理测试数据
    for t in ("t_a", "t_b"):
        for d in rag.list_documents(t):
            rag.delete_document(t, d["id"])


def _free_port() -> int:
    """自动选取空闲端口，避免与本机已占用端口冲突。"""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http_tests(port: int | None = None) -> None:
    print("\n── 接口层 ──")
    port = port or _free_port()
    env = dict(os.environ, MINIYUXI_PORT=str(port), MINIYUXI_DB=str(os.path.join(BASE_DIR, "data", "selftest.db")))
    if os.path.exists(env["MINIYUXI_DB"]):
        os.remove(env["MINIYUXI_DB"])
    proc = subprocess.Popen([sys.executable, "run.py", "--no-open", "--port", str(port)],
                            cwd=BASE_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(40):
            try:
                if requests.get(f"{base}/api/health", timeout=1).ok:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            check("服务启动", False, "超时未就绪")
            return

        check("服务启动 + 健康检查", requests.get(f"{base}/api/health", timeout=5).json()["ok"], base)

        r = requests.post(f"{base}/api/auth/login", json={"tenant": "default", "username": "admin", "password": "admin123"})
        check("登录获取 Token", r.status_code == 200, f"HTTP {r.status_code}")
        tok = r.json()["token"]
        H = {"Authorization": f"Bearer {tok}"}

        check("未带 Token 被拒绝(401)", requests.get(f"{base}/api/kb/docs").status_code == 401, "匿名访问拦截")

        r = requests.post(f"{base}/api/users", json={"username": "v1", "password": "p", "role": "viewer"}, headers=H)
        check("创建 viewer 用户", r.status_code == 200, f"HTTP {r.status_code}")
        r = requests.post(f"{base}/api/auth/login", json={"tenant": "default", "username": "v1", "password": "p"})
        vtok = r.json()["token"]
        VH = {"Authorization": f"Bearer {vtok}"}

        r = requests.post(f"{base}/api/kb/docs", json={"title": "考勤制度", "text": "上班时间9:00，下班18:00。迟到30分钟以内扣50元。"}, headers=VH)
        check("越权写入被拒绝(403)", r.status_code == 403, "viewer 无 kb.write")

        r = requests.post(f"{base}/api/kb/docs", json={"title": "考勤制度", "text": "上班时间9:00，下班18:00。迟到30分钟以内扣50元。"}, headers=H)
        check("管理员入库文档", r.status_code == 200 and r.json()["n_chunks"] > 0, str(r.json()))

        r = requests.post(f"{base}/api/chat", json={"question": "迟到怎么扣款"}, headers=H)
        check("RAG 问答返回引用", r.status_code == 200 and len(r.json()["citations"]) > 0,
              f"mode={r.json().get('mode')}")

        r = requests.post(f"{base}/api/tenants", json={"id": "hr", "name": "人力资源部"}, headers=H)
        check("创建租户", r.status_code == 200, "多租户")

        r = requests.post(f"{base}/api/agent/start", json={"flow": "recruit"}, headers=H)
        run_id = r.json()["run_id"]
        r = requests.post(f"{base}/api/agent/run", json={"run_id": run_id, "approve": True}, headers=H)
        check("Agent 接口跑通 19 阶段", r.json()["status"] == "done" and len(r.json().get("history", [])) == 19,
              f"{len(r.json().get('history', []))} 步")

        r = requests.get(f"{base}/api/audit?limit=5", headers=H)
        check("审计日志留痕", r.status_code == 200 and len(r.json()) > 0, f"{len(r.json())} 条")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    print("=" * 62)
    print("  MiniYuxi 端到端自检")
    print("=" * 62)
    core_tests()
    http_tests()
    ok = sum(1 for _, s, _ in results if s)
    print("\n" + "=" * 62)
    print(f"  结果：{ok}/{len(results)} 通过" + ("　✅ 全部通过" if ok == len(results) else "　❌ 存在失败项"))
    print("=" * 62)
    sys.exit(0 if ok == len(results) else 1)
