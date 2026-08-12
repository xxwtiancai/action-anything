# ActionAnything 小红书首发素材

## 图片顺序

1. `assets/social/actionanything-xhs-cover.png`：首图，负责品牌和核心定位。
2. `assets/social/actionanything-xhs-how-it-works.png`：第二页，解释完整执行链路。

## 推荐标题

大厂都在做 Computer Use，我开源了它们中间的动作控制层

## 备选标题

- 我把 AI 的“手”开源了：ActionAnything
- 让任何 AI 的动作更可控，我做了个开源项目
- AI 会点鼠标之后，谁来阻止它点错？

## 正文

最近 OpenAI、Anthropic、Google 都在做 Computer Use：让 AI 看懂屏幕，自己点击、输入、滚动，完成真实任务。

但我在研究时发现一个问题：

模型会“提议动作”，不代表这个动作就应该直接执行。

如果 AI 要打开陌生网站、填写密码、提交表单，甚至执行不可逆操作，我们仍然需要一个模型之外、由确定性代码控制、可审查的动作层。

所以我做了 **ActionAnything**，并把第一版开源了。

它位于 AI 模型和浏览器之间：

1. 把不同模型的操作转换成统一 Action Schema；
2. 在执行前判断 Allow / Confirm / Deny；
3. 敏感操作要求人工确认；
4. 默认 Dry-run，不会直接碰真实环境；
5. 每一步都可以记录、审计和回放。

目前第一版已经包含：

✅ Navigate / Click / Type / Scroll / Wait / Screenshot 动作协议

✅ 风险等级、域名白名单和敏感输入策略

✅ Dry-run 与可选 Playwright 浏览器执行器

✅ 脱敏 JSONL 轨迹、Inspect 和 Replay

✅ `aa` 命令行工具和可运行示例

✅ 当前仓库有 67 个离线单元测试方法，覆盖动作、策略、执行器、Adapter 和 Trace；远程 CI 结果以 GitHub Actions 页面为准

项目仍处于 0.1 阶段。现在已有 OpenAI `computer_call` 的规范化 Adapter；接下来准备扩展更多已文档化的提供方输出、截图证据、隔离执行和 BrowserGym / WebArena 评测。

如果你也在研究 AI Agent、Computer Use 或自动化安全，欢迎来提 Issue、贡献代码，或者点一个 Star 让我知道这个方向值得继续做下去。

GitHub：

https://github.com/xxwtiancai/action-anything

## 话题标签

#开源项目 #GitHub #人工智能 #AIAgent #ComputerUse #Python #程序员 #独立开发 #自动化 #开源

## 置顶评论建议

现在的 OpenAI `computer_call` Adapter 只负责把受支持的输出规范化为统一 Action Schema，不绑定 SDK，也不发模型请求；模型调用、凭据和安全确认仍由接入应用负责。想优先看到哪个已文档化的提供方输出，可以在评论或 Issue 里告诉我。
