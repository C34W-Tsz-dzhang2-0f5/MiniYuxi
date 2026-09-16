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
