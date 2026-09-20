"""知识库核心：解析 → 分块 → 双索引（FTS5 全文 + sqlite-vec 向量）→ 混合检索 → 生成回答。

离线可用性设计（本机无 Key 也能完整跑通）：
- Embedding 不可用时：跳过向量通道，纯 BM25 检索，功能不降级为"不可用"。
- LLM 不可用时：走抽取式兜底，直接返回命中的原文片段并标注 offline，保证链路闭环。
"""
import json
import re
import sqlite3
import struct
import uuid
from pathlib import Path

import requests

from . import config, db, citation_gate

_CJK = r"\u4e00-\u9fff"

# 多轮上下文：最多携带的轮数与单条最大字符（防止 prompt 膨胀）
MAX_HISTORY = 10
MAX_HISTORY_CHARS = 800


# ---------------- 分词：中文 bigram + 英文/数字词 ----------------
def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    toks: list[str] = []
    toks.extend(re.findall(r"[a-z0-9]+", text))
    for seg in re.findall(f"[{_CJK}]+", text):
        if len(seg) == 1:
            toks.append(seg)
        else:
            toks.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return toks


def _fts_query(q: str, limit: int = 32) -> str:
    """把查询串转成 FTS5 安全的 OR 表达式（避免语法错误）。"""
    toks = [t.replace('"', "") for t in tokenize(q)][:limit]
    if not toks:
        return '""'
    return " OR ".join(f'"{t}"' for t in toks)


# ---------------- 分块 ----------------
def split_text(text: str, size: int = 400, overlap: int = 60) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += max(1, size - overlap)
    return chunks


# ---------------- 文件解析 ----------------
def parse_file(path: str | Path) -> str:
    path = Path(path)
    suf = path.suffix.lower()
    if suf in {".txt", ".md", ".markdown", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suf == ".docx":
        import docx  # python-docx，已在本机可用

        d = docx.Document(str(path))
        return "\n".join(p.text for p in d.paragraphs if p.text.strip())
    if suf == ".pdf":
        try:
            import pymupdf

            with pymupdf.open(str(path)) as doc:
                return "\n".join(page.get_text() for page in doc)
        except Exception:
            from pypdf import PdfReader

            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8", errors="ignore")


# ---------------- Embedding / LLM（OpenAI 兼容，失败自动降级）----------------
def embed(texts: list[str]) -> list[list[float]] | None:
    if not config.emb_enabled() or not texts:
        return None
    try:
        resp = requests.post(
            f"{config.EMB_BASE_URL.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {config.EMB_API_KEY}"},
            json={"model": config.EMB_MODEL, "input": texts},
            timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])
        return [d["embedding"] for d in data]
    except Exception:
        return None


def _ser_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def llm_chat(system: str, prompt: str, history: list | None = None, tenant_id=None, provider=None, model=None) -> dict:
    """返回 {ok, text, err, model, provider, usage}。委托 gateway.chat 完成实际调用与埋点。

    history（可选）：多轮上下文，元素形如 {"role":"user"|"assistant","content":str}。
    仅取最近若干轮拼进 messages，使模型能理解追问指代（如"那试用期呢"）。
    历史为空时行为与旧版完全一致，不影响 selftest 基线（离线返回 ok=False）。
    """
    from . import gateway
    return gateway.chat(system, prompt, history=history, tenant_id=tenant_id, provider=provider, model=model)


def llm_chat_stream(system: str, prompt: str, history: list | None = None, tenant_id=None):
    """生成器：逐 token 产出字符串（SSE 用）。无 Key / 异常时不产出。委托 gateway.chat_stream。"""
    from . import gateway
    yield from gateway.chat_stream(system, prompt, history=history, tenant_id=tenant_id)


def _ghost_numbers(answer: str, context: str) -> list[str]:
    """答案中出现了但资料原文里没有的数字（可能是模型幻觉），返回去重后的字符串列表。

    只做提示不做改写：制度问答里一个数字错就是事故，宁可让人核一眼也不能悄悄改答案。
    """
    def nums(t):
        return set(re.findall(r"\d+(?:\.\d+)?", t or ""))
    return sorted(nums(answer) - nums(context), key=lambda x: -len(x))[:8]


