from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from magov import AgentRequest, Mode
from magov.adapters import CodexCliRuntime, CodexCliRuntimeConfig


class CodexCliRuntimeTests(unittest.TestCase):
    def test_adapter_captures_output_usage_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "fake-codex"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "assert args[args.index('--disable') + 1] == 'multi_agent'\n"
                "out = pathlib.Path(args[args.index('--output-last-message') + 1])\n"
                "out.write_text(json.dumps({'findings': []}))\n"
                "print(json.dumps({'type': 'item.completed', 'item': "
                "{'type': 'command_execution'}}))\n"
                "print(json.dumps({'type': 'turn.completed', 'usage': "
                "{'input_tokens': 90, 'cached_input_tokens': 20, "
                "'output_tokens': 10, 'reasoning_output_tokens': 4}}))\n"
            )
            executable.chmod(executable.stat().st_mode | 0o111)
            artifacts = root / "artifacts"
            workspace = root / "workspace"
            workspace.mkdir()
            runtime = CodexCliRuntime(
                CodexCliRuntimeConfig(
                    executable=str(executable),
                    artifacts_directory=artifacts,
                )
            )
            result = runtime.run_agent(
                AgentRequest(
                    run_id="run-1",
                    task_id="task-1",
                    agent_index=1,
                    role="baseline",
                    prompt="Review.",
                    working_directory=workspace,
                    mode=Mode.SINGLE,
                )
            )

        self.assertTrue(result.success)
        self.assertEqual(result.output, '{"findings": []}')
        self.assertEqual(result.usage.total_tokens, 100)
        self.assertEqual(result.usage.cached_input_tokens, 20)
        self.assertEqual(result.usage.tool_calls, 1)
        self.assertTrue(result.trace_path.endswith(".jsonl"))

    def test_adapter_rejects_unrestricted_sandbox(self) -> None:
        with self.assertRaisesRegex(ValueError, "intentionally unsupported"):
            CodexCliRuntimeConfig(sandbox="danger-full-access")

    def test_adapter_rejects_safety_bypass_flags(self) -> None:
        with self.assertRaisesRegex(ValueError, "only supports"):
            CodexCliRuntimeConfig(
                extra_args=(
                    "--dangerously-bypass-approvals-and-sandbox",
                )
            )

    def test_adapter_rejects_runtime_argument_overrides(self) -> None:
        for extra_args in (
            ("--sandbox", "danger-full-access"),
            ("--cd", "/tmp"),
            ("--output-last-message", "/tmp/result"),
            ("--config", "sandbox_policy='danger-full-access'"),
        ):
            with self.subTest(extra_args=extra_args):
                with self.assertRaisesRegex(ValueError, "only supports"):
                    CodexCliRuntimeConfig(extra_args=extra_args)

    def test_adapter_allows_ignoring_user_config(self) -> None:
        config = CodexCliRuntimeConfig(
            extra_args=("--ignore-user-config",)
        )
        self.assertEqual(config.extra_args, ("--ignore-user-config",))

    def test_adapter_keeps_traces_outside_agent_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "fake-codex"
            executable.write_text(f"#!{sys.executable}\n")
            executable.chmod(executable.stat().st_mode | 0o111)
            runtime = CodexCliRuntime(
                CodexCliRuntimeConfig(
                    executable=str(executable),
                    artifacts_directory=root / "visible-to-agent",
                )
            )
            with self.assertRaisesRegex(ValueError, "outside"):
                runtime.run_agent(
                    AgentRequest(
                        run_id="run-1",
                        task_id="task-1",
                        agent_index=1,
                        role="baseline",
                        prompt="Review.",
                        working_directory=root,
                        mode=Mode.SINGLE,
                    )
                )


if __name__ == "__main__":
    unittest.main()
