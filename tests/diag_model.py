import requests

BASE = "http://127.0.0.1:8801"
tok = requests.post(BASE + "/api/auth/login",
                    json={"tenant": "default", "username": "admin", "password": "admin123"}, timeout=15).json()["token"]
h = {"Authorization": "Bearer " + tok}
for m in ["siliconflow:THUDM/glm-4-9b-chat", "siliconflow:Qwen/Qwen2.5-72B-Instruct",
         "siliconflow:deepseek-ai/DeepSeek-V3", "siliconflow:Qwen/Qwen2.5-7B-Instruct"]:
    r = requests.post(BASE + "/api/models/test", headers=h, json={"model_id": m}, timeout=60).json()
    print(m, "| ok=", r.get("ok"), "| err=", r.get("err"), "| text=", repr((r.get("text") or "")[:30]))
