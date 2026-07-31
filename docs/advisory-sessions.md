# Advisory session receipts

`magov advisory` records externally executed, baseline-first Agent scaling
without pretending that Governor owns the surrounding runtime. It is intended
for general development or research tasks that do not yet have a supported
deterministic verifier.

The receipt is append-only JSONL. `start` records the measured baseline and
forecast. Each `checkpoint` adds exactly one completed Agent observation,
recomputes the policy decision, and records whether to admit one more Agent or
stop. `report` replays every decision from the original inputs and rejects
tampered plans, skipped Agent counts, mixed known models, duplicate Agent IDs,
decreasing cumulative measurements, or events after a stop.

## Commands

```bash
magov advisory start examples/advisory_session_start.json \
  --events /tmp/magov-advisory.events.jsonl

magov advisory checkpoint /tmp/magov-advisory.events.jsonl \
  examples/advisory_checkpoint_agent_2.json

magov advisory checkpoint /tmp/magov-advisory.events.jsonl \
  examples/advisory_checkpoint_agent_3.json

magov advisory report /tmp/magov-advisory.events.jsonl
```

The start file must declare a session and task ID, explicit policy version,
structural signals, measured baseline, budget, observable baseline evidence,
and remaining risks. A checkpoint records the new Agent's bounded
contribution, externally derived quality and novelty measurements, evidence,
remaining risks, and any available resource usage.

Token, call, cost, and time fields use `null` when unavailable. They are never
silently converted to zero. A corresponding hard budget cannot be described
as evaluated when its measurement is unavailable.

## Result fields

- `planned_total_agents` is the initial forecast.
- `actual_total_agents` is the number of recorded completed Agents, including
  the baseline.
- `plan_stop_reason` explains why planning did not forecast another Agent.
- `final_stop_reason` is the unique observed checkpoint stop, or `null` while
  the session remains active.
- `next_total_agents` admits at most one additional Agent.
- `usage.complete` is true only when every Agent supplied every usage field.
- `homogeneous_model_verified` is `null` if any model identity is unavailable.
- `hard_budget_evidence` separates measured resource values from forecasts.
- `runtime_enforced` is always false for an advisory receipt.

The exact bundled input schema is in
[`advisory-session-schema.md`](../plugins/multi-agent-governor/skills/multi-agent-governor/references/advisory-session-schema.md).

## Trust boundary

Advisory events prove what the caller recorded and what the deterministic
policy decided from those records. They do not prove that Governor launched,
isolated, timed, or stopped native Agents. Checkpoint evidence remains
caller-supplied and must be backed by test output, static analysis, coverage,
or another independently auditable source.

Use `magov run` instead when the task is a supported structured code review
and Governor must own admission, isolation, accounting, and stopping.
