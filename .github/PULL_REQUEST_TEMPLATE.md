## 这个 PR 做什么

<!-- 一句话说明目的 -->

## 关联 Issue

<!-- 例如 Closes #12 / Relates to #3 -->

## 改动类型

- [ ] feat（新功能）
- [ ] fix（缺陷修复）
- [ ] docs（文档）
- [ ] perf（性能）
- [ ] refactor（重构）

## 测试

- [ ] `python tests/selftest.py`（20/20）
- [ ] `python -m pytest tests/test_hermes_landing.py`（13 passed）
- [ ] `python -m pytest tests/test_perf_optimizations.py`（5 passed）
- [ ] 新增能力已补测试

## 三端影响

- [ ] 仅内核/core（三端自动受益）
- [ ] 涉及 Web 端
- [ ] 涉及 Desktop / CLI 端（路线图）

## 自检清单

- [ ] 无密钥/内部数据提交（`.env`、`data/` 已忽略）
- [ ] 调用外部命令处已过 `core/security.py` 校验
- [ ] 法条/口径引用已做效力核验
