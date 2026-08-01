# Bazi Agent V2

八字 Agent V2 的任务编排层，与现有 `app/chat` V1 主链路隔离。

规划模块：

- `schemas.py`：Agent 请求、状态、运行结果与错误结构。
- `orchestrator.py`：单次 Agent Run 的流程编排。
- `state_machine.py`：有限状态机与步骤限制。
- `context.py`：人物、命盘、任务与长期记忆上下文。
- `policies.py`：功能开关、限流、风险和降级策略。
- `evidence.py`：结论、证据、反证和置信度。
- `repository.py`：Agent Run 持久化接口。
- `tools/`：命盘、流运、知识检索和验证工具。

V2 应使用独立路由 `/api/agent/v2/*`，默认关闭，并只对白名单用户开放。V2 故障不得影响 `/api/chat/*`、现有排盘、支付、额度或会话持久化。
