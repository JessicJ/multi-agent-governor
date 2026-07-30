"""Thread-safe in-memory job queue."""

from threading import Lock


class JobQueue:
    def __init__(self, items: list[str]) -> None:
        self._items = items
        self._lock = Lock()

    def claim(self) -> str | None:
        with self._lock:
            if not self._items:
                return None
            return self._items.pop(0)
