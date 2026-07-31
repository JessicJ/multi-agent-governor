# Multi-Agent Governor

[中文说明](README.md) · English

Multi-Agent Governor is an explainable budget controller for homogeneous
Agents. It starts with one measured Agent, admits another only when observable
evidence justifies the marginal cost, and stops at a verified target, an
observed plateau, or a hard safety boundary.

It does **not** guess a universally correct Agent count. `max_agents` is a
safety cap, not a claim that the cap is sufficient. If the cap is reached
before the process contract is complete, the run returns
`cap_reached_incomplete`.

The project provides:

- `plan`: advisory scaling and topology decisions from measured input;
- `run`: an executable baseline-first controller with replayable checkpoints;
- a safe Codex CLI adapter for isolated, read-only structured code review;
- deterministic scripted runtimes for tests and demonstrations;
- fixed-count and adaptive evaluation arms with truth isolated until scoring.

## Status

The project is experimental `0.2.x` software. The runtime and accounting loop
are implemented and tested, but public historical pilot tasks do not prove
general effectiveness. Published pilot outputs remain:

```text
status: descriptive_only
claim_allowed: false
engineering_result: inconclusive
```

See [the product goal](docs/product-goal.md) and
[open source readiness checklist](docs/open-source-readiness.md). The completed
seven-task descriptive batch report is in
[evals/results/pilot-v2-validation-20260731](evals/results/pilot-v2-validation-20260731/).

## Requirements and installation

- Python 3.10 or newer
- no third-party runtime dependency for the core package
- Codex CLI only when using the real `codex-cli` review runtime

```bash
git clone https://github.com/JessicJ/multi-agent-governor.git
cd multi-agent-governor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

## Quick start

Advisory planning:

```bash
magov plan examples/research_task.json
magov plan examples/coupled_task.json
```

Deterministic end-to-end execution without a model call:

```bash
magov run examples/runtime_review_scripted_v2.json \
  --events /tmp/magov-demo.events.jsonl
magov replay /tmp/magov-demo.events.jsonl
```

Real structured review uses an isolated configuration based on
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

## Codex plugin

The repository includes a Codex plugin and Skill:

```bash
python -m pip install .
codex plugin marketplace add "$PWD"
codex plugin add multi-agent-governor@multi-agent-governor
```

Start a new Codex task after installation, then ask:

```text
Use $multi-agent-governor to start with one measured Agent, decide whether
another is justified, and stop when verified marginal value is too low.
```

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
