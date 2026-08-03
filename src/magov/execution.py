"""Runtime-agnostic adaptive execution loop.

The policy remains deterministic.  This module owns the admission capability:
it runs the baseline, asks a verifier for observable evidence, admits at most
one additional homogeneous Agent at a checkpoint, and stops the runtime when
the policy or a hard budget says to stop.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .events import EventSink, MemoryEventSink, RunEvent
from .evidence import (
    DecisionAction,
    DecisionReceipt,
    EvidenceFact,
    EvidenceSource,
)
from .evaluation import UsageObservation
from .models import (
    BaselineObservation,
    Budget,
    Decision,
    Mode,
    RoundObservation,
    StopReason,
    TaskSignals,
)
from .policy import Governor
from .telemetry import add_usage


@dataclass(frozen=True)
class WorkUnit:
    work_unit_id: str
    instruction: str
    scope: tuple[str, ...] = ()
    high_risk: bool = False

    def __post_init__(self) -> None:
        if not self.work_unit_id.strip() or not self.instruction.strip():
            raise ValueError("work unit id and instruction cannot be empty")
        if type(self.high_risk) is not bool:
            raise ValueError("work unit high_risk must be a boolean")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkUnit":
        return cls(
            work_unit_id=str(payload["work_unit_id"]),
            instruction=str(payload["instruction"]),
            scope=tuple(str(item) for item in payload.get("scope", ())),
            high_risk=payload.get("high_risk", False),
        )


@dataclass(frozen=True)
class ExecutionTask:
    task_id: str
    prompt: str
    working_directory: Path
    signals: TaskSignals
    work_units: tuple[WorkUnit, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.prompt.strip():
            raise ValueError("task id and prompt cannot be empty")
        directory = self.working_directory.resolve()
        if not directory.is_dir():
            raise ValueError(
                f"working directory does not exist: {self.working_directory}"
            )
        object.__setattr__(self, "working_directory", directory)
        work_unit_ids = [item.work_unit_id for item in self.work_units]
        if len(work_unit_ids) != len(set(work_unit_ids)):
            raise ValueError("work unit ids must be unique")

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, base_directory: Path | None = None
    ) -> "ExecutionTask":
        directory = Path(str(payload["working_directory"]))
        if not directory.is_absolute() and base_directory is not None:
            directory = base_directory / directory
        return cls(
            task_id=str(payload["task_id"]),
            prompt=str(payload["prompt"]),
            working_directory=directory,
            signals=TaskSignals(**dict(payload.get("signals", {}))),
            work_units=tuple(
                WorkUnit.from_dict(item)
                for item in payload.get("work_units", ())
            ),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(frozen=True)
class AgentRequest:
    run_id: str
    task_id: str
    agent_index: int
    role: str
    prompt: str
    working_directory: Path
    mode: Mode
    work_unit: WorkUnit | None = None

    def __post_init__(self) -> None:
        if self.agent_index < 1:
            raise ValueError("agent_index must be at least 1")
        for name in ("run_id", "task_id", "role", "prompt"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")
        directory = self.working_directory.resolve()
        if not directory.is_dir():
            raise ValueError(
                f"Agent working directory does not exist: "
                f"{self.working_directory}"
            )
        object.__setattr__(self, "working_directory", directory)


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    agent_index: int
    role: str
    success: bool
    output: str
    usage: UsageObservation
    error: str = ""
    trace_path: str = ""

    def __post_init__(self) -> None:
        if self.agent_index < 1:
            raise ValueError("agent_index must be at least 1")
        if not self.run_id.strip() or not self.role.strip():
            raise ValueError("run_id and role cannot be empty")
        if type(self.success) is not bool:
            raise ValueError("Agent result success must be a boolean")
        if self.success and self.error:
            raise ValueError("a successful Agent result cannot include an error")
        if not self.success and not self.error.strip():
            raise ValueError("a failed Agent result must include an error")

    def to_dict(self, *, include_output: bool = True) -> dict[str, Any]:
        result = {
            "run_id": self.run_id,
            "agent_index": self.agent_index,
            "role": self.role,
            "success": self.success,
            "usage": self.usage.to_dict(),
            "error": self.error,
            "trace_path": self.trace_path,
        }
        if include_output:
            result["output"] = self.output
        return result


@dataclass(frozen=True)
class AggregatedResult:
    content: str
    evidence_keys: tuple[str, ...] = ()
    reviewed_files: tuple[str, ...] = ()
    independently_reviewed_files: tuple[str, ...] = ()
    unresolved_conflicts: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.unresolved_conflicts < 0:
            raise ValueError("unresolved_conflicts cannot be negative")
        for name in (
            "evidence_keys",
            "reviewed_files",
            "independently_reviewed_files",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} cannot contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "evidence_keys": list(self.evidence_keys),
            "reviewed_files": list(self.reviewed_files),
            "independently_reviewed_files": list(
                self.independently_reviewed_files
            ),
            "unresolved_conflicts": self.unresolved_conflicts,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class VerificationResult:
    score: float
    verified: bool
    hard_failure: bool = False
    coverage_complete: bool = False
    evidence_keys: tuple[str, ...] = ()
    reviewed_files: tuple[str, ...] = ()
    independently_reviewed_files: tuple[str, ...] = ()
    independently_reviewed_high_risk_files: tuple[str, ...] = ()
    unresolved_conflicts: int = 0
    remaining_risks: tuple[str, ...] = ()
    explanation: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("verification score must be between 0 and 1")
        for name in ("verified", "hard_failure", "coverage_complete"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.hard_failure and self.verified:
            raise ValueError("a hard verification failure cannot be verified")
        if self.hard_failure and self.score != 0.0:
            raise ValueError("a hard verification failure must have score zero")
        if self.unresolved_conflicts < 0:
            raise ValueError("unresolved_conflicts cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentRuntime(Protocol):
    def run_agent(self, request: AgentRequest) -> AgentResult:
        """Run exactly one Agent and return its measured result."""


class Aggregator(Protocol):
    def aggregate(
        self, task: ExecutionTask, results: Sequence[AgentResult]
    ) -> AggregatedResult:
        """Merge successful Agent results without consulting hidden truth."""


class Verifier(Protocol):
    def verify(
        self,
        task: ExecutionTask,
        aggregate: AggregatedResult,
        results: Sequence[AgentResult],
    ) -> VerificationResult:
        """Score current observable evidence without model self-confidence."""


SignalProvider = Callable[
    [ExecutionTask, BaselineObservation, VerificationResult], TaskSignals
]


class ConcatenatingAggregator:
    """Framework-neutral fallback that preserves every successful output."""

    def aggregate(
        self, task: ExecutionTask, results: Sequence[AgentResult]
    ) -> AggregatedResult:
        del task
        outputs = [
            f"## Agent {result.agent_index} ({result.role})\n{result.output}"
            for result in results
            if result.success and result.output.strip()
        ]
        return AggregatedResult(content="\n\n".join(outputs))


class JsonFindingsAggregator:
    """Deterministically merge the structured Python-review response shape."""

    @staticmethod
    def _payload(output: str) -> Mapping[str, Any] | None:
        try:
            payload = json.loads(output.strip())
        except (json.JSONDecodeError, TypeError):
            return None
        return payload if isinstance(payload, Mapping) else None

    def aggregate(
        self, task: ExecutionTask, results: Sequence[AgentResult]
    ) -> AggregatedResult:
        del task
        merged_findings: list[dict[str, Any]] = []
        evidence_keys: set[str] = set()
        reviewed_by: dict[str, set[int]] = {}
        evidence_by_agent: dict[int, list[str]] = {}
        conflicts = 0
        invalid_results: list[int] = []

        for result in results:
            if not result.success:
                continue
            payload = self._payload(result.output)
            if payload is None:
                invalid_results.append(result.agent_index)
                continue
            reviewed_files = payload.get("reviewed_files", ())
            if isinstance(reviewed_files, list):
                for filename in reviewed_files:
                    reviewed_by.setdefault(str(filename), set()).add(
                        result.agent_index
                    )
            try:
                conflicts += max(0, int(payload.get("unresolved_conflicts", 0)))
            except (TypeError, ValueError):
                conflicts += 1
            findings = payload.get("findings", ())
            if not isinstance(findings, list):
                invalid_results.append(result.agent_index)
                continue
            for item in findings:
                if not isinstance(item, Mapping):
                    continue
                key = "|".join(
                    str(item.get(name, "")).strip()
                    for name in ("file", "symbol", "root_cause_category")
                )
                if not key.strip("|") or key in evidence_keys:
                    if key.strip("|"):
                        evidence_by_agent.setdefault(
                            result.agent_index, []
                        ).append(key)
                    continue
                evidence_keys.add(key)
                evidence_by_agent.setdefault(result.agent_index, []).append(key)
                merged_findings.append(dict(item))

        reviewed = tuple(sorted(reviewed_by))
        independent = tuple(
            sorted(
                filename
                for filename, agent_ids in reviewed_by.items()
                if len(agent_ids) >= 2
            )
        )
        content = json.dumps(
            {
                "findings": merged_findings,
                "reviewed_files": list(reviewed),
                "independently_reviewed_files": list(independent),
                "unresolved_conflicts": conflicts,
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        return AggregatedResult(
            content=content,
            evidence_keys=tuple(sorted(evidence_keys)),
            reviewed_files=reviewed,
            independently_reviewed_files=independent,
            unresolved_conflicts=conflicts,
            metadata={
                "findings": merged_findings,
                "invalid_agent_results": invalid_results,
                "evidence_by_agent": {
                    str(agent_index): sorted(set(keys))
                    for agent_index, keys in evidence_by_agent.items()
                },
            },
        )


class ReviewEvidenceVerifier:
    """Process verifier for structured code review.

    It deliberately does not claim correctness.  It scores observable changed
    file coverage, policy-versioned independent review coverage, and unresolved
    conflicts. Hidden truth remains reserved for offline evaluation.
    """

    def __init__(self, policy_version: str = "pilot-v1") -> None:
        if policy_version not in Governor.SUPPORTED_POLICY_VERSIONS:
            raise ValueError(
                f"unsupported review verifier policy version: {policy_version}"
            )
        self.policy_version = policy_version

    def verify(
        self,
        task: ExecutionTask,
        aggregate: AggregatedResult,
        results: Sequence[AgentResult],
    ) -> VerificationResult:
        successful = [result for result in results if result.success]
        if not successful:
            return VerificationResult(
                score=0.0,
                verified=False,
                hard_failure=True,
                remaining_risks=("No Agent produced a usable result.",),
                explanation="All Agent attempts failed.",
            )

        changed_files = {
            str(item) for item in task.metadata.get("changed_files", ())
        }
        high_risk_files = {
            str(item) for item in task.metadata.get("high_risk_files", ())
        }
        reviewed = set(aggregate.reviewed_files)
        independently_reviewed = set(aggregate.independently_reviewed_files)

        file_coverage = (
            len(changed_files & reviewed) / len(changed_files)
            if changed_files
            else 0.0
        )
        high_risk_coverage = (
            len(high_risk_files & independently_reviewed)
            / len(high_risk_files)
            if high_risk_files
            else 1.0
        )
        independent_changed_coverage = (
            len(changed_files & independently_reviewed) / len(changed_files)
            if changed_files
            else 0.0
        )
        conflict_score = 1.0 if aggregate.unresolved_conflicts == 0 else 0.0
        if self.policy_version == "pilot-v2":
            score = (
                0.45 * file_coverage
                + 0.30 * independent_changed_coverage
                + 0.15 * high_risk_coverage
                + 0.10 * conflict_score
            )
            coverage_complete = (
                changed_files.issubset(reviewed)
                and changed_files.issubset(independently_reviewed)
                and high_risk_files.issubset(independently_reviewed)
                and aggregate.unresolved_conflicts == 0
            )
        else:
            score = (
                0.65 * file_coverage
                + 0.25 * high_risk_coverage
                + 0.10 * conflict_score
            )
            coverage_complete = (
                changed_files.issubset(reviewed)
                and high_risk_files.issubset(independently_reviewed)
                and aggregate.unresolved_conflicts == 0
            )
        remaining: list[str] = []
        if not changed_files:
            remaining.append(
                "Task metadata does not declare any changed_files to verify."
            )
            coverage_complete = False
        for filename in sorted(changed_files - reviewed):
            remaining.append(f"Changed file not reviewed: {filename}")
        if self.policy_version == "pilot-v2":
            for filename in sorted(changed_files - independently_reviewed):
                remaining.append(
                    f"Changed file lacks independent review: {filename}"
                )
        for filename in sorted(high_risk_files - independently_reviewed):
            remaining.append(
                f"High-risk file lacks independent review: {filename}"
            )
        if aggregate.unresolved_conflicts:
            remaining.append(
                f"{aggregate.unresolved_conflicts} unresolved conflict(s)."
            )
        invalid = aggregate.metadata.get("invalid_agent_results", ())
        if invalid:
            remaining.append(
                "Unparseable structured result from Agent(s): "
                + ", ".join(str(item) for item in invalid)
            )
            score = min(score, 0.80)
            coverage_complete = False

        return VerificationResult(
            score=round(score, 6),
            verified=False,
            coverage_complete=coverage_complete,
            evidence_keys=aggregate.evidence_keys,
            reviewed_files=aggregate.reviewed_files,
            independently_reviewed_files=tuple(
                sorted(changed_files & independently_reviewed)
            ),
            independently_reviewed_high_risk_files=tuple(
                sorted(high_risk_files & independently_reviewed)
            ),
            unresolved_conflicts=aggregate.unresolved_conflicts,
            remaining_risks=tuple(remaining),
            explanation=(
                "Score is based on observable review coverage, independent "
                + (
                    "changed-file review, independent high-risk review, "
                    if self.policy_version == "pilot-v2"
                    else "high-risk review, "
                )
                + "and unresolved conflicts; it is not model self-confidence "
                "or hidden-truth correctness."
            ),
        )


@dataclass(frozen=True)
class ExecutionCheckpoint:
    total_agents: int
    verification: VerificationResult
    cumulative_usage: UsageObservation
    marginal_quality_gain: float
    new_evidence_count: int
    repeated_evidence_count: int
    decision: str
    stop_reason: StopReason | None = None

    @property
    def novel_evidence_ratio(self) -> float:
        total = self.new_evidence_count + self.repeated_evidence_count
        return self.new_evidence_count / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_agents": self.total_agents,
            "verification": self.verification.to_dict(),
            "cumulative_usage": self.cumulative_usage.to_dict(),
            "marginal_quality_gain": self.marginal_quality_gain,
            "new_evidence_count": self.new_evidence_count,
            "repeated_evidence_count": self.repeated_evidence_count,
            "novel_evidence_ratio": round(self.novel_evidence_ratio, 6),
            "decision": self.decision,
            "stop_reason": (
                self.stop_reason.value if self.stop_reason is not None else None
            ),
        }


@dataclass(frozen=True)
class ExecutionReport:
    run_id: str
    task_id: str
    status: str
    plan: Decision
    actual_total_agents: int
    stop_reason: StopReason
    aggregate: AggregatedResult
    verification: VerificationResult
    usage: UsageObservation
    agent_results: tuple[AgentResult, ...]
    checkpoints: tuple[ExecutionCheckpoint, ...]
    receipts: tuple[DecisionReceipt, ...]
    event_count: int
    wall_time_seconds: float
    policy_version: str

    def __post_init__(self) -> None:
        if self.status not in {"completed", "incomplete"}:
            raise ValueError("status must be completed or incomplete")
        if not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        incomplete_reasons = {
            StopReason.COST_BUDGET_REACHED,
            StopReason.TOKEN_BUDGET_REACHED,
            StopReason.TIME_BUDGET_REACHED,
            StopReason.TOOL_BUDGET_REACHED,
            StopReason.CAP_REACHED_INCOMPLETE,
            StopReason.RUNTIME_FAILURE,
        }
        if self.stop_reason in incomplete_reasons and self.status != "incomplete":
            raise ValueError(
                "budget-, cap-, and failure-limited reports must be incomplete"
            )

    def to_dict(self, *, include_agent_output: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status,
            "plan": self.plan.to_dict(),
            "actual_total_agents": self.actual_total_agents,
            "stop_reason": self.stop_reason.value,
            "aggregate": self.aggregate.to_dict(),
            "verification": self.verification.to_dict(),
            "usage": self.usage.to_dict(),
            "agent_results": [
                result.to_dict(include_output=include_agent_output)
                for result in self.agent_results
            ],
            "checkpoints": [
                checkpoint.to_dict() for checkpoint in self.checkpoints
            ],
            "receipts": [receipt.to_dict() for receipt in self.receipts],
            "event_count": self.event_count,
            "wall_time_seconds": self.wall_time_seconds,
            "policy_version": self.policy_version,
        }


class AdaptiveController:
    """Own Agent admission and enforce the Governor after every result."""

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        verifier: Verifier,
        aggregator: Aggregator | None = None,
        governor: Governor | None = None,
        signal_provider: SignalProvider | None = None,
        event_sink: EventSink | None = None,
        governance_tokens: int = 0,
    ) -> None:
        if governance_tokens < 0:
            raise ValueError("governance_tokens cannot be negative")
        self.runtime = runtime
        self.verifier = verifier
        self.aggregator = aggregator or ConcatenatingAggregator()
        self.governor = governor or Governor()
        self.signal_provider = signal_provider
        self.event_sink = event_sink or MemoryEventSink()
        self.governance_tokens = governance_tokens
        self._event_sequence = 0

    def _record(
        self,
        *,
        run_id: str,
        task_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._event_sequence += 1
        self.event_sink.record(
            RunEvent.create(
                sequence=self._event_sequence,
                run_id=run_id,
                task_id=task_id,
                event_type=event_type,
                data=data,
            )
        )

    @staticmethod
    def _work_unit(task: ExecutionTask, agent_index: int) -> WorkUnit | None:
        if not task.work_units:
            return None
        return task.work_units[(agent_index - 2) % len(task.work_units)]

    @staticmethod
    def _request_prompt(
        task: ExecutionTask,
        *,
        agent_index: int,
        mode: Mode,
        work_unit: WorkUnit | None,
    ) -> str:
        if agent_index == 1:
            return task.prompt
        if mode is Mode.INDEPENDENT:
            return (
                task.prompt
                + "\n\n你是独立复核 Agent。请独立完成任务，不要假设其他 "
                "Agent 的结论正确，并只返回任务要求的结构化结果。"
            )
        scope = ""
        if work_unit is not None:
            scope = (
                f"\n工作单元：{work_unit.work_unit_id}"
                f"\n目标：{work_unit.instruction}"
            )
            if work_unit.scope:
                scope += "\n范围：" + ", ".join(work_unit.scope)
        return (
            task.prompt
            + "\n\n你是中心协调模式下的有边界工作 Agent。"
            "只完成分配的工作单元，并返回可由协调者确定性合并的结构化结果。"
            + scope
        )

    @staticmethod
    def _role(agent_index: int, mode: Mode) -> str:
        if agent_index == 1:
            return "primary reviewer"
        return (
            "independent reviewer"
            if mode is Mode.INDEPENDENT
            else "bounded worker"
        )

    def _run_agent_safely(self, request: AgentRequest) -> AgentResult:
        try:
            return self.runtime.run_agent(request)
        except Exception as exc:
            return AgentResult(
                run_id=request.run_id,
                agent_index=request.agent_index,
                role=request.role,
                success=False,
                output="",
                usage=UsageObservation(
                    agent_input_tokens=0,
                    agent_output_tokens=0,
                ),
                error=(
                    f"{type(exc).__name__} raised by Agent runtime: {exc}"
                ),
            )

    @staticmethod
    def _usage_with_governance(
        results: Sequence[AgentResult], governance_tokens: int
    ) -> UsageObservation:
        usage = add_usage(result.usage for result in results)
        return UsageObservation(
            agent_input_tokens=usage.agent_input_tokens,
            agent_output_tokens=usage.agent_output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            reasoning_output_tokens=usage.reasoning_output_tokens,
            governance_tokens=governance_tokens,
            model_calls=usage.model_calls,
            tool_calls=usage.tool_calls,
            wall_time_seconds=usage.wall_time_seconds,
        )

    def _receipt(
        self,
        *,
        run_id: str,
        task_id: str,
        action: DecisionAction,
        current_agents: int,
        budget: Budget,
        recommended_total_agents: int,
        statement: str,
        source: EvidenceSource,
        remaining_risks: tuple[str, ...],
        usage: UsageObservation,
    ) -> DecisionReceipt:
        return DecisionReceipt(
            decision_id=f"{run_id}-d{current_agents}",
            task_id=task_id,
            action=action,
            current_agents=current_agents,
            max_agents=budget.max_agents,
            recommended_total_agents=recommended_total_agents,
            reasons=(
                EvidenceFact(
                    code=action.value,
                    statement=statement,
                    source=source,
                ),
            ),
            remaining_risks=remaining_risks,
            governance_tokens=usage.governance_tokens,
            total_task_tokens=usage.total_tokens,
            policy_version=self.governor.policy_version,
        )

    @staticmethod
    def _hard_budget_reason(
        usage: UsageObservation, budget: Budget
    ) -> StopReason | None:
        if (
            budget.max_total_tokens is not None
            and usage.total_tokens >= budget.max_total_tokens
        ):
            return StopReason.TOKEN_BUDGET_REACHED
        if (
            budget.max_wall_time_seconds is not None
            and usage.wall_time_seconds >= budget.max_wall_time_seconds
        ):
            return StopReason.TIME_BUDGET_REACHED
        if (
            budget.max_tool_calls is not None
            and usage.tool_calls >= budget.max_tool_calls
        ):
            return StopReason.TOOL_BUDGET_REACHED
        return None

    @staticmethod
    def _is_incomplete_stop(reason: StopReason) -> bool:
        return reason in {
            StopReason.COST_BUDGET_REACHED,
            StopReason.TOKEN_BUDGET_REACHED,
            StopReason.TIME_BUDGET_REACHED,
            StopReason.TOOL_BUDGET_REACHED,
            StopReason.CAP_REACHED_INCOMPLETE,
            StopReason.RUNTIME_FAILURE,
        }

    @classmethod
    def _is_incomplete_outcome(
        cls,
        reason: StopReason,
        verification: VerificationResult,
    ) -> bool:
        """Return whether a terminal decision leaves public proof incomplete.

        A marginal-value stop can be the correct cost decision without proving
        that the requested review coverage was achieved.  Preserve that
        distinction in the report instead of treating an economical stop as a
        completed verification.
        """

        return cls._is_incomplete_stop(reason) or not verification.coverage_complete

    @staticmethod
    def _runtime_stop_reason(
        reason: StopReason,
        verification: VerificationResult,
        budget: Budget,
    ) -> StopReason:
        if reason is not StopReason.AGENT_CAP_REACHED:
            return reason
        if (
            verification.coverage_complete
            and verification.score >= budget.target_confidence
        ):
            return StopReason.TARGET_REACHED
        return StopReason.CAP_REACHED_INCOMPLETE

    def execute(
        self, task: ExecutionTask, budget: Budget | None = None
    ) -> ExecutionReport:
        budget = budget or Budget()
        self._run_started_at = monotonic()
        run_id = f"magov-{uuid4().hex[:12]}"
        self._event_sequence = 0
        results: list[AgentResult] = []
        checkpoints: list[ExecutionCheckpoint] = []
        receipts: list[DecisionReceipt] = []
        self._record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="run_started",
            data={
                "max_agents": budget.max_agents,
                "policy_version": self.governor.policy_version,
            },
        )

        baseline_request = AgentRequest(
            run_id=run_id,
            task_id=task.task_id,
            agent_index=1,
            role=self._role(1, Mode.SINGLE),
            prompt=self._request_prompt(
                task,
                agent_index=1,
                mode=Mode.SINGLE,
                work_unit=None,
            ),
            working_directory=task.working_directory,
            mode=Mode.SINGLE,
        )
        self._record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="agent_started",
            data={"agent_index": 1, "role": baseline_request.role},
        )
        baseline_result = self._run_agent_safely(baseline_request)
        results.append(baseline_result)
        self._record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="agent_completed",
            data=baseline_result.to_dict(include_output=False),
        )

        aggregate = self.aggregator.aggregate(task, results)
        verification = self.verifier.verify(task, aggregate, results)
        self._record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="verification_completed",
            data=verification.to_dict(),
        )
        baseline = BaselineObservation(
            confidence=verification.score,
            verified=verification.verified,
            hard_failure=verification.hard_failure,
            cost_units=max(1.0, float(baseline_result.usage.total_tokens)),
            latency_seconds=baseline_result.usage.wall_time_seconds,
        )
        signals = (
            self.signal_provider(task, baseline, verification)
            if self.signal_provider is not None
            else replace(
                task.signals,
                uncertainty=max(
                    task.signals.uncertainty, 1.0 - verification.score
                ),
            )
        )
        plan = self.governor.decide(signals, baseline, budget)
        initial_stop_reason = self._runtime_stop_reason(
            plan.stop_reason, verification, budget
        )
        usage = self._usage_with_governance(
            results, self.governance_tokens
        )
        if not baseline_result.success:
            initial_action = DecisionAction.INCOMPLETE_STOP
            initial_statement = (
                "The mandatory baseline Agent failed, so no additional Agent "
                "was admitted."
            )
        elif (
            plan.mode is Mode.SINGLE
            and self._is_incomplete_outcome(
                initial_stop_reason, verification
            )
        ):
            initial_action = DecisionAction.INCOMPLETE_STOP
            initial_statement = (
                "The run stopped before public verification coverage was "
                "complete, so no completed-verification claim is made."
            )
        else:
            initial_action = (
                DecisionAction.SINGLE
                if plan.mode is Mode.SINGLE
                else DecisionAction.START_MULTI
            )
            initial_statement = plan.summary
        receipts.append(
            self._receipt(
                run_id=run_id,
                task_id=task.task_id,
                action=initial_action,
                current_agents=1,
                budget=budget,
                recommended_total_agents=plan.total_agents,
                statement=initial_statement,
                source=(
                    EvidenceSource.RUNTIME
                    if not baseline_result.success
                    else EvidenceSource.POLICY
                ),
                remaining_risks=verification.remaining_risks,
                usage=usage,
            )
        )
        self._record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="scale_decision",
            data=receipts[-1].to_dict(),
        )
        checkpoints.append(
            ExecutionCheckpoint(
                total_agents=1,
                verification=verification,
                cumulative_usage=usage,
                marginal_quality_gain=verification.score,
                new_evidence_count=len(verification.evidence_keys),
                repeated_evidence_count=0,
                decision=(
                    "stop"
                    if not baseline_result.success or plan.mode is Mode.SINGLE
                    else "continue"
                ),
                stop_reason=(
                    StopReason.RUNTIME_FAILURE
                    if not baseline_result.success
                    else (
                        initial_stop_reason
                        if plan.mode is Mode.SINGLE
                        else None
                    )
                ),
            )
        )

        if not baseline_result.success:
            return self._finish(
                run_id=run_id,
                task=task,
                status="incomplete",
                plan=plan,
                stop_reason=StopReason.RUNTIME_FAILURE,
                results=results,
                aggregate=aggregate,
                verification=verification,
                usage=usage,
                checkpoints=checkpoints,
                receipts=receipts,
            )

        if plan.mode is Mode.SINGLE:
            return self._finish(
                run_id=run_id,
                task=task,
                status=(
                    "incomplete"
                    if self._is_incomplete_outcome(
                        initial_stop_reason, verification
                    )
                    else "completed"
                ),
                plan=plan,
                stop_reason=initial_stop_reason,
                results=results,
                aggregate=aggregate,
                verification=verification,
                usage=usage,
                checkpoints=checkpoints,
                receipts=receipts,
            )

        initial_budget_reason = self._hard_budget_reason(usage, budget)
        if initial_budget_reason is not None:
            checkpoints[-1] = ExecutionCheckpoint(
                total_agents=1,
                verification=verification,
                cumulative_usage=usage,
                marginal_quality_gain=verification.score,
                new_evidence_count=len(verification.evidence_keys),
                repeated_evidence_count=0,
                decision="stop",
                stop_reason=initial_budget_reason,
            )
            receipts.append(
                self._receipt(
                    run_id=run_id,
                    task_id=task.task_id,
                    action=DecisionAction.INCOMPLETE_STOP,
                    current_agents=1,
                    budget=budget,
                    recommended_total_agents=1,
                    statement=(
                        "The mandatory baseline exhausted a configured hard "
                        "runtime budget, so no additional Agent was admitted."
                    ),
                    source=EvidenceSource.RUNTIME,
                    remaining_risks=verification.remaining_risks,
                    usage=usage,
                )
            )
            self._record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="scale_decision",
                data=receipts[-1].to_dict(),
            )
            return self._finish(
                run_id=run_id,
                task=task,
                status="incomplete",
                plan=plan,
                stop_reason=initial_budget_reason,
                results=results,
                aggregate=aggregate,
                verification=verification,
                usage=usage,
                checkpoints=checkpoints,
                receipts=receipts,
            )

        previous_score = verification.score
        previous_evidence = set(verification.evidence_keys)
        history: list[RoundObservation] = []
        stop_reason = plan.stop_reason
        status = "completed"
        execution_cap = (
            budget.max_agents
            if self.governor.policy_version == "pilot-v2"
            else plan.total_agents
        )

        for agent_index in range(2, execution_cap + 1):
            budget_reason = self._hard_budget_reason(usage, budget)
            if budget_reason is not None:
                stop_reason = budget_reason
                status = "incomplete"
                break

            work_unit = self._work_unit(task, agent_index)
            request = AgentRequest(
                run_id=run_id,
                task_id=task.task_id,
                agent_index=agent_index,
                role=self._role(agent_index, plan.mode),
                prompt=self._request_prompt(
                    task,
                    agent_index=agent_index,
                    mode=plan.mode,
                    work_unit=work_unit,
                ),
                working_directory=task.working_directory,
                mode=plan.mode,
                work_unit=work_unit,
            )
            self._record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="agent_admitted",
                data={
                    "agent_index": agent_index,
                    "role": request.role,
                    "work_unit": (
                        work_unit.work_unit_id if work_unit is not None else None
                    ),
                },
            )
            result = self._run_agent_safely(request)
            results.append(result)
            self._record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="agent_completed",
                data=result.to_dict(include_output=False),
            )
            usage = self._usage_with_governance(
                results, self.governance_tokens
            )
            if not result.success:
                stop_reason = StopReason.RUNTIME_FAILURE
                status = "incomplete"
                verification = self.verifier.verify(task, aggregate, results)
                checkpoint = ExecutionCheckpoint(
                    total_agents=len(results),
                    verification=verification,
                    cumulative_usage=usage,
                    marginal_quality_gain=0.0,
                    new_evidence_count=0,
                    repeated_evidence_count=0,
                    decision="stop",
                    stop_reason=stop_reason,
                )
                checkpoints.append(checkpoint)
                receipts.append(
                    self._receipt(
                        run_id=run_id,
                        task_id=task.task_id,
                        action=DecisionAction.INCOMPLETE_STOP,
                        current_agents=len(results),
                        budget=budget,
                        recommended_total_agents=len(results),
                        statement=(
                            "The admitted Agent failed, so adaptive execution "
                            "stopped without admitting another Agent."
                        ),
                        source=EvidenceSource.RUNTIME,
                        remaining_risks=verification.remaining_risks,
                        usage=usage,
                    )
                )
                self._record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="checkpoint",
                    data=checkpoint.to_dict(),
                )
                self._record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="scale_decision",
                    data=receipts[-1].to_dict(),
                )
                break

            aggregate = self.aggregator.aggregate(task, results)
            verification = self.verifier.verify(task, aggregate, results)
            current_evidence = set(verification.evidence_keys)
            evidence_by_agent = aggregate.metadata.get(
                "evidence_by_agent", {}
            )
            if isinstance(evidence_by_agent, Mapping):
                latest_agent_evidence = {
                    str(item)
                    for item in evidence_by_agent.get(
                        str(agent_index), ()
                    )
                }
            else:
                latest_agent_evidence = set()
            if latest_agent_evidence:
                new_evidence = latest_agent_evidence - previous_evidence
                repeated_evidence = (
                    latest_agent_evidence & previous_evidence
                )
            else:
                new_evidence = current_evidence - previous_evidence
                repeated_evidence = set()
            marginal_gain = max(0.0, verification.score - previous_score)
            cost_multiplier = usage.total_tokens / max(
                1.0, baseline_result.usage.total_tokens
            )
            observation = RoundObservation(
                total_agents=len(results),
                confidence=verification.score,
                cost_multiplier=cost_multiplier,
                marginal_quality_gain=marginal_gain,
                novel_finding_ratio=(
                    len(new_evidence)
                    / max(1, len(new_evidence) + len(repeated_evidence))
                ),
                total_tokens=usage.total_tokens,
                wall_time_seconds=usage.wall_time_seconds,
                tool_calls=usage.tool_calls,
                coverage_complete=verification.coverage_complete,
                unresolved_conflicts=verification.unresolved_conflicts,
            )
            history.append(observation)
            review = self.governor.review_scaling(plan, history, budget)
            stop_reason = review.stop_reason or plan.stop_reason
            incomplete_outcome = self._is_incomplete_outcome(
                stop_reason, verification
            )
            if (
                not review.should_continue
                and incomplete_outcome
            ):
                status = "incomplete"
            checkpoint = ExecutionCheckpoint(
                total_agents=len(results),
                verification=verification,
                cumulative_usage=usage,
                marginal_quality_gain=marginal_gain,
                new_evidence_count=len(new_evidence),
                repeated_evidence_count=len(repeated_evidence),
                decision="continue" if review.should_continue else "stop",
                stop_reason=review.stop_reason,
            )
            checkpoints.append(checkpoint)
            action = (
                DecisionAction.ADD_AGENT
                if review.should_continue
                else (
                    DecisionAction.INCOMPLETE_STOP
                    if incomplete_outcome
                    else DecisionAction.STOP
                )
            )
            receipts.append(
                self._receipt(
                    run_id=run_id,
                    task_id=task.task_id,
                    action=action,
                    current_agents=len(results),
                    budget=budget,
                    recommended_total_agents=(
                        review.next_total_agents
                        if review.next_total_agents is not None
                        else len(results)
                    ),
                    statement=review.explanation,
                    source=EvidenceSource.RUNTIME,
                    remaining_risks=verification.remaining_risks,
                    usage=usage,
                )
            )
            self._record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="checkpoint",
                data=checkpoint.to_dict(),
            )
            self._record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="scale_decision",
                data=receipts[-1].to_dict(),
            )
            if not review.should_continue:
                break
            previous_score = verification.score
            previous_evidence = current_evidence

        return self._finish(
            run_id=run_id,
            task=task,
            status=status,
            plan=plan,
            stop_reason=stop_reason,
            results=results,
            aggregate=aggregate,
            verification=verification,
            usage=usage,
            checkpoints=checkpoints,
            receipts=receipts,
        )

    def _finish(
        self,
        *,
        run_id: str,
        task: ExecutionTask,
        status: str,
        plan: Decision,
        stop_reason: StopReason,
        results: Sequence[AgentResult],
        aggregate: AggregatedResult,
        verification: VerificationResult,
        usage: UsageObservation,
        checkpoints: Sequence[ExecutionCheckpoint],
        receipts: Sequence[DecisionReceipt],
    ) -> ExecutionReport:
        self._record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="run_completed",
            data={
                "status": status,
                "actual_total_agents": len(results),
                "stop_reason": stop_reason.value,
                "policy_version": self.governor.policy_version,
                "usage": usage.to_dict(),
                "verification": verification.to_dict(),
            },
        )
        return ExecutionReport(
            run_id=run_id,
            task_id=task.task_id,
            status=status,
            plan=plan,
            actual_total_agents=len(results),
            stop_reason=stop_reason,
            aggregate=aggregate,
            verification=verification,
            usage=usage,
            agent_results=tuple(results),
            checkpoints=tuple(checkpoints),
            receipts=tuple(receipts),
            event_count=self._event_sequence,
            wall_time_seconds=monotonic() - self._run_started_at,
            policy_version=self.governor.policy_version,
        )
