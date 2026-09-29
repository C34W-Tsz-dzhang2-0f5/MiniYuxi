"""域15 专家市场 manifest 验收。

离线：build_manifest() 复用 skills_catalog.list_skills()（扫描项目 skills/，真实存在）。
用法：python tests/_verify_experts_manifest.py
退出码 0 = 全通过；非 0 = 有失败。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import experts_manifest, skills_catalog


def test_manifest_shape():
    m = experts_manifest.build_manifest()
    assert set(["generated_at", "count", "categories", "experts"]).issubset(m.keys()), "manifest 结构缺失字段"
    assert m["count"] == len(m["experts"]), "count 应与 experts 长度一致"
    print("[1] manifest 结构 OK，count =", m["count"])


def test_expert_fields():
    m = experts_manifest.build_manifest()
    req = ["id", "name", "category", "icon", "license", "version", "risk", "allowed_tools", "tags", "entrypoint"]
    for e in m["experts"]:
        for k in req:
            assert k in e, "专家缺字段：" + k
        assert e["icon"], "icon 不应为空"
        assert e["risk"] in ("low", "medium", "high"), "risk 取值非法"
    print("[2] 每个专家字段完整（含 icon/license/risk）OK")


def test_categories_aggregated():
    m = experts_manifest.build_manifest()
    total = sum(c["count"] for c in m["categories"])
    assert total == m["count"], "分类聚合之和应等于总数"
    print("[3] 分类聚合一致 OK")


def test_get_expert():
    m = experts_manifest.build_manifest()
    if m["experts"]:
        eid = m["experts"][0]["id"]
        e = experts_manifest.get_expert(eid)
        assert e and e["id"] == eid, "get_expert 应返回对应专家"
        assert experts_manifest.get_expert("__no_such__") is None, "未知 id 应返回 None"
    print("[4] get_expert 命中/未命中 OK")


def test_matches_skills_count():
    m = experts_manifest.build_manifest()
    sk = skills_catalog.list_skills()
    assert m["count"] == len(sk), "manifest 专家数应等于已注册技能数"
    print("[5] manifest 与 skills_catalog 计数一致 OK")


if __name__ == "__main__":
    test_manifest_shape()
    test_expert_fields()
    test_categories_aggregated()
    test_get_expert()
    test_matches_skills_count()
    print("\nALL EXPERTS_MANIFEST TESTS PASSED")
    sys.exit(0)
