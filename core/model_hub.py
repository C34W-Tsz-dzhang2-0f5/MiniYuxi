"""多模型中枢（Model Hub）：统一接入 / 手动切换 / 自动路由 / 并行对比 / 结果合并。

设计目标（对标 WorkBuddy 的多模型产品形态，落地到 MiniYuxi 技术栈）：
1. **一处接入，处处可用**：所有供应商走 OpenAI 兼容协议（/chat/completions），
   新增厂商只需在 PROVIDERS / MODELS 追加一条，无需改动调用方。
2. **手动切换**：前端可显式指定 model_id（形如 `siliconflow:Qwen/Qwen2.5-72B-Instruct`）。
3. **自动调度**：先规则判任务类型 → 再按策略档位（经济/均衡/强力）在「已配置 Key 的可用模型」中打分选优。
4. **并行对比**：ThreadPoolExecutor 并发打多个模型，返回结构化结果（延迟/token/成本/正文）。
5. **结果合并**：用一个裁判模型把多路答案汇成一份带「共识 + 分歧」的最终答复。
6. **可观测**：每次调用落 model_tasks 表 + usage 埋点，右侧「模型任务」可回看。

约束：不新增外部依赖（复用 requests）；不改动三指纹文件；建表一律 CREATE TABLE IF NOT EXISTS。
注意：db.connect() 返回线程级单例连接，**本模块禁止 close 它**（否则污染后续请求）。
"""
import json
import os
import time
import uuid
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, db, usage

MAX_WORKERS = 6
DEFAULT_TIMEOUT = 60

# =====================================================================
#  1. 供应商注册表（base_url / key 环境变量）
# =====================================================================
PROVIDERS = [
    {"id": "siliconflow", "name": "硅基流动 SiliconFlow", "base_url": "https://api.siliconflow.cn/v1",
     "env_key": "LLM_API_KEY", "default_base": config.LLM_BASE_URL, "home": "https://cloud.siliconflow.cn"},
    {"id": "deepseek", "name": "DeepSeek 官方", "base_url": "https://api.deepseek.com/v1",
     "env_key": "DEEPSEEK_API_KEY", "home": "https://platform.deepseek.com"},
    {"id": "mimo", "name": "小米 MiMo", "base_url": "https://api.xiaomimimo.com/v1",
     "env_key": "MIMO_API_KEY", "home": "https://platform.xiaomimimo.com"},
    {"id": "ark", "name": "火山方舟 Ark", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "env_key": "ARK_API_KEY", "home": "https://console.volcengine.com/ark"},
    {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "env_key": "ZHIPU_API_KEY", "home": "https://open.bigmodel.cn"},
    {"id": "custom", "name": "自定义（OpenAI 兼容）", "base_url": os.getenv("CUSTOM_BASE_URL", ""),
     "env_key": "CUSTOM_API_KEY", "home": ""},
    {"id": "offline", "name": "离线兜底（无需 Key）", "base_url": "", "env_key": "", "home": ""},
]
_PROV = {p["id"]: p for p in PROVIDERS}

