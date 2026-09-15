# -*- coding: utf-8 -*-
"""提示词解析器：把《2个岗位AI提示词大全.pdf》抽取文本 → 结构化任务库 JSON。

这是"从提示词解析到任务自动执行"端到端闭环的数据底座：
- 输入：pdf_extract.txt（由 pypdf 抽取，见 build_pdf_extract.bat 思路）
- 输出：../skills/task_library.json —— 每个任务含
  {id, role, module, title, scenario, inputs[], operation[], prompt_template,
   output_result, output_format[], followups[], expected}

解析依据 PDF 高度规整的字段模板：
  适用岗位 → 角色块边界
  模块短标题（纯中文）→ module
  N. 任务名（下一行是"适用场景："）→ 任务
  需要准备 / 文件与操作 / 主提示词 / 输出结果 / 输出格式 / 建议追问 / 预期输出 → 字段
零第三方依赖，纯标准库。可重复运行。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "..", "资料", "pdf_extract.txt")  # 同项目上级"资料"目录
# 兼容：若资料目录不在上级，则回退到脚本同级的 pdf_extract.txt
if not os.path.exists(SRC):
    SRC = os.path.join(ROOT, "pdf_extract.txt")
OUT = os.path.join(ROOT, "skills", "task_library.json")

ROLE_HEADER_RE = re.compile(r"^适用岗位[：:]\s*(.+)$")
TASK_RE = re.compile(r"^(\d+)[.、]\s*(.+)$")
MODULE_RE = re.compile(r"^[\u4e00-\u9fa5]{2,12}$")  # 纯中文短标题=模块名
PAGE_RE = re.compile(r"^=+ PAGE \d+ =+$")
NUM_NOISE_RE = re.compile(r"^\d{1,4}$")  # 页码噪声行

# 任务内字段锚点（行首）
FIELD_ANCHORS = ["需要准备", "文件与操作", "主提示词", "输出结果", "输出格式", "建议追问", "预期输出"]


def _clean_lines(raw):
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        if PAGE_RE.match(s):
            continue
        if NUM_NOISE_RE.match(s):  # 孤立页码
            continue
        out.append(s)
    return out


def _split_role_blocks(lines):
    """按'适用岗位：'切分为两个角色块（去掉前言）。"""
    blocks = []
    cur = None
    for s in lines:
        m = ROLE_HEADER_RE.match(s)
        if m:
            if cur:
                blocks.append(cur)
            cur = {"role_line": m.group(1), "lines": []}
        elif cur is not None:
            cur["lines"].append(s)
    if cur:
        blocks.append(cur)
    return blocks


def _norm_role_name(role_line):
    # "行政经理、行政专员..." → 取首个统称或前 8 字
    if "人力资源" in role_line or "HR" in role_line.upper():
        return "hr"
    if "行政" in role_line:
        return "admin_office"
    return "other"


def _parse_role_block(block):
    lines = block["lines"]
    role = _norm_role_name(block["role_line"])
    tasks = []
    i = 0
    n = len(lines)
    task_counter = 0
    while i < n:
        s = lines[i]
        m = TASK_RE.match(s)
        if not m:
            i += 1
            continue
        title = m.group(2).strip()
        # 下一行必须是"适用场景："
        if i + 1 >= n or not lines[i + 1].startswith("适用场景"):
            i += 1
            continue
        # 回溯找模块名（任务标题前的纯中文短行）
        module = ""
        for j in range(i - 1, max(-1, i - 5), -1):
            cand = lines[j].strip()
            if MODULE_RE.match(cand) and cand != title:
                module = cand
                break
        # 收集本任务区间：从 title 行到下一个"标题行(下一行是适用场景)"或块尾
        j = i + 1
        buf = []
        while j < n:
            nxt = lines[j]
            nm = TASK_RE.match(nxt)
            if nm and j + 1 < n and lines[j + 1].startswith("适用场景"):
                break
            buf.append(nxt)
            j += 1
        task_counter += 1
        task = _parse_task_fields(role, module, title, buf, task_counter)
        tasks.append(task)
        i = j  # 跳到下一个任务标题
    return role, tasks


def _collect_field(buf, start_idx, anchors):
    """从 buf[start_idx]（含锚点行）开始，收集到下一个锚点前的文本。"""
    text = []
    k = start_idx + 1
    while k < len(buf):
        if any(buf[k].startswith(a) for a in anchors):
            break
        text.append(buf[k])
        k += 1
    return [t for t in text if t.strip()]


def _find_anchor(buf, anchor):
    for idx, s in enumerate(buf):
        if s.startswith(anchor):
            return idx
    return -1


def _parse_task_fields(role, module, title, buf, counter):
    task = {
        "id": f"{role}_{counter:02d}",
        "role": role,
        "module": module,
        "title": title,
        "scenario": "",
        "inputs": [],
        "operation": [],
        "prompt_template": "",
        "output_result": "",
        "output_format": [],
        "followups": [],
        "expected": "",
    }
    # 适用场景
    for idx, s in enumerate(buf):
        if s.startswith("适用场景"):
            task["scenario"] = s.split("：", 1)[-1].split(":", 1)[-1].strip()
            break
    # 需要准备
    a = _find_anchor(buf, "需要准备")
    if a >= 0:
        task["inputs"] = [x.lstrip("•-·").strip() for x in _collect_field(buf, a, ["文件与操作"])]
    # 文件与操作
    a = _find_anchor(buf, "文件与操作")
    if a >= 0:
        task["operation"] = [x.lstrip("•-·").strip() for x in _collect_field(buf, a, ["主提示词"])]
    # 主提示词（到首个顶层元数据锚点为止）
    a = _find_anchor(buf, "主提示词")
    if a >= 0:
        pt = _collect_field(buf, a, ["输出结果", "【输出结果】", "输出格式", "【输出格式】", "建议追问", "预期输出"])
        task["prompt_template"] = "\n".join(pt).strip()
    # 输出结果（元数据，优先无括号的"输出结果："）
    a = _find_anchor(buf, "输出结果")
    if a < 0:
        a = _find_anchor(buf, "【输出结果】")
    if a >= 0:
        ors = _collect_field(buf, a, ["输出格式", "【输出格式】", "建议追问", "预期输出"])
        task["output_result"] = " ".join(ors).strip()
    # 输出格式
    a = _find_anchor(buf, "输出格式")
    if a < 0:
        a = _find_anchor(buf, "【输出格式】")
    if a >= 0:
        task["output_format"] = [x.lstrip("•-·").strip() for x in _collect_field(buf, a, ["建议追问", "预期输出"])]
    # 建议追问
    a = _find_anchor(buf, "建议追问")
    if a >= 0:
        task["followups"] = [x.lstrip("•-·").strip() for x in _collect_field(buf, a, ["预期输出"])]
    # 预期输出（可能同行内联："预期输出：xxx"）
    a = _find_anchor(buf, "预期输出")
    if a >= 0:
        inline = buf[a].split("：", 1)[-1].split(":", 1)[-1].strip()
        rest = " ".join(_collect_field(buf, a, [])).strip()
        task["expected"] = inline or rest
    return task


def main():
    if not os.path.exists(SRC):
        print(f"[ERR] 找不到抽取文本: {SRC}", file=sys.stderr)
        sys.exit(1)
    with open(SRC, encoding="utf-8") as f:
        raw = f.read()
    lines = _clean_lines(raw)
    blocks = _split_role_blocks(lines)
    library = {"roles": {}, "tasks": []}
    for blk in blocks:
        role, tasks = _parse_role_block(blk)
        library["roles"].setdefault(role, {"role_line": blk["role_line"], "count": 0})
        library["roles"][role]["count"] = len(tasks)
        library["tasks"].extend(tasks)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)
    print(f"OK 解析 {len(library['tasks'])} 个任务 → {OUT}")
    for r, meta in library["roles"].items():
        print(f"  - {r}: {meta['count']} 个任务  ({meta['role_line'][:30]})")


if __name__ == "__main__":
    main()
