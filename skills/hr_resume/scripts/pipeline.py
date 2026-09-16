#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HR-Workflow 本地引擎：确定性简历评分 + 入库（无需外部 LLM，可离线运行、可审计）。

设计目标（呼应公平性研究）：
  - 评分数学完全透明：每个维度分数显式输入，加权求和，输出分项明细。
  - 不替候选人补全缺失信息，不黑盒决策；AI 只做「标准化」，最终决策仍由人。

子命令：
  init                      初始化 data/candidates.csv 与 data/downloaded_records.json
  score --standard S --candidate C   对单个候选人评分并打印（C 为含 dim_scores 的 JSON）
  add   --standard S --candidate C   评分并追加写入 candidates.csv
  report [--min 8]          列出 CSV 中达到阈值（默认8分）的候选人
  demo                      用内置示例跑一遍 评分 -> 入库 -> 报告
  find-standard --role 产品经理   按岗位名匹配评分标准文件

候选人 JSON 字段示例：
  {
    "姓名":"张三","性别":"男","年龄":28,"手机号":"138...","邮箱":"z@x.com",
    "求职意向岗位":"产品经理","毕业院校":"xx大学","学历层次":"本科","专业名称":"计算机",
    "是否985/211":"211","工作年限":5,"是否大厂背景":"是","工作经历摘要":"...","技能清单":"需求分析,PRD,数据分析",
    "dim_scores":{"education_match":8,"experience_relevance":9,"skill_fit":8,"project_depth":9,"stability":7,"potential":8},
    "rejected": false,           # 可选：true 表示触发一票否决
    "总结评价":"...", "建议问题":"..."   # 可选
  }
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STD_DIR = BASE / "scoring_standards"
DATA_DIR = BASE / "data"
CSV_PATH = DATA_DIR / "candidates.csv"
DEDUP_PATH = DATA_DIR / "downloaded_records.json"

CSV_FIELDS = [
    "姓名", "性别", "年龄", "手机号", "邮箱", "求职意向岗位", "毕业院校", "学历层次",
    "专业名称", "是否985/211", "工作年限", "是否大厂背景", "工作经历摘要", "技能清单",
    "当前状态", "总分", "分项明细", "总结评价", "建议问题", "处理时间",
]


# ---------- 标准加载 ----------
def find_standard(role_name: str):
    for p in STD_DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("role") == role_name:
            return p
    return None


