"""Blind-evaluation bridge for adaptive Governor executions.

The fixed-count evaluation layer deliberately cannot represent an adaptive
arm because ``TrialOutcome`` requires the observed Agent count to equal a
predeclared exact count.  This module keeps the adaptive arm separate while
reusing the same hidden-truth scorer, usage accounting, and checkpoint shape.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from math import isclose, isfinite
from statistics import fmean
from typing import Any, Mapping, Sequence

from .evaluation import (
    BlindAdjudication,
    CheckpointObservation,
    GoldDefect,
    ReviewFinding,
    ReviewTask,
    ScoreReport,
    TaskStatus,
    TrialOutcome,
    TrialSpec,
    UsageObservation,
    score_findings,
)
from .models import Budget, TaskSignals


def _json_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a JSON boolean")
    return value


@dataclass(frozen=True)
class AdaptiveTrialSpec:
    """A predeclared adaptive arm with a maximum, not exact, Agent count."""

    trial_id: str
    task_id: str
    max_agents: int
    repetition: int
    model_id: str
    prompt_version: str
    policy_version: str
    homogeneous_agents: bool = True

    def __post_init__(self) -> None:
        for name in (
            "trial_id",
            "task_id",
            "model_id",
            "prompt_version",
            "policy_version",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")
        if type(self.max_agents) is not int or self.max_agents not in range(1, 9):
            raise ValueError("max_agents must be between 1 and 8")
        if type(self.repetition) is not int or self.repetition < 1:
            raise ValueError("repetition must be a positive integer")
        if type(self.homogeneous_agents) is not bool:
            raise TypeError("homogeneous_agents must be a JSON boolean")
        if not self.homogeneous_agents:
            raise ValueError("the first adaptive evaluation requires homogeneous Agents")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AdaptiveTrialSpec":
        homogeneous = _json_bool(
            payload.get("homogeneous_agents", True),
            "homogeneous_agents",
        )
        return cls(
            trial_id=str(payload["trial_id"]),
            task_id=str(payload["task_id"]),
            max_agents=int(payload["max_agents"]),
            repetition=int(payload["repetition"]),
            model_id=str(payload["model_id"]),
            prompt_version=str(payload["prompt_version"]),
            policy_version=str(payload["policy_version"]),
            homogeneous_agents=homogeneous,
        )


def build_adaptive_trial_matrix(
    tasks: Sequence[ReviewTask],
    *,
    model_id: str,
    prompt_version: str,
    policy_version: str,
    max_agents: int = 4,
    repetitions: int = 2,
) -> tuple[AdaptiveTrialSpec, ...]:
    """Build one adaptive arm per task and repetition."""

    if not tasks:
        raise ValueError("at least one task is required")
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if max_agents not in range(1, 9):
        raise ValueError("max_agents must be between 1 and 8")
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be unique")
    drafts = [
        task.task_id
        for task in tasks
        if task.status is not TaskStatus.READY
    ]
    if drafts:
        raise ValueError(
            "draft tasks cannot be scheduled: " + ", ".join(sorted(drafts))
        )

    return tuple(
        AdaptiveTrialSpec(
            trial_id=(
                f"{task.task_id}__adaptive-max-{max_agents}"
                f"__repeat-{repetition}"
            ),
            task_id=task.task_id,
            max_agents=max_agents,
            repetition=repetition,
            model_id=model_id,
            prompt_version=prompt_version,
            policy_version=policy_version,
        )
        for task in sorted(tasks, key=lambda item: item.task_id)
        for repetition in range(1, repetitions + 1)
    )


def derive_pilot_review_signals(
    task: ReviewTask,
    *,
    policy_version: str = "pilot-v1",
) -> TaskSignals:
    """Derive policy-versioned review signals from public task metadata.

    These constants are an inspectable engineering baseline, not fitted
    effectiveness claims.  They use only changed-file count and the declared
    high-risk file list; hidden truth and trigger tests are unavailable.

    ``pilot-v2`` treats independent replication as a second separable review
    unit even when only one file changed.  This lets the policy require an
    independent review without pretending that the file itself can be split.
    """

    changed_count = len(task.changed_files)
    has_high_risk = bool(task.high_risk_files)
    independent_replication = policy_version == "pilot-v2"
    parallelizable_units = max(
        2 if independent_replication else 1,
        min(4, changed_count),
    )
    return TaskSignals(
        parallelizable_units=parallelizable_units,
        parallel_fraction=(
            round(min(0.85, 0.35 + 0.15 * changed_count), 2)
            if changed_count > 1 or independent_replication
            else 0.15
        ),
        decomposition_confidence=(
            0.85 if changed_count > 1 or independent_replication else 0.60
        ),
        context_coupling=0.35,
        shared_context_ratio=0.40,
        uncertainty=0.80 if has_high_risk else 0.55,
        verification_value=0.90 if has_high_risk else 0.55,
        failure_correlation=0.25,
        aggregation_difficulty=0.30,
        error_impact=0.90 if has_high_risk else 0.55,
    )


def render_review_prompt(
    template: str,
    *,
    task_directory: str,
    trial_id: str,
    role: str = "runtime-assigned reviewer",
) -> str:
    """Render the fixed prompt template without consulting evaluation truth."""

    result = (
        template.replace("TASK_DIRECTORY", task_directory)
        .replace("TRIAL_ID", trial_id)
        .replace("ROLE", role)
    )
    if not result.strip():
        raise ValueError("review prompt template cannot be empty")
    for placeholder in ("TASK_DIRECTORY", "TRIAL_ID", "ROLE"):
        if placeholder in result:
            raise ValueError(f"unresolved prompt placeholder: {placeholder}")
    return result


def build_adaptive_run_payload(
    task: ReviewTask,
    trial: AdaptiveTrialSpec,
    *,
    working_directory: str,
    prompt: str,
    output_schema: str,
    artifacts_directory: str,
    budget: Budget | None = None,
) -> dict[str, Any]:
    """Build a truth-free ``magov run`` payload for one adaptive trial."""

    if task.task_id != trial.task_id:
        raise ValueError("task and adaptive trial task_id must match")
    if not working_directory.strip():
        raise ValueError("working_directory cannot be empty")
    if not prompt.strip():
        raise ValueError("prompt cannot be empty")
    if not output_schema.strip() or not artifacts_directory.strip():
        raise ValueError("output_schema and artifacts_directory are required")
    configured_budget = budget or Budget(
        max_agents=trial.max_agents,
        max_cost_multiplier=5.0,
        target_confidence=0.95,
        min_expected_gain=0.005,
        max_total_tokens=500_000,
        max_wall_time_seconds=3600,
        max_tool_calls=200,
    )
    if configured_budget.max_agents != trial.max_agents:
        raise ValueError("budget.max_agents must equal trial.max_agents")
    signals = derive_pilot_review_signals(
        task,
        policy_version=trial.policy_version,
    )
    work_units = [
        {
            "work_unit_id": f"review-file-{index}",
            "instruction": (
                "独立检查该文件的变更、边界条件与失败路径。"
                if filename in task.high_risk_files
                else "独立检查该文件的变更和可由代码支持的问题。"
            ),
            "scope": [filename],
            "high_risk": filename in task.high_risk_files,
        }
        for index, filename in enumerate(task.changed_files, 1)
    ]
    return {
        "task": {
            "task_id": task.task_id,
            "prompt": prompt,
            "working_directory": working_directory,
            "signals": asdict(signals),
            "metadata": {
                "changed_files": list(task.changed_files),
                "high_risk_files": list(task.high_risk_files),
                "evaluation_trial_id": trial.trial_id,
                "policy_version": trial.policy_version,
            },
            "work_units": work_units,
        },
        "runtime": {
            "kind": "codex-cli",
            "model": trial.model_id,
            "sandbox": "read-only",
            "timeout_seconds": 900,
            "ephemeral": True,
            "output_schema": output_schema,
            "artifacts_directory": artifacts_directory,
            "extra_args": ["--ignore-user-config"],
        },
        "verifier": {"kind": "review"},
        "policy": {"version": trial.policy_version},
        "budget": asdict(configured_budget),
        "governance_tokens": 0,
    }


def build_fixed_run_payload(
    task: ReviewTask,
    trial: TrialSpec,
    *,
    working_directory: str,
    prompt: str,
    output_schema: str,
    artifacts_directory: str,
    budget: Budget | None = None,
) -> dict[str, Any]:
    """Build the same truth-free runtime input for an exact-count arm."""

    proxy = AdaptiveTrialSpec(
        trial_id=trial.trial_id,
        task_id=trial.task_id,
        max_agents=trial.exact_total_agents,
        repetition=trial.repetition,
        model_id=trial.model_id,
        prompt_version=trial.prompt_version,
        policy_version="fixed-reference",
    )
    payload = build_adaptive_run_payload(
        task,
        proxy,
        working_directory=working_directory,
        prompt=prompt,
        output_schema=output_schema,
        artifacts_directory=artifacts_directory,
        budget=budget
        or Budget(
            max_agents=trial.exact_total_agents,
            max_cost_multiplier=max(1.0, float(trial.exact_total_agents + 1)),
            target_confidence=1.0,
            min_expected_gain=0.0,
            max_total_tokens=(
                500_000 if trial.exact_total_agents == 1 else 2_000_000
            ),
            max_wall_time_seconds=3600,
            max_tool_calls=400,
        ),
    )
    payload["task"]["metadata"]["evaluation_arm"] = "fixed"
    payload["task"]["metadata"].pop("policy_version", None)
    return payload


def _usage_delta(
    current: UsageObservation, previous: UsageObservation
) -> UsageObservation:
    values: dict[str, Any] = {}
    for name in (
        "agent_input_tokens",
        "agent_output_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "governance_tokens",
        "model_calls",
        "tool_calls",
        "wall_time_seconds",
    ):
        value = getattr(current, name) - getattr(previous, name)
        if value < 0:
            raise ValueError(f"cumulative usage decreased at {name}")
        values[name] = value
    return UsageObservation(**values)


def _pooled_defect_recall(
    outcomes: Sequence[Any],
    *,
    serious: bool,
) -> float:
    total_name = "serious_defects" if serious else "total_known_defects"
    found_name = (
        "found_serious_defects" if serious else "found_known_defects"
    )
    total = sum(getattr(item.score, total_name) for item in outcomes)
    if total == 0:
        return 1.0
    return sum(getattr(item.score, found_name) for item in outcomes) / total


def _scale_observation(outcomes: Sequence["AdaptiveTrialOutcome"]) -> dict[str, Any]:
    """Describe which adaptive admission depths the data actually observed."""

    configured_max_agents = outcomes[0].trial.max_agents
    highest_observed_agents = max(item.actual_total_agents for item in outcomes)
    post_independent_review_admissions = sum(
        max(0, item.actual_total_agents - 2) for item in outcomes
    )
    contains_post_independent_review_observation = (
        highest_observed_agents >= 3
    )
    result: dict[str, Any] = {
        "configured_max_agents": configured_max_agents,
        "highest_observed_agents": highest_observed_agents,
        "trials_reaching_three_or_more_agents": sum(
            item.actual_total_agents >= 3 for item in outcomes
        ),
        "post_independent_review_admissions": post_independent_review_admissions,
        "contains_post_independent_review_observation": (
            contains_post_independent_review_observation
        ),
    }
    if not contains_post_independent_review_observation:
        result["limitation"] = (
            "No trial admitted an Agent beyond the required independent review; "
            "this batch cannot calibrate third-or-later-Agent decisions."
        )
    return result


@dataclass(frozen=True)
class AdaptiveTrialOutcome:
    trial: AdaptiveTrialSpec
    actual_total_agents: int
    planned_total_agents: int
    execution_status: str
    stop_reason: str
    usage: UsageObservation
    score: ScoreReport
    coverage_complete: bool
    unresolved_conflicts: int
    checkpoints: tuple[CheckpointObservation, ...]
    wall_time_seconds: float = 0.0
    scripted_dry_run: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.actual_total_agents <= self.trial.max_agents:
            raise ValueError(
                "actual_total_agents must be between 1 and trial.max_agents"
            )
        if not 1 <= self.planned_total_agents <= self.trial.max_agents:
            raise ValueError(
                "planned_total_agents must be between 1 and max Agents"
            )
        if self.execution_status not in {"completed", "incomplete"}:
            raise ValueError("execution_status must be completed or incomplete")
        if not self.stop_reason.strip():
            raise ValueError("stop_reason cannot be empty")
        if self.unresolved_conflicts < 0:
            raise ValueError("unresolved_conflicts cannot be negative")
        if self.execution_status == "completed" and not self.coverage_complete:
            raise ValueError(
                "a completed adaptive outcome requires public verification coverage"
            )
        if self.execution_status == "completed" and self.unresolved_conflicts:
            raise ValueError(
                "a completed adaptive outcome cannot retain unresolved conflicts"
            )
        if (
            not isfinite(self.wall_time_seconds)
            or self.wall_time_seconds < 0
        ):
            raise ValueError("wall_time_seconds cannot be negative")
        if type(self.scripted_dry_run) is not bool:
            raise ValueError("scripted_dry_run must be a boolean")
        expected_counts = list(range(1, self.actual_total_agents + 1))
        if not self.checkpoints:
            raise ValueError("adaptive outcome must contain checkpoints")
        if [item.total_agents for item in self.checkpoints] != expected_counts:
            raise ValueError(
                "checkpoints must contain each admitted Agent count in order"
            )
        final = self.checkpoints[-1]
        if final.coverage_complete != self.coverage_complete:
            raise ValueError(
                "final checkpoint coverage_complete must match the outcome"
            )
        if final.unresolved_conflicts != self.unresolved_conflicts:
            raise ValueError(
                "final checkpoint unresolved_conflicts must match the outcome"
            )
        summed = UsageObservation(
            agent_input_tokens=sum(
                item.usage_delta.agent_input_tokens for item in self.checkpoints
            ),
            agent_output_tokens=sum(
                item.usage_delta.agent_output_tokens for item in self.checkpoints
            ),
            cached_input_tokens=sum(
                item.usage_delta.cached_input_tokens for item in self.checkpoints
            ),
            reasoning_output_tokens=sum(
                item.usage_delta.reasoning_output_tokens
                for item in self.checkpoints
            ),
            governance_tokens=sum(
                item.usage_delta.governance_tokens for item in self.checkpoints
            ),
            model_calls=sum(
                item.usage_delta.model_calls for item in self.checkpoints
            ),
            tool_calls=sum(
                item.usage_delta.tool_calls for item in self.checkpoints
            ),
            wall_time_seconds=sum(
                item.usage_delta.wall_time_seconds for item in self.checkpoints
            ),
        )
        for name in (
            "agent_input_tokens",
            "agent_output_tokens",
            "cached_input_tokens",
            "reasoning_output_tokens",
            "governance_tokens",
            "model_calls",
            "tool_calls",
        ):
            if getattr(summed, name) != getattr(self.usage, name):
                raise ValueError(
                    "checkpoint usage deltas must sum to outcome usage"
                )
        if not isclose(
            summed.wall_time_seconds,
            self.usage.wall_time_seconds,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "checkpoint usage deltas must sum to outcome usage"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial": self.trial.to_dict(),
            "actual_total_agents": self.actual_total_agents,
            "planned_total_agents": self.planned_total_agents,
            "execution_status": self.execution_status,
            "stop_reason": self.stop_reason,
            "usage": self.usage.to_dict(),
            "score": self.score.to_dict(),
            "coverage_complete": self.coverage_complete,
            "unresolved_conflicts": self.unresolved_conflicts,
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "wall_time_seconds": self.wall_time_seconds,
            "scripted_dry_run": self.scripted_dry_run,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AdaptiveTrialOutcome":
        coverage = _json_bool(
            payload["coverage_complete"], "coverage_complete"
        )
        return cls(
            trial=AdaptiveTrialSpec.from_dict(payload["trial"]),
            actual_total_agents=int(payload["actual_total_agents"]),
            planned_total_agents=int(payload["planned_total_agents"]),
            execution_status=str(payload["execution_status"]),
            stop_reason=str(payload["stop_reason"]),
            usage=UsageObservation.from_dict(payload["usage"]),
            score=ScoreReport.from_dict(payload["score"]),
            coverage_complete=coverage,
            unresolved_conflicts=int(payload.get("unresolved_conflicts", 0)),
            checkpoints=tuple(
                CheckpointObservation.from_dict(item)
                for item in payload.get("checkpoints", ())
            ),
            wall_time_seconds=float(payload.get("wall_time_seconds", 0.0)),
            scripted_dry_run=_json_bool(
                payload.get("scripted_dry_run", False),
                "scripted_dry_run",
            ),
        )


def _report_findings(
    report: Mapping[str, Any],
) -> tuple[ReviewFinding, ...]:
    aggregate = report.get("aggregate")
    if not isinstance(aggregate, Mapping):
        raise ValueError("runtime report has no aggregate object")
    metadata = aggregate.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("runtime aggregate metadata must be an object")
    raw_findings = metadata.get("findings", ())
    if not isinstance(raw_findings, list):
        raise ValueError("runtime aggregate findings must be an array")
    findings = [
        ReviewFinding.from_dict(item)
        for item in raw_findings
        if isinstance(item, Mapping)
    ]
    if len(findings) != len(raw_findings):
        raise ValueError("every runtime finding must be an object")

    # Agent-generated identifiers are labels, not semantic evidence. Independent
    # Agents can legitimately choose the same label, so namespace later
    # occurrences deterministically instead of rejecting an otherwise valid
    # completed run. Finding content and ordering remain unchanged.
    seen_ids: set[str] = set()
    occurrences: Counter[str] = Counter()
    normalized: list[ReviewFinding] = []
    for finding in findings:
        base_id = finding.finding_id
        occurrences[base_id] += 1
        finding_id = base_id
        if finding_id in seen_ids:
            suffix = occurrences[base_id]
            finding_id = f"{base_id}__occurrence-{suffix}"
            while finding_id in seen_ids:
                suffix += 1
                finding_id = f"{base_id}__occurrence-{suffix}"
            occurrences[base_id] = suffix
        seen_ids.add(finding_id)
        normalized.append(replace(finding, finding_id=finding_id))
    return tuple(normalized)


def _report_checkpoints(
    report: Mapping[str, Any],
) -> tuple[CheckpointObservation, ...]:
    runtime_checkpoints = report.get("checkpoints", ())
    if not isinstance(runtime_checkpoints, list) or not runtime_checkpoints:
        raise ValueError("runtime report must contain checkpoints")
    checkpoints: list[CheckpointObservation] = []
    previous_usage = UsageObservation(0, 0)
    previous_reviewed: set[str] = set()
    for raw_checkpoint in runtime_checkpoints:
        if not isinstance(raw_checkpoint, Mapping):
            raise ValueError("every runtime checkpoint must be an object")
        verification = raw_checkpoint.get("verification", {})
        if not isinstance(verification, Mapping):
            raise ValueError("checkpoint verification must be an object")
        raw_reviewed = verification.get("reviewed_files", ())
        if isinstance(raw_reviewed, (str, bytes)) or not isinstance(
            raw_reviewed, Sequence
        ) or not all(
            isinstance(item, str) for item in raw_reviewed
        ):
            raise ValueError(
                "checkpoint verification reviewed_files must be an array "
                "of strings"
            )
        reviewed = set(raw_reviewed)
        cumulative = UsageObservation.from_dict(
            raw_checkpoint["cumulative_usage"]
        )
        checkpoints.append(
            CheckpointObservation(
                total_agents=int(raw_checkpoint["total_agents"]),
                new_finding_count=int(
                    raw_checkpoint.get("new_evidence_count", 0)
                ),
                repeated_finding_count=int(
                    raw_checkpoint.get("repeated_evidence_count", 0)
                ),
                newly_reviewed_files=tuple(
                    sorted(reviewed - previous_reviewed)
                ),
                coverage_complete=_json_bool(
                    verification.get("coverage_complete", False),
                    "checkpoint verification coverage_complete",
                ),
                unresolved_conflicts=int(
                    verification.get("unresolved_conflicts", 0)
                ),
                usage_delta=_usage_delta(cumulative, previous_usage),
            )
        )
        previous_usage = cumulative
        previous_reviewed = reviewed
    return tuple(checkpoints)


def _final_verification(
    report: Mapping[str, Any],
) -> Mapping[str, Any]:
    verification = report.get("verification", {})
    if not isinstance(verification, Mapping):
        raise ValueError("runtime report verification must be an object")
    return verification


def adaptive_outcome_from_report(
    trial: AdaptiveTrialSpec,
    report: Mapping[str, Any],
    truth: Sequence[GoldDefect],
    adjudications: Sequence[BlindAdjudication] = (),
    *,
    scripted_dry_run: bool = False,
) -> AdaptiveTrialOutcome:
    """Join a completed truth-free runtime report with isolated scoring."""

    if str(report.get("task_id", "")) != trial.task_id:
        raise ValueError("runtime report task_id does not match the trial")
    reported_policy = report.get("policy_version")
    if reported_policy is None and trial.policy_version != "pilot-v1":
        raise ValueError(
            "runtime report must declare policy_version for this trial"
        )
    if (
        reported_policy is not None
        and str(reported_policy) != trial.policy_version
    ):
        raise ValueError(
            "runtime report policy_version does not match the adaptive trial"
        )
    findings = _report_findings(report)
    checkpoints = _report_checkpoints(report)

    final_verification = _final_verification(report)
    plan = report.get("plan", {})
    if not isinstance(plan, Mapping):
        raise ValueError("runtime report plan must be an object")
    return AdaptiveTrialOutcome(
        trial=trial,
        actual_total_agents=int(report["actual_total_agents"]),
        planned_total_agents=int(plan["total_agents"]),
        execution_status=str(report["status"]),
        stop_reason=str(report["stop_reason"]),
        usage=UsageObservation.from_dict(report["usage"]),
        score=score_findings(truth, findings, adjudications),
        coverage_complete=_json_bool(
            final_verification.get("coverage_complete", False),
            "report verification coverage_complete",
        ),
        unresolved_conflicts=int(
            final_verification.get("unresolved_conflicts", 0)
        ),
        checkpoints=checkpoints,
        wall_time_seconds=float(report.get("wall_time_seconds", 0.0)),
        scripted_dry_run=scripted_dry_run,
    )


def fixed_outcome_from_report(
    trial: TrialSpec,
    report: Mapping[str, Any],
    truth: Sequence[GoldDefect],
    adjudications: Sequence[BlindAdjudication] = (),
    *,
    scripted_dry_run: bool = False,
) -> TrialOutcome:
    """Score one exact-count report after its truth-free execution finishes."""

    if not isinstance(trial, TrialSpec):
        raise TypeError("trial must be a TrialSpec")
    if str(report.get("task_id", "")) != trial.task_id:
        raise ValueError("runtime report task_id does not match the trial")
    if str(report.get("status", "")) != "completed":
        raise ValueError("an incomplete fixed run cannot become an outcome")
    if int(report.get("exact_total_agents", 0)) != trial.exact_total_agents:
        raise ValueError(
            "runtime exact_total_agents does not match the fixed trial"
        )
    if int(report.get("actual_total_agents", 0)) != trial.exact_total_agents:
        raise ValueError("fixed runtime did not complete the exact Agent count")
    findings = _report_findings(report)
    checkpoints = _report_checkpoints(report)
    final_verification = _final_verification(report)
    return TrialOutcome(
        trial=trial,
        actual_total_agents=trial.exact_total_agents,
        usage=UsageObservation.from_dict(report["usage"]),
        score=score_findings(truth, findings, adjudications),
        coverage_complete=_json_bool(
            final_verification.get("coverage_complete", False),
            "report verification coverage_complete",
        ),
        unresolved_conflicts=int(
            final_verification.get("unresolved_conflicts", 0)
        ),
        checkpoints=checkpoints,
        wall_time_seconds=float(report.get("wall_time_seconds", 0.0)),
        scripted_dry_run=scripted_dry_run,
    )


def summarize_adaptive_outcomes(
    outcomes: Sequence[AdaptiveTrialOutcome],
) -> dict[str, Any]:
    """Return descriptive adaptive-arm quality, cost, and stopping evidence."""

    if not outcomes:
        raise ValueError("at least one adaptive outcome is required")
    trial_ids = [item.trial.trial_id for item in outcomes]
    if len(trial_ids) != len(set(trial_ids)):
        raise ValueError("adaptive trial ids must be unique")
    conditions = {
        (
            item.trial.model_id,
            item.trial.prompt_version,
            item.trial.policy_version,
            item.trial.max_agents,
            item.scripted_dry_run,
        )
        for item in outcomes
    }
    if len(conditions) != 1:
        raise ValueError(
            "adaptive outcomes must share model, prompt, policy, and max Agents"
        )
    complete = [item for item in outcomes if item.score.complete]
    false_positive_values = [
        item.score.false_positive_share
        for item in complete
        if item.score.false_positive_share is not None
    ]
    return {
        "status": "descriptive_only",
        "claim_allowed": False,
        "engineering_result": "inconclusive",
        "evaluation_mode": (
            "scripted_dry_run"
            if all(item.scripted_dry_run for item in outcomes)
            else "real"
        ),
        "real_experiment": not any(
            item.scripted_dry_run for item in outcomes
        ),
        "trials": len(outcomes),
        "complete_scores": len(complete),
        "mean_actual_agents": round(
            fmean(item.actual_total_agents for item in outcomes), 6
        ),
        "actual_agent_distribution": dict(
            sorted(
                Counter(
                    str(item.actual_total_agents) for item in outcomes
                ).items()
            )
        ),
        "scale_observation": _scale_observation(outcomes),
        "stop_reasons": dict(
            sorted(Counter(item.stop_reason for item in outcomes).items())
        ),
        "mean_serious_recall": (
            round(
                _pooled_defect_recall(complete, serious=True),
                6,
            )
            if complete
            else None
        ),
        "total_recall": (
            round(
                _pooled_defect_recall(complete, serious=False),
                6,
            )
            if complete
            else None
        ),
        "recall_aggregation": "micro_over_registered_defects",
        "mean_false_positive_share": (
            round(fmean(false_positive_values), 6)
            if false_positive_values
            else None
        ),
        "mean_total_tokens": round(
            fmean(item.usage.total_tokens for item in outcomes), 2
        ),
        "mean_agent_cumulative_time_seconds": round(
            fmean(item.usage.wall_time_seconds for item in outcomes), 3
        ),
        "mean_wall_time_seconds": round(
            fmean(item.wall_time_seconds for item in outcomes), 3
        ),
        "coverage_complete_rate": round(
            fmean(1.0 if item.coverage_complete else 0.0 for item in outcomes),
            6,
        ),
        "red_line_miss_trials": sum(
            bool(item.score.missed_red_line_defects) for item in outcomes
        ),
        "incomplete_runtime_trials": sum(
            item.execution_status != "completed" for item in outcomes
        ),
        "cap_censored_trials": sum(
            item.stop_reason == "cap_reached_incomplete" for item in outcomes
        ),
    }


def compare_adaptive_to_fixed(
    fixed_outcomes: Sequence[TrialOutcome],
    adaptive_outcomes: Sequence[AdaptiveTrialOutcome],
    *,
    reference_agents: int = 4,
) -> dict[str, Any]:
    """Create a paired descriptive snapshot against one fixed-count arm."""

    reference = [
        item
        for item in fixed_outcomes
        if item.actual_total_agents == reference_agents
    ]
    if not reference or not adaptive_outcomes:
        raise ValueError("both reference and adaptive outcomes are required")
    modes = {
        item.scripted_dry_run
        for item in (*fixed_outcomes, *adaptive_outcomes)
    }
    if len(modes) != 1:
        raise ValueError("cannot compare real and scripted dry-run outcomes")
    scripted_dry_run = next(iter(modes))
    conditions = {
        (item.trial.model_id, item.trial.prompt_version)
        for item in (*fixed_outcomes, *adaptive_outcomes)
    }
    if len(conditions) != 1:
        raise ValueError("all compared arms must use the same model and prompt")
    reference_by_pair = {
        (item.trial.task_id, item.trial.repetition): item
        for item in reference
    }
    adaptive_by_pair = {
        (item.trial.task_id, item.trial.repetition): item
        for item in adaptive_outcomes
    }
    if len(reference_by_pair) != len(reference) or len(adaptive_by_pair) != len(
        adaptive_outcomes
    ):
        raise ValueError("task and repetition pairs must be unique in each arm")
    if set(reference_by_pair) != set(adaptive_by_pair):
        raise ValueError(
            "fixed reference and adaptive arms must contain identical pairs"
        )
    if any(
        fixed.trial.model_id != adaptive_by_pair[pair].trial.model_id
        or fixed.trial.prompt_version
        != adaptive_by_pair[pair].trial.prompt_version
        for pair, fixed in reference_by_pair.items()
    ):
        raise ValueError("paired arms must use the same model and prompt")

    fixed_complete = all(item.score.complete for item in reference)
    adaptive_complete = all(
        item.score.complete for item in adaptive_outcomes
    )
    if not fixed_complete or not adaptive_complete:
        quality: dict[str, Any] = {
            "complete": False,
            "reason": "pending blind adjudications remain",
        }
    else:
        fixed_recall = _pooled_defect_recall(reference, serious=True)
        adaptive_recall = _pooled_defect_recall(
            adaptive_outcomes,
            serious=True,
        )
        fixed_total_recall = _pooled_defect_recall(
            reference,
            serious=False,
        )
        adaptive_total_recall = _pooled_defect_recall(
            adaptive_outcomes,
            serious=False,
        )
        fixed_fp = fmean(
            item.score.false_positive_share or 0.0 for item in reference
        )
        adaptive_fp = fmean(
            item.score.false_positive_share or 0.0
            for item in adaptive_outcomes
        )
        adaptive_runtime_complete = all(
            item.execution_status == "completed"
            for item in adaptive_outcomes
        )
        quality = {
            "complete": True,
            "recall_aggregation": "micro_over_registered_defects",
            "fixed_mean_serious_recall": round(fixed_recall, 6),
            "adaptive_mean_serious_recall": round(adaptive_recall, 6),
            "serious_recall_difference": round(
                adaptive_recall - fixed_recall, 6
            ),
            "fixed_mean_total_recall": round(fixed_total_recall, 6),
            "adaptive_mean_total_recall": round(adaptive_total_recall, 6),
            "total_recall_difference": round(
                adaptive_total_recall - fixed_total_recall, 6
            ),
            "fixed_found_all_registered_defects_rate": round(
                fmean(
                    item.score.found_known_defects
                    == item.score.total_known_defects
                    for item in reference
                ),
                6,
            ),
            "adaptive_found_all_registered_defects_rate": round(
                fmean(
                    item.score.found_known_defects
                    == item.score.total_known_defects
                    for item in adaptive_outcomes
                ),
                6,
            ),
            "fixed_mean_false_positive_share": round(fixed_fp, 6),
            "adaptive_mean_false_positive_share": round(adaptive_fp, 6),
            "false_positive_share_difference": round(
                adaptive_fp - fixed_fp, 6
            ),
            "quality_guardrails_observed": (
                adaptive_runtime_complete
                and adaptive_recall >= fixed_recall - 0.02
                and adaptive_fp <= fixed_fp + 0.03
                and sum(
                    bool(item.score.missed_red_line_defects)
                    for item in adaptive_outcomes
                )
                <= sum(
                    bool(item.score.missed_red_line_defects)
                    for item in reference
                )
            ),
        }
        if not adaptive_runtime_complete:
            quality["quality_guardrails_observed"] = None
            quality["note"] = (
                "At least one adaptive run ended at a budget, safety cap, "
                "or runtime boundary; quality guardrails are censored."
            )
        if scripted_dry_run:
            quality["quality_guardrails_observed"] = None
            quality["note"] = (
                "Scripted findings are infrastructure fixtures, not quality evidence."
            )

    fixed_tokens = fmean(item.usage.total_tokens for item in reference)
    adaptive_tokens = fmean(
        item.usage.total_tokens for item in adaptive_outcomes
    )
    if fixed_tokens <= 0:
        raise ValueError("fixed reference token usage must be positive")
    token_saving_rate = (fixed_tokens - adaptive_tokens) / fixed_tokens
    product_target_observed: bool | None
    if (
        scripted_dry_run
        or not quality.get("complete")
        or quality.get("quality_guardrails_observed") is None
    ):
        product_target_observed = None
    else:
        product_target_observed = bool(
            quality["quality_guardrails_observed"]
            and token_saving_rate >= 0.20
        )

    def arm_metrics(items: Sequence[Any]) -> dict[str, Any]:
        false_positive_values = [
            item.score.false_positive_share
            for item in items
            if item.score.false_positive_share is not None
        ]
        return {
            "trials": len(items),
            "mean_actual_agents": round(
                fmean(item.actual_total_agents for item in items), 6
            ),
            "mean_serious_recall": round(
                _pooled_defect_recall(items, serious=True), 6
            ),
            "mean_total_recall": round(
                _pooled_defect_recall(items, serious=False), 6
            ),
            "recall_aggregation": "micro_over_registered_defects",
            "found_all_registered_defects_rate": round(
                fmean(
                    item.score.found_known_defects
                    == item.score.total_known_defects
                    for item in items
                ),
                6,
            ),
            "mean_false_positive_share": (
                round(fmean(false_positive_values), 6)
                if false_positive_values
                else None
            ),
            "mean_input_tokens": round(
                fmean(item.usage.agent_input_tokens for item in items), 2
            ),
            "mean_cached_input_tokens": round(
                fmean(item.usage.cached_input_tokens for item in items), 2
            ),
            "mean_output_tokens": round(
                fmean(item.usage.agent_output_tokens for item in items), 2
            ),
            "mean_reasoning_tokens": round(
                fmean(item.usage.reasoning_output_tokens for item in items), 2
            ),
            "mean_total_tokens": round(
                fmean(item.usage.total_tokens for item in items), 2
            ),
            "mean_tool_calls": round(
                fmean(item.usage.tool_calls for item in items), 2
            ),
            "mean_agent_cumulative_time_seconds": round(
                fmean(item.usage.wall_time_seconds for item in items), 3
            ),
            "mean_wall_time_seconds": round(
                fmean(item.wall_time_seconds for item in items), 3
            ),
        }

    fixed_by_count: dict[int, list[TrialOutcome]] = {}
    for item in fixed_outcomes:
        fixed_by_count.setdefault(item.actual_total_agents, []).append(item)
    arms = {
        f"fixed-{count}": arm_metrics(items)
        for count, items in sorted(fixed_by_count.items())
    }
    adaptive_max_agents = max(
        item.trial.max_agents for item in adaptive_outcomes
    )
    arms[f"adaptive-max-{adaptive_max_agents}"] = arm_metrics(
        adaptive_outcomes
    )
    return {
        "status": "descriptive_only",
        "claim_allowed": False,
        "engineering_result": "inconclusive",
        "evaluation_mode": (
            "scripted_dry_run" if scripted_dry_run else "real"
        ),
        "real_experiment": not scripted_dry_run,
        "reference_agents": reference_agents,
        "paired_trials": len(reference),
        "adaptive_incomplete_runtime_trials": sum(
            item.execution_status != "completed"
            for item in adaptive_outcomes
        ),
        "adaptive_cap_censored_trials": sum(
            item.stop_reason == "cap_reached_incomplete"
            for item in adaptive_outcomes
        ),
        "adaptive_scale_observation": _scale_observation(adaptive_outcomes),
        "quality": quality,
        "fixed_mean_total_tokens": round(fixed_tokens, 2),
        "adaptive_mean_total_tokens": round(adaptive_tokens, 2),
        "arms": arms,
        "token_saving_rate": round(token_saving_rate, 6),
        "product_target": {
            "serious_recall_noninferiority_margin": -0.02,
            "false_positive_share_margin": 0.03,
            "minimum_token_saving_rate": 0.20,
            "cap_censored_allowed": False,
            "record_consistency_required": 1.0,
            "thresholds_observed_descriptively": product_target_observed,
            "claim_allowed": False,
        },
        "note": (
            "Pilot tasks are public and runtime-isolated only; this snapshot "
            "cannot establish holdout effectiveness."
        ),
    }