# ---------------- 工具快路径（仅显式前缀）----------------
def _detect_tool(question: str):
    """仅识别显式 'tool:' 前缀（用户主动指定工具），返回 (name, args) 或 None。

    设计转变：自然语言意图（如"现在几点""算100+200"）不再手写正则猜测，
    全部交给自主 Agent Loop（rag.agent_loop.run）由 LLM 自己决策调哪些工具、几步完成。
    显式前缀保留为"用户主动指定"的快路径。
    """
    q = (question or "").strip()
    if not q.startswith("tool:"):
        return None
    parts = q[5:].split(None, 1)
    name = parts[0]
    args = {}
    if len(parts) > 1:
        for kv in re.split(r"[,\s]+", parts[1]):
            if "=" in kv:
                k, v = kv.split("=", 1)
                args[k] = v
    return (name, args)


def _run_tool(tenant_id, name, args):
    """执行工具并返回统一结构。"""
    from . import tools_registry
    r = tools_registry.call_tool(name, args, tenant_id=tenant_id)
    if "result" in r:
        text = str(r["result"])
    elif "error" in r:
        text = "工具执行出错：" + str(r["error"])
    else:
        text = str(r)
    return {"answer": f"【工具调用 · {name}】\n{text}", "citations": [], "mode": "tool",
            "tool": name, "tool_result": r}


# ---------------- 入库 ----------------
def add_document(tenant_id: str, title: str, text: str, source: str = "") -> dict:
    conn = db.connect()
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    chunks = split_text(text)
    if not chunks:
        return {"doc_id": doc_id, "n_chunks": 0, "indexed_vec": 0, "note": "空文档，未入库"}

    vecs = embed(chunks)
    indexed_vec = 0

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO docs(id,tenant_id,title,source,n_chunks) VALUES(?,?,?,?,?)",
        (doc_id, tenant_id, title, source, len(chunks)),
    )
    for i, ch in enumerate(chunks):
        uid = f"{doc_id}-{i}"
        cur.execute(
            "INSERT INTO chunks(chunk_uid,tenant_id,doc_id,seq,text) VALUES(?,?,?,?,?)",
            (uid, tenant_id, doc_id, i, ch),
        )
        row_id = cur.lastrowid
        cur.execute(
            "INSERT INTO chunks_fts(chunk_uid,tenant_id,content) VALUES(?,?,?)",
            (uid, tenant_id, " ".join(tokenize(ch))),
        )
        if vecs and i < len(vecs) and len(vecs[i]) == config.EMB_DIM:
            cur.execute("INSERT INTO vec_chunks(rowid,embedding) VALUES(?,?)", (row_id, _ser_f32(vecs[i])))
            indexed_vec += 1
    conn.commit()
    return {"doc_id": doc_id, "n_chunks": len(chunks), "indexed_vec": indexed_vec}


def delete_document(tenant_id: str, doc_id: str) -> int:
    conn = db.connect()
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE tenant_id=? AND doc_id=?", (tenant_id, doc_id))]
    for cid in ids:
        try:
            conn.execute("DELETE FROM vec_chunks WHERE rowid=?", (cid,))
        except Exception:
            pass
    conn.execute("DELETE FROM chunks_fts WHERE chunk_uid LIKE ?", (f"{doc_id}-%",))
    conn.execute("DELETE FROM chunks WHERE tenant_id=? AND doc_id=?", (tenant_id, doc_id))
    conn.execute("DELETE FROM docs WHERE tenant_id=? AND id=?", (tenant_id, doc_id))
    conn.commit()
    return len(ids)


