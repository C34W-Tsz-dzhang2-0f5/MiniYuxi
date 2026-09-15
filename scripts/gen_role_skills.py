# -*- coding: utf-8 -*-
"""根据 skills/task_library.json 生成两个岗位级 SKILL.md（MiniYuxi 与 workbuddy 双兼容）。

每个岗位 = 一个角色级 skill（frontmatter: name/description/trigger/toolset），
body 含：适用岗位 / 触发条件 / 输入 / 输出 / 执行逻辑 + 任务目录 + 高频示例（真实提示词）。
通过 taskflow 引擎 + task_library.json 覆盖该岗位全部任务，避免 skill 爆炸。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "skills", "task_library.json")

ROLE_META = {
    "admin_office": {
        "name": "admin-office",
        "display": "行政与综合办公",
        "toolset": "admin",
        "trigger": "行政、公文、通知、会议纪要、会议议程、请示报告、接待方案、差旅、固定资产、行政制度、行政周报、行动事项、行政助手、admin",
        "examples": ["admin_office_01", "admin_office_04"],
        "expert": "行政与综合办公专家",
    },
    "hr": {
        "name": "hr-prompt-library",
        "display": "人力资源（HR）",
        "toolset": "hr",
        "trigger": "HR、人力资源、招聘、JD、简历筛选、面试、入职、培训、绩效、薪酬、员工关系、人事制度、人力规划、离职、HR周报、hr",
        "examples": ["hr_05", "hr_07", "hr_01"],
        "expert": "HR／人力资源专家",
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
    return (
        f"### 示例：{t['title']}（{t['id']}）\n\n"
        f"**适用场景**：{t['scenario']}\n\n"
        f"**需要准备（输入）**：\n{inp}\n\n"
        f"**主提示词（直接可用，[填写] 由系统按变量注入）**：\n```\n{pt}\n```\n\n"
        f"**输出格式**：\n{outs}\n\n"
        f"**建议追问（可一键继续）**：\n{fol}\n"
    )


def gen_role(role):
    meta = ROLE_META[role]
    tasks = load_tasks(role)
    example_ids = meta["examples"]
    ex_blocks = "\n".join(example_block(t) for t in tasks if t["id"] in example_ids)

    body = f"""# {meta['display']} 岗位 AI 助手（角色级 Skill）

把《2个岗位AI提示词大全》中「{meta['display']}」岗位的 {len(tasks)} 个高频任务，
转化为一个可在 MiniYuxi 与 WorkBuddy 双环境直接部署的角色级 skill。
通过 `taskflow` 引擎 + `skills/task_library.json`（由 PDF 解析生成）覆盖全部任务，
避免为每个任务单独建 skill 导致的爆炸式膨胀。

---

## 一、Skill 规格（必须明确）

- **适用岗位**：{meta['display']}（含：{", ".join(_role_titles(role))}）
- **触发条件**：用户说出台词命中本 skill 的 trigger（如"{meta['trigger'].split(',')[0]}…"），
  或在 MiniYuxi「岗位工作台」中选择本岗位任务。
- **输入**：
  1. `task_id`：从下方任务目录选择（如 `admin_office_01`）；
  2. `variables`：企业/部门、本次目标、使用对象、时间范围与截止时间（对应提示词中的 [填写]）；
  3. `materials`：本次任务相关材料/附件清单（公文草稿、数据表、JD、简历等）。
- **输出**：
  1. 材料完整性核验报告（已读取文件 + 缺失项，缺失不编造）；
  2. 按「输出格式」生成的正式结果稿（结论摘要 → 表格/清单 → 待确认/风险/行动项）；
  3. 行动项四列表（事项 / 负责人 / 截止时间 / 验收标准）+ 建议追问按钮。
- **执行逻辑（端到端闭环 6 步）**：
  1. 解析：从 `task_library.json` 按 `task_id` 取出任务的全部字段（提示词解析）；
  2. 材料核验：列出已读取材料，比对「需要准备」，标注缺失项，禁止编造；
  3. 注入：把 `variables` 填入提示词 [填写] 占位符，附材料清单；
  4. 执行：调用 LLM 网关（MiniYuxi `gateway.chat` / WorkBuddy 模型）运行主提示词；
  5. 格式化：套用该任务的「输出格式」，生成行动项四列表；
  6. 闭环：产出结果 + 建议追问，写入 SOC 审计链，重大人事/制度动作经人工确认闸门（HITL）后放行。

---

## 二、任务目录（共 {len(tasks)} 项，均可一键执行）

{catalog_table(tasks)}

> 调用方式（MiniYuxi）：`POST /api/taskflow/run` 传 `{{"task_id":"<id>","variables":{{...}},"materials":[...]}}`；
> 或前端「岗位工作台」选任务 → 填变量 → 运行。
> 调用方式（WorkBuddy）：读取 `skills/task_library.json`，按 `task_id` 取提示词，用本机模型执行上述 6 步。

---

## 三、高频示例（真实提示词，开箱即用）

{ex_blocks}

---

## 四、与 WorkBuddy / 专家 / 连接器对齐

- **MiniYuxi 侧**：`skills_catalog.py` 自动扫描本 `SKILL.md` 注册；`core/taskflow.py` 提供执行引擎；
  `core/experts.py` 已内置 HR 专家（system_prompt 视同本 skill 角色人设）。
- **WorkBuddy 侧**：本 `SKILL.md` 格式与 WorkBuddy 完全兼容，可直接放入
  `~/.workbuddy/skills/<name>/SKILL.md` 使用；可复用已有 `hr-resume`（简历筛选）、
  `biz-hr-handbook`（员工手册）、`labor-dispute-workflow`（劳动争议）等 skill 作为补充。
- **连接器复用**：若连接「邮箱连接器」可自动采集招聘简历/公文草稿；连接「飞书多维表」可把
  候选人/行政台账写入多维表（对齐 hr-resume 的连接器模式）。
- **权限与审计**：HR、制度、薪酬类任务涉敏感数据，强制人工确认闸门 + SOC 审计留痕，
  不自动对外发送。
"""

    fm = (
        "---\n"
        f"name: {meta['name']}\n"
        f"description: {meta['display']}岗位 AI 助手——覆盖 {len(tasks)} 个高频任务（公文会议/行政事务/人力规划/招聘/绩效薪酬/员工关系等），"
        "通过提示词解析+任务流引擎实现从任务选择到结果生成、审计留痕的端到端闭环。触发词："
        f"{meta['trigger']}。\n"
        f"trigger: {meta['trigger']}\n"
        f"toolset: {meta['toolset']}\n"
        "---\n\n"
    )
    out = os.path.join(ROOT, "skills", role, "SKILL.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(fm + body)
    print("written", out, len(body), "chars")


def _role_titles(role):
    d = json.load(open(LIB, encoding="utf-8"))
    # 取该角色块第一行的适用岗位称呼前 4 个
    for blk_role, meta in d["roles"].items():
        if blk_role == role:
            line = meta.get("role_line", "")
            parts = [p.strip() for p in line.replace("、", ",").split(",") if p.strip()]
            return parts[:5]
    return []


if __name__ == "__main__":
    for r in ROLE_META:
        gen_role(r)
