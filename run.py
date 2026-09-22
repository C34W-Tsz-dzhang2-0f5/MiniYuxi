"""MiniYuxi 启动器：初始化数据库 → 起原生 uvicorn 进程 → 打开浏览器。

用法：
    python run.py            # 启动（默认 http://127.0.0.1:8801）
    python run.py --no-open  # 不自动开浏览器
"""
import argparse
import os
import secrets
import sys
import threading
import time
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Windows 控制台默认 GBK 编码无法输出 ⚠/✗ 等字符会导致启动崩溃；
# 强制 stdout/stderr 为 UTF-8（双击 .bat 或任意 GBK 终端均安全）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 默认裸奔密钥（与 core/config.py 保持一致；一旦仍为此值，run.py 会自行生成随机密钥）
DEFAULT_SECRET = "dev-only-change-me-please-32bytes"


def _frozen_bootstrap() -> None:
    """PyInstaller 冻结（桌面 sidecar 打包）时，把数据目录固定到用户目录。

    冻结后 BASE_DIR 指向临时解压目录 _MEIPASS，若沿用会造成「每次启动都像全新安装」。
    这里在 import core 之前设置 MINIYUXI_DATA_DIR，让 config.DATA_DIR 落在稳定位置。
    """
    if not getattr(sys, "frozen", False):
        return
    if os.getenv("MINIYUXI_DATA_DIR"):
        return
    if sys.platform == "win32":
        root = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(root, "MiniYuxi", "data")
    elif sys.platform == "darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "MiniYuxi", "data")
    else:
        path = os.path.join(os.path.expanduser("~"), ".local", "share", "miniyuxi")
    os.makedirs(path, exist_ok=True)
    os.environ["MINIYUXI_DATA_DIR"] = path


def _load_dotenv() -> None:
    """零依赖加载项目根目录 .env（若存在）。必须在 import core 之前调用，使 config 读到键值。
    仅解析简单的 KEY=VALUE 行，跳过注释(#)与空行；已存在的环境变量不覆盖。"""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


def _ensure_secret() -> None:
    """默认密钥不再裸奔：若 MINIYUXI_SECRET 仍为默认值，自动生成 32 字节随机串写入
    data/.secret 后再启动；若 data/.secret 已存在（≥32 字符）则复用，保证重启幂等。
    若无法写入（如被占位成目录）则明确报错并以非零码退出，绝不静默用默认密钥启动。
    必须在 import core 之前调用，使 config 读到正确密钥。"""
    env_secret = os.getenv("MINIYUXI_SECRET", DEFAULT_SECRET)
    if env_secret != DEFAULT_SECRET:
        return  # 运维已显式指定密钥，尊重之
    # 冻结（打包）模式下数据目录由 MINIYUXI_DATA_DIR 指定，密钥必须同目录保存
    secret_path = os.path.join(os.getenv("MINIYUXI_DATA_DIR") or os.path.join(BASE_DIR, "data"), ".secret")
    # 复用已存在的密钥（重启幂等）
    if os.path.isfile(secret_path) and os.path.getsize(secret_path) >= 32:
        try:
            existing = open(secret_path, encoding="utf-8").read().strip()
            if existing:
                os.environ["MINIYUXI_SECRET"] = existing
                print("=" * 62)
                print("  ⚠ 复用 data/.secret 中已存在的密钥（非默认裸奔值）")
                print("=" * 62)
                return
        except OSError:
            pass
    # 生成新密钥（64 字符十六进制，≥32）
    try:
        new_secret = secrets.token_hex(32)
        os.makedirs(os.path.dirname(secret_path), exist_ok=True)
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(new_secret)
        os.environ["MINIYUXI_SECRET"] = new_secret
        print("=" * 62)
        print("  ⚠ 安全警告：检测到使用默认密钥，已自动生成随机密钥")
        print(f"    并写入 {os.path.relpath(secret_path, BASE_DIR)}（请妥善保管）")
        print("    生产环境建议使用 MINIYUXI_SECRET 环境变量显式指定。")
        print("=" * 62)
    except OSError as exc:
        print("=" * 62)
        print("  ✗ 启动失败：无法写入默认密钥到 data/.secret")
        print(f"    错误：{exc}")
        print("    请检查 data/ 目录权限，或通过 MINIYUXI_SECRET 环境变量指定密钥后重试。")
        print("=" * 62)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 调度驱动 + LAN 安全 + 启动钩子（让劳动关系每日预警/备份真正自动跑）
