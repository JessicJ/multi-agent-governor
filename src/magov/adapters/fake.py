"""Deterministic runtime used for controller tests and offline demonstrations."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from typing import Iterable

from ..execution import AgentRequest, AgentResult


class ScriptedRuntime:
    def __init__(self, results: Iterable[AgentResult]) -> None:
        self._results = deque(results)
        self.requests: list[AgentRequest] = []

    def run_agent(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if not self._results:
            raise RuntimeError("ScriptedRuntime has no result for this request")
        result = self._results.popleft()
        if result.agent_index != request.agent_index:
            raise ValueError(
                "scripted result agent_index does not match the request"
            )
        return replace(result, run_id=request.run_id, role=request.role)
