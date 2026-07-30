# python-pr-07 首次真实三臂实验

执行日期：2026-07-30

任务：`pytest-dev/pluggy` 的真实历史缺陷 `python-pr-07`

策略：`pilot-v1`

模型：`gpt-5.6-sol`

提示词：`python-review-v2`

## 结果

| 组 | Agent | serious 召回 | 总召回 | 误报 | 总 Token | 工具调用 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 1 | 0% | 50% | 0 | 105,221 | 3 | 103.061 秒 |
| adaptive-max-4 | 1 | 0% | 50% | 0 | 77,428 | 3 | 145.601 秒 |
| fixed-4 | 4 | 0% | 50% | 0 | 354,609 | 35 | 276.050 秒 |

三组都找到了 `PluginManager.get_hookcallers` 重复返回
`HookCaller` 的 ordinary 缺陷，均漏掉
`HookCaller._remove_plugin` 部分删除实现的 serious 缺陷。
fixed-4 的四个 Agent 报告的是同一个缺陷，因此记录了三条重复命中，
没有增加缺陷召回。

adaptive 在第一个 Agent 后以 `marginal_gain_too_low` 停止。相对
fixed-4，它在本次运行中少使用约 78.17% Token，但召回没有改善，
而且同样漏掉 serious 缺陷。

## 解释边界

```text
descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

这是一个公开历史任务、一次重复，不能证明 Governor 有效。该任务从现在
起属于策略开发和校准数据，不得再作为后续策略版本的未见验证任务。

## 评分与运行异常

评分在三个真实运行全部结束后才读取 `truth.json`。无法精确匹配根因类别
字符串的发现经过逐条隔离裁决；所有候选均匹配
`D-PLUGGY-431-DUPLICATE`，没有误报。

fixed-4 中两个 Agent 生成了相同的 `finding_id`。运行后评分桥接层增加了
确定性的 `__occurrence-N` 标识命名空间处理。该修复只改变记录标识，
不改变发现内容、顺序或语义。

第一次 fixed-1 启动被外层文件沙箱阻止，立即以 `runtime_failure`
结束且消耗 0 Token。它没有计入比较；有效 fixed-1 按恢复协议在新的
clean 工作区从 Agent 1 重新运行。

## 文件

- `comparison.real.json`：三臂确定性比较；
- `*.outcome.json`：各组评分结果；
- `*.adjudications.json`：隔离裁决；
- `archive.SHA256SUMS`：本地完整原始归档的哈希清单。

完整配置、Codex JSONL、last message、stderr、报告、adaptive 事件日志和
0-Token 启动失败记录保存在被 Git 忽略的：

```text
evals/runs/python-pr-07-20260730/
```

原始归档共 47 个文件，约 688 KiB。归档中的
`implementation-after-scoring-fix.patch` 是运行准备实现加运行后评分
标识修复的完整工作树快照；真实 Agent 执行期间尚未使用后加的评分修复。
