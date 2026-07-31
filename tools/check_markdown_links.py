#!/usr/bin/env python3
"""Check repository-local Markdown links without network access."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote


LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
IGNORED_PREFIXES = {Path("evals/runs")}
URI_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def _is_ignored(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in relative.parts):
        return True
    return any(relative.is_relative_to(prefix) for prefix in IGNORED_PREFIXES)


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and not _is_ignored(root, path)
    )


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def broken_local_links(root: Path) -> list[str]:
    root = root.resolve()
    failures: list[str] = []
    for markdown_path in markdown_files(root):
        text = markdown_path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in LINK_PATTERN.finditer(line):
                target = _link_target(match.group(1))
                if not target or target.startswith("#") or URI_SCHEME_PATTERN.match(target):
                    continue
                path_text = unquote(target.split("#", 1)[0])
                if not path_text:
                    continue
                resolved = (markdown_path.parent / path_text).resolve()
                relative = markdown_path.relative_to(root)
                if not resolved.is_relative_to(root):
                    failures.append(
                        f"{relative}:{line_number}: target escapes root {target}"
                    )
                elif not resolved.exists():
                    failures.append(f"{relative}:{line_number}: missing {target}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check local file targets in repository Markdown links."
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()

    root = args.root.resolve()
    failures = broken_local_links(root)
    if failures:
        for failure in failures:
            print(failure)
        return 1

    print(f"OK {len(markdown_files(root))} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
