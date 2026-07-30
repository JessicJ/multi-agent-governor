"""Codex CLI adapter for isolated, one-Agent-at-a-time execution."""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import which

from ..evaluation import UsageObservation, parse_codex_exec_jsonl
from ..execution import AgentRequest, AgentResult


@dataclass(frozen=True)
class CodexCliRuntimeConfig:
    executable: str = "codex"
    model: str | None = None
    sandbox: str = "read-only"
    timeout_seconds: float = 900.0
    ephemeral: bool = True
    output_schema: Path | None = None
    artifacts_directory: Path | None = None
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sandbox not in {"read-only", "workspace-write"}:
            raise ValueError(
                "sandbox must be read-only or workspace-write; unrestricted "
                "execution is intentionally unsupported"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.output_schema is not None and not self.output_schema.is_file():
            raise ValueError(
                f"output schema does not exist: {self.output_schema}"
            )
        allowed_extra_args = {"--ignore-user-config"}
        unsupported = [
            argument
            for argument in self.extra_args
            if argument not in allowed_extra_args
        ]
        if unsupported:
            raise ValueError(
                "extra_args only supports --ignore-user-config; runtime-owned "
                "sandbox, workspace, approval, schema, and artifact arguments "
                "cannot be overridden"
            )


class CodexCliRuntime:
    """Launch one fresh ``codex exec`` process per admitted Agent.

    The adapter does not use a shell, never bypasses the Codex sandbox, and
    writes the JSONL trace outside the Agent workspace by default.
    """

    def __init__(self, config: CodexCliRuntimeConfig | None = None) -> None:
        self.config = config or CodexCliRuntimeConfig()
        if which(self.config.executable) is None:
            raise ValueError(
                f"Codex executable was not found: {self.config.executable}"
            )

    def _artifact_directory(self) -> Path:
        if self.config.artifacts_directory is not None:
            directory = self.config.artifacts_directory.resolve()
            directory.mkdir(parents=True, exist_ok=True)
            return directory
        return Path(tempfile.mkdtemp(prefix="magov-codex-"))

    def run_agent(self, request: AgentRequest) -> AgentResult:
        artifacts = self._artifact_directory()
        if artifacts.is_relative_to(request.working_directory):
            raise ValueError(
                "Codex artifacts_directory must be outside the Agent "
                "working directory to preserve run isolation"
            )
        stem = f"{request.run_id}-agent-{request.agent_index}"
        jsonl_path = artifacts / f"{stem}.jsonl"
        stderr_path = artifacts / f"{stem}.stderr.log"
        output_path = artifacts / f"{stem}.last-message.txt"

        command = [
            self.config.executable,
            "exec",
            "--json",
            "--disable",
            "multi_agent",
            "--color",
            "never",
            "--sandbox",
            self.config.sandbox,
            "--cd",
            str(request.working_directory),
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
        ]
        if self.config.ephemeral:
            command.append("--ephemeral")
        if self.config.model:
            command.extend(["--model", self.config.model])
        if self.config.output_schema is not None:
            command.extend(
                ["--output-schema", str(self.config.output_schema.resolve())]
            )
        command.extend(self.config.extra_args)
        command.append("-")

        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                input=request.prompt,
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
            elapsed = time.monotonic() - started
            jsonl_path.write_text(completed.stdout)
            stderr_path.write_text(completed.stderr)
            try:
                usage = parse_codex_exec_jsonl(
                    jsonl_path, wall_time_seconds=elapsed
                )
            except ValueError as exc:
                usage = UsageObservation(
                    agent_input_tokens=0,
                    agent_output_tokens=0,
                    wall_time_seconds=elapsed,
                )
                parse_error = str(exc)
            else:
                parse_error = ""
            output = output_path.read_text() if output_path.is_file() else ""
            success = completed.returncode == 0 and not parse_error
            error_parts = []
            if completed.returncode != 0:
                error_parts.append(
                    f"codex exec exited with status {completed.returncode}"
                )
            if parse_error:
                error_parts.append(parse_error)
            if not output.strip():
                success = False
                error_parts.append("codex exec produced no final message")
            return AgentResult(
                run_id=request.run_id,
                agent_index=request.agent_index,
                role=request.role,
                success=success,
                output=output,
                usage=usage,
                error="; ".join(error_parts),
                trace_path=str(jsonl_path),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            jsonl_path.write_text(stdout)
            stderr_path.write_text(stderr)
            return AgentResult(
                run_id=request.run_id,
                agent_index=request.agent_index,
                role=request.role,
                success=False,
                output="",
                usage=UsageObservation(
                    agent_input_tokens=0,
                    agent_output_tokens=0,
                    wall_time_seconds=elapsed,
                ),
                error=(
                    f"codex exec timed out after "
                    f"{self.config.timeout_seconds:g} seconds"
                ),
                trace_path=str(jsonl_path),
            )
