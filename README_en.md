# MiniYuxi · Enterprise AI Assistant (Unified Web / Desktop / CLI · Local-first · Zero Docker)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Self-test](https://img.shields.io/badge/selftest-20%2F20-brightgreen)](tests/selftest.py)

> **Run an Agent inside your enterprise workflow** — Web / Desktop / CLI share one kernel. Single-file SQLite, no external services, fully auditable.

## ✨ Features

- 🌐 **Unified kernel for 3 ends**: Web (SPA) / Desktop (Tauri sidecar) / CLI (thin client) all reuse `core/`.
- 🏢 **Multi-tenant + RBAC**: admin / editor / viewer, tenant data isolation.
- 🤖 **Agent orchestration**: ReAct loop + tool governance (toolset filter + approval gate) + multi-provider failover.
- 📚 **Knowledge-base RAG**: BM25 + vector RRF fusion, Chinese bigram tokenizer, sqlite-vec (no service).
- 🛡️ **Security & audit**: hardline command block → approval → path check → append-only hash chain.
- ⏰ **Scheduler**: Cron = Agent task (fresh session; unknown type = fail-closed).
- 💾 **Local-first**: single Python process, single SQLite file, ~65–70MB RAM.

## 🚀 Quick start (Web)

```bash
git clone https://github.com/C34W-Tsz-dzhang2-0f5/MiniYuxi.git MiniYuxi && cd MiniYuxi
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py                 # http://127.0.0.1:8801
python tests/selftest.py      # expect 20/20
```

Default account: `default / admin / admin123` (**change the password on first deploy**).

## 🏗️ Architecture

One kernel, three shells. Full layered design, core-module mapping (vs learn-workbuddy's 24 lessons), and open-source growth strategy:
👉 [`docs/三端统一架构与开源增长方案.md`](docs/三端统一架构与开源增长方案.md) (Chinese; English version coming).

## ✅ Quality

- `tests/selftest.py`: **20/20**
- `tests/test_hermes_landing.py`: 13 passed
- `tests/test_perf_optimizations.py`: 5 passed
- `.github/workflows/verify.yml` gates every PR.

## 🤝 Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Run the test suite before submitting a PR.

## 📄 License

[MIT](LICENSE) © 2026 MiniYuxi Contributors.

---

⭐ **If this helps you, please star the repo to support the three-end roadmap!**
