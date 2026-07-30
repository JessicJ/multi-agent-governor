# Executable runtime input

`magov run` currently supports a structured code-review verifier and two
runtime kinds:

- `codex-cli`: run a fresh isolated `codex exec` process for every admitted
  Agent.
- `scripted`: deterministic local results for tests and demonstrations.

Every `scripted` input must also carry this top-level marker so its report and
downstream evaluation cannot be mistaken for a real model run:

```json
{
  "dry_run": {
    "scripted": true,
    "real_experiment": false
  }
}
```

Relative paths are resolved from the directory containing the run JSON file.

```json
{
  "task": {
    "task_id": "review-001",
    "prompt": "Review the changed files and return the required JSON.",
    "working_directory": "/absolute/path/to/isolated/task",
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
      "error_impact": 0.8
    },
    "metadata": {
      "changed_files": ["src/auth.py", "src/storage.py"],
      "high_risk_files": ["src/auth.py"]
    },
    "work_units": [
      {
        "work_unit_id": "authorization",
        "instruction": "Review permission boundaries and failure paths.",
        "scope": ["src/auth.py"],
        "high_risk": true
      }
    ]
  },
  "runtime": {
    "kind": "codex-cli",
    "model": "FIXED_MODEL_ID",
    "sandbox": "read-only",
    "timeout_seconds": 900,
    "ephemeral": true,
    "output_schema": "/absolute/path/to/review_output.schema.json",
    "artifacts_directory": "/absolute/path/outside/agent/workspace"
  },
  "verifier": {"kind": "review"},
  "budget": {
    "max_agents": 4,
    "max_cost_multiplier": 5,
    "target_confidence": 0.95,
    "min_expected_gain": 0.005,
    "max_total_tokens": 500000,
    "max_wall_time_seconds": 3600,
    "max_tool_calls": 200
  },
  "governance_tokens": 0
}
```

The review verifier uses only observable process evidence:

- changed-file coverage;
- independent review of declared high-risk files;
- unresolved conflicts;
- unique structured findings.

It does not read hidden truth and never treats a model's self-reported
confidence as evidence. `coverage_complete: true` means the declared review
coverage contract is complete, not that the code is proven defect-free.

`artifacts_directory` must be outside `working_directory`. The adapter refuses
unrestricted Codex sandbox modes and known safety-bypass flags.
