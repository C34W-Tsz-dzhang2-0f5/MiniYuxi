# 简道云《HRM人事管理系统》→ MiniYuxi 整体迁移方案

> **结论**：49 张表单、945 个主字段、19 个子表单、101 个视图、183 个权限组已通过已连接的浏览器扩展**全量逆向抓取**并落盘为 `core/hrm_schema.json`，MiniYuxi 侧已生成数据驱动引擎 `core/hrm.py` + 10 个 REST 路由 + 导入器 `tools/import_hrm_data.py`，结构与字段类型 1:1 复刻，**可直接执行**。审批节点图与公式字段两项存在保真度缺口（见风险表），已明确边界与补抓路径。

- 源应用：简道云《HRM人事管理系统》 `appId=6aaf4ffd3e5274a5665d4811`
- 目标：MiniYuxi（`14_自研MiniYuxi`），SQLite + FastAPI
- 生成日期：2026-09-21

---

## ⚠️ 风险提示与保真度分级

| 项 | 风险 | 敞口 | 说明 |
|---|---|---|---|
| 审批节点图（审批人/条件分支/多级） | 🔴 高 | 21/49 张流程表单 | `info_access` 只暴露流程 UI 开关，节点图在「流程设计」独立接口，本轮未抓到。已用通用状态机 `draft→pending→approved/rejected` 兜底 |
| 公式/计算字段 | 🟡 中 | 0 处 | 已全量扫描：49 张表单 `formEvents` 全为空、无任何 `formula`/`computeRule`/`trigger` 字段 → **源应用本身未使用公式字段**，故不存在丢失 |
| 数据字典（下拉选项来源） | 🟢 低 | 69 个 combo | 静态选项已抓入 `options`；异步来源（如「部门」取自部门岗位基础表）已抓入 `async_source`，建表期不强制约束 |
| 附件/图片/签名文件实体 | 🟡 中 | 13+1+16 字段 | 结构（JSON 数组）已还原，但**文件二进制未迁移**；需单独走附件下载 |
| 权限组 → MiniYuxi 角色 | 🟢 低 | 183 组 | 按 `dataPerms` 位严格校验；未映射的角色沿用粗粒度 `ROLE_PERMS` |

---

## 一、逆向产物清单

| 产物 | 路径 | 说明 |
|---|---|---|
| 应用树 | `C:\tmp\hrm_menu.json` | 49 表单 / 7 仪表盘 / 18 分组 |
| 表单原始 schema | `C:\tmp\hrm_forms\*.json`（49 个） | `POST /_/app/<appId>/form/<id>/info_access` 响应 |
| 结构定义（迁移依据） | `core/hrm_schema.json`（349 KB） | 由 `tools/gen_hrm_schema.py` 生成 |
| 数据驱动引擎 | `core/hrm.py` | 建表 / CRUD / 子表单 / 权限 / 视图 / 审批状态机 |
| 抓取脚本 | `huashu-chrome/tmp_extract_v2.mjs` | 经浏览器扩展批量抓 `info_access` |
| 导入器 | `tools/import_hrm_data.py` | CSV / JSON 灌库 |

抓取关键（踩坑记录）：
1. 真实 schema 接口是 `POST /_/app/<appId>/form/<formId>/info_access`，**不是** `form/<formId>`；
2. 扩展 `fetch` 命令直连该接口一律 403（页面请求带页面自签的鉴权头，钩子抓不到）→ **只能走 `navigate` 触发页面自身请求 + `network` 抓响应缓冲**；
3. `network` 匹配串必须精确用 `info_access`，用 `form/<id>` 会命中流程表单的 `bpa` 小请求，抓到空壳；
4. `views` / `authGroups` 在响应**顶层**，不在 `entry` 下；顶层 `flow` 只是 UI 开关，**不能**当审批标志（审批标志取 `entry.hasFlow` / 菜单 `hasFlow`）。

---

## 二、字段类型映射（简道云 → SQLite）

