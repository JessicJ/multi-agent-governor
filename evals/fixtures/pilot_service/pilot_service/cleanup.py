"""Safe cleanup planning."""

from pathlib import Path


def resolve_within(root: Path, candidate: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / candidate).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("cleanup target escapes configured root") from exc
    return target


def plan_cleanup(root: Path, candidates: list[str]) -> list[Path]:
    return [resolve_within(root, candidate) for candidate in candidates]