# =====================================================================
#  2. 模型目录
#     tier: 1=轻量(便宜快) 2=均衡 3=旗舰(强但贵)
#     price: 人民币元 / 百万 tokens（与 usage.price 同量纲，仅用于排序与估算）
#     caps: 能力标签 general/reasoning/code/long/cheap/fast/agent/vision/zh
# =====================================================================
MODELS = [
    # ---- 硅基流动 ----
    dict(id="siliconflow:Qwen/Qwen2.5-72B-Instruct", provider="siliconflow", model="Qwen/Qwen2.5-72B-Instruct",
         name="Qwen2.5-72B", tier=3, ctx=32, price_in=4.13, price_out=4.13,
         caps=["general", "zh", "long"], note="中文通用强，制度问答实测零数字幻觉"),
    dict(id="siliconflow:Qwen/Qwen2.5-7B-Instruct", provider="siliconflow", model="Qwen/Qwen2.5-7B-Instruct",
         name="Qwen2.5-7B", tier=1, ctx=32, price_in=0.70, price_out=0.70,
         caps=["general", "zh", "cheap", "fast"], note="便宜快，简单问答/草稿"),
    dict(id="siliconflow:deepseek-ai/DeepSeek-V3", provider="siliconflow", model="deepseek-ai/DeepSeek-V3",
         name="DeepSeek-V3", tier=3, ctx=64, price_in=2.0, price_out=8.0,
         caps=["general", "code", "reasoning", "zh"], note="代码与通用均衡"),
    dict(id="siliconflow:deepseek-ai/DeepSeek-R1", provider="siliconflow", model="deepseek-ai/DeepSeek-R1",
         name="DeepSeek-R1", tier=3, ctx=64, price_in=4.0, price_out=16.0,
         caps=["reasoning", "code"], note="深度推理，慢而准"),
    # 注：siliconflow:THUDM/glm-4-9b-chat 在硅基流动已禁用(403 Model disabled)，已从目录移除，
    # 避免自动路由误选导致失败；智谱 GLM 系列请走 zhipu provider（需配 ZHIPU_API_KEY）。

    # ---- DeepSeek 官方 ----
    dict(id="deepseek:deepseek-chat", provider="deepseek", model="deepseek-chat",
         name="DeepSeek-V3 官方", tier=3, ctx=64, price_in=2.0, price_out=8.0,
         caps=["general", "code", "zh"], note="官方直连，稳定低延时"),
    dict(id="deepseek:deepseek-reasoner", provider="deepseek", model="deepseek-reasoner",
         name="DeepSeek-R1 官方", tier=3, ctx=64, price_in=4.0, price_out=16.0,
         caps=["reasoning", "code"], note="官方推理模型，带思维链"),

    # ---- 小米 MiMo ----
    dict(id="mimo:mimo-v2.5-pro", provider="mimo", model="mimo-v2.5-pro",
         name="MiMo-v2.5-Pro", tier=3, ctx=1024, price_in=3.0, price_out=12.0,
         caps=["agent", "reasoning", "code", "long", "zh"], note="旗舰 Agent 基座，1M 上下文"),
    dict(id="mimo:mimo-v2.5", provider="mimo", model="mimo-v2.5",
         name="MiMo-v2.5", tier=2, ctx=1024, price_in=1.5, price_out=6.0,
         caps=["general", "vision", "long", "zh"], note="全模态感知"),
    dict(id="mimo:mimo-v2-flash", provider="mimo", model="mimo-v2-flash",
         name="MiMo-v2-Flash", tier=1, ctx=256, price_in=0.5, price_out=2.0,
         caps=["general", "fast", "cheap", "zh"], note="极速，适合高频短任务"),

    # ---- 火山方舟 ----
    dict(id="ark:doubao-seed-2-1-pro-260628", provider="ark", model="doubao-seed-2-1-pro-260628",
         name="豆包 Seed 2.1 Pro", tier=3, ctx=256, price_in=4.0, price_out=16.0,
         caps=["agent", "reasoning", "code", "zh"], note="方舟旗舰，支持深度思考开关"),
    dict(id="ark:doubao-seed-1-6-250615", provider="ark", model="doubao-seed-1-6-250615",
         name="豆包 Seed 1.6", tier=2, ctx=256, price_in=0.8, price_out=8.0,
         caps=["general", "zh"], note="通用主力，性价比好"),
    dict(id="ark:doubao-seed-1-6-lite-250615", provider="ark", model="doubao-seed-1-6-lite-250615",
         name="豆包 Seed 1.6 Lite", tier=1, ctx=256, price_in=0.3, price_out=2.0,
         caps=["general", "cheap", "fast", "zh"], note="轻量高频"),

    # ---- 智谱 ----
    dict(id="zhipu:glm-4.6", provider="zhipu", model="glm-4.6",
         name="GLM-4.6", tier=3, ctx=200, price_in=4.0, price_out=12.0,
         caps=["agent", "code", "reasoning", "zh"], note="智谱旗舰，编码强"),
    dict(id="zhipu:glm-4.5-air", provider="zhipu", model="glm-4.5-air",
         name="GLM-4.5-Air", tier=2, ctx=128, price_in=0.8, price_out=4.0,
         caps=["general", "zh"], note="轻量主力"),
    dict(id="zhipu:glm-4.5-flash", provider="zhipu", model="glm-4.5-flash",
         name="GLM-4.5-Flash", tier=1, ctx=128, price_in=0.1, price_out=0.6,
         caps=["general", "cheap", "fast", "zh"], note="免费档/极低价"),

    # ---- 离线兜底 ----
    dict(id="offline:offline", provider="offline", model="offline",
         name="离线兜底", tier=0, ctx=0, price_in=0.0, price_out=0.0,
         caps=["cheap"], note="无 Key 时的抽取式兜底，不调用外部"),
]
_MODEL = {m["id"]: m for m in MODELS}

