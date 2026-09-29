# -*- coding: utf-8 -*-
"""数据出境管控 · API 层验证（起真实服务 + 真实 HTTP）。

自包含：脚本自己拉起 run.py（独立端口 + 独立临时库），跑完 API 检查后关掉服务。
用独立端口和独立 MINIYUXI_DB，不碰正在运行的实例与真实库。

用法：.venv/Scripts/python.exe tests/_verify_egress_api.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {extra}" if extra and not cond else ""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, url, token="", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp(prefix="mx-egress-api-")
    env = dict(os.environ)
    env["MINIYUXI_DATA_DIR"] = tmp
    env["MINIYUXI_DB"] = os.path.join(tmp, "api.db")
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("MINIYUXI_EGRESS_LLM", "MINIYUXI_EGRESS_EMBEDDING", "MINIYUXI_EGRESS_SEARCH",
              "MINIYUXI_EGRESS_EXTERNAL_RAG", "MINIYUXI_EGRESS_CONNECTOR",
              "MINIYUXI_EGRESS_LOCKDOWN", "LLM_API_KEY"):
        env.pop(k, None)

    # 装 exe 时走冻结内核（行为级证明），否则跑源码。
    #   MX_SIDECAR_EXE="C:\Program Files\MiniYuxi\binaries\miniyuxi-sidecar.exe"
    exe = os.environ.get("MX_SIDECAR_EXE", "").strip()
    if exe:
        cmd = [exe, "--sidecar", "--port", str(port)]
        label = f"装机版 sidecar {os.path.basename(exe)}"
    else:
        cmd = [PY, os.path.join(ROOT, "run.py"), "--port", str(port), "--no-open"]
        label = "源码 run.py"
    logfile = os.path.join(tmp, "sidecar.log")
    print(f"[启动] {label} --port {port}")
    print(f"       库: {env['MINIYUXI_DB']}")
    # ⚠️ stdout 写文件而非 PIPE：PIPE 不读会填满缓冲区把子进程卡死
    lf = open(logfile, "wb")
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(120):
            if proc.poll() is not None:
                break
            try:
                st, js = http("GET", f"{base}/api/health", timeout=2)
                if st == 200 and js.get("ok"):
                    ok = True
                    break
            except Exception:
                time.sleep(0.5)
        if not ok:
            lf.flush()
            try:
                out = open(logfile, "rb").read()
            except Exception:
                out = b""
            print("服务未能启动：\n" + out.decode("utf-8", "ignore")[-2000:])
            return 2

        print("\n[API] 健康检查与登录")
        st, js = http("GET", f"{base}/api/health")
        check("health 200", st == 200 and js.get("ok") is True, str(js)[:200])
        # 版本号：与 core/version.py 的唯一来源一致（装机版据此确认打的是新版）
        sys.path.insert(0, ROOT)
        from core.version import __version__ as SRC_VER  # noqa: E402
        check(f"health 报版本 {SRC_VER}", js.get("version") == SRC_VER,
              f"got={js.get('version')!r} want={SRC_VER!r}")
        st, js = http("POST", f"{base}/api/auth/login",
                      body={"tenant": "default", "username": "admin", "password": "admin123"})
        tok = js.get("token", "")
        check("登录拿到 token", st == 200 and bool(tok), str(js)[:200])

        print("\n[API] 出境点自描述 /api/egress/inventory")
        st, js = http("GET", f"{base}/api/egress/inventory", token=tok)
        check("inventory 200", st == 200, str(js)[:200])
        check("覆盖 5 类目的地", len(js.get("classes", [])) == 5, str(len(js.get("classes", []))))
        names = {c["class"] for c in js.get("classes", [])}
        check("类别正确", names == {"llm", "embedding", "search", "external_rag", "connector"}, str(names))
        check("每类带收口点", all(c.get("sites") for c in js.get("classes", [])))
        check("暴露 3 档预设", set(js.get("presets", {})) == {"balanced", "strict", "lockdown"})
        check("默认非 lockdown", js.get("lockdown") is False, str(js.get("lockdown")))

        print("\n[API] 策略读 /api/egress/policy")
        st, js = http("GET", f"{base}/api/egress/policy", token=tok)
        check("policy 200", st == 200 and "policy" in js, str(js)[:200])
        check("默认 llm=allow", js["policy"]["classes"]["llm"]["default"] == "allow", str(js["policy"]["classes"]["llm"]))

        print("\n[API] 试分级 /api/egress/classify（无副作用）")
        st, js = http("POST", f"{base}/api/egress/classify", token=tok,
                      body={"text": "张三 2026年9月工资 18500 元，身份证 440301199001011234", "dest_class": "llm"})
        check("判为 confidential", js.get("level") == "confidential", str(js)[:200])
        check("脱敏预览无身份证号", "440301199001011234" not in (js.get("redacted_preview") or ""), str(js.get("redacted_preview")))
        check("balanced 下 would_allow=True", js.get("would_allow") is True, str(js)[:200])
        st, js2 = http("POST", f"{base}/api/egress/classify", token=tok,
                       body={"text": "公司的年假怎么算", "dest_class": "llm"})
        check("普通问题判 internal", js2.get("level") == "internal", str(js2)[:200])

        print("\n[API] 套用预设 /api/egress/preset")
        st, js = http("POST", f"{base}/api/egress/preset", token=tok, body={"name": "strict"})
        check("strict 预设 200", st == 200 and js.get("ok") is True, str(js)[:200])
        st, js = http("POST", f"{base}/api/egress/classify", token=tok,
                      body={"text": "张三 2026年9月工资 18500 元", "dest_class": "llm"})
        check("strict 下机密级 would_allow=False", js.get("would_allow") is False, str(js)[:200])
        check("strict 下模式为 approval", js.get("mode") == "approval", str(js)[:200])
        st, js = http("POST", f"{base}/api/egress/classify", token=tok,
                      body={"text": "公司的年假怎么算", "dest_class": "llm"})
        check("strict 下普通问题仍放行（不是一刀切）", js.get("would_allow") is True, str(js)[:200])

        print("\n[API] 写策略 /api/egress/policy")
        st, js = http("POST", f"{base}/api/egress/policy", token=tok,
                      body={"policy": {"classes": {"search": {"default": "deny"}}}})
        check("写策略 200", st == 200 and js.get("ok") is True, str(js)[:200])
        check("search=deny 已生效", js["policy"]["classes"]["search"]["default"] == "deny", str(js["policy"]["classes"]["search"]))
        check("未提到的类别保持原值", js["policy"]["classes"]["llm"]["default"] == "allow", str(js["policy"]["classes"]["llm"]))

        print("\n[API] 非法预设被拒")
        st, js = http("POST", f"{base}/api/egress/preset", token=tok, body={"name": "nope"})
        check("非法预设返回 400", st == 400, f"st={st} {js}")

        print("\n[API] 出境日志 /api/egress/log")
        st, js = http("GET", f"{base}/api/egress/log?limit=50", token=tok)
        check("log 200", st == 200 and "logs" in js, str(js)[:200])
        check("stats 有汇总结构", all(k in js.get("stats", {}) for k in ("total", "by_class", "by_decision", "by_level")), str(js.get("stats"))[:200])

        print("\n[API] 权限：viewer 不能读写策略")
        http("POST", f"{base}/api/users", token=tok,
             body={"username": "egv", "password": "p123456", "role": "viewer"})
        st, vjs = http("POST", f"{base}/api/auth/login",
                       body={"tenant": "default", "username": "egv", "password": "p123456"})
        vtok = vjs.get("token", "")
        if vtok:
            st, _ = http("POST", f"{base}/api/egress/preset", token=vtok, body={"name": "lockdown"})
            check("viewer 改策略被拒(403)", st == 403, f"st={st}")
            st, _ = http("GET", f"{base}/api/egress/log", token=vtok)
            check("viewer 读出境日志被拒(403)", st == 403, f"st={st}")
            st, _ = http("GET", f"{base}/api/egress/policy", token=vtok)
            check("viewer 可读策略（透明性）", st == 200, f"st={st}")
        else:
            check("viewer 登录", False, str(vjs)[:200])

        # 复位
        http("POST", f"{base}/api/egress/preset", token=tok, body={"name": "balanced"})
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            lf.close()
        except Exception:
            pass

    print("\n" + "=" * 62)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    for f in FAIL:
        print("  - " + f)
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
