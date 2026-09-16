# -*- coding: utf-8 -*-
"""生成《MiniYuxi 定位与开源平台分工白皮书》docx（C 方案交付物）。
依赖：python-docx（已位于隔离 venv）。纯结构化文档，公文风格。
"""
import os
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

OUT = os.path.join(os.path.dirname(__file__), "MiniYuxi定位与开源平台分工白皮书.docx")

doc = Document()

# 默认字体（中文）
style = doc.styles["Normal"]
style.font.name = "宋体"
style.font.size = Pt(11)
style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

def h1(t):
    p = doc.add_heading(level=1)
    r = p.add_run(t); r.font.name = "黑体"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体"); r.font.size = Pt(15)
    return p

def h2(t):
    p = doc.add_heading(level=2)
    r = p.add_run(t); r.font.name = "楷体"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "楷体"); r.font.size = Pt(13)
    return p

def para(t, bold=False):
    p = doc.add_paragraph()
    r = p.add_run(t); r.bold = bold
    return p

def bullet(t):
    p = doc.add_paragraph(style="List Bullet")
    p.add_run(t)
    return p

def table(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hc = t.rows[0].cells
    for i, htext in enumerate(headers):
        hc[i].text = ""
        rr = hc[i].paragraphs[0].add_run(htext)
        rr.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(val))
    if widths:
        for r_ in t.rows:
            for i, w in enumerate(widths):
                r_.cells[i].width = Cm(w)
    return t

# ---------------- 封面 ----------------
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
tr = title.add_run("MiniYuxi 定位与开源平台分工白皮书")
tr.bold = True; tr.font.size = Pt(22); tr.font.name = "方正小标宋简体"
tr._element.rPr.rFonts.set(qn("w:eastAsia"), "方正小标宋简体")

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
sr = sub.add_run("——自研轻量 HR 智能体平台 vs 主流开源企业级 Agent 平台的边界与协作")
sr.font.size = Pt(12); sr.font.name = "楷体"; sr._element.rPr.rFonts.set(qn("w:eastAsia"), "楷体")

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
meta.add_run("编制：车务通 HR · AI 助理项目组　|　版本 v1.0　|　2026-09-15").font.size = Pt(10)
doc.add_paragraph()

# ---------------- 一、定位 ----------------
h1("一、产品定位与适用边界")
para("MiniYuxi 是深圳车务通科技（隶属陕西导航）自研的轻量 HR 智能体平台，定位为「原生进程、零外部服务、可单机离线运行」的本地化 AI 助手基座。它不追求成为通用大模型编排巨头，而是聚焦 HR 五大模块（招聘 / 绩效 / 薪酬 / 培训 / 劳动关系）的落地可用性、数据主权与合规可审计。")
bullet("适用：本机/内网单机部署、HR 制度问答、招聘智能化、劳动争议案件辅助、员工自助服务。")
bullet("不适用：需要 Kubernetes 多集群弹性扩缩、跨组织联邦、超大规模多租户 SaaS 的通用 Agent 中台场景。")
bullet("核心约束：服务启动必须携带 LLM / EMB / DOUBAO 环境变量；数据层为 SQLite 单文件（sqlite-vec + FTS5），无 Docker、无 VT-x 依赖。")

# ---------------- 二、对比 ----------------
h1("二、MiniYuxi 与主流开源企业级 Agent 平台对比")
para("下表从自研可控性、部署门槛、知识库、审计合规、多模型、生态五大维度横向比较。", bold=True)
table(
    ["维度", "MiniYuxi（自研）", "Dify / FastGPT", "RAGFlow", "LangChain/AutoGen 类"],
    [
        ["部署门槛", "极低：uvicorn 单进程，零外部服务", "中：需容器编排+向量库+Redis", "中：依赖 ES/向量库", "高：需自行组装工程化"],
        ["数据主权", "完全本地，SQLite 单文件", "自托管可本地", "自托管可本地", "取决于集成组件"],
        ["原生 RAG", "内置（FTS5+向量 RRF 融合）", "需接外部向量库", "强项（深度文档解析）", "需自行实现"],
        ["审计合规", "内置 SOC 级哈希防篡改审计链", "企业版/插件", "弱", "需自行实现"],
        ["多模型路由", "内置 model_hub 策略路由", "支持", "支持", "需编码"],
        ["HR 业务深度", "招聘5模块+劳动关系已落地", "通用", "通用", "通用"],
        ["本地离线兜底", "支持（离线回答+数字护栏）", "弱", "弱", "无"],
        ["适合车务通", "✅ 直接契合", "⚠️ 需改造", "⚠️ 需改造", "❌ 工程量大"],
    ],
    widths=[3.0, 4.6, 4.2, 3.2, 3.8],
)

