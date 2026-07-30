import tempfile
import unittest
from pathlib import Path

from pilot_service.auth import authorize
from pilot_service.cleanup import resolve_within
from pilot_service.jobs import JobQueue
from pilot_service.storage import merge_records


class PilotServiceSmokeTests(unittest.TestCase):
    def test_authorization(self) -> None:
        authorize("admin", "delete")
        with self.assertRaises(PermissionError):
            authorize("viewer", "delete")

    def test_merge_preserves_existing_records(self) -> None:
        self.assertEqual(
            merge_records({"a": "1"}, {"b": "2"}),
            {"a": "1", "b": "2"},
        )

    def test_queue_claims_once(self) -> None:
        queue = JobQueue(["one"])
        self.assertEqual(queue.claim(), "one")
        self.assertIsNone(queue.claim())

    def test_cleanup_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            root.mkdir()
            with self.assertRaises(ValueError):
                resolve_within(root, "../outside")


if __name__ == "__main__":
    unittest.main()
