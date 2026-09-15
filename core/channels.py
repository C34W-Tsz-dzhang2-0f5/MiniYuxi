"""渠道接入（T4）：抽象渠道基类 + 企业微信最小 webhook 接收。

抄 nanobot 渠道抽象：不同入口统一收敛到 rag.answer。本批只做企微"接收文本 → 回答"最小端点，
完整客服后台（多级缓存 / FAQ / 管理端）留待下批。
"""
from . import rag


class Channel:
    name = "base"

    def receive(self, payload: dict) -> dict:
        raise NotImplementedError


class WeComChannel(Channel):
    name = "wecom"

    def receive(self, payload: dict) -> dict:
        # 兼容两种形态：直接 {"content": "..."} 或企微回调 {"text": {"content": "..."}}
        content = ""
        if isinstance(payload, dict):
            content = payload.get("content") or (payload.get("text") or {}).get("content") or ""
        if not content:
            return {"ok": False, "answer": "未识别到文本内容", "mode": "empty"}
        res = rag.answer("default", content, top_k=5, history=None)
        return {
            "ok": True,
            "answer": res.get("answer", ""),
            "citations": res.get("citations", []),
            "mode": res.get("mode", ""),
        }


def handle_wecom(payload: dict) -> dict:
    return WeComChannel().receive(payload)
