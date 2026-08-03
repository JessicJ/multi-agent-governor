"""Evidence-first evaluation primitives for Multi-Agent Governor.

This module does not launch agents.  It creates controlled fixed-agent trial
specifications, validates local measurements, scores structured review
findings against hidden truth cards, and summarizes completed trials.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from enum import Enum
from math import isclose, isfinite
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


class DatasetSplit(str, Enum):
    PILOT = "pilot"
    CALIBRATION = "calibration"
    HOLDOUT = "holdout"


class TaskSource(str, Enum):
    HISTORICAL = "historical"
    INJECTED = "injected"


class TaskStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"


class DefectSeverity(str, Enum):
    SERIOUS = "serious"
    ORDINARY = "ordinary"
    MINOR = "minor"


class AdjudicationVerdict(str, Enum):
    MATCHED = "matched"
    VALID_OTHER = "valid_other"
    FALSE_POSITIVE = "false_positive"


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a JSON boolean")
    return value


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a JSON array of strings")
    result = tuple(value)
    if any(not isinstance(item, str) for item in result):
        raise TypeError(f"{name} must be a JSON array of strings")
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


@dataclass(frozen=True)
class ReviewTask:
    """One bounded Python pull-request review task."""

    task_id: str
    repository: str
    base_revision: str
    patch_path: str
    truth_path: str
    source: TaskSource
    split: DatasetSplit
    status: TaskStatus = TaskStatus.DRAFT
    language: str = "python"
    changed_files: tuple[str, ...] = ()
    high_risk_files: tuple[str, ...] = ()
    license_spdx: str = ""
    source_reference: str = ""
    test_command: str = ""
    patch_sha256: str = ""
    materialization_revision: str = ""

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if self.language.lower() != "python":
            raise ValueError("the first evaluation protocol only supports Python")
        if self.status is TaskStatus.READY:
            for name in ("repository", "base_revision", "patch_path", "truth_path"):
                if not getattr(self, name).strip():
                    raise ValueError(f"{name} is required for a ready task")
            for name in (
                "license_spdx",
                "source_reference",
                "test_command",
                "patch_sha256",
            ):
                if not getattr(self, name).strip():
                    raise ValueError(f"{name} is required for a ready task")
            if len(self.patch_sha256) != 64 or any(
                character not in "0123456789abcdef"
                for character in self.patch_sha256.lower()
            ):
                raise ValueError("patch_sha256 must be a 64-character hex digest")
            if not self.changed_files:
                raise ValueError("a ready task must list its changed files")
        unknown_high_risk = set(self.high_risk_files) - set(self.changed_files)
        if unknown_high_risk:
            raise ValueError(
                "high_risk_files must be included in changed_files: "
                + ", ".join(sorted(unknown_high_risk))
            )
        if self.materialization_revision and self.repository.startswith("local://"):
            raise ValueError(
                "materialization_revision is only supported for upstream repositories"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewTask":
        return cls(
            task_id=str(payload["task_id"]),
            repository=str(payload.get("repository", "")),
            base_revision=str(payload.get("base_revision", "")),
            patch_path=str(payload.get("patch_path", "")),
            truth_path=str(payload.get("truth_path", "")),
            source=TaskSource(payload["source"]),
            split=DatasetSplit(payload["split"]),
            status=TaskStatus(payload.get("status", "draft")),
            language=str(payload.get("language", "python")),
            changed_files=_string_tuple(
                payload.get("changed_files", ()), "changed_files"
            ),
            high_risk_files=_string_tuple(
                payload.get("high_risk_files", ()), "high_risk_files"
            ),
            license_spdx=str(payload.get("license_spdx", "")),
            source_reference=str(payload.get("source_reference", "")),
            test_command=str(payload.get("test_command", "")),
            patch_sha256=str(payload.get("patch_sha256", "")),
            materialization_revision=str(
                payload.get("materialization_revision", "")
            ),
        )

    def resolve_patch_path(self, workspace: Path) -> Path:
        path = Path(self.patch_path)
        return path if path.is_absolute() else workspace / path


@dataclass(frozen=True)
class TrialSpec:
    """A controlled arm where the runtime must use exactly N total agents."""

    trial_id: str
    task_id: str
    exact_total_agents: int
    repetition: int
    model_id: str
    prompt_version: str
    topology: str = "centralized"
    homogeneous_agents: bool = True

    def __post_init__(self) -> None:
        if not self.trial_id.strip() or not self.task_id.strip():
            raise ValueError("trial_id and task_id cannot be empty")
        if self.exact_total_agents not in range(1, 9):
            raise ValueError("exact_total_agents must be between 1 and 8")
        if self.repetition < 1:
            raise ValueError("repetition must be at least 1")
        if not self.model_id.strip() or not self.prompt_version.strip():
            raise ValueError("model_id and prompt_version cannot be empty")
        if self.topology != "centralized":
            raise ValueError("the first evaluation fixes topology to centralized")
        if not self.homogeneous_agents:
            raise ValueError("the first evaluation requires homogeneous agents")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TrialSpec":
        return cls(
            trial_id=str(payload["trial_id"]),
            task_id=str(payload["task_id"]),
            exact_total_agents=int(payload["exact_total_agents"]),
            repetition=int(payload["repetition"]),
            model_id=str(payload["model_id"]),
            prompt_version=str(payload["prompt_version"]),
            topology=str(payload.get("topology", "centralized")),
            homogeneous_agents=_require_bool(
                payload.get("homogeneous_agents", True),
                "homogeneous_agents",
            ),
        )


def build_trial_matrix(
    tasks: Sequence[ReviewTask],
    *,
    model_id: str,
    prompt_version: str,
    agent_counts: Sequence[int] = (1, 2, 3, 4),
    repetitions: int = 2,
) -> tuple[TrialSpec, ...]:
    """Build a deterministic fixed-count trial matrix.

    Draft tasks are rejected so placeholder entries cannot accidentally produce
    evidence-looking results.
    """

    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if not tasks:
        raise ValueError("at least one task is required")
    if not model_id.strip() or not prompt_version.strip():
        raise ValueError("model_id and prompt_version cannot be empty")
    if not agent_counts:
        raise ValueError("agent_counts cannot be empty")
    if len(set(agent_counts)) != len(agent_counts):
        raise ValueError("agent_counts cannot contain duplicates")
    invalid_counts = set(agent_counts) - set(range(1, 9))
    if invalid_counts:
        raise ValueError("agent_counts must be drawn from 1 through 8")
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be unique")

    drafts = [task.task_id for task in tasks if task.status is not TaskStatus.READY]
    if drafts:
        raise ValueError(
            "draft tasks cannot be scheduled: " + ", ".join(sorted(drafts))
        )

    trials: list[TrialSpec] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        for total_agents in sorted(agent_counts):
            for repetition in range(1, repetitions + 1):
                trial_id = (
                    f"{task.task_id}__agents-{total_agents}__repeat-{repetition}"
                )
                trials.append(
                    TrialSpec(
                        trial_id=trial_id,
                        task_id=task.task_id,
                        exact_total_agents=total_agents,
                        repetition=repetition,
                        model_id=model_id,
                        prompt_version=prompt_version,
                    )
                )
    return tuple(trials)


def validate_task_assets(
    tasks: Sequence[ReviewTask], workspace: Path
) -> dict[str, Any]:
    """Validate local task metadata, hashes, truth cards, and fixture sources."""

    workspace = workspace.resolve()
    if not tasks:
        raise ValueError("at least one task is required")
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be unique")

    errors: list[str] = []
    defect_count = 0
    serious_count = 0
    red_line_count = 0
    source_counts = {source.value: 0 for source in TaskSource}

    for task in tasks:
        source_counts[task.source.value] += 1
        if task.status is not TaskStatus.READY:
            errors.append(f"{task.task_id}: task is not ready")
            continue
        try:
            patch_path = _inside_workspace(workspace, task.patch_path)
            truth_path = _inside_workspace(workspace, task.truth_path)
        except ValueError as exc:
            errors.append(f"{task.task_id}: {exc}")
            continue

        if not patch_path.is_file():
            errors.append(f"{task.task_id}: patch file does not exist")
        else:
            digest = hashlib.sha256(patch_path.read_bytes()).hexdigest()
            if digest != task.patch_sha256.lower():
                errors.append(
                    f"{task.task_id}: patch hash mismatch "
                    f"(expected {task.patch_sha256}, got {digest})"
                )

        if not truth_path.is_file():
            errors.append(f"{task.task_id}: truth file does not exist")
        else:
            try:
                payload = json.loads(
                    truth_path.read_text(),
                    parse_constant=_reject_json_constant,
                )
                if payload.get("task_id") != task.task_id:
                    errors.append(
                        f"{task.task_id}: truth file task_id does not match"
                    )
                defects = [
                    GoldDefect.from_dict(item)
                    for item in payload.get("defects", ())
                ]
                if not defects:
                    errors.append(
                        f"{task.task_id}: truth file has no defects"
                    )
                for defect in defects:
                    defect_count += 1
                    serious_count += (
                        defect.severity is DefectSeverity.SERIOUS
                    )
                    red_line_count += defect.red_line
                    if defect.file not in task.changed_files:
                        errors.append(
                            f"{task.task_id}: truth defect {defect.defect_id} "
                            "is outside changed_files"
                        )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{task.task_id}: invalid truth file: {exc}")

        if task.repository.startswith("local://"):
            local_source = task.repository.removeprefix("local://")
            try:
                source_path = _inside_workspace(workspace, local_source)
            except ValueError as exc:
                errors.append(f"{task.task_id}: {exc}")
            else:
                if not source_path.is_dir():
                    errors.append(
                        f"{task.task_id}: local repository does not exist"
                    )
                if not (source_path / "LICENSE").is_file():
                    errors.append(
                        f"{task.task_id}: local repository has no LICENSE"
                    )

    if errors:
        raise ValueError("; ".join(errors))
    return {
        "status": "valid",
        "tasks": len(tasks),
        "historical_tasks": source_counts[TaskSource.HISTORICAL.value],
        "injected_tasks": source_counts[TaskSource.INJECTED.value],
        "known_defects": defect_count,
        "serious_defects": serious_count,
        "red_line_defects": red_line_count,
    }


def materialize_task(
    task: ReviewTask,
    *,
    workspace: Path,
    destination: Path,
    review_instructions: Path | None = None,
    review_diff_redactions: Sequence[str] = (),
) -> dict[str, Any]:
    """Create an isolated review worktree without copying truth or hidden tests."""

    workspace = workspace.resolve()
    destination = destination.resolve()
    validate_task_assets([task], workspace)
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    patch_path = _inside_workspace(workspace, task.patch_path)
    instructions_path = (
        _inside_workspace(workspace, str(review_instructions))
        if review_instructions is not None
        else None
    )
    if instructions_path is not None and not instructions_path.is_file():
        raise ValueError(
            f"review instructions file does not exist: {instructions_path}"
        )

    try:
        if task.repository.startswith("local://"):
            source = _inside_workspace(
                workspace, task.repository.removeprefix("local://")
            )
            _reject_symlinks(source)
            shutil.copytree(source, destination)
        else:
            _run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    task.repository,
                    str(destination),
                ],
                cwd=workspace,
            )
            _run(
                [
                    "git",
                    "checkout",
                    "--detach",
                    task.materialization_revision or task.base_revision,
                ],
                cwd=destination,
            )

        if task.materialization_revision:
            # The checked-out tree is already the historical defect state.
            # Reversing the registered reverse patch must still apply cleanly,
            # proving that this state maps back to the fixed production code.
            _run(
                ["git", "apply", "--reverse", "--check", str(patch_path)],
                cwd=destination,
            )
        else:
            _run(["git", "apply", "--check", str(patch_path)], cwd=destination)
            _run(["git", "apply", str(patch_path)], cwd=destination)
        review_diff = patch_path.read_text()
        applied_redactions = 0
        for literal in dict.fromkeys(
            value.strip() for value in review_diff_redactions if value.strip()
        ):
            occurrences = review_diff.count(literal)
            if occurrences:
                review_diff = review_diff.replace(
                    literal,
                    "[redacted-for-blind-review]",
                )
                applied_redactions += occurrences
        (destination / ".magov-review.diff").write_text(review_diff)
        _remove_git_metadata(destination)
        if instructions_path is not None:
            shutil.copy2(
                instructions_path,
                destination / "REVIEW_INSTRUCTIONS.md",
            )
        public_metadata = {
            "task_id": task.task_id,
            "language": task.language,
            "changed_files": list(task.changed_files),
            "high_risk_files": list(task.high_risk_files),
            "truth_included": False,
        }
        (destination / ".magov-task.json").write_text(
            json.dumps(
                public_metadata,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return {
        "status": "materialized",
        "task_id": task.task_id,
        "destination": str(destination),
        "truth_included": False,
        "review_diff_redactions": applied_redactions,
    }


def scan_materialized_task(
    destination: Path,
    *,
    forbidden_literals: Sequence[str] = (),
) -> dict[str, Any]:
    """Fail closed when a materialized Agent directory contains answer hints."""

    destination = destination.resolve()
    if not destination.is_dir():
        raise ValueError(f"materialized directory does not exist: {destination}")
    forbidden_names = {
        ".git",
        "truth.json",
        "hidden_test.py",
        "historical_provenance.json",
        "pilot_manifest.json",
    }
    artifact_suffixes = (
        ".events.jsonl",
        ".stderr.log",
        ".last-message.txt",
        ".report.json",
        ".outcome.json",
    )
    literals = tuple(
        dict.fromkeys(
            item
            for item in (str(value).strip() for value in forbidden_literals)
            if item
        )
    )
    encoded_literals = tuple(
        (literal, literal.encode("utf-8")) for literal in literals
    )
    violations: list[str] = []
    files_scanned = 0
    bytes_scanned = 0

    for path in sorted(destination.rglob("*")):
        relative = path.relative_to(destination)
        if path.is_symlink():
            violations.append(f"symbolic link: {relative}")
            continue
        lowered_parts = {part.lower() for part in relative.parts}
        if lowered_parts & forbidden_names:
            violations.append(f"forbidden path: {relative}")
        lowered_name = path.name.lower()
        if lowered_name.endswith(artifact_suffixes):
            violations.append(f"runtime artifact: {relative}")
        if not path.is_file():
            continue
        files_scanned += 1
        payload = path.read_bytes()
        bytes_scanned += len(payload)
        for literal, encoded in encoded_literals:
            if encoded in payload:
                violations.append(
                    f"forbidden literal in {relative}: sha256="
                    + hashlib.sha256(literal.encode("utf-8")).hexdigest()
                )

    if violations:
        raise ValueError(
            "materialized task leak scan failed: " + "; ".join(violations)
        )
    return {
        "status": "clean",
        "destination": str(destination),
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "forbidden_names_checked": len(forbidden_names),
        "forbidden_literals_checked": len(literals),
        "runtime_artifact_suffixes_checked": len(artifact_suffixes),
        "violations": [],
    }


def _reject_symlinks(source: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(
                "local repository cannot contain symbolic links: "
                + str(path.relative_to(source))
            )


def _remove_git_metadata(destination: Path) -> None:
    candidates = [destination / ".git"]
    candidates.extend(destination.rglob(".git"))
    unique_candidates = sorted(
        set(candidates),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in unique_candidates:
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


@dataclass(frozen=True)
class GoldDefect:
    """Hidden truth card for a known defect."""

    defect_id: str
    file: str
    symbol: str
    root_cause_category: str
    severity: DefectSeverity
    red_line: bool = False
    trigger_test: str = ""
    accepted_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("defect_id", "file", "symbol", "root_cause_category"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoldDefect":
        return cls(
            defect_id=str(payload["defect_id"]),
            file=str(payload["file"]),
            symbol=str(payload["symbol"]),
            root_cause_category=str(payload["root_cause_category"]),
            severity=DefectSeverity(payload["severity"]),
            red_line=_require_bool(payload.get("red_line", False), "red_line"),
            trigger_test=str(payload.get("trigger_test", "")),
            accepted_symbols=_string_tuple(
                payload.get("accepted_symbols", ()), "accepted_symbols"
            ),
        )

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return (self.symbol, *self.accepted_symbols)


@dataclass(frozen=True)
class ReviewFinding:
    """Structured issue emitted by an agent review."""

    finding_id: str
    file: str
    symbol: str
    root_cause_category: str
    impact: str
    evidence: str
    claimed_severity: DefectSeverity | None = None

    def __post_init__(self) -> None:
        for name in (
            "finding_id",
            "file",
            "symbol",
            "root_cause_category",
            "impact",
            "evidence",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewFinding":
        severity = payload.get("claimed_severity")
        return cls(
            finding_id=str(payload["finding_id"]),
            file=str(payload["file"]),
            symbol=str(payload["symbol"]),
            root_cause_category=str(payload["root_cause_category"]),
            impact=str(payload["impact"]),
            evidence=str(payload["evidence"]),
            claimed_severity=DefectSeverity(severity) if severity else None,
        )


@dataclass(frozen=True)
class BlindAdjudication:
    """Human ruling for a finding that cannot be matched deterministically."""

    finding_id: str
    verdict: AdjudicationVerdict
    defect_id: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.finding_id.strip():
            raise ValueError("finding_id cannot be empty")
        if self.verdict is AdjudicationVerdict.MATCHED and not self.defect_id:
            raise ValueError("a matched adjudication requires defect_id")
        if self.verdict is not AdjudicationVerdict.MATCHED and self.defect_id:
            raise ValueError("only matched adjudications may include defect_id")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BlindAdjudication":
        return cls(
            finding_id=str(payload["finding_id"]),
            verdict=AdjudicationVerdict(payload["verdict"]),
            defect_id=(
                str(payload["defect_id"]) if payload.get("defect_id") else None
            ),
            note=str(payload.get("note", "")),
        )


@dataclass(frozen=True)
class ScoreReport:
    total_known_defects: int
    found_known_defects: int
    serious_defects: int
    found_serious_defects: int
    valid_other_findings: int
    false_positive_findings: int
    duplicate_findings: int
    pending_findings: tuple[str, ...]
    missed_red_line_defects: tuple[str, ...]

    def __post_init__(self) -> None:
        count_names = (
            "total_known_defects",
            "found_known_defects",
            "serious_defects",
            "found_serious_defects",
            "valid_other_findings",
            "false_positive_findings",
            "duplicate_findings",
        )
        for name in count_names:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.found_known_defects > self.total_known_defects:
            raise ValueError(
                "found_known_defects cannot exceed total_known_defects"
            )
        if self.serious_defects > self.total_known_defects:
            raise ValueError("serious_defects cannot exceed total_known_defects")
        if self.found_serious_defects > self.serious_defects:
            raise ValueError(
                "found_serious_defects cannot exceed serious_defects"
            )
        if self.found_serious_defects > self.found_known_defects:
            raise ValueError(
                "found_serious_defects cannot exceed found_known_defects"
            )
        if len(self.pending_findings) != len(set(self.pending_findings)):
            raise ValueError("pending_findings cannot contain duplicates")
        if len(self.missed_red_line_defects) != len(
            set(self.missed_red_line_defects)
        ):
            raise ValueError(
                "missed_red_line_defects cannot contain duplicates"
            )

    @property
    def recall(self) -> float:
        if self.total_known_defects == 0:
            return 1.0
        return self.found_known_defects / self.total_known_defects

    @property
    def serious_recall(self) -> float:
        if self.serious_defects == 0:
            return 1.0
        return self.found_serious_defects / self.serious_defects

    @property
    def false_positive_share(self) -> float | None:
        if self.pending_findings:
            return None
        supported = self.found_known_defects + self.valid_other_findings
        denominator = supported + self.false_positive_findings
        if denominator == 0:
            return 0.0
        return self.false_positive_findings / denominator

    @property
    def complete(self) -> bool:
        return not self.pending_findings

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(
            {
                "recall": round(self.recall, 6),
                "serious_recall": round(self.serious_recall, 6),
                "false_positive_share": (
                    round(self.false_positive_share, 6)
                    if self.false_positive_share is not None
                    else None
                ),
                "complete": self.complete,
            }
        )
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScoreReport":
        return cls(
            total_known_defects=int(payload["total_known_defects"]),
            found_known_defects=int(payload["found_known_defects"]),
            serious_defects=int(payload["serious_defects"]),
            found_serious_defects=int(payload["found_serious_defects"]),
            valid_other_findings=int(payload.get("valid_other_findings", 0)),
            false_positive_findings=int(
                payload.get("false_positive_findings", 0)
            ),
            duplicate_findings=int(payload.get("duplicate_findings", 0)),
            pending_findings=_string_tuple(
                payload.get("pending_findings", ()), "pending_findings"
            ),
            missed_red_line_defects=_string_tuple(
                payload.get("missed_red_line_defects", ()),
                "missed_red_line_defects",
            ),
        )


def _pooled_defect_recall(
    scores: Sequence[ScoreReport],
    *,
    serious: bool,
) -> float:
    total_name = "serious_defects" if serious else "total_known_defects"
    found_name = (
        "found_serious_defects" if serious else "found_known_defects"
    )
    total = sum(getattr(score, total_name) for score in scores)
    if total == 0:
        return 1.0
    return sum(getattr(score, found_name) for score in scores) / total


def score_findings(
    truth: Sequence[GoldDefect],
    findings: Sequence[ReviewFinding],
    adjudications: Sequence[BlindAdjudication] = (),
) -> ScoreReport:
    """Score findings without treating uncertain reports as false positives.

    Exact file + symbol + root-cause-category matches are automatic.  Every
    other finding remains pending until a blind adjudication marks it as a
    known defect, another valid defect, or a false positive.
    """

    truth_by_id = _unique_by_id(truth, "defect_id")
    findings_by_id = _unique_by_id(findings, "finding_id")
    adjudication_by_id = _unique_by_id(adjudications, "finding_id")
    unknown_adjudications = set(adjudication_by_id) - set(findings_by_id)
    if unknown_adjudications:
        raise ValueError(
            "adjudications reference unknown findings: "
            + ", ".join(sorted(unknown_adjudications))
        )

    found_defect_ids: set[str] = set()
    duplicate_findings = 0
    valid_other_findings = 0
    false_positive_findings = 0
    pending_findings: list[str] = []

    for finding in findings:
        exact = [
            defect
            for defect in truth
            if _normal(finding.file) == _normal(defect.file)
            and _normal(finding.symbol)
            in {_normal(symbol) for symbol in defect.all_symbols}
            and _normal(finding.root_cause_category)
            == _normal(defect.root_cause_category)
        ]
        matched_defect_id: str | None = None
        if len(exact) == 1:
            matched_defect_id = exact[0].defect_id
        elif finding.finding_id in adjudication_by_id:
            ruling = adjudication_by_id[finding.finding_id]
            if ruling.verdict is AdjudicationVerdict.MATCHED:
                if ruling.defect_id not in truth_by_id:
                    raise ValueError(
                        f"adjudication references unknown defect: {ruling.defect_id}"
                    )
                matched_defect_id = ruling.defect_id
            elif ruling.verdict is AdjudicationVerdict.VALID_OTHER:
                valid_other_findings += 1
            else:
                false_positive_findings += 1
        else:
            pending_findings.append(finding.finding_id)

        if matched_defect_id is not None:
            if matched_defect_id in found_defect_ids:
                duplicate_findings += 1
            else:
                found_defect_ids.add(matched_defect_id)

    serious_ids = {
        defect.defect_id
        for defect in truth
        if defect.severity is DefectSeverity.SERIOUS
    }
    red_line_ids = {defect.defect_id for defect in truth if defect.red_line}
    return ScoreReport(
        total_known_defects=len(truth),
        found_known_defects=len(found_defect_ids),
        serious_defects=len(serious_ids),
        found_serious_defects=len(found_defect_ids & serious_ids),
        valid_other_findings=valid_other_findings,
        false_positive_findings=false_positive_findings,
        duplicate_findings=duplicate_findings,
        pending_findings=tuple(sorted(pending_findings)),
        missed_red_line_defects=tuple(sorted(red_line_ids - found_defect_ids)),
    )


@dataclass(frozen=True)
class UsageObservation:
    """Raw, price-independent resource usage for a completed trial.

    ``agent_input_tokens`` includes cached input tokens.  The cached field is a
    diagnostic subset and is therefore not added a second time.  Governance
    tokens must only contain overhead not already counted in agent input/output.
    ``reasoning_output_tokens`` is likewise a diagnostic detail reported by
    Codex CLI and is not added separately to avoid double-counting output.
    """

    agent_input_tokens: int
    agent_output_tokens: int
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    governance_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    wall_time_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "agent_input_tokens",
            "agent_output_tokens",
            "cached_input_tokens",
            "reasoning_output_tokens",
            "governance_tokens",
            "model_calls",
            "tool_calls",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if (
            not isfinite(self.wall_time_seconds)
            or self.wall_time_seconds < 0
        ):
            raise ValueError("wall_time_seconds cannot be negative")
        if self.cached_input_tokens > self.agent_input_tokens:
            raise ValueError(
                "cached_input_tokens cannot exceed agent_input_tokens"
            )
        if self.reasoning_output_tokens > self.agent_output_tokens:
            raise ValueError(
                "reasoning_output_tokens cannot exceed agent_output_tokens"
            )

    @property
    def total_tokens(self) -> int:
        return (
            self.agent_input_tokens
            + self.agent_output_tokens
            + self.governance_tokens
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["total_tokens"] = self.total_tokens
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UsageObservation":
        return cls(
            agent_input_tokens=int(payload.get("agent_input_tokens", 0)),
            agent_output_tokens=int(payload.get("agent_output_tokens", 0)),
            cached_input_tokens=int(payload.get("cached_input_tokens", 0)),
            reasoning_output_tokens=int(
                payload.get("reasoning_output_tokens", 0)
            ),
            governance_tokens=int(payload.get("governance_tokens", 0)),
            model_calls=int(payload.get("model_calls", 0)),
            tool_calls=int(payload.get("tool_calls", 0)),
            wall_time_seconds=float(payload.get("wall_time_seconds", 0.0)),
        )


def parse_codex_exec_jsonl(
    events_path: Path, *, wall_time_seconds: float = 0.0
) -> UsageObservation:
    """Read one ``codex exec --json`` log into a price-independent usage record.

    A non-interactive Codex execution must emit exactly one ``turn.completed``
    event. Command-execution completions are counted as tool calls. The caller
    measures wall time externally because Codex JSONL does not guarantee a
    portable elapsed-time field on every event.
    """

    completed_usage: Mapping[str, Any] | None = None
    tool_calls = 0

    for line_number, line in enumerate(events_path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        if not line.lstrip().startswith("{"):
            # ``codex exec --json`` writes events to stdout, but a terminal
            # capture may combine them with timestamped diagnostics from stderr.
            continue
        try:
            event = json.loads(line, parse_constant=_reject_json_constant)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid Codex JSON event on line {line_number}: {exc}"
            ) from exc
        if not isinstance(event, Mapping):
            raise ValueError(f"Codex event on line {line_number} is not an object")

        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, Mapping) and item.get("type") == "command_execution":
                tool_calls += 1

        if event.get("type") == "turn.completed":
            usage = event.get("usage")
            if not isinstance(usage, Mapping):
                raise ValueError("turn.completed event has no usage object")
            if completed_usage is not None:
                raise ValueError("Codex JSONL must contain exactly one turn.completed event")
            completed_usage = usage

    if completed_usage is None:
        raise ValueError("Codex JSONL has no turn.completed usage event")

    return UsageObservation(
        agent_input_tokens=int(completed_usage.get("input_tokens", 0)),
        agent_output_tokens=int(completed_usage.get("output_tokens", 0)),
        cached_input_tokens=int(completed_usage.get("cached_input_tokens", 0)),
        reasoning_output_tokens=int(
            completed_usage.get("reasoning_output_tokens", 0)
        ),
        model_calls=1,
        tool_calls=tool_calls,
        wall_time_seconds=wall_time_seconds,
    )


@dataclass(frozen=True)
class CoverageObservation:
    reviewed_files: tuple[str, ...]
    independently_reviewed_high_risk_files: tuple[str, ...] = ()
    unresolved_conflicts: int = 0

    def __post_init__(self) -> None:
        if self.unresolved_conflicts < 0:
            raise ValueError("unresolved_conflicts cannot be negative")

    def is_complete_for(self, task: ReviewTask) -> bool:
        return (
            set(task.changed_files).issubset(self.reviewed_files)
            and set(task.high_risk_files).issubset(
                self.independently_reviewed_high_risk_files
            )
            and self.unresolved_conflicts == 0
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CoverageObservation":
        return cls(
            reviewed_files=_string_tuple(
                payload.get("reviewed_files", ()), "reviewed_files"
            ),
            independently_reviewed_high_risk_files=_string_tuple(
                payload.get("independently_reviewed_high_risk_files", ()),
                "independently_reviewed_high_risk_files",
            ),
            unresolved_conflicts=int(payload.get("unresolved_conflicts", 0)),
        )


@dataclass(frozen=True)
class CheckpointObservation:
    """Observable marginal evidence after one more agent report arrives."""

    total_agents: int
    new_finding_count: int
    repeated_finding_count: int
    newly_reviewed_files: tuple[str, ...]
    coverage_complete: bool
    unresolved_conflicts: int
    usage_delta: UsageObservation

    def __post_init__(self) -> None:
        if self.total_agents < 1:
            raise ValueError("total_agents must be at least 1")
        for name in (
            "new_finding_count",
            "repeated_finding_count",
            "unresolved_conflicts",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def novel_finding_ratio(self) -> float:
        total = self.new_finding_count + self.repeated_finding_count
        if total == 0:
            return 0.0
        return self.new_finding_count / total

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["usage_delta"] = self.usage_delta.to_dict()
        result["novel_finding_ratio"] = round(self.novel_finding_ratio, 6)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CheckpointObservation":
        return cls(
            total_agents=int(payload["total_agents"]),
            new_finding_count=int(payload.get("new_finding_count", 0)),
            repeated_finding_count=int(
                payload.get("repeated_finding_count", 0)
            ),
            newly_reviewed_files=_string_tuple(
                payload.get("newly_reviewed_files", ()),
                "newly_reviewed_files",
            ),
            coverage_complete=_require_bool(
                payload.get("coverage_complete", False),
                "coverage_complete",
            ),
            unresolved_conflicts=int(payload.get("unresolved_conflicts", 0)),
            usage_delta=UsageObservation.from_dict(payload["usage_delta"]),
        )


@dataclass(frozen=True)
class TrialOutcome:
    trial: TrialSpec
    actual_total_agents: int
    usage: UsageObservation
    score: ScoreReport
    coverage_complete: bool
    unresolved_conflicts: int = 0
    checkpoints: tuple[CheckpointObservation, ...] = ()
    wall_time_seconds: float = 0.0
    scripted_dry_run: bool = False

    def __post_init__(self) -> None:
        if self.actual_total_agents != self.trial.exact_total_agents:
            raise ValueError(
                "actual_total_agents must equal the fixed trial agent count"
            )
        if self.unresolved_conflicts < 0:
            raise ValueError("unresolved_conflicts cannot be negative")
        if (
            not isfinite(self.wall_time_seconds)
            or self.wall_time_seconds < 0
        ):
            raise ValueError("wall_time_seconds cannot be negative")
        if type(self.scripted_dry_run) is not bool:
            raise ValueError("scripted_dry_run must be a boolean")
        checkpoint_counts = [item.total_agents for item in self.checkpoints]
        expected_counts = list(range(1, self.actual_total_agents + 1))
        if checkpoint_counts != expected_counts:
            raise ValueError(
                "checkpoints must contain each total_agents value from 1 "
                "through actual_total_agents"
            )
        final_checkpoint = self.checkpoints[-1]
        if final_checkpoint.coverage_complete != self.coverage_complete:
            raise ValueError(
                "final checkpoint coverage_complete must match the outcome"
            )
        if final_checkpoint.unresolved_conflicts != self.unresolved_conflicts:
            raise ValueError(
                "final checkpoint unresolved_conflicts must match the outcome"
            )
        usage_fields = (
            "agent_input_tokens",
            "agent_output_tokens",
            "cached_input_tokens",
            "reasoning_output_tokens",
            "governance_tokens",
            "model_calls",
            "tool_calls",
        )
        for name in usage_fields:
            observed = sum(
                getattr(item.usage_delta, name) for item in self.checkpoints
            )
            if observed != getattr(self.usage, name):
                raise ValueError(
                    f"checkpoint usage deltas do not sum to usage.{name}"
                )
        checkpoint_wall_time = sum(
            item.usage_delta.wall_time_seconds for item in self.checkpoints
        )
        if not isclose(
            checkpoint_wall_time,
            self.usage.wall_time_seconds,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "checkpoint usage deltas do not sum to usage.wall_time_seconds"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial": self.trial.to_dict(),
            "actual_total_agents": self.actual_total_agents,
            "usage": self.usage.to_dict(),
            "score": self.score.to_dict(),
            "coverage_complete": self.coverage_complete,
            "unresolved_conflicts": self.unresolved_conflicts,
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "wall_time_seconds": self.wall_time_seconds,
            "scripted_dry_run": self.scripted_dry_run,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TrialOutcome":
        return cls(
            trial=TrialSpec.from_dict(payload["trial"]),
            actual_total_agents=int(payload["actual_total_agents"]),
            usage=UsageObservation.from_dict(payload["usage"]),
            score=ScoreReport.from_dict(payload["score"]),
            coverage_complete=_require_bool(
                payload["coverage_complete"], "coverage_complete"
            ),
            unresolved_conflicts=int(payload.get("unresolved_conflicts", 0)),
            checkpoints=tuple(
                CheckpointObservation.from_dict(item)
                for item in payload.get("checkpoints", ())
            ),
            wall_time_seconds=float(payload.get("wall_time_seconds", 0.0)),
            scripted_dry_run=_require_bool(
                payload.get("scripted_dry_run", False),
                "scripted_dry_run",
            ),
        )


def summarize_outcomes(outcomes: Sequence[TrialOutcome]) -> dict[str, Any]:
    """Produce descriptive evidence by fixed agent count.

    This deliberately does not declare non-inferiority.  Confidence intervals
    and the predeclared quality guardrails belong to the later formal report.
    """

    if not outcomes:
        raise ValueError("at least one outcome is required")
    trial_ids = [outcome.trial.trial_id for outcome in outcomes]
    if len(trial_ids) != len(set(trial_ids)):
        raise ValueError("trial ids must be unique")
    conditions = {
        (
            outcome.trial.model_id,
            outcome.trial.prompt_version,
            outcome.trial.topology,
            outcome.trial.homogeneous_agents,
            outcome.scripted_dry_run,
        )
        for outcome in outcomes
    }
    if len(conditions) != 1:
        raise ValueError(
            "outcomes must use one model, prompt version, topology, "
            "and agent homogeneity setting"
        )
    logical_trials = [
        (
            outcome.trial.task_id,
            outcome.actual_total_agents,
            outcome.trial.repetition,
        )
        for outcome in outcomes
    ]
    if len(logical_trials) != len(set(logical_trials)):
        raise ValueError(
            "task, agent count, and repetition combinations must be unique"
        )
    grouped: dict[int, list[TrialOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault(outcome.actual_total_agents, []).append(outcome)
    task_repetitions_by_count = {
        count: {
            (outcome.trial.task_id, outcome.trial.repetition)
            for outcome in group
        }
        for count, group in grouped.items()
    }
    first_arm = next(iter(task_repetitions_by_count.values()))
    if any(
        arm != first_arm for arm in task_repetitions_by_count.values()
    ):
        raise ValueError(
            "each agent-count arm must contain the same task/repetition pairs"
        )

    by_agent_count: dict[str, Any] = {}
    for count, group in sorted(grouped.items()):
        complete = [item for item in group if item.score.complete]
        by_agent_count[str(count)] = {
            "trials": len(group),
            "complete_scores": len(complete),
            "mean_serious_recall": (
                round(
                    _pooled_defect_recall(
                        [item.score for item in complete],
                        serious=True,
                    ),
                    6,
                )
                if complete
                else None
            ),
            "total_recall": (
                round(
                    _pooled_defect_recall(
                        [item.score for item in complete],
                        serious=False,
                    ),
                    6,
                )
                if complete
                else None
            ),
            "recall_aggregation": "micro_over_registered_defects",
            "mean_false_positive_share": (
                round(
                    fmean(
                        item.score.false_positive_share
                        for item in complete
                        if item.score.false_positive_share is not None
                    ),
                    6,
                )
                if complete
                else None
            ),
            "mean_total_tokens": round(
                fmean(item.usage.total_tokens for item in group), 2
            ),
            "mean_governance_tokens": round(
                fmean(item.usage.governance_tokens for item in group), 2
            ),
            "mean_reasoning_output_tokens": round(
                fmean(item.usage.reasoning_output_tokens for item in group), 2
            ),
            "mean_model_calls": round(
                fmean(item.usage.model_calls for item in group), 2
            ),
            "mean_tool_calls": round(
                fmean(item.usage.tool_calls for item in group), 2
            ),
            "mean_agent_cumulative_time_seconds": round(
                fmean(item.usage.wall_time_seconds for item in group), 3
            ),
            "mean_wall_time_seconds": round(
                fmean(item.wall_time_seconds for item in group), 3
            ),
            "coverage_complete_rate": round(
                fmean(1.0 if item.coverage_complete else 0.0 for item in group),
                6,
            ),
            "red_line_miss_trials": sum(
                bool(item.score.missed_red_line_defects) for item in group
            ),
            "mean_final_novel_finding_ratio": (
                round(
                    fmean(
                        item.checkpoints[-1].novel_finding_ratio
                        for item in group
                        if item.checkpoints
                    ),
                    6,
                )
                if any(item.checkpoints for item in group)
                else None
            ),
        }
    return {
        "status": "descriptive_only",
        "claim_allowed": False,
        "engineering_result": "inconclusive",
        "evaluation_mode": (
            "scripted_dry_run"
            if all(item.scripted_dry_run for item in outcomes)
            else "real"
        ),
        "real_experiment": not any(
            item.scripted_dry_run for item in outcomes
        ),
        "by_agent_count": by_agent_count,
    }


def _normal(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _unique_by_id(
    values: Iterable[Any], attribute: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        identifier = str(getattr(value, attribute))
        if identifier in result:
            raise ValueError(f"duplicate {attribute}: {identifier}")
        result[identifier] = value
    return result


def _inside_workspace(workspace: Path, value: str) -> Path:
    candidate = Path(value)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (workspace / candidate).resolve()
    )
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {value}") from exc
    return resolved


def _run(command: Sequence[str], *, cwd: Path) -> None:
    try:
        subprocess.run(
            list(command),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ValueError(f"command failed: {' '.join(command)}: {detail}") from exc
