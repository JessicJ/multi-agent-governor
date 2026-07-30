# python-pr-04 pilot-v2 真实三臂运行

执行日期：2026-07-30

任务：`more-itertools/more-itertools` 的真实历史缺陷 `python-pr-04`

策略：`pilot-v2`

模型：`gpt-5.6-sol`

提示词：`python-review-v2`

## 结果

| 组 | Agent | 登记缺陷召回 | 误报 | 重复命中 | 总 Token | 工具调用 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 1 | 100% | 0 | 0 | 71,445 | 5 | 43.892 秒 |
| adaptive-max-4 | 2 | 100% | 0 | 1 | 241,836 | 16 | 88.899 秒 |
| fixed-4 | 4 | 100% | 0 | 2 | 335,558 | 27 | 154.870 秒 |

三组都报告了 `numeric_range.__reversed__` 删除空序列保护后会对空
`numeric_range` 抛出 `IndexError`，隔离评分确认命中
`D-MORE-EMPTY-REVERSED`。adaptive 在第二个 Agent 独立覆盖变更文件后以
`target_reached` 停止；相对 fixed-4 少使用 27.930% Token，登记缺陷召回
相同，且两组均无误报。

该任务没有登记 serious 缺陷，因此 `serious_recall: 1.0` 是零分母约定。

## 解释边界

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

这是公开历史任务的一次重复，不能证明 Governor 有效。该任务从现在起
属于策略开发和校准数据，不得作为后续策略版本的未见验证任务。

## 评分与复现

评分只在三个真实运行全部结束后读取 `truth.json` 和隐藏测试。对原始缺陷
revision 运行隐藏触发测试时稳定抛出 `IndexError`；反向应用已登记的生产
代码补丁恢复历史修复后，同一测试通过。原始缺陷 revision 的两个公开测试
文件结果为 `715 passed, 19896 subtests passed`。

所有 Agent 报告都是同一登记根因的命中；多余报告计为重复命中，没有调用
模型充当评审或合并 Agent。本次裁决不是由一名看不到组别身份的独立人工
评审者完成，因此结果只能作为工程描述性证据。

完整原始配置、trace、报告、事件日志、泄漏扫描和评分复现保存在：

```text
evals/runs/pilot-v2-real-python-pr-04-20260730/
```

原始归档共 57 个文件，约 452 KiB。
