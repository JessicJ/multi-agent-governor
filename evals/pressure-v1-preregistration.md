# pressure-v1：max-8 压力验证预注册

机器可读冻结条件见
[`pressure-v1-preregistration.json`](pressure-v1-preregistration.json)。本批次
只检验“在两个新真实历史任务上，何时继续增加同模型审查 Agent 有可验证
增益”；它不会重写或混入既有 `pilot-v2` 的 7 任务结果。

## 任务与来源边界

只使用用户已限定的仓库，并排除所有既有 `python-pr-01` 至
`python-pr-08` 的 revision：

1. `pressure-pr-01`：Click PR #3484，参数来源在 type conversion 阶段不可见。
2. `pressure-pr-02`：more-itertools PR #1117，`repeat` 与 iterator 组合时
   会消耗后续重复使用的迭代器。

两者均是新任务、但不是新仓库。因此结果最多说明这些新的历史修复任务，
不能宣称对陌生项目或任意 Agent 数普遍有效。来源、许可证、生产反向补丁、
触发测试和禁止泄漏提示登记在
[`pressure-v1-historical-provenance.json`](pressure-v1-historical-provenance.json)。

## 固定运行条件

- 模型：`gpt-5.6-sol`，不允许替换；
- 提示词：`python-review-v2`；策略：`pilot-v2`；
- sandbox：read-only；关闭用户配置与 Codex 原生 multi-agent；
- 每个 task/arm 使用独立物化目录；不共享 outputs、trace 或 artifacts；
- 聚合只使用确定性 JSON 聚合器；Agent 运行时看不到真值、隐藏测试、
  provenance、manifest、Git 历史或 Governor 项目；
- 先完成一个 task 的 `fixed-1`、`adaptive-max-8`、`fixed-8`，才处理下一个；
  不得依据前序结果改动后续的提示词、预算、信号或 Agent 数量。

| arm | Agent 规则 | 每任务 Token 硬上限 | 工具调用上限 |
|---|---:|---:|---:|
| fixed-1 | 精确 1 | 175,000 | 100 |
| adaptive-max-8 | 从 1 起，逐个准入，最多 8 | 750,000 | 400 |
| fixed-8 | 精确 8，除故障/超时/安全上限外必须跑完 | 1,400,000 | 800 |

全批次三臂硬上限相加为 4,650,000 Token，低于用户冻结的 5,000,000 Token；
预估范围为 1.2M–3.6M。`adaptive-max-8` 在第二个 Agent 后只能按已登记的
公开覆盖、冲突、非真值新证据与预算信号，每次增加一个 Agent；每次准入和
停止理由必须在 receipt、checkpoint 与 event log 中保留。达到 8 仍不完整时
必须如实记为 `cap_reached_incomplete`。

## 运行与评分

真实运行前，使用已有的 `magov-eval fixed-config`（分别设 1 和 8）和
`magov-eval adaptive-config --max-agents 8` 生成配置；执行顺序、Token 数值和
输出位置必须与 JSON 预注册一致。只有用户再次明确授权后，才可执行
`fixed-run` 或 `magov run`。

评分层在所有 arm 结束后才读取 `truth.json` 与 `hidden_test.py`，比较 serious/
total 召回、false positive、四个 Token 字段、工具调用、实际 Agent 数、累计
Agent 时间和墙钟时间。即使结果良好，固定结论仍是：

```json
{
  "status": "descriptive_only",
  "claim_allowed": false,
  "engineering_result": "inconclusive"
}
```

scripted dry-run 仅检查流程和收据格式，绝不作为真实实验结果。
