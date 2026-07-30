# pilot-v2 开发预注册

`pilot-v2` 是针对首次真实 `python-pr-07` 三臂实验暴露出的过程验证缺口
所开发的下一版实验策略。它尚未经过新的真实任务验证，不得替代
`pilot-v1` 的历史结果。

## 数据角色

- `python-pr-07`：开发和校准任务；
- `python-pr-09` 至 `python-pr-12`：工程 fixture；
- 下一批真实历史验证：`python-pr-01` 至 `python-pr-06`、`python-pr-08`，
  已冻结但尚未运行；

任何用于实现或调试 `pilot-v2` 的任务都必须登记为开发数据，不能再计入
未见任务效果结论。下一批任务、重复次数、模型、提示词、预算和运行顺序
见 [`pilot-v2-validation.md`](pilot-v2-validation.md)。代码提交仍须在
真实运行前记录并保持工作树干净。

## 固定规则

运行配置必须显式包含：

```json
{
  "policy": {
    "version": "pilot-v2"
  }
}
```

trial、task metadata、runtime report 和每个 decision receipt 中的策略版本
必须一致；未知版本或不一致配置直接失败，不允许静默回退到 `pilot-v1`。

对于满足以下全部条件的任务，`pilot-v2` 在停止前至少准入一个独立复核
Agent：

1. baseline 没有被外部 verifier 标记为 `verified`；
2. 公开结构信号声明至少两个可分离审查单元；
3. 策略选择 `independent` 拓扑；
4. Agent、成本和硬运行预算允许第二个 Agent。

该下限不能突破 Agent、成本、Token、累计 Agent 时间或工具调用上限。

代码审查 bridge 将“独立重复审查”登记为一个可分离审查单元，因此即使
只有一个 changed file，`pilot-v2` 也会在预算允许时要求第二个 Agent。
这不表示文件可以并行拆分；它表示第二个 Agent 在不读取第一个 Agent
输出的前提下，对同一变更做独立复核。该信号只依赖策略版本和公开的
changed-file 列表，不读取真值、隐藏测试或缺陷严重度。

## 过程 verifier

`pilot-v2` 只读取公开运行证据，不读取真值或隐藏测试。过程分数固定为：

- changed-file 覆盖：45%；
- changed-file 独立复核覆盖：30%；
- high-risk 文件独立复核覆盖：15%；
- 无未解决冲突：10%。

`coverage_complete` 要求所有 changed files 都被至少两个独立 Agent
审查、所有 high-risk files 满足独立复核，并且没有未解决冲突。
该字段仍然只是过程覆盖，不代表缺陷已经全部找到。

第二个 Agent 返回后，Governor 继续使用预先存在的目标、成本、硬预算和
观察平台期规则决定停止或逐个扩容。聚合仍是确定性 JSON 聚合，不得调用
模型充当协调或评分 Agent。

在 2026-07-30 的产品目标澄清后，`pilot-v2` 将初始
`plan.total_agents` 改为扩容预测，而不是运行时硬上限。第二个及后续
Agent 的公开实时证据仍有边际价值时，控制器可以超过预测逐个扩容，但
不得超过 `budget.max_agents` 或资源预算。`pilot-v1` 的历史行为不变。

如果达到 `budget.max_agents` 时仍未满足公开 verifier 目标，且未形成
预注册的边际平台期，必须输出：

```text
status: incomplete
stop_reason: cap_reached_incomplete
```

该结果是安全上限造成的右截断，不能解释为当前 Agent 数足够。成本、
Token、时间、工具预算耗尽和 runtime 故障同样是 `incomplete`。

## 当前验证范围

当前只允许：

- 单元测试；
- scripted dry-run；
- 配置、事件、receipt、checkpoint 和 usage 校验；
- Plugin 与 Skill 校验。

在获得用户明确确认前，不运行新的真实 `codex exec` 实验。

当前状态固定为：

```text
development_only
claim_allowed: false
engineering_result: inconclusive
```
