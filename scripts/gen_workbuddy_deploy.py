# -*- coding: utf-8 -*-
"""生成 WorkBuddy 侧部署：把岗位任务流 skill 落地到 ~/.workbuddy/skills/。

与 MiniYuxi 的区别：
- MiniYuxi 走 /api/taskflow/*（taskflow 引擎 + gateway + 审计）；
- WorkBuddy 走本机模型直接执行 6 步闭环，并复用 WorkBuddy 已有 skill 与连接器。
两者共用同一份 task_library.json（提示词解析产物）与同一套 SKILL.md 结构。
"""
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "skills", "task_library.json")
WB = os.path.expanduser("~/.workbuddy/skills")

ROLE_META = {
    "admin_office": {
        "name": "admin-office-prompt-library",
        "display": "行政与综合办公",
        "toolset": "admin",
        "wb_skills": "（可配合 WorkBuddy 通用文档/邮件/表格 skill）",
        "wb_connectors": "邮箱连接器（采集公文/通知草稿）、飞书多维表（写行政台账）",
    },
    "hr": {
        "name": "hr-prompt-library",
        "display": "人力资源（HR）",
        "toolset": "hr",
        "wb_skills": "hr-resume（简历筛选）、biz-hr-handbook（员工手册）、labor-dispute-workflow（劳动争议）、hr-compliance-toolkit（合规）、hr-department",
        "wb_connectors": "邮箱连接器（采集简历/公文）、飞书多维表（写候选人/人事台账）",
    },
}


def load_tasks(role):
    d = json.load(open(LIB, encoding="utf-8"))
    return [t for t in d["tasks"] if t["role"] == role]


def catalog_table(tasks):
    lines = ["| 序号 | 模块 | 任务 | 适用场景 |", "| --- | --- | --- | --- |"]
    for i, t in enumerate(tasks, 1):
        sc = t["scenario"].replace("|", "／")
        lines.append(f"| {i} | {t['module']} | {t['title']} | {sc} |")
    return "\n".join(lines)


def example_block(t):
    pt = t["prompt_template"]
    outs = "\n".join(f"- {x}" for x in t["output_format"])
    fol = "\n".join(f"- {x}" for x in t["followups"])
    inp = "\n".join(f"- {x}" for x in t["inputs"])
    return (f"### 示例：{t['title']}（{t['id']}）\n\n"
            f"**适用场景**：{t['scenario']}\n\n**需要准备（输入）**：\n{inp}\n\n"
            f"**主提示词（直接可用，[填写] 由变量注入）**：\n```\n{pt}\n```\n\n"
            f"**输出格式**：\n{outs}\n\n**建议追问（可一键继续）**：\n{fol}\n")


def gen_role(role):
    meta = ROLE_META[role]
    tasks = load_tasks(role)
    ex_ids = {"admin_office": ["admin_office_01", "admin_office_04"],
              "hr": ["hr_05", "hr_07", "hr_01"]}[role]
    ex = "\n".join(example_block(t) for t in tasks if t["id"] in ex_ids)

    body = f"""# {meta['display']} 岗位 AI 助手（WorkBuddy 版 Skill）

把《2个岗位AI提示词大全》中「{meta['display']}」岗位的 {len(tasks)} 个高频任务，
转化为 WorkBuddy 可直接加载的角色级 skill。通过本技能目录下的 `task_library.json`
（由 PDF 解析生成）覆盖全部任务，避免为每个任务单独建 skill 的爆炸式膨胀。

---

## 一、Skill 规格

- **适用岗位**：{meta['display']}
- **触发条件**：用户提及本岗位工作（如 "{meta['display'][:4]}" 类任务）或命中下方 trigger 词。
- **输入**：① `task_id`（从任务目录选，如 `admin_office_01`）；② `variables`（企业/部门、本次目标、
  使用对象、时间范围与截止时间，对应提示词 [填写]）；③ `materials`（相关材料/附件）。
- **输出**：① 材料完整性核验（已读取 + 缺失项，缺失不编造）；② 按输出格式生成的正式结果稿
  （结论摘要 → 表格/清单 → 待确认/风险/行动项）；③ 行动项四列表（事项/负责人/截止时间/验收标准）
  + 建议追问按钮。
- **执行逻辑（端到端闭环 6 步）**：
  1. 解析：读取本技能目录 `task_library.json`，按 `task_id` 取出任务全部字段；
  2. 材料核验：列出已读取材料，比对"需要准备"，标注缺失（不编造）；
  3. 变量注入：把 `variables` 填入提示词 [填写] 占位符，附材料清单；
  4. 执行：用 WorkBuddy 本机模型运行主提示词（角色人设见示例 system 段）；
  5. 格式化：套用"输出格式"，生成行动项四列表；
  6. 闭环：产出结果 + 建议追问；HR/制度/薪酬等敏感动作须经人工确认后再对外发送。

---

## 二、任务目录（共 {len(tasks)} 项，均可一键执行）

{catalog_table(tasks)}

> 调用：读取本目录 `task_library.json`，按 `task_id` 取 `prompt_template`/`inputs`/`output_format`/`followups`，
> 用本机模型执行上述 6 步。

---

## 三、高频示例（真实提示词，开箱即用）

{ex}

---

## 四、与 WorkBuddy 已有能力对齐（复用，不重造）

- **可复用 skill**：{meta['wb_skills']}
- **可复用连接器**：{meta['wb_connectors']}
- **专家/知识库**：可挂载 HR 专家与《车务通案件追踪表》等知识库，作为"需要读取的材料"注入。
- **权限与审计**：HR、制度、薪酬类任务涉敏感数据，强制人工确认闸门 + 记录操作日志，不自动对外发送。
"""
    fm = ("---\n"
          f"name: {meta['name']}\n"
          f"description: {meta['display']}岗位 AI 助手——覆盖 {len(tasks)} 个高频任务（公文会议/行政事务/人力规划/招聘/绩效薪酬/员工关系等），"
          "通过提示词解析+6步闭环实现从任务选择到结果生成、人工确认的端到端自动化。触发词："
          f"{'、'.join(meta['display'][:2] for _ in range(1))}行政、公文、HR、招聘、绩效、员工关系、制度。\n"
          f"trigger: {meta['display'][:4]}、公文、通知、会议纪要、HR、招聘、绩效、员工关系、制度、admin、hr\n"
          f"toolset: {meta['toolset']}\n---\n\n")
    dest = os.path.join(WB, meta["name"])
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(fm + body)
    # 捆绑数据底座与 workflow
    shutil.copyfile(LIB, os.path.join(dest, "task_library.json"))
    wf = os.path.join(ROOT, "workflows", f"{role}.yaml")
    if os.path.exists(wf):
        shutil.copyfile(wf, os.path.join(dest, "workflow.yaml"))
    print("written", os.path.join(dest, "SKILL.md"))


if __name__ == "__main__":
    for r in ROLE_META:
        gen_role(r)
