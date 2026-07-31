#!/usr/bin/env python3
"""Validate release archives without installing project-specific tooling."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path


REQUIRED_LEGAL_FILES = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "LICENSES/attrs-MIT.txt",
    "LICENSES/click-BSD-3-Clause.txt",
    "LICENSES/more-itertools-MIT.txt",
    "LICENSES/pluggy-MIT.txt",
}

REQUIRED_SDIST_FILES = REQUIRED_LEGAL_FILES | {
    ".agents/plugins/marketplace.json",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "README.md",
    "README.en.md",
    "RELEASING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docs/product-goal.md",
    "docs/release-evidence-20260731.md",
    "evals/pilot_manifest.json",
    "evals/results/pilot-v2-validation-20260731/README.md",
    "examples/runtime_review_scripted_v2.json",
    "plugins/multi-agent-governor/.codex-plugin/plugin.json",
    "plugins/multi-agent-governor/skills/multi-agent-governor/SKILL.md",
    "requirements/release.txt",
    "tools/check_markdown_links.py",
}


def _normalized_legal_suffix(name: str) -> str | None:
    marker = ".dist-info/licenses/"
    if marker in name:
        return name.split(marker, 1)[1]

    parts = name.split("/", 1)
    if len(parts) == 2:
        return parts[1]

    return name


def _validate_names(path: Path, names: set[str]) -> None:
    present = {
        suffix
        for name in names
        if (suffix := _normalized_legal_suffix(name)) in REQUIRED_LEGAL_FILES
    }
    missing = sorted(REQUIRED_LEGAL_FILES - present)
    if missing:
        raise ValueError(f"{path}: missing legal files: {', '.join(missing)}")


def _validate_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        _validate_names(path, names)
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError(f"{path}: expected exactly one METADATA file")
        metadata = archive.read(metadata_names[0]).decode("utf-8")

    if "License-Expression: MIT" not in metadata:
        raise ValueError(f"{path}: missing MIT License-Expression metadata")

    if any("/evals/" in f"/{name}" for name in names):
        raise ValueError(f"{path}: evaluation assets must not be in the wheel")


def _validate_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = {member.name for member in archive.getmembers() if member.isfile()}
    _validate_names(path, names)
    root_relative_names = {
        name.split("/", 1)[1] if "/" in name else name for name in names
    }
    missing = sorted(REQUIRED_SDIST_FILES - root_relative_names)
    if missing:
        raise ValueError(
            f"{path}: missing source release files: {', '.join(missing)}"
        )


def validate_distribution(path: Path) -> None:
    if path.suffix == ".whl":
        _validate_wheel(path)
    elif path.name.endswith(".tar.gz"):
        _validate_sdist(path)
    else:
        raise ValueError(f"{path}: expected a .whl or .tar.gz distribution")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check release archives for metadata and legal files."
    )
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()

    kinds = {"wheel": 0, "sdist": 0}
    for archive in args.archives:
        validate_distribution(archive)
        if archive.suffix == ".whl":
            kinds["wheel"] += 1
        else:
            kinds["sdist"] += 1
        print(f"OK {archive}")

    if kinds != {"wheel": 1, "sdist": 1}:
        raise ValueError(
            "expected exactly one wheel and one source distribution, "
            f"got {kinds}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
