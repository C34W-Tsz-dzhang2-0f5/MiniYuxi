import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import rag

docs = rag.list_documents("default")
print("KB 文档总数:", len(docs))
for d in docs:
    print("  -", d["title"], "(chunks=%s)" % d["n_chunks"])

print("\n按唯一短语检索本文新增内容：")
for q in ["Chyris Tech Note 33.6k Star", "代码是能创造新工具的工具 自生成工具工厂", "微信文章：33.6k"]:
    hits = rag.search("default", q, 3)
    titles = {h["title"] for h in hits}
    mine = [h for h in hits if "33.6k" in h["title"] or "知识卡" in h["title"]]
    print(f"  「{q}」命中 {len(hits)} 条，命中本文档: {bool(mine)} | 标题集={titles}")
