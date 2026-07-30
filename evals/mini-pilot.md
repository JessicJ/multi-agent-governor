# 首批真实三臂 Mini-pilot

目的：在启动 120 次工程试跑前，用最小批次验证真实模型的三组记录口径
一致。该批次只能验证链路，不能证明 Governor 有效。

## 固定条件

- 任务：`python-pr-09`
- 重复：`repeat-1`
- 模型：`gpt-5.6-sol`，不可静默替换
- 提示词：`python-review-v2`
- 策略：`pilot-v1`
- sandbox：`read-only`
- 用户配置：关闭
- Codex 原生多 Agent：关闭
- 三个独立物化目录，运行间不共享 trace 或 Agent 输出

## 运行顺序

为避免看见某组结果后改变后续设置，顺序预先固定为：

1. fixed-1
2. adaptive-max-4
3. fixed-4

三组完成后才进入隔离评分。不得因前一组发现了缺陷而修改提示词、信号、
预算、文件风险标签或下一组 Agent 数。

## 安全上限

- 自适应组：500,000 累计 Token、3600 秒、200 次工具调用；
- 固定组：2,000,000 累计 Token、3600 秒、400 次工具调用；
- 单 Agent 超时：900 秒；
- 任一组出现 runtime failure、非结构化结果、工作区泄漏或安全上限停止，
  该组记为 `incomplete`，暂停 mini-pilot，不用补写结果伪装成功。

以前 `python-review-v1` 的局部结果只用于估算：`python-pr-09` 单 Agent
约 116k Token，双 Agent 约 228k Token。按此粗略估计，三臂 mini-pilot
约需 0.8M Token；实际数字必须以 v2 的 JSONL 为准。

## 通过链路验收的条件

- fixed-1 的 `actual_total_agents` 为 1；
- fixed-4 的 `actual_total_agents` 为 4，即使第二个 Agent 后覆盖已完成；
- adaptive 的 Agent 数在 1–4 之间，并有每轮准入／停止收据；
- 每组 checkpoint 从 1 连续递增；
- checkpoint usage delta 之和等于最终 usage；
- 三组只在结束后读取同一份隔离真值；
- `magov-eval compare` 输出配对结果，但保持
  `descriptive_only`、`claim_allowed: false` 和
  `engineering_result: inconclusive`。

满足这些条件后，再决定是否运行 `repeat-2`；两个重复均稳定后，才扩展到
第二个普通、单文件任务 `python-pr-01`。
