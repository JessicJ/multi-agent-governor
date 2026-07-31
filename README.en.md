# Multi-Agent Governor

[中文说明](README.md) · English

[![CI](https://github.com/JessicJ/multi-agent-governor/actions/workflows/ci.yml/badge.svg)](https://github.com/JessicJ/multi-agent-governor/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **Turn multi-Agent scaling from a guess into an evidence-based decision.**

Multi-Agent Governor is a budget controller and decision recorder for Codex
and Agent workflows. It starts with one measured baseline Agent, then uses
coverage, independent review, conflicts, novel evidence, and observed resource
use to decide whether another homogeneous Agent is worth admitting.

**Start with one. Scale with evidence. Stop with a reason.**

## Why use Governor

- **Start small:** avoid choosing an arbitrary Agent count before evidence
  exists.
- **Scale one at a time:** admit at most one Agent at each checkpoint and
  record why.
- **Enforce budgets:** cap Agent count, tokens, wall time, and tool calls.
- **Keep an audit trail:** deterministically replay event logs and receipts;
  unavailable usage stays `null` instead of becoming invented precision.
- **Choose a topology:** account for task coupling when selecting centralized
  or independent homogeneous Agents.
- **Protect evaluation truth:** keep hidden answers, provenance, and prior
  traces outside Agent workspaces.

| Question | Governor's answer |
|---|---|
| Should one Agent become several? | Measure the baseline, then evaluate marginal value |
| How should they collaborate? | Choose centralized or independent execution and price in coordination |
| When should scaling stop? | Stop at a verified target, an observed plateau, or a hard budget |

## Try it in 30 seconds

Install the Codex plugin from a local clone:

- Python 3.10 or newer
- no third-party runtime dependency for the core package
- Codex CLI only when using the real `codex-cli` review runtime

```bash
git clone https://github.com/JessicJ/multi-agent-governor.git
cd multi-agent-governor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
codex plugin marketplace add "$PWD"
codex plugin add multi-agent-governor@multi-agent-governor
```

Start a new Codex task and ask:

```text
Use $multi-agent-governor to start with one measured Agent, decide whether
another is justified, and stop when verified marginal value is too low.
```

Governor will first return an explainable Agent budget and collaboration
recommendation. It controls Agent admission only when you explicitly request a
supported structured code-review run.

For a standalone CLI preview:

```bash
magov plan examples/research_task.json
```

## Three operating modes

| Mode | Best for | Controls the Agent runtime? |
|---|---|---:|
| `plan` | Preflight scaling and topology advice | No |
| `advisory` | Replayable checkpoints for native or external Agent sessions | No |
| `run` | Budget-enforced execution for supported structured code review | Yes |

`plan` is the adviser, `advisory` is the flight recorder, and `run` is the
controller. All three use the same baseline-first decision loop without
confusing advice with runtime enforcement.

## Reproducible demo

Run the complete controller and replay loop without a model call:

```bash
magov run examples/runtime_review_scripted_v2.json \
  --events /tmp/magov-demo.events.jsonl
magov replay /tmp/magov-demo.events.jsonl
```

Create an append-only receipt for externally executed Agents:

```bash
magov advisory start examples/advisory_session_start.json \
  --events /tmp/magov-advisory.events.jsonl
magov advisory checkpoint /tmp/magov-advisory.events.jsonl \
  examples/advisory_checkpoint_agent_2.json
magov advisory checkpoint /tmp/magov-advisory.events.jsonl \
  examples/advisory_checkpoint_agent_3.json
magov advisory report /tmp/magov-advisory.events.jsonl
```

All scripted fixtures carry
`dry_run: {"scripted": true, "real_experiment": false}` so demonstrations
cannot masquerade as real experiments. See
[advisory session receipts](docs/advisory-sessions.md) for the full contract.

## Project status and boundaries

Multi-Agent Governor is experimental `0.2.x` software. Its control loop,
budgets, isolation, receipts, and replay are implemented and tested. Public
historical-task results are descriptive engineering validation, not proof that
multi-Agent execution is universally better or cheaper.

It does not guess a universally correct Agent count. `max_agents` is a safety
cap, not a promise that the cap is sufficient. If the process contract is
still incomplete at the cap, the run returns `cap_reached_incomplete`.

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

That boundary does not prevent Governor from being useful as budget control,
process audit, and experiment infrastructure. See
[the product goal](docs/product-goal.md),
[architecture and trust boundaries](docs/architecture.md), and the
[open source readiness checklist](docs/open-source-readiness.md).

## Executable structured review

Real review uses an isolated configuration based on
[`examples/runtime_review_codex.template.json`](examples/runtime_review_codex.template.json):

```bash
magov run RUN.json --events RUN.events.jsonl > RUN.report.json
magov replay RUN.events.jsonl
magov report RUN.report.json
```

The controller launches one fresh baseline Agent, evaluates changed-file
coverage, independent review, conflicts, novel evidence, and actual resource
use, then admits at most one additional Agent per checkpoint.

## Safety model

- Agent workspaces must not contain truth cards, hidden tests, prior Agent
  traces, provenance, user configuration, or Git history that leaks an answer.
- JSONL traces and event logs remain outside the Agent workspace.
- Native Codex multi-Agent capability is disabled inside Governor-owned runs
  so the reported Agent count stays auditable.
- The adapter rejects unrestricted sandbox bypass flags.
- Agent, token, wall-time, and tool-call budgets are hard boundaries.
- Process coverage is not hidden-truth correctness.

See the [architecture and trust boundaries](docs/architecture.md),
[runtime control](docs/runtime-control.md), and the
[evaluation protocol](docs/evaluation-protocol.md).

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m magov.eval_cli validate \
  evals/pilot_manifest.json --workspace .
python -m compileall -q src tests \
  plugins/multi-agent-governor/skills/multi-agent-governor/scripts
python tools/check_markdown_links.py .
git diff --check
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a change. Security
reports must follow [SECURITY.md](SECURITY.md). Maintainers should follow
[RELEASING.md](RELEASING.md) for release candidates and publication.

## License

Multi-Agent Governor is licensed under the [MIT License](LICENSE). Historical
evaluation patches retain their upstream licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [LICENSES](LICENSES/).
