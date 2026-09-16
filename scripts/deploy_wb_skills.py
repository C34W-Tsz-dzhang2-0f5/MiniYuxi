# -*- coding: utf-8 -*-
"""将本机 WorkBuddy user-level skills 的 SKILL.md 文本层部署进 MiniYuxi。

裁剪原则（Tier-1 强相关）：仅 HR / 行政 / 法律 / 办公文档 领域，纯 SKILL.md 文本层。
- 不含需外部服务的 skill（github/ding/wecom/浏览器桥/逆向等）
- 不含无关 skill（pua/mama/storage/逆向工程等）
- 不覆盖 MiniYuxi 自有 5 个 skill（admin_office/hr/offboard_review/policy_qa/recruit_sop）
- 仅拷贝 SKILL.md（文本层注册）；含 scripts/依赖的 skill 仅注册知识，执行需后续接入。
"""
import os
import re
import shutil

WB_SKILLS = os.path.expanduser(r"C:\Users\Administrator\.workbuddy\skills")
MY_SKILLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

# MiniYuxi 自有的、不可覆盖
PROTECTED = {"admin_office", "hr", "offboard_review", "policy_qa", "recruit_sop"}

# Tier-1 候选（目录名）。__skillhub 后缀会被去除。
CANDIDATES = [
    # --- HR 核心 ---
    "hr-prompt-library", "admin-office-prompt-library",
    "hr-resume", "hr-resume-screener__skillhub",
    "hr-department__skillhub", "hr-compliance-toolkit__skillhub",
    "hr-operations-team__skillhub", "hr-ai-assistant-builder",
    "hr-model-distill", "hrssc__skillhub",
    "biz-hr-handbook__skillhub", "biz-jd-resume__skillhub",
    "smart-recruitment-master", "job-description-generator",
    # --- 法律核心 ---
    "labor-dispute-workflow", "legal-article-retrieval",
    "legal-concept-comprehension", "legal-document-summarization",
    "legal-element-extraction", "legal-norm-validity-check",
    "legal-risk-assessment", "legal-terminology",
    "judicial-value-judgment", "other-legal-retrieval",
    "case-lifecycle-planning", "case-retrieval",
    "conflict-resolution", "dispute-issue-identification",
    "evidence-evaluation", "formal-legal-consequence",
    "internal-compliance-risk-identification", "judgment-document-generation",
    "trial-scheduling-and-deadline-monitoring", "billing-and-litigation-budget",
    "administrative-value-judgment",
    # --- 办公文档 ---
    "docx-beautify-pdf", "gongwenformat-pro__skillhub",
    "minimax-docx", "minimax-pdf", "wpscli",
]

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def parse_name(text: str):
    m = FM_RE.match(text)
    if not m:
        return None
    for line in m.group(1).splitlines():
        s = line.strip()
        if s.startswith("#") or ":" not in s:
            continue
        k, v = s.split(":", 1)
        if k.strip().lower() == "name":
            return v.strip().strip('"').strip("'")
    return None


def sanitize(d: str) -> str:
    d = d.replace("__skillhub", "").strip()
    d = d.lower().replace("-", "_").replace(" ", "_")
    return d or d


def main():
    copied, missing, parsed_ok, parsed_bad, skipped_protected = [], [], [], [], []
    for src_dir in CANDIDATES:
        src = os.path.join(WB_SKILLS, src_dir, "SKILL.md")
        if not os.path.isfile(src):
            missing.append(src_dir)
            continue
        text = open(src, encoding="utf-8-sig", errors="ignore").read()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        name = parse_name(text)
        dest_folder = sanitize(src_dir)
        if dest_folder in PROTECTED:
            skipped_protected.append(dest_folder)
            continue
        dest_dir = os.path.join(MY_SKILLS, dest_folder)
        os.makedirs(dest_dir, exist_ok=True)
        # 归一化：去 BOM(utf-8-sig)、统一换行，确保 MiniYuxi 正则能解析
        raw = open(src, encoding="utf-8-sig", errors="ignore").read()
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        open(os.path.join(dest_dir, "SKILL.md"), "w", encoding="utf-8").write(raw)
        copied.append(f"{src_dir} -> {dest_folder}")
        if name:
            parsed_ok.append(dest_folder)
        else:
            parsed_bad.append(dest_folder)

    print(f"=== MiniYuxi Skill 部署报告 (Tier-1) ===")
    print(f"拷贝成功: {len(copied)}")
    for c in copied:
        print(f"  + {c}")
    print(f"\n源缺失 SKILL.md (跳过): {len(missing)} -> {missing}")
    print(f"frontmatter 解析有 name: {len(parsed_ok)}")
    print(f"frontmatter 解析缺 name: {len(parsed_bad)} -> {parsed_bad}")
    print(f"受保护未覆盖: {skipped_protected}")


if __name__ == "__main__":
    main()
