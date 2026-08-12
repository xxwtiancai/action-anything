# 迭代 002：Trace 写入完整性

**状态：PR #2 已就绪，远程门禁通过，待维护者合入。** 本记录遵循
[AHE 维护闭环](../../AGENTS.md)：它是对 ActionAnything 的一次可独立回退的
证据完整性改进，不引入新的产品 Harness、模型调用或外部权限。

## 观察

`TraceRecorder.record()` 过去只调用一次 `os.write()`，却没有检查返回的字节数。
操作系统允许短写：动作可能已经完成，而 JSONL 事件只写入前缀，`record()` 仍会
返回成功；后续 `aa inspect` 或 replay 才因不完整 JSON 暴露问题。这会让调用方
误以为可用的审计证据已经落盘。

## 可证伪假设

若 recorder 在单个事件中持续写入全部剩余字节，并把零进度或非法进度视为失败，
且在失败后恢复该事件写入前的文件长度，则正短写不会留下不可解析事件；无进度时，
运行时会保留已执行的结果并标记审计失败，而不是把截断 trace 当成成功。

反例是：模拟正短写后 JSONL 仍无法解析，或模拟零进度写入后 runtime 没有
`audit_error`。

## 最小变更

- 在 `recorder.py` 新增私有 `_write_all()`：针对正短写继续写入剩余 `memoryview`；
  `InterruptedError` 重试；零/负值、布尔值或超过剩余长度的返回值抛出 `OSError`。若
  某次写入已写入前缀后失败，recorder 会恢复到写入该事件前的文件长度。
- `TraceRecorder.record()` 仅在完整事件写入后返回。
- 增加确定性测试：17 字节短写最终得到一条可读取事件；零进度写入失败；“先写入
  前缀、后零进度”回滚后下一条事件仍可读取；经 `ActionRuntime` 时保留动作的
  dry-run 状态并标记 `trace recording failed`。

范围外：该轮不提供多进程共享 trace 的锁、事务性文件系统保证、fsync 持久化
承诺，亦不改变默认策略、执行器权限、trace 脱敏或 CLI 合约。

## 实际验证

在 Python 3.12 本地离线环境执行：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/actionanything-pycache \
PYTHONPATH=src /Users/xiongweixiao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest tests.test_recorder tests.test_runtime -v
git diff --check
```

结果：**21 项定向测试通过**，格式检查通过。短写测试读取实际生成的 JSONL；
零进度测试断言底层 recorder 抛错且 runtime 返回 `audit_error`；部分写入后失败的
测试确认既有事件不受影响、下一条事件可解析。

随后运行了同一 Python 3.12 环境的全量离线测试：**71 项通过**。PR #2 的
GitHub Actions CI（Python 3.10–3.13 与构建）、CodeQL 和依赖审查也均通过。
本轮仍未运行真实并发文件系统压力测试；这些远程门禁不能证明多写入者语义。

## 残余风险与下一轮问题

`O_APPEND` 与完整写入循环/回滚不等价于跨进程事件原子性；恢复写前长度假定单一
写入者，多个写入者仍可能交错，突发断电/文件系统缓冲也可能在返回后丢失数据。
下一轮可在不扩大产品权限的前提下，决定是否定义单写入者约束或引入可选的进程间
锁与故障模型；在此之前，应用应将 trace 视为辅助证据而非防篡改或强持久审计日志。
