---
name: multi-agent-governor
description: Plan or execute evidence-based homogeneous Agent scaling. Start with one measured Agent, decide whether to admit another, select centralized or independent collaboration, enforce Agent and resource budgets, and stop when verified marginal value is too low. Use when a user asks whether multi-agent work is worthwhile, requests an adaptive code-review run, wants an Agent budget, or asks whether another Agent justifies its coordination and token cost.
---

# Multi-Agent Governor

Treat multi-agent use as an evidence-based admission decision, not a default.
The deterministic core has two modes:

- `plan`: return an advisory decision from a measured external baseline.
- `run`: let the Governor-owned runtime execute the baseline and admit one
  additional homogeneous Agent at each checkpoint.

The first executable verifier is intentionally limited to structured code
review. For other task types, use `plan` until a task-specific external
verifier exists.

## Advisory workflow

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
   python3 scripts/run_governor.py plan INPUT.json
   ```

6. Explain `mode`, `total_agents`, `stop_reason`, expected quality, expected
   cost multiplier, and the strongest two reasons in plain language.
7. If `mode` is not `single`, admit only the next Agent. After it returns,
   compare verified quality, coverage, unresolved conflicts, novel evidence,
   and actual cost before admitting another.

## Executable code-review workflow

Only use this workflow when the user explicitly asks the Governor to execute
the review, the task can be isolated in one working directory, and `codex exec`
is installed and authenticated.

1. Read [references/runtime-schema.md](references/runtime-schema.md).
2. Put the exact supported `policy.version`, review instructions, structural
   signals, changed files, high-risk files, budgets, and Codex runtime
   configuration in one run JSON file.
3. Keep truth cards, hidden tests, previous Agent output, and the event log
   outside the Agent working directory.
4. Ensure every extra Agent is launched by `magov run`; do not also use the
   surrounding session's native sub-Agent controls for the same run.
5. Run:

   ```bash
   python3 scripts/run_governor.py run RUN.json \
     --events RUN.events.jsonl > RUN.report.json
   ```

6. Inspect `actual_total_agents`, `stop_reason`, `verification`, `usage`,
   `checkpoints`, and `receipts`. A process-coverage score is not hidden-truth
   correctness.
7. Use `replay` for an interrupted run log and `report` to summarize completed
   report JSON files.

## Guardrails

- Preserve a forced single-Agent baseline.
- Reject unknown or mismatched policy versions; never silently fall back.
- Under `pilot-v2`, require one independent review before an unverified,
  separable independent review task may stop, unless a budget blocks admission.
- Treat `total_agents` as including the baseline Agent.
- Respect the user's cap even when the policy proposes more Agents.
- Prefer two Agents as the first real scale-out step; add later Agents one at
  a time.
- Use `centralized` when shared constraints or failure impact require one
  coherent result. The executable review mode uses deterministic JSON
  aggregation; another runtime must count and measure a model coordinator if
  it launches one.
- Use `independent` when work units and evidence can stay isolated until final
  aggregation.
- Stop when verified coverage is complete, no unresolved conflict remains,
  and the newest Agent contributes little novel evidence.
- Also stop at the quality target, planned cap, user cap, cost cap, or an
  observed marginal-value plateau.
- The executable runtime must own admission. A prose recommendation that the
  surrounding runtime may ignore is advisory mode, not enforced control.
- Never place Codex JSONL artifacts inside the Agent workspace; later Agents
  must not read earlier traces.
- Keep native Codex multi-agent tools disabled inside every Governor-owned
  `codex exec` process so `actual_total_agents` remains auditable.
- Never pass `--dangerously-bypass-approvals-and-sandbox` or an equivalent
  unrestricted execution option through the runtime adapter.
- Do not claim that the current default weights are universally optimal. Refer
  to them as an experimental, inspectable policy.

## Result boundary

In advisory mode, return a decision receipt and suggested checkpoint. In
executable code-review mode, return the runtime report and replayable event
log. Do not claim effectiveness until an unseen evaluation set passes the
predeclared quality and total-usage guardrails.
