# -*- coding: utf-8 -*-
"""把 jd_run.json（真实 DeepSeek 闭环结果）渲染成 MiniYuxi『岗位工作台』结果页并截图。"""
import json, html, subprocess, os, sqlite3, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data = json.load(open(os.path.join(ROOT, "jd_run.json"), encoding="utf-8"))
exec_node = data.get("trace", {}).get("exec", {})
mat = data.get("materials_check", {})

# ---------- 轻量 markdown -> html（标题/粗体/列表/引用/表格/分割线） ----------
def esc(s): return html.escape(s)

def md_to_html(md):
    lines = md.split("\n")
    out, i, n = [], 0, len(lines)
    def inline(t):
        t = esc(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
        t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        return t
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if s == "" or s == "---" or s == "***":
            out.append('<hr/>'); i += 1; continue
        if s.startswith("# "):
            out.append(f"<h2>{inline(s[2:])}</h2>"); i += 1; continue
        if s.startswith("## "):
            out.append(f"<h3>{inline(s[3:])}</h3>"); i += 1; continue
        if s.startswith("### "):
            out.append(f"<h4>{inline(s[4:])}</h4>"); i += 1; continue
        if s.startswith(">"):
            out.append(f"<blockquote>{inline(s.lstrip('> '))}</blockquote>"); i += 1; continue
        # 表格：连续 | 行 + 分隔行
        if "|" in s and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i+1]):
            tbl = [s]
            j = i
            while j < n and "|" in lines[j]:
                tbl.append(lines[j]); j += 1
            # 去掉分隔行
            rows = [r for r in tbl if not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", r)]
            cells = [[c.strip().strip("|") for c in r.split("|")] for r in rows]
            # 去掉首尾可能的空列
            cells = [c[1:] if c and c[0] == "" else c for c in cells]
            cells = [c[:-1] if c and c[-1] == "" else c for c in cells]
            html_rows = []
            for ri, row in enumerate(cells):
                tds = "".join(f"<td>{inline(c)}</td>" for c in row)
                html_rows.append(f"<tr>{tds}</tr>")
            out.append(f"<table>{''.join(html_rows)}</table>")
            i = j; continue
        # 列表
        if re.match(r"^[-*]\s+", s):
            buf = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                buf.append(f"<li>{inline(lines[i].strip()[2:].strip())}</li>"); i += 1
            out.append(f"<ul>{''.join(buf)}</ul>"); continue
        if re.match(r"^\d+\.\s+", s):
            buf = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                buf.append(f"<li>{inline(re.sub(r'^\d+\.\s+','',lines[i].strip()))}</li>"); i += 1
            out.append(f"<ol>{''.join(buf)}</ol>"); continue
        out.append(f"<p>{inline(s)}</p>"); i += 1
    return "\n".join(out)

answer_html = md_to_html(data.get("answer", ""))

# ---------- 最近一条审计事件 ----------
audit_line = ""
try:
    c = sqlite3.connect(os.path.join(ROOT, "data", "miniyuxi.db"))
    row = c.execute("SELECT action,target,result,actor,created_at FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        audit_line = f"{row[4]} · action={row[0]} · target={row[1]} · result={row[2]} · actor={row[3]}"
except Exception as e:
    audit_line = f"(审计查询失败: {e})"

provided = mat.get("provided", []) or []
missing = mat.get("missing", []) or []

css = """
*{box-sizing:border-box} body{margin:0;font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0}
.topbar{background:linear-gradient(90deg,#1e3a8a,#0ea5e9);padding:14px 22px;color:#fff;font-size:18px;font-weight:700;display:flex;justify-content:space-between;align-items:center}
.topbar .tag{font-size:12px;background:rgba(255,255,255,.18);padding:3px 10px;border-radius:20px;font-weight:500}
.wrap{display:flex;gap:18px;padding:18px;align-items:flex-start}
.left{width:340px;flex:0 0 340px}
.right{flex:1;min-width:0}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:14px 16px;margin-bottom:14px}
.card h3{margin:0 0 10px;font-size:14px;color:#7dd3fc;letter-spacing:.5px}
.step{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;margin-bottom:6px;background:#0f172a;border:1px solid #334155;font-size:13px}
.step .dot{width:22px;height:22px;border-radius:50%;background:#475569;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;flex:0 0 22px}
.step.active{background:#0c4a6e;border-color:#0ea5e9}
.step.active .dot{background:#0ea5e9}
.badge{display:inline-block;background:#065f46;color:#a7f3d0;font-size:11px;padding:2px 8px;border-radius:6px;margin-left:6px}
.kv{display:flex;justify-content:space-between;font-size:13px;padding:4px 0;border-bottom:1px dashed #334155}
.kv:last-child{border-bottom:none}
.kv b{color:#fbbf24}
.chip{display:inline-block;background:#334155;color:#e2e8f0;font-size:12px;padding:3px 9px;border-radius:6px;margin:3px 4px 3px 0}
.miss{background:#7f1d1d;color:#fecaca}
.ok{color:#86efac}.warn{color:#fbbf24}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}
th,td{border:1px solid #334155;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#0f172a;color:#7dd3fc}
blockquote{border-left:3px solid #0ea5e9;margin:6px 0;padding:4px 12px;color:#94a3b8;background:#0f172a;border-radius:0 6px 6px 0}
h2{font-size:18px;color:#f1f5f9;border-bottom:2px solid #0ea5e9;padding-bottom:6px;margin-top:18px}
h3{font-size:15px;color:#7dd3fc;margin:14px 0 6px}
h4{font-size:14px;color:#cbd5e1;margin:10px 0 4px}
p{line-height:1.7;margin:6px 0}
ul,ol{margin:6px 0;padding-left:22px;line-height:1.7}
code{background:#0f172a;padding:1px 5px;border-radius:4px;color:#fbbf24;font-size:12px}
.foot{margin:8px 18px 26px;font-size:12px;color:#94a3b8;border-top:1px solid #334155;padding-top:10px}
"""

steps = [
    ("1", "开始 / start", False),
    ("2", "材料核验 / knowledge", False),
    ("3", f"执行主提示词 / LLM（{exec_node.get('model_name','DeepSeek')}）", True),
    ("4", "套用输出格式 / format", False),
    ("5", "人工闸门 / approval（auto）", False),
    ("6", "结束 / end", False),
]

html_steps = "".join(
    f'<div class="step {"active" if a else ""}"><div class="dot">{n}</div><div>{t}</div></div>'
    for n, t, a in steps
)

missing_html = "".join(f'<span class="chip miss">{html.escape(m)}</span>' for m in missing) or '<span class="chip ok">无</span>'
provided_html = "".join(f'<span class="chip">{html.escape(p)}</span>' for p in provided) or '<span class="chip">（未提供）</span>'
follow_html = "".join(f"<li>{html.escape(f)}</li>" for f in data.get("followups", []))

page = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="topbar"><div>🤖 MiniYuxi · 岗位工作台 <span style="font-weight:400;opacity:.8">（真实闭环 · 模型路由：DeepSeek）</span></div>
<div class="tag">tenant: default</div></div>
<div class="wrap">
  <div class="left">
    <div class="card"><h3>任务</h3>
      <div class="kv"><span>task_id</span><b>{data.get('task_id')}</b></div>
      <div class="kv"><span>标题</span><b>{html.escape(str(data.get('title')))}</b></div>
      <div class="kv"><span>模块</span><span>{html.escape(str(data.get('module')))}</span></div>
      <div class="kv"><span>角色</span><span>{data.get('role')}</span></div>
    </div>
    <div class="card"><h3>端到端 DAG（6 节点闭环）</h3>{html_steps}</div>
    <div class="card"><h3>材料完整性核验</h3>
      <div style="font-size:12px;color:#94a3b8">已提供</div>{provided_html}
      <div style="font-size:12px;color:#94a3b8;margin-top:8px">缺失项（不自行编造）</div>{missing_html}
      <div class="kv" style="margin-top:8px"><span>缺失计数</span><b class="warn">{mat.get('missing_count')}</b></div>
    </div>
    <div class="card"><h3>LLM 执行节点（DeepSeek）</h3>
      <div class="kv"><span>模型</span><b>{exec_node.get('model_name')}</b></div>
      <div class="kv"><span>model_id</span><span>{exec_node.get('model')}</span></div>
      <div class="kv"><span>provider</span><span>{exec_node.get('provider')}</span></div>
      <div class="kv"><span>耗时</span><span>{exec_node.get('latency_ms')} ms</span></div>
      <div class="kv"><span>tokens</span><span>{exec_node.get('tokens')}</span></div>
      <div class="kv"><span>成本</span><b>¥{exec_node.get('cost')}</b></div>
      <div class="kv"><span>调用结果</span><b class="ok">ok={exec_node.get('ok')}</b></div>
    </div>
  </div>
  <div class="right">
    <div class="card"><h3>交付结果 · 撰写岗位 JD（结构化稿件）</h3>{answer_html}</div>
    <div class="card"><h3>建议追问（可一键继续）</h3><ul>{follow_html}</ul></div>
  </div>
</div>
<div class="foot">SOC 审计：{html.escape(data.get('audit',''))} ｜ 最近审计事件：{html.escape(audit_line)}</div>
</body></html>"""

report_path = os.path.join(ROOT, "jd_report.html")
open(report_path, "w", encoding="utf-8").write(page)
print("report written:", report_path, "bytes=", len(page))

# ---------- chrome 无头截图 ----------
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
png = os.path.join(ROOT, "jd_run.png")
cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
       "--force-device-scale-factor=1", "--window-size=1440,9000",
       f"--screenshot={png}", f"file:///{report_path.replace(os.sep,'/')}"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
print("chrome rc=", r.returncode, "stderr=", r.stderr[-300:])
print("png exists=", os.path.exists(png), "size=", os.path.getsize(png) if os.path.exists(png) else 0)
