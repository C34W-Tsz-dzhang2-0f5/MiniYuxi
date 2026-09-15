"""统一大模型网关（T1）：多供应商注册表 + 路由 + 超时 fallback。

抄 OpenClaw 的 /v1/models 思路（暴露模型列表）+ nanobot 的模型自由（运行时可切供应商）。
不新增外部依赖：SiliconFlow 走 OpenAI 兼容接口；离线兜底始终可用。
所有 LLM 调用经此网关，便于统一埋点（usage）与故障转移。rag.llm_chat / rag.llm_chat_stream 委托本模块。
"""
import json
import re
import time
import requests
from . import config, usage

OFFLINE_ID = "offline"
MAX_HISTORY = 10
MAX_HISTORY_CHARS = 800
MAX_RETRIES = 3  # 瞬断重试（429/5xx/timeout），避免一次 API 抖动就让整轮 agent 退化


def _post_with_retry(payload: dict):
    """POST 到 /chat/completions，瞬断自动重试；返回 (resp, None) 或 (None, err_str)。"""
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                json=payload,
                timeout=config.LLM_TIMEOUT,
            )
            resp.raise_for_status()
            return resp, None
        except requests.exceptions.Timeout:
            last_err = "timeout"
            time.sleep(1.5 * (attempt + 1))
        except requests.exceptions.HTTPError as he:
            status = he.response.status_code if he.response is not None else 0
            last_err = f"HTTP {status}"
            if status in (429, 500, 502, 503, 504):  # 瞬断 → 重试
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, last_err  # 鉴权/参数等硬错 → 直接放弃
        except requests.exceptions.RequestException as re:
            last_err = str(re)[:200]
            time.sleep(1.5 * (attempt + 1))
    return None, last_err


def list_models() -> list[dict]:
    """返回可用模型/网关列表，供 /api/gateway/models 使用。"""
    out = []
    if config.llm_enabled():
        out.append({
            "id": "siliconflow",
            "name": "SiliconFlow · " + config.LLM_MODEL,
            "model": config.LLM_MODEL,
            "base_url": config.LLM_BASE_URL,
            "status": "online",
        })
    out.append({
        "id": OFFLINE_ID,
        "name": "离线兜底（抽取式·无需 Key）",
        "model": "offline",
        "base_url": "",
        "status": "always",
    })
    return out


def _messages(system, prompt, history):
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-MAX_HISTORY:]:
        role = h.get("role") if isinstance(h, dict) else None
        content = (h.get("content") if isinstance(h, dict) else "") or ""
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    messages.append({"role": "user", "content": prompt})
    return messages


def chat(system, prompt, history=None, provider=None, model=None, tenant_id=None) -> dict:
    """返回 {ok, text, err, model, provider, usage}。失败自动转离线兜底标记。

    provider/model 可选：model 优先覆盖 config.LLM_MODEL；model="offline" 等价于 offline 供应商。
    """
    effective_model = (model or config.LLM_MODEL) if model != "offline" else "offline"
    if provider == OFFLINE_ID or effective_model == "offline" or not config.llm_enabled():
        usage.record(tenant_id, "llm", "offline", prompt_text=prompt, completion_text="")
        return {"ok": False, "text": "", "err": "offline", "model": "offline", "provider": OFFLINE_ID, "usage": None}

    resp, err = _post_with_retry({
        "model": effective_model,
        "messages": _messages(system, prompt, history),
        "temperature": config.LLM_TEMPERATURE,
    })
    if resp is None:
        usage.record(tenant_id, "llm", "offline", prompt_text=prompt, completion_text="")
        return {"ok": False, "text": "", "err": err, "model": effective_model, "provider": "siliconflow", "usage": None}
    js = resp.json()
    text = js["choices"][0]["message"]["content"]
    u = js.get("usage")
    pt = u.get("prompt_tokens") if u else None
    ct = u.get("completion_tokens") if u else None
    cost = None
    if u and u.get("total_tokens"):
        try:
            pin, pout = usage.price(effective_model)
        except Exception:
            pin = pout = 0.0
        cost = (pt or 0) / 1000.0 * pin + (ct or 0) / 1000.0 * pout
    usage.record(tenant_id, "llm", effective_model, prompt_text=prompt, completion_text=text,
                 prompt_tokens=pt, completion_tokens=ct, cost=cost)
    return {"ok": True, "text": text, "err": "", "model": effective_model, "provider": "siliconflow", "usage": u}


def chat_with_tools(system, messages, tools, history=None, provider=None, tenant_id=None) -> dict:
    """支持 OpenAI function calling 的对话。messages 为不含 system 的完整消息列表
    （history + 用户提问 + 工具结果）。返回 {ok, text, tool_calls, err, usage}。
    - 若模型返回 tool_calls：tool_calls=[{name, arguments(dict), id}]
    - 否则 text 为最终回答。
    """
    if provider == OFFLINE_ID or not config.llm_enabled():
        usage.record(tenant_id, "llm", "offline", prompt_text=str(messages), completion_text="")
        return {"ok": False, "text": "", "err": "offline", "tool_calls": [], "usage": None}

    full_msgs = [{"role": "system", "content": system}] + list(messages)
    payload = {
        "model": config.LLM_MODEL,
        "messages": full_msgs,
        "temperature": config.LLM_TEMPERATURE,
        "tools": tools,
        "tool_choice": "auto",
    }
    resp, err = _post_with_retry(payload)
    if resp is None:
        usage.record(tenant_id, "llm", "offline", prompt_text=str(messages), completion_text="")
        return {"ok": False, "text": "", "err": err, "tool_calls": [], "usage": None}
    js = resp.json()
    msg = js["choices"][0]["message"]
    u = js.get("usage")
    pt = u.get("prompt_tokens") if u else None
    ct = u.get("completion_tokens") if u else None
    cost = None
    if u and u.get("total_tokens"):
        pin, pout = usage.price(config.LLM_MODEL)
        cost = (pt or 0) / 1000.0 * pin + (ct or 0) / 1000.0 * pout
    usage.record(tenant_id, "llm", config.LLM_MODEL, prompt_text=str(messages),
                 completion_text=msg.get("content") or "", prompt_tokens=pt, completion_tokens=ct, cost=cost)
    raw_calls = msg.get("tool_calls") or []
    tool_calls = []
    for tc in raw_calls:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        tool_calls.append({"name": fn.get("name", ""), "arguments": args, "id": tc.get("id", "")})
    return {"ok": True, "text": msg.get("content") or "", "tool_calls": tool_calls,
            "model": config.LLM_MODEL, "provider": "siliconflow", "usage": u}


def chat_stream(system, prompt, history=None, provider=None, tenant_id=None):
    """生成器：逐 token 产出字符串（SSE 用）。无 Key / 异常时不产出（上层走离线兜底）。"""
    if provider == OFFLINE_ID or not config.llm_enabled():
        return
    try:
        resp = requests.post(
            f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            json={"model": config.LLM_MODEL, "messages": _messages(system, prompt, history),
                  "temperature": config.LLM_TEMPERATURE, "stream": True},
            stream=True, timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        full = []
        for line in resp.iter_lines():
            if not line:
                continue
            s = line.decode("utf-8") if isinstance(line, bytes) else line
            if not s.startswith("data:"):
                continue
            data = s[5:].strip()
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
                delta = j["choices"][0]["delta"].get("content", "")
                if delta:
                    full.append(delta)
                    yield delta
            except Exception:
                continue
        usage.record(tenant_id, "llm", config.LLM_MODEL, prompt_text=prompt, completion_text="".join(full))
    except Exception:
        return
