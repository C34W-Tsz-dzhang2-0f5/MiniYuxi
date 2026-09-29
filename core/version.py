# -*- coding: utf-8 -*-
"""MiniYuxi 版本号**唯一来源**（Single Source of Truth）。

为什么需要这个文件
------------------
2026-09-24 排查发现版本号有多个独立副本且互相漂移：
    api.py        -> "0.1.0"   （FastAPI app version + /api/health 返回）
    core/mcp_client.py -> "0.1.0"（MCP clientInfo）
    run.py / cli.py / pyproject.toml / tauri.conf.json / package.json / Cargo.toml -> "0.2.0"
    CHANGELOG.md  -> 最新已发布 0.2.2
对「企业级、可商用」的交付来说，对外报三个不同版本号是硬伤。

约定
----
- **Python 侧一律 `from core.version import __version__`**，不要再写字符串字面量。
- 非 Python 清单（`pyproject.toml` / `tauri.conf.json` / `apps/desktop/package.json` /
  `apps/desktop/src-tauri/Cargo.toml` / `CHANGELOG.md`）无法 import，只能手写，
  但**必须与本文件一致** —— 由 `scripts/check_version_consistency.py` 强制校验（可进 CI）。

改版本的正确流程
----------------
1. 改本文件的 `__version__`；
2. 同步改上面列的 4 个清单文件；
3. 在 `CHANGELOG.md` 顶部把 `[Unreleased]` 定版为新版本号；
4. 跑 `python scripts/check_version_consistency.py` 确认全绿。
"""

# 版本号遵循 SemVer：https://semver.org/lang/zh-CN/
# 0.3.0 = 新增 univer 办公操作面（表格/文档）+ 本地工具市场 + 公式引擎（均为新功能，minor 位）
# 0.4.0 = 新增「数据出境开关 + 出境日志」（企业级定位落地的核心能力，minor 位）
__version__ = "0.4.0"

# 对外展示用的产品名（避免各处再写一遍字面量）
APP_NAME = "MiniYuxi"

__all__ = ["__version__", "APP_NAME"]