# ---------------- 三、分工 ----------------
h1("三、自研与开源平台的分工原则")
para("结论先行：以 MiniYuxi 为 HR 业务主入口与合规底座，把通用能力「借力」开源平台，避免重复造轮子。", bold=True)
bullet("MiniYuxi 主责：HR 业务闭环、员工自助、制度知识库问答、审计留痕、劳动争议辅助、本地离线可用。")
bullet("开源平台借力（可选外部接入）：当 MiniYuxi 配置了 RAGFlow / FastGPT 环境变量后，知识库问答自动优先走外部平台，失败降级原生 RAG——详见第四章 A 方案。")
bullet("不重复建设：大模型训练、通用向量库集群、跨域联邦等重资产能力，直接对接成熟开源方案，不自研。")

# ---------------- 四、本轮增强 ----------------
h1("四、本轮能力增强（A / B / C 落地说明）")
h2("A · 外部 RAG 适配层 + HR 知识库问答入口")
bullet("新增 core/rag_adapter.py：零依赖封装 RAGFlow / FastGPT 客户端，统一 ask() 接口。")
bullet("新增后端端点 POST /api/rag/ask：默认走原生 RAG，配置外部平台后优先转发、失败自动降级。")
bullet("前端「HR 知识库」弹窗内置问答框，员工可直接向制度库提问并查看引用来源。")
h2("B · 审计补全 + 自助改密 + 用户管理面板")
bullet("登录失败审计：原仅记录成功，现已补登录失败留痕（异常登录可监测）。")
bullet("新增 POST /api/me/password：登录用户自助改密，强制校验旧口令。")
bullet("新增 GET /api/users + POST /api/users/reset：管理员列出本租户账号、重置他人口令。")
bullet("前端「管理」导航：含修改密码与用户管理（重置口令）面板，遵循 RBAC（仅 user.manage 可见用户列表）。")
h2("C · 本白皮书")
bullet("可贴 OA 的 docx 交付物，统一对外说明定位、对比、分工与能力边界。")

# ---------------- 五、部署与使用 ----------------
h1("五、部署与使用指引")
table(
    ["事项", "说明"],
    [
        ["访问地址", "http://127.0.0.1:8801（仅本机）；双击 start_miniyuxi.bat 启动"],
        ["默认账号", "default / admin / admin123（上线前务必改密）"],
        ["知识库", "顶部「知识库」→ 导入制度文件(.docx/.pdf/.txt/.md) → 直接提问"],
        ["系统管理", "顶部「管理」→ 修改我的密码 / 管理员重置用户口令"],
        ["审计查看", "管理员访问 /api/audit（events/verify/report/stats）"],
    ],
    widths=[3.5, 12.5],
)

# ---------------- 六、风险与下一步 ----------------
h1("六、风险分级与下一步")
table(
    ["风险", "等级", "敞口/影响", "应对"],
    [
        ["默认口令未改", "🔴 高", "admin123 明文于启动脚本", "上线前强制改密 + 纳入审计"],
        ["单点 SQLite", "🟡 中", "单机故障即不可用", "定期备份 data/miniyuxi.db"],
        ["外部平台密钥", "🟡 中", "RAGFlow/FastGPT Key 泄露", "环境变量隔离，不入库"],
        ["多租户隔离", "🟢 低", "租户间数据隔离已实现", "保持 tenant_id 强制校验"],
    ],
    widths=[3.5, 2.0, 4.5, 5.5],
)
para("下一步：1）将 A 方案外部适配层接入真实 RAGFlow/FastGPT 实例并回归测试；2）推动默认口令强改策略；3）补充自动化 selftest 覆盖新增端点。", bold=True)

doc.save(OUT)
print("SAVED:", OUT)