# =====================================================================
#  3. 任务类型 → 能力偏好（自动路由的"任务画像"）
# =====================================================================
TASK_PROFILES = {
    "code":      {"name": "代码开发", "caps": ["code", "reasoning", "general"], "tier": 3},
    "reasoning": {"name": "深度推理", "caps": ["reasoning", "agent", "general"], "tier": 3},
    "hr-policy": {"name": "制度/法务", "caps": ["zh", "long", "general"], "tier": 3},
    "summary":   {"name": "总结提炼", "caps": ["long", "general", "cheap"], "tier": 2},
    "translate": {"name": "翻译润色", "caps": ["cheap", "fast", "general"], "tier": 1},
    "creative":  {"name": "创意文案", "caps": ["general", "zh"], "tier": 2},
    "agent":     {"name": "任务编排", "caps": ["agent", "reasoning", "general"], "tier": 3},
    "general":   {"name": "通用问答", "caps": ["general", "zh"], "tier": 2},
}

# 规则化任务识别（零成本、可解释；不额外消耗 token）
TASK_RULES = [
    ("code", ["代码", "函数", "python", "python3", "java", "sql", "bug", "报错", "重构", "编程",
              "脚本", "接口", "debug", "写个", "实现", "算法", "前端", "后端", "class ", "def "]),
    ("reasoning", ["推导", "证明", "推理", "逻辑", "为什么", "原因分析", "根因", "计算", "对比分析",
                   "决策", "评估", "论证", "博弈"]),
    # agent 排在 hr-policy 之前：含「规划/排期/拆解」的请求优先视为任务编排而非制度问答
    ("agent", ["规划", "排期", "拆解", "执行方案", "分步", "工作流", "sop", "项目计划", "路线图"]),
    ("hr-policy", ["劳动法", "仲裁", "工伤", "年假", "加班", "社保", "公积金", "招聘", "绩效", "离职",
                   "赔偿", "劳动合同", "员工手册", "试用期", "竞业", "考勤", "薪酬", "调岗", "裁员"]),
    ("summary", ["总结", "摘要", "概括", "提炼", "归纳", "要点", "纪要", "复盘"]),
    ("translate", ["翻译", "译成", "英文", "english", "中译英", "英译中", "润色"]),
    ("creative", ["文案", "宣传", "标题", "海报", "创意", "故事", "slogan", "推文", "公众号"]),
]

STRATEGIES = {
    "economy":  {"name": "经济", "desc": "优先便宜快，适合高频短任务"},
    "balanced": {"name": "均衡", "desc": "质量与成本折中，默认档"},
    "premium":  {"name": "强力", "desc": "优先旗舰，适合高价值决策"},
}


