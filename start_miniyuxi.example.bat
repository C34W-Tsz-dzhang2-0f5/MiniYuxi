@echo off
REM ============================================================
REM  MiniYuxi 启动示例（请复制本文件为 start_miniyuxi.bat 并填入你自己的 Key）
REM  仅本机访问：http://127.0.0.1:8801
REM  默认账号：default / admin / admin123（上线前务必改密）
REM  [注意] 本示例 Key 为占位符，请勿提交真实 Key 到仓库
REM ============================================================
cd /d %~dp0
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

REM ---- LLM（SiliconFlow / DeepSeek / 其他 OpenAI 兼容网关）----
set LLM_API_KEY=你的LLM_API_KEY
set LLM_BASE_URL=https://api.siliconflow.cn/v1
set LLM_MODEL=Qwen/Qwen2.5-72B-Instruct
set LLM_TEMPERATURE=0.1

REM ---- Embedding（向量检索，不设则仅 BM25）----
set EMB_BASE_URL=https://api.siliconflow.cn/v1
set EMB_MODEL=BAAI/bge-m3
set EMB_DIM=1024

REM ---- 企业级联网搜索后端（可选；火山引擎/豆包，中文更准）----
set DOUBAO_API_KEY=你的DOUBAO_API_KEY
set DOUBAO_BASE_URL=https://open.feedcoopapi.com
set SEARCH_BACKEND=doubao

REM ---- 服务监听 ----
set MINIYUXI_HOST=127.0.0.1
set MINIYUXI_PORT=8801

python run.py
pause
