# -*- coding: utf-8 -*-
"""进程级 Agent 运行时管理器（目标任务书 2.1 域1 改造）。

补齐 MiniYuxi 缺失的「进程级 agent manager」：支撑多并发长会话。

设计约束（守红线，见目标任务书 §6）：
- 不触碰指纹文件 agent.py / rag.py / db.py；
- 复用现有同步 ReAct 大脑 core.agent_loop.run（不重写）；
- 并发用 ThreadPoolExecutor（不强行全栈 asyncio 化，避免破坏同步栈与 egress 收口）；
- 长会话：AgentSession 持有累积 messages，跨请求 resume（进程级单例保活）；
- 外部调用仍经 agent_loop → gateway（已收口 egress，合规不掉链子）。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future

from . import agent_loop, config

# 进程级单例状态
_lock = threading.RLock()
_sessions: dict = {}  # session_id -> AgentSession
# 线程池：支撑多会话并发，不阻塞 Web 请求线程（同步栈零侵入）
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mx-agent")

DEFAULT_SYSTEM = "你是 MiniYuxi，一个企业级 HR/法务垂直 Agent。"


class AgentSession:
    """单个 agent 会话：持有累积对话，支撑跨请求长会话保活。"""

    def __init__(self, session_id, tenant_id, thread_id=None, system=None):
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.thread_id = thread_id  # 预留：将来映射到持久化对话线程
        self.system = system or DEFAULT_SYSTEM
        self.messages = []          # 累积对话（长会话保活）
        self.created_at = time.time()
        self.last_active = time.time()
        self.status = "idle"        # idle | running | done | cancelled | error
        self.last_result = None
        self.error = None
        self._future = None
        self._cancel_requested = False

    def submit(self, user_prompt):
        """异步执行一轮（线程池），返回 Future；同一 session 串行（不并发两轮）。"""
        if self.status == "running":
            return None
        self._cancel_requested = False
        self._future = _executor.submit(self._step, user_prompt)
        return self._future

    def _step(self, user_prompt):
        self.status = "running"
        self.last_active = time.time()
        try:
            res = agent_loop.run(self.system, user_prompt,
                                 history=self.messages, tenant_id=self.tenant_id)
            if res is None:
                self.status = "error"
                self.error = "offline_or_gateway_failed"
                return {"ok": False, "reason": "offline_or_gateway_failed"}
            # 累积历史（长会话保活）；agent_loop 内部 tool 消息不跨轮保留（高层 user/assistant 足够）
            self.messages.append({"role": "user", "content": user_prompt})
            self.messages.append({"role": "assistant", "content": res.get("answer", "")})
            self.last_result = res
            self.status = "idle"
            self.last_active = time.time()
            return {"ok": True, **res}
        except Exception as e:  # noqa: BLE001
            self.status = "error"
            self.error = str(e)
            return {"ok": False, "error": str(e)}

    def cancel(self):
        """请求取消（协作式：运行中无法强制中断同步 loop，仅标记）。"""
        self._cancel_requested = True
        if self.status != "running":
            self.status = "cancelled"
        return self._cancel_requested

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "thread_id": self.thread_id,
            "status": self.status,
            "turns": len([m for m in self.messages if m.get("role") == "user"]),
            "created_at": self.created_at,
            "last_active": self.last_active,
            "error": self.error,
        }


class AgentManager:
    """进程级 agent 运行时管理器（单例，按 session 管理长会话 + 并发）。"""

    @staticmethod
    def create(session_id, tenant_id, thread_id=None, system=None):
        with _lock:
            if session_id in _sessions:
                return _sessions[session_id]
            s = AgentSession(session_id, tenant_id, thread_id, system)
            _sessions[session_id] = s
            return s

    @staticmethod
    def get(session_id):
        with _lock:
            return _sessions.get(session_id)

    @staticmethod
    def submit(session_id, user_prompt):
        s = AgentManager.get(session_id)
        if not s:
            return None
        if s.status == "running":
            return None
        return s.submit(user_prompt)

    @staticmethod
    def cancel(session_id):
        s = AgentManager.get(session_id)
        return s.cancel() if s else False

    @staticmethod
    def list_sessions(tenant_id=None):
        with _lock:
            return [s.to_dict() for sid, s in _sessions.items()
                    if tenant_id is None or s.tenant_id == tenant_id]

    @staticmethod
    def prune_idle(max_idle=3600):
        """清理超过 max_idle 秒且非运行中的闲置会话（防内存泄漏）。返回清理数。"""
        with _lock:
            now = time.time()
            dead = [sid for sid, s in _sessions.items()
                    if now - s.last_active > max_idle and s.status != "running"]
            for sid in dead:
                del _sessions[sid]
            return len(dead)

    @staticmethod
    def shutdown():
        _executor.shutdown(wait=False)
