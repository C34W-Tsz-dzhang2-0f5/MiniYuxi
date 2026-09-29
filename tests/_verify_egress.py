# -*- coding: utf-8 -*-
"""数据出境管控（core/egress.py）验证：策略 / 闸门 / 日志 / 端到端拦截。

分两层：
  A. 逻辑层（纯离线）：分级、脱敏、策略解析、策略往返、预设、闸门三态、日志与统计。
  B. 端到端（关键）：设 MINIYUXI_EGRESS_LLM=deny 后调 gateway.chat()，
     必须返回 err=egress_denied **且 requests.post 一次都没被调用** ——
     证明「拒绝」是真的没发出去，而不是发完再报错。

用法：
    .venv/Scripts/python.exe tests/_verify_egress.py

用独立临时库（MINIYUXI_DB 指向临时文件），不污染真实 data/miniyuxi.db。
"""
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ⚠️ 必须在 import core.config 之前设好，config 在导入时就把 DB_PATH 定下来了
_TMP = tempfile.mkdtemp(prefix="mx-egress-verify-")
os.environ["MINIYUXI_DATA_DIR"] = _TMP
os.environ["MINIYUXI_DB"] = os.path.join(_TMP, "verify.db")
# 清掉可能存在的策略环境变量，保证基线干净
for _k in ("MINIYUXI_EGRESS_LLM", "MINIYUXI_EGRESS_EMBEDDING", "MINIYUXI_EGRESS_SEARCH",
           "MINIYUXI_EGRESS_EXTERNAL_RAG", "MINIYUXI_EGRESS_CONNECTOR",
           "MINIYUXI_EGRESS_LOCKDOWN", "MINIYUXI_EGRESS_FAIL_MODE"):
    os.environ.pop(_k, None)

from core import db, egress, soc_audit, approval, gateway  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {extra}" if extra and not cond else ""))


