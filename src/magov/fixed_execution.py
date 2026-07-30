"""Exact-count execution for controlled evaluation reference arms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .evaluation import UsageObservation
from .execution import (
    AgentRequest,
    AgentResult,
    AggregatedResult,
    Aggregator,
    ExecutionCheckpoint,
    ExecutionTask,
    Verifier,
    VerificationResult,
)
from .models import Mode, StopReason
from .telemetry import add_usage


@dataclass(frozen=True)
class FixedExecutionReport:
    run_id: str
    task_id: str
    status: str
    exact_total_agents: int
    actual_total_agents: int
    stop_reason: str
    aggregate: AggregatedResult
    verification: VerificationResult
    usage: UsageObservation
    agent_results: tuple[AgentResult, ...]
    checkpoints: tuple[ExecutionCheckpoint, ...]

    def __post_init__(self) -> None:
        if self.status not in {"completed", "incomplete"}:
            raise ValueError("status must be completed or incomplete")
        if self.exact_total_agents not in (1, 2, 3, 4):
            raise ValueError(
                "exact_total_agents must be one of 1, 2, 3, or 4"
            )
        if not 1 <= self.actual_total_agents <= self.exact_total_agents:
            raise ValueError(
                "actual_total_agents must be between 1 and the exact count"
            )
        if self.status == "completed" and (
            self.actual_total_agents != self.exact_total_agents
        ):
            raise ValueError(
                "a completed fixed run must reach the exact Agent count"
            )
        if [item.total_agents for item in self.checkpoints] != list(
            range(1, self.actual_total_agents + 1)
        ):
            raise ValueError(
                "fixed checkpoints must contain every attempted Agent count"
            )

    def to_dict(self, *, include_agent_output: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status,
            "exact_total_agents": self.exact_total_agents,
            "actual_total_agents": self.actual_total_agents,
            "stop_reason": self.stop_reason,
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
        }


class FixedCountController:
    """Run exactly N homogeneous Agents unless the runtime fails.

    This controller intentionally ignores quality targets and marginal-value
    stop rules.  It exists only to provide fixed-count evaluation reference
    arms against which the adaptive Governor can be compared.
    """

    def __init__(
        self,
        *,
        runtime,
        aggregator: Aggregator,
        verifier: Verifier,
    ) -> None:
        self.runtime = runtime
        self.aggregator = aggregator
        self.verifier = verifier

    @staticmethod
    def _role(agent_index: int, exact_total_agents: int) -> str:
        if exact_total_agents == 1:
            return "primary reviewer"
        if agent_index == 1:
            return "primary reviewer"
        return "independent reviewer"

    @staticmethod
    def _prompt(
        task: ExecutionTask,
        *,
        agent_index: int,
        exact_total_agents: int,
    ) -> str:
        role = FixedCountController._role(
            agent_index, exact_total_agents
        )
        return (
            task.prompt
            + f"\n\n本次固定数量对照组角色：{role}。"
            + (
                "\n请独立审查同一代码快照，不要假设其他 Agent 的结论正确。"
                if agent_index > 1
                else ""
            )
            + "\n只返回任务要求的结构化 JSON。"
        )

    @staticmethod
    def _run_safely(runtime, request: AgentRequest) -> AgentResult:
        try:
            return runtime.run_agent(request)
        except Exception as exc:
            return AgentResult(
                run_id=request.run_id,
                agent_index=request.agent_index,
                role=request.role,
                success=False,
                output="",
                usage=UsageObservation(0, 0),
                error=(
                    f"{type(exc).__name__} raised by Agent runtime: {exc}"
                ),
            )

    @staticmethod
    def _latest_agent_evidence(
        aggregate: AggregatedResult, agent_index: int
    ) -> set[str]:
        evidence_by_agent = aggregate.metadata.get(
            "evidence_by_agent", {}
        )
        if not isinstance(evidence_by_agent, Mapping):
            return set()
        values = evidence_by_agent.get(str(agent_index), ())
        if isinstance(values, (str, bytes)) or not isinstance(
            values, Sequence
        ):
            return set()
        return {str(item) for item in values}

    def execute(
        self,
        task: ExecutionTask,
        *,
        exact_total_agents: int,
        max_total_tokens: int | None = None,
        max_wall_time_seconds: float | None = None,
        max_tool_calls: int | None = None,
    ) -> FixedExecutionReport:
        if exact_total_agents not in (1, 2, 3, 4):
            raise ValueError(
                "exact_total_agents must be one of 1, 2, 3, or 4"
            )
        for name, value in (
            ("max_total_tokens", max_total_tokens),
            ("max_wall_time_seconds", max_wall_time_seconds),
            ("max_tool_calls", max_tool_calls),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        run_id = f"magov-fixed-{uuid4().hex[:12]}"
        results: list[AgentResult] = []
        checkpoints: list[ExecutionCheckpoint] = []
        previous_score = 0.0
        previous_evidence: set[str] = set()
        aggregate = AggregatedResult(content="")
        verification = VerificationResult(score=0.0, verified=False)
        status = "completed"
        stop_reason = "fixed_count_reached"

        for agent_index in range(1, exact_total_agents + 1):
            role = self._role(agent_index, exact_total_agents)
            request = AgentRequest(
                run_id=run_id,
                task_id=task.task_id,
                agent_index=agent_index,
                role=role,
                prompt=self._prompt(
                    task,
                    agent_index=agent_index,
                    exact_total_agents=exact_total_agents,
                ),
                working_directory=task.working_directory,
                mode=(
                    Mode.SINGLE
                    if exact_total_agents == 1
                    else Mode.INDEPENDENT
                ),
            )
            result = self._run_safely(self.runtime, request)
            results.append(result)
            cumulative_usage = add_usage(item.usage for item in results)

            if result.success:
                aggregate = self.aggregator.aggregate(task, results)
                verification = self.verifier.verify(
                    task, aggregate, results
                )
                current_evidence = set(verification.evidence_keys)
                latest_evidence = self._latest_agent_evidence(
                    aggregate, agent_index
                )
                if latest_evidence:
                    new_evidence = latest_evidence - previous_evidence
                    repeated_evidence = (
                        latest_evidence & previous_evidence
                    )
                else:
                    new_evidence = current_evidence - previous_evidence
                    repeated_evidence = set()
                marginal_gain = max(
                    0.0, verification.score - previous_score
                )
                safety_reason: StopReason | None = None
                if (
                    max_total_tokens is not None
                    and cumulative_usage.total_tokens >= max_total_tokens
                ):
                    safety_reason = StopReason.TOKEN_BUDGET_REACHED
                elif (
                    max_wall_time_seconds is not None
                    and cumulative_usage.wall_time_seconds
                    >= max_wall_time_seconds
                ):
                    safety_reason = StopReason.TIME_BUDGET_REACHED
                elif (
                    max_tool_calls is not None
                    and cumulative_usage.tool_calls >= max_tool_calls
                ):
                    safety_reason = StopReason.TOOL_BUDGET_REACHED
                is_final = agent_index == exact_total_agents
                checkpoints.append(
                    ExecutionCheckpoint(
                        total_agents=agent_index,
                        verification=verification,
                        cumulative_usage=cumulative_usage,
                        marginal_quality_gain=marginal_gain,
                        new_evidence_count=len(new_evidence),
                        repeated_evidence_count=len(repeated_evidence),
                        decision=(
                            "stop"
                            if is_final or safety_reason is not None
                            else "continue"
                        ),
                        stop_reason=(
                            safety_reason
                            or (
                                StopReason.PLANNED_CAP_REACHED
                                if is_final
                                else None
                            )
                        ),
                    )
                )
                previous_score = verification.score
                previous_evidence = current_evidence
                if safety_reason is not None:
                    status = "incomplete"
                    stop_reason = safety_reason.value
                    break
                continue

            status = "incomplete"
            stop_reason = "runtime_failure"
            verification = self.verifier.verify(task, aggregate, results)
            checkpoints.append(
                ExecutionCheckpoint(
                    total_agents=agent_index,
                    verification=verification,
                    cumulative_usage=cumulative_usage,
                    marginal_quality_gain=0.0,
                    new_evidence_count=0,
                    repeated_evidence_count=0,
                    decision="stop",
                    stop_reason=StopReason.RUNTIME_FAILURE,
                )
            )
            break

        return FixedExecutionReport(
            run_id=run_id,
            task_id=task.task_id,
            status=status,
            exact_total_agents=exact_total_agents,
            actual_total_agents=len(results),
            stop_reason=stop_reason,
            aggregate=aggregate,
            verification=verification,
            usage=add_usage(item.usage for item in results),
            agent_results=tuple(results),
            checkpoints=tuple(checkpoints),
        )
