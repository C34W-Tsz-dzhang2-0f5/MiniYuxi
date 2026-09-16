# HR-Workflow ｜ AI 招聘流水线（基于 WorkBuddy）

把招聘流程中**规则明确、可标准化**的环节自动化：简历采集 → 信息提取 → 评分 → 入库 → 推送高分候选人。HR 只做「挑人」。

> 来源文章：叶小钗《我用 WorkBuddy 搭了一套 AI 招聘流水线》https://mp.weixin.qq.com/s/9iCOjCrczbyGp3n7Mu0GXw
> 配套知识库：`../knowledge-base/hr-ai-recruitment-pipeline.md`

## 目录结构
```
HR-Workflow/
├── SKILL.md                  # hr-resume 技能（WorkBuddy 直接加载执行）
├── scoring_standards/        # 各岗位评分标准（JSON，机器可读）+ INDEX.md 导航
│   ├── _template.json        # 评分标准模板
│   ├── product_manager.json  # 产品经理
│   ├── frontend_engineer.json# 前端工程师
│   └── INDEX.md              # 岗位评分标准地址导航
├── data/
│   ├── candidates.csv        # 候选人跟踪表（飞书多维表的本地替代）
│   └── downloaded_records.json # 简历去重记录
├── scripts/
│   └── pipeline.py           # 本地确定性评分/入库引擎（可离线、可审计）
├── inbox/                    # 简历投放文件夹（放示例简历 sample_zhangsan.txt）
└── README.md
```

## 两种运行方式

### A. WorkBuddy 技能模式（推荐，完整流水线）
在 WorkBuddy 中打开本项目目录，加载 `SKILL.md`（`hr-resume` 技能），说一句：
> 「跑一下招聘流水线，处理 inbox 里的简历」

技能会：扫描 inbox → 结构化提取 → 按岗位标准评分（含分项明细）→ 写入 `data/candidates.csv` → 把 ≥8 分候选人标记为「待业务复核」。
若已连接**飞书多维表 / 邮箱连接器**，技能自动切换为连接器模式（邮件采集 + 飞书入库），无需改代码。

### B. 本地引擎模式（离线验证 / 校准 / 审计）
用托管 Python 直接运行，无需外部 LLM（评分数学确定性、可解释）：

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe"
cd HR-Workflow
$PY scripts/pipeline.py init                       # 初始化数据文件
$PY scripts/pipeline.py demo                       # 用内置示例跑一遍
$PY scripts/pipeline.py find-standard --role 产品经理   # 按岗位找标准
$PY scripts/pipeline.py score --standard scoring_standards/product_manager.json --candidate data/_demo_candidate.json
$PY scripts/pipeline.py add   --standard scoring_standards/product_manager.json --candidate path/to/candidate.json
$PY scripts/pipeline.py report --min 8             # 列出高分候选人
```
候选人 JSON 需含 `dim_scores`（6 个维度 1-10 分），详见 `pipeline.py` 顶部注释。

## 公平性护栏（必读）
- 评估前**盲筛**：遮蔽姓名/性别/年龄/照片/邮编。
- 评分**必须输出分项明细**（本技能与 pipeline.py 均已实现），便于人工复核与审计。
- 定期做**差异影响分析**（four-fifths / 80% 规则）。
- AI 只做标准化，**最终决策须人工复核**；保留评分所用标准版本与审计日志。

## 落地建议
渐进式：先跑通高频环节（提取+评分+入库），稳定后再接入面试预约与通知；评分标准随岗位要求持续校准。
