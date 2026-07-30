"""CLI for planning and scoring local Governor evaluation trials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .adaptive_evaluation import (
    AdaptiveTrialOutcome,
    AdaptiveTrialSpec,
    adaptive_outcome_from_report,
    build_adaptive_run_payload,
    build_adaptive_trial_matrix,
    build_fixed_run_payload,
    compare_adaptive_to_fixed,
    fixed_outcome_from_report,
    render_review_prompt,
    summarize_adaptive_outcomes,
)
from .cli import runtime_from_payload
from .evaluation import (
    BlindAdjudication,
    GoldDefect,
    ReviewFinding,
    ReviewTask,
    TrialOutcome,
    TrialSpec,
    build_trial_matrix,
    materialize_task,
    parse_codex_exec_jsonl,
    score_findings,
    summarize_outcomes,
    validate_task_assets,
)
from .execution import (
    ExecutionTask,
    JsonFindingsAggregator,
    ReviewEvidenceVerifier,
)
from .fixed_execution import FixedCountController


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
    outcomes = _load_jsonl_outcomes(Path(args.outcomes), TrialOutcome.from_dict)
    return summarize_outcomes(outcomes)


def _load_jsonl_outcomes(path: Path, loader):
    outcomes = []
    for line_number, line in enumerate(
        path.read_text().splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            outcomes.append(
                loader(
                    json.loads(
                        line, parse_constant=_reject_json_constant
                    )
                )
            )
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                f"invalid outcome on JSONL line {line_number}: {exc}"
            ) from exc
    if not outcomes:
        raise ValueError("outcome JSONL is empty")
    return outcomes


def _adaptive_plan(args: argparse.Namespace) -> dict[str, Any]:
    trials = build_adaptive_trial_matrix(
        _load_tasks(args.manifest),
        model_id=args.model_id,
        prompt_version=args.prompt_version,
        policy_version=args.policy_version,
        max_agents=args.max_agents,
        repetitions=args.repetitions,
    )
    return {
        "status": "planned",
        "arm": "adaptive",
        "trial_count": len(trials),
        "trials": [trial.to_dict() for trial in trials],
    }


def _adaptive_config(args: argparse.Namespace) -> dict[str, Any]:
    tasks = _load_tasks(args.manifest)
    matching_tasks = [task for task in tasks if task.task_id == args.task_id]
    if len(matching_tasks) != 1:
        raise ValueError(
            f"task_id must match exactly one task: {args.task_id}"
        )
    trial = build_adaptive_trial_matrix(
        matching_tasks,
        model_id=args.model_id,
        prompt_version=args.prompt_version,
        policy_version=args.policy_version,
        max_agents=args.max_agents,
        repetitions=args.repetition,
    )[-1]
    prompt = render_review_prompt(
        Path(args.prompt_template).read_text(),
        task_directory=str(Path(args.working_directory).resolve()),
        trial_id=trial.trial_id,
    )
    return {
        "trial": trial.to_dict(),
        "run": build_adaptive_run_payload(
            matching_tasks[0],
            trial,
            working_directory=str(
                Path(args.working_directory).resolve()
            ),
            prompt=prompt,
            output_schema=str(Path(args.output_schema).resolve()),
            artifacts_directory=str(
                Path(args.artifacts_directory).resolve()
            ),
        ),
    }


def _fixed_config(args: argparse.Namespace) -> dict[str, Any]:
    tasks = _load_tasks(args.manifest)
    matching_tasks = [task for task in tasks if task.task_id == args.task_id]
    if len(matching_tasks) != 1:
        raise ValueError(
            f"task_id must match exactly one task: {args.task_id}"
        )
    trial = build_trial_matrix(
        matching_tasks,
        model_id=args.model_id,
        prompt_version=args.prompt_version,
        agent_counts=(args.exact_total_agents,),
        repetitions=args.repetition,
    )[-1]
    prompt = render_review_prompt(
        Path(args.prompt_template).read_text(),
        task_directory=str(Path(args.working_directory).resolve()),
        trial_id=trial.trial_id,
    )
    return {
        "trial": trial.to_dict(),
        "run": build_fixed_run_payload(
            matching_tasks[0],
            trial,
            working_directory=str(
                Path(args.working_directory).resolve()
            ),
            prompt=prompt,
            output_schema=str(Path(args.output_schema).resolve()),
            artifacts_directory=str(
                Path(args.artifacts_directory).resolve()
            ),
        ),
    }


def _select_adaptive_trial(
    payload: Any, trial_id: str | None
) -> AdaptiveTrialSpec:
    if isinstance(payload, Mapping) and isinstance(
        payload.get("trial"), Mapping
    ):
        candidates = [payload["trial"]]
    elif isinstance(payload, Mapping) and "trial_id" in payload:
        candidates = [payload]
    else:
        candidates = _items(payload, "trials")
    if trial_id is not None:
        candidates = [
            item for item in candidates if item.get("trial_id") == trial_id
        ]
    if len(candidates) != 1:
        raise ValueError(
            "adaptive spec must resolve to exactly one trial; use --trial-id"
        )
    return AdaptiveTrialSpec.from_dict(candidates[0])


def _select_fixed_trial(
    payload: Any, trial_id: str | None
) -> TrialSpec:
    if isinstance(payload, Mapping) and isinstance(
        payload.get("trial"), Mapping
    ):
        candidates = [payload["trial"]]
    elif isinstance(payload, Mapping) and "trial_id" in payload:
        candidates = [payload]
    else:
        candidates = _items(payload, "trials")
    if trial_id is not None:
        candidates = [
            item for item in candidates if item.get("trial_id") == trial_id
        ]
    if len(candidates) != 1:
        raise ValueError(
            "fixed spec must resolve to exactly one trial; use --trial-id"
        )
    return TrialSpec.from_dict(candidates[0])


def _run_payload(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping) and isinstance(
        payload.get("run"), Mapping
    ):
        return payload["run"]
    if isinstance(payload, Mapping):
        return payload
    raise ValueError("run configuration must be a JSON object")


def _fixed_run(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.config).resolve()
    envelope = _load_json(str(path))
    trial = _select_fixed_trial(envelope, args.trial_id)
    payload = _run_payload(envelope)
    task_payload = payload.get("task")
    runtime_payload = payload.get("runtime")
    if not isinstance(task_payload, Mapping):
        raise ValueError("fixed run requires a task object")
    if not isinstance(runtime_payload, Mapping):
        raise ValueError("fixed run requires a runtime object")
    if (
        runtime_payload.get("kind", "codex-cli") == "codex-cli"
        and str(runtime_payload.get("model", "")) != trial.model_id
    ):
        raise ValueError("runtime model must match the fixed trial model_id")
    task = ExecutionTask.from_dict(
        task_payload, base_directory=path.parent
    )
    if task.task_id != trial.task_id:
        raise ValueError("run task_id must match the fixed trial")
    runtime = runtime_from_payload(
        runtime_payload, base_directory=path.parent
    )
    budget_payload = payload.get("budget", {})
    if not isinstance(budget_payload, Mapping):
        raise ValueError("fixed run budget must be an object")
    report = FixedCountController(
        runtime=runtime,
        aggregator=JsonFindingsAggregator(),
        verifier=ReviewEvidenceVerifier(),
    ).execute(
        task,
        exact_total_agents=trial.exact_total_agents,
        max_total_tokens=(
            int(budget_payload["max_total_tokens"])
            if budget_payload.get("max_total_tokens") is not None
            else None
        ),
        max_wall_time_seconds=(
            float(budget_payload["max_wall_time_seconds"])
            if budget_payload.get("max_wall_time_seconds") is not None
            else None
        ),
        max_tool_calls=(
            int(budget_payload["max_tool_calls"])
            if budget_payload.get("max_tool_calls") is not None
            else None
        ),
    )
    return report.to_dict(
        include_agent_output=args.include_agent_output
    )


def _adaptive_outcome(args: argparse.Namespace) -> dict[str, Any]:
    trial = _select_adaptive_trial(
        _load_json(args.spec), args.trial_id
    )
    truth = [
        GoldDefect.from_dict(item)
        for item in _items(_load_json(args.truth), "defects")
    ]
    adjudications = []
    if args.adjudications:
        adjudications = [
            BlindAdjudication.from_dict(item)
            for item in _items(
                _load_json(args.adjudications), "adjudications"
            )
        ]
    return adaptive_outcome_from_report(
        trial,
        _load_json(args.report),
        truth,
        adjudications,
    ).to_dict()


def _fixed_outcome(args: argparse.Namespace) -> dict[str, Any]:
    trial = _select_fixed_trial(_load_json(args.spec), args.trial_id)
    truth = [
        GoldDefect.from_dict(item)
        for item in _items(_load_json(args.truth), "defects")
    ]
    adjudications = []
    if args.adjudications:
        adjudications = [
            BlindAdjudication.from_dict(item)
            for item in _items(
                _load_json(args.adjudications), "adjudications"
            )
        ]
    return fixed_outcome_from_report(
        trial,
        _load_json(args.report),
        truth,
        adjudications,
    ).to_dict()


def _adaptive_summarize(args: argparse.Namespace) -> dict[str, Any]:
    outcomes = _load_jsonl_outcomes(
        Path(args.outcomes), AdaptiveTrialOutcome.from_dict
    )
    return summarize_adaptive_outcomes(outcomes)


def _compare(args: argparse.Namespace) -> dict[str, Any]:
    fixed = _load_jsonl_outcomes(
        Path(args.fixed_outcomes), TrialOutcome.from_dict
    )
    adaptive = _load_jsonl_outcomes(
        Path(args.adaptive_outcomes), AdaptiveTrialOutcome.from_dict
    )
    return compare_adaptive_to_fixed(
        fixed, adaptive, reference_agents=args.reference_agents
    )


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

    adaptive_plan = subparsers.add_parser(
        "adaptive-plan",
        help="create one Governor-controlled arm per task and repetition",
    )
    adaptive_plan.add_argument("manifest")
    adaptive_plan.add_argument("--model-id", required=True)
    adaptive_plan.add_argument("--prompt-version", required=True)
    adaptive_plan.add_argument("--policy-version", required=True)
    adaptive_plan.add_argument("--max-agents", type=int, default=4)
    adaptive_plan.add_argument("--repetitions", type=int, default=2)
    adaptive_plan.set_defaults(handler=_adaptive_plan)

    adaptive_config = subparsers.add_parser(
        "adaptive-config",
        help="build a truth-free magov run configuration for one trial",
    )
    adaptive_config.add_argument("manifest")
    adaptive_config.add_argument("task_id")
    adaptive_config.add_argument("working_directory")
    adaptive_config.add_argument("--model-id", required=True)
    adaptive_config.add_argument("--prompt-version", required=True)
    adaptive_config.add_argument("--policy-version", required=True)
    adaptive_config.add_argument("--prompt-template", required=True)
    adaptive_config.add_argument("--output-schema", required=True)
    adaptive_config.add_argument("--artifacts-directory", required=True)
    adaptive_config.add_argument("--max-agents", type=int, default=4)
    adaptive_config.add_argument("--repetition", type=int, default=1)
    adaptive_config.set_defaults(handler=_adaptive_config)

    fixed_config = subparsers.add_parser(
        "fixed-config",
        help="build a truth-free exact-count reference configuration",
    )
    fixed_config.add_argument("manifest")
    fixed_config.add_argument("task_id")
    fixed_config.add_argument("working_directory")
    fixed_config.add_argument("--exact-total-agents", type=int, required=True)
    fixed_config.add_argument("--model-id", required=True)
    fixed_config.add_argument("--prompt-version", required=True)
    fixed_config.add_argument("--prompt-template", required=True)
    fixed_config.add_argument("--output-schema", required=True)
    fixed_config.add_argument("--artifacts-directory", required=True)
    fixed_config.add_argument("--repetition", type=int, default=1)
    fixed_config.set_defaults(handler=_fixed_config)

    fixed_run = subparsers.add_parser(
        "fixed-run",
        help="execute exactly the Agent count declared by one fixed config",
    )
    fixed_run.add_argument("config")
    fixed_run.add_argument("--trial-id")
    fixed_run.add_argument("--include-agent-output", action="store_true")
    fixed_run.set_defaults(handler=_fixed_run)

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

    adaptive_outcome = subparsers.add_parser(
        "adaptive-outcome",
        help="score one completed adaptive report in the isolated truth stage",
    )
    adaptive_outcome.add_argument("spec")
    adaptive_outcome.add_argument("report")
    adaptive_outcome.add_argument("truth")
    adaptive_outcome.add_argument("--trial-id")
    adaptive_outcome.add_argument("--adjudications")
    adaptive_outcome.set_defaults(handler=_adaptive_outcome)

    fixed_outcome = subparsers.add_parser(
        "fixed-outcome",
        help="score one completed exact-count report in the isolated stage",
    )
    fixed_outcome.add_argument("spec")
    fixed_outcome.add_argument("report")
    fixed_outcome.add_argument("truth")
    fixed_outcome.add_argument("--trial-id")
    fixed_outcome.add_argument("--adjudications")
    fixed_outcome.set_defaults(handler=_fixed_outcome)

    adaptive_summarize = subparsers.add_parser(
        "adaptive-summarize",
        help="summarize completed adaptive outcome JSONL",
    )
    adaptive_summarize.add_argument("outcomes")
    adaptive_summarize.set_defaults(handler=_adaptive_summarize)

    compare = subparsers.add_parser(
        "compare",
        help="compare adaptive outcomes to a paired fixed-count arm",
    )
    compare.add_argument("fixed_outcomes")
    compare.add_argument("adaptive_outcomes")
    compare.add_argument("--reference-agents", type=int, default=4)
    compare.set_defaults(handler=_compare)
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
