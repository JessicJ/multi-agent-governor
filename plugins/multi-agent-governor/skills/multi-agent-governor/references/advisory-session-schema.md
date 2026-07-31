# Advisory session schema

Use this schema only when external or native Agents execute a task outside
`magov run`. The JSONL receipt is auditable advice, not runtime enforcement.

## Start input

```json
{
  "session": {
    "session_id": "task-run-001",
    "task_id": "task-001",
    "model_id": "gpt-5.6-sol",
    "wall_time_seconds": null
  },
  "policy": {"version": "pilot-v2"},
  "signals": {
    "parallelizable_units": 4,
    "parallel_fraction": 0.55,
    "decomposition_confidence": 0.7,
    "context_coupling": 0.65,
    "shared_context_ratio": 0.6,
    "uncertainty": 0.95,
    "verification_value": 0.9,
    "failure_correlation": 0.35,
    "aggregation_difficulty": 0.75,
    "error_impact": 0.7
  },
  "baseline": {
    "confidence": 0,
    "verified": false,
    "hard_failure": true,
    "cost_units": 1,
    "latency_seconds": 0
  },
  "budget": {
    "max_agents": 4,
    "max_cost_multiplier": 4,
    "target_confidence": 0.95
  },
  "baseline_evidence": [
    {
      "code": "baseline_test",
      "statement": "The initial test command failed before implementation.",
      "source": "verifier"
    }
  ],
  "remaining_risks": ["No implementation exists."],
  "baseline_usage": {
    "input_tokens": null,
    "cached_input_tokens": null,
    "output_tokens": null,
    "reasoning_tokens": null,
    "total_tokens": null,
    "model_calls": null,
    "tool_calls": null,
    "agent_time_seconds": null
  }
}
```

Requirements:

- `policy.version` is explicit; unknown versions are rejected.
- `max_agents` includes the baseline Agent.
- `baseline_evidence` is non-empty and includes at least one non-policy fact.
- Evidence sources are `task`, `runtime`, `verifier`, or `policy`.
- `confidence` comes from an external score, never model self-confidence.
- Unknown model, Token, call, cost, or time measurements are `null`.

Start the receipt:

```bash
magov advisory start START.json --events SESSION.events.jsonl
```

The event file must not already contain data.

## Checkpoint input

```json
{
  "agent_id": "reviewer-1",
  "total_agents": 2,
  "contribution": "Reviewed persistence and schema boundaries.",
  "quality_score": 0.72,
  "marginal_quality_gain": 0.22,
  "novel_evidence_ratio": 0.8,
  "coverage_complete": false,
  "unresolved_conflicts": 1,
  "evidence": [
    {
      "code": "schema_test",
      "statement": "A deterministic test rejects an unsafe conversion.",
      "source": "verifier"
    }
  ],
  "remaining_risks": ["CLI negative paths remain unreviewed."],
  "usage": {
    "input_tokens": null,
    "cached_input_tokens": null,
    "output_tokens": null,
    "reasoning_tokens": null,
    "total_tokens": null,
    "model_calls": null,
    "tool_calls": null,
    "agent_time_seconds": null
  },
  "model_id": "gpt-5.6-sol",
  "cumulative_cost_multiplier": null,
  "cumulative_wall_time_seconds": null
}
```

Append one completed Agent:

```bash
magov advisory checkpoint SESSION.events.jsonl CHECKPOINT.json
```

Requirements:

- `total_agents` increments by exactly one.
- `agent_id` is unique.
- Known model IDs remain identical.
- Cumulative cost and wall time never decrease.
- `quality_score` and `novel_evidence_ratio` are between 0 and 1.
- Token totals equal input plus output; cached input is a subset of input and
  reasoning is a subset of output.
- Evidence is non-empty and contains a non-policy observable fact.
- No checkpoint may follow a stop.

## Report

```bash
magov advisory report SESSION.events.jsonl
```

Replay recomputes the original plan and every checkpoint decision. It keeps
forecast `plan_stop_reason` separate from observed `final_stop_reason`.
Unavailable usage remains `null`, and `runtime_enforced` remains false.