# ---------------------------------------------------------------------------
def _enforce_lan_guard(args) -> None:
    """非回环 host（0.0.0.0 / 局域网 IP）视为暴露到网络，强制安全自检：
    - admin 若仍为默认口令 admin123，自动重置为随机强口令并打印（强制改密）；
    - 默认密钥已由 _ensure_secret 处理，此处只管口令。
    """
    loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if loopback:
        return
    print("=" * 62)
    print("  🔴 检测到非回环监听（LAN/公网暴露）：已启用强制安全检查")
    try:
        from core import auth
        conn = db.connect()
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE tenant_id='default' AND username='admin'"
        ).fetchone()
        if row and auth.verify_password("admin123", row["password_hash"], row["salt"]):
            new_pw = secrets.token_urlsafe(12)
            h, s = auth.hash_password(new_pw)
            conn.execute(
                "UPDATE users SET password_hash=?, salt=? WHERE tenant_id='default' AND username='admin'",
                (h, s))
            conn.commit()
            print(f"  ⚠ admin 仍使用默认口令 admin123，已自动重置为随机强口令：{new_pw}")
            print("    请妥善保存；上线前建议改用专属账号并再次改密。")
        else:
            print("  ✓ admin 口令已非默认值")
    except Exception as exc:
        print(f"  ✗ LAN 自检异常：{exc}（服务仍启动，请人工确认口令安全）")
    print("=" * 62)


def _register_default_jobs() -> None:
    """注册每日定时任务（幂等：已存在则跳过）。"""
    from core import db, scheduler
    specs = {
        "labor_sync_daily": ({"kind": "daily", "at": "08:00"}, {"action": "labor_sync"}),
        "backup_daily": ({"kind": "daily", "at": "03:00"}, {"action": "daily_backup"}),
    }
    # 注意：db.connect() 返回线程本地共享连接，此处绝不可 close，
    # 否则该线程后续所有 DB 操作都会 "Cannot operate on a closed database"。
    conn = db.connect()
    for name, (spec, payload) in specs.items():
        try:
            exists = conn.execute(
                "SELECT id FROM schedules WHERE name=?", (name,)).fetchone()
            if not exists:
                scheduler.register(name, spec, payload,
                                   tenant_id="default", conn=conn)
        except Exception:
            pass


def _run_job(payload: dict) -> None:
    """通用定时任务分发（对应 Hermes 十·Cron=Agent 任务）。

    支持三类 payload：
      - {"action": "labor_sync" | "daily_backup"}   旧式硬编码业务动作（向后兼容）
      - {"kind": "agent", "prompt": "...",          真·Agent 任务：用 rag.answer 跑一个
         "skills"?: [...], "model"?: "...",         fresh session（不继承聊天历史），
         "deliver"?: "wecom"/"log"}                 结果按 deliver 投递
      - {"kind": "script", "path": "scripts/xxx.py"} 受控脚本任务：路径须落在允许根目录内，
                                                经安全校验后执行（绝不直接执行任意命令）
    未知 kind → 记审计后 fail-closed（不静默跳过，也不盲执行）。
    """
    p = payload or {}

    # 旧式 action（兼容已注册任务）
    action = p.get("action")
    if action == "labor_sync":
        from core import labor_relations
        labor_relations.sync_all()
        return
    if action == "daily_backup":
        from core import backup
        backup.daily_backup()
        return

    kind = p.get("kind")
    if kind == "agent":
        prompt = (p.get("prompt") or "").strip()
        if not prompt:
            print(f"  ✗ Cron agent 任务缺少 prompt，跳过：{p}")
            return
        from core import rag
        # fresh session：history=None → 不继承任何聊天历史，prompt 必须自包含
        try:
            res = rag.answer("default", prompt, history=None)
            answer = (res or {}).get("answer") or ""
            print(f"  ✓ Cron agent 任务完成（{len(answer)} 字）")
            if p.get("deliver") == "log":
                import datetime as _dt
                log_path = os.path.join(BASE_DIR, "data", "cron_agent_runs.log")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{_dt.datetime.now()}] {prompt[:60]}\n{answer}\n\n")
        except Exception as exc:
            print(f"  ✗ Cron agent 任务异常：{exc}")
        return

    if kind == "script":
        script_path = p.get("path") or ""
        try:
            from core import security
            allowed_root = os.path.join(BASE_DIR, "scripts")
            if not security.validate_within_dir(script_path, allowed_root):
                print(f"  ✗ Cron script 路径越权被拦截：{script_path}")
                return
            ok, reason = security.validate_script(open(script_path, encoding="utf-8").read())
            if not ok:
                print(f"  ✗ Cron script 安全校验未过：{reason}")
                return
            import subprocess
            subprocess.run([sys.executable, script_path], cwd=BASE_DIR, timeout=300,
                           capture_output=True, text=True)
            print(f"  ✓ Cron script 任务完成：{script_path}")
        except Exception as exc:
            print(f"  ✗ Cron script 任务异常：{exc}")
        return

    # 未知 kind → fail-closed（记日志，不盲执行）
    print(f"  ✗ Cron 任务 payload 未知，已 fail-closed：{p}")


