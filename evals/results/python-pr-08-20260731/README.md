# python-pr-08 pilot-v2 真实三臂运行

执行日期：2026-07-31

任务：`pytest-dev/pluggy` 的真实历史缺陷 `python-pr-08`

策略：`pilot-v2`

模型：`gpt-5.6-sol`

提示词：`python-review-v2`

## 结果

| 组 | Agent | serious 召回 | 总召回 | 误报 | 重复命中 | 总 Token | 工具调用 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-1 | 1 | 100% | 100% | 0 | 0 | 76,254 | 3 | 61.012 秒 |
| adaptive-max-4 | 2 | 100% | 100% | 0 | 1 | 274,613 | 11 | 170.494 秒 |
| fixed-4 | 4 | 100% | 100% | 0 | 2 | 457,114 | 16 | 247.321 秒 |

三组都报告了 `HookCaller.__call__` 和 `call_historic` 把可变的
`_hookimpls` 原列表交给 dispatch 后，hook 执行期间注册或注销插件会改变
当前迭代。隔离评分确认命中登记的 serious 缺陷 `D-PLUGGY-438`。
adaptive 在第二个 Agent 独立覆盖变更文件后以 `target_reached` 停止；
相对 fixed-4 少使用 39.925% Token，serious 和总召回相同，且两组均无
误报。

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
revision 对普通和 historic 两种注册中途变更场景均失败；反向应用已登记
的生产代码补丁恢复历史修复后，两种场景均通过。

所有报告都指向同一登记根因；多余报告计为重复命中，没有调用模型充当
评审或合并 Agent。本次裁决不是由一名看不到组别身份的独立人工评审者
完成，因此结果只能作为工程描述性证据。

完整原始配置、trace、报告、事件日志、泄漏扫描和评分复现保存在：

```text
evals/runs/pilot-v2-real-python-pr-08-20260731/
```

原始归档共 56 个文件，约 584 KiB。
