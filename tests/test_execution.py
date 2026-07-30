from __future__ import annotations

import json
import tempfile
import unittest
from collections import deque
from pathlib import Path

from magov import (
    AdaptiveController,
    AgentResult,
    Budget,
    ExecutionTask,
    Governor,
    JsonFindingsAggregator,
    MemoryEventSink,
    ReviewEvidenceVerifier,
    StopReason,
    TaskSignals,
    UsageObservation,
    VerificationResult,
)
from magov.adapters import ScriptedRuntime


def usage(tokens: int = 100) -> UsageObservation:
    return UsageObservation(
        agent_input_tokens=tokens - 10,
        agent_output_tokens=10,
        model_calls=1,
        wall_time_seconds=1.0,
    )


def review_result(
    agent_index: int,
    *,
    findings: list[dict[str, str]] | None = None,
    reviewed_files: list[str] | None = None,
    success: bool = True,
) -> AgentResult:
    return AgentResult(
        run_id="scripted",
        agent_index=agent_index,
        role="scripted",
        success=success,
        output=json.dumps(
            {
                "findings": findings or [],
                "reviewed_files": reviewed_files or [],
                "unresolved_conflicts": 0,
            }
        ),
        usage=usage(),
        error="" if success else "scripted failure",
    )


class SequenceVerifier:
    def __init__(self, results: list[VerificationResult]) -> None:
        self.results = deque(results)

    def verify(self, task, aggregate, results) -> VerificationResult:
        del task, aggregate, results
        return self.results.popleft()


class RaisingRuntime:
    def run_agent(self, request):
        del request
        raise RuntimeError("runtime unavailable")


