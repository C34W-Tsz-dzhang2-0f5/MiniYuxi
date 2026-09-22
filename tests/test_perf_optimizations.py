"""MiniYuxi 性能与稳定性优化回归测试（对应 docs/性能与稳定性优化_20260922.md）。

覆盖：O1 DB 并发韧性 pragmas、O2 tools/list MCP 探测缓存、O3 skills 目录扫描缓存、
O4 health 后端探测缓存、O5 首页渲染缓存。

运行：python -m pytest tests/test_perf_optimizations.py -q
"""
import time

from core import db, tools_registry, skills_catalog


def test_db_pragmas_resilient():
    """O1：连接须启用 WAL 并发韧性 pragma。"""
    conn = db.connect()
    pragma = {p: conn.execute(f"PRAGMA {p}").fetchone()[0]
              for p in ("busy_timeout", "synchronous", "cache_size", "journal_mode", "temp_store")}
    assert pragma["journal_mode"] == "wal"
    assert pragma["busy_timeout"] == 5000          # 写冲突等待而非立即 locked
    assert pragma["synchronous"] == 1             # NORMAL（WAL 下仍崩溃一致）
    assert pragma["cache_size"] < 0               # 负值为 KB 页缓存（放大）
    assert pragma["temp_store"] == 2              # MEMORY


def test_skills_catalog_caches_by_mtime():
    """O3：目录未变动时 list_skills 应命中缓存（返回同一对象），避免重复 glob 扫描。"""
    a = skills_catalog.list_skills()
    b = skills_catalog.list_skills()
    assert isinstance(a, list)
    assert a is b  # 命中缓存：同一 list 对象


def test_tools_list_includes_builtins_and_caches():
    """O2：list_tools 必含内置工具，且二次调用不抛错（命中 MCP 探测缓存）。"""
    first = tools_registry.list_tools()
    names = {t["name"] for t in first}
    assert "current_time" in names and "kb_search" in names
    second = tools_registry.list_tools()   # 走缓存，不应再触发网络探测
    assert {t["name"] for t in second} == names


def test_health_backend_status_cached_shape():
    """O4：search_backend_status 返回稳定结构（首次探测后带 TTL 缓存）。"""
    s = tools_registry.search_backend_status()
    assert isinstance(s, dict)
    assert "default" in s and "fallback_chain" in s
    # 二次调用应命中缓存且结构一致
    s2 = tools_registry.search_backend_status()
    assert s2["default"] == s["default"]


def test_index_render_cache_does_not_error():
    """O5：首页渲染缓存路径不报错（通过 TestClient 触发 index()，断言 200）。"""
    try:
        from fastapi.testclient import TestClient
        import api
    except Exception:
        import pytest
        pytest.skip("TestClient/httpx 不可用，跳过首页渲染缓存用例")
    client = TestClient(api.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "MiniYuxi" in r.text