def list_documents(tenant_id: str) -> list[dict]:
    rows = db.connect().execute(
        "SELECT id,title,source,n_chunks,created_at FROM docs WHERE tenant_id=? ORDER BY created_at DESC",
        (tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_document_text(tenant_id: str, doc_id: str, max_chars: int = 8000) -> str:
    """按 doc_id 取文档全文（按 chunks 顺序拼接）。"""
    try:
        conn = db.connect()
        rows = conn.execute(
            "SELECT text FROM chunks WHERE tenant_id=? AND doc_id=? ORDER BY idx",
            (tenant_id, doc_id),
        ).fetchall()
        text = "\n".join(r["text"] for r in rows)
        return text[:max_chars]
    except Exception:
        return ""


# ---------------- 检索：BM25 + 向量，RRF 融合 ----------------
def _bm25_hits(tenant_id: str, q: str, top_k: int) -> list[tuple[int, float]]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT c.id AS cid, bm25(chunks_fts) AS score
               FROM chunks_fts
               JOIN chunks c ON c.chunk_uid = chunks_fts.chunk_uid
               WHERE chunks_fts MATCH ? AND chunks_fts.tenant_id = ?
               ORDER BY score LIMIT ?""",
            (_fts_query(q), tenant_id, top_k * 3),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    # bm25() 返回负值，越小越相关 → 归一为正分
    return [(r["cid"], 1.0 / (1.0 + max(0.0, -r["score"]))) for r in rows]


def _vec_hits(tenant_id: str, q: str, top_k: int) -> list[tuple[int, float]]:
    if not config.emb_enabled():
        return []
    qv = embed([q])
    if not qv:
        return []
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_ser_f32(qv[0]), top_k * 3),
        ).fetchall()
    except Exception:
        return []
    # 租户过滤在 Python 侧完成（vec0 表不带 tenant 列，数据量小，代价可接受）
    allowed = {r[0] for r in conn.execute("SELECT id FROM chunks WHERE tenant_id=?", (tenant_id,))}
    return [(r[0], 1.0 / (1.0 + float(r[1]))) for r in rows if r[0] in allowed][: top_k * 3]


def search(tenant_id: str, q: str, top_k: int = 5) -> list[dict]:
    bm = _bm25_hits(tenant_id, q, top_k)
    vc = _vec_hits(tenant_id, q, top_k)

    # RRF 融合（k=60 为通用经验值）
    fused: dict[int, float] = {}
    for rank, (cid, _) in enumerate(bm):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank + 1)
    for rank, (cid, _) in enumerate(vc):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank + 1)
    if not fused:
        return []

    ordered = sorted(fused.items(), key=lambda x: -x[1])[:top_k]
    conn = db.connect()
    out = []
    for cid, score in ordered:
        row = conn.execute(
            "SELECT chunk_uid,doc_id,text FROM chunks WHERE id=? AND tenant_id=?", (cid, tenant_id)
        ).fetchone()
        if not row:
            continue
        title = conn.execute("SELECT title FROM docs WHERE id=?", (row["doc_id"],)).fetchone()
        out.append(
            {
                "score": round(score, 6),
                "doc_id": row["doc_id"],
                "title": title["title"] if title else "",
                "text": row["text"],
                "sources": ["bm25"] if cid in dict(bm) else [],
            }
        )
    for item, (cid, _) in zip(out, ordered):
        if cid in dict(vc):
            item["sources"].append("vector")
    return out


# ---------------- 问答（带引用）----------------
def _agent_system(context: str, n_hits: int) -> str:
    """自主 Agent 的统一系统提示：知识底座 + 工具清单 + 规划引导（T4）+ 数字护栏。

    橙皮书 Agent Skills 落地：在系统提示末尾追加【可用技能清单】段（指令层 Skill 注册表
    自动注入），让 LLM 知道平台沉淀了哪些"工作手册"可按 trigger 调用。学 Hermes——
    仅作追加段，不改动上方 5 条能力主结构，保持 system prompt 主干干净。
    """
    base = (
        "你是 MiniYuxi 企业级 AI Agent 平台的智能助手，具备自主规划与工具调用能力。\n"
        "【你的能力】\n"
        "1. 可自主调用工具完成任务（无需用户提醒）：calc 计算、current_time 获取当前时间、"
        "kb_search 检索企业知识库、web_search 联网搜索实时信息、count_docs 统计知识库文档数。\n"
        "2. 遇到多步任务，先想清楚步骤，再依次调用工具逐步完成，最后综合给出答案（ReAct 循环）。\n"
        "3. 优先依据下方【知识库资料】与工具返回结果作答；资料未涉及的要明说「资料未提及」，不得凭空编造。\n"
        "4. 凡涉及数字、天数、金额、期限、比例、百分比，必须逐字照抄来源，禁止换算/四舍五入/概括/推测。\n"
        "5. 回答中用 [编号] 标注资料来源；若多来源冲突，列出冲突并说明各出自哪条。\n"
    )
    # 指令层 Skill 注入（橙皮书 Agent Skills）：可用技能清单作为追加段
    try:
        from . import skills_catalog
        skills_block = skills_catalog.inject_text()
    except Exception:
        skills_block = ""
    if skills_block:
        base += "\n" + skills_block + "\n"
    base += f"\n【知识库资料】（共 {n_hits} 条命中）\n{context}\n"
    return base


def _rag_single(system, question, history, tenant_id, hits, citations) -> dict:
    """退化路径：单次 LLM 生成（agent_loop 不可用[离线/网关失败]时）。"""
    res = llm_chat(system, question, history, tenant_id=tenant_id)
    if res["ok"]:
        warn = _ghost_numbers(res["text"], system)
        out = {"answer": res["text"], "citations": citations, "mode": "llm", "model": config.LLM_MODEL}
        if warn:
            out["warnings"] = ["答案中的数字 " + "、".join(warn) + " 未在原文中出现，请核对引用"]
        return out
    best = hits[0]
    text = (f"【离线兜底 · 未配置模型 Key，以下为原文摘录】\n{best['text'][:500]}\n"
            f"（依据来源：{best['title']}）")
    return {"answer": text, "citations": citations, "mode": "offline", "reason": res["err"]}


def answer(tenant_id: str, question: str, top_k: int = 5, history: list | None = None) -> dict:
    """问答主入口（真·Agent 版）。

    路径：① 显式 'tool:' 前缀 → 直接调工具（快路径）；
          ② 离线/无 Key → 抽取式兜底（selftest 基线，行为不变）；
          ③ 在线 → 自主 Agent Loop（rag.agent_loop.run），LLM 自己决定调哪些工具、几步完成；
          对话摘要持久化到服务端记忆（T3），关键经验沉淀 skills（T6）。
    """
    hits = search(tenant_id, question, top_k)
    citations = [{"title": h["title"], "text": h["text"][:200], "score": h["score"]} for h in hits]

    # 坑2 防护（360 七坑）：legal/labor 意图且未命中知识库 → 硬闸门拒绝自由生成法条
    block = citation_gate.evaluate(question, hits)
    if block is not None:
        return block

    # ① 显式前缀快路径
    tool_hit = _detect_tool(question)
    if tool_hit:
        name, args = tool_hit
        res = _run_tool(tenant_id, name, args)
        try:
            from . import skills
            skills.learn(tenant_id, question, res.get("answer", ""))
        except Exception:
            pass
        return res

    if not hits:
        return {"answer": "知识库中未检索到相关内容，请先上传制度文档。", "citations": [], "mode": "empty"}

    context = "\n\n".join(f"[{i+1}] 来源：{h['title']}\n{h['text']}" for i, h in enumerate(hits))

    if not config.llm_enabled():
        # ② 离线兜底：抽取式返回（与旧版完全一致，保障 selftest）
        best = hits[0]
        final_text = (f"【离线兜底 · 未配置模型 Key，以下为原文摘录】\n{best['text'][:500]}\n"
                      f"（依据来源：{best['title']}）")
        out = {"answer": final_text, "citations": citations, "mode": "offline", "reason": "no-api-key"}
        try:
            from . import skills
            skills.learn(tenant_id, question, final_text)
        except Exception:
            pass
        return out

    # ③ 在线 → 自主 Agent Loop（大脑）
    from . import agent_loop, memory
    mem = memory.recall(tenant_id, limit=8)
    system = _agent_system(context, len(hits))
    res = agent_loop.run(system, question, history, tenant_id=tenant_id, memories=mem)
    if res is None:
        out = _rag_single(system, question, history, tenant_id, hits, citations)
    else:
        warn = _ghost_numbers(res["answer"], context)
        out = {"answer": res["answer"], "citations": citations, "mode": "agent",
               "model": res["model"], "tool_calls_used": res["tool_calls_used"],
               "loop_trace": res["loop_trace"], "memories_used": res["memories_used"]}
        if warn:
            out["warnings"] = ["答案中的数字 " + "、".join(warn) + " 未在原文中出现，请核对引用"]
    # 坑2 防护（360 七坑）：legal/labor 意图且答案编造了 KB 中不存在的法规引用 → 拒绝
    block = citation_gate.evaluate(question, hits, out.get("answer", ""))
    if block is not None:
        return block
    # T3 记忆持久化 + T6 闭环学习（失败不影响主链路）
    try:
        memory.append(tenant_id, "user", question)
        memory.append(tenant_id, "assistant", out.get("answer", ""))
    except Exception:
        pass
    try:
        from . import skills
        skills.learn(tenant_id, question, out.get("answer", ""))
    except Exception:
        pass
    return out