def main():
    db.init_db()
    egress.init()
    soc_audit.init()
    approval.init()

    # ============ A. 分级 ============
    print("\n[A] 数据分级 classify()")
    check("工资表文本 -> confidential", egress.classify("张三 2026年9月工资 18500元") == "confidential")
    check("身份证号 -> confidential", egress.classify("身份证 440301199001011234") == "confidential")
    check("普通业务问题 -> internal", egress.classify("公司的年假怎么算") == "internal")
    check("空文本 -> public", egress.classify("") == "public")
    check("辞退关键词 -> confidential", egress.classify("关于解除劳动合同的通知") == "confidential")

    # ============ 脱敏 ============
    print("\n[A] 日志脱敏 redact()")
    r = egress.redact("联系 13812345678 或 test@corp.com，卡号 6222021234567890123")
    check("手机号被脱敏", "13812345678" not in r, r)
    check("邮箱被脱敏", "test@corp.com" not in r, r)
    check("银行卡被脱敏", "6222021234567890123" not in r, r)
    long_r = egress.redact("x" * 500)
    check("摘要截断到 200 字符", len(long_r) <= 200, f"len={len(long_r)}")

    # ============ 策略解析 ============
    print("\n[A] 策略解析 effective_mode()")
    egress.set_policy(egress.PRESETS["balanced"]["policy"])
    check("默认 allow", egress.effective_mode("llm", "internal") == "allow")
    check("默认 allow（机密级也是 allow）", egress.effective_mode("llm", "confidential") == "allow")

    egress.apply_preset("strict")
    check("strict: 机密级 llm -> approval", egress.effective_mode("llm", "confidential") == "approval")
    check("strict: 普通 llm -> allow", egress.effective_mode("llm", "internal") == "allow")
    check("strict: search 不受机密级约束", egress.effective_mode("search", "confidential") == "allow")

    egress.apply_preset("lockdown")
    check("lockdown 预设: 全 deny", all(egress.effective_mode(c, lv) == "deny"
                                        for c in egress.CLASSES for lv in egress.LEVELS))

    egress.apply_preset("balanced")
    os.environ["MINIYUXI_EGRESS_LLM"] = "deny"
    check("环境变量覆盖策略（最高优先级）", egress.effective_mode("llm", "internal") == "deny")
    os.environ.pop("MINIYUXI_EGRESS_LLM", None)
    os.environ["MINIYUXI_EGRESS_LOCKDOWN"] = "1"
    check("LOCKDOWN 环境变量 -> 全 deny", egress.effective_mode("search", "public") == "deny")
    os.environ.pop("MINIYUXI_EGRESS_LOCKDOWN", None)

    # 策略往返（写进去读出来要一致）
    print("\n[A] 策略往返 get/set")
    egress.set_policy({"classes": {"llm": {"default": "approval",
                                          "by_level": {"confidential": "deny"}}}})
    pol = egress.get_policy()
    check("写入 default=approval 生效", pol["classes"]["llm"]["default"] == "approval")
    check("写入 by_level 生效", pol["classes"]["llm"]["by_level"].get("confidential") == "deny")
    egress.set_policy({"classes": {"llm": {"default": "banana"}}})  # 非法值
    check("非法 mode 被丢弃而非写入", egress.get_policy()["classes"]["llm"]["default"] == "approval")
    egress.apply_preset("balanced")

    # ============ 闸门三态 ============
    print("\n[A] 闸门 guard() 三态 + 留痕")
    before = len(egress.list_log(limit=1000))
    g = egress.guard("llm", "https://api.siliconflow.cn/v1", "张三9月工资18500元", tenant_id="t1")
    check("allow 模式放行", g["allow"] is True and g["mode"] == "allow", str(g))
    check("allow 时判为 confidential", g["level"] == "confidential", str(g))
    check("allow 写了 log_id", g["log_id"] is not None)
    logs = egress.list_log(limit=5)
    check("日志已落库", len(egress.list_log(limit=1000)) == before + 1)
    check("日志只存脱敏摘要（无手机号/无全文）",
          all("13812345678" not in (l.get("summary") or "") for l in logs))
    check("日志记了目的地主机而非完整 URL",
          any(l.get("dest_host") == "api.siliconflow.cn" for l in logs))

    egress.set_policy({"classes": {"llm": {"default": "deny"}}})
    g2 = egress.guard("llm", "https://api.siliconflow.cn/v1", "问题", tenant_id="t1")
    check("deny 模式拒绝", g2["allow"] is False and g2["mode"] == "deny", str(g2))
    check("deny 也留痕（可审计被拒行为）", g2["log_id"] is not None)
    check("deny 决策写入日志", any(l["decision"] == "deny" for l in egress.list_log(limit=20)))

    egress.apply_preset("strict")
    ap_before = len(approval.list_all() if hasattr(approval, "list_all") else [])
    g3 = egress.guard("llm", "https://api.siliconflow.cn/v1", "张三工资18500", tenant_id="t1",
                      session_id="sess-1")
    check("approval 模式不放行", g3["allow"] is False and g3["mode"] == "approval", str(g3))
    check("approval 建了审批卡", bool(g3.get("approval_id")), str(g3))
    check("approval 决策写入日志", any(l["decision"] == "pending" for l in egress.list_log(limit=20)))
    egress.apply_preset("balanced")

    # 未知类别 / 异常不崩
    print("\n[A] 健壮性")
    gx = egress.guard("not_a_class", "https://x.example.com", "hi")
    check("未知类别不抛栈（默认放行）", isinstance(gx, dict) and "allow" in gx, str(gx))
    check("blocked() 布尔语义正确",
          egress.blocked("llm", "https://x.cn", "hi") is False)
    egress.set_policy({"classes": {"llm": {"default": "deny"}}})
    check("blocked() 拒绝时为 True", egress.blocked("llm", "https://x.cn", "hi") is True)
    egress.apply_preset("balanced")

    # ============ inventory / stats ============
    print("\n[A] 自描述与统计")
    inv = egress.inventory()
    check("inventory 覆盖 5 类目的地", len(inv["classes"]) == 5, str(len(inv["classes"])))
    check("每类都有收口点与三级模式",
          all(c.get("sites") and len(c.get("modes_by_level", {})) == 3 for c in inv["classes"]))
    check("inventory 暴露预设", set(inv["presets"]) == {"balanced", "strict", "lockdown"})
    st = egress.stats()
    check("stats 有汇总", st["total"] >= 3 and "by_class" in st and "by_decision" in st, str(st)[:200])
    check("stats 统计到 deny", st["by_decision"].get("deny", {}).get("count", 0) >= 1, str(st["by_decision"]))

    # ============ B. 端到端：deny 时真的不发包 ============
    print("\n[B] 端到端：策略拒绝 => 零发包（关键验证）")
    import requests as _rq
    import core.config as _cfg
    _orig_post = _rq.post
    _orig_key = _cfg.LLM_API_KEY
    calls = []

    def _spy(*a, **kw):
        calls.append(a[0] if a else kw.get("url"))
        raise AssertionError(f"策略已拒绝，不应发起网络请求！url={a[0] if a else ''}")

    try:
        # ⚠️ 注意：gateway.chat 里「无 Key → 离线兜底」的判断在出境闸门**之前**
        #   （合理：没 Key 就没出境可言）。所以要让闸门真正被触发，必须先给一个假 Key。
        #   这里直接打补丁 core.config.LLM_API_KEY —— llm_enabled() 是调用时读模块属性，
        #   直接赋值即生效；不要用 importlib.reload(gateway)，那不会重载已缓存的 config。
        _cfg.LLM_API_KEY = "fake-key-for-test"
        os.environ["MINIYUXI_EGRESS_LLM"] = "deny"

        _rq.post = _spy
        res = gateway.chat("你是助手", "张三9月工资多少", tenant_id="t1")
        check("gateway.chat 返回 egress_denied", res.get("err") == "egress_denied", str(res))
        check("gateway.chat 未发起任何网络请求", len(calls) == 0, f"calls={calls}")
        check("被拒后 ok=False（上层可降级）", res.get("ok") is False)
        streamed = list(gateway.chat_stream("你是助手", "工资多少", tenant_id="t1"))
        check("chat_stream 被拒时零产出", streamed == [], str(streamed))
        check("chat_stream 也未发包", len(calls) == 0, f"calls={calls}")

        # 放行时必须真的走到网络层（否则说明闸门把功能掐死了 —— 反向验证）
        os.environ.pop("MINIYUXI_EGRESS_LLM", None)
        calls.clear()
        try:
            gateway.chat("你是助手", "普通问题", tenant_id="t1")
        except Exception:
            pass  # spy 抛 AssertionError，说明确实发起了请求 —— 正是我们要的
        check("放行时闸门不阻断（确实走到网络层）", len(calls) >= 1, f"calls={calls}")
    finally:
        _rq.post = _orig_post
        _cfg.LLM_API_KEY = _orig_key
        os.environ.pop("MINIYUXI_EGRESS_LLM", None)

    # ============ D. 五类目的地逐一出出口验证（证明「10/10 全覆盖」不是口头声明）============
    print("\n[D] 五类目的地出口逐一验证（策略拒绝 => 该出口零发包）")
    import urllib.request as _ur
    from core import rag, rag_adapter, tools_registry, connectors, provider_router, model_hub

    _orig_urlopen = _ur.urlopen
    net = []

    def _post_spy(*a, **kw):
        net.append(("requests.post", a[0] if a else kw.get("url")))
        raise AssertionError("不应发起请求")

    def _url_spy(*a, **kw):
        net.append(("urlopen", a[0] if a else kw.get("url")))
        raise AssertionError("不应发起请求")

    _rq.post = _post_spy
    _ur.urlopen = _url_spy
    _orig_emb_key = _cfg.EMB_API_KEY
    try:
        # --- 1. llm / model_hub ---
        model_hub.init()
        db.connect().execute(
            "INSERT OR REPLACE INTO model_providers(id,api_key,base_url,enabled) "
            "VALUES('siliconflow','fake-key','https://api.siliconflow.cn/v1',1)")
        db.connect().commit()
        net.clear()
        os.environ["MINIYUXI_EGRESS_LLM"] = "deny"
        r1 = model_hub.chat("Qwen/Qwen2.5-72B-Instruct", "你是助手", "张三工资18500")
        check("[llm] model_hub 被拦 + 零发包",
              r1.get("err") == "egress_denied" and len(net) == 0, f"{r1.get('err')} net={net}")

        # --- 2. llm / provider_router（故障转移也不能绕过管控）---
        provider_router.init()
        provider_router.register_provider({
            "id": "p1", "name": "P1", "kind": "openai",
            "base_url": "https://api.siliconflow.cn/v1", "api_key": "fake-key", "model": "m1"})
        net.clear()
        r2 = provider_router.chat("你是助手", "张三工资18500", tenant_id="t1")
        check("[llm] provider_router 被拦 + 零发包",
              r2.get("ok") is False and len(net) == 0, f"{r2.get('err')} net={net}")

        # --- 3. embedding / rag.embed（载荷=文档原文，最敏感）---
        os.environ.pop("MINIYUXI_EGRESS_LLM", None)
        os.environ["MINIYUXI_EGRESS_EMBEDDING"] = "deny"
        _cfg.EMB_API_KEY = "fake-key"
        net.clear()
        r3 = rag.embed(["员工张三 2026年9月工资 18500 元"])
        check("[embedding] rag.embed 返回 None（降级 BM25）+ 零发包",
              r3 is None and len(net) == 0, f"{r3} net={net}")

        # --- 4. search / tools_registry.web_search ---
        os.environ.pop("MINIYUXI_EGRESS_EMBEDDING", None)
        os.environ["MINIYUXI_EGRESS_SEARCH"] = "deny"
        net.clear()
        r4 = tools_registry._web_search("2026年最新社保基数")
        txt = r4.get("result", "") if isinstance(r4, dict) else str(r4)
        check("[search] web_search 被拦（友好降级文案）+ 零发包",
              "出境策略" in txt and len(net) == 0, f"{txt[:60]} net={net}")

        # --- 5. external_rag / rag_adapter ---
        os.environ.pop("MINIYUXI_EGRESS_SEARCH", None)
        os.environ["MINIYUXI_EGRESS_EXTERNAL_RAG"] = "deny"
        net.clear()
        raised = False
        try:
            rag_adapter._http_post("https://ragflow.example.com/api/v1/x", {"question": "工资"},
                                   {"Authorization": "Bearer k"})
        except RuntimeError as e:
            raised = "egress_denied" in str(e)
        check("[external_rag] _http_post 被拦抛错 + 零发包",
              raised and len(net) == 0, f"raised={raised} net={net}")

        # --- 6. connector / connectors.send_message ---
        os.environ.pop("MINIYUXI_EGRESS_EXTERNAL_RAG", None)
        os.environ["MINIYUXI_EGRESS_CONNECTOR"] = "deny"
        connectors.init()
        cid = connectors.register("test-wecom", "wecom",
                                  {"endpoint": "https://qyapi.weixin.qq.com/cgi-bin/x", "token": "t"})
        net.clear()
        r6 = connectors.send_message(cid, "user1", "张三的工资是 18500")
        check("[connector] send_message 被拦（egress_denied）+ 零发包",
              r6.get("status") == "egress_denied" and len(net) == 0, f"{r6} net={net}")

        # --- 反向：放行时每个出口确实会发包（证明闸门不是把功能焊死）---
        for k in ("MINIYUXI_EGRESS_LLM", "MINIYUXI_EGRESS_EMBEDDING", "MINIYUXI_EGRESS_SEARCH",
                  "MINIYUXI_EGRESS_EXTERNAL_RAG", "MINIYUXI_EGRESS_CONNECTOR"):
            os.environ.pop(k, None)
        net.clear()
        try:
            rag.embed(["普通文本"])
        except Exception:
            pass
        check("[embedding] 放行时确实走到网络层", len(net) >= 1, f"net={net}")
        net.clear()
        try:
            connectors.send_message(cid, "user1", "hi")
        except Exception:
            pass
        check("[connector] 放行时确实走到网络层", len(net) >= 1, f"net={net}")
    finally:
        _rq.post = _orig_post
        _ur.urlopen = _orig_urlopen
        _cfg.EMB_API_KEY = _orig_emb_key
        for k in ("MINIYUXI_EGRESS_LLM", "MINIYUXI_EGRESS_EMBEDDING", "MINIYUXI_EGRESS_SEARCH",
                  "MINIYUXI_EGRESS_EXTERNAL_RAG", "MINIYUXI_EGRESS_CONNECTOR"):
            os.environ.pop(k, None)

    # ============ C. 哈希链完整性 ============
    print("\n[C] SOC 审计哈希链（出境事件已入链）")
    try:
        v = soc_audit.verify_chain()
        ok = v.get("ok") if isinstance(v, dict) else bool(v)
        check("审计链未断裂", ok, str(v)[:200])
    except Exception as e:
        check("审计链校验可执行", False, str(e))
    try:
        rows = db.connect().execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE action LIKE 'egress.%'").fetchone()
        check("审计链含 egress.* 事件", rows["n"] >= 3, f"n={rows['n']}")
    except Exception as e:
        check("可查 egress 审计事件", False, str(e))

    # ============ 汇总 ============
    print("\n" + "=" * 62)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
