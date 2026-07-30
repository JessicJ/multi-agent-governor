# Changelog

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
