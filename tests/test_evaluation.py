import hashlib
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from magov import (
    AdjudicationVerdict,
    BlindAdjudication,
    CheckpointObservation,
    CoverageObservation,
    DatasetSplit,
    DefectSeverity,
    GoldDefect,
    ReviewFinding,
    ReviewTask,
    ScoreReport,
    TaskSource,
    TaskStatus,
    TrialOutcome,
    TrialSpec,
    UsageObservation,
    build_trial_matrix,
    materialize_task,
    parse_codex_exec_jsonl,
    scan_materialized_task,
    score_findings,
    summarize_outcomes,
)


class TrialMatrixTests(unittest.TestCase):
    def test_twelve_tasks_create_ninety_six_pilot_trials(self) -> None:
        tasks = [
            ReviewTask(
                task_id=f"python-pr-{index:02d}",
                repository=f"https://example.test/repo-{index}.git",
                base_revision="abc123",
                patch_path=f"patches/{index}.diff",
                truth_path=f"truth/{index}.json",
                source=(
                    TaskSource.HISTORICAL
                    if index <= 8
                    else TaskSource.INJECTED
                ),
                split=DatasetSplit.PILOT,
                status=TaskStatus.READY,
                changed_files=("src/example.py",),
                license_spdx="MIT",
                source_reference="https://example.test/fix",
                test_command="python -m unittest",
                patch_sha256="a" * 64,
            )
            for index in range(1, 13)
        ]

        trials = build_trial_matrix(
            tasks,
            model_id="fixed-model",
            prompt_version="python-review-v1",
            repetitions=2,
        )

        self.assertEqual(len(trials), 96)
        self.assertEqual(
            {trial.exact_total_agents for trial in trials}, {1, 2, 3, 4}
        )
        self.assertTrue(all(trial.homogeneous_agents for trial in trials))

    def test_draft_tasks_cannot_be_scheduled(self) -> None:
        task = ReviewTask(
            task_id="draft-task",
            repository="",
            base_revision="",
            patch_path="",
            truth_path="",
            source=TaskSource.HISTORICAL,
            split=DatasetSplit.PILOT,
        )

        with self.assertRaisesRegex(ValueError, "draft tasks"):
            build_trial_matrix(
                [task],
                model_id="fixed-model",
                prompt_version="python-review-v1",
            )

    def test_duplicate_task_ids_and_empty_agent_counts_are_rejected(self) -> None:
        def ready_task() -> ReviewTask:
            return ReviewTask(
                task_id="duplicate",
                repository="https://example.test/repo.git",
                base_revision="abc123",
                patch_path="patches/duplicate.diff",
                truth_path="truth/duplicate.json",
                source=TaskSource.HISTORICAL,
                split=DatasetSplit.PILOT,
                status=TaskStatus.READY,
                changed_files=("src/example.py",),
                license_spdx="MIT",
                source_reference="https://example.test/fix",
                test_command="python -m unittest",
                patch_sha256="a" * 64,
            )

        with self.assertRaisesRegex(ValueError, "task ids must be unique"):
            build_trial_matrix(
                [ready_task(), ready_task()],
                model_id="fixed-model",
                prompt_version="python-review-v1",
            )
        with self.assertRaisesRegex(ValueError, "agent_counts cannot be empty"):
            build_trial_matrix(
                [ready_task()],
                model_id="fixed-model",
                prompt_version="python-review-v1",
                agent_counts=(),
            )


