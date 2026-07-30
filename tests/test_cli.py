import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from magov.cli import main


class CliValidationTests(unittest.TestCase):
    def test_non_finite_json_numbers_are_rejected(self) -> None:
        payload = """
        {
          "signals": {},
          "baseline": {"confidence": 0.5},
          "budget": {"max_cost_multiplier": NaN}
        }
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(payload)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = main([str(path)])

        self.assertEqual(status, 2)
        self.assertIn("non-finite JSON number", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
