# 本地评测工作区

这里包含首轮 Python PR 审查实验的 12 个可复现任务：8 个公开上游历史缺陷的生产代码反向补丁，和 4 个明确标为 synthetic 的本地 MIT fixture 任务。固定数量组用于建立 1–4 个同构 Agent 的质量／消耗曲线；自适应组检验 Governor 是否能在不读取真值的情况下提前停止。

这些工程试跑任务的 `truth.json` 和触发测试会随开源仓库公开，以便复现评分链路；“隐藏”仅表示它们在单次 Agent 运行时必须被隔离，**不表示它们是秘密保留集**。因此，这 12 个任务不能用于正式的未见任务效果声明。正式评测的保留任务及真值必须存放在独立的私有评测环境中。

## 当前状态

`pilot_manifest.json` 中的 12 个任务均为 `ready`，并包含固定基线 revision、补丁 SHA-256、许可证、来源、变更文件、运行时隔离真值卡和触发测试命令。静态校验应返回 12 个任务、13 个已知缺陷、7 个 serious 和 3 个 red-line 缺陷：

```bash
PYTHONPATH=src python3 -m magov.eval_cli validate \
  evals/pilot_manifest.json --workspace .
```

## 生成固定 Agent 数实验计划

```bash
PYTHONPATH=src python3 -m magov.eval_cli plan \
  evals/pilot_manifest.json \
  --model-id FIXED_MODEL_VERSION \
  --prompt-version python-review-v1 \
  --agent-counts 1 2 3 4 \
  --repetitions 2
```

12 个任务会生成 96 个固定数量试验。该命令只生成计划，不会启动 Agent。
固定数量执行、隔离评分和失败处理命令见
[runner-contract.md](runner-contract.md)。

## 生成 Governor 自适应实验计划

```bash
PYTHONPATH=src python3 -m magov.eval_cli adaptive-plan \
  evals/pilot_manifest.json \
  --model-id FIXED_MODEL_VERSION \
  --prompt-version python-review-v2 \
  --policy-version pilot-v1 \
  --max-agents 4 \
  --repetitions 2
```

这会生成 24 个自适应试验。固定组与自适应组合计 120 次。自适应组的
完整隔离、配置、评分与比较步骤见
[adaptive-runner-contract.md](adaptive-runner-contract.md)。
正式启动整批前，先按 [mini-pilot.md](mini-pilot.md) 运行
`python-pr-09` 的 fixed-1、adaptive-max-4、fixed-4 三臂验收。

已有的 `python-review-v1` 局部结果不能与 `python-review-v2` 自适应结果
混用。正式配对比较必须用 v2 重新运行所选固定数量参考组。

## 物化与触发验证

每次评测应先物化一个隔离工作目录；该目录只包含待审查代码、补丁和公开元数据，**不包含** `truth.json` 或运行时隔离测试。

```bash
PYTHONPATH=src python3 -m magov.eval_cli materialize \
  evals/pilot_manifest.json python-pr-01 /tmp/magov-task-01 --workspace .
```

在物化目录中执行 manifest 的 `test_command`。其中 `{hidden_test}` 由评测执行器替换为 Agent 运行时不可见的测试路径；带 `PYTHONPATH` 的命令是为了确保导入当前物化目录的源码，而不是机器上已安装的同名包。任务有效性的最低要求是：缺陷版本的触发测试失败，原始安全基线的同一测试通过。

真实 Agent 审查必须在未接触真值卡的外部干净环境中运行。固定审查提示词与运行交接约定见 [agent-review-prompt.md](agent-review-prompt.md) 和 [runner-contract.md](runner-contract.md)。

## 验证评分器

```bash
PYTHONPATH=src python3 -m magov.eval_cli score \
  evals/fixtures/truth.example.json \
  evals/fixtures/findings.example.json \
  --adjudications evals/fixtures/adjudications.example.json
```

自动匹配不了、且没有盲审结论的发现会保留为 `pending_findings`，不会直接算成误报。

## 本地结果

将试验结果以一行一个 JSON 的形式保存在 `evals/runs/*.jsonl`。该目录默认不进入 Git。完整实验约束见 [评测协议](../docs/evaluation-protocol.md)。
