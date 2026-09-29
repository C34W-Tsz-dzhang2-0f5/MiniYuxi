# -*- coding: utf-8 -*-
"""端到端（HTTP 级）：把阿长截图里的那条指令真的发给 /api/chat，看技能是否落盘。

自包含：自己起 uvicorn（隔离 MINIYUXI_DATA_DIR / MINIYUXI_SKILLS_DIR）、自己关掉。
用本地夹具仓库冒充 GitHub 仓库，避免联网与沙箱删除慢的问题。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根（本文件在 tests/ 下）
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.isfile(PY):
    PY = sys.executable

WORK = tempfile.mkdtemp(prefix="e2e_chat_")
DATA = os.path.join(WORK, "data")
SKILLS = os.path.join(WORK, "skills")
FIXTURE = os.path.join(WORK, "coll_repo")
os.makedirs(DATA, exist_ok=True)
os.makedirs(SKILLS, exist_ok=True)

DEMO = "---\nname: {n}\ndescription: {d}\n---\n\n# {n}\n\nbody\n"
for sub, nm, desc in (("engineering/tdd", "tdd", "测试驱动开发"),
                      ("productivity/grill-me", "grill-me", "追问式设计")):
    p = os.path.join(FIXTURE, sub, "SKILL.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(DEMO.format(n=nm, d=desc))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _rm(path):
    """删目录，容忍只读文件（本测试故意造了一个只读 readonly.pack）。"""
    if not os.path.isdir(path):
        return
    for base, dirs, files in os.walk(path):
        for nm in files + dirs:
            try:
                os.chmod(os.path.join(base, nm), 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


PORT = free_port()
BASE = "http://127.0.0.1:%d" % PORT

env = dict(os.environ)
env["MINIYUXI_DATA_DIR"] = DATA
env["MINIYUXI_SKILLS_DIR"] = SKILLS
env["PYTHONIOENCODING"] = "utf-8"

print("PORT=%d\nDATA=%s\nSKILLS=%s\nFIXTURE=%s\n" % (PORT, DATA, SKILLS, FIXTURE))

log = open(os.path.join(WORK, "server.log"), "w", encoding="utf-8")
# 必须走 run.py：它负责 _frozen_bootstrap / _ensure_secret / db.init_db（建表 + 播种默认账号）
proc = subprocess.Popen(
    [PY, "run.py", "--host", "127.0.0.1", "--port", str(PORT), "--no-open"],
    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
)
PASS = FAIL = 0


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  " + label)
    else:
        FAIL += 1
        print("  FAIL  " + label)


try:
    import requests

    up = False
    for _ in range(90):
        try:
            if requests.get(BASE + "/api/health", timeout=2).status_code == 200:
                up = True
                break
        except Exception:
            time.sleep(0.5)
    check(up, "服务已起（/api/health 200）")
    if not up:
        print(open(os.path.join(WORK, "server.log"), encoding="utf-8", errors="ignore").read()[-2000:])
        raise SystemExit(1)

    r = requests.post(BASE + "/api/auth/login",
                      json={"tenant": "default", "username": "admin", "password": "admin123"}, timeout=15)
    check(r.status_code == 200, "登录成功")
    h = {"Authorization": "Bearer " + r.json()["token"]}

    def chat(q):
        rr = requests.post(BASE + "/api/chat", headers=h, json={"question": q}, timeout=180)
        return rr.status_code, rr.json()

    print("\n== 场景 1：npx skills add <集合仓库> --skill tdd（应只装 tdd）==")
    st, j = chat("npx skills add %s --skill tdd" % FIXTURE)
    check(st == 200, "HTTP 200")
    check(j.get("mode") == "tool" and j.get("tool") == "skill.install",
          "识别为 skill.install 工具调用（mode=tool, tool=%s）" % j.get("tool"))
    check(os.path.isfile(os.path.join(SKILLS, "tdd", "SKILL.md")),
          "磁盘上出现 skills/tdd/SKILL.md（真的装了，不是只回一句解释）")
    check(not os.path.isdir(os.path.join(SKILLS, "grill-me")),
          "未选中的 grill-me 没被一起装上")
    print("    回答片段：", str(j.get("answer", ""))[:160].replace("\n", " "))

    print("\n== 场景 2：--skill find-skills（集合里没有这个名字，应明确报错）==")
    st, j = chat("npx skills add %s --skill find-skills" % FIXTURE)
    ans = str(j.get("answer", ""))
    check(st == 200, "HTTP 200（不崩）")
    check("find-skills" in ans and "tdd" in ans,
          "回答里点名了缺失的技能 + 列出可用技能")
    check(not os.path.isdir(os.path.join(SKILLS, "find-skills")),
          "未命中不留下任何目录")

    print("\n== 场景 3：不带 --skill（整仓作为容器装入，向后兼容）==")
    st, j = chat("npx skills add %s" % FIXTURE)
    check(j.get("mode") == "tool", "识别为工具调用")
    check(os.path.isfile(os.path.join(SKILLS, "coll_repo", "engineering", "tdd", "SKILL.md")),
          "容器 coll_repo 装入，嵌套技能递归可见")

    print("\n== 场景 4：/api/skills/list 能看到刚装的技能 ==")
    r = requests.get(BASE + "/api/skills/list", headers=h, timeout=30)
    names = {s.get("name") for s in r.json().get("skills", [])}
    check({"tdd", "grill-me"} <= names, "tdd / grill-me 都进了技能列表")
    check("tdd" in names, "skills/list 含 tdd")

    print("\n== 场景 5：HTTP 卸载（含只读文件也要删干净）==")
    # 先删掉容器 coll_repo —— 它内部也有一个 name=tdd 的技能，
    # 留着会让 load_skill("tdd") 解析到容器里那份（同名歧义，见下方备注）
    r = requests.delete(BASE + "/api/skills/coll_repo", headers=h, timeout=120)
    check(r.status_code == 200 and r.json().get("removed") is True, "容器 coll_repo 卸载 removed=True")
    check(not os.path.isdir(os.path.join(SKILLS, "coll_repo")), "容器目录已删除")

    ro = os.path.join(SKILLS, "tdd", "readonly.pack")
    with open(ro, "w", encoding="utf-8") as f:
        f.write("fake")
    os.chmod(ro, 0o400)
    r = requests.delete(BASE + "/api/skills/tdd", headers=h, timeout=120)
    check(r.status_code == 200 and r.json().get("removed") is True, "DELETE 返回 removed=True")
    check(not os.path.isdir(os.path.join(SKILLS, "tdd")), "含只读文件的目录被删干净")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()
    log.close()
    tail = open(os.path.join(WORK, "server.log"), encoding="utf-8", errors="ignore").read()
    if FAIL:
        print("\n--- server.log tail ---\n" + tail[-2500:])
    print("\n==== HTTP 级端到端：PASS=%d FAIL=%d ====" % (PASS, FAIL))
    print("ALL_PASS" if FAIL == 0 else "HAS_FAIL")
    # 通过则清场；失败保留现场（MINIYUXI_E2E_KEEP=1 可强制保留）
    keep = FAIL or os.getenv("MINIYUXI_E2E_KEEP", "").strip().lower() in ("1", "true", "yes", "on")
    if keep:
        print("WORK=%s（保留以便排查）" % WORK)
    else:
        _rm(WORK)
        print("WORK 已清理")
    sys.exit(1 if FAIL else 0)