# =====================================================================
#  4. 初始化与运行时配置（Key 可在界面配置，落库优先于环境变量）
# =====================================================================
def init(conn=None) -> None:
    c = conn or db.connect()
    c.execute("""CREATE TABLE IF NOT EXISTS model_providers(
        id TEXT PRIMARY KEY, api_key TEXT NOT NULL DEFAULT '',
        base_url TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS model_tasks(
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default',
        kind TEXT NOT NULL DEFAULT 'chat', task_type TEXT, strategy TEXT,
        message TEXT, model_ids TEXT, model_used TEXT, ok INTEGER NOT NULL DEFAULT 0,
        latency_ms INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
        tokens INTEGER NOT NULL DEFAULT 0, result TEXT,
        created_at TEXT DEFAULT (datetime('now')))""")
    c.commit()


def _conf(provider_id: str) -> dict:
    """返回 {base_url, api_key, configured, enabled}：库配置 > 环境变量 > 默认值。"""
    p = _PROV.get(provider_id, {})
    key, base, enabled = "", p.get("base_url", ""), 1
    try:
        row = db.connect().execute(
            "SELECT api_key, base_url, enabled FROM model_providers WHERE id=?", (provider_id,)
        ).fetchone()
        if row:
            key = row["api_key"] or ""
            base = row["base_url"] or base
            enabled = int(row["enabled"])
    except Exception:
        pass
    if not key and p.get("env_key"):
        key = os.getenv(p["env_key"], "")
    if not base and provider_id == "siliconflow":
        base = config.LLM_BASE_URL
    # 硅基流动未显式配置时，沿用全局 LLM_API_KEY（向后兼容既有部署）
    if provider_id == "siliconflow" and not key:
        key = config.LLM_API_KEY
    if provider_id == "custom":
        base = base or os.getenv("CUSTOM_BASE_URL", "")
        if not key:
            key = os.getenv("CUSTOM_API_KEY", "")
    return {"base_url": base, "api_key": key, "configured": bool(key), "enabled": enabled}


def set_provider(provider_id: str, api_key: str = "", base_url: str = "", enabled: bool = True):
    c = db.connect()
    # 若未传 api_key（空串），保留库中已有 Key，避免误清空已配置供应商
    if not api_key:
        try:
            row = c.execute("SELECT api_key FROM model_providers WHERE id=?", (provider_id,)).fetchone()
            if row:
                api_key = row["api_key"] or ""
        except Exception:
            pass
    c.execute(
        "INSERT OR REPLACE INTO model_providers(id, api_key, base_url, enabled, updated_at) "
        "VALUES(?,?,?,?,datetime('now'))",
        (provider_id, api_key, base_url, 1 if enabled else 0),
    )
    c.commit()
    return provider_id


def catalog() -> dict:
    """返回模型目录 + 供应商状态，供前端渲染模型中心。"""
    provs = []
    for p in PROVIDERS:
        cf = _conf(p["id"])
        n_ok = 0
        if p["id"] != "offline":
            n_ok = sum(1 for m in MODELS
                       if m["provider"] == p["id"] and _conf(p["id"])["configured"])
        provs.append({
            "id": p["id"], "name": p["name"], "base_url": cf["base_url"],
            "configured": cf["configured"] or p["id"] == "offline",
            "enabled": bool(cf["enabled"]), "home": p.get("home", ""),
            "models_total": sum(1 for m in MODELS if m["provider"] == p["id"]),
            "models_ready": n_ok,
        })
    models = []
    for m in MODELS:
        cf = _conf(m["provider"])
        ok = (m["provider"] == "offline") or (cf["configured"] and cf["enabled"])
        models.append({**m, "available": ok,
                       "status": "ready" if ok else ("no_key" if not cf["configured"] else "disabled")})
    return {"providers": provs, "models": models,
            "strategies": STRATEGIES, "task_types": TASK_PROFILES,
            "default_model": default_model_id()}


