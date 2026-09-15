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
    secret_path = os.path.join(BASE_DIR, "data", ".secret")
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.getenv("MINIYUXI_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("MINIYUXI_PORT", "8801")))
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    _load_dotenv()    # 必须在 import core / _ensure_secret 之前，加载 .env 中的密钥
    _ensure_secret()  # 必须在 import core 之前，使 config.SECRET_KEY 取到正确值

    from core import config, db

    db.init_db()
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
