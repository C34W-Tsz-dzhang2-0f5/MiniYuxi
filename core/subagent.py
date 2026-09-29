"""子 Agent（生成器 / 评判器分离 · Loop 工程：让会说"不行"的东西做验证）。

设计：生成器调用 llm_fn 产出草稿；rule_judge 为确定性、可测的评判器（不依赖 LLM，便于单测与回归）；
delegate 把二者闭合成"生成→评判→不达标重做"的循环，直到通过或达最大轮次。
真实场景里 llm_fn / judge_fn 可换成 LLM 调用；测试用确定性函数注入。
零新增依赖。
"""


def run_generator(prompt, llm_fn):
    """调用生成器产出草稿。"""
    return llm_fn(prompt)


def rule_judge(draft, criteria: dict) -> dict:
    """确定性评判器：按 criteria 检查草稿。

    criteria 字段：
      min_len     最小长度（字符）
      must_contain 必含关键词列表
      forbid      禁用词列表（命中即失败）
    返回 {pass, score, reasons}。
    """
    reasons = []
    score = 0
    d = draft or ""
    if "min_len" in criteria and len(d) < criteria["min_len"]:
        reasons.append("长度不足（%d < %d）" % (len(d), criteria["min_len"]))
    else:
        score += 1
    for kw in criteria.get("must_contain", []):
        if kw in d:
            score += 1
        else:
            reasons.append("缺少必含关键词：%s" % kw)
    for fw in criteria.get("forbid", []):
        if fw in d:
            reasons.append("命中禁用词：%s" % fw)
            score -= 1
    return {"pass": len(reasons) == 0, "score": score, "reasons": reasons}


def delegate(task, generator_fn, judge_fn, max_rounds=3, ctx=None) -> dict:
    """生成器/评判器分离闭环：循环生成→评判，直到评判通过或达最大轮次。"""
    ctx = ctx or {}
    rounds = 0
    draft = None
    verdict = None
    for _ in range(max_rounds):
        rounds += 1
        draft = generator_fn(task, ctx)
        verdict = judge_fn(draft, ctx)
        if verdict.get("pass"):
            return {"draft": draft, "rounds": rounds, "passed": True, "verdict": verdict}
    return {"draft": draft, "rounds": rounds, "passed": False, "verdict": verdict}


# ---------------- 真实生成器（调用统一大模型网关）----------------
# 内置子 Agent：平台预置，用户不可删；read_only 表示只检索知识库、不外发/不执行写操作。
BUILTIN_AGENTS = [
    {
        "id": "builtin_explorer",
        "name": "制度检索员（只读）",
        "role": "只读检索知识库，基于制度原文作答，不编造。",
        "system_prompt": (
            "你是 MiniYuxi 的只读检索员。只能依据【知识库资料】作答，严格逐字引用来源编号 [n]；"
            "资料未提及的内容必须回答「资料未提及」，严禁凭空生成法条、政策或数字。"
            "涉及天数、金额、比例、比例必须照抄原文，不得换算或推测。"
        ),
        "tools": "[]",
        "read_only": 1,
        "builtin": 1,
    }
]


def _llm_generate(system: str, prompt: str, tenant_id: str) -> str:
    """真实生成器：调用统一大模型网关。离线（无 Key）时优雅降级为提示，不抛异常。"""
    from . import rag

    res = rag.llm_chat(system, prompt, tenant_id=tenant_id)
    if res.get("ok"):
        return res["text"]
    return ("（子 Agent 生成失败：模型未配置或网关不可用，请在「多模型中心」配置 Key。"
            "原始请求：" + prompt[:200] + "）")


def _explorer_generate(task: str, tenant_id: str) -> str:
    """只读检索员：先检索知识库，再让 LLM 基于命中原文作答。"""
    from . import rag

    hits = rag.search(tenant_id, task, top_k=5)
    if not hits:
        return "（制度检索员：知识库未检索到与「" + task + "」相关的制度文档，请先在资料库上传。）"
    context = "\n\n".join(
        f"[{i + 1}] 来源：{h['title']}\n{h['text']}" for i, h in enumerate(hits)
    )
    system = BUILTIN_AGENTS[0]["system_prompt"] + f"\n\n【知识库资料】（共 {len(hits)} 条命中）\n{context}\n"
    return _llm_generate(system, task, tenant_id)


def real_generator(agent: dict, task: str, tenant_id: str) -> str:
    """按 agent 定义选择生成策略：read_only 走检索增强，否则走通用 LLM。"""
    if agent.get("read_only"):
        return _explorer_generate(task, tenant_id)
    sp = agent.get("system_prompt") or "你是 MiniYuxi 的子 Agent，请专业、简洁地完成用户交代的任务。"
    return _llm_generate(sp, task, tenant_id)


# ---------------- 持久化：用户级自定义子 Agent ----------------
def _conn():
    from . import db

    return db.connect()


def list_agents(tenant_id: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT id,name,role,system_prompt,tools,read_only,builtin,created_at "
        "FROM subagents WHERE tenant_id=? ORDER BY builtin DESC, created_at ASC",
        (tenant_id,),
    ).fetchall()
    custom = [dict(r) for r in rows]
    return BUILTIN_AGENTS + custom


def create_agent(tenant_id: str, name: str, role: str = "", system_prompt: str = "",
                 tools: str = "[]", read_only: int = 0) -> str:
    import uuid

    aid = "agent-" + uuid.uuid4().hex[:10]
    _conn().execute(
        "INSERT INTO subagents(id,tenant_id,name,role,system_prompt,tools,read_only,builtin) "
        "VALUES(?,?,?,?,?,?,?,0)",
        (aid, tenant_id, name, role, system_prompt, tools, int(read_only)),
    )
    return aid


def update_agent(tenant_id: str, agent_id: str, **fields) -> bool:
    allowed = {"name", "role", "system_prompt", "tools", "read_only"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v if k != "read_only" else int(v))
    if not sets:
        return False
    vals.extend([tenant_id, agent_id])
    _conn().execute(
        "UPDATE subagents SET " + ",".join(sets) + " WHERE tenant_id=? AND id=?", vals
    )
    return True


def delete_agent(tenant_id: str, agent_id: str) -> bool:
    # 只允许删自定义；内置受保护（builtin=0）
    _conn().execute(
        "DELETE FROM subagents WHERE tenant_id=? AND id=? AND builtin=0", (tenant_id, agent_id)
    )
    return True
