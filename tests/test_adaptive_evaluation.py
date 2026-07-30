from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from magov import (
    AdaptiveController,
    AdaptiveTrialOutcome,
    AdaptiveTrialSpec,
    AgentResult,
    Budget,
    CheckpointObservation,
    DatasetSplit,
    DefectSeverity,
    ExecutionTask,
    FixedCountController,
    GoldDefect,
    JsonFindingsAggregator,
    ReviewEvidenceVerifier,
    ReviewTask,
    ScoreReport,
    TaskSource,
    TaskStatus,
    TrialOutcome,
    TrialSpec,
    UsageObservation,
    adaptive_outcome_from_report,
    build_adaptive_run_payload,
    build_adaptive_trial_matrix,
    compare_adaptive_to_fixed,
    derive_pilot_review_signals,
    fixed_outcome_from_report,
    render_review_prompt,
    score_findings,
    summarize_adaptive_outcomes,
)
from magov.adapters import ScriptedRuntime
from magov.adaptive_evaluation import _report_findings
from magov.eval_cli import main as eval_main


class CapturingRuntime:
    def __init__(self) -> None:
        self.requests = []

    def run_agent(self, request):
        self.requests.append(request)
        return AgentResult(
            run_id=request.run_id,
            agent_index=request.agent_index,
            role=request.role,
            success=True,
            output=json.dumps(
                {
                    "findings": [],
                    "reviewed_files": (
                        ["service/auth.py"]
                        if request.agent_index == 1
                        else ["service/storage.py"]
                    ),
                    "unresolved_conflicts": 0,
                }
            ),
            usage=usage(),
        )


def ready_task(
    *,
    task_id: str = "python-pr-09",
    high_risk: bool = True,
) -> ReviewTask:
    changed = ("service/auth.py", "service/storage.py")
    return ReviewTask(
        task_id=task_id,
        repository="local://fixture",
        base_revision="fixture-v1",
        patch_path=f"evals/tasks/{task_id}/change.diff",
        truth_path=f"evals/tasks/{task_id}/truth.json",
        source=TaskSource.INJECTED,
        split=DatasetSplit.PILOT,
        status=TaskStatus.READY,
        changed_files=changed,
        high_risk_files=("service/auth.py",) if high_risk else (),
        license_spdx="MIT",
        source_reference="fixture",
        test_command="python hidden_test.py",
        patch_sha256="a" * 64,
    )


def usage(tokens: int = 100) -> UsageObservation:
    return UsageObservation(
        agent_input_tokens=tokens - 10,
        agent_output_tokens=10,
        model_calls=1,
        tool_calls=1,
        wall_time_seconds=2.0,
    )


def agent_result(
    index: int, *, finding: bool = False
) -> AgentResult:
    findings = []
    if finding:
        findings.append(
            {
                "finding_id": f"f-{index}",
                "file": "service/auth.py",
                "symbol": "authorize",
                "root_cause_category": "missing-permission-check",
                "impact": "Unauthorized access",
                "evidence": "The caller role is not checked.",
                "claimed_severity": "serious",
            }
        )
    return AgentResult(
        run_id="scripted",
        agent_index=index,
        role="scripted",
        success=True,
        output=json.dumps(
            {
                "findings": findings,
                "reviewed_files": [
                    "service/auth.py",
                    "service/storage.py",
                ],
                "unresolved_conflicts": 0,
            }
        ),
        usage=usage(),
    )


