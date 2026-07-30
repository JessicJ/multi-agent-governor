"""Deterministic and explainable scale-out policy."""

from __future__ import annotations

from math import sqrt
from typing import Sequence

from .models import (
    BaselineObservation,
    Budget,
    Candidate,
    Decision,
    DecisionTrace,
    Mode,
    RoundObservation,
    ScalingReview,
    StopReason,
    TaskSignals,
)


class Governor:
    """Decide whether additional agents are worth their coordination cost.

    The formulas are deliberately small and monotonic.  They are defaults, not
    claims of universal optimality: production users should calibrate weights
    against task outcomes and costs from their own runtime.
    """

    MIN_PARALLEL_FRACTION = 0.20
    HIGH_COUPLING = 0.78

    def decide(
        self,
        signals: TaskSignals,
        baseline: BaselineObservation,
        budget: Budget | None = None,
    ) -> Decision:
        budget = budget or Budget()
        trace = self._trace(signals)
        if baseline.hard_failure:
            trace.add(
                "baseline_hard_failure",
                1.0,
                "The baseline produced no usable result, so its verified "
                "confidence is treated as zero.",
            )

        if baseline.verified and baseline.confidence >= budget.target_confidence:
            return self._single(
                baseline,
                trace,
                StopReason.BASELINE_SUFFICIENT,
                "The verified baseline already meets the confidence target.",
            )

        verification_case = (
            signals.verification_value
            * signals.uncertainty
            * (1.0 - signals.failure_correlation)
        )
        parallel_case = (
            signals.parallel_fraction
            * signals.decomposition_confidence
            * min(1.0, (signals.parallelizable_units - 1) / 2)
        )

        if (
            signals.parallelizable_units < 2
            or signals.parallel_fraction < self.MIN_PARALLEL_FRACTION
        ) and verification_case < 0.18:
            return self._single(
                baseline,
                trace,
                StopReason.NOT_PARALLELIZABLE,
                "The task has neither useful parallel work nor a strong independent-verification case.",
            )

        coordination_pressure = self._coordination_pressure(signals)
        if (
            signals.context_coupling >= self.HIGH_COUPLING
            and coordination_pressure > 0.70
            and verification_case < 0.22
        ):
            return self._single(
                baseline,
                trace,
                StopReason.COORDINATION_DOMINATES,
                "Shared evolving context and aggregation work outweigh the available parallelism.",
            )

        if signals.failure_correlation > 0.88 and parallel_case < 0.20:
            return self._single(
                baseline,
                trace,
                StopReason.CORRELATED_ERRORS,
                "Extra agents are likely to repeat the same failure mode.",
            )

        mode = self._select_mode(signals)
        candidates: list[Candidate] = []
        confidence = baseline.confidence
        cost_multiplier = 1.0
        stop_reason = StopReason.AGENT_CAP_REACHED

        upper_bound = min(budget.max_agents, signals.parallelizable_units + 1)
        if verification_case >= 0.30:
            upper_bound = budget.max_agents

        for total_agents in range(2, upper_bound + 1):
            candidate = self._candidate(
                signals=signals,
                mode=mode,
                total_agents=total_agents,
                current_confidence=confidence,
                current_cost_multiplier=cost_multiplier,
                budget=budget,
            )

            if candidate.expected_cost_multiplier > budget.max_cost_multiplier:
                stop_reason = StopReason.COST_BUDGET_REACHED
                break
            if candidate.net_marginal_utility < budget.min_expected_gain:
                stop_reason = StopReason.MARGINAL_GAIN_TOO_LOW
                break

            candidates.append(candidate)
            confidence = candidate.expected_confidence
            cost_multiplier = candidate.expected_cost_multiplier

            if confidence >= budget.target_confidence:
                stop_reason = StopReason.TARGET_REACHED
                break
        else:
            stop_reason = StopReason.AGENT_CAP_REACHED

        if not candidates:
            return self._single(
                baseline,
                trace,
                stop_reason,
                "The first additional agent has negative or insufficient marginal utility.",
            )

        count = candidates[-1].total_agents
        topology = (
            "a coordinator with bounded workers"
            if mode is Mode.CENTRALIZED
            else "independent workers with final aggregation"
        )
        summary = (
            f"Use {count} total agents via {topology}; stop at the planned cap "
            f"or earlier when live evidence triggers a stop rule."
        )
        return Decision(
            mode=mode,
            total_agents=count,
            expected_confidence=round(confidence, 4),
            expected_cost_multiplier=round(cost_multiplier, 4),
            stop_reason=stop_reason,
            summary=summary,
            scores=tuple(trace.scores),
            candidates=tuple(candidates),
        )

    def review_scaling(
        self,
        plan: Decision,
        history: Sequence[RoundObservation],
        budget: Budget | None = None,
    ) -> ScalingReview:
        """Apply live stop rules after each admitted agent."""

        budget = budget or Budget()
        if not history:
            return ScalingReview(
                should_continue=plan.additional_agents > 0,
                stop_reason=None if plan.additional_agents > 0 else plan.stop_reason,
                next_total_agents=2 if plan.additional_agents > 0 else None,
                explanation="No scale-out round has been observed yet.",
            )

        latest = history[-1]
        if latest.confidence >= budget.target_confidence:
            return self._stop(
                StopReason.TARGET_REACHED,
                "Observed confidence reached the target.",
            )
        if latest.cost_multiplier >= budget.max_cost_multiplier:
            return self._stop(
                StopReason.COST_BUDGET_REACHED,
                "Observed cost reached the configured budget.",
            )
        if (
            budget.max_total_tokens is not None
            and latest.total_tokens >= budget.max_total_tokens
        ):
            return self._stop(
                StopReason.TOKEN_BUDGET_REACHED,
                "Observed tokens reached the configured budget.",
            )
        if (
            budget.max_wall_time_seconds is not None
            and latest.wall_time_seconds >= budget.max_wall_time_seconds
        ):
            return self._stop(
                StopReason.TIME_BUDGET_REACHED,
                "Observed wall time reached the configured budget.",
            )
        if (
            budget.max_tool_calls is not None
            and latest.tool_calls >= budget.max_tool_calls
        ):
            return self._stop(
                StopReason.TOOL_BUDGET_REACHED,
                "Observed tool calls reached the configured budget.",
            )
        if latest.total_agents >= budget.max_agents:
            return self._stop(
                StopReason.AGENT_CAP_REACHED,
                "The global agent cap was reached.",
            )
        if latest.total_agents >= plan.total_agents:
            return self._stop(
                StopReason.PLANNED_CAP_REACHED,
                "The governor's planned agent cap was reached.",
            )

        window = history[-budget.plateau_rounds :]
        if len(window) == budget.plateau_rounds and all(
            item.marginal_quality_gain < budget.min_observed_gain
            or item.novel_finding_ratio < 0.10
            for item in window
        ):
            return self._stop(
                StopReason.OBSERVED_PLATEAU,
                "Recent agents produced too little quality gain or new evidence.",
            )

        return ScalingReview(
            should_continue=True,
            stop_reason=None,
            next_total_agents=latest.total_agents + 1,
            explanation="Observed marginal value remains positive and within budget.",
        )

    def _trace(self, signals: TaskSignals) -> DecisionTrace:
        trace = DecisionTrace()
        parallel = (
            signals.parallel_fraction
            * signals.decomposition_confidence
            * min(1.0, signals.parallelizable_units / 3)
        )
        verification = (
            signals.uncertainty
            * signals.verification_value
            * (1 - signals.failure_correlation)
        )
        coordination = self._coordination_pressure(signals)
        trace.add(
            "parallel_opportunity",
            parallel,
            "Higher means the task contains separable work with a credible decomposition.",
        )
        trace.add(
            "independent_verification_value",
            verification,
            "Higher means another agent can catch errors instead of repeating them.",
        )
        trace.add(
            "coordination_pressure",
            coordination,
            "Higher means shared context and synthesis work make scale-out expensive.",
        )
        trace.add(
            "error_propagation_risk",
            signals.failure_correlation * signals.error_impact,
            "Higher means a shared mistake can spread across workers.",
        )
        return trace

    @staticmethod
    def _coordination_pressure(signals: TaskSignals) -> float:
        return (
            0.40 * signals.context_coupling
            + 0.25 * signals.shared_context_ratio
            + 0.25 * signals.aggregation_difficulty
            + 0.10 * signals.error_impact
        )

    @staticmethod
    def _select_mode(signals: TaskSignals) -> Mode:
        # Central coordination is useful when outputs must remain coherent or a
        # mistake is expensive.  Otherwise isolation preserves error diversity.
        if (
            signals.context_coupling >= 0.42
            or signals.aggregation_difficulty >= 0.58
            or signals.error_impact >= 0.72
        ):
            return Mode.CENTRALIZED
        return Mode.INDEPENDENT

    def _candidate(
        self,
        signals: TaskSignals,
        mode: Mode,
        total_agents: int,
        current_confidence: float,
        current_cost_multiplier: float,
        budget: Budget,
    ) -> Candidate:
        extra_index = total_agents - 1
        remaining_error = 1.0 - current_confidence

        coverage = (
            signals.parallel_fraction
            * signals.decomposition_confidence
            * (1.0 - 0.35 * signals.context_coupling)
        )
        verification = (
            signals.uncertainty
            * signals.verification_value
            * (1.0 - signals.failure_correlation)
        )
        mode_quality = (
            0.94 + 0.08 * signals.context_coupling
            if mode is Mode.CENTRALIZED
            else 1.02 - 0.28 * signals.context_coupling
        )
        diminishing_return = sqrt(extra_index)
        marginal_quality = (
            remaining_error
            * (0.48 * coverage + 0.52 * verification)
            * mode_quality
            / diminishing_return
        )

        if current_confidence < 0.25:
            # A failed baseline creates more upside, but the boost stays bounded.
            marginal_quality *= 1.15

        incremental_worker_cost = 1.0 + 0.35 * signals.shared_context_ratio
        coordination_increment = (
            0.08
            + 0.15 * signals.context_coupling
            + 0.08 * signals.aggregation_difficulty
            if mode is Mode.CENTRALIZED
            else 0.035 + 0.14 * signals.aggregation_difficulty
        )
        expected_cost = (
            current_cost_multiplier
            + incremental_worker_cost
            + coordination_increment
        )

        available_parallel_slots = max(1, signals.parallelizable_units)
        marginal_latency = (
            signals.parallel_fraction
            * min(1.0, available_parallel_slots / total_agents)
            / (total_agents * 1.5)
        )
        propagation_penalty = (
            signals.failure_correlation
            * signals.error_impact
            * (0.025 if mode is Mode.CENTRALIZED else 0.065)
            / diminishing_return
        )
        cost_penalty = (
            budget.cost_weight
            * (incremental_worker_cost + coordination_increment)
            / budget.max_cost_multiplier
        )
        net = (
            marginal_quality
            + budget.latency_weight * marginal_latency
            - propagation_penalty
            - cost_penalty
        )

        return Candidate(
            total_agents=total_agents,
            expected_confidence=round(
                min(0.995, current_confidence + marginal_quality), 4
            ),
            expected_cost_multiplier=round(expected_cost, 4),
            marginal_quality_gain=round(marginal_quality, 4),
            marginal_latency_gain=round(marginal_latency, 4),
            marginal_coordination_penalty=round(propagation_penalty, 4),
            marginal_cost_penalty=round(cost_penalty, 4),
            net_marginal_utility=round(net, 4),
        )

    @staticmethod
    def _single(
        baseline: BaselineObservation,
        trace: DecisionTrace,
        reason: StopReason,
        summary: str,
    ) -> Decision:
        return Decision(
            mode=Mode.SINGLE,
            total_agents=1,
            expected_confidence=baseline.confidence,
            expected_cost_multiplier=1.0,
            stop_reason=reason,
            summary=summary,
            scores=tuple(trace.scores),
        )

    @staticmethod
    def _stop(reason: StopReason, explanation: str) -> ScalingReview:
        return ScalingReview(
            should_continue=False,
            stop_reason=reason,
            next_total_agents=None,
            explanation=explanation,
        )
