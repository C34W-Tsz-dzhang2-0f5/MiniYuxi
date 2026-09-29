"""技能管理工具（skill.install / skill.uninstall / skill.list）验证（自包含，无需起服务）。

背景（2026-09-29 阿长反馈「对话框输入指令还是无法安装 skill」）：
技能安装此前只有「UI 抽屉」和 HTTP 接口两条入口，**没有注册成工具** →
用户在对话框里说「装这个技能」或粘贴 `npx skills add <仓库> --skill <名>` 时，
Agent Loop 的工具清单里根本没有对应能力，模型只能把命令"解释"一遍，不会真的执行。
本测试守住「自然语言 → 真执行」这条链。

覆盖：
  A. 注册与暴露：三个工具在 list_tools() 且在 agent_loop._to_openai_tools() 里（模型看得见）
  B. 系统提示：_agent_system 声明技能能力 + 「而不是解释命令」的强制指令
  C. method 自动判定：URL / 本地目录 / 正文（含 http 字样的正文不得被误判成 URL）
  D. 端到端（隔离 skills 目录）：paste 装 → list 可见 → uninstall 删干净
  E. 参数映射：单个技能仓库下 name / select 均可覆盖技能名
  F. 错误与安全：缺参 / 非 https → 返回可读错误（不抛栈）；hardline 载荷被治理层拦截
  G. 命令行快路径：`npx skills add … [--skill <名>]` 在**知识库闸门之前**被确定性识别为
     skill.install，且 `--skill` 映射到 **select**（端到端走 rag.answer 真装到磁盘）
  H. select 语义：只装集合仓库里的那一个（平铺）；未命中**明确报错并列出可用技能**；
     未传 select 时整仓作为容器装入（向后兼容）
  I. 回归：① `skills_dir=` 隔离目录校验（曾误报 frontmatter 错并回滚刚装好的技能）；
     ② 含只读文件的目录（git clone 的 .git/objects/pack/*）卸载时被真正删干净

运行：
  .venv/Scripts/python.exe tests/_verify_skill_tools.py
"""
import os
import shutil
import stat
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import skills_catalog  # noqa: E402
from core import skills_install as si  # noqa: E402
import core.tools_registry as tr  # noqa: E402
import core.agent_loop as agent_loop  # noqa: E402
import core.rag as rag  # noqa: E402

# 夹具仓库放在**被扫描的 skills 目录之外**：否则夹具里的 tdd/grill-me 会被 catalog 先扫到，
# 导致 load_skill() 解析到夹具而非刚装的那份，卸载时删错对象。
_FIX = tempfile.mkdtemp(prefix="my_skillfix_")

PASS = 0
FAIL = 0
_msgs = []


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        _msgs.append("  PASS  " + label)
    else:
        FAIL += 1
        _msgs.append("  FAIL  " + label)


def _with_temp_skills_dir(fn):
    """把 skills_catalog.SKILLS_DIR 临时指向空目录（工具→skills_install 走 catalog，需一致）。"""
    orig = skills_catalog.SKILLS_DIR
    tmp = tempfile.mkdtemp(prefix="my_skilltools_")
    skills_catalog.SKILLS_DIR = tmp
    skills_catalog.invalidate_cache()
    try:
        return fn(tmp)
    finally:
        skills_catalog.SKILLS_DIR = orig
        skills_catalog.invalidate_cache()
        si._rmtree(tmp)   # 可能含只读文件，走 _rmtree 保证删净


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


DEMO_MD = ("---\nname: {n}\ndescription: {d}\n---\n\n# {n}\n\n{body}\n")


def _make_collection_into(root):
    """造「集合仓库」：根目录无 SKILL.md，技能藏在子目录（模拟 mattpocock/skills 结构）。"""
    _write(os.path.join(root, "engineering", "tdd", "SKILL.md"),
           DEMO_MD.format(n="tdd", d="测试驱动开发", body="body"))
    _write(os.path.join(root, "productivity", "grill-me", "SKILL.md"),
           DEMO_MD.format(n="grill-me", d="追问式设计", body="body"))
    return root


# ---------------------------------------------------------------- A 注册与暴露
print("== A. 注册与暴露 ==")
_names = {t["name"]: t for t in tr.list_tools()}
check("skill.install" in _names, "skill.install 已注册")
check("skill.uninstall" in _names, "skill.uninstall 已注册")
check("skill.list" in _names, "skill.list 已注册")
check(all(_names[n].get("toolset") == "skills" for n in
          ("skill.install", "skill.uninstall", "skill.list") if n in _names),
      "三个工具的 toolset 均为 skills")
check(_names.get("skill.install", {}).get("schema", {}).get("required") == ["source"],
      "skill.install 必填 source")

