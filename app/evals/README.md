# Bazi Evaluations

八字引擎与 Agent V2 的离线评测和发布门禁。

规划内容：

- `datasets/chart/`：排盘金标案例。
- `datasets/rules/`：十神、藏干及干支关系金标案例。
- `datasets/conversations/`：多轮任务、一致性和人物隔离案例。
- `datasets/safety/`：健康、投资、灾祸和重大决定等安全案例。
- `chart_eval.py`：排盘一致率评测。
- `rule_eval.py`：规则计算正确率评测。
- `conversation_eval.py`：对话与 Agent 轨迹评测。

评测代码不应依赖线上数据库，也不能在生产请求中同步执行。
