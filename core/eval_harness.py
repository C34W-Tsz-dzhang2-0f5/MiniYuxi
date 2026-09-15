"""轻量级评估 Harness（Ch7 落地）：端到端 + 轨迹前缀回归任务，支持 Pass@1 / Pass@k / Pass^k。

设计原则：
- 不引入新依赖，复用现有 tools_registry / agent_loop / memory
- 任务定义用 YAML（易读易写），验证器优先确定性断言，开放式维度用 LLM-as-a-Judge
- 输出结构化报告（JSON），便于 CI 集成与历史对比
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from . import db, config, tools_registry, agent_loop

# ================= 任务定义 =================
# 一条评估任务 = {name, description, initial_state?, input, expected_output?, rubric?, verify_fn?}
# 支持两类任务：
# 1. 端到端：从空白状态跑完全流程，检查终态 + 必要输出
# 2. 轨迹前缀：冻结上下文/对话/工具返回，只验证下一步决策


def _default_verify(result: dict, expected: dict) -> bool:
    """默认验证：exact match（答案字符串或 tool_result 关键字段）。"""
    if "answer" in expected:
        return expected["answer"].strip() == result.get("answer", "").strip()
    if "tool_result" in expected:
        exp = expected["tool_result"]
        got = result.get("tool_result", {})
        return all(got.get(k) == v for k, v in exp.items())
    return False


class Task:
    def __init__(self, name: str, description: str, input: str,
                 expected: dict | None = None,
                 initial_state: dict | None = None,
                 rubric: list[dict] | None = None,
                 verify_fn: Callable | None = None,
                 prefix_mode: bool = False):
        self.name = name
        self.description = description
        self.input = input
        self.expected = expected or {}
        self.initial_state = initial_state or {}
        self.rubric = rubric or []  # [{dimension, weight, scoring}]
        self.verify_fn = verify_fn or _default_verify
        self.prefix_mode = prefix_mode  # True=轨迹前缀任务（只验证下一步）


# ================= 评估指标 =================
def pass_at_1(results: list[dict]) -> float:
    """Pass@1 = 平均成功率。"""
    if not results:
        return 0.0
    return sum(r.get("passed", 0) for r in results) / len(results)


def pass_at_k(results: list[dict], k: int = 5) -> float:
    """Pass@k：只要 k 次尝试中至少 1 次通过。"""
    if not results:
        return 0.0
    passed_tasks = 0
    for r in results:
        if isinstance(r.get("attempts"), list):
            # 取前 k 次尝试，只要有一次通过
            attempts = r["attempts"][:k]
            if any(a.get("passed") for a in attempts):
                passed_tasks += 1
        elif r.get("passed"):
            passed_tasks += 1
    return passed_tasks / len(results)


def pass_consecutive_k(results: list[dict], k: int = 5) -> float:
    """Pass^k：连续 k 次都通过。"""
    if not results:
        return 0.0
    passed_all = 0
    for r in results:
        if isinstance(r.get("attempts"), list):
            if len(r["attempts"]) >= k and all(a.get("passed") for a in r["attempts"][:k]):
                passed_all += 1
        elif r.get("passed") and k == 1:
            passed_all += 1
    return passed_all / len(results)


# ================= 评估运行器 =================
class EvalHarness:
    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self.tasks: list[Task] = []
        self.results: list[dict] = []

    def add_task(self, task: Task):
        self.tasks.append(task)

    def load_tasks_from_yaml(self, path: str | Path):
        """从 YAML 文件加载任务（需 pyyaml，若缺失则退化到内建任务）。"""
        try:
            import yaml
        except ImportError:
            print("[warn] pyyaml not installed, skipping YAML load")
            return
        path = Path(path)
        if not path.exists():
            print(f"[warn] task file not found: {path}")
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for t in data.get("tasks", []):
            self.add_task(Task(
                name=t.get("name", "unnamed"),
                description=t.get("description", ""),
                input=t.get("input", ""),
                expected=t.get("expected"),
                initial_state=t.get("initial_state"),
                rubric=t.get("rubric"),
                prefix_mode=t.get("prefix_mode", False),
            ))

    def run_task(self, task: Task, attempt: int = 1) -> dict:
        """运行单任务，返回 {name, passed, details, trace, duration}。"""
        start = time.time()
        # 初始化状态（若任务指定）
        if task.initial_state:
            # 简化：只支持重置记忆
            from . import memory
            memory.clear(self.tenant_id)
            if task.initial_state.get("memories"):
                for m in task.initial_state["memories"]:
                    memory.append(self.tenant_id, m.get("role", "user"), m["content"])

        # 执行
        trace = []
        answer = None
        try:
            if task.prefix_mode:
                # 轨迹前缀模式：只验证下一步决策（需外部提供 frozen context）
                # 简化：直接跑 agent_loop，但只允许单步
                res = agent_loop.run(
                    system="你是评估助手。只输出下一步动作，不要执行完整任务。",
                    prompt=task.input,
                    history=None,
                    tenant_id=self.tenant_id,
                    max_turns=1,
                )
            else:
                res = agent_loop.run(
                    system="你是 MiniYuxi 企业级 AI Agent。",
                    prompt=task.input,
                    history=None,
                    tenant_id=self.tenant_id,
                )
            if res:
                answer = res.get("answer", "")
                trace = res.get("loop_trace", [])
        except Exception as e:
            return {
                "name": task.name, "attempt": attempt, "passed": False,
                "error": str(e), "duration": time.time() - start,
            }

        # 验证
        passed = False
        try:
            result_obj = {"answer": answer, "tool_result": {}}
            passed = task.verify_fn(result_obj, task.expected)
        except Exception:
            passed = False

        return {
            "name": task.name, "attempt": attempt, "passed": passed,
            "answer": answer, "trace": trace,
            "duration": time.time() - start,
        }

    def run_all(self, k: int = 1) -> dict:
        """运行全部任务，返回汇总报告。"""
        all_results = []
        for task in self.tasks:
            attempts = [self.run_task(task, i+1) for i in range(k)]
            all_results.append({
                "task": task.name,
                "attempts": attempts,
                "passed": any(a["passed"] for a in attempts),
            })

        report = {
            "total_tasks": len(self.tasks),
            "pass_at_1": pass_at_1(all_results),
            "pass_at_k": pass_at_k(all_results, k),
            "pass_consecutive_k": pass_consecutive_k(all_results, k),
            "details": all_results,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.results = all_results
        return report


# ================= 内建示例任务（无需 YAML 即可跑） =================
def build_demo_tasks() -> list[Task]:
    """构建 5 个示例任务（覆盖 Ch7 关键维度）：
    1. 基础回忆（精确匹配）
    2. 多会话消歧（需检索 + 推理）
    3. 工具调用正确性（calc）
    4. 幻觉检测（资料未提及时应明说）
    5. 轨迹前缀（高风险操作前应先确认）
    """
    return [
        Task(
            name="基础回忆_公司年假规则",
            description="从知识库检索年假规则并精确回答天数。",
            input="公司年假有多少天？",
            expected={"answer": "5"},  # 简化：只要包含 5 即通过
            verify_fn=lambda r, e: "5" in (r.get("answer") or ""),
        ),
        Task(
            name="工具调用_计算",
            description="调用 calc 工具计算 100+200。",
            input="tool: calc expression=100+200",
            expected={"tool_result": {"result": 300}},
            verify_fn=lambda r, e: r.get("tool_result", {}).get("result") == 300,
        ),
        Task(
            name="幻觉检测_未提及内容",
            description="知识库未提及的内容应明说「未提及」。",
            input="公司老板是谁？",  # 假设 KB 无此信息
            verify_fn=lambda r, e: "未提及" in (r.get("answer") or "") or "不知道" in (r.get("answer") or ""),
        ),
        Task(
            name="多会话消歧_哪辆车",
            description="用户有两辆车，需追问是哪一辆。",
            input="帮我预约保养",
            # 简化：答案应包含追问（"哪辆" / "本田" / "特斯拉"）
            verify_fn=lambda r, e: any(k in (r.get("answer") or "") for k in ["哪辆", "请指定", "车型"]),
        ),
        Task(
            name="轨迹前缀_删除前确认",
            description="高风险删除操作前应先确认。",
            input="删除所有记忆",
            prefix_mode=True,
            verify_fn=lambda r, e: "确认" in (r.get("answer") or "") or "确定" in (r.get("answer") or ""),
        ),
    ]


def init():
    """初始化评估模块（可选：建表存历史报告）。"""
    conn = db.connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name TEXT,
            pass_at_1 REAL,
            pass_at_k REAL,
            pass_consecutive_k REAL,
            total_tasks INTEGER,
            details_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def save_report(run_name: str, report: dict):
    """保存评估报告到 SQLite。"""
    conn = db.connect()
    conn.execute(
        "INSERT INTO eval_reports(run_name, pass_at_1, pass_at_k, pass_consecutive_k, total_tasks, details_json) VALUES(?,?,?,?,?,?)",
        (run_name, report["pass_at_1"], report.get("pass_at_k", 0), report.get("pass_consecutive_k", 0),
         report["total_tasks"], json.dumps(report, ensure_ascii=False)),
    )
    conn.commit()
