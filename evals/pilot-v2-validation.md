# pilot-v2 真实历史验证批次

本批次用于检验 `pilot-v2` 在未参与策略开发的真实历史任务上的工程行为。
它不使用 synthetic 任务，也不会把 `python-pr-07` 重复计为未见数据。
机器可读冻结配置见
[`pilot-v2-validation.json`](pilot-v2-validation.json)。

## 固定任务

按编号顺序使用全部剩余历史任务：

1. `python-pr-01`：`pallets/click`
2. `python-pr-02`：`pallets/click`
3. `python-pr-03`：`more-itertools/more-itertools`
4. `python-pr-04`：`more-itertools/more-itertools`
5. `python-pr-05`：`python-attrs/attrs`
6. `python-pr-06`：`python-attrs/attrs`
7. `python-pr-08`：`pytest-dev/pluggy`

`python-pr-07` 是 `pilot-v2` 的开发和校准任务。`python-pr-09` 至
`python-pr-12` 是 synthetic 工程 fixture。两类任务都不进入本批次。
选择全部七个剩余历史任务，避免根据项目、严重度或预期难度挑选结果。

这些任务的 `change.diff` 均逐字节等于从真实上游修复提交到其直接父提交
所生成的生产代码反向 diff。Agent 目录直接物化该父提交，不从修复提交
反向应用补丁，因此不会保留修复提交新增或修改的测试、changelog、提交
说明和 Git 历史。若原始 diff 含 Issue、PR 或修复提示，只有 Agent 可见
副本会替换这些提示；登记补丁、代码变化和缺陷状态保持不变。触发测试
保存在评分侧，并已验证 fixed 通过、buggy 失败。

## 固定条件

- 重复：每个任务一次；
- 模型：`gpt-5.6-sol`，禁止替换；
- 提示词：`python-review-v2`；
- 自适应策略：`pilot-v2`；
- sandbox：`read-only`；
- 用户配置：关闭；
- Codex 原生 multi-agent：关闭；
- 每个任务、每个 arm 使用独立目录；
- arm 之间不共享输出、trace、checkpoint 或 artifacts；
- 聚合只使用确定性 JSON 聚合器；
- Agent 运行期间不得读取真值、隐藏测试、provenance、manifest、其他
  arm 输出或 Governor 仓库。

对每个任务按以下 arm 顺序运行，然后再进入下一个任务：

1. `fixed-1`
2. `adaptive-max-4`
3. `fixed-4`

所有任务的提示词、预算、信号和 Agent 规则在首个真实运行前冻结。不得
根据较早任务或 arm 的结果修改后续运行。任一 arm 出现泄漏、运行故障、
超时或安全上限停止时，将该 arm 标为 `incomplete` 并暂停真实批次。

## Agent 与资源上限

| arm | Agent 规则 | Token 上限 | 累计 Agent 时间 | 工具调用 |
|---|---:|---:|---:|---:|
| fixed-1 | 精确 1 | 300,000 | 1,200 秒 | 100 |
| adaptive-max-4 | 从 1 开始，最多 4 | 600,000 | 3,600 秒 | 200 |
| fixed-4 | 精确 4 | 1,200,000 | 3,600 秒 | 400 |

单 Agent 超时固定为 900 秒。七个任务预计总消耗 3.5M–7.0M Token，
三臂累计硬上限为 14.7M Token。由于 `codex exec` 没有单次调用内的
Token 截断，控制器只能在 Agent 返回后的 checkpoint 强制累计上限；
900 秒超时用于限制该窗口。

`adaptive-max-4` 必须从一个 Agent 开始。`pilot-v2` 将独立重复审查视为
第二个可分离审查单元，因此预算允许时，单文件任务也至少运行两个相互
独立的 Agent。第二个 Agent 后是否继续扩容，只能依据预先登记的过程覆盖、
冲突、非真值证据新颖性、成本和硬预算规则。每次扩容或停止理由必须写入
checkpoint、event log 和 decision receipt。

## 物化与无模型预检

预检根目录固定为：

```text
/tmp/magov-pilot-v2-validation-preflight-20260730-v2/
```

每个任务下创建 `fixed-1/workspace`、`adaptive-max-4/workspace` 和
`fixed-4/workspace`。可以先使用现有 `magov-eval materialize` 创建一个
无 `.git`、无真值的 seed，再复制为三个独立目录；复制后必须分别运行
`magov-eval leak-scan`，扫描报告写在 workspace 外部。

真实配置必须使用现有命令生成：

```bash
PYTHONPATH=src python3 -m magov.eval_cli fixed-config \
  evals/pilot_manifest.json TASK_ID ARM_WORKSPACE \
  --exact-total-agents 1 \
  --model-id gpt-5.6-sol \
  --prompt-version python-review-v2 \
  --prompt-template evals/adaptive-review-prompt.txt \
  --output-schema ARM_CONFIG/review_output.schema.json \
  --artifacts-directory ARM_ARTIFACTS \
  --max-total-tokens 300000 \
  --max-wall-time-seconds 1200 \
  --max-tool-calls 100

PYTHONPATH=src python3 -m magov.eval_cli adaptive-config \
  evals/pilot_manifest.json TASK_ID ARM_WORKSPACE \
  --model-id gpt-5.6-sol \
  --prompt-version python-review-v2 \
  --policy-version pilot-v2 \
  --max-agents 4 \
  --prompt-template evals/adaptive-review-prompt.txt \
  --output-schema ARM_CONFIG/review_output.schema.json \
  --artifacts-directory ARM_ARTIFACTS \
  --max-total-tokens 600000 \
  --max-wall-time-seconds 3600 \
  --max-tool-calls 200

PYTHONPATH=src python3 -m magov.eval_cli fixed-config \
  evals/pilot_manifest.json TASK_ID ARM_WORKSPACE \
  --exact-total-agents 4 \
  --model-id gpt-5.6-sol \
  --prompt-version python-review-v2 \
  --prompt-template evals/adaptive-review-prompt.txt \
  --output-schema ARM_CONFIG/review_output.schema.json \
  --artifacts-directory ARM_ARTIFACTS \
  --max-total-tokens 1200000 \
  --max-wall-time-seconds 3600 \
  --max-tool-calls 400
```

