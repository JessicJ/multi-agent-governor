"""CLI for planning and scoring local Governor evaluation trials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .evaluation import (
    BlindAdjudication,
    GoldDefect,
    ReviewFinding,
    ReviewTask,
    TrialOutcome,
    build_trial_matrix,
    materialize_task,
    parse_codex_exec_jsonl,
    score_findings,
    summarize_outcomes,
    validate_task_assets,
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _load_json(path: str) -> Any:
    return json.loads(
        Path(path).read_text(),
        parse_constant=_reject_json_constant,
    )


def _items(payload: Any, key: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    raise ValueError(f"expected a JSON list or an object containing '{key}'")


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    payload = _load_json(args.manifest)
    tasks = [
        ReviewTask.from_dict(item) for item in _items(payload, "tasks")
    ]
    trials = build_trial_matrix(
        tasks,
        model_id=args.model_id,
        prompt_version=args.prompt_version,
        agent_counts=tuple(args.agent_counts),
        repetitions=args.repetitions,
    )
    return {
        "status": "planned",
        "trial_count": len(trials),
        "trials": [trial.to_dict() for trial in trials],
    }


def _load_tasks(path: str) -> list[ReviewTask]:
    payload = _load_json(path)
    return [
        ReviewTask.from_dict(item) for item in _items(payload, "tasks")
    ]


def _validate(args: argparse.Namespace) -> dict[str, Any]:
    return validate_task_assets(
        _load_tasks(args.manifest),
        Path(args.workspace),
    )


def _materialize(args: argparse.Namespace) -> dict[str, Any]:
    tasks = _load_tasks(args.manifest)
    matching = [task for task in tasks if task.task_id == args.task_id]
    if len(matching) != 1:
        raise ValueError(f"task_id must match exactly one task: {args.task_id}")
    return materialize_task(
        matching[0],
        workspace=Path(args.workspace),
        destination=Path(args.destination),
    )


def _codex_usage(args: argparse.Namespace) -> dict[str, Any]:
    return parse_codex_exec_jsonl(
        Path(args.events), wall_time_seconds=args.wall_time_seconds
    ).to_dict()


def _score(args: argparse.Namespace) -> dict[str, Any]:
    truth = [
        GoldDefect.from_dict(item)
        for item in _items(_load_json(args.truth), "defects")
    ]
    findings = [
        ReviewFinding.from_dict(item)
        for item in _items(_load_json(args.findings), "findings")
    ]
    adjudications = []
    if args.adjudications:
        adjudications = [
            BlindAdjudication.from_dict(item)
            for item in _items(
                _load_json(args.adjudications), "adjudications"
            )
        ]
    return score_findings(truth, findings, adjudications).to_dict()


def _summarize(args: argparse.Namespace) -> dict[str, Any]:
    outcomes: list[TrialOutcome] = []
    for line_number, line in enumerate(
        Path(args.outcomes).read_text().splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            outcomes.append(
                TrialOutcome.from_dict(
                    json.loads(
                        line,
                        parse_constant=_reject_json_constant,
                    )
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid outcome on JSONL line {line_number}: {exc}"
            ) from exc
    return summarize_outcomes(outcomes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magov-eval",
        description=(
            "Create fixed-agent evaluation plans and score local review evidence."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser(
        "plan", help="create an exact 1-4 agent trial matrix"
    )
    plan.add_argument("manifest", help="evaluation task manifest JSON")
    plan.add_argument("--model-id", required=True)
    plan.add_argument("--prompt-version", required=True)
    plan.add_argument(
        "--agent-counts",
        nargs="+",
        type=int,
        default=[1, 2, 3, 4],
    )
    plan.add_argument("--repetitions", type=int, default=2)
    plan.set_defaults(handler=_plan)

    validate = subparsers.add_parser(
        "validate", help="validate task assets, hashes, and truth cards"
    )
    validate.add_argument("manifest")
    validate.add_argument("--workspace", default=".")
    validate.set_defaults(handler=_validate)

    materialize = subparsers.add_parser(
        "materialize",
        help="create one isolated review worktree without its hidden truth",
    )
    materialize.add_argument("manifest")
    materialize.add_argument("task_id")
    materialize.add_argument("destination")
    materialize.add_argument("--workspace", default=".")
    materialize.set_defaults(handler=_materialize)

    codex_usage = subparsers.add_parser(
        "codex-usage",
        help="read usage and tool calls from one codex exec --json log",
    )
    codex_usage.add_argument("events", help="path to codex exec JSONL output")
    codex_usage.add_argument("--wall-time-seconds", type=float, default=0.0)
    codex_usage.set_defaults(handler=_codex_usage)

    score = subparsers.add_parser(
        "score", help="score structured findings against hidden truth cards"
    )
    score.add_argument("truth")
    score.add_argument("findings")
    score.add_argument("--adjudications")
    score.set_defaults(handler=_score)

    summarize = subparsers.add_parser(
        "summarize", help="summarize completed trial outcome JSONL"
    )
    summarize.add_argument("outcomes")
    summarize.set_defaults(handler=_summarize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
