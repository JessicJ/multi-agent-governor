"""JSON CLI for policy planning and adaptive runtime execution."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import (
    CodexCliRuntime,
    CodexCliRuntimeConfig,
    ScriptedRuntime,
)
from .events import JsonlEventSink, load_events
from .evaluation import UsageObservation
from .execution import (
    AdaptiveController,
    AgentResult,
    ExecutionTask,
    JsonFindingsAggregator,
    ReviewEvidenceVerifier,
)
from .models import BaselineObservation, Budget, TaskSignals
from .policy import Governor


COMMANDS = {"plan", "run", "replay", "report"}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _read_json(path: str | None) -> tuple[dict[str, Any], Path]:
    if path:
        input_path = Path(path).resolve()
        raw = input_path.read_text()
        base_directory = input_path.parent
    else:
        raw = sys.stdin.read()
        base_directory = Path.cwd()
    payload = json.loads(raw, parse_constant=_reject_json_constant)
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload, base_directory


def _write_json(payload: Mapping[str, Any], *, compact: bool = False) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=None if compact else 2,
            allow_nan=False,
        )
    )


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    signals = TaskSignals(**payload["signals"])
    baseline = BaselineObservation(**payload["baseline"])
    budget = Budget(**payload.get("budget", {}))
    return Governor().decide(signals, baseline, budget).to_dict()


def _path_from_config(
    value: Any, *, base_directory: Path
) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else base_directory / path


def _scripted_runtime(payload: Mapping[str, Any]) -> ScriptedRuntime:
    results: list[AgentResult] = []
    for index, item in enumerate(payload.get("results", ()), 1):
        if not isinstance(item, Mapping):
            raise ValueError("each scripted runtime result must be an object")
        output = item.get("output", "")
        if isinstance(output, Mapping):
            output = json.dumps(
                output, ensure_ascii=False, allow_nan=False
            )
        success = _require_bool(
            item.get("success", True), "scripted result success"
        )
        results.append(
            AgentResult(
                run_id="scripted",
                agent_index=int(item.get("agent_index", index)),
                role="scripted",
                success=success,
                output=str(output),
                usage=UsageObservation.from_dict(item.get("usage", {})),
                error=(
                    ""
                    if success
                    else str(item.get("error", "scripted failure"))
                ),
            )
        )
    if not results:
        raise ValueError("scripted runtime requires at least one result")
    return ScriptedRuntime(results)


def _runtime_from_payload(
    payload: Mapping[str, Any], *, base_directory: Path
):
    kind = str(payload.get("kind", "codex-cli"))
    if kind == "scripted":
        return _scripted_runtime(payload)
    if kind != "codex-cli":
        raise ValueError(f"unsupported runtime kind: {kind}")
    return CodexCliRuntime(
        CodexCliRuntimeConfig(
            executable=str(payload.get("executable", "codex")),
            model=(
                str(payload["model"]) if payload.get("model") else None
            ),
            sandbox=str(payload.get("sandbox", "read-only")),
            timeout_seconds=float(payload.get("timeout_seconds", 900)),
            ephemeral=_require_bool(
                payload.get("ephemeral", True), "runtime ephemeral"
            ),
            output_schema=_path_from_config(
                payload.get("output_schema"),
                base_directory=base_directory,
            ),
            artifacts_directory=_path_from_config(
                payload.get("artifacts_directory"),
                base_directory=base_directory,
            ),
            extra_args=tuple(str(item) for item in payload.get("extra_args", ())),
        )
    )


def execute_payload(
    payload: dict[str, Any],
    *,
    base_directory: Path,
    events_path: Path | None = None,
    include_agent_output: bool = False,
) -> dict[str, Any]:
    task_payload = payload.get("task")
    if not isinstance(task_payload, Mapping):
        raise ValueError("run input requires a task object")
    runtime_payload = payload.get("runtime", {})
    if not isinstance(runtime_payload, Mapping):
        raise ValueError("runtime must be an object")
    verifier_payload = payload.get("verifier", {})
    if not isinstance(verifier_payload, Mapping):
        raise ValueError("verifier must be an object")
    verifier_kind = str(verifier_payload.get("kind", "review"))
    if verifier_kind != "review":
        raise ValueError(
            "the first executable release supports verifier kind 'review' only"
        )
    task = ExecutionTask.from_dict(
        task_payload, base_directory=base_directory
    )
    if not task.metadata.get("changed_files"):
        raise ValueError(
            "review verifier requires task.metadata.changed_files"
        )
    runtime = _runtime_from_payload(
        runtime_payload, base_directory=base_directory
    )
    event_sink = (
        JsonlEventSink(events_path.resolve())
        if events_path is not None
        else None
    )
    controller = AdaptiveController(
        runtime=runtime,
        aggregator=JsonFindingsAggregator(),
        verifier=ReviewEvidenceVerifier(),
        event_sink=event_sink,
        governance_tokens=int(payload.get("governance_tokens", 0)),
    )
    budget = Budget(**dict(payload.get("budget", {})))
    report = controller.execute(task, budget)
    return report.to_dict(include_agent_output=include_agent_output)


def replay_events(path: Path) -> dict[str, Any]:
    events = load_events(path)
    if not events:
        raise ValueError("event log is empty")
    run_ids = {event.run_id for event in events}
    task_ids = {event.task_id for event in events}
    if len(run_ids) != 1 or len(task_ids) != 1:
        raise ValueError("one event log must contain exactly one run and task")
    completed = [
        event for event in events if event.event_type == "run_completed"
    ]
    if len(completed) > 1:
        raise ValueError("event log contains multiple run_completed events")
    decisions = [
        event.data
        for event in events
        if event.event_type == "scale_decision"
    ]
    return {
        "run_id": next(iter(run_ids)),
        "task_id": next(iter(task_ids)),
        "event_count": len(events),
        "complete": len(completed) == 1,
        "final": completed[0].data if completed else None,
        "decisions": decisions,
    }


def summarize_reports(paths: Sequence[Path]) -> dict[str, Any]:
    reports: list[Mapping[str, Any]] = []
    for path in paths:
        payload = json.loads(
            path.read_text(), parse_constant=_reject_json_constant
        )
        if not isinstance(payload, Mapping):
            raise ValueError(f"report is not an object: {path}")
        reports.append(payload)
    if not reports:
        raise ValueError("at least one execution report is required")
    agents = [int(report["actual_total_agents"]) for report in reports]
    tokens = [
        int(dict(report.get("usage", {})).get("total_tokens", 0))
        for report in reports
    ]
    verification_scores = [
        float(dict(report.get("verification", {})).get("score", 0.0))
        for report in reports
    ]
    model_calls = [
        int(dict(report.get("usage", {})).get("model_calls", 0))
        for report in reports
    ]
    tool_calls = [
        int(dict(report.get("usage", {})).get("tool_calls", 0))
        for report in reports
    ]
    return {
        "runs": len(reports),
        "completed": sum(
            str(report.get("status")) == "completed" for report in reports
        ),
        "incomplete": sum(
            str(report.get("status")) != "completed" for report in reports
        ),
        "average_actual_agents": round(sum(agents) / len(agents), 6),
        "total_tokens": sum(tokens),
        "average_tokens": round(sum(tokens) / len(tokens), 6),
        "average_verification_score": round(
            sum(verification_scores) / len(verification_scores), 6
        ),
        "coverage_complete_runs": sum(
            bool(
                dict(report.get("verification", {})).get(
                    "coverage_complete", False
                )
            )
            for report in reports
        ),
        "total_model_calls": sum(model_calls),
        "total_tool_calls": sum(tool_calls),
        "stop_reasons": dict(
            sorted(
                Counter(
                    str(report.get("stop_reason", "unknown"))
                    for report in reports
                ).items()
            )
        ),
    }


def build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magov",
        description="Decide whether a completed single-agent baseline should scale out.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="JSON input file; reads stdin when omitted",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magov",
        description=(
            "Plan, execute, replay, and summarize adaptive Agent scaling."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="evaluate a measured baseline")
    plan.add_argument("input", nargs="?")
    plan.add_argument("--compact", action="store_true")

    run = subparsers.add_parser(
        "run", help="execute a baseline-first adaptive runtime loop"
    )
    run.add_argument("input")
    run.add_argument(
        "--events",
        help="append replayable run events to this JSONL file",
    )
    run.add_argument(
        "--include-agent-output",
        action="store_true",
        help="include raw Agent final messages in the report",
    )
    run.add_argument("--compact", action="store_true")

    replay = subparsers.add_parser(
        "replay", help="inspect a JSONL execution event log"
    )
    replay.add_argument("events")
    replay.add_argument("--compact", action="store_true")

    report = subparsers.add_parser(
        "report", help="summarize one or more execution report JSON files"
    )
    report.add_argument("reports", nargs="+")
    report.add_argument("--compact", action="store_true")
    return parser


def _main_commands(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        payload, _ = _read_json(args.input)
        _write_json(evaluate(payload), compact=args.compact)
    elif args.command == "run":
        payload, base_directory = _read_json(args.input)
        events_path = Path(args.events) if args.events else None
        _write_json(
            execute_payload(
                payload,
                base_directory=base_directory,
                events_path=events_path,
                include_agent_output=args.include_agent_output,
            ),
            compact=args.compact,
        )
    elif args.command == "replay":
        _write_json(
            replay_events(Path(args.events).resolve()),
            compact=args.compact,
        )
    else:
        _write_json(
            summarize_reports(
                [Path(item).resolve() for item in args.reports]
            ),
            compact=args.compact,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and (argv[0] in COMMANDS or argv[0] in {"-h", "--help"}):
            return _main_commands(argv)
        args = build_legacy_parser().parse_args(argv)
        payload, _ = _read_json(args.input)
        _write_json(evaluate(payload), compact=args.compact)
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(
            json.dumps({"error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
