# `.scratch/` — 本地 Markdown 工单跟踪器

本仓库用**本地 Markdown** 作为 issue tracker（`triage` 技能未安装，故不使用五角色标签，状态用 `open`/`claimed`/`done`）。

约定（详见 `docs/agents/issue-tracker.md`）：

- 一个特性一个目录：`.scratch/<feature-slug>/`
- 设计规格：`.scratch/<feature-slug>/spec.md`
- 实现工单：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 起编号，每票一个文件（不合并）
- 依赖边写在工单顶部 `Blocked by: NN, NN`
- 会话（wayfinding）地图：`.scratch/<effort>/map.md`

由 `to-spec` 写 spec、`to-tickets` 拆工单。
