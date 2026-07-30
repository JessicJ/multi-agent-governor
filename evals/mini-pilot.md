# 首批真实三臂 Mini-pilot

目的：用一个真实开源历史缺陷任务验证三组运行、隔离、恢复、用量记录和
评分链路。该批次只有一个任务、一次重复，只能产生描述性工程结果，不能
证明 Governor 有效。

## 真实任务与固定条件

- 项目：`pytest-dev/pluggy`
- 任务：`python-pr-07`
- 重复：`repeat-1`
- 修复 PR：`https://github.com/pytest-dev/pluggy/pull/646`
- 修复提交：`20d8143f127a4d7526dbbea441857b4b80ec8bdd`
- 原始缺陷 revision：`6e1d0f13a259776bbf137f90bd7ab8b4474f68e7`
- 许可证：MIT
- 模型：`gpt-5.6-sol`，不可静默替换
- 提示词：`python-review-v2`
- 策略：`pilot-v1`
- sandbox：`read-only`
- Codex 用户配置：关闭
- Codex 原生 multi-agent：关闭
- 每组使用独立物化目录和独立 artifacts 目录
- Agent 运行期间不读取真值、触发测试、来源登记或其他组输出
- 所有组使用相同模型、提示词模板、任务内容和代码状态
- 聚合只使用现有确定性 JSON 聚合器，不启动评审或合并模型

`python-pr-07` 的 Agent 目录直接检出已登记的原始缺陷 revision，再移除
`.git`；这样不会残留修复提交新增的回归测试和 changelog。待审
`.magov-review.diff` 保持为从真实修复提交到原始缺陷代码的生产代码
反向补丁。

## 预先固定的运行顺序

1. fixed-1
2. adaptive-max-4
3. fixed-4

不得根据前一组的结果修改后一组的提示词、预算、信号、Agent 数或风险
标签。fixed-1 精确运行一个 Agent；adaptive-max-4 从一个 Agent 开始，
最多四个，只按 `pilot-v1` 的公开结构信号和运行中非真值验证结果扩容或
停止；fixed-4 必须精确运行四个相互独立的 Agent，除非运行故障、超时或
安全上限使该组变为 `incomplete`。

## 安全上限与预计用量

- fixed-1：500,000 累计 Token、3600 秒累计 Agent 时间、400 次工具调用；
- adaptive-max-4：500,000 累计 Token、3600 秒累计 Agent 时间、200 次工具调用；
- fixed-4：2,000,000 累计 Token、3600 秒累计 Agent 时间、400 次工具调用；
- 单 Agent 超时：900 秒；
- 三组 Token 硬上限合计：3,000,000。

Token 和工具上限在每个 Agent 返回后的 checkpoint 强制执行；底层
`codex exec` 没有逐调用 Token 截断参数，因此单个正在运行的 Agent 可能
让累计值越过阈值一轮。900 秒单 Agent 超时是这段窗口的额外安全边界。

以前 `python-review-v1` 的 synthetic `python-pr-09` 局部结果只可用于粗略
量级估算，不能当作本任务数据。首次真实运行预计约 0.7M–1.5M Token；
实际用量必须以每个 Codex JSONL 的 `turn.completed.usage` 汇总为准。

任一组出现 runtime failure、非结构化结果、工作区泄漏或安全上限停止，
该组记为 `incomplete` 并暂停后续真实运行，不补写结果伪装成功。

## 输出目录与物化

以下命令假定从仓库根目录执行：

```bash
export MAGOV_FIXED1_ROOT="/tmp/magov-python-pr-07-fixed-1"
export MAGOV_ADAPTIVE_ROOT="/tmp/magov-python-pr-07-adaptive-max-4"
export MAGOV_FIXED4_ROOT="/tmp/magov-python-pr-07-fixed-4"
export MAGOV_COMPARE_ROOT="/tmp/magov-python-pr-07-compare"
mkdir -p \
  "$MAGOV_FIXED1_ROOT/configs" "$MAGOV_FIXED1_ROOT/artifacts" \
  "$MAGOV_FIXED1_ROOT/reports" "$MAGOV_FIXED1_ROOT/outcomes" \
  "$MAGOV_ADAPTIVE_ROOT/configs" "$MAGOV_ADAPTIVE_ROOT/artifacts" \
  "$MAGOV_ADAPTIVE_ROOT/reports" "$MAGOV_ADAPTIVE_ROOT/outcomes" \
  "$MAGOV_FIXED4_ROOT/configs" "$MAGOV_FIXED4_ROOT/artifacts" \
  "$MAGOV_FIXED4_ROOT/reports" "$MAGOV_FIXED4_ROOT/outcomes" \
  "$MAGOV_COMPARE_ROOT"

cp examples/review_output.schema.json \
  "$MAGOV_FIXED1_ROOT/configs/review_output.schema.json"
cp examples/review_output.schema.json \
  "$MAGOV_ADAPTIVE_ROOT/configs/review_output.schema.json"
cp examples/review_output.schema.json \
  "$MAGOV_FIXED4_ROOT/configs/review_output.schema.json"

PYTHONPATH=src python3 -m magov.eval_cli materialize \
  evals/pilot_manifest.json python-pr-07 \
  "$MAGOV_FIXED1_ROOT/workspace" \
  --workspace . \
  --review-instructions evals/adaptive-review-prompt.txt

PYTHONPATH=src python3 -m magov.eval_cli materialize \
  evals/pilot_manifest.json python-pr-07 \
  "$MAGOV_ADAPTIVE_ROOT/workspace" \
  --workspace . \
  --review-instructions evals/adaptive-review-prompt.txt

PYTHONPATH=src python3 -m magov.eval_cli materialize \
  evals/pilot_manifest.json python-pr-07 \
  "$MAGOV_FIXED4_ROOT/workspace" \
  --workspace . \
  --review-instructions evals/adaptive-review-prompt.txt
```

