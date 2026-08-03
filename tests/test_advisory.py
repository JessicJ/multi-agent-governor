import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from magov.advisory import (
    AdvisoryUsage,
    advisory_report,
    append_advisory_checkpoint,
    start_advisory_session,
)
from magov.cli import main


class AdvisorySessionTests(unittest.TestCase):
    @staticmethod
    def _start_payload(*, max_total_tokens=None) -> dict:
        budget = {
            "max_agents": 4,
            "max_cost_multiplier": 4,
            "target_confidence": 0.95,
        }
        if max_total_tokens is not None:
            budget["max_total_tokens"] = max_total_tokens
        return {
            "session": {
                "session_id": "dinner-mvp-001",
                "task_id": "dinner-compiler-mvp",
                "model_id": "gpt-test",
            },
            "policy": {"version": "pilot-v2"},
            "signals": {
                "parallelizable_units": 4,
                "parallel_fraction": 0.55,
                "decomposition_confidence": 0.7,
                "context_coupling": 0.65,
                "shared_context_ratio": 0.6,
                "uncertainty": 0.95,
                "verification_value": 0.9,
                "failure_correlation": 0.35,
                "aggregation_difficulty": 0.75,
                "error_impact": 0.7,
            },
            "baseline": {
                "confidence": 0,
                "verified": False,
                "hard_failure": True,
                "cost_units": 1,
                "latency_seconds": 0,
            },
            "budget": budget,
            "baseline_evidence": [
                {
                    "code": "empty_repository",
                    "statement": "The baseline found no package or tests.",
                    "source": "task",
                },
                {
                    "code": "baseline_commands_failed",
                    "statement": "Initial typecheck and tests could not start.",
                    "source": "verifier",
                },
            ],
            "remaining_risks": ["No implementation exists yet."],
        }

    @staticmethod
    def _checkpoint(
        total_agents: int,
        *,
        quality_score: float = 0.7,
        marginal_quality_gain: float = 0.2,
        novel_evidence_ratio: float = 0.8,
        coverage_complete: bool = False,
        unresolved_conflicts: int = 1,
        model_id: str = "gpt-test",
        usage: dict | None = None,
        cumulative_cost_multiplier=None,
        cumulative_wall_time_seconds=None,
    ) -> dict:
        return {
            "agent_id": f"reviewer-{total_agents - 1}",
            "total_agents": total_agents,
            "contribution": "Reviewed one bounded implementation surface.",
            "quality_score": quality_score,
            "marginal_quality_gain": marginal_quality_gain,
            "novel_evidence_ratio": novel_evidence_ratio,
            "coverage_complete": coverage_complete,
            "unresolved_conflicts": unresolved_conflicts,
            "evidence": [
                {
                    "code": f"review-{total_agents}",
                    "statement": "A deterministic test exposes a distinct risk.",
                    "source": "verifier",
                }
            ],
            "remaining_risks": (
                [] if coverage_complete else ["One review surface remains."]
            ),
            "usage": usage or {},
            "model_id": model_id,
            "cumulative_cost_multiplier": cumulative_cost_multiplier,
            "cumulative_wall_time_seconds": cumulative_wall_time_seconds,
        }

    def test_start_separates_plan_boundary_from_actual_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            report = start_advisory_session(self._start_payload(), events)

        self.assertEqual(report["status"], "active")
        self.assertEqual(report["enforcement"], "advisory_only")
        self.assertFalse(report["runtime_enforced"])
        self.assertEqual(report["planned_total_agents"], 3)
        self.assertEqual(report["actual_total_agents"], 1)
        self.assertEqual(report["plan_stop_reason"], "cost_budget_reached")
        self.assertIsNone(report["final_stop_reason"])
        self.assertEqual(report["next_total_agents"], 2)
        self.assertIsNone(report["usage"]["total_tokens"])
        self.assertIn("total_tokens", report["usage"]["missing_fields"])

    def test_checkpoints_increment_and_actual_target_stop_is_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            active = append_advisory_checkpoint(
                events, self._checkpoint(2)
            )
            completed = append_advisory_checkpoint(
                events,
                self._checkpoint(
                    3,
                    quality_score=0.97,
                    marginal_quality_gain=0.27,
                    coverage_complete=True,
                    unresolved_conflicts=0,
                ),
            )

        self.assertEqual(active["status"], "active")
        self.assertEqual(active["next_total_agents"], 3)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["actual_total_agents"], 3)
        self.assertEqual(completed["plan_stop_reason"], "cost_budget_reached")
        self.assertEqual(completed["final_stop_reason"], "target_reached")
        self.assertIsNone(completed["next_total_agents"])
        self.assertEqual(len(completed["checkpoints"]), 3)

    def test_unknown_usage_does_not_become_zero_or_trip_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(
                self._start_payload(max_total_tokens=1), events
            )
            report = append_advisory_checkpoint(
                events, self._checkpoint(2)
            )

        self.assertEqual(report["status"], "active")
        self.assertIsNone(report["usage"]["total_tokens"])
        self.assertIsNone(report["hard_budget_evidence"]["total_tokens"])

    def test_measured_tokens_trigger_incomplete_stop(self) -> None:
        payload = self._start_payload(max_total_tokens=100)
        payload["baseline_usage"] = {
            "input_tokens": 30,
            "output_tokens": 20,
            "cached_input_tokens": 10,
            "reasoning_tokens": 5,
            "model_calls": 1,
            "tool_calls": 2,
            "agent_time_seconds": 4,
        }
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(payload, events)
            report = append_advisory_checkpoint(
                events,
                self._checkpoint(
                    2,
                    usage={
                        "input_tokens": 40,
                        "output_tokens": 20,
                        "cached_input_tokens": 10,
                        "reasoning_tokens": 5,
                        "model_calls": 1,
                        "tool_calls": 2,
                        "agent_time_seconds": 5,
                    },
                ),
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(
            report["final_stop_reason"], "token_budget_reached"
        )
        self.assertEqual(report["usage"]["total_tokens"], 110)
        self.assertEqual(report["usage"]["agent_time_seconds"], 9)

    def test_plateau_without_public_coverage_is_an_incomplete_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            append_advisory_checkpoint(
                events,
                self._checkpoint(
                    2,
                    marginal_quality_gain=0.001,
                    novel_evidence_ratio=0.05,
                ),
            )
            report = append_advisory_checkpoint(
                events,
                self._checkpoint(
                    3,
                    quality_score=0.701,
                    marginal_quality_gain=0.001,
                    novel_evidence_ratio=0.05,
                ),
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["final_stop_reason"], "observed_plateau")
        self.assertEqual(
            report["checkpoints"][-1]["decision"]["action"],
            "incomplete_stop",
        )
        self.assertIn(
            "coverage remains incomplete",
            report["checkpoints"][-1]["decision"]["explanation"],
        )

    def test_rejects_skipped_agent_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            with self.assertRaisesRegex(ValueError, "must be 2"):
                append_advisory_checkpoint(
                    events, self._checkpoint(3)
                )

    def test_rejects_checkpoint_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            append_advisory_checkpoint(
                events,
                self._checkpoint(
                    2,
                    quality_score=0.99,
                    coverage_complete=True,
                    unresolved_conflicts=0,
                ),
            )
            with self.assertRaisesRegex(ValueError, "after an advisory stop"):
                append_advisory_checkpoint(
                    events, self._checkpoint(3)
                )

    def test_rejects_mixed_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            with self.assertRaisesRegex(ValueError, "homogeneous model"):
                append_advisory_checkpoint(
                    events, self._checkpoint(2, model_id="other-model")
                )

    def test_replay_rejects_tampered_agent_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            append_advisory_checkpoint(
                events, self._checkpoint(2)
            )
            lines = events.read_text().splitlines()
            tampered = json.loads(lines[1])
            tampered["data"]["observation"]["total_agents"] = 4
            lines[1] = json.dumps(tampered)
            events.write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(ValueError, "increment"):
                advisory_report(events)

    def test_usage_validates_accounting_relationships(self) -> None:
        with self.assertRaisesRegex(ValueError, "total_tokens"):
            AdvisoryUsage.from_dict(
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 99,
                }
            )
        with self.assertRaisesRegex(ValueError, "cached_input_tokens"):
            AdvisoryUsage.from_dict(
                {"input_tokens": 10, "cached_input_tokens": 11}
            )

    def test_cli_start_checkpoint_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start_input = root / "start.json"
            checkpoint_input = root / "checkpoint.json"
            events = root / "advisory.jsonl"
            start_input.write_text(json.dumps(self._start_payload()))
            checkpoint_input.write_text(json.dumps(self._checkpoint(2)))

            self.assertEqual(
                self._quiet_main(
                    "advisory",
                    "start",
                    str(start_input),
                    "--events",
                    str(events),
                    "--compact",
                ),
                0,
            )
            self.assertEqual(
                self._quiet_main(
                    "advisory",
                    "checkpoint",
                    str(events),
                    str(checkpoint_input),
                    "--compact",
                ),
                0,
            )
            self.assertEqual(
                self._quiet_main(
                    "advisory",
                    "report",
                    str(events),
                    "--compact",
                ),
                0,
            )

    @staticmethod
    def _quiet_main(*args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return main(list(args))

    def test_replay_rejects_tampered_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            append_advisory_checkpoint(events, self._checkpoint(2))
            lines = events.read_text().splitlines()
            tampered = json.loads(lines[1])
            tampered["data"]["decision"]["action"] = "stop"
            lines[1] = json.dumps(tampered)
            events.write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(ValueError, "does not match replay"):
                advisory_report(events)

    def test_replay_rejects_tampered_decision_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            append_advisory_checkpoint(events, self._checkpoint(2))
            lines = events.read_text().splitlines()
            tampered = json.loads(lines[1])
            tampered["data"]["decision"]["evidence"][0][
                "statement"
            ] = "Rewritten evidence."
            lines[1] = json.dumps(tampered)
            events.write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(ValueError, "does not match replay"):
                advisory_report(events)

    def test_missing_cost_is_explicit_in_continue_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "advisory.jsonl"
            start_advisory_session(self._start_payload(), events)
            report = append_advisory_checkpoint(
                events, self._checkpoint(2)
            )

        explanation = report["checkpoints"][-1]["decision"]["explanation"]
        self.assertIn("could not be evaluated: cost_multiplier", explanation)


if __name__ == "__main__":
    unittest.main()
