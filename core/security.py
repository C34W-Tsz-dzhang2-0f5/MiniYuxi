"""安全工具：敏感字段脱敏。

供劳动关系/薪酬等接口在对外展示时对身份证、银行卡、手机号、邮箱做掩码，
避免明文泄露。入库仍按业务需要存明文（受 .gitignore 与权限约束），
展示层按需调用本模块脱敏——遵循 hr-ai-workbench「敏感字段明文存储但 UI 默认掩码」思路。
"""
import re


def mask_phone(phone: str) -> str:
    """手机号中间四位打码：138****8888。"""
    p = (phone or "").strip()
    m = re.search(r"(\d{3})\d{4}(\d{4})", p)
    return m.group(1) + "****" + m.group(2) if m else (p[:3] + "****" if len(p) >= 7 else p)


def mask_id_card(idc: str) -> str:
    """身份证保留前 4 后 2：4403**********12。"""
    s = (idc or "").strip()
    if len(s) >= 8:
        return s[:4] + "*" * (len(s) - 6) + s[-2:]
    return "*" * len(s) if s else ""


def mask_bank(bank: str) -> str:
    """银行卡保留后 4 位：****1234。"""
    s = (bank or "").strip()
    if len(s) >= 4:
        return "*" * (len(s) - 4) + s[-4:]
    return "*" * len(s) if s else ""


def mask_email(email: str) -> str:
    """邮箱名保留首字符：a***@example.com。"""
    e = (email or "").strip()
    if "@" in e:
        name, dom = e.split("@", 1)
        if len(name) <= 1:
            return "*@" + dom
        return name[0] + "*" * (len(name) - 1) + "@" + dom
    return e


def mask_record(rec: dict, fields: dict) -> dict:
    """批量脱敏：fields = {字段名: 掩码函数}。返回新字典，不破坏原值。"""
    out = dict(rec)
    for f, fn in fields.items():
        if f in out and out[f]:
            out[f] = fn(str(out[f]))
    return out


# ===========================================================================
# 执行层安全分层（对应 Hermes 源码解读十一：动手之前先有边界）
# 原则：可恢复风险 → 走审批；不可恢复风险 → 系统硬阻断（hardline block）。
# 这些函数被工具执行、Cron 脚本、Coding Agent 复用，属系统底线，fail-closed。
# ===========================================================================

# 不可恢复灾难命令：无论 yolo/审批模式如何，一律无条件阻断。
_COMMAND_BLOCKLIST = [
    re.compile(r"\brm\s+(-rf?|--recursive)\s+/", re.I),       # rm -rf /
    re.compile(r"\brm\s+-rf?\s+--no-preserve-root", re.I),
    re.compile(r"\bmkfs(\.\w+)?\b", re.I),                     # 格式化文件系统
    re.compile(r"/dev/sd[a-z]"),                               # 裸设备直接写入
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.I),  # 关机/重启
    re.compile(r":\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}", re.S),  # fork bomb
    re.compile(r"\bdd\b\s+if=/dev/(zero|random|urandom)"),     # 全盘擦写
    re.compile(r"\b(chmod|chown)\s+(-R\s+)?(777|0)\b", re.I),  # 权限归零
]


def hardline_block(cmd: str) -> bool:
    """不可恢复灾难命令检测。返回 True=必须无条件拦截（yolo 也不能绕过）。"""
    s = (cmd or "").strip()
    if not s:
        return False
    return any(p.search(s) for p in _COMMAND_BLOCKLIST)


# 中危命令：需走审批层（而非无条件阻断）。
_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf?\b", re.I),                        # rm -rf（非根也危险）
    re.compile(r"\bsudo\b", re.I),                             # 提权
    re.compile(r">\s*/dev/sd", re.I),                          # 直写设备
    re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sh|bash)", re.I),   # curl/wget | sh 远程执行
    re.compile(r">\s*/etc/(passwd|shadow|hosts)", re.I),       # 改写系统认证文件
]


def is_dangerous_command(cmd: str) -> bool:
    """智能危险命令检测（应交给审批层处理，非无条件阻断）。"""
    s = (cmd or "").strip()
    if not s:
        return False
    return any(p.search(s) for p in _DANGEROUS_PATTERNS)


def validate_within_dir(path: str, root: str) -> bool:
    """路径越权校验：path 解析后必须仍在 root 目录内（防 ../ 穿越、绝对路径逃逸）。

    返回 True=安全。覆盖 symlink/..  /home 展开/绝对路径。"""
    import os

    try:
        root_abs = os.path.abspath(os.path.expanduser(root))
        path_abs = os.path.abspath(os.path.expanduser(path))
        return os.path.commonpath([root_abs, path_abs]) == root_abs
    except Exception:
        return False


# 脚本执行前禁止触碰的敏感路径（与 coding_agent 黑名单互补，覆盖文件写侧）。
_SENSITIVE_PATH_HINTS = (
    "c:\\windows", "/etc/passwd", "/etc/shadow", "/boot", "/sys/",
    "/proc/", "/root/", "id_rsa", ".env", "config.yaml",
)


def validate_script(script: str) -> tuple:
    """脚本/命令执行前安全校验。返回 (ok: bool, reason: str)。

    - 命中不可恢复黑名单 → 拒绝；
    - 试图写/读系统敏感路径 → 拒绝；
    - 其余 → 放行（由上层审批层处理中危命令）。"""
    s = script or ""
    if hardline_block(s):
        return False, "命中不可恢复命令黑名单（hardline block），系统已无条件拦截"
    low = s.lower()
    for bad in _SENSITIVE_PATH_HINTS:
        if bad in low:
            return False, f"脚本试图访问敏感路径：{bad}"
    return True, ""
