# -*- coding: utf-8 -*-
"""为 MiniYuxi 正式库补齐向量索引（sqlite-vec）。

适用场景：
- 导入知识库时若遇 SiliconFlow 限流（429），rag.add_document 会自动跳过向量、只写
  chunks + FTS 全文索引，导致 vec_chunks 为空、语义/混合检索不可用。
- 本脚本在限流解除后运行，把现有所有 chunk 重新调 bge-m3 生成向量写入 vec_chunks，
  使 BM25 + 向量混合检索与生成式问答可用。

用法：
    set LLM_API_KEY=你的Key        （EMB_API_KEY 会 fallback 到它）
    python rebuild_vectors.py

特性：
- 批量 32 条 embedding，遇 429 指数退避重试（最长 ~60s/次，最多 8 次）
- 幂等：每个 chunk 先 DELETE 旧向量再 INSERT，可反复重跑补齐未完成部分
- 仅依赖 core.config（读 DB_PATH / EMB_*），不改动任何冻结文件
"""
import os
import sys
import time
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core.config as config  # noqa: E402
import sqlite3  # noqa: E402

try:
    import sqlite_vec  # noqa: E402
except ImportError:
    print("未安装 sqlite_vec，无法写入向量表")
    sys.exit(1)


def ser_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def embed_with_retry(texts, max_retry: int = 8):
    import requests

    url = config.EMB_BASE_URL.rstrip("/") + "/embeddings"
    for attempt in range(max_retry):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {config.EMB_API_KEY}"},
                json={"model": config.EMB_MODEL, "input": texts},
                timeout=config.LLM_TIMEOUT,
            )
            if r.status_code == 429:
                wait = min(60, 5 * (2 ** attempt))
                print(f"  [429 限流] 退避 {wait}s（第 {attempt + 1} 次重试）")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()["data"]
            data.sort(key=lambda x: x["index"])
            return [d["embedding"] for d in data]
        except Exception as e:  # noqa: BLE001
            if attempt == max_retry - 1:
                print(f"  最终失败：{e}")
                return None
            time.sleep(min(20, 2 ** attempt))
    return None


def main():
    conn = sqlite3.connect(config.DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)

    rows = conn.execute("SELECT id, text FROM chunks").fetchall()
    total = len(rows)
    print(f"待补向量 chunks：{total}")

    BATCH = 32
    done = 0
    for i in range(0, total, BATCH):
        batch = rows[i:i + BATCH]
        texts = [r[1] for r in batch]
        vecs = embed_with_retry(texts)
        if vecs is None:
            print(f"  批次 {i // BATCH} 失败，跳过（可重跑补齐）")
            continue
        for (cid, _), vec in zip(batch, vecs):
            if vec and len(vec) == config.EMB_DIM:
                try:
                    conn.execute("DELETE FROM vec_chunks WHERE rowid=?", (cid,))
                    conn.execute(
                        "INSERT INTO vec_chunks(rowid,embedding) VALUES(?,?)",
                        (cid, ser_f32(vec)),
                    )
                except Exception:  # noqa: BLE001
                    pass
        conn.commit()
        done += len(batch)
        print(f"  进度 {done}/{total}")

    n = conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    print(f"完成：vec_chunks = {n} 行（目标 {total}）")
    if n < total:
        print("仍有缺口，可再次运行本脚本补齐（幂等）。")
    conn.close()


if __name__ == "__main__":
    main()