| 简道云 widget | 数量 | SQLite 类型 | 存储形态 | 还原方式 |
|---|---|---|---|---|
| `text` | 193 | TEXT | 原样 | — |
| `number` | 159 | REAL | 数值 | — |
| `datetime` | 93 | TEXT | ISO 字符串 | — |
| `user` | 75 | TEXT | JSON 数组 `[{id,name}]` | 自动 dumps/loads |
| `combo` | 69 | TEXT | 选项文本 | `options` / `async_source` 已存 |
| `radiogroup` | 51 | TEXT | 选项文本 | 同上 |
| `textarea` | 47 | TEXT | 原样 | — |
| `dept` | 25 | TEXT | JSON 数组 | 自动 |
| `linkquery` | 19 | TEXT | JSON（跨表引用） | 外键语义保留在 `link` |
| `subform` | 19 | — | **独立子表** | `hrm_<key>_<col>`，1:N |
| `signature` | 16 | TEXT | JSON | 自动 |
| `sn` | 7 | TEXT | 流水号 | `rules`(fixedChars+incNumber) 自动生成 |
| `upload` | 13 | TEXT | JSON 数组 | 自动 |
| `address` | 12 | TEXT | JSON | 自动 |
| `linkfield` | 11 | TEXT | 外键值 | — |
| `combocheck` | 2 | TEXT | JSON 数组 | 自动 |
| `location` | 2 | TEXT | JSON | 自动 |
| `image` / `usergroup` | 1 / 1 | TEXT | JSON | 自动 |
| `separator` | 130 | — | **不建列** | 仅布局，保留在 schema |
| 子表单内字段 | 119 | 同上规则 | 同上 | 建在子表 |

通用规则：
- 每张主表固定附加 `id / tenant_id / created_by / created_at / updated_at`；流程表单额外加 `flow_status`；
- 必填（`allowBlank=false`）记录在 `fields[].required`（共 252 个），列级不强制 NOT NULL，交由应用层校验，避免历史脏数据导入失败；
- 列名 = 简道云 `widgetName`（`_widget_xxx` → `w_xxx`），**同时支持中文字段标题作为键**写入。

---

## 三、落地数据结构

```
hrm_<form_key>              主表，49 张（字段名=widgets）
hrm_<form_key>_<subform_col> 子表，19 张（parent_id → 主表 id）
hrm_flow_instances          审批实例（form_key/row_id/status/审批人/意见/时间）
hrm_counters                流水号计数器
```

示例（员工档案）：

| 层级 | 表名 | 说明 |
|---|---|---|
| 主表 | `hrm_emp_archive` | 50 字段，含 `工号(sn)` `姓名` `部门` `员工成员单选(user)` `籍贯(address)` … |
| 子表 | `hrm_emp_archive_w_1686276751989` | 「紧急联系人」3 个子字段，1:N |

---

## 四、业务逻辑保真

| 逻辑 | 简道云侧 | MiniYuxi 侧 | 一致性 |
|---|---|---|---|
| 流水号 | `rules`: fixedChars `FR` + incNumber(5) | `_next_sn()` 自动生成，`FR00001` 递增 | ✅ |
| 子表单 | 内嵌多行 | 独立子表 + `parent_id`，`row_get` 自动装载、`row_update` 整体替换、`row_delete` 级联删除 | ✅ |
| 数据字典 | 静态 options / 异步取自他表字段 | `options` + `async_source{form_id,field}` 存档 | ✅ 结构一致 |
| 跨表关联 | `linkquery` / `linkfield` | 存 `link{link_filter,link_fields,data}`，列存引用值 | ✅ 结构一致 |
| 权限 | `authGroups[].dataPerms`（read/create/update/delete/export/flow_*） | `check_perm()` 按位校验；`perm_matrix()` 导出对照 | ✅ |
| 视图 | `views[]`（filter/sort/kanban），101 个 | `row_list(view=)` 按 `sort` 还原排序；filter/kanban 存档待前端渲染 | 🟡 排序已生效，筛选待接 |
| 审批流 | 21 张 `hasFlow` 表单 | `flow_submit` / `flow_decide` / `flow_list_pending`，状态回写 `flow_status` | 🟡 单级兜底 |

---

## 五、可直接执行的步骤

```bash
cd "E:/HR有关AI/AI应用基座最佳实践/14_自研MiniYuxi"
PY="$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

# 1)（可选，已有产物）重新生成结构定义：需先跑抓取脚本产出 C:\tmp\hrm_forms
"$PY" tools/gen_hrm_schema.py            # → core/hrm_schema.json

# 2) 建表（服务启动时自动执行；也可手工）
"$PY" -c "import core.hrm as h; h.init(); print(len(h.list_forms()), 'tables ready')"

# 3) 冒烟验证
"$PY" tests/_smoke_hrm.py                # 引擎层：27 项
"$PY" tests/_smoke_hrm_http.py           # HTTP 层：29 项

# 4) 导入简道云导出数据（先 dry-run 再实跑）
"$PY" tools/import_hrm_data.py --dir ./jdy_export --tenant default --user admin --dry-run
"$PY" tools/import_hrm_data.py --dir ./jdy_export --tenant default --user admin

# 5) 启动服务
"$PY" -m uvicorn api:app --host 127.0.0.1 --port 8000
```

