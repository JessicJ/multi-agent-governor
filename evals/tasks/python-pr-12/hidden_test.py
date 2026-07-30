import tempfile
import unittest
from pathlib import Path

from pilot_service.cleanup import resolve_within


class InjectedCleanupTest(unittest.TestCase):
    def test_sibling_with_shared_prefix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            sibling = Path(directory) / "data-archive"
            root.mkdir()
            sibling.mkdir()

            with self.assertRaises(ValueError):
                resolve_within(root, "../data-archive/record.json")


if __name__ == "__main__":
    unittest.main()
