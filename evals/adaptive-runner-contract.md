# 自适应 Governor 盲测运行约定

本文件只描述 `magov run` 自适应对照组。固定 1、2、3、4 Agent 组继续
遵循 [runner-contract.md](runner-contract.md)。

## 预先固定的条件

- 模型：所有组使用同一个精确模型版本；
- 提示词：`adaptive-review-prompt.txt`，版本记为
  `python-review-v2`；
- 策略：`pilot-v1`；
- 最大 Agent 数：4，包含 baseline；
- 每个任务重复 2 次；
- Codex sandbox：`read-only`；
- Codex 用户配置：关闭；
- Codex 原生多 Agent 工具：关闭；
- 真值、触发测试、其他 Agent 的 trace 与项目根目录：运行时不可见。

首次真实 mini-pilot 固定为 `python-pr-07`、`repeat-1`、模型
`gpt-5.6-sol`，并使用三个独立物化目录；准确命令和输出位置见
[mini-pilot.md](mini-pilot.md)。

`pilot-v1` 信号只能由 manifest 中公开的 `changed_files` 和
`high_risk_files` 派生。具体常量定义在
`derive_pilot_review_signals()`；不得根据 `truth.json`、触发测试结果或
某次 Agent 输出临时修改。

工程试跑包含 24 个自适应试验：12 个任务 × 2 次重复。它们与 96 个固定
数量试验合计 120 次。

## 单次运行

1. 物化一个无真值工作目录：

   ```bash
   magov-eval materialize evals/pilot_manifest.json TASK_ID \
     /tmp/TASK_DIRECTORY --workspace .
   ```

2. 生成预声明 trial 与无真值运行配置：

   ```bash
   magov-eval adaptive-config \
     evals/pilot_manifest.json TASK_ID /tmp/TASK_DIRECTORY \
     --model-id FIXED_MODEL_ID \
     --prompt-version python-review-v2 \
     --policy-version pilot-v1 \
     --prompt-template evals/adaptive-review-prompt.txt \
     --output-schema examples/review_output.schema.json \
     --artifacts-directory /tmp/ARTIFACTS > CONFIG_ENVELOPE.json
   ```

   输出 envelope 包含 `trial` 与 `run` 两个对象，可直接交给
   `magov run`。运行环境不得得到 manifest 或项目根目录。

3. 由 Governor 执行：

   ```bash
   magov run CONFIG_ENVELOPE.json \
     --events RUN.events.jsonl > RUN.report.json
   ```

4. Agent 全部结束后，才在隔离评分环境中合并 `trial`、报告和真值：

   ```bash
   magov-eval adaptive-outcome \
     CONFIG_ENVELOPE.json RUN.report.json TRUTH.json > OUTCOME.json
   ```

5. 将每个 `OUTCOME.json` 作为一行加入本地 adaptive outcome JSONL。

## 汇总与比较

```bash
magov-eval adaptive-summarize adaptive-outcomes.jsonl
magov-eval compare fixed-outcomes.jsonl adaptive-outcomes.jsonl \
  --reference-agents 4
```

比较必须配对相同任务和重复编号，并使用相同模型与提示词版本。工程试跑
无论数字如何都只输出 `descriptive_only` 和 `inconclusive`，不得变成
公开有效性结论。
