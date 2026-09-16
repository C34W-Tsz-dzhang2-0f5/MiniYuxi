---
name: "biz-jd-resume"
slug: "biz-jd-resume"
displayName: "招聘JD与简历初筛"
description: "一键生成专业招聘 JD；输入简历+JD 给匹配度与风险点，辅助 HR 初筛。当用户要写招聘JD，或输入“帮我写一份后端工程师JD”“这份简历和这个岗位匹配吗”时使用。"
description_zh: "生成结构化招聘JD（职责/要求/加分项/我们提供），并对简历做匹配度、亮点、风险与面试建议分析。"
description_en: "Generate professional job descriptions and screen resumes with match score, strengths, and risks."
version: 1.0.0
agent_created: true
category: "business-ops"
tags:
  - 招聘
  - JD
  - 简历
  - HR
  - 初筛
capability: recruitment_screening
pricing:
  model: free
  amount_fen: 0
---

# 招聘 JD 生成 + 简历初筛

一键生成专业招聘 JD；输入简历+JD 给匹配度与风险点，辅助 HR 初筛。

## 何时使用
- 用户要写招聘JD、职位描述
- 用户要评估简历与岗位的匹配度
- 用户输入“帮我写一份后端工程师JD”“这份简历和这个岗位匹配吗”

## 工作流程
### JD 生成
1. 收集：岗位名、级别、团队/公司、核心职责、任职要求、亮点（薪资/福利/成长）。
2. 输出结构化 JD：职责、要求（硬性/软性）、加分项、我们提供、应聘方式。
3. 语言专业、避免歧视性表述，突出吸引力。

### 简历初筛
1. 输入简历文本 + 目标 JD。
2. 输出：
   - 综合匹配度（高/中/低 + 百分比估计）
   - 亮点（与岗位强相关的经历）
   - 风险/疑点（空窗期、频繁跳槽、经历与要求不符）
   - 面试建议问题（针对性验证）

## 输出要求
- JD 不含性别/年龄等歧视用语
- 初筛结论有据可依，标注“需面试确认”项

## 参考
- JD 模板见 `references/template.md`