class AdaptiveControllerTests(unittest.TestCase):
    def _task(
        self,
        directory: Path,
        *,
        high_risk_files: tuple[str, ...] = (),
    ) -> ExecutionTask:
        return ExecutionTask(
            task_id="review-task",
            prompt="Review the changed files and return structured JSON.",
            working_directory=directory,
            signals=TaskSignals(
                parallelizable_units=6,
                parallel_fraction=0.9,
                decomposition_confidence=0.9,
                context_coupling=0.15,
                shared_context_ratio=0.2,
                uncertainty=0.9,
                verification_value=0.9,
                failure_correlation=0.1,
                aggregation_difficulty=0.2,
            ),
            metadata={
                "changed_files": ["auth.py"],
                "high_risk_files": list(high_risk_files),
            },
        )

    def test_high_risk_review_scales_once_then_stops_on_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [
                    review_result(1, reviewed_files=["auth.py"]),
                    review_result(
                        2,
                        findings=[
                            {
                                "finding_id": "F-1",
                                "file": "auth.py",
                                "symbol": "authorize",
                                "root_cause_category": "missing-check",
                                "impact": "Unauthorized access",
                                "evidence": "The branch bypasses the role check.",
                            }
                        ],
                        reviewed_files=["auth.py"],
                    ),
                ]
            )
            sink = MemoryEventSink()
            report = AdaptiveController(
                runtime=runtime,
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier(),
                event_sink=sink,
            ).execute(
                self._task(Path(directory), high_risk_files=("auth.py",)),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=6,
                    target_confidence=0.95,
                    min_expected_gain=0.005,
                ),
            )

        self.assertEqual(report.actual_total_agents, 2)
        self.assertEqual(report.stop_reason, StopReason.TARGET_REACHED)
        self.assertTrue(report.verification.coverage_complete)
        self.assertEqual(
            report.verification.independently_reviewed_high_risk_files,
            ("auth.py",),
        )
        self.assertEqual([item.agent_index for item in runtime.requests], [1, 2])
        self.assertEqual(
            [event.sequence for event in sink.events],
            list(range(1, len(sink.events) + 1)),
        )

    def test_pilot_v2_requires_independent_changed_file_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [
                    review_result(1, reviewed_files=["auth.py"]),
                    review_result(2, reviewed_files=["auth.py"]),
                ]
            )
            sink = MemoryEventSink()
            report = AdaptiveController(
                runtime=runtime,
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier("pilot-v2"),
                governor=Governor("pilot-v2"),
                event_sink=sink,
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=6,
                    target_confidence=0.95,
                    min_expected_gain=0.005,
                ),
            )

        self.assertEqual(report.policy_version, "pilot-v2")
        self.assertEqual(report.actual_total_agents, 2)
        self.assertFalse(report.checkpoints[0].verification.coverage_complete)
        self.assertTrue(report.verification.coverage_complete)
        self.assertEqual(
            report.verification.independently_reviewed_files,
            ("auth.py",),
        )
        self.assertTrue(
            all(
                receipt.policy_version == "pilot-v2"
                for receipt in report.receipts
            )
        )
        self.assertEqual(
            sink.events[0].data["policy_version"], "pilot-v2"
        )

    def test_observed_plateau_stops_before_planned_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [review_result(index) for index in range(1, 5)]
            )
            verifier = SequenceVerifier(
                [
                    VerificationResult(
                        score=0.30,
                        verified=False,
                        evidence_keys=("baseline",),
                    ),
                    VerificationResult(
                        score=0.31,
                        verified=False,
                        evidence_keys=("baseline",),
                    ),
                    VerificationResult(
                        score=0.315,
                        verified=False,
                        evidence_keys=("baseline",),
                    ),
                ]
            )
            report = AdaptiveController(
                runtime=runtime,
                verifier=verifier,
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=6,
                    max_cost_multiplier=8,
                    target_confidence=0.98,
                    min_expected_gain=0.005,
                    plateau_rounds=2,
                ),
            )

        self.assertEqual(report.actual_total_agents, 3)
        self.assertEqual(report.stop_reason, StopReason.OBSERVED_PLATEAU)
        self.assertLess(report.actual_total_agents, report.plan.total_agents)

    def test_token_budget_stops_after_observed_overrun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [review_result(index) for index in range(1, 4)]
            )
            verifier = SequenceVerifier(
                [
                    VerificationResult(score=0.30, verified=False),
                    VerificationResult(score=0.50, verified=False),
                ]
            )
            report = AdaptiveController(
                runtime=runtime,
                verifier=verifier,
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=6,
                    max_cost_multiplier=8,
                    target_confidence=0.98,
                    min_expected_gain=0.005,
                    max_total_tokens=150,
                ),
            )

        self.assertEqual(report.actual_total_agents, 2)
        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.stop_reason, StopReason.TOKEN_BUDGET_REACHED)
        self.assertEqual(report.receipts[-1].action.value, "incomplete_stop")
        self.assertEqual(report.usage.total_tokens, 200)
        self.assertEqual(
            [checkpoint.total_agents for checkpoint in report.checkpoints],
            [1, 2],
        )

    def test_pilot_v2_can_exceed_forecast_using_live_evidence(self) -> None:
        signals = TaskSignals(
            parallelizable_units=2,
            parallel_fraction=0.65,
            decomposition_confidence=0.85,
            context_coupling=0.35,
            shared_context_ratio=0.4,
            uncertainty=0.55,
            verification_value=0.55,
            failure_correlation=0.25,
            aggregation_difficulty=0.3,
            error_impact=0.55,
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [review_result(index) for index in range(1, 4)]
            )
            verifier = SequenceVerifier(
                [
                    VerificationResult(
                        score=0.90,
                        verified=False,
                        evidence_keys=("baseline",),
                    ),
                    VerificationResult(
                        score=0.91,
                        verified=False,
                        evidence_keys=("baseline", "second"),
                    ),
                    VerificationResult(
                        score=0.99,
                        verified=False,
                        coverage_complete=True,
                        evidence_keys=("baseline", "second", "third"),
                    ),
                ]
            )
            report = AdaptiveController(
                runtime=runtime,
                verifier=verifier,
                governor=Governor("pilot-v2"),
                signal_provider=lambda task, baseline, verification: signals,
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=5,
                    target_confidence=0.95,
                    min_expected_gain=0.005,
                ),
            )

        self.assertEqual(report.plan.total_agents, 2)
        self.assertEqual(report.actual_total_agents, 3)
        self.assertEqual(report.status, "completed")
        self.assertEqual(report.stop_reason, StopReason.TARGET_REACHED)

    def test_user_cap_before_completion_is_an_incomplete_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [review_result(index) for index in range(1, 5)]
            )
            verifier = SequenceVerifier(
                [
                    VerificationResult(
                        score=0.30,
                        verified=False,
                        evidence_keys=("a",),
                    ),
                    VerificationResult(
                        score=0.50,
                        verified=False,
                        evidence_keys=("a", "b"),
                    ),
                    VerificationResult(
                        score=0.70,
                        verified=False,
                        evidence_keys=("a", "b", "c"),
                    ),
                    VerificationResult(
                        score=0.80,
                        verified=False,
                        coverage_complete=False,
                        evidence_keys=("a", "b", "c", "d"),
                    ),
                ]
            )
            report = AdaptiveController(
                runtime=runtime,
                verifier=verifier,
                governor=Governor("pilot-v2"),
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=8,
                    target_confidence=0.98,
                    min_expected_gain=0.005,
                ),
            )

        self.assertEqual(report.actual_total_agents, 4)
        self.assertEqual(report.status, "incomplete")
        self.assertEqual(
            report.stop_reason, StopReason.CAP_REACHED_INCOMPLETE
        )
        self.assertEqual(report.receipts[-1].action.value, "incomplete_stop")
        self.assertFalse(report.verification.coverage_complete)

    def test_baseline_that_exhausts_budget_admits_no_extra_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime([review_result(1)])
            verifier = SequenceVerifier(
                [VerificationResult(score=0.30, verified=False)]
            )
            report = AdaptiveController(
                runtime=runtime,
                verifier=verifier,
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=6,
                    target_confidence=0.98,
                    min_expected_gain=0.005,
                    max_total_tokens=100,
                ),
            )

        self.assertEqual(report.actual_total_agents, 1)
        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.stop_reason, StopReason.TOKEN_BUDGET_REACHED)
        self.assertEqual(report.receipts[-1].action.value, "incomplete_stop")

    def test_additional_agent_failure_is_an_incomplete_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ScriptedRuntime(
                [
                    review_result(1),
                    review_result(2, success=False),
                ]
            )
            verifier = SequenceVerifier(
                [
                    VerificationResult(score=0.30, verified=False),
                    VerificationResult(score=0.30, verified=False),
                ]
            )
            sink = MemoryEventSink()
            report = AdaptiveController(
                runtime=runtime,
                verifier=verifier,
                event_sink=sink,
            ).execute(
                self._task(Path(directory)),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=6,
                    target_confidence=0.98,
                    min_expected_gain=0.005,
                ),
            )

        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.stop_reason, StopReason.RUNTIME_FAILURE)
        self.assertEqual(report.actual_total_agents, 2)
        self.assertEqual(report.receipts[-1].action.value, "incomplete_stop")
        self.assertEqual(report.checkpoints[-1].decision, "stop")
        self.assertIn(
            "checkpoint", [event.event_type for event in sink.events]
        )

    def test_runtime_exception_becomes_auditable_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = AdaptiveController(
                runtime=RaisingRuntime(),
                verifier=ReviewEvidenceVerifier(),
                aggregator=JsonFindingsAggregator(),
            ).execute(
                ExecutionTask(
                    task_id="non-parallel",
                    prompt="Review.",
                    working_directory=Path(directory),
                    signals=TaskSignals(),
                    metadata={
                        "changed_files": ["app.py"],
                        "high_risk_files": [],
                    },
                ),
                Budget(max_agents=1),
            )

        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.stop_reason, StopReason.RUNTIME_FAILURE)
        self.assertFalse(report.agent_results[0].success)
        self.assertIn("runtime unavailable", report.agent_results[0].error)
        self.assertEqual(report.receipts[-1].action.value, "incomplete_stop")


if __name__ == "__main__":
    unittest.main()
