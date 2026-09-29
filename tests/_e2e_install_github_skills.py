"""端到端：对着真实运行的 MiniYuxi 服务，用「https 链接」方式安装一个 GitHub 技能集合仓库，
再核对技能是否进入 catalog（= 网页版技能列表可见）。

用法：
  python run.py --no-open            # 另开一个终端起服务（127.0.0.1:8801）
  .venv/Scripts/python.exe tests/_e2e_install_github_skills.py [repo_url] [name]

默认安装 github.com/mattpocock/skills。
"""
import os
import sys
import json
import requests

BASE = os.getenv("MINIYUXI_BASE", "http://127.0.0.1:8801")
REPO = sys.argv[1] if len(sys.argv) > 1 else "https://github.com/mattpocock/skills.git"
NAME = sys.argv[2] if len(sys.argv) > 2 else "mattpocock-skills"


def main():
    # 1) 登录
    r = requests.post(BASE + "/api/auth/login",
                      json={"tenant": "default", "username": "admin", "password": "admin123"},
                      timeout=15)
    r.raise_for_status()
    tok = r.json()["token"]
    h = {"Authorization": "Bearer " + tok}
    print("[1] 登录成功，token=%s…" % tok[:12])

    # 2) 安装（method=url → git clone）
    body = {"method": "url", "value": REPO, "name": NAME}
    r = requests.post(BASE + "/api/skills/install", headers=h, json=body, timeout=240)
    print("[2] POST /api/skills/install ->", r.status_code)
    j = r.json()
    if r.status_code != 200:
        print("    安装失败：", json.dumps(j, ensure_ascii=False)[:400])
        sys.exit(1)
    print("    ok=%s name=%s count=%s" % (j.get("ok"), j.get("name"), j.get("count")))
    print("    path=%s" % j.get("path"))

    # 3) 磁盘核对：解析本次安装目录下所有 SKILL.md 的 frontmatter name
    import glob
    import re as _re
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(proj, "skills", NAME)
    files = glob.glob(os.path.join(base, "**", "SKILL.md"), recursive=True)
    disk_names = []
    for p in files:
        txt = open(p, encoding="utf-8", errors="ignore").read()
        m = _re.search(r"^name\s*:\s*(.+)$", txt, _re.M)
        if m:
            disk_names.append(m.group(1).strip().strip('"').strip("'"))
    print("[3] 磁盘 SKILL.md 文件数 = %d（目录：skills/%s）" % (len(files), NAME))

    # 4) 接口核对：这些技能是否已进入 catalog（网页版技能抽屉用的就是这个接口）
    r = requests.get(BASE + "/api/skills/list", headers=h, timeout=30)
    r.raise_for_status()
    skills = r.json().get("skills", [])
    catalog_names = set(s.get("name") for s in skills)
    folder = [s for s in skills if s.get("type") == "folder"]
    missing = [n for n in disk_names if n not in catalog_names]
    print("[4] /api/skills/list -> 共 %d 条，文件夹技能 %d 条" % (len(skills), len(folder)))
    print("    本次安装 %d 个，已进入技能列表 %d 个，缺失 %d 个"
          % (len(disk_names), len(disk_names) - len(missing), len(missing)))
    for n in sorted(disk_names):
        print("      -", n)

    # 5) 抽查一个技能正文能否被读到（= 能被注入对话）
    if disk_names:
        head = open(files[0], encoding="utf-8", errors="ignore").read()[:160].replace("\n", " ")
        print("[5] 抽查正文（%s）：%s…" % (os.path.relpath(files[0], proj), head))

    # 6) 清场：E2E 不应在真实 skills/ 里留痕（否则技能列表会多出几十个幽灵技能）
    #    需要保留现场时设 MINIYUXI_E2E_KEEP=1
    if os.getenv("MINIYUXI_E2E_KEEP", "").strip().lower() in ("1", "true", "yes", "on"):
        print("[6] 保留本次安装（MINIYUXI_E2E_KEEP=1）")
    else:
        r = requests.delete(BASE + "/api/skills/" + NAME, headers=h, timeout=120)
        print("[6] DELETE /api/skills/%s -> %s %s" % (NAME, r.status_code, r.text[:160]))
        left = glob.glob(os.path.join(base, "**", "SKILL.md"), recursive=True)
        print("    清场后残留 SKILL.md = %d（期望 0）" % len(left))
        if left:
            print("    清理未彻底，请手工检查 %s" % base)
            sys.exit(1)
    print("E2E_INSTALL_OK")


if __name__ == "__main__":
    main()
