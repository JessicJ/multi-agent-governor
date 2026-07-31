from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
WRAPPER_PATH = (
    ROOT
    / "plugins"
    / "multi-agent-governor"
    / "skills"
    / "multi-agent-governor"
    / "scripts"
    / "run_governor.py"
)
SPEC = importlib.util.spec_from_file_location("run_governor", WRAPPER_PATH)
assert SPEC is not None and SPEC.loader is not None
WRAPPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WRAPPER)


class PluginWrapperTests(unittest.TestCase):
    def test_candidate_pythons_prefers_explicit_then_supported_versions(self) -> None:
        resolved = {
            "/custom/python": "/custom/python",
            "python3.14": "/opt/python3.14",
            "python3.13": "/opt/python3.13",
        }

        with (
            patch.dict(os.environ, {"MAGOV_PYTHON": "/custom/python"}),
            patch.object(WRAPPER.sys, "executable", "/current/python"),
            patch.object(
                WRAPPER.shutil,
                "which",
                side_effect=lambda name: resolved.get(name),
            ),
        ):
            candidates = WRAPPER._candidate_pythons()

        self.assertEqual(
            candidates,
            ("/custom/python", "/opt/python3.14", "/opt/python3.13"),
        )

    def test_reexec_uses_first_interpreter_with_installed_core(self) -> None:
        execv = MagicMock(side_effect=RuntimeError("re-executed"))

        with (
            patch.object(
                WRAPPER,
                "_candidate_pythons",
                return_value=("/python-a", "/python-b"),
            ),
            patch.object(
                WRAPPER,
                "_has_installed_core",
                side_effect=(False, True),
            ),
            patch.object(WRAPPER.os, "execv", execv),
            patch.object(WRAPPER.sys, "argv", ["run_governor.py", "plan", "input.json"]),
        ):
            with self.assertRaisesRegex(RuntimeError, "re-executed"):
                WRAPPER._reexec_with_installed_core()

        execv.assert_called_once_with(
            "/python-b",
            [
                "/python-b",
                str(WRAPPER_PATH),
                "plan",
                "input.json",
            ],
        )

    def test_core_probe_rejects_failure_and_timeout(self) -> None:
        failed = MagicMock(returncode=1)
        with patch.object(WRAPPER.subprocess, "run", return_value=failed):
            self.assertFalse(WRAPPER._has_installed_core("/python"))

        with patch.object(
            WRAPPER.subprocess,
            "run",
            side_effect=WRAPPER.subprocess.TimeoutExpired("/python", 5),
        ):
            self.assertFalse(WRAPPER._has_installed_core("/python"))


if __name__ == "__main__":
    unittest.main()
