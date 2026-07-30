# 自适应 Runtime 控制

状态：experimental-v0.2

## 边界

`GovernorSession.plan()` 是兼容的建议接口。`AdaptiveController.execute()`
才拥有额外 Agent 的准入能力。一个运行若绕过 Controller 直接启动额外
Agent，就不能声称 Governor 强制了预算或停止规则。

首个可执行场景是结构化、只读代码审查。它使用同模型、同工具的同构
Agent。当前版本不调度异构专家，也不为通用软件开发提供可靠质量验证。

## 核心协议

- `AgentRuntime.run_agent(request) -> AgentResult`
- `Aggregator.aggregate(task, results) -> AggregatedResult`
- `Verifier.verify(task, aggregate, results) -> VerificationResult`
- `AdaptiveController.execute(task, budget) -> ExecutionReport`

baseline Agent 尝试完整任务。额外 Agent 在 `independent` 模式下独立复核，
在 `centralized` 模式下领取预先声明的有边界工作单元。代码审查输出由
确定性 JSON 聚合器合并，不额外调用一个未计费的协调模型。

## 可观察证据

运行时不得读取隐藏真值。当前代码审查 verifier 只使用：

- 变更文件是否被审查；
- 高风险文件是否被两个不同 Agent 审查；
- 是否存在未解决冲突；
- 新 Agent 的结构化发现是新增还是重复；
- 真实 Token、模型调用、工具调用和耗时。

因此 `score` 是外部过程证据分，不是模型自信，也不是缺陷召回率。
隐藏真值只供离线评测。

## 停止

Controller 在每个 Agent 返回后调用 `review_scaling()`。以下任一条件可停止：

- 观察分达到目标；
- 达到计划 Agent 上限或用户上限；
- 标准化成本达到上限；
- Token、耗时或工具调用达到硬预算；
- 最近若干 Agent 的边际质量或新证据过低；
- Runtime 失败。

硬预算是在一次 Agent 返回后根据实际累计用量检查的，因此单次 Agent
可能让累计值越过预算。Controller 保证越过后不再准入下一个 Agent，
不能保证未知成本的在途 Agent 精确停在阈值之前。

## Codex CLI 适配器

每个准入 Agent 对应一个新的 `codex exec --ephemeral --json` 进程。适配器：

- 不使用 shell；
- 显式传入 `--disable multi_agent`，避免单次 Codex 进程内部再生成未计数
  的原生子 Agent；
- 只允许 `read-only` 或 `workspace-write`；
- 拒绝已知安全绕过参数；
- 支持固定模型、输出 schema 和超时；
- 从 `turn.completed.usage` 提取 Token；
- 记录 JSONL、stderr 和最终消息；
- 强制运行产物目录位于 Agent 工作目录之外。

Codex CLI 适配器会关闭进程内部的原生多 Agent 工具；上层调用者也不得
在同一运行中另行启动子 Agent。所有额外 Agent 必须由 `magov run` 创建。

## 事件与回放

事件日志是每个运行一个文件的连续 JSONL：

```text
run_started
agent_started
agent_completed
verification_completed
scale_decision
agent_admitted
checkpoint
run_completed
```

事件文件不得复用；已有非空文件会被拒绝，避免把多个运行拼接成无法可靠
回放的日志。Agent 原始最终消息默认不进入报告或事件，只保存在隔离的
runtime artifact 中。
