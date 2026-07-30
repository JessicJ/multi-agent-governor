# pilot-v2 开发预注册

`pilot-v2` 是针对首次真实 `python-pr-07` 三臂实验暴露出的过程验证缺口
所开发的下一版实验策略。它尚未经过新的真实任务验证，不得替代
`pilot-v1` 的历史结果。

## 数据角色

- `python-pr-07`：开发和校准任务；
- `python-pr-09` 至 `python-pr-12`：工程 fixture；
- 后续效果评测任务：尚未选择和运行。

任何用于实现或调试 `pilot-v2` 的任务都必须登记为开发数据，不能再计入
未见任务效果结论。正式验证前必须另行冻结任务列表、重复次数、模型、
提示词、预算、运行顺序和代码提交。

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
2. 公开结构信号声明至少两个可分离工作单元；
3. 策略选择 `independent` 拓扑；
4. Agent、成本和硬运行预算允许第二个 Agent。

该下限不能突破 Agent、成本、Token、累计 Agent 时间或工具调用上限。

## 过程 verifier

`pilot-v2` 只读取公开运行证据，不读取真值或隐藏测试。过程分数固定为：

- changed-file 覆盖：45%；
- changed-file 独立复核覆盖：30%；
- high-risk 文件独立复核覆盖：15%；
- 无未解决冲突：10%。

`coverage_complete` 要求所有 changed files 都被至少两个独立 Agent
审查、所有 high-risk files 满足独立复核，并且没有未解决冲突。
该字段仍然只是过程覆盖，不代表缺陷已经全部找到。

第二个 Agent 返回后，Governor 继续使用预先存在的目标、计划上限、成本、
硬预算和观察平台期规则决定停止或逐个扩容。聚合仍是确定性 JSON 聚合，
不得调用模型充当协调或评分 Agent。

## 当前验证范围

当前只允许：

- 单元测试；
- scripted dry-run；
- 配置、事件、receipt、checkpoint 和 usage 校验；
- Plugin 与 Skill 校验。

在单独冻结新的真实任务与预算、并获得用户明确确认前，不运行新的真实
`codex exec` 实验。

当前状态固定为：

```text
development_only
claim_allowed: false
engineering_result: inconclusive
```
