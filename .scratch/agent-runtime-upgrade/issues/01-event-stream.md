# 01 · 事件流 SSE（agent_loop emit + /api/wb/chat/stream + 前端流式渲染）

Status: `done`（代码+测试+闸门绿；S4 真实浏览器回归待补）
Depends on: —
Owner: —

## 目标
把 `agent_loop.run()` 从「同步黑盒」升级为**可流式观测**：循环每一步 emit 标准事件，经 SSE 推到前端实时渲染「思考 / 工具调用 / 文本增量」。这是「看起来像不能用」的最大体感来源。

## 契约（写进 CONTEXT.md §三，禁止别名）
- 事件三型：`lifecycle`（`{phase:"start"|"end"|"error"}`）/ `tool`（`{event:"call"|"result", tool, args?, result?}`）/ `assistant`（`{delta}`）。
- SSE 端点：`POST /api/wb/chat/stream`（**新增**，不改 `/api/wb/chat` 契约）。
- 响应 `Content-Type: text/event-stream`，每帧 `event: <type>\ndata: <json>\n\n`。

## 实现要点
1. `agent_loop.run()` 增加可选 `emit: Callable[[dict], None]` 参数（默认 None → 行为不变，向后兼容）。
   - 循环开始 emit `lifecycle:start`；每轮 LLM 前/后 emit `assistant:delta`（有内容时）；每个 tool 执行前 emit `tool:call`、后 emit `tool:result`；结束 emit `lifecycle:end`（含 `tool_calls_used`/`trace_id`）；异常 emit `lifecycle:error`。
   - **不改变**返回值结构（仍返回 dict），emit 是旁路观测，失败不得影响主链路。
2. `api.py` 新增 `POST /api/wb/chat/stream`：`StreamingResponse` 包一层 generator，内部调 `wb_workbench.chat(..., emit=队列put)`，用 `queue.Queue` 把同步 loop 的事件桥到 SSE。
3. 前端 `web/wb_workbench.js`：新增流式渲染（`fetch` + `ReadableStream` 读 SSE 帧），`assistant` 增量追加、`tool` 显示「🔧 工具: call/result」、`lifecycle` 显示阶段。**保留**现有同步 `/api/wb/chat` 作降级。
4. 零新依赖（FastAPI `StreamingResponse` 内置）。

## 验收（先写失败测试）
- [x] `tests/_verify_event_stream.py`：三型事件齐 + 顺序正确（start→tool:call→tool:result→assistant→end）+ emit 异常不影响返回。
- [x] SSE 端点返回 `text/event-stream`，逐帧可 `json.loads`。
- [x] `agent_loop.run()` 不传 emit 时行为与返回值**完全不变**（回归断言）。
- [x] 接入 `scripts/verify.py` quick 子集（quick 8/8 绿）。
- [ ] S4：huashu-chrome 真实浏览器验证「发消息→看到流式思考→最终答复」。

## Done
- commit: `21cf358` feat(agent): 事件流 SSE——agent_loop emit + /api/wb/chat/stream + 前端流式渲染
- 备注：`tests/_verify_event_stream.py` 20/20 通过。S4 真实浏览器回归与 02 号票一并做。