def load_standard(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- 评分（确定性） ----------
def compute_score(standard: dict, dim_scores: dict):
    dims = standard["scoring"]["dimensions"]
    total_w = 0.0
    acc = 0.0
    detail = []
    for d in dims:
        k = d["key"]
        w = d["weight"]
        s = float(dim_scores.get(k, 0))
        acc += s * w
        total_w += w
        detail.append(f"{d['name']}:{s:.0f}（权重{int(w*100)}%）")
    norm = total_w if total_w else 1.0
    final = round(acc / norm, 2)
    return final, " | ".join(detail)


def init_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
    if not DEDUP_PATH.exists():
        DEDUP_PATH.write_text(json.dumps({"downloaded": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已初始化：{CSV_PATH}\n            {DEDUP_PATH}")


def score_cmd(standard_path, candidate_path):
    standard = load_standard(standard_path)
    cand = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    final, detail = compute_score(standard, cand.get("dim_scores", {}))
    rejected = cand.get("rejected", False)
    print("=" * 50)
    print(f"候选人：{cand.get('姓名','?')} ｜ 岗位：{cand.get('求职意向岗位','?')}")
    print(f"分项明细：{detail}")
    print(f"加权总分：{final} / 10  ｜ 一票否决：{rejected}")
    print("=" * 50)
    return final, detail


def add_cmd(standard_path, candidate_path):
    standard = load_standard(standard_path)
    cand = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    final, detail = compute_score(standard, cand.get("dim_scores", {}))
    rejected = cand.get("rejected", False)
    status = "已拒（否决）" if rejected else ("待业务复核" if final >= 8 else "待HR复审")
    row = {
        "姓名": cand.get("姓名", ""), "性别": cand.get("性别", ""), "年龄": cand.get("年龄", ""),
        "手机号": cand.get("手机号", ""), "邮箱": cand.get("邮箱", ""), "求职意向岗位": cand.get("求职意向岗位", ""),
        "毕业院校": cand.get("毕业院校", ""), "学历层次": cand.get("学历层次", ""), "专业名称": cand.get("专业名称", ""),
        "是否985/211": cand.get("是否985/211", ""), "工作年限": cand.get("工作年限", ""), "是否大厂背景": cand.get("是否大厂背景", ""),
        "工作经历摘要": cand.get("工作经历摘要", ""), "技能清单": cand.get("技能清单", ""),
        "当前状态": status, "总分": final, "分项明细": detail,
        "总结评价": cand.get("总结评价", ""), "建议问题": cand.get("建议问题", ""),
        "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    init_data()
    with CSV_PATH.open("a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(row)
    print(f"已写入候选人 {row['姓名']}（总分 {final}，状态：{status}）-> {CSV_PATH}")


def report_cmd(min_score):
    if not CSV_PATH.exists():
        print("尚无候选人数据，请先 init / add。"); return
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    hits = [r for r in rows if r.get("总分") and float(r["总分"]) >= min_score]
    print(f"达到 {min_score} 分及以上的候选人（共 {len(hits)} 人）：")
    for r in hits:
        print(f"  - {r['姓名']} ｜ {r['求职意向岗位']} ｜ 总分 {r['总分']} ｜ {r['当前状态']}")


def demo():
    init_data()
    std = find_standard("产品经理") or (STD_DIR / "product_manager.json")
    sample = {
        "姓名": "张三", "性别": "男", "年龄": 28, "手机号": "13800000000", "邮箱": "zhangsan@example.com",
        "求职意向岗位": "产品经理", "毕业院校": "某211高校", "学历层次": "本科", "专业名称": "计算机科学与技术",
        "是否985/211": "211", "工作年限": 5, "是否大厂背景": "是",
        "工作经历摘要": "主导 B 端 SaaS 订单系统 0-1，上线后转化率提升 18%",
        "技能清单": "需求分析,PRD,数据分析,项目管理",
        "dim_scores": {"education_match": 8, "experience_relevance": 9, "skill_fit": 8,
                       "project_depth": 9, "stability": 7, "potential": 8},
        "总结评价": "具备 5 年 B 端产品经验，主导过复杂业务系统并取得量化成果，匹配度高。",
        "建议问题": "1) 订单系统 0-1 的关键决策 2) 如何衡量需求优先级 ...",
    }
    cand_path = DATA_DIR / "_demo_candidate.json"
    cand_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    add_cmd(std, cand_path)
    report_cmd(8)
    cand_path.unlink(missing_ok=True)
    # 自清理：demo 跑完把 CSV 还原为表头，避免重复运行污染数据
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
    print("\nDemo 完成（已自清理数据，CSV 仅保留表头）。生产使用：把简历放入 inbox/，由 WorkBuddy 加载 hr-resume 技能执行提取与评分，")


def main():
    ap = argparse.ArgumentParser(description="HR-Workflow 本地评分/入库引擎")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("init")
    p_score = sub.add_parser("score"); p_score.add_argument("--standard", required=True); p_score.add_argument("--candidate", required=True)
    p_add = sub.add_parser("add"); p_add.add_argument("--standard", required=True); p_add.add_argument("--candidate", required=True)
    p_rep = sub.add_parser("report"); p_rep.add_argument("--min", type=float, default=8)
    sub.add_parser("demo")
    p_find = sub.add_parser("find-standard"); p_find.add_argument("--role", required=True)

    args = ap.parse_args()
    if args.cmd == "init":
        init_data()
    elif args.cmd == "score":
        score_cmd(Path(args.standard), Path(args.candidate))
    elif args.cmd == "add":
        add_cmd(Path(args.standard), Path(args.candidate))
    elif args.cmd == "report":
        report_cmd(args.min)
    elif args.cmd == "demo":
        demo()
    elif args.cmd == "find-standard":
        sp = find_standard(args.role)
        print(sp or f"未找到岗位「{args.role}」的标准，可用 _template.json 新建。")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
