# Multi-Agent Governor

一个轻量、可解释的自适应控制层：先跑单 Agent 基线，只有可观察证据表明边际收益值得时才增加同构 Agent，并在收益平台期或预算耗尽时强制停止。

它不是新的通用 Agent 框架。它提供两层能力：

- `plan`：不接管执行，只回答三个治理问题；
- `run`：通过可替换的 Agent Runtime 适配器实际拥有扩容权限，每次只准入一个新 Agent，再验证和决定是否继续。

三个治理问题是：

1. 要不要从 1 个 Agent 扩到多个？
2. 应采用中心协调还是独立协作？
3. 何时停止继续增加 Agent？

## 决策闭环

```text
任务 → Controller → 单 Agent 基线 → 外部验证 → Governor
           ↑                                  ↓
           └── 聚合 ← 新 Agent ← 准入 / 停止 ─┘
```

Governor 先使用硬门槛排除明显不适合多 Agent 的任务，再逐个估计新增 Agent 的边际质量收益、延迟收益、成本、协调压力和错误传播风险。只有净边际效用超过阈值，才允许增加下一个 Agent。

## 快速运行

项目只需要 Python 3.10+，核心没有第三方依赖：

```bash
python3 --version
cd multi-agent-governor
PYTHONPATH=src python3 -m magov.cli examples/research_task.json
PYTHONPATH=src python3 -m magov.cli examples/coupled_task.json
PYTHONPATH=src python3 -m magov.cli plan examples/research_task.json
PYTHONPATH=src python3 -m magov.cli run \
  examples/runtime_review_scripted.json \
  --events /tmp/magov-demo.events.jsonl
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

旧的 `magov INPUT.json` 仍兼容，等价于 `magov plan INPUT.json`。
`runtime_review_scripted.json` 不调用模型，用固定结果演示 baseline、扩容、验证和提前停止的完整状态机。scripted 配置必须显式包含
`dry_run: {"scripted": true, "real_experiment": false}`；运行报告、outcome
和 compare 会保留该标记，防止 dry-run 被误当成真实实验。

如果版本低于 3.10，请先安装较新的 Python，再继续下面的安装步骤。

也可以安装为本地命令：

```bash
python3 -m pip install .
magov examples/research_task.json
```

## 作为 Codex 插件或 Skill 使用

仓库包含可安装的 [`multi-agent-governor` 插件](plugins/multi-agent-governor/.codex-plugin/plugin.json)，插件内部包含一个 [`multi-agent-governor` Skill](plugins/multi-agent-governor/skills/multi-agent-governor/SKILL.md)。
插件支持两种模式：普通任务默认只生成建议；用户明确要求执行结构化代码审查时，可以调用 `magov run`，由控制器通过 Codex CLI 启动隔离 Agent、记录真实用量并强制停止。目前可执行模式不适用于任意类型的软件开发任务。

推荐以插件形式安装。克隆仓库后，在仓库根目录运行：

```bash
python3 -m pip install .
codex plugin marketplace add "$PWD"
codex plugin add multi-agent-governor@multi-agent-governor
```

如果只想安装 Skill，也可以运行：

```bash
python3 -m pip install .
mkdir -p ~/.codex/skills
cp -R plugins/multi-agent-governor/skills/multi-agent-governor ~/.codex/skills/
```

安装后请新建一个 Codex 会话，再这样使用：

```text
Use $multi-agent-governor to decide whether this task should use more agents and when to stop.
```

当前 Skill、策略与 Codex CLI Runtime 均为实验性 v0.2。可执行闭环已经存在，但不代表已经证明多 Agent 在所有任务上都能无损节省成本。

## 实际执行：结构化代码审查

第一种可执行场景限定为只读代码审查。运行 JSON 必须声明：

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
3. 计算初始扩容上限；
4. 每次只启动一个额外 Agent；
5. 每轮重新聚合、验证、记录真实 Token/耗时/工具调用；
6. 在质量目标、计划上限、Agent 上限、成本、Token、耗时、工具预算或边际收益平台期停止；
7. 输出可回放事件日志和决策收据。

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

首个协议固定为 Python PR 的只读缺陷审查：

- 12 个工程试跑任务槽位，70% 左右为历史缺陷、其余为植入缺陷；
- 同模型、同工具、集中汇总；
- 恰好使用 1、2、3、4 个 Agent，每组重复 2 次；
- 最多 4 Agent、逐次准入的 Governor 自适应组，每个任务重复 2 次；
- 仓库公开但在 Agent 运行时隔离的工程真值卡、结构化发现、自动匹配和模糊案例盲审；
- 严重缺陷召回优先，误报为硬约束；
- Token、调用、耗时以及 Governor 自身开销全部记录；
- 所有运行结果默认只保存在本地。

验证示例评分：

```bash
PYTHONPATH=src python3 -m magov.eval_cli score \
  evals/fixtures/truth.example.json \
  evals/fixtures/findings.example.json \
  --adjudications evals/fixtures/adjudications.example.json
```

任务清单和使用方法见 [`evals/README.md`](evals/README.md)，完整边界见 [`docs/evaluation-protocol.md`](docs/evaluation-protocol.md)。

8 个历史任务包含来自第三方开源项目的补丁片段。来源、适用许可证和完整许可证文本见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

在另一批未参与规则制定的代码完成正式验证之前，本项目只能称为“实验性策略”，不能声称已经证明可以无损节省成本。
