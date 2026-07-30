"""JSON CLI for trying the policy without installing an agent framework."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .models import BaselineObservation, Budget, TaskSignals
from .policy import Governor


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    signals = TaskSignals(**payload["signals"])
    baseline = BaselineObservation(**payload["baseline"])
    budget = Budget(**payload.get("budget", {}))
    return Governor().decide(signals, baseline, budget).to_dict()


def build_parser() -> argparse.ArgumentParser:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = Path(args.input).read_text() if args.input else sys.stdin.read()
        result = evaluate(
            json.loads(raw, parse_constant=_reject_json_constant)
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    indent = None if args.compact else 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=indent,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
