# python-pr-05 pilot-v2 真实三臂运行

执行日期：2026-07-31

任务：`python-attrs/attrs` 的真实历史缺陷 `python-pr-05`

策略：`pilot-v2`

模型：`gpt-5.6-sol`

提示词：`python-review-v2`

## 结果

| 组 | Agent | 登记缺陷召回 | 误报 | 重复命中 | 总 Token | 工具调用 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 1 | 100% | 0 | 0 | 67,240 | 3 | 41.121 秒 |
| adaptive-max-4 | 2 | 100% | 0 | 1 | 133,358 | 6 | 57.488 秒 |
| fixed-4 | 4 | 100% | 0 | 3 | 301,856 | 14 | 132.464 秒 |

三组都报告了 `attrs.validators.disabled()` 没有保存并恢复先前全局状态，
导致嵌套上下文提前重新启用验证器。隔离评分确认命中 `D-ATTRS-1513`。
adaptive 在第二个 Agent 独立覆盖变更文件后以 `target_reached` 停止；
相对 fixed-4 少使用 55.821% Token，登记缺陷召回相同，且两组均无误报。

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

评分只在三个真实运行全部结束后读取 `truth.json` 和隐藏测试。原始缺陷
revision 的嵌套上下文触发测试失败；反向应用已登记的生产代码补丁恢复
历史修复后，同一测试通过。

所有 Agent 报告都是同一登记根因的命中；多余报告计为重复命中，没有调用
模型充当评审或合并 Agent。本次裁决不是由一名看不到组别身份的独立人工
评审者完成，因此结果只能作为工程描述性证据。

完整原始配置、trace、报告、事件日志、泄漏扫描和评分复现保存在：

```text
evals/runs/pilot-v2-real-python-pr-05-20260731/
```

原始归档共 56 个文件，约 352 KiB。
