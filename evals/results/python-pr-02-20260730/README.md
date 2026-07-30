# python-pr-02 pilot-v2 真实三臂运行

执行日期：2026-07-30

任务：`pallets/click` 的真实历史缺陷 `python-pr-02`

策略：`pilot-v2`

模型：`gpt-5.6-sol`

提示词：`python-review-v2`

## 结果

| 组 | Agent | 登记缺陷召回 | 误报 | 重复命中 | 总 Token | 工具调用 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 1 | 100% | 0 | 0 | 151,084 | 14 | 72.560 秒 |
| adaptive-max-4 | 2 | 100% | 0 | 1 | 271,640 | 19 | 154.576 秒 |
| fixed-4 | 4 | 100% | 0 | 1 | 524,702 | 39 | 297.858 秒 |

三组都找到了登记缺陷 `D-CLICK-2790`：错误提示从未过滤的帮助选项
列表取首项，可能推荐已经被普通参数占用的选项。该任务没有登记 serious
缺陷，因此输出中的 `serious_recall: 1.0` 是零分母约定，不能解释为验证
了 serious 缺陷能力。

adaptive 在第一个 Agent 后因变更文件尚未得到独立复查而扩容；第二个
Agent 后覆盖完整、无剩余风险，以 `target_reached` 停止。相对 fixed-4，
本次少使用 48.230% Token，同时保持相同登记缺陷召回和零误报。

## 解释边界

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

这是公开历史任务的一次重复，不能证明 Governor 有效。该任务从现在起
属于策略开发和校准数据，不得作为后续策略版本的未见验证任务。

## 评分说明

评分只在三个真实运行全部结束后读取 `truth.json` 和隐藏测试。自动匹配
因 Agent 报告 `UsageError.show`、真值卡登记 `UsageError.format_message`
而留下候选；修复版隐藏测试通过、缺陷版失败，全部候选按语义裁决为登记
缺陷命中。没有调用模型充当评审或合并 Agent。

本次裁决不是由一名看不到组别身份的独立人工评审者完成；因此尽管 outcome
格式中的 pending finding 已全部解决，结果仍应严格视为工程描述性证据。

## 文件

- `comparison.real.json`：三臂确定性比较；
- `*.outcome.json`：各组评分结果；
- `*.adjudications.json`：运行后隔离裁决；
- `metadata.json`：运行、预算、用量与裁决元数据；
- `archive.SHA256SUMS`：被 Git 忽略的完整原始归档哈希清单。

完整配置、Codex JSONL、last message、stderr、报告、adaptive 事件日志、
泄漏扫描和评分复现记录保存在：

```text
evals/runs/pilot-v2-real-python-pr-02-20260730/
```

原始归档共 53 个文件，约 516 KiB。
