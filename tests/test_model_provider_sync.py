# -*- coding: utf-8 -*-
"""多模型中心 Key 配置的回归测试：
1. set_provider 落库 model_providers 的同时必须同步注册进 provider_router（llm_providers），
   让工作台 Agent 模式（故障转移链）用上同一份 Key；
2. 空 Key / 离线兜底 / 自定义供应商不得注册脏条目。
"""
import sqlite3

from core import db as dbmod
from core import model_hub


def _fake_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE model_providers(
        id TEXT PRIMARY KEY, api_key TEXT, base_url TEXT,
        enabled INTEGER, updated_at TEXT)""")
    conn.execute("""CREATE TABLE llm_providers(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'openai',
        base_url TEXT NOT NULL, api_key TEXT NOT NULL DEFAULT '', model TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')))""")
    monkeypatch.setattr(dbmod, "connect", lambda: conn)
    return conn


def test_set_provider_syncs_key_into_router(monkeypatch):
    conn = _fake_db(monkeypatch)
    model_hub.set_provider("deepseek", api_key="sk-test-123",
                           base_url="https://api.deepseek.com/v1", enabled=True)
    row = conn.execute("SELECT * FROM llm_providers WHERE id='hub:deepseek'").fetchone()
    assert row is not None, "保存 Key 后必须同步注册进 provider_router"
    assert row["api_key"] == "sk-test-123"
    assert row["model"] == "deepseek-chat", "同步条目应带该供应商目录中的默认模型名"
    assert row["enabled"] == 1


def test_set_provider_empty_key_not_registered(monkeypatch):
    conn = _fake_db(monkeypatch)
    model_hub.set_provider("mimo", api_key="", base_url="", enabled=True)
    n = conn.execute("SELECT COUNT(*) c FROM llm_providers").fetchone()["c"]
    assert n == 0, "无 Key 不得注册空条目"


def test_set_provider_offline_and_custom_skipped(monkeypatch):
    conn = _fake_db(monkeypatch)
    model_hub.set_provider("offline", api_key="x", base_url="", enabled=True)
    model_hub.set_provider("custom", api_key="x", base_url="https://x/v1", enabled=True)
    n = conn.execute("SELECT COUNT(*) c FROM llm_providers").fetchone()["c"]
    assert n == 0, "离线兜底与自定义供应商不进故障转移链"


def test_set_provider_disable_updates_router_entry(monkeypatch):
    conn = _fake_db(monkeypatch)
    model_hub.set_provider("deepseek", api_key="sk-a", base_url="", enabled=True)
    model_hub.set_provider("deepseek", api_key="", base_url="", enabled=False)  # 留空=保留原 Key
    row = conn.execute("SELECT * FROM llm_providers WHERE id='hub:deepseek'").fetchone()
    assert row is not None
    assert row["api_key"] == "sk-a", "重复保存留空 Key 时不得清掉已同步的 Key"
    assert row["enabled"] == 0, "停用供应商必须同步停用 router 条目"
