# Multi-Agent Governor

[English README](README.en.md) · 中文说明

[![CI](https://github.com/JessicJ/multi-agent-governor/actions/workflows/ci.yml/badge.svg)](https://github.com/JessicJ/multi-agent-governor/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **让多 Agent 从“凭感觉堆数量”，变成“按证据逐个准入”。**

Multi-Agent Governor 是面向 Codex 和 Agent 工作流的预算控制与决策审计
插件。它先运行一个可测量的基线 Agent，再根据覆盖、独立复核、冲突、
新增证据和实际资源消耗，判断下一个同构 Agent 是否仍值得加入。

**Start with one. Scale with evidence. Stop with a reason.**

## 为什么使用 Governor

- **先小后大**：默认从一个 Agent 开始，不必在任务开始前拍脑袋选择数量。
- **逐个准入**：每个 checkpoint 最多增加一个 Agent，并记录扩容或停止理由。
- **预算可控**：Agent 数、Token、墙钟时间和工具调用都有硬上限。
- **过程可审计**：事件日志和决策收据可以确定性重放；未知用量明确保留为
  `null`，不拿估算冒充实测。
- **协作方式可选**：根据任务耦合度选择中心协调或相互独立的同构 Agent。
- **真值隔离**：评测模式把隐藏答案与 Agent 工作区分开，防止“看过答案”
  的结果被当成能力提升。

Governor 关注的不是“多 Agent 听起来更强”，而是三个可以检查的问题：

| 问题 | Governor 的处理方式 |
|---|---|
| 要不要从 1 个 Agent 扩容？ | 先测基线，再检查新增 Agent 的预期边际价值 |
| 应如何协作？ | 在集中协调与独立执行之间选择，并显式计入协调成本 |
| 什么时候停止？ | 达到公开验证目标、观察到平台期，或触及安全预算时停止 |

## 安装与使用

推荐使用仓库内的
[`multi-agent-governor` Codex 插件](plugins/multi-agent-governor/.codex-plugin/plugin.json)。
克隆仓库后运行：

```bash
git clone https://github.com/JessicJ/multi-agent-governor.git
cd multi-agent-governor
python3 -m pip install .
codex plugin marketplace add "$PWD"
codex plugin add multi-agent-governor@multi-agent-governor
```

新建一个 Codex 任务，然后直接说：

```text
Use $multi-agent-governor to start with one measured Agent, decide whether
another is justified, and stop when verified marginal value is too low.
```

Governor 会先给出可解释的 Agent 预算和协作建议。只有当你明确要求执行
受支持的结构化代码审查时，`run` 模式才会实际控制 Agent 的逐个准入。

也可以不安装插件，直接体验零第三方运行时依赖的 Python CLI：

```bash
PYTHONPATH=src python3 -m magov.cli plan examples/research_task.json
```

## 三种使用方式

| 模式 | 适合场景 | Governor 是否控制 Agent Runtime |
|---|---|---:|
| `plan` | 在执行前估算是否值得使用多 Agent，以及选择何种拓扑 | 否 |
| `advisory` | 外部或 Codex 原生 Agent 已在运行，需要可回放 checkpoint 和收据 | 否 |
| `run` | 受支持的结构化代码审查，需要实际执行预算与停止规则 | 是 |

`plan` 是建议层，`advisory` 是外部运行的飞行记录仪，`run` 才是执行
控制器。这三层共享同一套“基线 → 验证 → 准入或停止”的治理逻辑，但不会
混淆“建议过”与“实际控制过”。

## 决策闭环

```text
任务 → Controller → 单 Agent 基线 → 外部验证 → Governor
           ↑                                  ↓
           └── 聚合 ← 新 Agent ← 准入 / 停止 ─┘
```

Governor 先用硬门槛排除明显不适合多 Agent 的任务，再估计新增 Agent 的
边际质量收益、延迟收益、成本、协调压力和错误传播风险。只有净边际效用
超过阈值，才允许增加下一个 Agent。

## 可复现演示

项目需要 Python 3.10+。下面的 scripted runtime 不调用真实模型，可以
安全演示 baseline、扩容、验证、提前停止和事件重放：

```bash
PYTHONPATH=src python3 -m magov.cli run \
  examples/runtime_review_scripted_v2.json \
  --events /tmp/magov-demo.events.jsonl
PYTHONPATH=src python3 -m magov.cli replay /tmp/magov-demo.events.jsonl
```

为外部 Agent 会话生成追加式收据：

```bash
PYTHONPATH=src python3 -m magov.cli advisory start \
  examples/advisory_session_start.json \
  --events /tmp/magov-advisory.events.jsonl
PYTHONPATH=src python3 -m magov.cli advisory checkpoint \
  /tmp/magov-advisory.events.jsonl \
  examples/advisory_checkpoint_agent_2.json
PYTHONPATH=src python3 -m magov.cli advisory report \
  /tmp/magov-advisory.events.jsonl
```

完整命令和语义见
[`docs/advisory-sessions.md`](docs/advisory-sessions.md)。所有 scripted 配置
都会携带 `dry_run: {"scripted": true, "real_experiment": false}`，防止演示
结果被误当成真实实验。

## 项目状态与边界

当前 Skill、策略与 Codex CLI Runtime 为实验性 `0.2.x` 软件。控制闭环、
预算、隔离、收据和重放已经实现并有自动化测试；公开历史任务验证仍属于
描述性工程验证，不构成“多 Agent 在所有项目上更好或更省”的普遍结论。

Governor 也不会猜测一个普遍正确的 Agent 数量。`max_agents` 是安全上限，
不是“这个数量一定足够”的承诺；若到达上限时公开过程验证仍不完整，运行
必须返回 `cap_reached_incomplete`。

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

这项边界不影响它作为预算控制、过程审计和实验基础设施使用。完整产品
目标见 [`docs/product-goal.md`](docs/product-goal.md)，组件关系与信任边界
见 [`docs/architecture.md`](docs/architecture.md)。

## 实际执行：结构化代码审查

第一种可执行场景限定为只读代码审查。运行 JSON 必须声明：

- 精确的 `policy.version`，当前支持 `pilot-v1` 和开发中的 `pilot-v2`；
- 隔离的 Agent 工作目录；
- 固定审查提示词与结构化输出 schema；
- 变更文件与至少需要双重检查的高风险文件；
- 结构信号、Agent 上限、Token、耗时和工具调用预算；
- `codex-cli` 或仅用于测试的 `scripted` runtime。

无模型示意配置见 [`runtime_review_scripted.json`](examples/runtime_review_scripted.json)，真实 Codex 配置模板见 [`runtime_review_codex.template.json`](examples/runtime_review_codex.template.json)，结构化输出约束见 [`review_output.schema.json`](examples/review_output.schema.json)。真实 Codex 运行使用：

```bash
magov run RUN.json --events RUN.events.jsonl > RUN.report.json
magov replay RUN.events.jsonl
magov report RUN.report.json
```

控制器会执行以下闭环：

1. 启动一个全新 baseline Agent；
2. 使用外部过程证据评估变更文件覆盖、高风险文件独立复核、冲突和结构化发现；
3. 计算初始扩容预测；
4. 每次只启动一个额外 Agent；
5. 每轮重新聚合、验证、记录真实 Token/耗时/工具调用；
6. `pilot-v2` 把初始计划数量视为预测，并依据实时证据继续逐个扩容，
   直到质量目标、边际收益平台期、用户 Agent 安全上限、成本、Token、
   耗时或工具预算触发停止；
7. 输出可回放事件日志和决策收据。

预算或 runtime 故障返回 `incomplete`。到达用户 Agent 上限但公开 verifier
仍不完整时返回 `cap_reached_incomplete`；这是上限截断，不是“已找到
足够 Agent”的结论。

`pilot-v1` 保留首次真实实验的原始行为。开发中的 `pilot-v2` 对未被外部
verifier 证明、具有至少两个可分离审查单元且采用独立拓扑的审查，要求
停止前至少完成一次独立复核；代码审查 bridge 把独立重复审查计为第二个
审查单元，因此单文件变更也适用。changed-file 独立复核同时纳入过程覆盖。
如果实时边际证据仍为正，`pilot-v2` 可以超过初始预测继续扩容，但绝不
突破用户安全上限。
完整冻结规则见 [`evals/pilot-v2.md`](evals/pilot-v2.md)。这仍是开发规则，
不是效果声明。

冻结的七任务真实历史验证已按
[`evals/pilot-v2-validation.md`](evals/pilot-v2-validation.md) 完成：
使用除开发任务 `python-pr-07` 外的全部七个历史任务、一次重复和相同三臂
顺序。确定性批次汇总见
[`evals/results/pilot-v2-validation-20260731/`](evals/results/pilot-v2-validation-20260731/)。
该批次描述了运行时隔离、停止与成本行为，但任务公开、重复数为一且没有
独立盲审，因此仍是 `descriptive_only / claim_allowed:false /
inconclusive`，不能证明 Governor 对未见项目普遍有效。

Codex JSONL 和最终消息默认写入 Agent 工作目录之外的临时目录。适配器
显式关闭单次 Codex 进程内部的原生多 Agent 工具，拒绝
`danger-full-access` 和运行参数覆盖。若显式指定
`artifacts_directory`，它也必须位于 Agent 工作目录之外。

## 输入信号

所有比例信号均为 `0..1`。信号可以来自规则、任务分析模型、人工标注或历史遥测；Governor 本身不绑定任何生成方式。

| 信号 | 含义 | 值高时的影响 |
|---|---|---|
| `parallelizable_units` | 可独立处理的工作单元数 | 提高可扩展上限 |
| `parallel_fraction` | 可并行工作占比 | 增加并行收益 |
| `decomposition_confidence` | 对任务拆分正确性的把握 | 增加覆盖收益 |
| `context_coupling` | 子任务对共享、动态上下文的依赖 | 增加协调成本 |
| `shared_context_ratio` | 每个 Agent 都要重复携带的上下文 | 增加 token/成本 |
| `uncertainty` | 基线结果仍有多少不确定性 | 增加复核价值 |
| `verification_value` | 独立尝试发现错误的能力 | 增加正确率收益 |
| `failure_correlation` | 不同 Agent 犯同一错误的概率 | 降低复核价值 |
| `aggregation_difficulty` | 合并输出的难度 | 增加协调成本 |
| `error_impact` | 错误一旦传播的损失 | 倾向中心协调或单 Agent |

单 Agent 基线至少提供：

- `confidence`：经过校准的成功概率或外部 verifier 分数；
- `verified`：是否已通过确定性测试、规则或人工验证；
- `hard_failure`：基线未产生可用结果；此时 `confidence` 必须为 `0`，且
  `verified` 必须为 `false`；
- `cost_units`：基线成本，用作后续成本归一化；
- `latency_seconds`：基线延迟。

不要直接使用模型自报的“我有 95% 把握”。生产环境应优先采用测试通过率、judge 校准分数、检索证据覆盖率、历史同类任务成功率等外部信号。

## 两种多 Agent 拓扑

- `independent`：低上下文耦合，Agent 隔离工作，最后聚合。它保留观点和错误的多样性，适合独立研究、候选方案、交叉验证。
- `centralized`：存在共享约束、输出必须一致，或错误影响较高。由一个协调者分配有边界的子任务并做最终合并。

如果任务不可真实并行、协调压力过高、错误高度相关，或基线已经足够好，结果为 `single`。

## 接入现有 Agent runtime

`GovernorSession` 保留为兼容的纯建议 API：

```python
from magov import BaselineObservation, GovernorSession, TaskSignals

session = GovernorSession(
    baseline_runner=lambda task: BaselineObservation(
        confidence=run_one_agent_and_score(task),
        verified=False,
        cost_units=1.0,
    ),
    signal_provider=lambda task, baseline: TaskSignals(
        parallelizable_units=4,
        parallel_fraction=0.8,
        decomposition_confidence=0.9,
        context_coupling=0.25,
        shared_context_ratio=0.3,
        uncertainty=1 - baseline.confidence,
        verification_value=0.85,
        failure_correlation=0.2,
        aggregation_difficulty=0.35,
        error_impact=0.6,
    ),
)

baseline, plan = session.plan(task)
```

你的 runtime 根据 `plan.mode` 和 `plan.total_agents` 执行。每增加一个 Agent 后，将真实的质量增量、新发现比例和成本传给 `review_scaling(...)`；达到质量目标、预算上限、计划上限或连续边际收益平台期时立即停止。

需要 Governor 实际拥有准入权限时，使用 `AdaptiveController`：

```python
from magov import (
    AdaptiveController,
    Budget,
    ExecutionTask,
    JsonFindingsAggregator,
    ReviewEvidenceVerifier,
)
from magov.adapters import CodexCliRuntime, CodexCliRuntimeConfig

controller = AdaptiveController(
    runtime=CodexCliRuntime(
        CodexCliRuntimeConfig(
            sandbox="read-only",
            output_schema=review_schema_path,
            artifacts_directory=artifacts_outside_agent_workspace,
        )
    ),
    aggregator=JsonFindingsAggregator(),
    verifier=ReviewEvidenceVerifier(),
)

report = controller.execute(
    ExecutionTask(
        task_id="review-001",
        prompt=fixed_review_prompt,
        working_directory=isolated_task_directory,
        signals=task_signals,
        metadata={
            "changed_files": changed_files,
            "high_risk_files": high_risk_files,
        },
    ),
    Budget(max_agents=4, max_total_tokens=500_000),
)
```

`AgentRuntime`、`Aggregator` 和 `Verifier` 都是小型 Protocol。其他平台可以实现自己的适配器，而不必改动策略。

`total_agents` 表示包括原始 baseline 在内的 Agent 执行总数。纯建议模式的
`centralized` 表示需要中心协调；当前可执行代码审查模式由确定性 JSON
聚合器承担协调，不额外调用一个 coordinator Agent。其他 runtime 若必须
启用独立 coordinator，应把它计入 Agent 数与真实用量。

## 当前策略的边界

这是可执行的策略基线，不是已经证明最优的通用公式。当前代码审查 verifier 证明的是过程覆盖，不是代码无缺陷。默认权重的作用是建立可观测、可回放的决策闭环。生产校准建议记录：

- 输入信号与最终计划；
- 每个 Agent 的实际成本、延迟和边际新发现；
- 最终任务是否成功以及外部 verifier 得分；
- 如果坚持单 Agent，是否真的比多 Agent 更差；
- 如果扩容，新增第 N 个 Agent 是否仍带来净收益。

有了这些反事实和结果数据后，可以用简单回归、bandit 或离线策略评估替换默认权重，而无需改动上层 Agent 框架。

## 证据优先的评测层

项目同时提供独立的评测试跑框架，用于回答“什么时候不该增加 Agent、什么时候停止、是否真的减少消耗且没有损害结果”。评测层与新的执行层分离：执行层不能读取真值，评分层只能在运行结束后读取真值。工程试跑仍不能被当成有效性证明。

当前协议固定为 Python PR 的只读缺陷审查：

- 8 个真实历史任务和 4 个仅用于工程测试的 synthetic fixture；
- `python-pr-07` 用于策略开发，pilot-v2 验证使用其余 7 个历史任务；
- 同模型、同工具、同提示词，依次运行 fixed-1、adaptive-max-4、fixed-4；
- 仓库公开但在 Agent 运行时隔离的工程真值卡、结构化发现和后置裁决；
- 严重缺陷召回优先，误报为硬约束；
- Token、调用、Agent 数、累计 Agent 时间和墙钟时间全部记录；
- 原始 trace 默认只保存在被 Git 忽略的本地归档，审计结果单独入库。

验证示例评分：

```bash
PYTHONPATH=src python3 -m magov.eval_cli score \
  evals/fixtures/truth.example.json \
  evals/fixtures/findings.example.json \
  --adjudications evals/fixtures/adjudications.example.json
```

任务清单和使用方法见 [`evals/README.md`](evals/README.md)，完整边界见 [`docs/evaluation-protocol.md`](docs/evaluation-protocol.md)。

8 个历史任务包含来自第三方开源项目的补丁片段。来源、适用许可证和完整许可证文本见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

在新的真正未见任务、多次重复和独立盲审完成之前，本项目只能称为
“实验性策略”，不能声称已经证明可以无损节省成本。

参与贡献前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。安全问题请遵循
[`SECURITY.md`](SECURITY.md) 私下报告；发布步骤见
[`RELEASING.md`](RELEASING.md)。

## 开发与验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m magov.eval_cli validate \
  evals/pilot_manifest.json --workspace .
python3 -m compileall -q src tests \
  plugins/multi-agent-governor/skills/multi-agent-governor/scripts
python3 tools/check_markdown_links.py .
git diff --check
```

## 许可证

Multi-Agent Governor 使用 [MIT License](LICENSE)。历史评测补丁保留各自的
上游许可证，详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 和
[`LICENSES/`](LICENSES/)。