def default_model_id() -> str:
    for mid in ("siliconflow:Qwen/Qwen2.5-72B-Instruct", "siliconflow:Qwen/Qwen2.5-7B-Instruct"):
        if _MODEL[mid]["provider"] == "offline" or _conf(_MODEL[mid]["provider"])["configured"]:
            return mid
    return "offline:offline"


# =====================================================================
#  5. 任务识别与自动路由
# =====================================================================
def classify(message: str) -> dict:
    """规则化任务识别：返回 {task_type, name, matched, confidence}。"""
    t = (message or "").lower()
    best, hits = "general", 0
    for ttype, kws in TASK_RULES:
        n = sum(1 for k in kws if k in t)
        if n > hits:
            best, hits = ttype, n
    conf = min(1.0, 0.4 + 0.3 * hits) if hits else 0.4
    return {"task_type": best, "name": TASK_PROFILES[best]["name"],
            "matched": hits, "confidence": round(conf, 2)}


def _score(m: dict, profile: dict, strategy: str) -> float:
    """三档策略打分：能力匹配（主）+ 档位倾向 + 成本惩罚 + 长上下文加分。

    权重经过实测校准：economy 下便宜模型能赢旗舰，premium 下旗舰能赢便宜模型，
    balanced 下贴近任务推荐档位者胜出。
    """
    s = 0.0
    caps = profile["caps"]
    for i, cap in enumerate(caps):                      # 越靠前的能力权重越高
        if cap in m["caps"]:
            s += (len(caps) - i) * 1.5
    if strategy == "economy":
        s += (3 - m["tier"]) * 3.5                      # 越轻量越加分
        s -= (m["price_in"] + m["price_out"]) / 4.0     # 成本权重翻倍
    elif strategy == "premium":
        s += m["tier"] * 3.5                            # 越旗舰越加分
        s -= (m["price_in"] + m["price_out"]) / 16.0    # 成本几乎不计
    else:                                                # balanced：贴近任务推荐档位
        s += (3 - abs(m["tier"] - profile["tier"])) * 2.0
        s -= (m["price_in"] + m["price_out"]) / 8.0
    s += min(m["ctx"], 256) / 512.0                      # 长上下文轻微加分
    return s


def route(message: str, strategy: str = "balanced") -> dict:
    """自动路由：判任务类型 → 在可用模型中打分选优。返回含理由，便于前端解释。"""
    cls = classify(message)
    profile = TASK_PROFILES[cls["task_type"]]
    pool = [m for m in MODELS if m["provider"] != "offline" and _conf(m["provider"])["configured"]]
    if not pool:
        return {**cls, "strategy": strategy, "model_id": "offline:offline",
                "model_name": "离线兜底", "provider": "offline",
                "reason": "未检测到任何已配置 Key 的模型，走离线兜底", "candidates": []}
    ranked = sorted(pool, key=lambda m: _score(m, profile, strategy), reverse=True)
    top = ranked[0]
    return {
        **cls, "strategy": strategy,
        "model_id": top["id"], "model_name": top["name"], "provider": top["provider"],
        "reason": f"识别为「{profile['name']}」，策略「{STRATEGIES[strategy]['name']}」，"
                  f"在 {len(pool)} 个可用模型中 {top['name']} 得分最高（能力：{'/'.join(top['caps'][:3])}）",
        "candidates": [{"id": m["id"], "name": m["name"], "provider": m["provider"],
                        "score": round(_score(m, profile, strategy), 2)} for m in ranked[:5]],
    }


# =====================================================================
#  6. 单模型调用
# =====================================================================
def _messages(system, prompt, history):
    msgs = [{"role": "system", "content": system or ""}]
    for h in (history or [])[-10:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:2000]})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def _price(model_id: str):
    m = _MODEL.get(model_id)
    if m:
        return m["price_in"], m["price_out"]
    try:
        return usage.price(model_id)
    except Exception:
        return 0.0, 0.0


