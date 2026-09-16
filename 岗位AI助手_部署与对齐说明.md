# 岗位 AI 助手 · 双环境部署与对齐说明

> 来源：基于《2个岗位AI提示词大全.pdf》（行政与综合办公 18 任务 + 人力资源 28 任务，共 46 任务）
> 方法：参考 DeepSeek 分享链接的方法论——**岗位 Agent → 任务 Skill → 跨任务 Workflow → 通用节点/知识库/权限治理**
> 目标：为 MiniYuxi 与 WorkBuddy 两套环境各生成可直接部署的 skill + 全自动工作流，覆盖"提示词解析 → 任务自动执行"端到端闭环。

---

## 一、总体架构（端到端闭环）

```
PDF ──解析──▶ skills/task_library.json（46 任务结构化）
                    │
        ┌───────────┴────────────┐
   MiniYuxi 环境                  WorkBuddy 环境
   core/taskflow.py               ~/.workbuddy/skills/<role>/SKILL.md
   + /api/taskflow/*              + 本机模型执行 6 步闭环
   + 前端「岗位工作台」            + 复用已有 skill/连接器
        │                                  │
   解析→核验→变量注入→LLM→格式化→审计(HITL)── 同一套 6 步逻辑
```

**关键共识**：两个岗位共 46 个任务模板 100% 同构（适用场景/需要准备/文件与操作/主提示词/输出结果/输出格式/建议追问/预期输出）。
因此不做"46 个独立 skill"，而是**每个岗位 1 个角色级 skill + 一个任务库 + 一个执行引擎**，覆盖全部任务——避免 skill 爆炸。

---

## 二、交付文件清单

### MiniYuxi 侧（项目目录 `14_自研MiniYuxi/`）
| 文件 | 作用 |
| --- | --- |
| `scripts/build_task_library.py` | 提示词解析器：PDF 抽取文本 → `task_library.json`（可重复运行） |
| `skills/task_library.json` | 46 任务结构化库（闭环数据底座） |
| `skills/admin_office/SKILL.md` | 行政角色级 skill（18 任务目录 + 2 示例 + 规格） |
| `skills/hr/SKILL.md` | HR 角色级 skill（28 任务目录 + 3 示例 + 规格） |
| `core/taskflow.py` | 执行引擎：build_dag + run_task（集成 gateway LLM / orchestration / SOC 审计） |
| `workflows/admin_office.yaml` `workflows/hr.yaml` | 端到端 DAG 静态蓝本（start→knowledge→llm→tool→approval→end） |
| `api.py`（增量） | `/api/taskflow/roles|list|workflow/{id}|run` 四个端点 |
| `web/wb_workbench.js`（增量） | 顶部导航「岗位工作台」入口 + 任务选择/运行面板 |
| `web/index.html`（增量） | `fm-form`/`fm-sub` 等样式 |

### WorkBuddy 侧（已落地）
| 路径 | 作用 |
| --- | --- |
| `~/.workbuddy/skills/hr-prompt-library/` | SKILL.md + task_library.json + workflow.yaml |
| `~/.workbuddy/skills/admin-office-prompt-library/` | 同上（行政） |

> 两环境 SKILL.md 共用同一 frontmatter 格式（name/description/trigger/toolset），MiniYuxi 的 `skills_catalog.py` 与 WorkBuddy 均可直接加载。

---

## 三、MiniYuxi 部署步骤
1. 环境变量齐备（LLM/EMB/DOUBAO）后，双击 `start_miniyuxi.bat`（或 `run.py`）。
2. 服务启动自动 `taskflow.init()` 加载任务库，并注册两个角色 skill。
3. 前端点「岗位工作台」→ 选岗位 → 选任务 → 填变量/材料 → 运行（支持试运行 dry）。
4. 程序化调用：`POST /api/taskflow/run {"task_id":"hr_05","variables":{...},"materials":[...]}`。

## 四、WorkBuddy 部署步骤
- 已自动落地到 `~/.workbuddy/skills/`，WorkBuddy 重启即加载。
- 触发后读取本目录 `task_library.json`，按 `task_id` 取提示词，用本机模型执行 6 步闭环。

---

## 五、与 WorkBuddy 已有能力对齐（复用，不重造）

| 本方案模块 | 对应 WorkBuddy 已有能力 | 复用方式 |
| --- | --- | --- |
| HR·批量筛选简历（hr_07） | **hr-resume**（简历自动化筛选流水线） | 直接复用其 inbox/评分标准/飞书多维表写入；本库仅提供提示词与触发 |
| HR·撰写人事制度（hr_25） | **biz-hr-handbook**（员工手册/人事制度） | 制度起草走 biz-hr-handbook，本库提供制度类任务入口 |
| HR·员工关系/离职/劳动争议 | **labor-dispute-workflow** + **hr-compliance-toolkit** | 涉诉/合规场景转交这两个工作流，本库做前置分流 |
| HR 全模块 | **hr-department** / **hr-ai-assistant-builder** | 作为角色能力底座 |
| 行政·公文/通知/纪要 | WorkBuddy 通用文档/邮件/表格 skill | 结果稿由本库生成，润色/排版交给通用 skill |
| 材料采集 | **邮箱连接器** | 自动采集简历/公文草稿 |
| 结果回写台账 | **飞书多维表连接器**（wecomcli-sheet/smarttable） | 候选人/行政台账写入多维表 |

**专家对齐**：MiniYuxi `core/experts.py` 已内置 HR 专家（system_prompt 视同角色人设）；WorkBuddy 侧可用 `expert-manager` 挂载同款 HR 专家，作为"需要读取的材料"注入。

---

## 六、验证结果（MiniYuxi 实测）
- 解析：PDF → 46 任务全部结构化成功（行政 18 + HR 28）。
- 端点：`/api/taskflow/roles|list|workflow|run` 全部 200。
- DAG：`build_dag` 产出 6 节点闭环（start→knowledge→llm→tool→approval→end）。
- 试运行(dry)：材料核验、变量注入、审计留痕均正确。
- **真实 LLM 调用**：`hr_05 撰写岗位JD` 产出 2422 字结构化 JD（列文件→查缺失→事实/判断/假设分离），已写入 SOC 审计链。

---

## 七、风险与注意
- 🔴 **敏感数据**：HR/制度/薪酬任务涉个人信息，强制人工确认闸门（HITL）+ 审计；勿自动对外发送。
- 🟡 **外部连接器**：邮箱/飞书连接器需用户在 WorkBuddy 内授权后才会启用，否则走本地文件模式。
- 🟡 **任务库漂移**：PDF 若有更新，重跑 `scripts/build_task_library.py` 重新生成 `task_library.json`（已解析文本在 `资料/pdf_extract.txt`）。
- 🟢 **三指纹保护**：本方案新增 `core/taskflow.py`、改写 `api.py`/`wb_workbench.js`/`index.html`，**未改动** `db.py`/`rag.py`/`agent.py`。
