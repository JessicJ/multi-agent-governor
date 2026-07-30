import unittest

from magov import (
    BaselineObservation,
    Budget,
    Governor,
    Mode,
    RoundObservation,
    StopReason,
    TaskSignals,
)


class GovernorDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.governor = Governor()

    def test_verified_baseline_stays_single(self) -> None:
        decision = self.governor.decide(
            TaskSignals(
                parallelizable_units=5,
                parallel_fraction=0.9,
                verification_value=0.9,
            ),
            BaselineObservation(confidence=0.93, verified=True),
        )

        self.assertEqual(decision.mode, Mode.SINGLE)
        self.assertEqual(decision.stop_reason, StopReason.BASELINE_SUFFICIENT)

    def test_separable_research_uses_independent_agents(self) -> None:
        decision = self.governor.decide(
            TaskSignals(
                parallelizable_units=4,
                parallel_fraction=0.85,
                decomposition_confidence=0.9,
                context_coupling=0.2,
                shared_context_ratio=0.25,
                uncertainty=0.8,
                verification_value=0.85,
                failure_correlation=0.15,
                aggregation_difficulty=0.3,
                error_impact=0.55,
            ),
            BaselineObservation(confidence=0.55),
            Budget(max_cost_multiplier=3.6, target_confidence=0.88),
        )

        self.assertEqual(decision.mode, Mode.INDEPENDENT)
        self.assertGreaterEqual(decision.total_agents, 2)
        self.assertGreater(decision.expected_confidence, 0.55)

    def test_coupled_parallel_work_uses_coordinator(self) -> None:
        decision = self.governor.decide(
            TaskSignals(
                parallelizable_units=5,
                parallel_fraction=0.85,
                decomposition_confidence=0.9,
                context_coupling=0.55,
                shared_context_ratio=0.5,
                uncertainty=0.75,
                verification_value=0.8,
                failure_correlation=0.2,
                aggregation_difficulty=0.65,
                error_impact=0.75,
            ),
            BaselineObservation(confidence=0.45),
            Budget(max_cost_multiplier=4.0),
        )

        self.assertEqual(decision.mode, Mode.CENTRALIZED)
        self.assertGreaterEqual(decision.total_agents, 2)

    def test_extreme_coupling_rejects_scale_out(self) -> None:
        decision = self.governor.decide(
            TaskSignals(
                parallelizable_units=3,
                parallel_fraction=0.35,
                decomposition_confidence=0.5,
                context_coupling=0.94,
                shared_context_ratio=0.95,
                uncertainty=0.4,
                verification_value=0.3,
                failure_correlation=0.8,
                aggregation_difficulty=0.9,
                error_impact=0.8,
            ),
            BaselineObservation(confidence=0.65),
        )

        self.assertEqual(decision.mode, Mode.SINGLE)
        self.assertEqual(decision.stop_reason, StopReason.COORDINATION_DOMINATES)

    def test_correlated_retries_are_rejected(self) -> None:
        decision = self.governor.decide(
            TaskSignals(
                parallelizable_units=2,
                parallel_fraction=0.25,
                decomposition_confidence=0.4,
                uncertainty=0.9,
                verification_value=0.9,
                failure_correlation=0.95,
            ),
            BaselineObservation(confidence=0.4),
        )

        self.assertEqual(decision.mode, Mode.SINGLE)
        self.assertEqual(decision.stop_reason, StopReason.CORRELATED_ERRORS)

    def test_tighter_budget_never_adds_more_agents(self) -> None:
        signals = TaskSignals(
            parallelizable_units=6,
            parallel_fraction=0.9,
            decomposition_confidence=0.9,
            context_coupling=0.2,
            shared_context_ratio=0.25,
            uncertainty=0.9,
            verification_value=0.9,
            failure_correlation=0.1,
            aggregation_difficulty=0.25,
        )
        baseline = BaselineObservation(confidence=0.3)

        tight = self.governor.decide(
            signals,
            baseline,
            Budget(max_cost_multiplier=2.5, target_confidence=0.99),
        )
        loose = self.governor.decide(
            signals,
            baseline,
            Budget(max_cost_multiplier=6.0, target_confidence=0.99),
        )

        self.assertLessEqual(tight.total_agents, loose.total_agents)

    def test_pilot_v2_requires_one_independent_review_before_stopping(self) -> None:
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
        baseline = BaselineObservation(confidence=1.0, verified=False)
        budget = Budget(
            max_agents=4,
            max_cost_multiplier=5,
            target_confidence=0.95,
            min_expected_gain=0.005,
        )

        pilot_v1 = Governor("pilot-v1").decide(
            signals, baseline, budget
        )
        pilot_v2 = Governor("pilot-v2").decide(
            signals, baseline, budget
        )

        self.assertEqual(pilot_v1.mode, Mode.SINGLE)
        self.assertEqual(pilot_v2.mode, Mode.INDEPENDENT)
        self.assertEqual(pilot_v2.total_agents, 2)
        self.assertIn(
            "independent_review_floor",
            {score.code for score in pilot_v2.scores},
        )

    def test_pilot_v2_review_floor_does_not_override_cost_budget(self) -> None:
        decision = Governor("pilot-v2").decide(
            TaskSignals(
                parallelizable_units=2,
                parallel_fraction=0.65,
                decomposition_confidence=0.85,
                context_coupling=0.35,
                shared_context_ratio=0.4,
                uncertainty=0.55,
                verification_value=0.55,
                failure_correlation=0.25,
                aggregation_difficulty=0.3,
            ),
            BaselineObservation(confidence=1.0, verified=False),
            Budget(max_agents=4, max_cost_multiplier=1.0),
        )

        self.assertEqual(decision.mode, Mode.SINGLE)
        self.assertEqual(
            decision.stop_reason, StopReason.COST_BUDGET_REACHED
        )

    def test_unknown_policy_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported policy version"):
            Governor("pilot-v999")

    def test_hard_failure_requires_zero_unverified_confidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "zero confidence"):
            BaselineObservation(confidence=0.8, hard_failure=True)
        with self.assertRaisesRegex(ValueError, "cannot be verified"):
            BaselineObservation(
                confidence=0.0,
                verified=True,
                hard_failure=True,
            )
        decision = self.governor.decide(
            TaskSignals(
                parallelizable_units=3,
                parallel_fraction=0.8,
                uncertainty=0.9,
                verification_value=0.9,
                failure_correlation=0.1,
            ),
            BaselineObservation(confidence=0.0, hard_failure=True),
            Budget(max_cost_multiplier=4.0),
        )
        self.assertIn(
            "baseline_hard_failure",
            {score.code for score in decision.scores},
        )

    def test_non_finite_cost_and_gain_inputs_are_rejected(self) -> None:
        for value in (float("nan"), float("inf")):
            with self.subTest(field="parallelizable_units", value=value):
                with self.assertRaises(ValueError):
                    TaskSignals(parallelizable_units=value)
            with self.subTest(field="baseline_cost", value=value):
                with self.assertRaises(ValueError):
                    BaselineObservation(confidence=0.5, cost_units=value)
            with self.subTest(field="budget_cost", value=value):
                with self.assertRaises(ValueError):
                    Budget(max_cost_multiplier=value)
            with self.subTest(field="round_cost", value=value):
                with self.assertRaises(ValueError):
                    RoundObservation(2, 0.5, value, 0.1)
            with self.subTest(field="round_gain", value=value):
                with self.assertRaises(ValueError):
                    RoundObservation(2, 0.5, 2.0, value)

    def test_core_boolean_fields_reject_strings(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be booleans"):
            BaselineObservation(confidence=0.5, verified="false")

    def test_runtime_hard_budgets_require_positive_values(self) -> None:
        for kwargs in (
            {"max_total_tokens": 0},
            {"max_wall_time_seconds": 0},
            {"max_tool_calls": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    Budget(**kwargs)


class GovernorScalingReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.governor = Governor()
        self.plan = self.governor.decide(
            TaskSignals(
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
            BaselineObservation(confidence=0.3),
            Budget(
                max_agents=6,
                max_cost_multiplier=8,
                target_confidence=0.98,
                min_expected_gain=0.005,
            ),
        )

    def test_stops_after_observed_plateau(self) -> None:
        budget = Budget(
            max_agents=6,
            max_cost_multiplier=8,
            target_confidence=0.98,
            plateau_rounds=2,
        )
        review = self.governor.review_scaling(
            self.plan,
            [
                RoundObservation(2, 0.50, 2.1, 0.01, 0.2),
                RoundObservation(3, 0.505, 3.2, 0.005, 0.05),
            ],
            budget,
        )

        self.assertFalse(review.should_continue)
        self.assertEqual(review.stop_reason, StopReason.OBSERVED_PLATEAU)

    def test_stops_at_observed_target(self) -> None:
        budget = Budget(target_confidence=0.9, max_cost_multiplier=8)
        review = self.governor.review_scaling(
            self.plan,
            [RoundObservation(2, 0.91, 2.1, 0.2)],
            budget,
        )

        self.assertFalse(review.should_continue)
        self.assertEqual(review.stop_reason, StopReason.TARGET_REACHED)


if __name__ == "__main__":
    unittest.main()