class MaterializationIsolationTests(unittest.TestCase):
    def _task(
        self,
        workspace: Path,
        *,
        patch: str | None = None,
    ) -> ReviewTask:
        fixture = workspace / "fixture"
        fixture.mkdir()
        (fixture / "LICENSE").write_text("MIT\n")
        (fixture / "app.py").write_text("value = 1\n")
        patch_text = patch or (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-value = 1\n"
            "+value = 2\n"
        )
        patch_path = workspace / "task.diff"
        patch_path.write_text(patch_text)
        truth_path = workspace / "truth.json"
        truth_path.write_text(
            json.dumps(
                {
                    "task_id": "local-task",
                    "defects": [
                        {
                            "defect_id": "D-1",
                            "file": "app.py",
                            "symbol": "module",
                            "root_cause_category": "wrong-value",
                            "severity": "ordinary",
                        }
                    ],
                }
            )
        )
        return ReviewTask(
            task_id="local-task",
            repository="local://fixture",
            base_revision="private-revision",
            patch_path="task.diff",
            truth_path="truth.json",
            source=TaskSource.INJECTED,
            split=DatasetSplit.PILOT,
            status=TaskStatus.READY,
            changed_files=("app.py",),
            license_spdx="MIT",
            source_reference="local fixture",
            test_command="python -m unittest",
            patch_sha256=hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        )

    def test_materialized_task_strips_git_and_private_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            task = self._task(workspace)
            git_dir = workspace / "fixture" / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text(
                "private fixing commit subject and hash\n"
            )
            destination = workspace / "trial"

            materialize_task(
                task,
                workspace=workspace,
                destination=destination,
            )

            metadata = json.loads(
                (destination / ".magov-task.json").read_text()
            )
            self.assertFalse((destination / ".git").exists())
            self.assertNotIn("exact_base_revision", metadata)
            self.assertEqual((destination / "app.py").read_text(), "value = 2\n")

    def test_historical_materialization_uses_original_bug_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repository = workspace / "upstream"
            repository.mkdir()

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init")
            git("config", "user.name", "Evaluation Test")
            git("config", "user.email", "eval@example.test")
            (repository / "app.py").write_text("value = 2\n")
            git("add", "app.py")
            git("commit", "-m", "original buggy state")
            buggy_revision = git("rev-parse", "HEAD")

            (repository / "app.py").write_text("value = 1\n")
            (repository / "fix_regression_test.py").write_text(
                "FIX_ANSWER_HINT = True\n"
            )
            git("add", "app.py", "fix_regression_test.py")
            git("commit", "-m", "fix exact bug")
            fix_revision = git("rev-parse", "HEAD")

            patch_path = workspace / "task.diff"
            patch_path.write_text(
                subprocess.run(
                    [
                        "git",
                        "diff",
                        fix_revision,
                        buggy_revision,
                        "--",
                        "app.py",
                    ],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            truth_path = workspace / "truth.json"
            truth_path.write_text(
                json.dumps(
                    {
                        "task_id": "historical-task",
                        "defects": [
                            {
                                "defect_id": "D-1",
                                "file": "app.py",
                                "symbol": "module",
                                "root_cause_category": "wrong-value",
                                "severity": "ordinary",
                            }
                        ],
                    }
                )
            )
            instructions = workspace / "instructions.md"
            instructions.write_text("Review the change.\n")
            task = ReviewTask(
                task_id="historical-task",
                repository=str(repository),
                base_revision=fix_revision,
                materialization_revision=buggy_revision,
                patch_path="task.diff",
                truth_path="truth.json",
                source=TaskSource.HISTORICAL,
                split=DatasetSplit.PILOT,
                status=TaskStatus.READY,
                changed_files=("app.py",),
                license_spdx="MIT",
                source_reference="https://example.test/fix",
                test_command="python -m unittest",
                patch_sha256=hashlib.sha256(patch_path.read_bytes()).hexdigest(),
            )
            destination = workspace / "trial"

            materialize_task(
                task,
                workspace=workspace,
                destination=destination,
                review_instructions=instructions,
            )

            self.assertEqual((destination / "app.py").read_text(), "value = 2\n")
            self.assertFalse((destination / "fix_regression_test.py").exists())
            self.assertFalse((destination / ".git").exists())
            self.assertTrue((destination / ".magov-review.diff").is_file())
            self.assertEqual(
                (destination / "REVIEW_INSTRUCTIONS.md").read_text(),
                "Review the change.\n",
            )
            result = scan_materialized_task(
                destination,
                forbidden_literals=(fix_revision, buggy_revision, "FIX_ANSWER_HINT"),
            )
            self.assertEqual(result["status"], "clean")

    def test_agent_review_diff_redacts_registered_source_hints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            patch = (
                "diff --git a/app.py b/app.py\n"
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1,2 +1 @@\n"
                "-# secret-fix-hint\n"
                "-value = 1\n"
                "+value = 2\n"
            )
            task = self._task(workspace, patch=patch)
            (workspace / "fixture" / "app.py").write_text(
                "# secret-fix-hint\nvalue = 1\n"
            )
            task = replace(
                task,
                patch_sha256=hashlib.sha256(
                    (workspace / "task.diff").read_bytes()
                ).hexdigest(),
            )
            destination = workspace / "trial"

            result = materialize_task(
                task,
                workspace=workspace,
                destination=destination,
                review_diff_redactions=("secret-fix-hint",),
            )

            self.assertEqual(result["review_diff_redactions"], 1)
            self.assertEqual(
                (destination / "app.py").read_text(),
                "value = 2\n",
            )
            agent_diff = (destination / ".magov-review.diff").read_text()
            self.assertNotIn("secret-fix-hint", agent_diff)
            self.assertIn("[redacted-for-blind-review]", agent_diff)
            self.assertIn(
                "secret-fix-hint",
                (workspace / "task.diff").read_text(),
            )
            self.assertEqual(
                scan_materialized_task(
                    destination,
                    forbidden_literals=("secret-fix-hint",),
                )["status"],
                "clean",
            )

    def test_leak_scan_rejects_truth_and_sensitive_literals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            (destination / "app.py").write_text("secret-fix-commit\n")
            with self.assertRaisesRegex(ValueError, "forbidden literal"):
                scan_materialized_task(
                    destination,
                    forbidden_literals=("secret-fix-commit",),
                )
            (destination / "app.py").write_text("safe\n")
            (destination / "truth.json").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "forbidden path"):
                scan_materialized_task(destination)

    def test_local_fixture_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            task = self._task(workspace)
            secret = workspace / "truth-secret.txt"
            secret.write_text("hidden truth\n")
            (workspace / "fixture" / "leak.txt").symlink_to(secret)
            destination = workspace / "trial"

            with self.assertRaisesRegex(ValueError, "symbolic links"):
                materialize_task(
                    task,
                    workspace=workspace,
                    destination=destination,
                )

            self.assertFalse(destination.exists())

    def test_failed_materialization_removes_partial_destination(self) -> None:
        bad_patch = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-value = 999\n"
            "+value = 2\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            task = self._task(workspace, patch=bad_patch)
            destination = workspace / "trial"

            with self.assertRaisesRegex(ValueError, "command failed"):
                materialize_task(
                    task,
                    workspace=workspace,
                    destination=destination,
                )

            self.assertFalse(destination.exists())


class FindingScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.truth = [
            GoldDefect(
                defect_id="D-1",
                file="src/auth.py",
                symbol="authorize",
                root_cause_category="missing-permission-check",
                severity=DefectSeverity.SERIOUS,
                red_line=True,
            ),
            GoldDefect(
                defect_id="D-2",
                file="src/parser.py",
                symbol="parse",
                root_cause_category="missing-empty-input-guard",
                severity=DefectSeverity.ORDINARY,
            ),
        ]

    def test_exact_matches_deduplicate_and_uncertain_findings_wait(self) -> None:
        findings = [
            ReviewFinding(
                finding_id="F-1",
                file="src/auth.py",
                symbol="authorize",
                root_cause_category="missing-permission-check",
                impact="Unauthorized access",
                evidence="The branch returns before checking the caller role.",
            ),
            ReviewFinding(
                finding_id="F-2",
                file="src/auth.py",
                symbol="authorize",
                root_cause_category="missing-permission-check",
                impact="Unauthorized access",
                evidence="A second reviewer identified the same missing check.",
            ),
            ReviewFinding(
                finding_id="F-3",
                file="src/cache.py",
                symbol="load",
                root_cause_category="stale-read",
                impact="May return stale state",
                evidence="The cache key omits the revision.",
            ),
        ]

        report = score_findings(self.truth, findings)

        self.assertEqual(report.found_known_defects, 1)
        self.assertEqual(report.duplicate_findings, 1)
        self.assertEqual(report.pending_findings, ("F-3",))
        self.assertIsNone(report.false_positive_share)
        self.assertFalse(report.complete)

    def test_blind_adjudication_completes_false_positive_scoring(self) -> None:
        finding = ReviewFinding(
            finding_id="F-3",
            file="src/cache.py",
            symbol="load",
            root_cause_category="stale-read",
            impact="May return stale state",
            evidence="The cache key omits the revision.",
        )
        report = score_findings(
            self.truth,
            [finding],
            [
                BlindAdjudication(
                    finding_id="F-3",
                    verdict=AdjudicationVerdict.FALSE_POSITIVE,
                )
            ],
        )

        self.assertTrue(report.complete)
        self.assertEqual(report.false_positive_share, 1.0)
        self.assertEqual(report.missed_red_line_defects, ("D-1",))

    def test_impossible_score_counts_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "found_known_defects cannot exceed"
        ):
            ScoreReport(
                total_known_defects=1,
                found_known_defects=7,
                serious_defects=1,
                found_serious_defects=1,
                valid_other_findings=0,
                false_positive_findings=0,
                duplicate_findings=0,
                pending_findings=(),
                missed_red_line_defects=(),
            )


