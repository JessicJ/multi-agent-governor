# Contributing to Multi-Agent Governor

Thank you for helping improve Multi-Agent Governor. The project welcomes bug
reports, documentation corrections, evaluation tasks, and focused code
changes.

## Before you start

- Use GitHub Issues for bugs and proposed behavior changes.
- Keep pull requests focused on one problem.
- Do not include credentials, private source code, proprietary traces, or
  personal data in issues, fixtures, or test artifacts.
- Report vulnerabilities through the private process in
  [SECURITY.md](SECURITY.md), not a public issue.

## Development setup

The core package supports Python 3.10 and newer and has no runtime
dependencies.

```bash
git clone https://github.com/JessicJ/multi-agent-governor.git
cd multi-agent-governor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the required checks:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m magov.eval_cli validate \
  evals/pilot_manifest.json --workspace .
python -m compileall -q src tests \
  plugins/multi-agent-governor/skills/multi-agent-governor/scripts
git diff --check
```

For a deterministic end-to-end smoke test that does not call a model:

```bash
PYTHONPATH=src python -m magov.cli run \
  examples/runtime_review_scripted_v2.json \
  --events /tmp/magov-contributor.events.jsonl
```

## Evaluation integrity

Evaluation changes need extra care:

- historical tasks must identify the upstream repository, license, fix commit,
  original buggy revision, and patch hash;
- `change.diff` must reconstruct the registered historical revision rather
  than inventing a more convenient defect;
- Agent workspaces must not contain truth cards, hidden tests, provenance,
  prior traces, or Git history;
- scripted dry-runs must remain visibly marked as non-real;
- real run conditions must not be changed after seeing an earlier arm;
- results from public historical tasks are descriptive engineering evidence,
  not proof of general effectiveness.

Never edit a task's hidden truth to make a policy look better. If a truth card
is wrong, explain the correction and invalidate affected comparisons.

## Pull requests

A pull request should include:

- the problem and intended behavior;
- tests for changed behavior;
- documentation or changelog updates when user-visible behavior changes;
- exact validation commands and results;
- any compatibility, security, evaluation-integrity, or token-cost impact.

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
