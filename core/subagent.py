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
