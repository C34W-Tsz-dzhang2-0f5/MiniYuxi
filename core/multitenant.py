"""多租户隔离 + 合规架构骨架（深度构造·项5 技术控制层）。

- 租户策略表（tenant_policies）：配额、数据驻留、MLPS 等级、CMK 开关/密钥标识；
- enforce：按租户策略做配额/权限前置校验，越界即拒（多租户隔离的强制闸门）；
- readiness：结构化"合规就绪度"评估——明确区分【代码已具备】与【需外部机构/基础设施】，
  不伪造任何认证结论（等保三级/ISO 是证书，不是代码能出的）。

说明：真实"多租户 SaaS + 对外高并发"还需：无状态水平扩展层 + 托管库/读写分离 +
负载均衡 + 租户路由网关。本模块交付数据隔离闸门与合规就绪度账本，HA 骨架见 readiness。
"""
from . import db


def init(conn=None):
    c = conn or db.connect()
    c.execute("""CREATE TABLE IF NOT EXISTS tenant_policies(
        tenant_id TEXT PRIMARY KEY, mlps_level TEXT NOT NULL DEFAULT 'unset',
        data_residency TEXT NOT NULL DEFAULT 'cn-guangdong',
        quota_daily_calls INTEGER NOT NULL DEFAULT 1000, quota_kb_mb INTEGER NOT NULL DEFAULT 100,
        cmk_enabled INTEGER NOT NULL DEFAULT 0, cmk_key_id TEXT,
        created_at TEXT DEFAULT (datetime('now')))""")
    c.commit()


def set_policy(tenant_id, policy: dict, conn=None):
    c = conn or db.connect()
    c.execute(
        """INSERT OR REPLACE INTO tenant_policies(tenant_id,mlps_level,data_residency,
           quota_daily_calls,quota_kb_mb,cmk_enabled,cmk_key_id)
           VALUES(?,?,?,?,?,?,?)""",
        (tenant_id, policy.get("mlps_level", "unset"), policy.get("data_residency", "cn-guangdong"),
         int(policy.get("quota_daily_calls", 1000)), int(policy.get("quota_kb_mb", 100)),
         1 if policy.get("cmk_enabled") else 0, policy.get("cmk_key_id") or ""),
    )
    c.commit()


def get_policy(tenant_id, conn=None):
    c = conn or db.connect()
    row = c.execute("SELECT * FROM tenant_policies WHERE tenant_id=?", (tenant_id,)).fetchone()
    return dict(row) if row else None


def enforce(tenant_id, action, usage_counts=None, conn=None):
    """多租户强制闸门。usage_counts: {daily_calls, kb_mb}。返回 {allow, reason}。"""
    c = conn or db.connect()
    p = get_policy(tenant_id, c)
    if p is None:
        return {"allow": True, "reason": "no_policy", "policy": None}
    uc = usage_counts or {}
    if uc.get("daily_calls", 0) >= p["quota_daily_calls"]:
        return {"allow": False, "reason": "quota_daily_calls_exceeded",
                "policy": p["quota_daily_calls"]}
    if uc.get("kb_mb", 0) >= p["quota_kb_mb"]:
        return {"allow": False, "reason": "quota_kb_mb_exceeded", "policy": p["quota_kb_mb"]}
    return {"allow": True, "reason": "ok", "policy": p}


def readiness(conn=None):
    """合规/HA 就绪度账本：code_done=代码已有控制点；external=需外部机构/基础设施。"""
    return {
        "mlps_level3": {
            "code_done": [
                "RBAC 角色权限矩阵（admin/editor/viewer）",
                "统一身份鉴别（密码哈希+salt，token TTL）",
                "结构化 SOC 审计 + 哈希防篡改链（soc_audit）",
                "租户数据隔离闸门（enforce 配额/驻留）",
                "敏感动作 HITL 审批卡（approval 模块）",
            ],
            "external_required": [
                "测评机构现场评估 + 公安/网信备案（证书由机构出具，代码交付不了）",
                "安全边界/网络区域划分（需拓扑与设备）",
                "入侵检测/日志集中审计设备（SOC 硬件/服务）",
                "等保三级测评报告与年度复测",
            ],
        },
        "iso_27001": {
            "code_done": ["审计留痕", "访问控制", "密钥管理开关（cmk_enabled）"],
            "external_required": ["认证机构审核 + 证书", "ISMS 制度文件与内审", "管理层承诺与风险处置"],
        },
        "cmk": {
            "code_done": ["tenant_policies.cmk_enabled/cmk_key_id 字段与开关", "落盘加密钩子接口预留"],
            "external_required": ["对接 KMS/HSM 托管密钥（云厂商 KMS 或自建 HSM）", "密钥轮换流程"],
        },
        "saas_ha": {
            "code_done": ["无状态接口设计（请求级 db.connect）", "租户路由按 tenant_id", "KV/provider 可持久化"],
            "external_required": [
                "负载均衡 + 多无状态实例（需容器/多机，本机单进程不满足）",
                "托管数据库/读写分离（SQLite 单文件不满足高并发写）",
                "对象存储/向量库外置（sqlite-vec 进程内不满足）",
            ],
        },
    }
