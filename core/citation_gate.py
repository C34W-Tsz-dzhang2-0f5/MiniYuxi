# -*- coding: utf-8 -*-
"""法律/劳动类问答的「无引用不出文」硬闸门（360 七坑 · 坑2 编造防护）。

设计目标（对齐阿长「法条必核验」铁律）：
- 当问题被识别为 legal/labor 意图，且知识库检索 0 命中 → 拒绝自由生成法条，
  强制要求先上传相关法规/制度文档或确认来源。
- 当 legal/labor 意图且检索有命中，但答案引用了知识库中并不存在的法规名
  （《xxx法/条例/规定》）→ 同样拒绝，防止模型编造出处。
- 非 legal/labor 意图一律放行，不影响其他问答（含通用制度问答）。

判定只依赖纯标准库（re），可独立 import，不触发 core 其他重模块，
便于在 pre-commit / CI 中零依赖快速验证。
"""
import re

# 命中任一关键词即视为 legal/labor 意图（保守：宁可多判，也不漏放法条生成）
LEGAL_LABOR_KEYWORDS = (
    "法条", "法律", "法规", "法释", "司法解释", "条例", "仲裁", "劳动争议",
    "劳动合同", "劳动合", "经济补偿", "赔偿金", "二倍", "试用期", "解除", "终止",
    "工伤", "社保", "社保费", "生育", "竞业", "工时", "加班费", "年休假", "带薪",
    "辞退", "开除", "违法解除", "代通知金", "n+1", "2n", "公积金", "工资支付",
    "拖欠工资", "劳动能力", "伤残", "抚恤", "丧葬", "一次性", "医疗期", "无固定期限",
)

# 用于「探测答案/问题中是否引用了某部法规」：捕获《...》内的法规名
_LAW_NAME_RE = re.compile(r"《([^》]{2,30}?)(?:法|条例|规定|办法|解释|通知|细则|指引|规程)》")


def is_legal_labor_intent(text: str) -> bool:
    """问题是否属法律/劳动类意图。"""
    if not text:
        return False
    t = (text or "").lower()
    return any(kw in t for kw in LEGAL_LABOR_KEYWORDS)


def _cited_law_names(text: str) -> set:
    """提取文本中《xxx法》形式的法规名（去《》）。"""
    return {m.group(1) for m in _LAW_NAME_RE.finditer(text or "")}


def _hit_blob_law_names(hits: list) -> set:
    """从检索命中（标题+正文）中提取出现的法规名。"""
    names = set()
    for h in hits or []:
        blob = (h.get("title", "") or "") + " " + (h.get("text", "") or "")
        names |= _cited_law_names(blob)
    return names


def _law_grounded(law_name: str, hits: list) -> bool:
    """法规名是否真实出现在任一命中（标题或正文）中（子串宽松匹配）。"""
    for h in hits or []:
        blob = (h.get("title", "") or "") + " " + (h.get("text", "") or "")
        if law_name in blob:
            return True
    return False


def evaluate(question: str, hits: list, answer: str | None = None) -> dict | None:
    """返回拒绝 dict（含 answer / citations / mode='citation_blocked' / reason）或 None（放行）。

    判定：
    1) legal/labor 意图 且 hits 为空 → 拒绝（无引用不出文）。
    2) legal/labor 意图 且 hits 非空，但 answer 引用了知识库中不存在的法规名
       （且该法规名未出现在用户问题里）→ 拒绝（防编造出处）。
    """
    if not is_legal_labor_intent(question):
        return None

    # 规则 1：未命中知识库 → 拒绝自由生成法条
    if not hits:
        return {
            "answer": (
                "⚠️ 未命中知识库，已拒绝自由生成法条。\n"
                "本平台对法律/劳动类问题执行「无引用不出文」硬闸门："
                "请先将相关法规/制度原文上传至知识库，或明确问题所依据的法条来源后重试。"
            ),
            "citations": [],
            "mode": "citation_blocked",
            "reason": "no_kb_hit",
        }

    # 规则 2：答案编造了 KB 中不存在的法规引用 → 拒绝
    if answer:
        cited = _cited_law_names(answer)
        question_laws = _cited_law_names(question)  # 用户自己提到的法规不算编造
        effective = cited - question_laws
        fabricated = [L for L in effective if not _law_grounded(L, hits)]
        if fabricated:
            missing = "、".join(sorted(fabricated))
            return {
                "answer": (
                    f"⚠️ 答案引用了知识库中不存在的法规（{missing}），已拒绝自由生成法条。\n"
                    "请补充该法规原文到知识库，或核实引用来源后再生成。"
                ),
                "citations": [
                    {"title": h["title"], "text": h["text"][:200], "score": h["score"]}
                    for h in hits
                ],
                "mode": "citation_blocked",
                "reason": "fabricated_citation",
            }

    return None
