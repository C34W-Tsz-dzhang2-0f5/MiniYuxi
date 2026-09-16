---
name: hr-resume
description: HR 简历自动化筛选流水线（自包含技能）。读取简历（本地 inbox 或邮箱连接器），结构化提取候选人信息，按岗位评分标准打分并生成总结与面试问题，写入候选人跟踪表（本地 CSV 或飞书多维表），并把高分简历（≥8分）推送给业务负责人。触发词：招聘流水线、简历筛选、简历评分、hr-resume、自动收简历、人才库入库、AI 招聘。
---

# HR 简历自动化筛选流水线（hr-resume，自包含技能）

把招聘流程中**规则明确、可标准化**的环节自动化：简历采集 → 信息提取 → 评分 → 入库 → 推送高分候选人。HR 只做「挑人」。
核心原则：**把主观判断转化为客观规则，规则越清晰，AI 执行越精准。**

> 本技能**自带脚手架、路径自包含**，安装即可用，所有数据默认存放在技能目录内：
> `C:\Users\Administrator\.workbuddy\skills\hr-resume\`
> 下设 `inbox/`（简历投放）、`scoring_standards/`（评分标准）、`data/`（候选人表+去重）、`scripts/pipeline.py`（离线评分引擎）。

---

## 处理流程（严格按顺序执行）

### 步骤 1 ｜ 采集简历
- **本地模式（默认）**：扫描 `C:\Users\Administrator\.workbuddy\skills\hr-resume\inbox\` 下未处理的简历（PDF/Word/图片/文本）。
- **连接器模式**：若已连接**邮箱连接器**，拉取新邮件；按主题规则 `应聘<岗位>-<姓名>` 判定是否为简历投递；仅下载带附件邮件。
- **去重**：以「邮箱地址」为唯一 ID，处理前先查 `data/downloaded_records.json`；已存在则跳过，否则处理并写入去重清单。
- ⚠️ 采集频率不要过高，避免浪费积分（建议定时每日 1–2 次）。

### 步骤 2 ｜ 结构化提取
读取简历内容（PDF/Word 均能处理），按以下结构提取：

```
姓名 / 性别 / 年龄 / 手机号 / 邮箱 / 求职意向岗位 / 毕业院校 / 学历层次 /
专业名称 / 是否985/211 / 工作年限 / 是否大厂背景 / 工作经历摘要 / 技能清单 / 当前状态
```

**提取提示词（直接用）**：
```
帮我按照如下结构提取简历信息：
{
  "姓名":"", "性别":"", "年龄":"", "手机号":"", "邮箱":"",
  "求职意向岗位":"", "毕业院校":"", "学历层次":"", "专业名称":"",
  "是否985/211":"", "工作年限":"", "是否大厂背景":"", "工作经历摘要":"", "技能清单":""
}
部分字段简历中可能不直接存在，需根据已有基础信息推断（如是否985/211、工作年限、是否大厂背景）。
对于不确定的信息，不要强行填充，填写"未知"。
```
- 表字段名必须与上述结构**严格一致**，否则写入报错。

### 步骤 3 ｜ 定位评分标准
- 用 `求职意向岗位` 匹配 `C:\Users\Administrator\.workbuddy\skills\hr-resume\scoring_standards\<role_id>.json`（脚本按岗位名自动匹配）。
- 若无匹配：先按 `_template.json` 通用维度打分，并提示 HR「该岗位尚无专属标准，建议补充」。

### 步骤 4 ｜ 简历评分（关键步骤）
读取岗位评分标准打分。**评分准确性决定整套流程是否可用**，标准必须事先定义清楚。

**评分提示词（直接用）**：
```
根据候选人简历内容和岗位评分标准，对候选人进行简历打分，并输出总结评价与建议面试问题。

## 简历内容
{简历提取结果}

## 岗位评分标准
{对应 <role_id>.json 的 scoring 维度与权重}