class EvidenceSummaryTests(unittest.TestCase):
    def test_high_risk_files_require_independent_review(self) -> None:
        task = ReviewTask(
            task_id="python-pr-risk",
            repository="https://example.test/repo.git",
            base_revision="abc123",
            patch_path="patches/risk.diff",
            truth_path="truth/risk.json",
            source=TaskSource.INJECTED,
            split=DatasetSplit.PILOT,
            status=TaskStatus.READY,
            changed_files=("src/ui.py", "src/auth.py"),
            high_risk_files=("src/auth.py",),
            license_spdx="MIT",
            source_reference="https://example.test/fix",
            test_command="python -m unittest",
            patch_sha256="a" * 64,
        )
        first_pass = CoverageObservation(
            reviewed_files=("src/ui.py", "src/auth.py"),
        )
        independently_checked = CoverageObservation(
            reviewed_files=("src/ui.py", "src/auth.py"),
            independently_reviewed_high_risk_files=("src/auth.py",),
        )

        self.assertFalse(first_pass.is_complete_for(task))
        self.assertTrue(independently_checked.is_complete_for(task))

    def test_summary_is_descriptive_and_includes_governance_tokens(self) -> None:
        task = ReviewTask(
            task_id="python-pr-01",
            repository="https://example.test/repo.git",
            base_revision="abc123",
            patch_path="patches/01.diff",
            truth_path="truth/01.json",
            source=TaskSource.HISTORICAL,
            split=DatasetSplit.PILOT,
            status=TaskStatus.READY,
            changed_files=("src/auth.py",),
            license_spdx="MIT",
            source_reference="https://example.test/fix",
            test_command="python -m unittest",
            patch_sha256="a" * 64,
        )
        trial = build_trial_matrix(
            [task],
            model_id="fixed-model",
            prompt_version="python-review-v1",
            agent_counts=(1,),
            repetitions=1,
        )[0]
        score = score_findings(
            [
                GoldDefect(
                    defect_id="D-1",
                    file="src/auth.py",
                    symbol="authorize",
                    root_cause_category="missing-permission-check",
                    severity=DefectSeverity.SERIOUS,
                )
            ],
            [
                ReviewFinding(
                    finding_id="F-1",
                    file="src/auth.py",
                    symbol="authorize",
                    root_cause_category="missing-permission-check",
                    impact="Unauthorized access",
                    evidence="The caller role is never checked.",
                )
            ],
        )
        usage = UsageObservation(
            agent_input_tokens=100,
            agent_output_tokens=20,
            cached_input_tokens=10,
            governance_tokens=5,
            model_calls=1,
            tool_calls=2,
            wall_time_seconds=3.5,
        )
        outcome = TrialOutcome(
            trial=trial,
            actual_total_agents=1,
            usage=usage,
            score=score,
            coverage_complete=True,
            checkpoints=(
                CheckpointObservation(
                    total_agents=1,
                    new_finding_count=1,
                    repeated_finding_count=0,
                    newly_reviewed_files=("src/auth.py",),
                    coverage_complete=True,
                    unresolved_conflicts=0,
                    usage_delta=usage,
                ),
            ),
        )

        summary = summarize_outcomes([outcome])

        self.assertEqual(usage.total_tokens, 125)
        self.assertEqual(summary["status"], "descriptive_only")
        self.assertFalse(summary["claim_allowed"])
        self.assertEqual(
            summary["by_agent_count"]["1"]["mean_total_tokens"], 125
        )
        self.assertEqual(
            summary["by_agent_count"]["1"][
                "mean_final_novel_finding_ratio"
            ],
            1.0,
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
        ordinary = replace(outcome, score=ordinary_score)
        missed_serious = replace(
            outcome,
            trial=replace(
                trial,
                trial_id="python-pr-02__agents-1__repeat-1",
                task_id="python-pr-02",
            ),
            score=missed_serious_score,
        )
        pooled = summarize_outcomes([ordinary, missed_serious])

        self.assertEqual(
            pooled["by_agent_count"]["1"]["mean_serious_recall"],
            0.0,
        )
        self.assertEqual(
            pooled["by_agent_count"]["1"]["total_recall"],
            0.0,
        )
        self.assertEqual(
            pooled["by_agent_count"]["1"]["recall_aggregation"],
            "micro_over_registered_defects",
        )


class OutcomeValidationTests(unittest.TestCase):
    @staticmethod
    def _score() -> ScoreReport:
        return ScoreReport(
            total_known_defects=0,
            found_known_defects=0,
            serious_defects=0,
            found_serious_defects=0,
            valid_other_findings=0,
            false_positive_findings=0,
            duplicate_findings=0,
            pending_findings=(),
            missed_red_line_defects=(),
        )

    def _make_outcome(
        self,
        *,
        task_id: str = "task-1",
        trial_id: str = "trial-1",
        model_id: str = "fixed-model",
        total_agents: int = 1,
    ) -> TrialOutcome:
        usage = UsageObservation(
            agent_input_tokens=total_agents,
            agent_output_tokens=0,
            model_calls=total_agents,
        )
        checkpoints = tuple(
            CheckpointObservation(
                total_agents=index,
                new_finding_count=0,
                repeated_finding_count=0,
                newly_reviewed_files=(),
                coverage_complete=index == total_agents,
                unresolved_conflicts=0,
                usage_delta=UsageObservation(
                    agent_input_tokens=1,
                    agent_output_tokens=0,
                    model_calls=1,
                ),
            )
            for index in range(1, total_agents + 1)
        )
        return TrialOutcome(
            trial=TrialSpec(
                trial_id=trial_id,
                task_id=task_id,
                exact_total_agents=total_agents,
                repetition=1,
                model_id=model_id,
                prompt_version="prompt-v1",
            ),
            actual_total_agents=total_agents,
            usage=usage,
            score=self._score(),
            coverage_complete=True,
            checkpoints=checkpoints,
        )

    def test_string_false_is_not_accepted_as_a_boolean(self) -> None:
        with self.assertRaisesRegex(TypeError, "JSON boolean"):
            CheckpointObservation.from_dict(
                {
                    "total_agents": 1,
                    "coverage_complete": "false",
                    "usage_delta": {},
                }
            )

    def test_outcome_must_match_final_checkpoint(self) -> None:
        usage = UsageObservation(agent_input_tokens=1, agent_output_tokens=0)
        with self.assertRaisesRegex(ValueError, "coverage_complete must match"):
            TrialOutcome(
                trial=TrialSpec(
                    trial_id="trial-1",
                    task_id="task-1",
                    exact_total_agents=1,
                    repetition=1,
                    model_id="fixed-model",
                    prompt_version="prompt-v1",
                ),
                actual_total_agents=1,
                usage=usage,
                score=self._score(),
                coverage_complete=True,
                checkpoints=(
                    CheckpointObservation(
                        total_agents=1,
                        new_finding_count=0,
                        repeated_finding_count=0,
                        newly_reviewed_files=(),
                        coverage_complete=False,
                        unresolved_conflicts=0,
                        usage_delta=usage,
                    ),
                ),
            )

    def test_outcome_requires_every_agent_checkpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "each total_agents value"):
            TrialOutcome(
                trial=TrialSpec(
                    trial_id="trial-2",
                    task_id="task-1",
                    exact_total_agents=2,
                    repetition=1,
                    model_id="fixed-model",
                    prompt_version="prompt-v1",
                ),
                actual_total_agents=2,
                usage=UsageObservation(
                    agent_input_tokens=1,
                    agent_output_tokens=0,
                ),
                score=self._score(),
                coverage_complete=True,
                checkpoints=(
                    CheckpointObservation(
                        total_agents=2,
                        new_finding_count=0,
                        repeated_finding_count=0,
                        newly_reviewed_files=(),
                        coverage_complete=True,
                        unresolved_conflicts=0,
                        usage_delta=UsageObservation(
                            agent_input_tokens=1,
                            agent_output_tokens=0,
                        ),
                    ),
                ),
            )

    def test_summary_rejects_duplicates_and_mixed_models(self) -> None:
        outcome = self._make_outcome()
        with self.assertRaisesRegex(ValueError, "trial ids must be unique"):
            summarize_outcomes([outcome, outcome])

        with self.assertRaisesRegex(ValueError, "must use one model"):
            summarize_outcomes(
                [
                    outcome,
                    self._make_outcome(
                        task_id="task-2",
                        trial_id="trial-2",
                        model_id="different-model",
                    ),
                ]
            )


class CodexUsageIngestionTests(unittest.TestCase):
    def test_reads_usage_and_command_completions_from_jsonl(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "trial-1"},
            {
                "type": "item.completed",
                "item": {"type": "command_execution", "status": "completed"},
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "done"},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 8,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                "2026-07-29T00:00:00Z ERROR diagnostic from stderr\n"
                + "\n".join(json.dumps(event) for event in events)
            )
            usage = parse_codex_exec_jsonl(path, wall_time_seconds=12.5)

        self.assertEqual(usage.agent_input_tokens, 100)
        self.assertEqual(usage.cached_input_tokens, 60)
        self.assertEqual(usage.agent_output_tokens, 20)
        self.assertEqual(usage.reasoning_output_tokens, 8)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.model_calls, 1)
        self.assertEqual(usage.tool_calls, 1)
        self.assertEqual(usage.wall_time_seconds, 12.5)


if __name__ == "__main__":
    unittest.main()
