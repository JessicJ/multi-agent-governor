#!/usr/bin/env python3
"""Run the repository's deterministic Governor JSON CLI."""

from __future__ import annotations

import sys
from pathlib import Path


def _load_cli():
    try:
        from magov.cli import main

        return main
    except ModuleNotFoundError:
        repository_src = Path(__file__).resolve().parents[5] / "src"
        if repository_src.is_dir():
            sys.path.insert(0, str(repository_src))
            from magov.cli import main

            return main
        raise SystemExit(
            "Multi-Agent Governor core was not found. Run this skill from its "
            "repository checkout or install the multi-agent-governor package."
        )


if __name__ == "__main__":
    raise SystemExit(_load_cli()())
