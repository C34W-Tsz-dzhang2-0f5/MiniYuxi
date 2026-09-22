"""Coding Agent 自生成工具工厂 —— 离线确定性测试（无需 LLM / 联网）。

验证：
 1. 危险代码被静态校验拒绝（os/subprocess/eval/open）；
 2. 安全代码通过校验并成功安装；
 3. 生成的工具出现在 tools_registry（即会被自主 Agent Loop 自动发现）；
 4. 工具可被 call_tool 正确调用；
 5. 列出 / 删除 自生成工具 链路闭环。
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core import coding_agent, tools_registry, db  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
res = []


def check(name, ok, detail=""):
    res.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  → {detail}" if detail else ""))


def main():
    db.init_db()
    coding_agent.init()  # 建表 + 重载（幂等）
    NAME = "test_gen_unit"

    # 1. 危险代码拒绝
    bad = "import os\ndef run(tenant_id=None, **kwargs):\n    return {'result': os.system('echo hi')}"
    ok, err, _ = coding_agent.validate_tool_code(bad)
    check("危险代码（os）被拒绝", not ok, err)

    evil = "def run(tenant_id=None, **kwargs):\n    return {'result': eval('1+1')}"
    ok2, _, _ = coding_agent.validate_tool_code(evil)
    check("危险调用（eval）被拒绝", not ok2)

    # 2. 安全代码通过
    good = ("def run(tenant_id=None, **kwargs):\n"
            "    t = kwargs.get('text', '') or ''\n"
            "    return {'result': f'字符数={len(t)} 词数={len(t.split())} 行数={t.count(chr(10))+1}'}")
    ok3, err3, _ = coding_agent.validate_tool_code(good)
    check("安全代码通过校验", ok3, err3)

    # 3. 安装 + 注册进 tools_registry
    d = coding_agent.generate_tool("default", "统计文本指标", code=good, name=NAME)
    check("生成并安装工具 ok", d.get("ok") is True, str(d))
    names = {t["name"] for t in tools_registry.list_tools()}
    check("工具出现在 registry（Agent 可发现）", NAME in names)

    # 4. 调用工具
    r = tools_registry.call_tool(NAME, {"text": "hello world foo"}, tenant_id="default")
    check("工具被正确调用", "result" in r and "字符数=" in str(r.get("result", "")) and "词数=3" in str(r.get("result", "")), str(r.get("result")))

    # 5. 列出 + 删除闭环
    listed = coding_agent.list_generated("default")
    check("list 含该工具", any(x["name"] == NAME for x in listed))
    rm = coding_agent.remove_tool("default", NAME)
    check("删除成功", rm.get("ok") is True)
    check("删除后 list 不再含该工具", not any(x["name"] == NAME for x in coding_agent.list_generated("default")))

    total = len(res)
    ok_n = sum(1 for _, s, _ in res if s)
    print(f"\n  Coding Agent 测试：{ok_n}/{total} 通过" + ("  ✅" if ok_n == total else "  ❌"))
    sys.exit(0 if ok_n == total else 1)


if __name__ == "__main__":
    main()
