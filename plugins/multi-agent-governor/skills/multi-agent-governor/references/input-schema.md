# Policy input

All ratio signals use `0..1`. Start from one measured Agent baseline.

```json
{
  "signals": {
    "parallelizable_units": 4,
    "parallel_fraction": 0.8,
    "decomposition_confidence": 0.9,
    "context_coupling": 0.25,
    "shared_context_ratio": 0.3,
    "uncertainty": 0.8,
    "verification_value": 0.85,
    "failure_correlation": 0.2,
    "aggregation_difficulty": 0.35,
    "error_impact": 0.6
  },
  "baseline": {
    "confidence": 0.58,
    "verified": false,
    "hard_failure": false,
    "cost_units": 1.0,
    "latency_seconds": 42
  },
  "budget": {
    "max_agents": 3,
    "max_cost_multiplier": 3.0,
    "target_confidence": 0.9
  }
}
```

## Evidence rules

- `parallelizable_units`: count genuinely separable work units, not headings.
- `parallel_fraction`: estimate how much work can proceed without shared
  evolving context.
- `decomposition_confidence`: lower it when task boundaries are ambiguous.
- `context_coupling` and `shared_context_ratio`: raise them when Agents must
  repeatedly share the same large or changing context.
- `uncertainty`: derive from verifier gaps, uncovered requirements, failing
  tests, or missing evidence.
- `verification_value`: raise it when an independent attempt can expose a
  different failure mode.
- `failure_correlation`: raise it when Agents use the same evidence, approach,
  prompt, or blind spot.
- `aggregation_difficulty`: raise it when outputs can conflict or must preserve
  one coherent state.
- `error_impact`: raise it for authorization, deletion, money, privacy,
  irreversible writes, and other high-consequence failures.

Set `baseline.confidence` from tests, calibrated judges, evidence coverage, or
historical success rates. Never copy the Agent's own confidence statement.
When `baseline.hard_failure` is `true`, set `confidence` to `0` and
`verified` to `false`; a hard failure means the baseline produced no usable
result to verify.

`max_agents` is a total count including the baseline Agent. Cost is normalized
against the measured baseline, so `max_cost_multiplier: 3` permits at most
three baseline-equivalent units of work.
