# 岗位评分标准导航（地址导航）

> WorkBuddy 在评分时据此快速定位岗位标准。当前为本地文件模式；
> 若已连接飞书/文档连接器，可把每个标准改为对应文档链接。

| 岗位 | 标准文件（本地） | 备注 |
|---|---|---|
| 产品经理 | `scoring_standards/product_manager.json` | 已配置 |
| 前端工程师 | `scoring_standards/frontend_engineer.json` | 已配置 |
| （新增岗位） | `scoring_standards/<role_id>.json` | 复制 `_template.json` 修改 |

## 新增岗位评分标准步骤
1. 复制 `_template.json` 重命名为 `<role_id>.json`。
2. 填写 `role`、`description`、`knockout`、`scoring.dimensions` 的权重与说明。
3. 权重之和应 = 1.0（脚本会做归一化，但不建议依赖）。
4. 在此 INDEX 增加一行。
5. 在 `HR-Workflow/SKILL.md` 的岗位映射中补充（若用本地文件模式，脚本按 `求职意向岗位` 自动匹配 `<role_id>.json`，无需改代码）。

## 评分标准维护原则
- 由 HR 与业务负责人**共同商定**并协同维护。
- 标准变更需记录版本与日期（见各 JSON 的 `fairness_notes` / 注释）。
- 评估前开启盲筛（遮蔽 PII）；评分输出**必须含分项明细**。
