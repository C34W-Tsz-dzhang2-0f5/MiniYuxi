"""legal/labor「无引用不出文」硬闸门单元测试（坑2 编造防护，零依赖，可在 pre-commit 跑）。

直接 importlib 加载 core/citation_gate.py，避免触发 core 包重依赖（fastapi 等）。
覆盖：意图识别、未命中拒绝、编造法规引用拒绝、命中/用户自带法规放行。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SPEC = os.path.join(ROOT, "core", "citation_gate.py")

spec = importlib.util.spec_from_file_location("citation_gate", SPEC)
cg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cg)

PASS = []


def check(name, cond):
    PASS.append(cond)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))


# --- 意图识别 ---
check("识别劳动意图(经济补偿)", cg.is_legal_labor_intent("解除劳动合同的经济补偿怎么算"))
check("识别法条意图(民法典)", cg.is_legal_labor_intent("这条法条依据民法典第几条"))
check("非法律意图放行(年假)", not cg.is_legal_labor_intent("年假怎么算"))
check("非法律意图放行(天气)", not cg.is_legal_labor_intent("今天天气如何"))

# --- 规则1：未命中知识库 → 拒绝 ---
hits_empty = []
block = cg.evaluate("违法解除劳动合同的赔偿", hits_empty)
check("无命中法律问题→拒绝(mode=citation_blocked)",
      block is not None and block["mode"] == "citation_blocked" and block["reason"] == "no_kb_hit")

# --- 非法律问题无命中 → 放行（不抢答通用问答）---
block2 = cg.evaluate("公司打印机坏了找谁", hits_empty)
check("非法律问题无命中→放行", block2 is None)

# --- 规则2：编造 KB 不存在的法规引用 → 拒绝 ---
hits_law = [{"title": "劳动合同法重点解读", "text": "劳动合同法规定试用期不得超过六个月。", "score": 0.9}]
fabricated_answer = "根据《2026最新劳动补偿条例》第5条，单位应当支付三倍补偿。"
block3 = cg.evaluate("解除劳动合同补偿", hits_law, fabricated_answer)
check("编造 KB 不存在的法规→拒绝(fabricated_citation)",
      block3 is not None and block3["reason"] == "fabricated_citation")

# --- 命中中存在的法规引用 → 放行 ---
grounded_answer = "根据《劳动合同法》第19条，试用期不得超过六个月。"
block4 = cg.evaluate("试用期最长多久", hits_law, grounded_answer)
check("引用命中中存在的法规→放行", block4 is None)

# --- 用户自己提到的法规不算编造 → 放行 ---
q_with_law = "根据《劳动合同法》试用期怎么算"
block5 = cg.evaluate(q_with_law, hits_law, grounded_answer)
check("用户自带法规名→放行", block5 is None)

# --- 有命中但回答未引用任何法规 → 放行（不误伤普通法律问答）---
plain_answer = "解除劳动合同需符合法定情形，建议先核实解除理由是否合法。"
block6 = cg.evaluate("公司能随便辞退我吗", hits_law, plain_answer)
check("有命中且未编造法规→放行", block6 is None)

n_pass = sum(1 for p in PASS if p)
print("\nCITATION GATE: %d/%d 通过" % (n_pass, len(PASS)))
sys.exit(0 if n_pass == len(PASS) else 1)