class AdaptiveEvaluationTests(unittest.TestCase):
    def test_report_findings_namespaces_duplicate_agent_ids(self) -> None:
        finding = {
            "finding_id": "runtime-assigned-reviewer-1",
            "file": "service/auth.py",
            "symbol": "authorize",
            "root_cause_category": "missing-permission-check",
            "impact": "Unauthorized access",
            "evidence": "The caller role is not checked.",
            "claimed_severity": "serious",
        }
        findings = _report_findings(
            {
                "aggregate": {
                    "metadata": {
                        "findings": [finding, dict(finding)],
                    }
                }
            }
        )

        self.assertEqual(
            [item.finding_id for item in findings],
            [
                "runtime-assigned-reviewer-1",
                "runtime-assigned-reviewer-1__occurrence-2",
            ],
        )

    def test_fixed_and_adaptive_arms_use_the_same_agent_prompts(self) -> None:
        task = ready_task(high_risk=False)
        with tempfile.TemporaryDirectory() as directory:
            execution_task = ExecutionTask(
                task_id=task.task_id,
                prompt="Identical preregistered review prompt.",
                working_directory=Path(directory),
                signals=derive_pilot_review_signals(task),
                metadata={
                    "changed_files": list(task.changed_files),
                    "high_risk_files": list(task.high_risk_files),
                },
            )
            fixed_runtime = CapturingRuntime()
            adaptive_runtime = CapturingRuntime()
            FixedCountController(
                runtime=fixed_runtime,
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier(),
            ).execute(execution_task, exact_total_agents=4)
            AdaptiveController(
                runtime=adaptive_runtime,
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier(),
            ).execute(execution_task, Budget(max_agents=4))

        self.assertGreaterEqual(len(adaptive_runtime.requests), 2)
        self.assertEqual(
            [item.prompt for item in fixed_runtime.requests[:2]],
            [item.prompt for item in adaptive_runtime.requests[:2]],
        )
        self.assertEqual(
            [item.role for item in fixed_runtime.requests[:2]],
            [item.role for item in adaptive_runtime.requests[:2]],
        )

    def test_matrix_and_signals_use_only_public_task_metadata(self) -> None:
        high_risk = ready_task()
        ordinary = ready_task(task_id="python-pr-01", high_risk=False)
        trials = build_adaptive_trial_matrix(
            [high_risk, ordinary],
            model_id="fixed-model",
            prompt_version="python-review-v2",
            policy_version="pilot-v1",
            repetitions=2,
        )

        self.assertEqual(len(trials), 4)
        self.assertEqual(trials[0].max_agents, 4)
        self.assertGreater(
            derive_pilot_review_signals(high_risk).verification_value,
            derive_pilot_review_signals(ordinary).verification_value,
        )

    def test_pilot_v2_single_file_review_declares_independent_replication(
        self,
    ) -> None:
        task = ready_task(task_id="python-pr-01", high_risk=False)
        task = replace(
            task,
            changed_files=("service/auth.py",),
        )

        pilot_v1 = derive_pilot_review_signals(
            task,
            policy_version="pilot-v1",
        )
        pilot_v2 = derive_pilot_review_signals(
            task,
            policy_version="pilot-v2",
        )

        self.assertEqual(pilot_v1.parallelizable_units, 1)
        self.assertEqual(pilot_v1.parallel_fraction, 0.15)
        self.assertEqual(pilot_v2.parallelizable_units, 2)
        self.assertGreaterEqual(pilot_v2.parallel_fraction, 0.20)

    def test_truth_free_run_payload_omits_private_evaluation_fields(self) -> None:
        task = ready_task()
        trial = build_adaptive_trial_matrix(
            [task],
            model_id="fixed-model",
            prompt_version="python-review-v2",
            policy_version="pilot-v1",
            repetitions=1,
        )[0]
        prompt = render_review_prompt(
            "TASK_DIRECTORY\nTRIAL_ID\nROLE",
            task_directory="/tmp/task",
            trial_id=trial.trial_id,
        )
        payload = build_adaptive_run_payload(
            task,
            trial,
            working_directory="/tmp/task",
            prompt=prompt,
            output_schema="/tmp/schema.json",
            artifacts_directory="/tmp/artifacts",
        )
        serialized = json.dumps(payload)

        self.assertNotIn(task.truth_path, serialized)
        self.assertNotIn(task.base_revision, serialized)
        self.assertNotIn(task.repository, serialized)
        self.assertEqual(payload["budget"]["max_agents"], 4)
        self.assertEqual(
            payload["runtime"]["extra_args"], ["--ignore-user-config"]
        )
        self.assertEqual(payload["policy"], {"version": "pilot-v1"})

    def test_runtime_report_converts_to_scored_adaptive_outcome(self) -> None:
        task = ready_task()
        trial = build_adaptive_trial_matrix(
            [task],
            model_id="fixed-model",
            prompt_version="python-review-v2",
            policy_version="pilot-v1",
            repetitions=1,
        )[0]
        truth = [
            GoldDefect(
                defect_id="D-1",
                file="service/auth.py",
                symbol="authorize",
                root_cause_category="missing-permission-check",
                severity=DefectSeverity.SERIOUS,
                red_line=True,
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            report = AdaptiveController(
                runtime=ScriptedRuntime(
                    [agent_result(1), agent_result(2, finding=True)]
                ),
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier(),
            ).execute(
                ExecutionTask(
                    task_id=task.task_id,
                    prompt="Review and return structured JSON.",
                    working_directory=Path(directory),
                    signals=derive_pilot_review_signals(task),
                    metadata={
                        "changed_files": list(task.changed_files),
                        "high_risk_files": list(task.high_risk_files),
                    },
                ),
                Budget(
                    max_agents=4,
                    max_cost_multiplier=6,
                    target_confidence=0.95,
                    min_expected_gain=0.005,
                ),
            )
        outcome = adaptive_outcome_from_report(
            trial, report.to_dict(), truth
        )

        self.assertEqual(outcome.actual_total_agents, 2)
        self.assertEqual(outcome.stop_reason, "target_reached")
        self.assertEqual(outcome.score.found_serious_defects, 1)
        self.assertEqual(outcome.usage.total_tokens, 200)
        self.assertEqual(
            [item.total_agents for item in outcome.checkpoints], [1, 2]
        )

    def test_pilot_v2_outcome_requires_reported_policy_version(self) -> None:
        trial = AdaptiveTrialSpec(
            trial_id="python-pr-09__adaptive-max-4__repeat-1",
            task_id="python-pr-09",
            max_agents=4,
            repetition=1,
            model_id="fixed-model",
            prompt_version="python-review-v2",
            policy_version="pilot-v2",
        )
        report = {
            "task_id": "python-pr-09",
            "actual_total_agents": 1,
        }

        with self.assertRaisesRegex(ValueError, "must declare policy_version"):
            adaptive_outcome_from_report(trial, report, ())

    def test_fixed_controller_reaches_exact_count_despite_early_target(self) -> None:
        task = ready_task()
        trial = TrialSpec(
            trial_id=f"{task.task_id}__agents-4__repeat-1",
            task_id=task.task_id,
            exact_total_agents=4,
            repetition=1,
            model_id="fixed-model",
            prompt_version="python-review-v2",
        )
        truth = [
            GoldDefect(
                defect_id="D-1",
                file="service/auth.py",
                symbol="authorize",
                root_cause_category="missing-permission-check",
                severity=DefectSeverity.SERIOUS,
                red_line=True,
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            report = FixedCountController(
                runtime=ScriptedRuntime(
                    [
                        agent_result(1),
                        agent_result(2, finding=True),
                        agent_result(3),
                        agent_result(4),
                    ]
                ),
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier(),
            ).execute(
                ExecutionTask(
                    task_id=task.task_id,
                    prompt="Review and return structured JSON.",
                    working_directory=Path(directory),
                    signals=derive_pilot_review_signals(task),
                    metadata={
                        "changed_files": list(task.changed_files),
                        "high_risk_files": list(task.high_risk_files),
                    },
                ),
                exact_total_agents=4,
            )
        outcome = fixed_outcome_from_report(
            trial, report.to_dict(), truth
        )

        self.assertEqual(report.actual_total_agents, 4)
        self.assertEqual(report.stop_reason, "fixed_count_reached")
        self.assertEqual(
            [item.total_agents for item in report.checkpoints],
            [1, 2, 3, 4],
        )
        self.assertEqual(outcome.actual_total_agents, 4)
        self.assertEqual(outcome.score.found_serious_defects, 1)

    def test_fixed_controller_safety_budget_invalidates_the_trial(self) -> None:
        task = ready_task()
        with tempfile.TemporaryDirectory() as directory:
            report = FixedCountController(
                runtime=ScriptedRuntime(
                    [agent_result(index) for index in range(1, 5)]
                ),
                aggregator=JsonFindingsAggregator(),
                verifier=ReviewEvidenceVerifier(),
            ).execute(
                ExecutionTask(
                    task_id=task.task_id,
                    prompt="Review and return structured JSON.",
                    working_directory=Path(directory),
                    signals=derive_pilot_review_signals(task),
                    metadata={
                        "changed_files": list(task.changed_files),
                        "high_risk_files": list(task.high_risk_files),
                    },
                ),
                exact_total_agents=4,
                max_total_tokens=150,
            )

        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.actual_total_agents, 2)
        self.assertEqual(report.stop_reason, "token_budget_reached")

    def test_summary_and_fixed_comparison_remain_descriptive(self) -> None:
        task = ready_task()
        trial = build_adaptive_trial_matrix(
            [task],
            model_id="fixed-model",
            prompt_version="python-review-v2",
            policy_version="pilot-v1",
            repetitions=1,
        )[0]
        score = score_findings([], [])
        adaptive_usage = UsageObservation(
            agent_input_tokens=180,
            agent_output_tokens=20,
            model_calls=2,
            tool_calls=2,
            wall_time_seconds=4.0,
        )
        adaptive = AdaptiveTrialOutcome(
            trial=trial,
            actual_total_agents=2,
            planned_total_agents=4,
            execution_status="completed",
            stop_reason="target_reached",
            usage=adaptive_usage,
            score=score,
            coverage_complete=True,
            unresolved_conflicts=0,
            checkpoints=(
                CheckpointObservation(
                    total_agents=1,
                    new_finding_count=0,
                    repeated_finding_count=0,
                    newly_reviewed_files=task.changed_files,
                    coverage_complete=False,
                    unresolved_conflicts=0,
                    usage_delta=usage(100),
                ),
                CheckpointObservation(
                    total_agents=2,
                    new_finding_count=0,
                    repeated_finding_count=0,
                    newly_reviewed_files=(),
                    coverage_complete=True,
                    unresolved_conflicts=0,
                    usage_delta=usage(100),
                ),
            ),
        )
        fixed_usage = UsageObservation(
            agent_input_tokens=360,
            agent_output_tokens=40,
            model_calls=4,
            tool_calls=4,
            wall_time_seconds=8.0,
        )
        fixed = TrialOutcome(
            trial=TrialSpec(
                trial_id=f"{task.task_id}__agents-4__repeat-1",
                task_id=task.task_id,
                exact_total_agents=4,
                repetition=1,
                model_id="fixed-model",
                prompt_version="python-review-v2",
            ),
            actual_total_agents=4,
            usage=fixed_usage,
            score=score,
            coverage_complete=True,
            checkpoints=tuple(
                CheckpointObservation(
                    total_agents=index,
                    new_finding_count=0,
                    repeated_finding_count=0,
                    newly_reviewed_files=(
                        task.changed_files if index == 1 else ()
                    ),
                    coverage_complete=index == 4,
                    unresolved_conflicts=0,
                    usage_delta=usage(100),
                )
                for index in range(1, 5)
            ),
        )

        summary = summarize_adaptive_outcomes([adaptive])
        comparison = compare_adaptive_to_fixed([fixed], [adaptive])

        self.assertFalse(summary["claim_allowed"])
        self.assertEqual(summary["mean_actual_agents"], 2)
        self.assertFalse(comparison["claim_allowed"])
        self.assertEqual(comparison["engineering_result"], "inconclusive")
        self.assertEqual(comparison["token_saving_rate"], 0.5)
        self.assertTrue(
            comparison["product_target"][
                "thresholds_observed_descriptively"
            ]
        )
        forecast_exceeded = replace(adaptive, planned_total_agents=1)
        self.assertGreater(
            forecast_exceeded.actual_total_agents,
            forecast_exceeded.planned_total_agents,
        )

        cap_censored = replace(
            adaptive,
            execution_status="incomplete",
            stop_reason="cap_reached_incomplete",
            coverage_complete=False,
            checkpoints=(
                adaptive.checkpoints[0],
                replace(
                    adaptive.checkpoints[1],
                    coverage_complete=False,
                ),
            ),
        )
        censored_summary = summarize_adaptive_outcomes([cap_censored])
        censored_comparison = compare_adaptive_to_fixed(
            [fixed], [cap_censored]
        )
        self.assertEqual(censored_summary["cap_censored_trials"], 1)
        self.assertEqual(
            censored_comparison["adaptive_cap_censored_trials"], 1
        )
        self.assertIsNone(
            censored_comparison["quality"]["quality_guardrails_observed"]
        )
        self.assertIsNone(
            censored_comparison["product_target"][
                "thresholds_observed_descriptively"
            ]
        )

        ordinary_score = ScoreReport(
            total_known_defects=1,
            found_known_defects=0,
            serious_defects=0,
            found_serious_defects=0,
            valid_other_findings=0,
            false_positive_findings=0,
            duplicate_findings=0,
            pending_findings=(),
            missed_red_line_defects=(),
        )
        missed_serious_score = ScoreReport(
            total_known_defects=1,
            found_known_defects=0,
            serious_defects=1,
            found_serious_defects=0,
            valid_other_findings=0,
            false_positive_findings=0,
            duplicate_findings=0,
            pending_findings=(),
            missed_red_line_defects=(),
        )
        adaptive_ordinary = replace(adaptive, score=ordinary_score)
        adaptive_serious = replace(
            adaptive,
            trial=replace(
                trial,
                trial_id="python-pr-10__adaptive-max-4__repeat-1",
                task_id="python-pr-10",
            ),
            score=missed_serious_score,
        )
        fixed_ordinary = replace(fixed, score=ordinary_score)
        fixed_serious = replace(
            fixed,
            trial=replace(
                fixed.trial,
                trial_id="python-pr-10__agents-4__repeat-1",
                task_id="python-pr-10",
            ),
            score=missed_serious_score,
        )
        pooled_summary = summarize_adaptive_outcomes(
            [adaptive_ordinary, adaptive_serious]
        )
        pooled_comparison = compare_adaptive_to_fixed(
            [fixed_ordinary, fixed_serious],
            [adaptive_ordinary, adaptive_serious],
        )

        self.assertEqual(pooled_summary["mean_serious_recall"], 0.0)
        self.assertEqual(pooled_summary["total_recall"], 0.0)
        self.assertEqual(
            pooled_comparison["quality"][
                "adaptive_mean_serious_recall"
            ],
            0.0,
        )
        self.assertEqual(
            pooled_comparison["arms"]["adaptive-max-4"][
                "mean_serious_recall"
            ],
            0.0,
        )

    def test_eval_cli_plans_adaptive_arm(self) -> None:
        task = ready_task()
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                **task.__dict__,
                                "source": task.source.value,
                                "split": task.split.value,
                                "status": task.status.value,
                                "changed_files": list(task.changed_files),
                                "high_risk_files": list(
                                    task.high_risk_files
                                ),
                            }
                        ]
                    }
                )
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = eval_main(
                    [
                        "adaptive-plan",
                        str(manifest),
                        "--model-id",
                        "fixed-model",
                        "--prompt-version",
                        "python-review-v2",
                        "--policy-version",
                        "pilot-v1",
                        "--repetitions",
                        "2",
                    ]
                )
        result = json.loads(stdout.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(result["arm"], "adaptive")
        self.assertEqual(result["trial_count"], 2)

    def test_eval_cli_freezes_adaptive_hard_budgets(self) -> None:
        task = ready_task()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            prompt = root / "prompt.txt"
            schema = root / "schema.json"
            artifacts = root / "artifacts"
            worktree = root / "worktree"
            prompt.write_text("Review TASK_DIRECTORY for TRIAL_ID as ROLE.")
            schema.write_text("{}")
            worktree.mkdir()
            manifest.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                **task.__dict__,
                                "source": task.source.value,
                                "split": task.split.value,
                                "status": task.status.value,
                                "changed_files": list(task.changed_files),
                                "high_risk_files": list(
                                    task.high_risk_files
                                ),
                            }
                        ]
                    }
                )
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = eval_main(
                    [
                        "adaptive-config",
                        str(manifest),
                        task.task_id,
                        str(worktree),
                        "--model-id",
                        "gpt-5.6-sol",
                        "--prompt-version",
                        "python-review-v2",
                        "--policy-version",
                        "pilot-v2",
                        "--prompt-template",
                        str(prompt),
                        "--output-schema",
                        str(schema),
                        "--artifacts-directory",
                        str(artifacts),
                        "--max-total-tokens",
                        "600000",
                        "--max-wall-time-seconds",
                        "3600",
                        "--max-tool-calls",
                        "200",
                    ]
                )
        result = json.loads(stdout.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(result["run"]["policy"]["version"], "pilot-v2")
        self.assertEqual(result["run"]["budget"]["max_total_tokens"], 600000)
        self.assertEqual(
            result["run"]["budget"]["max_wall_time_seconds"],
            3600.0,
        )
        self.assertEqual(result["run"]["budget"]["max_tool_calls"], 200)
        self.assertEqual(
            result["run"]["task"]["signals"]["parallelizable_units"],
            2,
        )

    def test_eval_cli_marks_scripted_config_as_non_real(self) -> None:
        task = ready_task()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            prompt = root / "prompt.txt"
            schema = root / "schema.json"
            worktree = root / "worktree"
            prompt.write_text("Review TASK_DIRECTORY for TRIAL_ID as ROLE.")
            schema.write_text("{}")
            worktree.mkdir()
            manifest.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                **task.__dict__,
                                "source": task.source.value,
                                "split": task.split.value,
                                "status": task.status.value,
                                "changed_files": list(task.changed_files),
                                "high_risk_files": list(
                                    task.high_risk_files
                                ),
                            }
                        ]
                    }
                )
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = eval_main(
                    [
                        "adaptive-config",
                        str(manifest),
                        task.task_id,
                        str(worktree),
                        "--model-id",
                        "gpt-5.6-sol",
                        "--prompt-version",
                        "python-review-v2",
                        "--policy-version",
                        "pilot-v2",
                        "--prompt-template",
                        str(prompt),
                        "--output-schema",
                        str(schema),
                        "--artifacts-directory",
                        str(root / "artifacts"),
                        "--scripted-dry-run",
                    ]
                )
        result = json.loads(stdout.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(
            result["dry_run"],
            {"scripted": True, "real_experiment": False},
        )
        self.assertEqual(result["run"]["runtime"]["kind"], "scripted")
        self.assertEqual(len(result["run"]["runtime"]["results"]), 4)


if __name__ == "__main__":
    unittest.main()
