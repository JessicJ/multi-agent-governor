"""In-memory record transformation helpers."""


def normalize_key(key: str) -> str:
    return key.strip().casefold()


def merge_records(
    existing: dict[str, str], updates: dict[str, str]
) -> dict[str, str]:
    result = dict(existing)
    result.update(updates)
    return result


def apply_batch(
    existing: dict[str, str],
    updates: dict[str, str],
    *,
    preserve_existing: bool = True,
) -> dict[str, str]:
    result = dict(existing) if preserve_existing else {}
    result.update(updates)
    return result
