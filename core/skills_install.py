"""技能安装 / 卸载（T6）—— core 单一可信源，api.py 只做传输（见 CONTRIBUTING §4）。

安全边界：技能正文仅作为 Agent 提示词上下文注入（见 core/wb_workbench.py），**不执行代码**。
本模块职责：来源归一（粘贴 / 本地路径 / https 链接）→ staging → 目录名规范化 → catalog 校验；
以及按名卸载（支持嵌套技能集合仓库，如 github.com/mattpocock/skills）。

设计要点：
- **staging 落在 skills/ 的同级目录**（绝不在 skills/ 内），避免半成品被 catalog 扫到 / 残留在技能目录；
  同盘保证 `shutil.move` 不触发 Windows 跨盘错误。
- **目录名 == frontmatter name == catalog 主键**；嵌套集合仓库（根无 SKILL.md）用容器名。
- **`select` = 从集合仓库里只装某一个技能**（对应 `npx skills add <仓库> --skill <名>`）：
  命中则平铺装到 `SKILLS_DIR/<名>/`；未命中明确报错并列出可用技能（不静默装整个仓库）。
  未传 select 时，嵌套集合仓库仍按容器整装（向后兼容）。
- 所有外部命令 / 路径操作过 `core.security` 的守卫。
- 安装 / 卸载后 `skills_catalog.invalidate_cache()`，使 /api/skills/list 立即反映变更。
- 删除一律走 `_rmtree()`：git clone 的 `.git/objects/pack/*` 是只读文件，裸 rmtree 删不掉。
"""
import glob
import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from . import skills_catalog


class SkillInstallError(Exception):
    """安装 / 卸载失败（api 层转 HTTP 400）。"""


# ---------------- 纯辅助函数 ----------------
def _clear_readonly(root):
    """递归清掉只读位（Windows 上 git clone 的 `.git/objects/pack/*` 是只读的）。"""
    for base, dirs, files in os.walk(root):
        for nm in files + dirs:
            try:
                os.chmod(os.path.join(base, nm), stat.S_IWRITE)
            except OSError:
                pass


def _rmtree(path):
    """删目录，**容忍 Windows 上 git clone 留下的只读文件**。

    为什么不能用裸 `shutil.rmtree(path, ignore_errors=True)`：
    `git clone` 会把 `.git/objects/pack/*.pack|.idx` 标成只读（-r--r--r--），
    Windows 上 `os.unlink` 直接 `PermissionError` → `ignore_errors` **静默**留下半截目录
    （2026-09-29 实测残留 `.git/objects/pack` 共 7 个条目，卸载后技能目录删不干净）。

    策略「先裸删，失败再清只读位重试」：正常路径零额外开销（不做预扫描），
    只有真遇到只读文件才付出一次 os.walk 的代价。
    """
    if not path or not os.path.exists(path):
        return
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass
    _clear_readonly(path)
    try:
        shutil.rmtree(path)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)   # 最后兜底：尽力而为，不抛栈


# staging 时丢弃的目录/文件：技能只需要正文，不需要版本库与字节码缓存。
# `.git` 同时是 Windows 删除失败的根源（只读 pack 文件），一并丢掉。
_STAGE_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")


