# 迭代 001：动作入口与浏览器边界

**状态：本地验证完成，待 PR/远程 CI 复核。** 这是一份
Agentic Harness Engineering（AHE）维护记录：它描述 ActionAnything 的一次
小范围、可复验的安全迭代，而不是在产品中新增 Harness 功能。

## 观察到的基线

本轮开始时，ActionAnything 已有动作协议、策略、dry-run 和可选浏览器
执行器，但下列边界尚不足以作为对不可信计划或提供方输出的稳定入口：

- 模型可通过任意参数、低声明风险或不兼容的提供方载荷扩大动作能力；
  `click`/`type` 的默认确认也不足以覆盖所有模型声明为低风险的情形。
- 仅检查显式导航无法约束重定向、点击后的跨域、非 HTTP(S) 协议、下载、
  Service Worker 或 WebSocket；浏览器截图路径和 trace 亦不能信任计划值。
- 默认 trace 曾可能保留 selector、提供方关联 ID、异常文字和 URL 路径；
  它不能成为秘密存储或可公开共享的日志。
- OpenAI Responses 的 `computer_call` 是单个 `action`，且带有状态和
  `pending_safety_checks`；忽略这些字段会把应用应处理的安全检查变成隐式
  执行许可。

## 可证伪假设

若把不可信数据在动作入口、提供方适配、策略、浏览器和 trace 的每一层
规范化/拒绝，并用离线回归测试证明拒绝路径，模型或网页就不能静默扩大
默认执行面或通过默认 trace 回显其载荷。

该假设会被以下现象否定：畸形动作或提供方安全检查仍到达执行器；未允许
的 URL/私网或旧式数值 IPv4 通过策略；默认 JSONL 中出现测试的秘密标记；
或默认 `click`/`type` 在没有确认处理器时仍被执行。

## 本轮范围

- 建立本仓库的 AHE 协作约定、组件地图和迭代证据格式；AHE 仅是开发方法。
- 严格校验全部内建动作参数、HTTP(S) URL 和截图相对路径；设定不可降低的
  风险下限，并令标准策略确认 `click`/`type`，导航要求显式 allowlist。
- 新增无网络 I/O 的 OpenAI `computer_call` normalizer：只接收已完成、无
  待处理安全检查的单个受支持动作，并保留最小 provenance。
- 收紧 Playwright 请求/当前页/弹窗/下载/Service Worker/WebSocket 边界，
  支持坐标点击和焦点输入，并限制截图制品输出。
- 默认 trace 仅保留固定、非秘密的结构性/数值信息；拒绝不安全的既有 trace 文件，
  不回显执行器错误；`--unsafe-trace` 仍仅适用于本地无敏感测试数据。
- 增加 CI、CodeQL、依赖审查、发布和社区健康基础，但未启用自动 PyPI 发布。

## 实际验证

在 Python 3.12 的本地离线环境执行：

```bash
PYTHONPATH=src /Users/xiongweixiao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s tests -v
```

结果：**67 项通过**。其中覆盖动作未知/缺失参数、低声明风险、数值 IPv4、
坏端口、Adapter 的安全检查与不回显路径、默认确认、CLI 预执行验证、递归
trace 脱敏、既有 trace 软链接/过宽权限拒绝，以及模拟 Playwright 的请求、
弹窗、WebSocket、重定向与截图路径边界。

另执行：

```bash
git diff --check
git diff --no-index --check /dev/null AGENTS.md
git diff --no-index --check /dev/null docs/maintainer-iterations/001-action-intake-browser-containment.md
```

结果：通过。

另在 `/private/tmp` 的干净副本中，以 Python 3.12 构建 wheel、在新的虚拟
环境离线安装该 wheel，并运行：

```bash
aa validate /path/to/examples/demo.json
```

结果：wheel 构建、离线安装和 `aa validate` 均通过；导入路径来自虚拟环境的
`site-packages`，不是工作树。直接在受限工作树构建曾因无法创建 `build/`
目录失败，因此采用干净临时副本验证打包，而不是将环境限制误报为包失败。

本轮**未运行真实 Chromium 端到端测试，也未运行远程 CI、CodeQL、依赖
审查或发布工作流**；模拟测试不能证明真实浏览器对 `file:`、`data:`、
`blob:`、Service Worker 与 WebSocket 的完整运行时语义。

## 迭代中的修正

- 初始数值主机检测把 `bad.cafe`、`dead.beef` 这类普通 DNS 名误认为旧式
  IPv4；已改为逐段解析，并添加回归测试。
- 默认 trace 的第一版仍保留上游可控 provenance、选择器、错误信息或 URL
  路径；已改为默认只记录固定结构/数值，完整本地重现需显式 `--unsafe-trace`。
- 本地普通 Python 为 3.9，不满足项目的 Python 3.10+ 支持范围；验证改用
  项目环境提供的 Python 3.12。

## 残余风险

- 域名允许列表不是完整的网络沙箱：DNS 解析、DNS rebinding、代理、
  浏览器/宿主进程能力及部署网络策略仍需要隔离环境和应用级控制。
- 结构化动作与规则策略不能证明模型或网页内容的语义意图安全；业务规则、
  高影响操作的确认、测试账户和人工/应用策略仍是必要边界。
- Provider 协议会变化；新增字段或安全检查不得被静默接受、自动确认或
  通过原始载荷泄露到 trace。
- 脱敏 trace 仍可能泄露时间、动作类别、数值、结果状态及未来代码遗漏的
  字段；不得把它当作可公开共享的
  数据集或秘密存储替代品。
- 默认确认阈值从 `EXTERNAL` 收紧为 `REVERSIBLE`，因此旧的无确认处理器
  的 `click`/`type` 调用现在会得到 `cancelled`。这是刻意的 0.x 安全性
  兼容性变化，应在合并前由维护者复核。

## 下一轮可验证问题

在专用、隔离的 Chromium 测试环境中，如何建立可重复的真实浏览器证据：
请求/重定向/弹窗/下载/WebSocket 被拦截，且控制未被 Service Worker 或代理
路径绕过？同时应明确哪些控制必须由隔离浏览器、代理或宿主环境承担。