对三个目录分别执行 `magov-eval leak-scan`。扫描报告必须写在 workspace
外部：

```bash
PYTHONPATH=src python3 -m magov.eval_cli leak-scan \
  evals/pilot_manifest.json python-pr-07 "$MAGOV_FIXED1_ROOT/workspace" \
  --workspace . --provenance evals/historical_provenance.json \
  > "$MAGOV_FIXED1_ROOT/reports/leak-scan.json"

PYTHONPATH=src python3 -m magov.eval_cli leak-scan \
  evals/pilot_manifest.json python-pr-07 "$MAGOV_ADAPTIVE_ROOT/workspace" \
  --workspace . --provenance evals/historical_provenance.json \
  > "$MAGOV_ADAPTIVE_ROOT/reports/leak-scan.json"

PYTHONPATH=src python3 -m magov.eval_cli leak-scan \
  evals/pilot_manifest.json python-pr-07 "$MAGOV_FIXED4_ROOT/workspace" \
  --workspace . --provenance evals/historical_provenance.json \
  > "$MAGOV_FIXED4_ROOT/reports/leak-scan.json"
```

## 生成三组真实配置

```bash
PYTHONPATH=src python3 -m magov.eval_cli fixed-config \
  evals/pilot_manifest.json python-pr-07 \
  "$MAGOV_FIXED1_ROOT/workspace" \
  --exact-total-agents 1 \
  --model-id gpt-5.6-sol \
  --prompt-version python-review-v2 \
  --prompt-template evals/adaptive-review-prompt.txt \
  --output-schema "$MAGOV_FIXED1_ROOT/configs/review_output.schema.json" \
  --artifacts-directory "$MAGOV_FIXED1_ROOT/artifacts" \
  --max-total-tokens 500000 \
  > "$MAGOV_FIXED1_ROOT/configs/real.json"

PYTHONPATH=src python3 -m magov.eval_cli adaptive-config \
  evals/pilot_manifest.json python-pr-07 \
  "$MAGOV_ADAPTIVE_ROOT/workspace" \
  --model-id gpt-5.6-sol \
  --prompt-version python-review-v2 \
  --policy-version pilot-v1 \
  --max-agents 4 \
  --prompt-template evals/adaptive-review-prompt.txt \
  --output-schema "$MAGOV_ADAPTIVE_ROOT/configs/review_output.schema.json" \
  --artifacts-directory "$MAGOV_ADAPTIVE_ROOT/artifacts" \
  > "$MAGOV_ADAPTIVE_ROOT/configs/real.json"

PYTHONPATH=src python3 -m magov.eval_cli fixed-config \
  evals/pilot_manifest.json python-pr-07 \
  "$MAGOV_FIXED4_ROOT/workspace" \
  --exact-total-agents 4 \
  --model-id gpt-5.6-sol \
  --prompt-version python-review-v2 \
  --prompt-template evals/adaptive-review-prompt.txt \
  --output-schema "$MAGOV_FIXED4_ROOT/configs/review_output.schema.json" \
  --artifacts-directory "$MAGOV_FIXED4_ROOT/artifacts" \
  --max-total-tokens 2000000 \
  > "$MAGOV_FIXED4_ROOT/configs/real.json"
```

## 真实运行命令

只有用户再次明确确认后，才按下面顺序执行：