def safe_skill_name(name):
    """技能名白名单校验：仅字母数字_-. ，长度 ≤64；拒绝 .. / / \\ 。"""
    name = (name or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    if not re.match(r"^[A-Za-z0-9_.\-]+$", name):
        return None
    return name[:64]


def name_from_frontmatter(text):
    m = re.search(r"^name\s*:\s*(.+)$", text or "", re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def set_frontmatter_name(text, new_name):
    """把 SKILL.md 顶部 frontmatter 的 name 设为 new_name（替换 / 插入 / 兜底包一层）。"""
    lines = (text or "").split("\n")
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            for i in range(1, end):
                if re.match(r"^name\s*:", lines[i]):
                    lines[i] = "name: " + new_name
                    return "\n".join(lines)
            lines.insert(1, "name: " + new_name)
            return "\n".join(lines)
    return "---\nname: " + new_name + "\n---\n" + text


def has_skill_md(d):
    """目录（含递归子目录）内是否存在至少一个 SKILL.md（支持嵌套技能集合仓库）。"""
    return any(glob.glob(os.path.join(d, "**", "SKILL.md"), recursive=True))


def iter_sub_skills(d):
    """列出目录下所有 SKILL.md → [(技能名, 所在目录), ...]（支持嵌套集合仓库）。

    技能名取 frontmatter 的 name，缺失则退回目录名，保证「能选得中」。
    """
    out = []
    for p in sorted(glob.glob(os.path.join(d, "**", "SKILL.md"), recursive=True)):
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        folder = os.path.dirname(p)
        nm = name_from_frontmatter(text) or os.path.basename(folder)
        out.append(((nm or "").strip(), folder))
    return out


def find_sub_skill(d, want):
    """在集合仓库里按 frontmatter name / 目录名（忽略大小写）精确匹配目标技能目录。

    命中返回该子目录绝对路径，否则 None。用于 `npx skills add <repo> --skill <名>`
    「只装集合里的某一个技能」的语义。
    """
    w = (want or "").strip().lower()
    if not w:
        return None
    for nm, folder in iter_sub_skills(d):
        if nm.lower() == w or os.path.basename(folder).strip().lower() == w:
            return folder
    return None


def _same_tree(child, parent):
    """判断 child 是否位于 parent 目录树内（大小写 / 分隔符不敏感，Windows 友好）。

    必要性：SKILLS_DIR 可能来自环境变量（正斜杠），而 glob 返回的路径用的是
    本机分隔符（反斜杠）→ 直接 `startswith(target + os.sep)` 会误判为「不在树内」。
    """
    c = os.path.normcase(os.path.abspath(child or ""))
    p = os.path.normcase(os.path.abspath(parent or "")) + os.sep
    return c.startswith(p)


def normalize_url(value):
    """把常见写法归一成可 clone / 下载的 https 链接。

    - 补 https:// 前缀：`github.com/owner/repo` → `https://github.com/owner/repo`
    - GitHub/GitLab/Gitee 仓库页（无 .git / .zip）→ 补 `.git`，走 clone
    - 仅接受 https；http 明确拒绝。
    """
    v = (value or "").strip()
    if v.startswith("http://"):
        raise SkillInstallError("仅支持 https 链接")
    if not v.startswith("https://"):
        if re.match(r"^[\w.\-]+\.[\w.\-]+/", v):   # 形如 github.com/owner/repo
            v = "https://" + v
        else:
            raise SkillInstallError("仅支持 https 链接（git 仓库或 .zip）")
    low = v.lower()
    if not (low.endswith(".git") or low.endswith(".zip")):
        if re.match(r"^https://(github|gitlab|gitee)\.com/[^/]+/[^/]+/?$", low):
            v = v.rstrip("/") + ".git"
        else:
            raise SkillInstallError("仅支持 .git 仓库或 .zip 压缩包链接（或形如 github.com/owner/repo）")
    return v


# ---------------- 安装 ----------------
def install_skill(method, value, name="", skills_dir=None, select=""):
    """安装技能。成功返回 {ok,name,path,description,count}，失败抛 SkillInstallError。

    name    目标目录名 / 容器名（可选）。单个技能仓库会回写 frontmatter 的 name；
            嵌套集合仓库且未命中子技能时，用作容器目录名（向后兼容）。
    select  只安装集合仓库中的**某一个**技能（可选），对应
            `npx skills add <仓库> --skill <名>`：命中则把该子技能**平铺**装到
            SKILLS_DIR/<名>/；未命中**明确报错并列出可用技能**（不静默装整个仓库）。
    """
    from . import security

    method = (method or "paste").lower()
    value = (value or "").strip()
    SKILLS_DIR = skills_dir or skills_catalog.SKILLS_DIR
    os.makedirs(SKILLS_DIR, exist_ok=True)
    want_select = (select or "").strip()
    if want_select and not safe_skill_name(want_select):
        raise SkillInstallError("无效的 --skill 名称：%s（仅字母数字_-.，且不得含路径分隔符）"
                                % want_select[:40])
    explicit = safe_skill_name(want_select) or safe_skill_name(name)
    container_name = explicit   # 嵌套集合仓库（根无 SKILL.md）时的容器目录名

    # staging 落在 skills/ 的**同级目录**：既不在 skills/ 内（不会被 catalog 扫到 / 残留），
    # 又与 SKILLS_DIR 同盘（避免 Windows 跨盘 os.replace 报 WinError 17）。
    stage_parent = os.path.dirname(os.path.abspath(SKILLS_DIR)) or None
    try:
        stage = tempfile.mkdtemp(prefix="_skill_stage_", dir=stage_parent)
    except Exception:
        stage = tempfile.mkdtemp(prefix="_skill_stage_")
    payload = None   # 真正要落盘的目录（默认 = stage；集合仓库选中子技能时为 pick_dir）
    try:
        if method == "paste":
            if not value:
                raise SkillInstallError("请粘贴 SKILL.md 内容")
            with open(os.path.join(stage, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(value)

        elif method == "path":
            if not value:
                raise SkillInstallError("请填写本地文件夹绝对路径")
            src = os.path.abspath(value)
            if not os.path.isdir(src) or not has_skill_md(src):
                raise SkillInstallError("路径不存在或不包含 SKILL.md（支持嵌套目录）")
            shutil.rmtree(stage, ignore_errors=True)   # stage 刚建、必空
            shutil.copytree(src, stage, ignore=_STAGE_IGNORE)
            container_name = container_name or safe_skill_name(os.path.basename(src.rstrip("/\\")))

        elif method == "url":
            url = normalize_url(value)
            if security.hardline_block(url) or security.is_dangerous_command(url):
                raise SkillInstallError("链接命中安全黑名单，已拒绝")
            if url.lower().endswith(".git"):
                try:
                    subprocess.run(["git", "clone", "--depth", "1", url, stage],
                                   timeout=180, capture_output=True, check=True)
                except FileNotFoundError:
                    raise SkillInstallError("本机未安装 git，无法克隆仓库")
                except subprocess.CalledProcessError as e:
                    raise SkillInstallError(
                        "git clone 失败：" + (e.stderr or b"").decode(errors="ignore")[:200])
            else:
                # zip 下载 + 安全解压（逐条防穿越，过 security.validate_within_dir）
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "miniyuxi"})
                    data = urllib.request.urlopen(req, timeout=60).read()
                except urllib.error.URLError as e:
                    raise SkillInstallError("下载失败：" + str(e)[:200])
                if data[:2] != b"PK":
                    raise SkillInstallError("链接内容不是 zip（缺少 PK 头）")
                try:
                    zf = zipfile.ZipFile(io.BytesIO(data))
                    for member in zf.namelist():
                        dest = os.path.normpath(os.path.join(stage, member))
                        if not security.validate_within_dir(dest, stage):
                            raise SkillInstallError("zip 内含越界路径，已拒绝")
                        if member.endswith("/"):
                            os.makedirs(dest, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(zf.read(member))
                    zf.close()
                except SkillInstallError:
                    raise
                except Exception as e:
                    raise SkillInstallError("zip 解压失败：" + str(e)[:200])
            base = os.path.basename(url.rstrip("/").split("?")[0])
            if base.lower().endswith(".git"):
                base = base[:-4]
            container_name = container_name or safe_skill_name(base)

        else:
            raise SkillInstallError("未知安装方式：%s" % method)

        if not has_skill_md(stage):
            raise SkillInstallError("未找到 SKILL.md（支持嵌套目录）")

        # 统一清理版本库（git clone 会产生 stage/.git；只读 pack 文件是删除失败的根源）
        _rmtree(os.path.join(stage, ".git"))

        # 目录名规范化 +（集合仓库）子技能选择
        payload = stage
        root_skill = os.path.join(stage, "SKILL.md")
        if os.path.isfile(root_skill):
            # 单技能仓库：显式名回写 frontmatter（--skill 与 name 在此同义）
            text = open(root_skill, encoding="utf-8", errors="ignore").read()
            if explicit:
                with open(root_skill, "w", encoding="utf-8") as f:
                    f.write(set_frontmatter_name(text, explicit))
                final = explicit
            else:
                final = safe_skill_name(name_from_frontmatter(text))
        else:
            # 嵌套集合仓库
            want = want_select or explicit
            picked = find_sub_skill(stage, want) if want else None
            if picked:
                # 只装选中的那一个：把子目录平铺出来，其余丢弃
                final = safe_skill_name(want) or safe_skill_name(name_from_frontmatter(
                    open(os.path.join(picked, "SKILL.md"), encoding="utf-8",
                         errors="ignore").read()))
                if not final:
                    raise SkillInstallError("无法解析技能名：请在 name / select 显式指定")
                try:
                    pick_dir = tempfile.mkdtemp(prefix="_skill_pick_", dir=stage_parent)
                except Exception:
                    pick_dir = tempfile.mkdtemp(prefix="_skill_pick_")
                _rmtree(pick_dir)
                shutil.move(picked, pick_dir)   # 同盘 rename
                payload = pick_dir
            elif want_select:
                avail = [n for n, _ in iter_sub_skills(stage) if n]
                raise SkillInstallError(
                    "集合仓库中没有名为「%s」的技能。可用技能（%d 个）：%s"
                    % (want_select, len(avail),
                       "、".join(avail[:30]) + ("…" if len(avail) > 30 else "")))
            else:
                final = container_name   # 无选择意图 → 整仓作为一个容器装入
        if not final:
            raise SkillInstallError("无法解析技能名：请在 name 字段显式指定（仅字母数字_-.）")

        target = os.path.join(SKILLS_DIR, final)
        if not security.validate_within_dir(target, SKILLS_DIR):
            raise SkillInstallError("目标路径越界")
        if os.path.exists(target):
            _rmtree(target)
        shutil.move(payload, target)   # move 兼容跨盘（同盘则等价 rename）
    finally:
        # stage / payload 已被 move 走时此处为 no-op；异常路径则清掉，绝不留残留
        _rmtree(stage)
        if payload and payload != stage:
            _rmtree(payload)

    # 刷新 catalog 缓存 + 校验至少一个合法 SKILL.md
    # ⚠️ 必须用 **SKILLS_DIR** 去校验（不能裸调 list_skills() 扫默认目录）：
    #    否则传了 skills_dir 的调用方会「装到 A、却拿 B 校验」→ 误报 frontmatter 错
    #    并把刚装好的技能回滚删掉（2026-09-29 实测踩中）。
    skills_catalog.invalidate_cache()
    installed = [s for s in skills_catalog.list_skills(skills_dir=SKILLS_DIR)
                 if s.get("name") and s.get("description")
                 and _same_tree(s.get("path"), target)]
    if not installed:
        _rmtree(target)
        skills_catalog.invalidate_cache()
        raise SkillInstallError("SKILL.md 缺少合法 frontmatter（需 name + description）")
    return {"ok": True, "name": final, "path": target,
            "description": installed[0].get("description", ""), "count": len(installed)}


# ---------------- 卸载 ----------------
def uninstall_skill(name, skills_dir=None):
    """按名卸载技能。优先经 catalog 解析其真实子目录（支持嵌套），再删；不连带误删同级技能。"""
    from . import security

    nm = safe_skill_name(name)
    if not nm:
        raise SkillInstallError("无效技能名")
    SKILLS_DIR = skills_dir or skills_catalog.SKILLS_DIR
    removed = False
    sk = skills_catalog.load_skill(nm, skills_dir=SKILLS_DIR)
    if sk and sk.get("path"):
        d = os.path.dirname(os.path.abspath(sk["path"]))
        if security.validate_within_dir(d, SKILLS_DIR) and os.path.isdir(d):
            _rmtree(d)
            removed = True
    if not removed:
        target = os.path.abspath(os.path.join(SKILLS_DIR, nm))
        if security.validate_within_dir(target, SKILLS_DIR) and os.path.isdir(target):
            _rmtree(target)
            removed = True
    skills_catalog.invalidate_cache()
    return {"ok": True, "name": nm, "removed": removed}