def _schedule_pump() -> None:
    """后台线程：每 60s 拉取到期任务并分发执行（补全 scheduler 的执行侧）。"""
    import time as _t
    from datetime import datetime as _dt
    from core import scheduler
    while True:
        try:
            jobs = scheduler.due_jobs(now=_dt.now())
            for j in jobs:
                try:
                    _run_job(j.get("payload"))
                except Exception:
                    pass
                try:
                    scheduler.mark_run(j["id"])
                except Exception:
                    pass
        except Exception:
            pass
        _t.sleep(60)


# ---------------------------------------------------------------------------
# 桌面端 sidecar 常驻模式（P3：Tauri 外壳 + 现有内核作 sidecar）
# ---------------------------------------------------------------------------
# 传输契约（外壳侧按前缀解析 stdout，另有一份 data/sidecar.json 兜底，防止 stdout 被缓冲吞掉）：
#   MINIYUXI_SIDECAR_READY {"ok":true,"host":"127.0.0.1","port":8801,"url":"http://127.0.0.1:8801",
#                           "token":"<jwt>","tenant":"default","user":"admin","role":"admin",
#                           "pid":1234,"version":"0.2.0"}
SIDECAR_READY_PREFIX = "MINIYUXI_SIDECAR_READY "
SIDECAR_VERSION = "0.2.0"  # 与 pyproject.toml 保持一致
# 桌面本地会话 token 默认 7 天（可用 MINIYUXI_SIDECAR_TOKEN_TTL_H 覆盖，单位小时）。
# 该 token 只对「回环监听的 sidecar 本进程」有效，不用于任何网络暴露场景。
SIDECAR_TOKEN_TTL = int(os.getenv("MINIYUXI_SIDECAR_TOKEN_TTL_H", str(24 * 7))) * 3600


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _pick_port(host: str, preferred: int) -> int:
    """端口被占则自动顺延（桌面端与已有 Web 服务并存 / 多开时的关键兜底）。"""
    if preferred and _port_free(host, preferred):
        return preferred
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _emit_ready(host: str, port: int, token: str, tenant: str, user: str,
                role: str, stop: "threading.Event") -> None:
    """就绪探针：/api/health 返回 200 后，在 stdout 打一行机器可读 READY。"""
    import json
    import time
    import urllib.request

    url = f"http://{host}:{port}/api/health"
    deadline = time.time() + 90
    ok = False
    while not stop.is_set() and time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(0.3)
    if stop.is_set():
        return
    payload = {
        "ok": ok, "host": host, "port": port, "url": f"http://{host}:{port}",
        "token": token, "tenant": tenant, "user": user, "role": role,
        "pid": os.getpid(), "version": SIDECAR_VERSION,
    }
    sys.stdout.write(SIDECAR_READY_PREFIX + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def sidecar_main(args) -> int:
    """以 sidecar 形式常驻：强制回环、不开浏览器、自动选端口、READY 契约、优雅退出。

    与 Web 端跑的是同一个 api.py + core/ 内核，桌面外壳只是另一个入口。
    """
    import atexit
    import json

    host = "127.0.0.1"                      # 桌面 sidecar 只监听回环，绝不暴露到网络
    port = _pick_port(host, args.port)
    tenant = os.getenv("MINIYUXI_SIDECAR_TENANT", "default")
    user = os.getenv("MINIYUXI_SIDECAR_USER", "admin")
    role = "admin"

    _frozen_bootstrap()   # 冻结（打包）模式下把数据目录固定到用户目录，必须在 import core 之前

    from core import auth, config, db

    db.init_db()
    try:
        from core import backup, labor_relations
        labor_relations.init()
        backup.daily_backup()
        labor_relations.sync_all()
    except Exception as exc:
        print(f"  （sidecar 启动钩子异常，已忽略：{exc}）", file=sys.stderr)
    _register_default_jobs()
    threading.Thread(target=_schedule_pump, daemon=True).start()

    token = auth.make_token({"tid": tenant, "sub": user, "role": role}, ttl=SIDECAR_TOKEN_TTL)
    info = {
        "host": host, "port": port, "url": f"http://{host}:{port}", "token": token,
        "tenant": tenant, "user": user, "role": role, "pid": os.getpid(),
        "version": SIDECAR_VERSION, "db": str(config.DB_PATH),
    }
    sidecar_path = os.path.join(str(config.DATA_DIR), "sidecar.json")

    def _cleanup() -> None:
        try:
            os.remove(sidecar_path)
        except OSError:
            pass

    os.makedirs(os.path.dirname(sidecar_path), exist_ok=True)
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"  ✗ sidecar 无法写入 {sidecar_path}：{exc}", file=sys.stderr)
        return 1
    atexit.register(_cleanup)

    print(f"  sidecar 监听 http://{host}:{port}（仅回环）· pid {os.getpid()}", file=sys.stderr)
    print(f"  数据库 {config.DB_PATH}", file=sys.stderr)

    stop = threading.Event()
    threading.Thread(target=_emit_ready,
                     args=(host, port, token, tenant, user, role, stop),
                     daemon=True).start()

    import uvicorn

    import api
    from api import app

    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(cfg)
    # 桌面外壳退出前 POST /api/desktop/shutdown → 优雅停机（不留孤儿进程）
    api.register_shutdown_hook(lambda: setattr(server, "should_exit", True))

    # stdin 看门狗（可选）：外壳进程被硬杀时管道关闭 → sidecar 自行退出，避免变孤儿。
    # 默认关闭，因为 Tauri 可能给 sidecar 分配 null stdin（会立刻读到 EOF 而误退出）。
    if os.getenv("MINIYUXI_SIDECAR_WATCH_STDIN") == "1":
        def _stdin_watchdog() -> None:
            try:
                while True:
                    if not sys.stdin.readline():   # EOF / 管道关闭
                        break
            except Exception:
                pass
            stop.set()
            server.should_exit = True

        threading.Thread(target=_stdin_watchdog, daemon=True).start()

    try:
        server.run()          # 阻塞；SIGINT/SIGTERM 由 uvicorn 转为优雅退出
    finally:
        stop.set()
        _cleanup()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.getenv("MINIYUXI_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("MINIYUXI_PORT", "8801")))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--sidecar", action="store_true",
                    help="桌面端 sidecar 常驻模式：强制回环、不开浏览器、自动选端口、"
                         "就绪后在 stdout 打印 MINIYUXI_SIDECAR_READY 契约行")
    args = ap.parse_args()

    _frozen_bootstrap()
    _load_dotenv()    # 必须在 import core / _ensure_secret 之前，加载 .env 中的密钥
    _ensure_secret()  # 必须在 import core 之前，使 config.SECRET_KEY 取到正确值

    if args.sidecar:
        sys.exit(sidecar_main(args))

    from core import config, db

    db.init_db()
    _enforce_lan_guard(args)  # 非回环 host 强制 admin 改密（失败安全）
    _register_default_jobs()  # 幂等注册每日预警/备份任务
    # 启动即跑一次：备份 + 合同预警
    try:
        from core import backup, labor_relations
        labor_relations.init()
        backup.daily_backup()
        labor_relations.sync_all()
    except Exception as exc:
        print(f"  （启动钩子异常，已忽略：{exc}）")
    # 后台驱动定时任务（让每日预警/备份真正自动执行）
    threading.Thread(target=_schedule_pump, daemon=True).start()
    print("=" * 62)
    print("  MiniYuxi · 轻量 HR 智能体平台（原生进程 · 零外部服务）")
    print("=" * 62)
    print(f"  数据库   : {config.DB_PATH} (SQLite)")
    print(f"  向量检索 : sqlite-vec {db.vec_version()} · 维度 {config.EMB_DIM}")
    print(f"  全文检索 : SQLite FTS5 + 中文 bigram")
    print(f"  模型模式 : {'在线(' + config.LLM_MODEL + ')' if config.llm_enabled() else '离线兜底（未配置 LLM_API_KEY）'}")
    print(f"  检索模式 : {'向量 + BM25 混合' if config.emb_enabled() else '仅 BM25（未配置 EMB_API_KEY）'}")
    print(f"  访问地址 : http://{args.host}:{args.port}")
    print(f"  默认账号 : default / admin / admin123")
    print("=" * 62)
    print("  Ctrl+C 停止\n")

    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    import uvicorn

    uvicorn.run("api:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
