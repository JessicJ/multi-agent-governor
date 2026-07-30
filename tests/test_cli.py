import contextlib
import io
import tempfile
import unittest
import json
from pathlib import Path

from magov.cli import main, replay_events, summarize_reports
from magov.events import JsonlEventSink


class CliValidationTests(unittest.TestCase):
    def test_non_finite_json_numbers_are_rejected(self) -> None:
        payload = """
        {
          "signals": {},
          "baseline": {"confidence": 0.5},
          "budget": {"max_cost_multiplier": NaN}
        }
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(payload)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = main([str(path)])

        self.assertEqual(status, 2)
        self.assertIn("non-finite JSON number", stderr.getvalue())

    def test_run_command_executes_scripted_adaptive_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "run.json"
            events = root / "events.jsonl"
            config.write_text(
                json.dumps(
                    {
                        "task": {
                            "task_id": "cli-review",
                            "prompt": "Review and return JSON.",
                            "working_directory": ".",
                            "signals": {
                                "parallelizable_units": 4,
                                "parallel_fraction": 0.9,
                                "decomposition_confidence": 0.9,
                                "context_coupling": 0.2,
                                "shared_context_ratio": 0.2,
                                "uncertainty": 0.9,
                                "verification_value": 0.9,
                                "failure_correlation": 0.1,
                                "aggregation_difficulty": 0.2,
                            },
                            "metadata": {
                                "changed_files": ["auth.py"],
                                "high_risk_files": ["auth.py"],
                            },
                        },
                        "runtime": {
                            "kind": "scripted",
                            "results": [
                                {
                                    "output": {
                                        "findings": [],
                                        "reviewed_files": ["auth.py"],
                                        "unresolved_conflicts": 0,
                                    },
                                    "usage": {
                                        "agent_input_tokens": 90,
                                        "agent_output_tokens": 10,
                                    },
                                },
                                {
                                    "output": {
                                        "findings": [],
                                        "reviewed_files": ["auth.py"],
                                        "unresolved_conflicts": 0,
                                    },
                                    "usage": {
                                        "agent_input_tokens": 90,
                                        "agent_output_tokens": 10,
                                    },
                                },
                            ],
                        },
                        "budget": {
                            "max_agents": 4,
                            "max_cost_multiplier": 6,
                            "target_confidence": 0.95,
                            "min_expected_gain": 0.005,
                        },
                    }
                )
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = main(
                    ["run", str(config), "--events", str(events)]
                )

            report = json.loads(stdout.getvalue())
            events_created = events.is_file()

        self.assertEqual(status, 0)
        self.assertEqual(report["actual_total_agents"], 2)
        self.assertEqual(report["stop_reason"], "target_reached")
        self.assertTrue(events_created)

    def test_replay_and_report_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "events.jsonl"
            events.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "sequence": 1,
                                "run_id": "r1",
                                "task_id": "t1",
                                "event_type": "run_started",
                                "data": {},
                                "occurred_at": "2026-01-01T00:00:00+00:00",
                            }
                        ),
                        json.dumps(
                            {
                                "sequence": 2,
                                "run_id": "r1",
                                "task_id": "t1",
                                "event_type": "run_completed",
                                "data": {
                                    "status": "completed",
                                    "actual_total_agents": 2,
                                },
                                "occurred_at": "2026-01-01T00:00:01+00:00",
                            }
                        ),
                    ]
                )
                + "\n"
            )
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "actual_total_agents": 2,
                        "stop_reason": "target_reached",
                        "usage": {"total_tokens": 200},
                    }
                )
            )

            replay = replay_events(events)
            summary = summarize_reports([report_path])

        self.assertTrue(replay["complete"])
        self.assertEqual(replay["event_count"], 2)
        self.assertEqual(summary["average_actual_agents"], 2)
        self.assertEqual(summary["total_tokens"], 200)

    def test_nonempty_event_log_cannot_be_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.jsonl"
            events.write_text('{"existing": true}\n')
            with self.assertRaisesRegex(ValueError, "already exists"):
                JsonlEventSink(events)


if __name__ == "__main__":
    unittest.main()
