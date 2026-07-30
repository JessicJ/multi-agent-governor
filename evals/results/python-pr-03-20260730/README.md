# python-pr-03 pilot-v2 真实三臂运行

执行日期：2026-07-30

任务：`more-itertools/more-itertools` 的真实历史缺陷 `python-pr-03`

策略：`pilot-v2`

模型：`gpt-5.6-sol`

提示词：`python-review-v2`

## 结果

| 组 | Agent | 登记缺陷召回 | 误报 | 重复命中 | 总 Token | 工具调用 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 1 | 0% | 0 | 0 | 92,739 | 8 | 63.953 秒 |
| adaptive-max-4 | 2 | 100% | 0 | 2 | 187,313 | 19 | 152.646 秒 |
| fixed-4 | 4 | 100% | 0 | 4 | 440,921 | 34 | 274.549 秒 |

fixed-1 覆盖了变更文件但没有报告登记缺陷。adaptive 的第一个 Agent 已
报告一个相关表现，第二个独立 Agent 补充了 `locate` 和 `replace` 中内部
sentinel 泄漏给用户谓词的直接证据；隔离评分确认命中 `D-MORE-813`。
fixed-4 也命中同一缺陷，但额外报告均为重复命中。

adaptive 在第二个 Agent 后以 `target_reached` 停止。相对 fixed-4，本次
少使用 57.518% Token，同时保持相同登记缺陷召回和零误报。该任务没有
登记 serious 缺陷，因此 `serious_recall: 1.0` 是零分母约定。

## 解释边界

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

这是公开历史任务的一次重复，不能证明 Governor 有效。该任务从现在起
属于策略开发和校准数据，不得作为后续策略版本的未见验证任务。

## 评分说明

评分只在三个真实运行全部结束后读取 `truth.json` 和隐藏测试。修复版隐藏
测试通过、缺陷版失败。`locate`、`replace` 和空输入相关候选具有同一个
根因：内部 marker 窗口被传给用户谓词，因此全部裁决为登记缺陷命中。
没有调用模型充当评审或合并 Agent。

本次裁决不是由一名看不到组别身份的独立人工评审者完成；因此尽管 outcome
格式中的 pending finding 已全部解决，结果仍应严格视为工程描述性证据。

完整原始配置、trace、报告、事件日志、泄漏扫描和评分复现保存在：

```text
evals/runs/pilot-v2-real-python-pr-03-20260730/
```

原始归档共 53 个文件，约 484 KiB。