_exposed = [x["function"]["name"] for x in agent_loop._to_openai_tools()]
check("skill.install" in _exposed, "skill.install 暴露给 Agent Loop（模型可见）")
check("skill.uninstall" in _exposed and "skill.list" in _exposed,
      "skill.uninstall / skill.list 同样暴露")
# 这是本次问题的核心断言：模型必须"有得可调"
check(len([n for n in _exposed if n.startswith("skill.")]) == 3,
      "Agent 工具清单含 3 个 skill.* 工具")

# ---------------------------------------------------------------- B 系统提示
print("== B. 系统提示 ==")
_sys = rag._agent_system("（空）", 0)
check("skill.install" in _sys and "skill.uninstall" in _sys,
      "系统提示声明了技能安装/卸载能力")
check("而不是解释命令" in _sys, "系统提示含「必须执行、而不是解释命令」强制指令")
check("npx skills add" in _sys, "系统提示点名了 npx skills add 这类命令行的映射方式")

# ---------------------------------------------------------------- C method 判定
print("== C. method 自动判定 ==")
check(tr._guess_skill_method("https://github.com/vercel-labs/skills") == "url", "https URL → url")
check(tr._guess_skill_method("github.com/mattpocock/skills") == "url", "裸 github.com 路径 → url")
check(tr._guess_skill_method("https://x.com/a.git") == "url", ".git 结尾 → url")
check(tr._guess_skill_method("git@github.com:a/b.git") == "url", "git@ 形式 → url")
_tmpdir = tempfile.mkdtemp(prefix="my_sk_src_")
check(tr._guess_skill_method(_tmpdir) == "path", "存在的本地目录 → path")
# 关键负例：正文里带 http 字样，不能被误判成 URL（否则会把 SKILL.md 正文当链接去 clone）
check(tr._guess_skill_method(DEMO_MD.format(n="a", d="b", body="参考 http://example.com")) == "paste",
      "含 http 字样的 SKILL.md 正文 → paste（不得误判为 url）")
check(tr._guess_skill_method("这不是路径也不是链接") == "paste", "普通文本 → paste")


