"""技能安装 / 卸载（T6）—— core 单一可信源，api.py 只做传输（见 CONTRIBUTING §4）。

安全边界：技能正文仅作为 Agent 提示词上下文注入（见 core/wb_workbench.py），**不执行代码**。
本模块职责：来源归一（粘贴 / 本地路径 / https 链接）→ staging → 目录名规范化 → catalog 校验；
以及按名卸载（支持嵌套技能集合仓库，如 github.com/mattpocock/skills）。

设计要点：
- **staging 落在 skills/ 的同级目录**（绝不在 skills/ 内），避免半成品被 catalog 扫到 / 残留在技能目录；
  同盘保证 `shutil.move` 不触发 Windows 跨盘错误。
- **目录名 == frontmatter name == catalog 主键**；嵌套集合仓库（根无 SKILL.md）用容器名。
- 所有外部命令 / 路径操作过 `core.security` 的守卫。
- 安装 / 卸载后 `skills_catalog.invalidate_cache()`，使 /api/skills/list 立即反映变更。
"""
import glob
import io
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from . import skills_catalog


class SkillInstallError(Exception):
    """安装 / 卸载失败（api 层转 HTTP 400）。"""


# ---------------- 纯辅助函数 ----------------
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
def install_skill(method, value, name="", skills_dir=None):
    """安装技能。成功返回 {ok,name,path,description,count}，失败抛 SkillInstallError。"""
    from . import security

    method = (method or "paste").lower()
    value = (value or "").strip()
    SKILLS_DIR = skills_dir or skills_catalog.SKILLS_DIR
    os.makedirs(SKILLS_DIR, exist_ok=True)
    explicit = safe_skill_name(name)
    container_name = explicit   # 嵌套集合仓库（根无 SKILL.md）时的容器目录名

    # staging 落在 skills/ 的**同级目录**：既不在 skills/ 内（不会被 catalog 扫到 / 残留），
    # 又与 SKILLS_DIR 同盘（避免 Windows 跨盘 os.replace 报 WinError 17）。
    stage_parent = os.path.dirname(os.path.abspath(SKILLS_DIR)) or None
    try:
        stage = tempfile.mkdtemp(prefix="_skill_stage_", dir=stage_parent)
    except Exception:
        stage = tempfile.mkdtemp(prefix="_skill_stage_")
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
            shutil.rmtree(stage, ignore_errors=True)
            shutil.copytree(src, stage)
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

        # 目录名规范化
        root_skill = os.path.join(stage, "SKILL.md")
        if os.path.isfile(root_skill):
            text = open(root_skill, encoding="utf-8", errors="ignore").read()
            if explicit:
                with open(root_skill, "w", encoding="utf-8") as f:
                    f.write(set_frontmatter_name(text, explicit))
                final = explicit
            else:
                final = safe_skill_name(name_from_frontmatter(text))
        else:
            final = container_name   # 纯嵌套集合仓库
        if not final:
            raise SkillInstallError("无法解析技能名：请在 name 字段显式指定（仅字母数字_-.）")

        target = os.path.join(SKILLS_DIR, final)
        if not security.validate_within_dir(target, SKILLS_DIR):
            raise SkillInstallError("目标路径越界")
        if os.path.exists(target):
            shutil.rmtree(target)
        shutil.move(stage, target)   # move 兼容跨盘（同盘则等价 rename）
    finally:
        # stage 已被 move 走时此处为 no-op；异常路径则清掉，绝不留残留
        shutil.rmtree(stage, ignore_errors=True)

    # 刷新 catalog 缓存 + 校验至少一个合法 SKILL.md
    skills_catalog.invalidate_cache()
    target_abs = os.path.abspath(target)
    installed = [s for s in skills_catalog.list_skills()
                 if s.get("name") and s.get("description")
                 and (s.get("path") or "").startswith(target_abs + os.sep)]
    if not installed:
        shutil.rmtree(target, ignore_errors=True)
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
    sk = skills_catalog.load_skill(nm)
    if sk and sk.get("path"):
        d = os.path.dirname(os.path.abspath(sk["path"]))
        if security.validate_within_dir(d, SKILLS_DIR) and os.path.isdir(d):
            shutil.rmtree(d)
            removed = True
    if not removed:
        target = os.path.abspath(os.path.join(SKILLS_DIR, nm))
        if security.validate_within_dir(target, SKILLS_DIR) and os.path.isdir(target):
            shutil.rmtree(target)
            removed = True
    skills_catalog.invalidate_cache()
    return {"ok": True, "name": nm, "removed": removed}