生成后的三个 arm 配置必须与机器可读冻结配置一致；真实运行前必须执行
自动一致性检查，不允许人工修改。

只有用户再次明确确认后，才对当前任务按固定 arm 顺序执行：

```bash
PYTHONPATH=src python3 -m magov.eval_cli fixed-run \
  TASK_ROOT/fixed-1/configs/real.json \
  > TASK_ROOT/fixed-1/reports/real.report.json

PYTHONPATH=src python3 -m magov.cli run \
  TASK_ROOT/adaptive-max-4/configs/real.json \
  --events TASK_ROOT/adaptive-max-4/reports/real.events.jsonl \
  > TASK_ROOT/adaptive-max-4/reports/real.report.json

PYTHONPATH=src python3 -m magov.eval_cli fixed-run \
  TASK_ROOT/fixed-4/configs/real.json \
  > TASK_ROOT/fixed-4/reports/real.report.json
```

查询 adaptive checkpoint、Agent 数、停止原因和累计用量：

```bash
PYTHONPATH=src python3 -m magov.cli replay \
  TASK_ROOT/adaptive-max-4/reports/real.events.jsonl

PYTHONPATH=src python3 -m magov.cli report \
  TASK_ROOT/fixed-1/reports/real.report.json \
  TASK_ROOT/adaptive-max-4/reports/real.report.json \
  TASK_ROOT/fixed-4/reports/real.report.json
```

中断时向前台进程发送 `Ctrl-C`。保留已写出的 config、artifact、report 和
event log，将该 arm 标记为 `incomplete`。`replay` 只恢复审计状态，不会
续跑 Agent；安全恢复必须使用新的独立 workspace、artifacts 和 event
文件，从该 arm 的第一个 Agent 重新开始。

本阶段只执行 manifest、来源、补丁、触发测试、物化、泄漏、scripted、
checkpoint、usage、compare、单元测试、compileall、diff 和 Plugin/Skill
校验。没有用户再次明确确认，不启动任何真实 `codex exec`。

生成 scripted 配置时在同一条 `fixed-config` 或 `adaptive-config` 命令末尾
增加 `--scripted-dry-run`。该选项把 runtime 替换为确定性 fixture，并
强制写入：

```json
{
  "dry_run": {
    "scripted": true,
    "real_experiment": false
  }
}
```

scripted 报告和 outcome 不得改名或冒充真实结果。

## 已完成的无模型预检

2026-07-30 的预检结果：
机器可读摘要见
[`pilot-v2-preflight-20260730.json`](pilot-v2-preflight-20260730.json)；
完整本地 artifacts 位于被 Git 忽略的
`evals/runs/pilot-v2-preflight-20260730/`。

- 七个修复提交的直接父提交均等于登记的原始缺陷 revision；
- 七个 `change.diff` 均与上游 `git diff FIX BUGGY -- CHANGED_FILES`
  逐字节一致，SHA-256 与 manifest 一致；
- 七个隔离触发测试在 fixed revision 全部通过，在 buggy revision 全部
  失败；
- 七个 buggy revision 各有一个与缺陷无关的公开 smoke test 通过；
- `python-pr-01` 和 `python-pr-08` 的首次泄漏扫描准确拦截了 Agent diff
  中的 Issue 提示；物化器修正后分别替换 2 处提示；
- 7 个任务 × 3 个 arm，共 21 个独立目录全部通过最终泄漏扫描；
- 21 份冻结真实配置通过模型、提示词、sandbox、预算、路径和版本一致性
  检查；
- 21 个 scripted arm 全部完成：fixed-1 均为 1 个 Agent，adaptive 均为
  2 个 Agent，fixed-4 均为 4 个 Agent；
- adaptive 首个 checkpoint 的独立覆盖均不完整，第二个 Agent 后均以
  `target_reached` 停止；
- compare dry-run 配对 7 个任务，并保持
  `descriptive_only / claim_allowed:false / inconclusive`；
- scripted 质量数据只验证评分格式，不是缺陷发现证据。

多任务 dry-run 还发现并修复了 serious recall 的宏平均错误：没有 serious
缺陷的任务不再按 100% 计入均值。跨任务 serious 与 total recall 现在按
登记缺陷总数做 micro aggregation。

## 评分与结论

只有同一任务三个 arm 全部结束后，评分层才能读取该任务的 `truth.json`
和 `hidden_test.py`。跨任务汇总必须同时报告 serious 与总召回、全部登记
缺陷命中、误报、各类 Token、工具调用、Agent 数、累计 Agent 时间和墙钟
时间。

本批次使用仓库公开但运行时隔离的任务，且每个任务只有一次重复。无论
数字如何，结论固定为：

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```