导出文件命名：`<表单中文名>.csv`（如 `员工档案.csv`）或 `<form_key>.csv`（如 `emp_archive.csv`）；子表单列头写作 `紧急联系人.紧急联系人姓名`；也可直接给 JSON（子表单内嵌数组）。

---

## 六、REST API

| 方法 | 路径 | 说明 | 权限位 |
|---|---|---|---|
| GET | `/api/hrm/forms` | 49 张表单清单 | `hrm.read` |
| GET | `/api/hrm/meta/{form_key}` | 结构（字段/子表单/权限/视图） | `hrm.read` |
| GET | `/api/hrm/perm/{form_key}` | 权限矩阵 | `hrm.read` |
| GET | `/api/hrm/{form_key}` | 列表，支持 `view/page/size` | `hrm.read` + `read` 位 |
| POST | `/api/hrm/{form_key}` | 建单（列名或中文标题均可） | `hrm.write` + `create` 位 |
| GET | `/api/hrm/{form_key}/{rid}` | 单条（含子表单） | `hrm.read` + `read` 位 |
| PUT | `/api/hrm/{form_key}/{rid}` | 更新（子表单整体替换） | `hrm.write` + `update` 位 |
| DELETE | `/api/hrm/{form_key}/{rid}` | 删除（级联子表单） | `hrm.delete` + `delete` 位 |
| POST | `/api/hrm/{form_key}/{rid}/submit` | 提交审批 | `hrm.flow` + `flow_create` 位 |
| GET | `/api/hrm/flows/pending` | 待办 | `hrm.flow` |
| POST | `/api/hrm/flows/{instance_id}/decide` | 通过/驳回 | `hrm.flow` |

> 静态路径（`meta` / `perm` / `flows`）声明在 `{form_key}` 通配路由之前，否则会被截胡——已加回归用例覆盖。

角色权限（`core/config.py` `ROLE_PERMS`）：
- `admin`：`hrm.read/write/delete/flow/admin`，且 `check_perm` 全放行
- `editor`：`hrm.read/write/flow`
- `viewer`：`hrm.read`

---

## 七、验证结果

| 验证项 | 结果 |
|---|---|
| `py_compile`（`core/hrm.py`、`api.py`、`tools/*`） | ✅ |
| `tests/_smoke_hrm.py` | ✅ 27/27（建表/子表单/标签键/sn/权限/审批） |
| `tests/_smoke_hrm_http.py` | ✅ 29/29（含通配路由顺序、400/404 错误码） |
| `tests/_scan_undef.py` | ✅ 无未定义符号 |
| 导入器 CSV 实跑 | ✅ 2 行成功，未知列严格报错 / skip 模式正常 |

---

## 八、已知边界与下一步

1. **审批节点图**：需抓「流程设计」接口（`/flow/...` 设计态），拿到后扩展 `flow_submit` 为多级 `current_node` 流转——状态机与实例表已预留字段。
2. **附件实体**：需批量下载 `upload/image/signature` 指向的文件并落到对象存储，当前只保留引用 JSON。
3. **视图筛选**：`filter` 已存档，待前端按 `filter` 结构渲染（排序已生效）。
4. **仪表盘**：7 个仪表盘（人事工作台/薪酬看板/绩效看板/考勤报表等）为独立组件，未纳入本次 49 表单迁移，可按看板指标在 MiniYuxi 侧另行建模。

---

## 附录：49 张表单清单

