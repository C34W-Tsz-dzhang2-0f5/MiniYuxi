"""P2 编排画布执行引擎：8 类节点工作流（start/end/llm/subagent/knowledge/tool/condition/approval）。

设计：工作流 = {nodes:[{id,type,...}], edges:[{from,to}]}。execute 按拓扑序调用 handlers 回调，
handlers 可注入（便于测试用 mock，也便于后端接真实 LLM/工具）。validate 负责结构校验（单 start/end、无环）。
零新增依赖。
"""
from collections import deque


def validate(workflow: dict):
    errs = []
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    starts = [n for n in nodes if n.get("type") == "start"]
    ends = [n for n in nodes if n.get("type") == "end"]
    if len(starts) != 1:
        errs.append("必须且只能有 1 个 start 节点")
    if len(ends) < 1:
        errs.append("至少 1 个 end 节点")

    adj = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])
    seen, stack = set(), set()

    def dfs(u):
        if u in stack:
            return True
        if u in seen:
            return False
        stack.add(u)
        seen.add(u)
        for v in adj.get(u, []):
            if dfs(v):
                return True
        stack.discard(u)
        return False

    for n in nodes:
        if dfs(n["id"]):
            errs.append("工作流存在环路(cycle)，无法执行")
            break
    return (len(errs) == 0), errs


def execute(workflow: dict, ctx: dict = None, handlers: dict = None, conn=None) -> dict:
    """按拓扑序执行工作流。handlers: {node_type: callable(node, g) -> output}。"""
    handlers = handlers or {}
    ctx = ctx or {}
    nodes = {n["id"]: n for n in workflow.get("nodes", [])}
    edges = workflow.get("edges", [])
    if not nodes:
        return {"ok": False, "error": "空工作流", "trace": [], "outputs": {}}

    indeg = {nid: 0 for nid in nodes}
    adj = {}
    for e in edges:
        indeg[e["to"]] = indeg.get(e["to"], 0) + 1
        adj.setdefault(e["from"], []).append(e["to"])

    q = deque([nid for nid in nodes if indeg.get(nid, 0) == 0])
    order = []
    while q:
        u = q.popleft()
        order.append(u)
        for v in adj.get(u, []):
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    if len(order) != len(nodes):
        return {"ok": False, "error": "存在环路或孤立节点", "trace": [], "outputs": {}}

    trace, outputs, g = [], {}, dict(ctx)
    for nid in order:
        node = nodes[nid]
        h = handlers.get(node["type"])
        out = h(node, g) if h else {"out": None}
        outputs[nid] = out
        g[nid] = out
        trace.append({"id": nid, "type": node["type"], "out": out})
    return {"ok": True, "trace": trace, "outputs": outputs}
