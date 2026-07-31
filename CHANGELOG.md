# Changelog

## Unreleased

- Complete the frozen seven-task `pilot-v2` historical validation batch and
  publish deterministic, descriptive-only results without changing the
  preregistered runtime conditions.
- Add English onboarding, community health files, security and governance
  policies, release documentation, source-distribution completeness checks,
  and package metadata based on PEP 639.
- Pin GitHub Actions to reviewed commit SHAs, add CodeQL analysis, and validate
  both wheel and source distributions in CI.
- Test the built source distribution and scripted wheel workflow in CI, and
  add an offline checker for broken or repository-escaping Markdown links.

## 0.2.1

- Add a separate adaptive evaluation arm with predeclared trial specs,
  truth-free run configuration generation, isolated outcome scoring,
  descriptive summaries, and paired fixed-arm comparison.
- Add an exact-count reference controller and `fixed-config`, `fixed-run`, and
  `fixed-outcome` commands that never apply adaptive early stopping.
- Disable native Codex multi-Agent tools inside every Governor-owned process
  so the reported Agent count remains auditable.

## 0.2.0

- Add `AdaptiveController`, which owns baseline-first Agent admission and
  enforces a checkpoint after every admitted Agent.
- Add runtime-neutral Agent, aggregation, verification, work-unit, checkpoint,
  report, telemetry, and replayable event protocols.
- Add a safe `CodexCliRuntime` that launches isolated ephemeral `codex exec`
  processes, parses real JSONL usage, enforces timeouts, and refuses
  unrestricted sandbox bypasses.
- Add deterministic `ScriptedRuntime` for end-to-end testing.
- Add structured code-review aggregation and an observable process verifier
  for changed-file coverage, independent high-risk review, and conflicts.
- Add hard Token, wall-time, and tool-call budgets.
- Add `magov plan`, `magov run`, `magov replay`, and `magov report`, while
  preserving the legacy `magov INPUT.json` planning command.
- Update the Codex plugin with separate advisory and executable code-review
  workflows.

The runtime and default policy remain experimental. Process coverage is not
hidden-truth correctness, and the engineering pilot is not evidence of general
quality-preserving cost savings.
