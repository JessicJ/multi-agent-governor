"""Append-only events for replaying adaptive Governor runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RunEvent:
    sequence: int
    run_id: str
    task_id: str
    event_type: str
    data: dict[str, Any]
    occurred_at: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("event sequence must be at least 1")
        for name in ("run_id", "task_id", "event_type", "occurred_at"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        run_id: str,
        task_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> "RunEvent":
        return cls(
            sequence=sequence,
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            data=data or {},
            occurred_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunEvent":
        return cls(
            sequence=int(payload["sequence"]),
            run_id=str(payload["run_id"]),
            task_id=str(payload["task_id"]),
            event_type=str(payload["event_type"]),
            data=dict(payload.get("data", {})),
            occurred_at=str(payload["occurred_at"]),
        )


class EventSink(Protocol):
    def record(self, event: RunEvent) -> None:
        """Persist one event before returning."""


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def record(self, event: RunEvent) -> None:
        self.events.append(event)


class JsonlEventSink:
    """Durable local event log.

    The parent directory is created on demand.  Each call flushes before
    returning so a failed Agent process still leaves a replayable prefix.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        if self.path.exists() and self.path.stat().st_size > 0:
            raise ValueError(
                f"event log already exists and is not empty: {self.path}"
            )

    def record(self, event: RunEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    event.to_dict(),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )
            stream.flush()


def load_events(path: Path) -> tuple[RunEvent, ...]:
    events: list[RunEvent] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid run event on line {line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"run event on line {line_number} is not an object")
        events.append(RunEvent.from_dict(payload))
    sequences = [event.sequence for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise ValueError("run event sequences must be contiguous from 1")
    return tuple(events)