def chat(model_id: str, system: str, prompt: str, history=None, tenant_id: str = "default",
         temperature: float | None = None) -> dict:
    """调用单个模型。返回 {ok,text,err,model_id,model_name,provider,latency_ms,tokens,cost,usage}。"""
    m = _MODEL.get(model_id)
    if m is None:                       # 未在目录中的裸模型名 → 交给默认供应商
        m = {"id": model_id, "provider": "siliconflow", "model": model_id,
             "name": model_id, "caps": [], "tier": 2, "ctx": 32, "price_in": 0.0, "price_out": 0.0}
    if m["provider"] == "offline":
        usage.record(tenant_id, "llm", "offline", prompt_text=prompt, completion_text="")
        return {"ok": False, "text": "", "err": "offline", "model_id": "offline:offline",
                "model_name": "离线兜底", "provider": "offline", "latency_ms": 0,
                "tokens": 0, "cost": 0.0, "usage": None}

    cf = _conf(m["provider"])
    if not cf["api_key"]:
        return {"ok": False, "text": "", "err": "no_key", "model_id": m["id"],
                "model_name": m["name"], "provider": m["provider"], "latency_ms": 0,
                "tokens": 0, "cost": 0.0, "usage": None}

    payload = {
        "model": m["model"],
        "messages": _messages(system, prompt, history),
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
    }
    t0 = time.time()
    text, err, u = "", "", None
    try:
        resp = requests.post(
            f"{cf['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {cf['api_key']}", "Content-Type": "application/json"},
            json=payload, timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code >= 400:
            err = f"HTTP {resp.status_code}: {(resp.text or '')[:160]}"
        else:
            js = resp.json()
            text = (js.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            u = js.get("usage")
    except requests.exceptions.Timeout:
        err = "timeout"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
    ms = int((time.time() - t0) * 1000)

    pt = (u or {}).get("prompt_tokens") or 0
    ct = (u or {}).get("completion_tokens") or 0
    pin, pout = _price(m["id"])
    cost = round(pt / 1e6 * pin + ct / 1e6 * pout, 6)
    usage.record(tenant_id, "llm", f"{m['provider']}:{m['model']}", prompt_text=prompt,
                 completion_text=text, prompt_tokens=pt or None, completion_tokens=ct or None,
                 cost=cost or None)
    return {"ok": bool(text), "text": text, "err": err, "model_id": m["id"],
            "model_name": m["name"], "provider": m["provider"], "latency_ms": ms,
            "tokens": (pt + ct), "cost": cost, "usage": u}


# =====================================================================
#  7. 并行对比
# =====================================================================
def compare(model_ids: list[str], system: str, prompt: str, history=None,
            tenant_id: str = "default") -> list[dict]:
    """并发调用多个模型，返回按输入顺序的结果列表。"""
    ids = [i for i in (model_ids or []) if i][:MAX_WORKERS]
    if not ids:
        return []
    out = [None] * len(ids)
    with ThreadPoolExecutor(max_workers=min(len(ids), MAX_WORKERS)) as ex:
        futs = {ex.submit(chat, mid, system, prompt, history, tenant_id): i
                for i, mid in enumerate(ids)}
        for f in as_completed(futs):
            i = futs[f]
            try:
                out[i] = f.result()
            except Exception as e:
                out[i] = {"ok": False, "text": "", "err": f"{type(e).__name__}: {e}"[:200],
                          "model_id": ids[i], "model_name": ids[i], "provider": "",
                          "latency_ms": 0, "tokens": 0, "cost": 0.0, "usage": None}
    return [r for r in out if r]


MERGE_SYSTEM = (
    "你是多模型结果仲裁员。下面是同一个问题的多个模型答案。"
    "请输出三部分：\n"
    "## 共识\n各模型一致认可的事实与结论（去重合并）。\n"
    "## 分歧\n各模型不一致之处，逐条标注是哪个模型的观点。\n"
    "## 最终建议\n给出你综合后的唯一可执行结论；若某模型明显错误请直接指出。\n"
    "要求：中文、结构化、不编造；只基于给定答案，不引入外部知识。"
)


def merge(question: str, results: list[dict], judge_model_id: str | None = None,
          tenant_id: str = "default") -> dict:
    """用一个裁判模型合并多路答案。裁判默认取「可用且 tier 最高」的模型。"""
    blocks = []
    for r in results:
        if not r.get("text"):
            continue
        blocks.append(f"### 模型：{r.get('model_name')}（{r.get('provider')}，{r.get('latency_ms')}ms）\n{r['text']}")
    if not blocks:
        return {"ok": False, "text": "", "err": "no_results", "judge": None}
    judge = judge_model_id
    if not judge:
        pool = [m for m in MODELS if m["provider"] != "offline" and _conf(m["provider"])["configured"]]
        if not pool:
            return {"ok": False, "text": "", "err": "no_judge", "judge": None}
        judge = sorted(pool, key=lambda m: (m["tier"], -m["price_out"]), reverse=True)[0]["id"]
    prompt = f"问题：{question}\n\n" + "\n\n".join(blocks)
    r = chat(judge, MERGE_SYSTEM, prompt, tenant_id=tenant_id)
    return {"ok": r.get("ok"), "text": r.get("text", ""), "err": r.get("err", ""),
            "judge": r.get("model_name"), "judge_id": r.get("model_id"),
            "latency_ms": r.get("latency_ms", 0), "cost": r.get("cost", 0)}


# =====================================================================
#  8. 任务记录（会话与任务管理区的数据源）
# =====================================================================
def record_task(tenant_id: str, kind: str, message: str, task_type: str, strategy: str,
                model_ids: list, model_used: str, ok: bool, latency_ms: int,
                cost: float, tokens: int, result: str = "") -> str:
    tid = uuid.uuid4().hex[:12]
    db.connect().execute(
        "INSERT INTO model_tasks(id,tenant_id,kind,task_type,strategy,message,model_ids,"
        "model_used,ok,latency_ms,cost,tokens,result) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, tenant_id, kind, task_type, strategy, (message or "")[:500],
         json.dumps(model_ids or [], ensure_ascii=False), model_used,
         1 if ok else 0, int(latency_ms), float(cost), int(tokens), (result or "")[:8000]),
    )
    db.connect().commit()
    return tid


