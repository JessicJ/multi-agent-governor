# pressure-v1 max-8 真实历史压力批次

执行日期：2026-08-03

冻结协议：`pressure-v1-max-8`。配置、任务顺序和预算在运行前已登记；运行中
没有改动提示词、模型、信号、预算或 Agent 数量。

任务：`pressure-pr-01`（Click PR #3484）与 `pressure-pr-02`
（more-itertools PR #1117）。两者是新的真实历史任务，但都来自已使用过的
仓库家族，因此不能作为跨仓库泛化证据。

模型：`gpt-5.6-sol`；提示词：`python-review-v2`；自适应策略：`pilot-v2`；
Agent sandbox：read-only。

## 汇总结果

| 组 | 任务 | 实际 Agent | serious 命中 | 总缺陷命中 | 误报 | 总 Token | 工具调用 | 累计 Agent 时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 2 | 2 | 1/1 | 4/4 | 0 | 167,943 | 8 | 117.123 秒 |
| adaptive-max-8 | 2 | 4 | 1/1 | 4/4 | 0 | 378,338 | 18 | 254.223 秒 |
| fixed-8 | 2 | 16 | 1/1 | 4/4 | 0 | 1,465,792 | 68 | 984.237 秒 |

两个 adaptive trial 都在第二个独立审查 Agent 后满足公开过程覆盖，均以
`target_reached` 停止；没有超时、运行故障、Token/工具预算截断或
`cap_reached_incomplete`。相对 fixed-8，它保持相同的 serious 与总召回，
并减少 74.1888% 总 Token。

fixed-1 在这两个任务上同样发现全部登记缺陷，说明本批次没有形成一个能区分
1、2 与 8 个 Agent 的高压力质量曲线。尤其是，adaptive 从未准入第 3 个
Agent，因而它**不能**校准第三个或之后 Agent 的扩容条件。

## 审计边界

- 所有六个 Agent 目录在运行前都经泄漏扫描，未含 truth、hidden test、来源
  提示、Git 历史或其他组输出。
- 两个缺陷版本的隐藏触发测试在运行后重新执行，结果分别为 1 failed 与
  3 failed；固定修复版通过证据在冻结 preflight 中保存。
- 自动精确匹配无法覆盖同义根因描述。评分后在隔离环境中进行了逐项语义裁决，
  没有使用模型 judge；这些裁决不是独立、隐藏组别身份的人工盲审。
- 原始 Agent trace、工作区和隐藏测试不在本目录；此处仅保存用于复算的
  outcome、裁决、JSONL 汇总和确定性比较结果。

## 强制结论边界

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

这些结果证明已冻结的真实执行、隔离、one-at-a-time admission、用量回执、
确定性聚合和评分链路可以工作；不能证明 `max-8`、`pilot-v2` 或任何固定
Agent 数对未见项目普遍有效。
