# 迭代 003：批次执行预算

**状态：本地验证完成，待 PR/远程 CI 复核。** 本记录遵循
[AHE 维护闭环](../../AGENTS.md)：它把一项可证伪、可回退的产品改进落实到
ActionAnything，不引入新的产品 Harness、模型调用、凭据或外部权限。

## 观察

动作入口已经限制了单个 `wait` 至 60 秒，但 `ActionRuntime.execute_many()` 会持续
消费任意 iterable；CLI 也会把整个规范化 JSON 计划直接交给它。因而一份结构合法的
计划仍可包含任意多项动作或累计等待时间。威胁模型已把长期/重复计划列为资源和重复
副作用风险，且此前只能由每个调用方另行实现限制。

## 可证伪假设

若把动作总数和累计允许等待时间作为调用方拥有的、每批次的 `ExecutionBudget`，并在
动作到达执行器前拒绝超限项，则结构合法但超长的计划无法继续触发额外执行器调用；
预算拒绝会像其他拒绝一样进入 trace；未配置预算的既有调用保持行为不变。

该假设会被以下现象否定：`stop_on_error=False` 可继续消费超限 iterable、超限动作
到达执行器、或预算拒绝未留下 trace 证据。

## 最小变更

- 新增公开、不可变的 `ExecutionBudget(max_actions, max_total_wait_milliseconds)`；只接受
  非负整数或 `None`，而且不成为 action-plan 字段。
- `max_actions` 在每个 batch 项进入策略前计数，预算拒绝立即停止 batch，因此即使
  调用方设定 `stop_on_error=False` 也不能用无限 iterable 绕过总数上限。
- 仅在 policy 与确认都允许后，`wait` 才预留累计毫秒数；已交给执行器的 wait 即使
  执行失败也会保留预留，避免失败重试扩大资源使用。
- CLI 的 `run` 与 `replay` 新增 `--max-actions` 和 `--max-total-wait-ms`（完整别名
  `--max-total-wait-milliseconds`）。参数先于 recorder 创建被校验；计划顶层只允许
  `actions` 等应用自定义字段，但明确拒绝 `budget`，不能让不可信 JSON 自行声明预算。
- replay 会拒绝包含 denied、cancelled 或 `ExecutionBudget` 拦截事件的 trace，避免先前
  未获执行许可的动作在后续 replay 时重新取得执行机会。
- 为留下逐 action 的拒绝证据，`max_actions` 到达后最多额外读取一个候选动作并记录拒绝；
  它不会进入策略、确认或执行。对有副作用的 generator，调用方仍须在上游限制或物化。
- 无预算 batch 保留既有子类 `execute()` / `_execute()` 覆写；带预算 batch 若发现这些
  legacy 覆写则在消费 iterable 前失败关闭，不能绕开嵌入方可能附加的确认或审计。此时
  应改用 policy/executor 组合，或保留无预算的 legacy 流程。

范围外：跨多次 `execute_many()` 的会话额度、分布式配额、速率/带宽/CPU/内存限制、
浏览器耗时、事务回滚、幂等与业务副作用分类仍由应用和部署环境负责。CLI 会先完整解析
JSON 计划，所以本预算也不是输入大小或内存上限。

## 实际验证

使用项目支持范围内的 Python 3.12，在干净的本地环境中实际运行：

- `PYTHONPATH=src python -m unittest tests.test_runtime tests.test_cli -v`：32 项通过。
- `PYTHONPATH=src python -m unittest discover -s tests -v`：82 项通过。
- `python -m compileall -q src` 与 `git diff --check`：通过。

覆盖内容包括：零值/负值预算、action 与 wait 的精确边界、超限项不进入 policy 或
executor、拒绝/取消仍消耗 action admission、失败的 wait 保留预留、同一预算对象在两次
batch 间重置、CLI 两种 wait 参数名、计划内 budget 拒绝、trace replay fail-closed，以及
`execute()` / `_execute()` legacy 覆写不能绕过带预算路径。尚未把远程 CI 写成已通过；
它将在 PR 创建后作为下一条独立证据记录。

## 残余风险与下一轮问题

预算仅约束本地 runtime 的 batch 入口，不能证明一个 click 的业务成本，也不能阻止
调用方创建多个 runtime 或多个进程。下一轮可以在不把模型输出提升为权限配置的前提下，
研究 session-level budget、外部监控或新增严格的 provider adapter。