def list_tasks(tenant_id: str = "default", limit: int = 30) -> list[dict]:
    rows = db.connect().execute(
        "SELECT * FROM model_tasks WHERE tenant_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (tenant_id, int(limit)),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["model_ids"] = json.loads(d.get("model_ids") or "[]")
        except Exception:
            d["model_ids"] = []
        out.append(d)
    return out


def task_stats(tenant_id: str = "default") -> dict:
    c = db.connect()
    row = c.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(ok),0) ok, COALESCE(SUM(cost),0) cost, "
        "COALESCE(AVG(latency_ms),0) lat FROM model_tasks WHERE tenant_id=?", (tenant_id,)
    ).fetchone()
    by_model = c.execute(
        "SELECT model_used m, COUNT(*) n, COALESCE(SUM(cost),0) cost, "
        "COALESCE(AVG(latency_ms),0) lat FROM model_tasks WHERE tenant_id=? "
        "GROUP BY model_used ORDER BY n DESC LIMIT 10", (tenant_id,)
    ).fetchall()
    return {
        "total": row["n"] or 0, "ok": row["ok"] or 0,
        "cost": round(row["cost"] or 0.0, 6), "avg_latency": int(row["lat"] or 0),
        "by_model": [{"model": r["m"], "n": r["n"], "cost": round(r["cost"] or 0, 6),
                      "avg_latency": int(r["lat"] or 0)} for r in by_model],
    }
