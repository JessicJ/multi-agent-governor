#!/usr/bin/env python3
"""Run the repository's deterministic Governor JSON CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


SUPPORTED_PYTHONS = tuple(f"python3.{minor}" for minor in range(14, 9, -1))


def _candidate_pythons() -> tuple[str, ...]:
    """Return unique Python executables that may contain the installed core."""
    requested = os.environ.get("MAGOV_PYTHON")
    names = ((requested,) if requested else ()) + SUPPORTED_PYTHONS
    current = Path(sys.executable).resolve()
    candidates: list[str] = []
    seen: set[Path] = {current}

    for name in names:
        executable = shutil.which(name)
        if executable is None:
            continue
        resolved = Path(executable).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(str(resolved))

    return tuple(candidates)


def _has_installed_core(executable: str) -> bool:
    """Check a candidate without importing untrusted output into this process."""
    try:
        completed = subprocess.run(
            [executable, "-c", "from magov.cli import main"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _reexec_with_installed_core() -> None:
    """Re-execute with another supported Python when it owns the core package."""
    for executable in _candidate_pythons():
        if _has_installed_core(executable):
            os.execv(
                executable,
                [executable, str(Path(__file__).resolve()), *sys.argv[1:]],
            )


def _load_cli():
    try:
        from magov.cli import main

        return main
    except ModuleNotFoundError as error:
        if error.name != "magov":
            raise
        repository_src = Path(__file__).resolve().parents[5] / "src"
        if repository_src.is_dir():
            sys.path.insert(0, str(repository_src))
            from magov.cli import main

            return main
        _reexec_with_installed_core()
        raise SystemExit(
            "Multi-Agent Governor core was not found by "
            f"{sys.executable}. Install the multi-agent-governor package into "
            "a Python 3.10+ interpreter visible on PATH, or set MAGOV_PYTHON "
            "to that interpreter."
        )


if __name__ == "__main__":
    raise SystemExit(_load_cli()())
