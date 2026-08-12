# 迭代 002：Trace 写入完整性

**状态：PR #2 已通过远程门禁，待维护者合入。** 本记录遵循
[AHE 维护闭环](../../AGENTS.md)：它是对 ActionAnything 的一次可独立回退的
证据完整性改进，不引入新的产品 Harness、模型调用或外部权限。

## 观察

`TraceRecorder.record()` 过去只调用一次 `os.write()`，却没有检查返回的字节数。
操作系统允许短写：动作可能已经完成，而 JSONL 事件只写入前缀，`record()` 仍会
返回成功；后续 `aa inspect` 或 replay 才因不完整 JSON 暴露问题。这会让调用方
误以为可用的审计证据已经落盘。

## 可证伪假设

若 recorder 在单个事件中持续写入全部剩余字节，并把零进度或非法进度视为失败，
且针对使用同一锁协议的写入者在失败后恢复该事件写入前的文件长度，则正短写不会
留下不可解析事件；无进度时，运行时会保留已执行的结果并标记审计失败，而不是把
截断 trace 当成成功。

反例是：模拟正短写后 JSONL 仍无法解析，或模拟零进度写入后 runtime 没有
`audit_error`。

## 最小变更

- 在 `recorder.py` 新增私有 `_write_all()`：针对正短写继续写入剩余 `memoryview`；
  `InterruptedError` 重试；零/负值、布尔值或超过剩余长度的返回值抛出 `OSError`。若
  某次写入已写入前缀后失败，recorder 会尝试恢复到写入该事件前的文件长度。
- `TraceRecorder.record()` 仅在完整事件写入后返回。
- 增加确定性测试：17 字节短写最终得到一条可读取事件；零进度写入失败；“先写入
  前缀、后零进度”回滚后下一条事件仍可读取；经 `ActionRuntime` 时保留动作的
  dry-run 状态并标记 `trace recording failed`。
- 对 Windows 的原始字节写入显式使用 `O_BINARY`，并在 CI 中以 Python 3.10 运行
  recorder/runtime 定向测试，覆盖 `msvcrt` 锁、短写、回滚和普通 recorder 失败。

范围外：该轮不提供对旧版本或不合作写入者的事务性文件系统保证，也不提供
`fsync` 持久化承诺；它亦不改变默认策略、执行器权限、trace 脱敏或 CLI 合约。

## 实际验证

在 Python 3.12 本地离线环境执行：

```bash
PYTHONPATH=src python3.12 \
  -m unittest tests.test_recorder tests.test_runtime -v
git diff --check
```

结果：**23 项定向测试通过**，格式检查通过。短写测试读取实际生成的 JSONL；
零进度测试断言底层 recorder 抛错且 runtime 返回 `audit_error`；部分写入后失败的
测试确认既有事件不受影响、下一条事件可解析。

随后运行了同一 Python 3.12 环境的全量离线测试：**73 项通过**。PR #2 的 GitHub
Actions 门禁也全部通过：Linux Python 3.10–3.13 矩阵、分发构建、CodeQL 与依赖审查，
以及新增的 Windows Python 3.10 recorder/runtime 定向任务。该 Windows 任务实跑
23 项测试，其中 2 项因 POSIX 锁或符号链接/权限语义而按预期跳过；其余用例覆盖
Windows 的单写入、短写、回滚和普通 recorder 失败路径。真实并发文件系统压力测试
尚未运行。

## 评审驱动修正

- 自动代码审查指出无锁 `ftruncate` 可能删除另一个协作写入者在 EOF 快照后追加的
  事件。修订实现用目标 trace 文件上的跨平台建议锁把 EOF 快照、写入和可能的回滚
  串行化；它只覆盖使用相同锁协议的本地写入者。
- 回滚失败不再替换原始写入或中断异常；附加诊断仅作为异常备注（Python 3.11+）或
  私有属性（Python 3.10）保留。
- Windows 的字节写入现在显式使用 `O_BINARY`。Windows Python 3.10 门禁已验证
  `msvcrt` 锁分支可运行；其 `LK_LOCK` 在锁竞争持续超过平台的有限等待窗口时会在
  写入前以普通 I/O 错误失败，`ActionRuntime` 会把这种普通 recorder 错误标记为
  `audit_error`，而不是写入未受保护的事件。
- 本记录不再包含维护者机器的绝对路径或用户名。

## 残余风险与下一轮问题

目标文件锁是建议性的：旧版本、不合作写入者、某些网络文件系统或直接修改文件的
工具仍可能绕过它；突发断电/文件系统缓冲也可能在 `record()` 返回后丢失数据。回滚
本身若失败，trace 也可能不完整；普通 recorder/I/O 异常会由 runtime 标记为
`audit_error`，而 `KeyboardInterrupt` 等进程控制异常会保留并传播。Windows CI 是
该锁分支的基础门禁，但目前仍没有 Windows 双写入竞争的确定性测试。下一轮可在不扩大
产品权限的前提下，决定是否需要单独的持久化/共享存储故障模型；在此之前，应用应将
trace 视为辅助证据而非防篡改或强持久审计日志。
