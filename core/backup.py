"""安全补课 · 每日自动备份：对 MiniYuxi 主库做 WAL checkpoint 后按日期拷贝并滚动保留。

移植自 hr-ai-workbench/app/main.py 的 do_backup_if_needed（P0-5 每日备份）。
设计：
- 备份到 data/backups/，文件名 miniyuxi.db.YYYYMMDD；
- 拷贝前先 wal_checkpoint(TRUNCATE)，确保 WAL 数据落盘，避免备份缺数据；
- 滚动保留最近 KEEP 份（默认 7）；
- 全部异常静默吞掉，绝不阻塞主服务启动。
"""
import shutil
from datetime import date
from pathlib import Path

from . import config, db

BACKUP_KEEP = int(__import__("os").getenv("MINIYUXI_BACKUP_KEEP", "7"))


def daily_backup(conn=None, keep: int = BACKUP_KEEP) -> dict:
    """执行一次备份（若今日已备份则跳过）。返回 {backed_up, path, kept}。"""
    src = Path(config.DB_PATH)
    if not src.exists():
        return {"backed_up": False, "reason": "no_source"}
    backups_dir = Path(config.DATA_DIR) / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    tag = date.today().strftime("%Y%m%d")
    dest = backups_dir / f"miniyuxi.db.{tag}"
    if dest.exists():
        return {"backed_up": False, "reason": "already_today", "path": str(dest)}

    # checkpoint，确保 WAL 数据落盘
    try:
        c = conn or db.connect()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.commit()
    except Exception:
        pass

    try:
        shutil.copy2(src, dest)
    except Exception as exc:
        return {"backed_up": False, "reason": str(exc)}

    files = sorted(backups_dir.glob("miniyuxi.db.*"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for f in files[keep:]:
        try:
            f.unlink()
            removed.append(f.name)
        except OSError:
            pass
    return {"backed_up": True, "path": str(dest), "kept": len(files[:keep]), "removed": removed}


def list_backups() -> list:
    backups_dir = Path(config.DATA_DIR) / "backups"
    if not backups_dir.exists():
        return []
    return sorted((p.name for p in backups_dir.glob("miniyuxi.db.*")),
                  reverse=True)
