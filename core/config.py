"""MiniYuxi 全局配置：全部走环境变量，无 Key 时自动降级到离线模式。

设计原则（对应本机硬约束：无 Docker / 无 VT-x / 7.8GB 内存 / 纯原生进程）：
- 零外部服务依赖：数据库 SQLite，向量库 sqlite-vec（进程内扩展），全文检索 FTS5。
- 模型侧可插拔：有 API Key 走云端 OpenAI 兼容接口；无 Key 自动降级为离线抽取式兜底。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ---------- 存储 ----------
DB_PATH = os.getenv("MINIYUXI_DB", str(DATA_DIR / "miniyuxi.db"))

# ---------- 模型（OpenAI 兼容）----------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# 默认用 72B：2026-09-10 实测，7B 在"天数/金额"上存在数字幻觉（把 10天 答成 11天、
# 500元 答成 55元），即使 temperature=0.1 且提示词强制照抄原文仍会错；72B 三题全对。
# ⚠️ HR 制度场景数字错即事故，准确性优先于成本；可用 LLM_MODEL 覆盖（改模型不影响已建库）。
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
# 制度问答要求"照抄原文"，温度越低越不易改写数字；可用 LLM_TEMPERATURE 覆盖
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# 统一大模型网关（T1）：多供应商注册表。抄 OpenClaw /v1/models 思路，运行时由 gateway.list_models() 暴露。
# 网关只做路由/超时 fallback，不新增外部依赖；新增供应商只需在此追加。
LLM_PROVIDERS = [
    {"id": "siliconflow", "name": "SiliconFlow", "base_url": LLM_BASE_URL,
     "api_key": LLM_API_KEY, "model": LLM_MODEL, "kind": "openai"},
    {"id": "offline", "name": "离线兜底（抽取式）", "base_url": "", "api_key": "", "model": "offline", "kind": "offline"},
]

EMB_BASE_URL = os.getenv("EMB_BASE_URL", LLM_BASE_URL)
EMB_API_KEY = os.getenv("EMB_API_KEY", LLM_API_KEY)
EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-m3")
# ⚠️ 向量维度一经建库不可更改（更换需重建 vec 表并全量重嵌）
EMB_DIM = int(os.getenv("EMB_DIM", "1024"))

LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

# ---------- 联网搜索后端（T2）----------
# 默认走企业级搜索（火山引擎/豆包，中文更准），失败自动回退 Bing → DuckDuckGo。
# 设为 bing / duckduckgo 可关闭企业后端；密钥复用 DOUBAO_API_KEY(+DOUBAO_BASE_URL) 或
# 显式 WEB_SEARCH_API_URL+WEB_SEARCH_API_KEY。
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "doubao").lower()

# ---------- 安全 ----------
# 生产部署务必通过环境变量覆盖，禁止使用默认值
SECRET_KEY = os.getenv("MINIYUXI_SECRET", "dev-only-change-me-please-32bytes")
TOKEN_TTL = int(os.getenv("MINIYUXI_TOKEN_TTL", "12")) * 3600

# ---------- 服务 ----------
HOST = os.getenv("MINIYUXI_HOST", "127.0.0.1")
PORT = int(os.getenv("MINIYUXI_PORT", "8801"))

# ---------- 角色权限矩阵（RBAC）----------
# 对象: 动作
ROLE_PERMS = {
    "admin":  {"kb.read", "kb.write", "kb.delete", "chat", "agent.run", "tenant.manage", "user.manage", "audit.read",
               "hrm.read", "hrm.write", "hrm.delete", "hrm.flow", "hrm.admin"},
    "editor": {"kb.read", "kb.write", "chat", "agent.run",
               "hrm.read", "hrm.write", "hrm.flow"},
    "viewer": {"kb.read", "chat", "hrm.read"},
}


def llm_enabled() -> bool:
    """是否配置了真实大模型（否则走离线兜底）。"""
    return bool(LLM_API_KEY)


def emb_enabled() -> bool:
    """是否配置了真实 Embedding（否则仅走 BM25 全文检索）。"""
    return bool(EMB_API_KEY)
