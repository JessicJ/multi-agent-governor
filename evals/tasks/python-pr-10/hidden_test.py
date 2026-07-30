import unittest

from pilot_service.storage import apply_batch


class InjectedStorageTest(unittest.TestCase):
    def test_default_batch_preserves_existing_records(self) -> None:
        self.assertEqual(
            apply_batch({"existing": "keep"}, {"new": "value"}),
            {"existing": "keep", "new": "value"},
        )


if __name__ == "__main__":
    unittest.main()
