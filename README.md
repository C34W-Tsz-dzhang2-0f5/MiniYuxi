# MiniYuxi · 轻量 HR 智能体平台（自研原型）

对标 Yuxi（语析）四项核心能力——**多租户 / Agent 编排 / 权限体系 / 知识库**，
但**完全不依赖 Docker、不依赖硬件虚拟化**，以单个 Python 原生进程运行。
在本机（AOC A24837 / Celeron N5095 / 7.8GB / VT-x 关闭）**实测可跑：内存 65–70MB**。

---

## 一、快速开始

```powershell
# 方式一（Windows）：复制示例启动脚本并填入你的 Key
copy start_miniyuxi.example.bat start_miniyuxi.bat   # 编辑该文件填入 LLM_API_KEY / DOUBAO_API_KEY
start_miniyuxi.bat

# 方式二：命令行（密钥通过环境变量或根目录 .env 提供；.env 已被 .gitignore 忽略）
python run.py --port 8801
```

> Python 依赖：建议先 `python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`（详见第七节）。

启动后浏览器访问 **http://127.0.0.1:8801** ，默认账号：

| 租户 | 用户 | 密码 | 角色 |
|---|---|---|---|
| default | admin | admin123 | admin |

自检（推荐先跑一次，验证全部能力）：

```powershell
python selftest.py     # 期望输出：20/20 全部通过
```

---

## 二、架构（全部为进程内组件，零外部服务）

| 能力 | 实现 | 说明 |
|---|---|---|
| 数据库 | **SQLite** | 单文件 `data/miniyuxi.db`，备份即拷文件 |
| 向量检索 | **sqlite-vec** | SQLite 扩展，纯 C，无需 Milvus/服务进程 |
| 全文检索 | **SQLite FTS5 + bm25()** | 中文按 bigram 分词，零额外依赖 |
| 检索融合 | **RRF**（k=60） | BM25 与向量结果融合排序 |
| 认证 | **自签 JWT**（HMAC-SHA256） | 不依赖 PyJWT；口令 PBKDF2 加盐 |
| 授权 | **RBAC 角色矩阵** | admin / editor / viewer，见 `core/config.py` |
| Agent 编排 | **进程内状态机** | 节点 + 条件边 + HITL 闸门；语义与 LangGraph 同构，可平滑替换 |
| Web | **FastAPI + 单页原生 JS** | 无前端构建步骤 |

```
api.py              REST 接口（多租户/权限/知识库/Agent/审计）
core/config.py      配置与角色权限矩阵
core/db.py          SQLite + sqlite-vec + FTS5 建表与连接
core/auth.py        口令哈希、JWT 签发校验、RBAC
core/rag.py         分词 / 分块 / 解析 / Embedding / 检索 / 问答
core/agent.py       流程定义（招聘 19 阶段）与运行状态机
web/index.html      单页控制台
run.py              启动器    selftest.py  端到端自检
```

---

## 三、离线优先设计（无 API Key 也能完整验收）

| 缺失配置 | 降级行为 |
|---|---|
| 未设 `EMB_API_KEY` | 跳过向量通道，仅用 BM25 全文检索，功能不中断 |
| 未设 `LLM_API_KEY` | 走"离线兜底"：直接返回命中的原文片段并标注 `mode=offline` |

接入真实模型（可选）：

```powershell
$env:LLM_BASE_URL = "https://api.siliconflow.cn/v1"
$env:LLM_API_KEY  = "sk-xxx"
$env:LLM_MODEL    = "Qwen/Qwen2.5-7B-Instruct"
$env:EMB_API_KEY  = "sk-xxx"      # 不设则仅用 BM25
$env:EMB_MODEL    = "BAAI/bge-m3"
$env:EMB_DIM      = "1024"        # ⚠️ 一经建库不可更改，更换需删库重建
python run.py
```

---