## 输出要求
1. 每个维度给出 1-10 分，并输出【分项明细】（分数 + 简要理由）——必须可追溯。
2. 加权总分 1-10 分（按权重）。
3. 总结评价 150-200 字。
4. 结合简历内容生成最值得问的 5 个问题。
5. 若触发 knockout（一票否决项），明确标注并给 0 分结论。
```
- 维度与权重见各标准文件（通用：学历10% / 经验30% / 技能10% / 项目30% / 稳定性10% / 潜力10%）。
- **公平性护栏**：评分前开启盲筛（遮蔽姓名/性别/年龄/照片/邮编）；输出必须含分项明细，供人工复核与审计。

### 步骤 5 ｜ 存储候选人信息
- **本地模式**：追加写入 `C:\Users\Administrator\.workbuddy\skills\hr-resume\data\candidates.csv`，表结构与提取字段一致，并增加 `当前状态`、`总分`、`分项明细`、`总结评价`、`建议问题`、`处理时间`。
- **连接器模式**：若已连接**飞书多维表连接器**，写入「候选人简历信息表」（字段须一致）。

`data/candidates.csv` 表结构：
```
姓名,性别,年龄,手机号,邮箱,求职意向岗位,毕业院校,学历层次,专业名称,
是否985/211,工作年限,是否大厂背景,工作经历摘要,技能清单,当前状态,
总分,分项明细,总结评价,建议问题,处理时间
```

### 步骤 6 ｜ 推送高分候选人
- 总分 **≥ 8 分** 的简历，将「候选人信息 + 面试安排 + 建议问题」推送给业务负责人。
- 本地模式：在 CSV 标记 `当前状态=待业务复核`，并在对话中高亮列出高分名单。
- 连接器模式：通过 OA 消息 / 邮件连接器发送。

---

## 本地离线引擎（推荐用于校准/审计）
无需外部 LLM，评分数学确定性、可解释。用托管 Python 运行（评分由本步骤的维度分输入计算）：

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe"
cd C:/Users/Administrator/.workbuddy/skills/hr-resume
$PY scripts/pipeline.py init                       # 初始化数据文件
$PY scripts/pipeline.py demo                       # 内置示例跑一遍（会自动自清理）
$PY scripts/pipeline.py add --standard scoring_standards/product_manager.json --candidate path/to/candidate.json
$PY scripts/pipeline.py report --min 8             # 列出高分候选人
```
候选人 JSON 需含 `dim_scores`（6 个维度 1-10 分），详见 `scripts/pipeline.py` 顶部注释。

---

## 连接器接入（可选，需用户在 WorkBuddy 内连接）
- **邮箱连接器**：用于自动从邮箱采集简历附件。
- **飞书多维表连接器**：用于把候选人写入飞书多维表（替代本地 CSV）。
- 接入方式：在 WorkBuddy 连接器面板分别添加「邮箱」「飞书」并授权信任；本技能检测到连接器可用时自动切换为连接器模式，无需改代码。

## 落地与校准
- 渐进式：先跑通高频环节（提取+评分+入库），稳定后再扩展面试预约与通知。
- 持续校准：岗位要求/业务判断会变，评分标准需同步调整；若高分简历大量不符合业务预期，说明该岗位标准需修正。
- 审计：保留每次评分的分项明细与所用标准版本，便于差异影响分析（four-fifths 规则）。

## 配套文件
- `scoring_standards/` — 各岗位评分标准（JSON）+ 导航 INDEX.md
- `data/candidates.csv` — 候选人跟踪表
- `data/downloaded_records.json` — 去重记录
- `scripts/pipeline.py` — 本地确定性评分/入库引擎
- `inbox/` — 简历投放文件夹（含示例 sample_zhangsan.txt）
- `README.md` — 使用说明

## MiniYuxi 执行接入（已打通）
本技能已作为 **kind=skill 任务**接入 MiniYuxi 执行引擎（`core/taskflow.py::run_skill_task`），
不再是只读文本，而是可被真实调用的流水线：
- 任务 id：`hr_resume_01`（在 `skills/task_library.json`，`role=hr`）
- 链路：knowledge 读取简历 → llm(DeepSeek) 提取结构化候选人 JSON + 按标准逐项打分 →
  tool 调 `scripts/pipeline.py` 做确定性加权评分并写入 `data/candidates.csv` → approval(HITL) → end
- 调用方式（CLI）：
  `python scripts/run_taskflow.py run hr_resume_01 --real --model deepseek:deepseek-chat --role 产品经理`
  （`--resume <简历路径>` 可指定简历；不传则自动扫描 `inbox/`）
- 调用方式（API）：`POST /api/taskflow/run` 传 `task_id=hr_resume_01`、`model=deepseek:deepseek-chat`、
  `variables={"role_name":"产品经理"}`、`materials=[简历路径]`
- 确定性评分引擎为纯标准库 Python，可离线运行、可审计；LLM 仅做「标准化提取」，最终评分与入库由 `pipeline.py` 完成。
- 注：原 WorkBuddy 版的邮箱/飞书连接器模式在 MiniYuxi 暂未接入，当前为本地 inbox + CSV 模式。
