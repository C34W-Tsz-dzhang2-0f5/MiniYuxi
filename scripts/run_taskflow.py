# -*- coding: utf-8 -*-
"""岗位任务流 CLI（验证/调试用）。
用法：
  python scripts/run_taskflow.py roles
  python scripts/run_taskflow.py list [role]
  python scripts/run_taskflow.py run <task_id> [--dry] [--real] [--model <id>] [--vars <json>] [--materials <json>]
  python scripts/run_taskflow.py workflow <task_id>
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import taskflow


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "roles"
    taskflow.init()
    if cmd == "roles":
        print(json.dumps(taskflow.list_roles(), ensure_ascii=False, indent=2))
    elif cmd == "list":
        role = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(taskflow.list_tasks(role), ensure_ascii=False, indent=2))
    elif cmd == "run":
        tid = sys.argv[2]
        dry = "--dry" in sys.argv
        real = "--real" in sys.argv
        model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else None
        variables = {
            "dept": "深圳车务通科技有限公司（陕西导航母公司下属）",
            "goal": "招聘 1 名结构开发工程师（嵌入式/C++ 方向），负责中控与 DVR 产品结构设计",
            "audience": "HR 招聘团队与硬件研发负责人",
            "deadline": "2026-09-20",
        }
        materials = ["《结构开发工程师岗位需求表》.docx", "现有薪酬带宽表.xlsx"]
        if "--vars" in sys.argv:
            variables = json.loads(sys.argv[sys.argv.index("--vars") + 1])
        if "--materials" in sys.argv:
            materials = json.loads(sys.argv[sys.argv.index("--materials") + 1])
        if "--resume" in sys.argv:
            materials = [sys.argv[sys.argv.index("--resume") + 1]]
        if "--role" in sys.argv:
            variables = dict(variables, role_name=sys.argv[sys.argv.index("--role") + 1])
        r = taskflow.run_task(
            tid,
            variables=variables,
            materials=materials,
            dry=dry and not real,
            model=model,
        )
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif cmd == "workflow":
        tid = sys.argv[2]
        print(json.dumps(taskflow.get_workflow(tid), ensure_ascii=False, indent=2))
    else:
        print("unknown cmd:", cmd)


if __name__ == "__main__":
    main()
