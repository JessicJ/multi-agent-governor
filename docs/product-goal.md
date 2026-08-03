# Multi-Agent Governor 产品目标

状态：`product-target-v1`

## 一句话目标

Multi-Agent Governor 是面向可验证代码审查任务的 Agent 预算控制器：
从一个同构 Agent 基线开始，在用户给定的 Agent、Token、时间和工具预算
内，只在非真值的可观察边际收益仍值得时逐个扩容，并对停止原因和未完成
风险给出可审计记录。

## 它解决什么

Governor 不预先猜测一个项目“正确的 Agent 数量”。它在每个 Agent 返回
后回答一个更可操作的问题：

> 在当前证据和剩余预算下，再增加一个 Agent 是否仍值得？

Agent 数针对一次具体审查任务，而不是整个仓库。用户配置的
`max_agents` 是成本与安全边界，不是系统对充分 Agent 数量的断言。

## 它不解决什么

- 不证明多 Agent 总是优于单 Agent；
- 不保证在任意安全上限内找到全部缺陷；
- 不把过程覆盖分解释为隐藏真值正确率；
- 不把 `max_agents=4` 或任何固定数字解释为通用最优值；
- 当前可执行范围不包括通用开发、研究、写作或异构专家调度。

## 运行契约

1. 必须先运行一个可计量的单 Agent 基线。
2. 运行时不得读取隐藏真值、隐藏测试或其他 Agent 的私有 trace。
3. 每次最多准入一个新 Agent。
4. 每个 checkpoint 必须记录覆盖、冲突、新证据、重复证据和累计用量。
5. 初始计划数量只是预测。`pilot-v2` 允许实时正向证据超过该预测继续
   扩容，但不得超过用户安全上限或资源预算。
6. 确定性聚合不得偷偷增加一个未计费的模型协调者。

核心停止结果：

| `stop_reason` | 含义 | 运行状态 |
|---|---|---|
| `target_reached` / `baseline_sufficient` | 公开 verifier 目标与覆盖均已满足 | `completed` |
| `observed_plateau` / `marginal_gain_too_low` | 新 Agent 的可观察边际价值不足 | 覆盖完整时 `completed`，否则 `incomplete` |
| `*_budget_reached` | 成本、Token、时间或工具预算耗尽 | `incomplete` |
| `cap_reached_incomplete` | 到达用户 Agent 上限但目标和平台期条件均未满足 | `incomplete` |
| `runtime_failure` | Agent runtime 未形成完整结果 | `incomplete` |

`completed` 只表示控制器按其公开规则完成了本次决策，且公开验证覆盖完整；
不表示代码已经被证明无缺陷。若平台期或单 Agent 停止时覆盖仍缺失，控制器
保留节省调用的决定，但必须记录为 `incomplete`，不能把经济性停止伪装成
验证完成。`cap_reached_incomplete` 是右截断结果，不能用于声称该上限足够。

## 可证伪的产品成功指标

以下是未来保留集确认实验的目标，不是当前已达成结果。相对同模型、同
提示词、同任务内容的固定高预算参考组，Governor 必须同时满足：

1. 严重缺陷召回率非劣界限不低于 `-2` 个百分点；
2. 误报占比差异上界不高于 `+3` 个百分点；
3. 红线缺陷漏检次数不高于固定参考组；
4. 每任务总 Token 中位数至少降低 `20%`，并计入治理开销；
5. `cap_reached_incomplete` 的任务不得计为质量护栏通过；
6. 事件、checkpoint、receipt、Agent 数和用量可重放一致率为 `100%`。

确认实验必须使用未参与策略开发的项目，至少 60 个任务、每组至少 3 次
重复，并报告置信区间。未满足任何一项即为 `fail`；统计精度不足或存在
上限截断即为 `inconclusive`。

## 分阶段路线

1. **机制正确性**：单元测试、scripted dry-run、预算与截断状态、事件
   重放、隔离和泄漏扫描；不消耗真实模型。
2. **区间校准**：真实历史任务上观察 1–4 Agent 的质量—成本曲线和停止
   行为；只产生描述性工程证据。
3. **上限压力测试**：在新的、更大变更上预注册 1–8 Agent 区间，检查
   4 Agent 截断任务是否继续获得边际价值。
4. **保留集确认**：冻结策略后运行跨项目、重复的私有或未见任务；只有
   此阶段满足全部成功指标，才允许作有边界的效果声明。

当前 `pilot-v2` 已完成第 1 阶段，并完成了第 2 阶段的首个冻结历史任务
批次：7 个真实任务、每个任务 1 次重复、共 21 个真实运行。结果仅为
`descriptive_only`，`claim_allowed: false`，工程结论为 `inconclusive`；
详见
[`evals/results/pilot-v2-validation-20260731/`](../evals/results/pilot-v2-validation-20260731/)。
现有 `adaptive-max-4` 只能描述 1–4 Agent 区间，不能回答任意规模任务
需要多少 Agent。下一步是第 3 阶段的独立上限压力测试，而不是把本批次
包装成效果证明。
