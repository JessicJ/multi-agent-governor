"""Append-only receipts for advisory, externally executed Agent sessions.

The advisory path never claims to own Agent admission.  It records caller-
supplied observable evidence, asks the deterministic policy for the next
checkpoint decision, and preserves unavailable accounting fields as ``null``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import EvidenceFact, EvidenceSource
from .events import JsonlEventSink, RunEvent, load_events
from .models import (
    BaselineObservation,
    Budget,
    Decision,
    Mode,
    RoundObservation,
    ScalingReview,
    StopReason,
    TaskSignals,
)
from .policy import Governor


ADVISORY_SCHEMA_VERSION = "advisory-session-v1"
USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "model_calls",
    "tool_calls",
    "agent_time_seconds",
)
INCOMPLETE_STOP_REASONS = {
    StopReason.COST_BUDGET_REACHED,
    StopReason.TOKEN_BUDGET_REACHED,
    StopReason.TIME_BUDGET_REACHED,
    StopReason.TOOL_BUDGET_REACHED,
    StopReason.CAP_REACHED_INCOMPLETE,
    StopReason.RUNTIME_FAILURE,
}


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or null")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return value


def _optional_non_negative_float(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{name} must be a finite non-negative number or null")
    result = float(value)
    if result < 0:
        raise ValueError(f"{name} must be a finite non-negative number or null")
    return result


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, name)


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(_require_string(item, f"{name} item") for item in value)


@dataclass(frozen=True)
class AdvisoryUsage:
    """Per-Agent measured usage; ``None`` means unavailable, never zero."""

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    model_calls: int | None = None
    tool_calls: int | None = None
    agent_time_seconds: float | None = None

    def __post_init__(self) -> None:
        for name in USAGE_FIELDS[:-1]:
            _optional_non_negative_int(getattr(self, name), f"usage.{name}")
        _optional_non_negative_float(
            self.agent_time_seconds, "usage.agent_time_seconds"
        )
        if (
            self.cached_input_tokens is not None
            and self.input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if (
            self.reasoning_tokens is not None
            and self.output_tokens is not None
            and self.reasoning_tokens > self.output_tokens
        ):
            raise ValueError("reasoning_tokens cannot exceed output_tokens")
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("total_tokens must equal input_tokens + output_tokens")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "AdvisoryUsage":
        payload = payload or {}
        unknown = sorted(set(payload) - set(USAGE_FIELDS))
        if unknown:
            raise ValueError(f"unknown usage fields: {', '.join(unknown)}")
        values: dict[str, Any] = {
            name: payload.get(name) for name in USAGE_FIELDS
        }
        if (
            values["total_tokens"] is None
            and values["input_tokens"] is not None
            and values["output_tokens"] is not None
        ):
            values["total_tokens"] = (
                values["input_tokens"] + values["output_tokens"]
            )
        return cls(
            input_tokens=_optional_non_negative_int(
                values["input_tokens"], "usage.input_tokens"
            ),
            cached_input_tokens=_optional_non_negative_int(
                values["cached_input_tokens"], "usage.cached_input_tokens"
            ),
            output_tokens=_optional_non_negative_int(
                values["output_tokens"], "usage.output_tokens"
            ),
            reasoning_tokens=_optional_non_negative_int(
                values["reasoning_tokens"], "usage.reasoning_tokens"
            ),
            total_tokens=_optional_non_negative_int(
                values["total_tokens"], "usage.total_tokens"
            ),
            model_calls=_optional_non_negative_int(
                values["model_calls"], "usage.model_calls"
            ),
            tool_calls=_optional_non_negative_int(
                values["tool_calls"], "usage.tool_calls"
            ),
            agent_time_seconds=_optional_non_negative_float(
                values["agent_time_seconds"], "usage.agent_time_seconds"
            ),
        )

    def to_dict(self) -> dict[str, int | float | None]:
        return asdict(self)


def _parse_evidence(value: Any, name: str) -> tuple[EvidenceFact, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a non-empty evidence array")
    facts: list[EvidenceFact] = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"{name}[{index}] must be an object")
        try:
            source = EvidenceSource(str(item["source"]))
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{name}[{index}].source must be task, runtime, verifier, or policy"
            ) from exc
        facts.append(
            EvidenceFact(
                code=_require_string(item.get("code"), f"{name}[{index}].code"),
                statement=_require_string(
                    item.get("statement"), f"{name}[{index}].statement"
                ),
                source=source,
            )
        )
    if not facts:
        raise ValueError(f"{name} must contain at least one evidence fact")
    if all(fact.source is EvidenceSource.POLICY for fact in facts):
        raise ValueError(f"{name} must include non-policy observable evidence")
    return tuple(facts)


def _evidence_to_dict(facts: Sequence[EvidenceFact]) -> list[dict[str, str]]:
    return [
        {
            "code": fact.code,
            "statement": fact.statement,
            "source": fact.source.value,
        }
        for fact in facts
    ]


@dataclass(frozen=True)
class AdvisoryAgentObservation:
    agent_id: str
    total_agents: int
    contribution: str
    quality_score: float
    marginal_quality_gain: float
    novel_evidence_ratio: float
    coverage_complete: bool
    unresolved_conflicts: int
    evidence: tuple[EvidenceFact, ...]
    remaining_risks: tuple[str, ...] = ()
    usage: AdvisoryUsage = AdvisoryUsage()
    model_id: str | None = None
    cumulative_cost_multiplier: float | None = None
    cumulative_wall_time_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_string(self.agent_id, "agent_id")
        _require_string(self.contribution, "contribution")
        if type(self.total_agents) is not int or self.total_agents < 2:
            raise ValueError("total_agents must be an integer of at least 2")
        for name in ("quality_score", "novel_evidence_ratio"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not isfinite(self.marginal_quality_gain):
            raise ValueError("marginal_quality_gain must be finite")
        _require_bool(self.coverage_complete, "coverage_complete")
        if (
            type(self.unresolved_conflicts) is not int
            or self.unresolved_conflicts < 0
        ):
            raise ValueError("unresolved_conflicts must be a non-negative integer")
        if not self.evidence:
            raise ValueError("checkpoint evidence cannot be empty")
        if self.model_id is not None:
            _require_string(self.model_id, "model_id")
        if (
            self.cumulative_cost_multiplier is not None
            and (
                not isfinite(self.cumulative_cost_multiplier)
                or self.cumulative_cost_multiplier <= 0
            )
        ):
            raise ValueError("cumulative_cost_multiplier must be positive or null")
        _optional_non_negative_float(
            self.cumulative_wall_time_seconds,
            "cumulative_wall_time_seconds",
        )

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "AdvisoryAgentObservation":
        usage_payload = payload.get("usage")
        if usage_payload is not None and not isinstance(usage_payload, Mapping):
            raise ValueError("usage must be an object")
        return cls(
            agent_id=_require_string(payload.get("agent_id"), "agent_id"),
            total_agents=_require_int(
                payload.get("total_agents"), "total_agents", minimum=2
            ),
            contribution=_require_string(
                payload.get("contribution"), "contribution"
            ),
            quality_score=float(payload.get("quality_score")),
            marginal_quality_gain=float(payload.get("marginal_quality_gain")),
            novel_evidence_ratio=float(payload.get("novel_evidence_ratio")),
            coverage_complete=_require_bool(
                payload.get("coverage_complete"), "coverage_complete"
            ),
            unresolved_conflicts=_require_int(
                payload.get("unresolved_conflicts"),
                "unresolved_conflicts",
            ),
            evidence=_parse_evidence(payload.get("evidence"), "evidence"),
            remaining_risks=_string_tuple(
                payload.get("remaining_risks"), "remaining_risks"
            ),
            usage=AdvisoryUsage.from_dict(usage_payload),
            model_id=_optional_string(payload.get("model_id"), "model_id"),
            cumulative_cost_multiplier=_optional_non_negative_float(
                payload.get("cumulative_cost_multiplier"),
                "cumulative_cost_multiplier",
            ),
            cumulative_wall_time_seconds=_optional_non_negative_float(
                payload.get("cumulative_wall_time_seconds"),
                "cumulative_wall_time_seconds",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_agents": self.total_agents,
            "contribution": self.contribution,
            "quality_score": self.quality_score,
            "marginal_quality_gain": self.marginal_quality_gain,
            "novel_evidence_ratio": self.novel_evidence_ratio,
            "coverage_complete": self.coverage_complete,
            "unresolved_conflicts": self.unresolved_conflicts,
            "evidence": _evidence_to_dict(self.evidence),
            "remaining_risks": list(self.remaining_risks),
            "usage": self.usage.to_dict(),
            "model_id": self.model_id,
            "cumulative_cost_multiplier": self.cumulative_cost_multiplier,
            "cumulative_wall_time_seconds": self.cumulative_wall_time_seconds,
        }


def _aggregate_usage(usages: Sequence[AdvisoryUsage]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    missing: list[str] = []
    for name in USAGE_FIELDS:
        values = [getattr(usage, name) for usage in usages]
        if any(value is None for value in values):
            result[name] = None
            missing.append(name)
        else:
            total = sum(values)
            result[name] = round(total, 6) if name.endswith("_seconds") else total
    result["missing_fields"] = missing
    result["complete"] = not missing
    return result


def _decision_from_dict(payload: Mapping[str, Any]) -> Decision:
    return Decision(
        mode=Mode(str(payload["mode"])),
        total_agents=int(payload["total_agents"]),
        expected_confidence=float(payload["expected_confidence"]),
        expected_cost_multiplier=float(payload["expected_cost_multiplier"]),
        stop_reason=StopReason(str(payload["stop_reason"])),
        summary=str(payload["summary"]),
    )


def _review_observations(
    start: RunEvent,
    observations: Sequence[AdvisoryAgentObservation],
) -> tuple[ScalingReview, dict[str, Any], tuple[str, ...]]:
    usages = [
        AdvisoryUsage.from_dict(start.data.get("baseline_usage"))
    ] + [item.usage for item in observations]
    cumulative_usage = _aggregate_usage(usages)
    plan = _decision_from_dict(start.data["plan"])
    budget = Budget(**dict(start.data["budget"]))
    history = [
        RoundObservation(
            total_agents=item.total_agents,
            confidence=item.quality_score,
            cost_multiplier=item.cumulative_cost_multiplier,
            marginal_quality_gain=item.marginal_quality_gain,
            novel_finding_ratio=item.novel_evidence_ratio,
            total_tokens=_aggregate_usage(usages[: index + 2])[
                "total_tokens"
            ],
            wall_time_seconds=item.cumulative_wall_time_seconds,
            tool_calls=_aggregate_usage(usages[: index + 2])["tool_calls"],
            coverage_complete=item.coverage_complete,
            unresolved_conflicts=item.unresolved_conflicts,
        )
        for index, item in enumerate(observations)
    ]
    review = Governor(str(start.data["policy_version"])).review_scaling(
        plan, history, budget
    )
    latest = observations[-1]
    unavailable: list[str] = []
    if latest.cumulative_cost_multiplier is None:
        unavailable.append("cost_multiplier")
    if (
        budget.max_total_tokens is not None
        and cumulative_usage["total_tokens"] is None
    ):
        unavailable.append("total_tokens")
    if (
        budget.max_wall_time_seconds is not None
        and latest.cumulative_wall_time_seconds is None
    ):
        unavailable.append("wall_time_seconds")
    if (
        budget.max_tool_calls is not None
        and cumulative_usage["tool_calls"] is None
    ):
        unavailable.append("tool_calls")
    return review, cumulative_usage, tuple(unavailable)


def _review_decision_fields(
    review: ScalingReview,
    observation: AdvisoryAgentObservation,
    unavailable: Sequence[str],
) -> tuple[str, int, str]:
    if review.should_continue:
        action = "add_agent"
        recommended = review.next_total_agents or observation.total_agents + 1
        if unavailable:
            explanation = (
                "Observed marginal evidence permits another Agent. "
                "Unavailable hard-budget fields were not treated as zero and "
                f"could not be evaluated: {', '.join(unavailable)}."
            )
        else:
            explanation = review.explanation
    else:
        action = (
            "incomplete_stop"
            if review.stop_reason in INCOMPLETE_STOP_REASONS
            else "stop"
        )
        recommended = observation.total_agents
        explanation = review.explanation
    return action, recommended, explanation


def _decision_payload(
    *,
    action: str,
    current_agents: int,
    recommended_total_agents: int,
    stop_reason: StopReason | None,
    explanation: str,
    evidence: Sequence[EvidenceFact],
    remaining_risks: Sequence[str],
    usage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "action": action,
        "current_agents": current_agents,
        "recommended_total_agents": recommended_total_agents,
        "stop_reason": stop_reason.value if stop_reason is not None else None,
        "explanation": explanation,
        "evidence": _evidence_to_dict(evidence),
        "remaining_risks": list(remaining_risks),
        "usage": dict(usage),
    }


def _event_span_seconds(events: Sequence[RunEvent]) -> float:
    if len(events) < 2:
        return 0.0
    start = datetime.fromisoformat(events[0].occurred_at)
    end = datetime.fromisoformat(events[-1].occurred_at)
    return round(max(0.0, (end - start).total_seconds()), 6)


def _append_event(path: Path, event: RunEvent) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                event.to_dict(), ensure_ascii=False, allow_nan=False
            )
            + "\n"
        )
        stream.flush()


def _validate_advisory_events(
    events: Sequence[RunEvent],
) -> tuple[RunEvent, tuple[RunEvent, ...]]:
    if not events:
        raise ValueError("advisory event log is empty")
    run_ids = {event.run_id for event in events}
    task_ids = {event.task_id for event in events}
    if len(run_ids) != 1 or len(task_ids) != 1:
        raise ValueError("one advisory log must contain one session and task")
    start = events[0]
    if start.event_type != "advisory_started":
        raise ValueError("advisory log must start with advisory_started")
    if start.data.get("schema_version") != ADVISORY_SCHEMA_VERSION:
        raise ValueError("unsupported advisory session schema version")
    if (
        start.data.get("enforcement") != "advisory_only"
        or start.data.get("runtime_enforced") is not False
    ):
        raise ValueError("advisory runtime boundary does not match the schema")
    checkpoints = tuple(events[1:])
    for index, event in enumerate(checkpoints, 2):
        if event.event_type != "advisory_checkpoint":
            raise ValueError("advisory logs may only contain checkpoint events")
        if event.data.get("schema_version") != ADVISORY_SCHEMA_VERSION:
            raise ValueError("unsupported advisory checkpoint schema version")
        observation = event.data.get("observation")
        if not isinstance(observation, Mapping):
            raise ValueError(f"advisory checkpoint {index} has no observation")
        if int(observation.get("total_agents", 0)) != index:
            raise ValueError(
                "advisory checkpoints must increment total_agents by one"
            )
    return start, checkpoints


def _validate_replayed_decisions(
    start: RunEvent, checkpoints: Sequence[RunEvent]
) -> None:
    policy_version = str(start.data["policy_version"])
    expected_plan = Governor(policy_version).decide(
        TaskSignals(**dict(start.data["signals"])),
        BaselineObservation(**dict(start.data["baseline"])),
        Budget(**dict(start.data["budget"])),
    )
    stored_plan = dict(start.data["plan"])
    expected_plan_fields = {
        "mode": expected_plan.mode.value,
        "total_agents": expected_plan.total_agents,
        "expected_confidence": expected_plan.expected_confidence,
        "expected_cost_multiplier": expected_plan.expected_cost_multiplier,
        "stop_reason": expected_plan.stop_reason.value,
        "summary": expected_plan.summary,
    }
    if any(
        stored_plan.get(name) != value
        for name, value in expected_plan_fields.items()
    ):
        raise ValueError("stored advisory plan does not match deterministic replay")
    start_decision = start.data.get("decision")
    if not isinstance(start_decision, Mapping):
        raise ValueError("advisory start has no decision")
    if expected_plan.total_agents == 1:
        start_action = "single"
        start_recommended = 1
        start_stop_reason = expected_plan.stop_reason
        start_explanation = expected_plan.summary
    else:
        start_action = "start_multi"
        start_recommended = 2
        start_stop_reason = None
        start_explanation = (
            "Advisory plan recommends scale-out; admit only the next Agent "
            "and record a checkpoint before any later admission."
        )
    start_expected = _decision_payload(
        action=start_action,
        current_agents=1,
        recommended_total_agents=start_recommended,
        stop_reason=start_stop_reason,
        explanation=start_explanation,
        evidence=_parse_evidence(
            start.data.get("baseline_evidence"), "baseline_evidence"
        ),
        remaining_risks=_string_tuple(
            start.data.get("remaining_risks"), "remaining_risks"
        ),
        usage=AdvisoryUsage.from_dict(
            start.data.get("baseline_usage")
        ).to_dict(),
    )
    if dict(start_decision) != start_expected:
        raise ValueError("stored advisory start decision does not match replay")

    observations: list[AdvisoryAgentObservation] = []
    stopped = expected_plan.total_agents == 1
    seen_agent_ids = {"baseline"}
    known_models = {
        str(start.data["model_id"]) if start.data.get("model_id") else ""
    } - {""}
    previous_cost: float | None = None
    previous_wall = _optional_non_negative_float(
        start.data.get("wall_time_seconds"), "wall_time_seconds"
    )
    for event in checkpoints:
        if stopped:
            raise ValueError("advisory log contains a checkpoint after stop")
        observation = AdvisoryAgentObservation.from_dict(
            event.data["observation"]
        )
        if observation.agent_id in seen_agent_ids:
            raise ValueError("advisory agent_id values must be unique")
        seen_agent_ids.add(observation.agent_id)
        if observation.model_id:
            known_models.add(observation.model_id)
        if len(known_models) > 1:
            raise ValueError("advisory session must use one homogeneous model")
        if (
            previous_cost is not None
            and observation.cumulative_cost_multiplier is not None
            and observation.cumulative_cost_multiplier < previous_cost
        ):
            raise ValueError("cumulative_cost_multiplier cannot decrease")
        if observation.cumulative_cost_multiplier is not None:
            previous_cost = observation.cumulative_cost_multiplier
        if (
            previous_wall is not None
            and observation.cumulative_wall_time_seconds is not None
            and observation.cumulative_wall_time_seconds < previous_wall
        ):
            raise ValueError("cumulative_wall_time_seconds cannot decrease")
        if observation.cumulative_wall_time_seconds is not None:
            previous_wall = observation.cumulative_wall_time_seconds
        observations.append(observation)
        review, cumulative_usage, unavailable = _review_observations(
            start, observations
        )
        action, recommended, explanation = _review_decision_fields(
            review, observation, unavailable
        )
        stored = event.data.get("decision")
        if not isinstance(stored, Mapping):
            raise ValueError("advisory checkpoint has no decision")
        policy_fact = EvidenceFact(
            code="policy_checkpoint_decision",
            statement=explanation,
            source=EvidenceSource.POLICY,
        )
        expected = _decision_payload(
            action=action,
            current_agents=observation.total_agents,
            recommended_total_agents=recommended,
            stop_reason=review.stop_reason,
            explanation=explanation,
            evidence=(*observation.evidence, policy_fact),
            remaining_risks=observation.remaining_risks,
            usage=cumulative_usage,
        )
        if dict(stored) != expected:
            raise ValueError(
                "stored advisory checkpoint decision does not match replay"
            )
        stopped = not review.should_continue


def start_advisory_session(
    payload: Mapping[str, Any], events_path: Path
) -> dict[str, Any]:
    session = payload.get("session")
    if not isinstance(session, Mapping):
        raise ValueError("advisory start input requires a session object")
    session_id = _require_string(session.get("session_id"), "session.session_id")
    task_id = _require_string(session.get("task_id"), "session.task_id")
    model_id = _optional_string(session.get("model_id"), "session.model_id")
    policy = payload.get("policy")
    if not isinstance(policy, Mapping) or not policy.get("version"):
        raise ValueError("advisory start requires an explicit policy.version")
    policy_version = str(policy["version"])
    signals = TaskSignals(**dict(payload.get("signals", {})))
    baseline = BaselineObservation(**dict(payload["baseline"]))
    budget = Budget(**dict(payload.get("budget", {})))
    evidence = _parse_evidence(
        payload.get("baseline_evidence"), "baseline_evidence"
    )
    remaining_risks = _string_tuple(
        payload.get("remaining_risks"), "remaining_risks"
    )
    usage_payload = payload.get("baseline_usage")
    if usage_payload is not None and not isinstance(usage_payload, Mapping):
        raise ValueError("baseline_usage must be an object")
    baseline_usage = AdvisoryUsage.from_dict(usage_payload)
    baseline_wall_time = _optional_non_negative_float(
        session.get("wall_time_seconds"), "session.wall_time_seconds"
    )
    plan = Governor(policy_version).decide(signals, baseline, budget)
    if plan.total_agents == 1:
        action = "single"
        actual_stop = plan.stop_reason
        recommended = 1
        explanation = plan.summary
    else:
        action = "start_multi"
        actual_stop = None
        recommended = 2
        explanation = (
            "Advisory plan recommends scale-out; admit only the next Agent "
            "and record a checkpoint before any later admission."
        )
    decision = _decision_payload(
        action=action,
        current_agents=1,
        recommended_total_agents=recommended,
        stop_reason=actual_stop,
        explanation=explanation,
        evidence=evidence,
        remaining_risks=remaining_risks,
        usage=baseline_usage.to_dict(),
    )
    data = {
        "schema_version": ADVISORY_SCHEMA_VERSION,
        "enforcement": "advisory_only",
        "runtime_enforced": False,
        "policy_version": policy_version,
        "model_id": model_id,
        "signals": asdict(signals),
        "baseline": asdict(baseline),
        "budget": asdict(budget),
        "baseline_evidence": _evidence_to_dict(evidence),
        "remaining_risks": list(remaining_risks),
        "baseline_usage": baseline_usage.to_dict(),
        "wall_time_seconds": baseline_wall_time,
        "plan": plan.to_dict(),
        "decision": decision,
    }
    sink = JsonlEventSink(events_path)
    sink.record(
        RunEvent.create(
            sequence=1,
            run_id=session_id,
            task_id=task_id,
            event_type="advisory_started",
            data=data,
        )
    )
    return advisory_report(events_path)


def append_advisory_checkpoint(
    events_path: Path, payload: Mapping[str, Any]
) -> dict[str, Any]:
    events = load_events(events_path)
    start, checkpoints = _validate_advisory_events(events)
    current = advisory_report(events_path)
    if current["status"] != "active":
        raise ValueError("cannot append a checkpoint after an advisory stop")
    observation = AdvisoryAgentObservation.from_dict(payload)
    expected_agents = 2 + len(checkpoints)
    if observation.total_agents != expected_agents:
        raise ValueError(
            f"checkpoint total_agents must be {expected_agents}"
        )
    known_models = {
        str(item)
        for item in [start.data.get("model_id")]
        + [
            event.data["observation"].get("model_id")
            for event in checkpoints
        ]
        if item
    }
    if observation.model_id is not None:
        known_models.add(observation.model_id)
    if len(known_models) > 1:
        raise ValueError("advisory session must use one homogeneous model")

    observations = [
        AdvisoryAgentObservation.from_dict(event.data["observation"])
        for event in checkpoints
    ] + [observation]
    review, cumulative_usage, unavailable = _review_observations(
        start, observations
    )
    stop_reason = review.stop_reason
    action, recommended, explanation = _review_decision_fields(
        review, observation, unavailable
    )
    policy_fact = EvidenceFact(
        code="policy_checkpoint_decision",
        statement=explanation,
        source=EvidenceSource.POLICY,
    )
    decision = _decision_payload(
        action=action,
        current_agents=observation.total_agents,
        recommended_total_agents=recommended,
        stop_reason=stop_reason,
        explanation=explanation,
        evidence=(*observation.evidence, policy_fact),
        remaining_risks=observation.remaining_risks,
        usage=cumulative_usage,
    )
    _append_event(
        events_path,
        RunEvent.create(
            sequence=len(events) + 1,
            run_id=start.run_id,
            task_id=start.task_id,
            event_type="advisory_checkpoint",
            data={
                "schema_version": ADVISORY_SCHEMA_VERSION,
                "observation": observation.to_dict(),
                "decision": decision,
            },
        ),
    )
    return advisory_report(events_path)


def advisory_report(events_path: Path) -> dict[str, Any]:
    events = load_events(events_path)
    start, checkpoints = _validate_advisory_events(events)
    _validate_replayed_decisions(start, checkpoints)
    plan = dict(start.data["plan"])
    checkpoint_payloads = [
        {
            "total_agents": 1,
            "agent_id": "baseline",
            "model_id": start.data.get("model_id"),
            "evidence": list(start.data["baseline_evidence"]),
            "remaining_risks": list(start.data["remaining_risks"]),
            "usage": dict(start.data["baseline_usage"]),
            "decision": dict(start.data["decision"]),
        }
    ]
    observations: list[AdvisoryAgentObservation] = []
    for event in checkpoints:
        observation = AdvisoryAgentObservation.from_dict(
            event.data["observation"]
        )
        observations.append(observation)
        checkpoint_payloads.append(
            {
                **observation.to_dict(),
                "decision": dict(event.data["decision"]),
            }
        )
    usages = [
        AdvisoryUsage.from_dict(start.data.get("baseline_usage"))
    ] + [item.usage for item in observations]
    usage = _aggregate_usage(usages)
    last_decision = checkpoint_payloads[-1]["decision"]
    active = last_decision["action"] in {"start_multi", "add_agent"}
    final_stop_reason = (
        None if active else last_decision.get("stop_reason")
    )
    if active:
        status = "active"
    elif (
        final_stop_reason is not None
        and StopReason(final_stop_reason) in INCOMPLETE_STOP_REASONS
    ):
        status = "incomplete"
    else:
        status = "completed"
    model_ids = [
        item
        for item in [start.data.get("model_id")]
        + [observation.model_id for observation in observations]
        if item is not None
    ]
    model_complete = len(model_ids) == 1 + len(observations)
    if not model_complete:
        homogeneous_model_verified: bool | None = None
    else:
        homogeneous_model_verified = len(set(model_ids)) == 1
    hard_budget_evidence = {
        "cost_multiplier": (
            observations[-1].cumulative_cost_multiplier
            if observations
            else None
        ),
        "total_tokens": usage["total_tokens"],
        "wall_time_seconds": (
            observations[-1].cumulative_wall_time_seconds
            if observations
            else start.data.get("wall_time_seconds")
        ),
        "tool_calls": usage["tool_calls"],
    }
    limitations = [
        "Agent admission occurred outside a Governor-owned runtime.",
        "Checkpoint evidence is caller-supplied and must be independently auditable.",
    ]
    if not usage["complete"]:
        limitations.append(
            "One or more usage fields are unavailable; missing values remain null."
        )
    if homogeneous_model_verified is None:
        limitations.append("Homogeneous model identity could not be fully verified.")
    return {
        "schema_version": ADVISORY_SCHEMA_VERSION,
        "session_id": start.run_id,
        "task_id": start.task_id,
        "status": status,
        "enforcement": "advisory_only",
        "runtime_enforced": False,
        "policy_version": start.data["policy_version"],
        "mode": plan["mode"],
        "total_agent_cap": start.data["budget"]["max_agents"],
        "planned_total_agents": plan["total_agents"],
        "actual_total_agents": 1 + len(observations),
        "plan_stop_reason": plan["stop_reason"],
        "final_stop_reason": final_stop_reason,
        "next_total_agents": (
            last_decision["recommended_total_agents"] if active else None
        ),
        "homogeneous_model_verified": homogeneous_model_verified,
        "usage": usage,
        "hard_budget_evidence": hard_budget_evidence,
        "recorded_event_span_seconds": _event_span_seconds(events),
        "checkpoints": checkpoint_payloads,
        "limitations": limitations,
    }
