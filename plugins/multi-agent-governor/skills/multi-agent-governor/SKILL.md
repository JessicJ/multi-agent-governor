---
name: multi-agent-governor
description: Decide whether a task should remain single-agent or use multiple homogeneous agents, select centralized or independent collaboration, cap the available agent count, and determine when further agents should stop. Use when a user asks whether multi-agent work is worthwhile, how many agents to use, how to allocate an existing agent budget, or whether another agent would improve quality enough to justify coordination and token cost.
---

# Multi-Agent Governor

Treat multi-agent use as an evidence-based admission decision, not a default.
This skill produces a plan; it does not launch, select, or orchestrate agents.

## Workflow

1. Record the user's available total-agent cap. Count the original baseline
   Agent in that total.
2. Run or inspect exactly one single-Agent baseline before recommending
   scale-out. If no baseline exists, label any answer preliminary.
3. Derive task signals from observable structure and verifier evidence. Never
   use the model's self-reported confidence as baseline confidence.
4. Read [references/input-schema.md](references/input-schema.md) when creating
   the policy JSON.
5. Run:

   ```bash
   python3 scripts/run_governor.py INPUT.json
   ```

6. Explain `mode`, `total_agents`, `stop_reason`, expected quality, expected
   cost multiplier, and the strongest two reasons in plain language.
7. If `mode` is not `single`, admit only the next Agent. After it returns,
   compare verified quality, coverage, unresolved conflicts, novel evidence,
   and actual cost before admitting another.

## Guardrails

- Preserve a forced single-Agent baseline.
- Treat `total_agents` as including the baseline Agent.
- Respect the user's cap even when the policy proposes more Agents.
- Prefer two Agents as the first real scale-out step; add later Agents one at
  a time.
- Use `centralized` when shared constraints or failure impact require one
  coherent result. The baseline Agent is the logical coordinator unless the
  runtime explicitly pays for a separate coordinator.
- Use `independent` when work units and evidence can stay isolated until final
  aggregation.
- Stop when verified coverage is complete, no unresolved conflict remains,
  and the newest Agent contributes little novel evidence.
- Also stop at the quality target, planned cap, user cap, cost cap, or an
  observed marginal-value plateau.
- Do not claim that the current default weights are universally optimal. Refer
  to them as an experimental, inspectable policy.

## Result boundary

Return a decision receipt and suggested checkpoint, not an orchestration
trace. If the user separately asks to execute the plan, use the surrounding
runtime's normal Agent controls and record actual outcomes for later
calibration.