# ---------------------------------------------------------------- D/E/F 端到端
def _e2e(tmp):
    print("== D. 端到端：装 → 列表 → 卸载 ==")
    r = tr.run_tool_governed("skill.install",
                             {"source": DEMO_MD.format(n="tool-demo", d="工具装技能演示", body="hello")})
    check(r.get("result", {}).get("ok") is True, "skill.install(paste) 返回 ok=True")
    check(os.path.isfile(os.path.join(tmp, "tool-demo", "SKILL.md")), "磁盘上出现 tool-demo/SKILL.md")
    check(r.get("result", {}).get("name") == "tool-demo", "返回 name == tool-demo")

    rl = tr.run_tool_governed("skill.list", {})
    body = str(rl.get("result", {}).get("result", ""))
    check("tool-demo" in body, "skill.list 能看到刚装的技能")

    ru = tr.run_tool_governed("skill.uninstall", {"name": "tool-demo"})
    check(ru.get("result", {}).get("removed") is True, "skill.uninstall 返回 removed=True")
    check(not os.path.isdir(os.path.join(tmp, "tool-demo")), "磁盘目录已删除")
    rl2 = tr.run_tool_governed("skill.list", {})
    check("tool-demo" not in str(rl2.get("result", {}).get("result", "")),
          "卸载后 skill.list 不再含该技能")

    print("== E. 参数映射：npx skills add <仓库> --skill <名> ==")
    # 用本地目录冒充「仓库」避免联网；断言 name 被正确应用（= 模型从命令行取出的 --skill 值）
    src = os.path.join(tmp, "_src_repo")
    _write(os.path.join(src, "SKILL.md"), DEMO_MD.format(n="orig-name", d="来源技能", body="x"))
    r2 = tr.run_tool_governed("skill.install", {"source": src, "name": "find-skills"})
    check(r2.get("result", {}).get("ok") is True, "skill.install(path + name) 返回 ok=True")
    check(r2.get("result", {}).get("name") == "find-skills",
          "name 生效：--skill find-skills → 安装名 find-skills")
    check(os.path.isfile(os.path.join(tmp, "find-skills", "SKILL.md")),
          "磁盘上出现 find-skills/SKILL.md")
    # 单个技能仓库下 select 与 name 同义（都是覆盖技能名）
    r3 = tr.run_tool_governed("skill.install", {"source": src, "select": "find-skills-2"})
    check(r3.get("result", {}).get("name") == "find-skills-2",
          "单技能仓库：select 同样覆盖技能名")
    tr.run_tool_governed("skill.uninstall", {"name": "find-skills-2"})
    tr.run_tool_governed("skill.uninstall", {"name": "find-skills"})   # 清场，供 H2 断言复用
    check(not os.path.isdir(os.path.join(tmp, "find-skills")), "E 清场：find-skills 已卸载")

    print("== F. 错误与安全 ==")
    # 本仓约定：handler 返回 {"error": ...} 时，call_tool 会把它嵌在 result 下；
    # handler 抛异常才会落到顶层 error。两种都算"返回可读错误"，都不应抛栈到调用方。
    def _err(r):
        if isinstance(r.get("error"), str):
            return r["error"]
        res = r.get("result")
        if isinstance(res, dict) and isinstance(res.get("error"), str):
            return res["error"]
        return ""

    e1 = tr.run_tool_governed("skill.install", {})
    check("source" in _err(e1), "缺 source → 返回可读错误（不抛栈）")
    e2 = tr.run_tool_governed("skill.uninstall", {})
    check("name" in _err(e2), "skill.uninstall 缺 name → 返回可读错误")
    e3 = tr.run_tool_governed("skill.install", {"source": "http://insecure.example.com/x"})
    check("https" in _err(e3), "非 https 链接 → 返回可读错误（不抛栈）")
    e4 = tr.run_tool_governed("skill.install", {"source": "rm -rf /"})
    check("安全层" in _err(e4) or "hardline" in _err(e4).lower(), "hardline 载荷被治理层拦截")
    e5 = tr.run_tool_governed("skill.uninstall", {"name": "../../etc"})
    check(_err(e5) != "" or e5.get("result", {}).get("removed") is False,
          "越界技能名不会误删（返回错误或 removed=False）")
    # 模型侧可见性：agent_loop 把 result 字符串化喂回模型，错误必须是可读文本而非异常栈
    check(len(_err(e1)) > 0 and "Traceback" not in _err(e1),
          "错误以可读文本回填给模型（无异常栈）")

    print("== G. 命令行快路径（用户粘贴 npx skills add …）==")
    d = rag._detect_tool("npx skills add https://github.com/vercel-labs/skills --skill find-skills")
    check(d == ("skill.install", {"source": "https://github.com/vercel-labs/skills",
                                  "select": "find-skills"}),
          "npx skills add <url> --skill <名> → --skill 映射到 select（不是容器名 name）")
    check(rag._detect_tool("npx skills add https://github.com/owner/repo")
          == ("skill.install", {"source": "https://github.com/owner/repo"}),
          "不带 --skill 时只传 source")
    check(rag._detect_tool("npx skills add https://github.com/owner/repo --skill=tdd")
          == ("skill.install", {"source": "https://github.com/owner/repo", "select": "tdd"}),
          "--skill=tdd（等号写法）同样映射到 select")
    check(rag._detect_tool("帮我装这个技能") is None,
          "自然语言不被正则猜意图（仍交给 Agent Loop）")
    check(rag._detect_tool("tool: skill.list") == ("skill.list", {}),
          "tool: 前缀快路径仍可用")

    # 端到端：走 rag.answer 的完整快路径（用本地集合仓库冒充，避免联网）
    # 夹具放 _FIX（skills 目录之外），避免夹具里的 tdd 与刚装的 tdd 撞名
    src2 = _make_collection_into(os.path.join(_FIX, "cli_repo"))
    out = rag.answer("default", "npx skills add %s --skill tdd" % src2)
    check(out.get("mode") == "tool" and out.get("tool") == "skill.install",
          "rag.answer 把该命令行识别为 skill.install 工具调用（mode=tool）")
    check(os.path.isfile(os.path.join(tmp, "tdd", "SKILL.md")),
          "端到端：--skill tdd 真的把「那一个」技能装到磁盘（不是只回一句解释）")
    check(not os.path.isdir(os.path.join(tmp, "grill-me")),
          "端到端：未选中的技能不会被一起装上（select 只装一个）")
    check("工具调用" in str(out.get("answer") or ""),
          "端到端：回答里回执了工具调用结果（不是只回一句解释）")

    print("== H. select：只装集合仓库里的一个技能 ==")
    coll = _make_collection_into(os.path.join(_FIX, "coll_repo"))

    # H1 命中 → 只装那一个，且**平铺**到 <名>/SKILL.md（不套集合仓库的目录层级）
    rh = tr.run_tool_governed("skill.install", {"source": coll, "select": "tdd"})
    check(rh.get("result", {}).get("ok") is True, "select=tdd → 安装成功")
    check(rh.get("result", {}).get("name") == "tdd", "select=tdd → 安装名 tdd")
    check(rh.get("result", {}).get("count") == 1, "select=tdd → 只装了 1 个技能")
    check(os.path.isfile(os.path.join(tmp, "tdd", "SKILL.md")), "平铺到 tdd/SKILL.md")
    check(not os.path.isdir(os.path.join(tmp, "grill-me")), "未选中的 grill-me 没被装上")
    tr.run_tool_governed("skill.uninstall", {"name": "tdd"})

    # H2 未命中 → 明确报错 + 列出可用技能（绝不静默整仓装入）
    rmiss = tr.run_tool_governed("skill.install", {"source": coll, "select": "find-skills"})
    msg = _err(rmiss)
    check("find-skills" in msg and "tdd" in msg,
          "select 未命中 → 报错并列出可用技能（含 tdd）")
    check(not os.path.isdir(os.path.join(tmp, "find-skills")),
          "select 未命中 → 不留任何目录（不静默装整个仓库）")

    # H3 无 select → 向后兼容：整仓作为一个容器装入
    rcont = tr.run_tool_governed("skill.install", {"source": coll, "name": "coll-box"})
    check(rcont.get("result", {}).get("count") == 2, "无 select → 整装 2 个技能（向后兼容）")
    check(os.path.isdir(os.path.join(tmp, "coll-box")), "无 select → 容器目录 coll-box")
    tr.run_tool_governed("skill.uninstall", {"name": "tdd"})
    tr.run_tool_governed("skill.uninstall", {"name": "grill-me"})

    # H4 非法 select 名 → 可读错误（不得越界建目录）
    rbad = tr.run_tool_governed("skill.install", {"source": coll, "select": "../escape"})
    check(_err(rbad) != "", "非法 select 名 → 返回可读错误")
    check(not os.path.isdir(os.path.join(tmp, "..", "escape")), "非法 select 名不会越界建目录")

    print("== I. 回归：skills_dir 隔离目录校验 / 只读文件清理 ==")
    # I1 原缺陷①：install_skill(skills_dir=X) 却拿**默认**目录去校验 →
    #    误报「SKILL.md 缺少合法 frontmatter」并把刚装好的技能回滚删掉。
    iso = tempfile.mkdtemp(prefix="my_iso_")
    try:
        ri = si.install_skill("path", coll, "iso-box", skills_dir=iso)
        check(ri.get("ok") is True and ri.get("count") == 2,
              "skills_dir= 隔离目录安装成功（原缺陷①：误报 frontmatter 错并回滚）")
        check(os.path.isdir(os.path.join(iso, "iso-box")), "隔离目录里确有 iso-box")

        # I2 原缺陷②：git clone 的 .git/objects/pack/* 是只读文件 → 裸 rmtree 抛
        #    PermissionError，ignore_errors 又静默留残留 → 卸载后目录删不干净。
        ro = os.path.join(iso, "iso-box", "engineering", "tdd", "readonly.pack")
        _write(ro, "fake git pack")
        os.chmod(ro, stat.S_IREAD)
        check(not (stat.S_IMODE(os.stat(ro).st_mode) & stat.S_IWRITE), "只读文件已置位（构造成功）")
        ui = si.uninstall_skill("tdd", skills_dir=iso)
        check(ui.get("removed") is True, "卸载含只读文件的技能返回 removed=True")
        check(not os.path.isdir(os.path.join(iso, "iso-box", "engineering", "tdd")),
              "原缺陷②：含只读文件的目录被真正删干净（不再静默残留）")
        check(os.path.isdir(os.path.join(iso, "iso-box", "productivity", "grill-me")),
              "同仓库其它技能未被连带误删")
    finally:
        si._rmtree(iso)

    # I3 staging 不把 .git 装进技能目录（只读 pack 文件是删除失败的根源）
    repo = os.path.join(_FIX, "gitlike_repo")
    _write(os.path.join(repo, "SKILL.md"), DEMO_MD.format(n="gitlike", d="带 .git 的仓库", body="z"))
    _write(os.path.join(repo, ".git", "objects", "pack", "x.pack"), "fake")
    os.chmod(os.path.join(repo, ".git", "objects", "pack", "x.pack"), stat.S_IREAD)
    rg = tr.run_tool_governed("skill.install", {"source": repo})
    check(rg.get("result", {}).get("ok") is True, "含 .git 的本地仓库可安装")
    check(not os.path.isdir(os.path.join(tmp, "gitlike", ".git")),
          "staging 丢弃 .git（技能目录里不留版本库）")
    tr.run_tool_governed("skill.uninstall", {"name": "gitlike"})
    check(not os.path.isdir(os.path.join(tmp, "gitlike")), "含只读 .git 的技能卸载干净")


try:
    _with_temp_skills_dir(_e2e)
finally:
    shutil.rmtree(_tmpdir, ignore_errors=True)
    si._rmtree(_FIX)

print()
for m in _msgs:
    print(m)
print()
print("==== 技能管理工具验证：PASS=%d  FAIL=%d ====" % (PASS, FAIL))
print("ALL_PASS" if FAIL == 0 else "HAS_FAIL")
sys.exit(1 if FAIL else 0)
