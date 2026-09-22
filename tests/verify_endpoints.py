import sys, json
import requests

BASE = "http://127.0.0.1:8801"
TOOL = "e2e_demo_tool"

r = requests.post(f"{BASE}/api/auth/login", json={"tenant": "default", "username": "admin", "password": "admin123"}, timeout=10)
tok = r.json()["token"]
H = {"Authorization": f"Bearer {tok}"}
print("1) 登录:", r.status_code, r.json().get("role"))

bp = requests.get(f"{BASE}/api/coding/blueprint", headers=H, timeout=10).json()
print("2) 蓝图示例可用:", "code" in bp, "| 示例工具名:", bp.get("name"))

gen = requests.post(f"{BASE}/api/coding/generate", headers=H, timeout=20,
                    json={"description": "端到端验证工具", "name": TOOL,
                          "code": "def run(tenant_id=None, **kwargs):\n    return {'result': 'gen-ok ' + str(kwargs.get('x', ''))}"}).json()
print("3) 生成并注册工具:", gen.get("ok"), "| name:", gen.get("name"))

lst = requests.get(f"{BASE}/api/coding/list", headers=H, timeout=10).json()
names = [t["name"] for t in lst["tools"]]
print("4) 自生成工具列表含该工具:", TOOL in names, "| 当前列表:", names)

tools = requests.get(f"{BASE}/api/tools/list", headers=H, timeout=10).json()
allnames = [t["name"] for t in tools["tools"]]
print("5) 出现在 /api/tools/list（自主 Agent 自动可发现）:", TOOL in allnames)

call = requests.post(f"{BASE}/api/tools/call", headers=H, timeout=10,
                    json={"name": TOOL, "args": {"x": "42"}}).json()
print("6) 调用自生成工具:", call.get("result"))

off = requests.post(f"{BASE}/api/coding/generate", headers=H, timeout=20,
                   json={"description": "无代码无LLM", "code": ""}).json()
print("7) 无代码无LLM时优雅降级（返回蓝图而非报错）:", off.get("mode") == "offline-no-code",
      "| 含blueprint:", "blueprint" in off)

chat = requests.post(f"{BASE}/api/chat", headers=H, timeout=20,
                    json={"question": "Agent 等于 LLM 加上下文加工具 这一公式出自哪里"}).json()
print("8) KB 知识增强问答 mode:", chat.get("mode"), "| 引用数:", len(chat.get("citations", [])),
      "| 首条引用来源:", (chat.get("citations")[0].get("title") if chat.get("citations") else None))

d = requests.delete(f"{BASE}/api/coding/{TOOL}", headers=H, timeout=10).json()
print("9) 删除自生成工具:", d.get("ok"))

after = requests.get(f"{BASE}/api/coding/list", headers=H, timeout=10).json()
print("10) 删除后列表不含该工具:", TOOL not in [t["name"] for t in after["tools"]])