| # | key | 表单名 | 字段 | 子表单 | 视图 | 审批流 |
|---|-----|--------|------|--------|------|--------|
| 1 | `app_help` | 应用说明 💡 | 1 | 0 | 1 | — |
| 2 | `attendance_clock` | 考勤打卡 | 17 | 0 | 1 | — |
| 3 | `attendance_confirm` | 考勤确认 | 34 | 0 | 3 | 是 |
| 4 | `attendance_cycle` | 考勤周期 | 8 | 0 | 1 | — |
| 5 | `city_insurance_rate` | 城市五险一金缴纳比例 | 24 | 1 | 2 | — |
| 6 | `comp_leave_apply` | 调休申请 | 16 | 1 | 3 | 是 |
| 7 | `dept_position` | 部门岗位基础表 | 5 | 0 | 1 | — |
| 8 | `dim_year_month` | 辅助表-年月 | 2 | 0 | 1 | — |
| 9 | `emp_archive` | 员工档案 | 50 | 1 | 7 | — |
| 10 | `emp_attachment` | 员工个人附件收集 | 8 | 0 | 1 | 是 |
| 11 | `emp_contract` | 员工合同管理 | 20 | 0 | 1 | — |
| 12 | `emp_count_calc` | 期初期末员工数量计算 | 15 | 0 | 1 | — |
| 13 | `emp_insurance_base` | 员工五险一金缴纳基数 | 7 | 0 | 3 | — |
| 14 | `emp_salary_struct` | 员工薪资结构 | 9 | 0 | 6 | — |
| 15 | `emp_special_deduction` | 员工专项附加扣除 | 13 | 0 | 1 | — |
| 16 | `employer_eval` | 用人单位评估 | 40 | 0 | 3 | 是 |
| 17 | `field_clock` | 外勤打卡 | 17 | 0 | 1 | — |
| 18 | `hr_cert_apply` | 人事证明开具 | 11 | 0 | 1 | 是 |
| 19 | `interview_apply` | 发起面试 | 30 | 0 | 1 | 是 |
| 20 | `jd_base` | JD 基础表 | 6 | 0 | 1 | — |
| 21 | `kpi_library` | 指标库 | 8 | 0 | 1 | — |
| 22 | `leave_apply` | 请假申请 | 23 | 1 | 3 | 是 |
| 23 | `leave_type` | 假别基础表 | 5 | 0 | 1 | — |
| 24 | `offboard_apply` | 离职申请与交接 | 49 | 4 | 3 | 是 |
| 25 | `offboard_interview` | 离职面谈 | 21 | 0 | 1 | 是 |
| 26 | `offer_follow` | offer跟进 | 18 | 0 | 1 | — |
| 27 | `offer_send` | offer发放 | 22 | 0 | 1 | — |
| 28 | `onboard_apply` | 入职审批 | 58 | 1 | 3 | 是 |
| 29 | `overtime_apply` | 加班申请 | 14 | 1 | 3 | 是 |
| 30 | `payroll_calc` | 导入发起工资计算 | 12 | 0 | 1 | — |
| 31 | `payroll_detail` | 员工工资明细 | 49 | 0 | 1 | 是 |
| 32 | `payslip` | 工资条 | 32 | 0 | 3 | 是 |
| 33 | `recruit_demand` | 招聘需求 | 26 | 0 | 1 | — |
| 34 | `regularization_apply` | 转正审批 | 29 | 2 | 3 | 是 |
| 35 | `repair_clock_apply` | 补卡申请 | 19 | 0 | 3 | 是 |
| 36 | `resume_recommend` | 简历推荐 | 3 | 1 | 1 | — |
| 37 | `resume_screen` | 简历收集及初筛 | 41 | 1 | 5 | 是 |
| 38 | `review_cycle` | 考核周期 | 6 | 0 | 1 | — |
| 39 | `review_interview` | 绩效面谈 | 12 | 0 | 3 | 是 |
| 40 | `review_plan` | 绩效考核计划制定 | 28 | 1 | 3 | 是 |
| 41 | `review_result` | 绩效结果考核 | 29 | 2 | 3 | 是 |
| 42 | `review_template` | 考核模板 | 6 | 1 | 1 | — |
| 43 | `salary_item` | 薪资项 | 5 | 0 | 2 | — |
| 44 | `talent_pool` | 人才库 | 39 | 1 | 3 | — |
| 45 | `tax_rate` | 个人所得税税率表 | 6 | 0 | 2 | — |
| 46 | `transfer_apply` | 岗位调动审批 | 28 | 0 | 3 | 是 |
| 47 | `travel_apply` | 出差申请 | 15 | 0 | 3 | 是 |
| 48 | `work_calendar` | 工作日历 | 7 | 0 | 1 | — |
| 49 | `work_location` | 工作地点基础表 | 2 | 0 | 1 | — |