## 四、主要接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/health` | 公开 | 健康检查与运行模式 |
| POST | `/api/auth/login` | 公开 | 登录获取 JWT |
| GET | `/api/me` | 登录 | 当前身份与权限 |
| GET/POST | `/api/tenants` | tenant.manage | 租户列表 / 创建 |
| POST | `/api/users` | user.manage | 创建用户（含角色） |
| GET/POST/DELETE | `/api/kb/docs` | kb.read / kb.write / kb.delete | 知识库文档 |
| POST | `/api/kb/search` | kb.read | 混合检索 |
| POST | `/api/chat` | chat | 问答（带引用溯源） |
| GET/POST | `/api/agent/*` | agent.run | 流程列表 / 启动 / 单步 / 自动跑通 |
| GET | `/api/audit` | audit.read | 审计日志 |

---

## 五、已验证能力（自检 20/20）

核心层：sqlite-vec 可用、中文分词、检索命中、**多租户数据隔离**、问答闭环、RBAC 矩阵、JWT 签发校验与防篡改、**Agent S1→S19 跑通**、**HITL 闸门可中断**。
接口层：健康检查、登录、匿名 401、**越权 403**、文档入库、RAG 引用、创建租户、Agent 19 步、审计留痕。

## 六、已知限制（上线前须处理）

1. **默认密钥与口令必须改**：`MINIYUXI_SECRET` 为开发默认值，admin 口令为 admin123。
2. **知识图谱尚未实现**：当前为"向量 + 全文"双索引；图谱实体抽取列为后置（P3）。
3. **单机部署**：无高可用，需定期备份 `data/miniyuxi.db`。
4. **未做速率限制与配额**：多租户场景下需补充。
5. 仅绑定 `127.0.0.1`，如需内网访问应加反向代理与 HTTPS。

---

## 七、开源发布与部署

本项目以 **MIT 协议**开源，仓库中**不含任何密钥**：真实 Key 通过环境变量或根目录 `.env` 提供（见 `.env.example`），含明文 Key 的 `start_miniyuxi.bat` / `run.bat` 与 `data/` 均已被 `.gitignore` 忽略。

### 7.1 本地运行（开发者）

```bash
git clone <your-repo-url> MiniYuxi && cd MiniYuxi
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # 编辑 .env 填入 LLM_API_KEY / EMB_API_KEY / DOUBAO_API_KEY
# 或直接 export 环境变量；Windows 也可复制 start_miniyuxi.example.bat 为 start_miniyuxi.bat 后填 Key

python run.py               # 默认 http://127.0.0.1:8801
python selftest.py          # 期望 20/20
```

默认账号：`default / admin / admin123`（**首次部署务必改密**）。

### 7.2 生产 / 团队部署须知

| 项目 | 建议 |
|---|---|
| 密钥 | 切勿写入代码或提交仓库；用环境变量 / `.env`（已忽略）/ 密钥管理服务 |
| 通信 | 仅绑定 `127.0.0.1`；对外或内网访问务必套 **nginx 反代 + HTTPS**（自签或 CA） |
| 会话密钥 | 生产环境显式设置强随机 `MINIYUXI_SECRET`（run.py 也会自动生成写入 `data/.secret`） |
| 口令 | 改掉默认 `admin/admin123`，按需用 `POST /api/users` 建账号 |
| 并发 | SQLite 单写者，**小团队可用**；公网/高并发请换 Postgres 等 |
| 备份 | 定期备份 `data/miniyuxi.db`（含知识库向量、审计链、账号） |
| 容器 | 已附 `Dockerfile` + `docker-compose.yml`：`docker compose up -d --build`（密钥用 `-e` 注入，勿写进镜像） |

### 7.3 发布清单（安全红线）

- [ ] `.gitignore` 已忽略 `data/`、`*.db`、`.secret`、`.env`、`start_miniyuxi.bat`、`run.bat`
- [ ] 提交前对暂存区执行密钥复扫（`grep -rE "sk-|DUeu" ` 应为空）
- [ ] 不含任何真实 API Key、内部知识库原文、用户数据
- [ ] 含 `LICENSE`、`README.md`、`.env.example`、`start_miniyuxi.example.bat`

---

> 选型与可行性论证见：`../13_平台选型与二开研判/V2_自研vs二开_完整可行性研判.md`
