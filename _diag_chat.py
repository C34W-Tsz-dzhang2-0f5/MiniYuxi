"""诊断「无法对话」：实测 登录 -> 鉴权 -> 对话 全链路（只读，不改数据）。

用法：先起服务，再跑本脚本。
"""
import sys
import httpx

BASE = "http://127.0.0.1:8801"

def line(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)

def main():
    c = httpx.Client(base_url=BASE, timeout=90.0)

    line("1. 首页可达性")
    for path in ["/", "/api/health"]:
        try:
            r = c.get(path)
            print(f"  GET {path:<16} -> {r.status_code}")
        except Exception as e:
            print(f"  GET {path:<16} -> EXC {type(e).__name__}: {e}")

    line("2. 未带 token 访问受保护接口（应 401）")
    r = c.post("/api/wb/chat", json={"message": "你好"})
    print(f"  POST /api/wb/chat 无 token -> {r.status_code} {r.text[:160]}")

    line("3. 登录测试（默认账号）")
    token = None
    for pw in ["admin123"]:
        try:
            r = c.post("/api/auth/login",
                       json={"tenant": "default", "username": "admin", "password": pw})
            print(f"  login admin/{pw:<10} -> {r.status_code} {r.text[:200]}")
            if r.status_code == 200:
                token = r.json().get("token")
        except Exception as e:
            print(f"  login EXC {type(e).__name__}: {e}")

    if not token:
        print("\n  ⚠ 默认口令登录失败 —— 口令可能已被 LAN 守卫重置或人工改过。")
        print("    尝试从 config / .env 读取口令线索...")
        return 2

    H = {"Authorization": "Bearer " + token}

    line("4. 带 token 访问聊天相关接口")
    for path in ["/api/wb/stats", "/api/skills/list", "/api/models/catalog"]:
        try:
            r = c.get(path, headers=H)
            print(f"  GET {path:<22} -> {r.status_code} {r.text[:120]}")
        except Exception as e:
            print(f"  GET {path:<22} -> EXC {type(e).__name__}: {e}")

    line("5. 真实对话（这条会调模型，最可能出问题）")
    try:
        r = c.post("/api/wb/chat",
                   json={"message": "你好，请用一句话自我介绍", "scene": "日常办公",
                         "history": [], "mode": "agent"},
                   headers=H)
        print(f"  POST /api/wb/chat -> {r.status_code}")
        print(f"  body[:800]: {r.text[:800]}")
    except Exception as e:
        print(f"  POST /api/wb/chat -> EXC {type(e).__name__}: {e}")

    line("6. 流式对话（前端实际走的路径）")
    try:
        with c.stream("POST", "/api/wb/chat/stream",
                      json={"message": "你好", "history": [], "mode": "agent"},
                      headers=H) as r:
            print(f"  HTTP {r.status_code}")
            n = 0
            for chunk in r.iter_bytes():
                n += len(chunk)
                if n > 600:
                    break
            print(f"  收到 {n} 字节")
    except Exception as e:
        print(f"  stream -> EXC {type(e).__name__}: {e}")

    line("7. 可用的对话路由盘点（看前端该打哪个）")
    print("  见 api.py 中 /api/wb/* 定义")
    return 0


if __name__ == "__main__":
    sys.exit(main())