```bash
PYTHONPATH=src python3 -m magov.eval_cli fixed-run \
  "$MAGOV_FIXED1_ROOT/configs/real.json" \
  > "$MAGOV_FIXED1_ROOT/reports/real.report.json"

PYTHONPATH=src python3 -m magov.cli run \
  "$MAGOV_ADAPTIVE_ROOT/configs/real.json" \
  --events "$MAGOV_ADAPTIVE_ROOT/reports/real.events.jsonl" \
  > "$MAGOV_ADAPTIVE_ROOT/reports/real.report.json"

PYTHONPATH=src python3 -m magov.eval_cli fixed-run \
  "$MAGOV_FIXED4_ROOT/configs/real.json" \
  > "$MAGOV_FIXED4_ROOT/reports/real.report.json"
```

## 查询、中断与恢复

- 查询运行中已写出的 adaptive checkpoint 和扩容／停止理由：

  ```bash
  PYTHONPATH=src python3 -m magov.cli replay \
    "$MAGOV_ADAPTIVE_ROOT/reports/real.events.jsonl"
  ```

- 查询已完成报告的 Agent 数、总 Token、工具调用和停止理由：

  ```bash
  PYTHONPATH=src python3 -m magov.cli report \
    "$MAGOV_FIXED1_ROOT/reports/real.report.json" \
    "$MAGOV_ADAPTIVE_ROOT/reports/real.report.json" \
    "$MAGOV_FIXED4_ROOT/reports/real.report.json"
  ```

- 查询单个 Codex JSONL 的 input、cached input、output、reasoning、总 Token
  和工具调用：

  ```bash
  PYTHONPATH=src python3 -m magov.eval_cli codex-usage \
    "/tmp/magov-python-pr-07-ARM/artifacts/TRACE.jsonl" \
    --wall-time-seconds SECONDS
  ```

- 中断时向前台进程发送 `Ctrl-C`。保留已写出的 config、artifact、report
  和 adaptive event log，不复用非空 event log，不把部分结果算作完成。
- `magov replay` 只恢复审计状态，不会重新启动 Agent。当前版本的安全恢复
  方法是：确认该组为 `incomplete`，创建新的独立 workspace、artifacts
  和 event 文件，从该组第一个 Agent 重新运行；不得把中断前回答注入新组。

## 隔离评分与比较

三个真实运行全部成功结束前，不得执行本节。评分层此时才可读取
`truth.json` 和 `hidden_test.py`。

若 outcome 出现 `pending_findings`，先按既有盲审协议生成对应
`adjudications.json`，再用 `--adjudications FILE` 重跑该 outcome；在所有
pending finding 解决前，不得把 `false_positive_share: null` 解释为零误报。

```bash
PYTHONPATH=src python3 -m magov.eval_cli fixed-outcome \
  "$MAGOV_FIXED1_ROOT/configs/real.json" \
  "$MAGOV_FIXED1_ROOT/reports/real.report.json" \
  evals/tasks/python-pr-07/truth.json \
  > "$MAGOV_FIXED1_ROOT/outcomes/real.json"

PYTHONPATH=src python3 -m magov.eval_cli adaptive-outcome \
  "$MAGOV_ADAPTIVE_ROOT/configs/real.json" \
  "$MAGOV_ADAPTIVE_ROOT/reports/real.report.json" \
  evals/tasks/python-pr-07/truth.json \
  > "$MAGOV_ADAPTIVE_ROOT/outcomes/real.json"

PYTHONPATH=src python3 -m magov.eval_cli fixed-outcome \
  "$MAGOV_FIXED4_ROOT/configs/real.json" \
  "$MAGOV_FIXED4_ROOT/reports/real.report.json" \
  evals/tasks/python-pr-07/truth.json \
  > "$MAGOV_FIXED4_ROOT/outcomes/real.json"

jq -c . \
  "$MAGOV_FIXED1_ROOT/outcomes/real.json" \
  "$MAGOV_FIXED4_ROOT/outcomes/real.json" \
  > "$MAGOV_COMPARE_ROOT/fixed.real.jsonl"
jq -c . "$MAGOV_ADAPTIVE_ROOT/outcomes/real.json" \
  > "$MAGOV_COMPARE_ROOT/adaptive.real.jsonl"

PYTHONPATH=src python3 -m magov.eval_cli compare \
  "$MAGOV_COMPARE_ROOT/fixed.real.jsonl" \
  "$MAGOV_COMPARE_ROOT/adaptive.real.jsonl" \
  --reference-agents 4 \
  > "$MAGOV_COMPARE_ROOT/comparison.real.json"
```

比较输出必须同时列出 serious 与总召回、是否找到全部登记缺陷、误报、
input/cached input/output/reasoning/总 Token、工具调用、Agent 数、Agent
累计时间与墙钟时间。无论数字如何，最终边界固定为：

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

scripted dry-run 只验证控制流、checkpoint、用量汇总和比较格式，必须显式
标记为 scripted，不得作为真实实验 outcome 或效果证据。
