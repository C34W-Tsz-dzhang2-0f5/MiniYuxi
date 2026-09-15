"""RAG 外部平台适配层（A 方案）：把 MiniYuxi 的 HR 知识库问答接入 RAGFlow / FastGPT。

设计原则：
  - 本文件为「可选后端」，不修改任何指纹文件（selftest.py / db.py / agent.py）。
  - 默认走 MiniYuxi 原生 RAG（rag.answer）；仅当配置了对应环境变量时才转发到外部平台。
  - 零额外依赖：仅用标准库 urllib，避免污染本机环境。
  - 任何外部调用失败都降级回原生 RAG，保证 HR 问答始终可用。

环境变量（任选其一配置即可启用对应平台）：
  RAGFLOW_API_KEY / RAGFLOW_BASE_URL / RAGFLOW_DATASET_ID
  FASTGPT_API_KEY  / FASTGPT_BASE_URL / FASTGPT_APP_ID
"""
import json
import os
import urllib.error
import urllib.request

import core.rag as rag  # 原生 RAG，作为降级兜底


def _http_post(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_ragflow(question: str, top_k: int = 5) -> dict:
    """调用 RAGFlow 的 /api/v1/retrieval 或对话接口，返回 {answer, citations}。"""
    base = os.environ.get("RAGFLOW_BASE_URL", "http://localhost:8000").rstrip("/")
    key = os.environ.get("RAGFLOW_API_KEY", "")
    ds = os.environ.get("RAGFLOW_DATASET_ID", "")
    if not key or not ds:
        raise RuntimeError("RAGFLOW_API_KEY / RAGFLOW_DATASET_ID 未配置")
    url = f"{base}/api/v1/chats/{{chat_id}}/completions"
    # RAGFlow 以 dataset 检索为主，这里用 retrieval 接口拿片段再本地合成答案
    retrieve_url = f"{base}/api/v1/datasets/{ds}/documents"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # 退化处理：外部不可用直接抛错，由 ask() 统一降级
    _http_post(retrieve_url, {"question": question, "page_size": top_k}, headers)
    # 真正问答走对话接口（chat_id 可经环境变量 RAGFLOW_CHAT_ID 覆盖）
    chat_id = os.environ.get("RAGFLOW_CHAT_ID", "")
    ans = _http_post(
        url.format(chat_id=chat_id),
        {"question": question, "stream": False},
        headers,
    )
    data = ans.get("data", {})
    return {
        "answer": data.get("answer", "") or json.dumps(ans, ensure_ascii=False),
        "citations": data.get("reference", {}).get("chunks", []) or [],
        "mode": "external:ragflow",
    }


def query_fastgpt(question: str, top_k: int = 5) -> dict:
    """调用 FastGPT 的 /api/v1/chat/completions（OpenAI 兼容）。"""
    base = os.environ.get("FASTGPT_BASE_URL", "http://localhost:3000").rstrip("/")
    key = os.environ.get("FASTGPT_API_KEY", "")
    app_id = os.environ.get("FASTGPT_APP_ID", "")
    if not key or not app_id:
        raise RuntimeError("FASTGPT_API_KEY / FASTGPT_APP_ID 未配置")
    url = f"{base}/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    ans = _http_post(
        url,
        {
            "chatId": app_id,
            "stream": False,
            "detail": False,
            "messages": [{"role": "user", "content": question}],
        },
        headers,
    )
    choices = ans.get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content", "")
    return {"answer": content, "citations": [], "mode": "external:fastgpt"}


def ask(question: str, tenant_id: str = "default", top_k: int = 5,
        prefer: str = "auto") -> dict:
    """统一的 HR 知识库问答入口。

    prefer:
      'auto'      —— 优先外部平台（按配置），失败降级原生 RAG
      'ragflow'   —— 强制 RAGFlow
      'fastgpt'   —— 强制 FastGPT
      'native'    —— 强制原生 RAG
    """
    if prefer == "native":
        return _native(tenant_id, question, top_k)

    if prefer in ("auto", "ragflow") and os.environ.get("RAGFLOW_API_KEY"):
        try:
            return query_ragflow(question, top_k)
        except Exception:
            if prefer == "ragflow":
                raise
    if prefer in ("auto", "fastgpt") and os.environ.get("FASTGPT_API_KEY"):
        try:
            return query_fastgpt(question, top_k)
        except Exception:
            if prefer == "fastgpt":
                raise
    return _native(tenant_id, question, top_k)


def _native(tenant_id: str, question: str, top_k: int) -> dict:
    d = rag.answer(tenant_id, question, top_k, None)
    d["mode"] = "native:" + str(d.get("mode", "rag"))
    return d
