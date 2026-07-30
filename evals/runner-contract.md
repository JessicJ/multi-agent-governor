# 盲测运行交接约定

本文件描述如何在 **干净的外部 Agent 运行环境** 中执行 `pilot_manifest.json` 的试验。它不是 Governor 的一部分，也不授权 Governor 启动或调度 Agent。

工程试跑的真值与触发测试在本仓库中公开；这里的隔离仅保证参与单次试验的 Agent 在运行时无法访问它们。它们不是秘密保留集，也不能支持正式的未见任务效果声明。

## 为什么必须隔离

运行器只能得到：一个 `magov-eval materialize` 生成的任务目录、固定审查提示词和指定的 `TrialSpec`。它不得看到项目根目录、`truth.json`、`hidden_test.py`、触发验证结果或其他任务。否则结果不能作为盲测证据。

## 每个 TrialSpec 的执行步骤

1. 在受限目录中物化一个任务；物化目录不应包含真值卡或运行时隔离测试。
2. 使用 [agent-review-prompt.md](agent-review-prompt.md) 启动恰好 `exact_total_agents` 个同模型 Agent。
3. 主 Agent 是其中之一；其余 Agent 独立审查同一代码快照。所有 Agent 均为只读。
4. 每个 Agent 返回结构化发现、已审查文件和冲突数。记录实际输入、输出、缓存 Token，模型调用、工具调用和耗时。
5. 每个 Agent 返回后记录一个检查点；检查点只包含聚合统计，不保存完整回答。
6. 仅在所有 Agent 结束后，在独立评分环境中把合并后的发现与运行时隔离真值卡匹配。未知发现进入盲审，不直接算误报。

## 不可变的实验条件

- 同一批试验固定模型版本、工具权限、基础提示词和代码快照；
- 只改变 `exact_total_agents`（1、2、3、4）与预先计划的重复编号；
- 不允许按结果临时加 Agent；渐进扩容与停止策略另作为 Governor 对照组试验；
- 任务完成前不得读取或执行运行时隔离测试；
- 每次输出写入本地 JSONL，再通过 `magov-eval summarize` 汇总。

## 结果回写最小字段

每行 JSONL 必须符合 `TrialOutcome`：`trial`、`actual_total_agents`、`usage`、`score`、`coverage_complete`、`unresolved_conflicts` 和递增的 `checkpoints`。评分所需的 `score` 必须来自独立评分步骤，不能在 Agent 审查期间生成。

工程试跑的结果状态始终是 `inconclusive`；它只证明运行链路可用，不证明 Governor 的策略已经有效。
