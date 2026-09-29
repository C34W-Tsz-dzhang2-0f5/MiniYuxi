"""域13 流程画布后端（flow_store）验收。

离线：monkeypatch core.db.connect → 单一内存 sqlite，不碰真实库、不碰红线文件。
用法：python tests/_verify_flow_store.py
退出码 0 = 全通过；非 0 = 有失败。
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core.db as db_mod
_shared = sqlite3.connect(":memory:")
_shared.row_factory = sqlite3.Row  # 模拟真实 db.connect() 的 Row 工厂
db_mod.connect = lambda: _shared  # 单连接内存库，保证跨调用可持久

from core import flow_store


def _reset():
    flow_store.init()
    _shared.execute("DELETE FROM flows")
    _shared.commit()


def test_save_and_get():
    _reset()
    fid = flow_store.save_flow("", "t1", "招聘画布", {"nodes": [{"id": "n1"}], "edges": []})
    assert fid, "应返回 flow id"
    f = flow_store.get_flow(fid, "t1")
    assert f and f["name"] == "招聘画布"
    assert f["definition"]["nodes"][0]["id"] == "n1"
    print("[1] save/get OK")


def test_upsert():
    _reset()
    fid = flow_store.save_flow("", "t1", "A", {"x": 1})
    flow_store.save_flow(fid, "t1", "A2", {"x": 2})  # 同 id 覆盖
    f = flow_store.get_flow(fid, "t1")
    assert f["name"] == "A2" and f["definition"]["x"] == 2
    assert len(flow_store.list_flows("t1")) == 1, "upsert 不应新增行"
    print("[2] upsert OK")


def test_list_and_tenant_isolation():
    _reset()
    flow_store.save_flow("", "t1", "a", {})
    flow_store.save_flow("", "t2", "b", {})
    assert len(flow_store.list_flows("t1")) == 1
    assert len(flow_store.list_flows("t2")) == 1
    print("[3] 租户隔离 OK")


def test_delete():
    _reset()
    fid = flow_store.save_flow("", "t1", "del", {})
    assert flow_store.delete_flow(fid, "t1") == 1
    assert flow_store.get_flow(fid, "t1") is None
    print("[4] delete OK")


def test_definition_string_or_dict():
    _reset()
    fid = flow_store.save_flow("", "t1", "strdef", '{"nodes":[]}')
    f = flow_store.get_flow(fid, "t1")
    assert isinstance(f["definition"], dict) and f["definition"]["nodes"] == []
    print("[5] 字符串/字典定义兼容 OK")


if __name__ == "__main__":
    test_save_and_get()
    test_upsert()
    test_list_and_tenant_isolation()
    test_delete()
    test_definition_string_or_dict()
    print("\nALL FLOW_STORE TESTS PASSED")
    sys.exit(0)
