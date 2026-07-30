"""Small integration seam: baseline first, policy second."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from .models import BaselineObservation, Budget, Decision, TaskSignals
from .policy import Governor

TaskT = TypeVar("TaskT")

BaselineRunner = Callable[[TaskT], BaselineObservation]
SignalProvider = Callable[[TaskT, BaselineObservation], TaskSignals]


@dataclass
class GovernorSession(Generic[TaskT]):
    """Run the mandatory single-agent baseline and return a scale-out plan.

    This object intentionally does not launch worker agents.  The caller owns
    execution, credentials, tools, and aggregation; the governor only decides
    whether admitting more workers is justified.
    """

    baseline_runner: BaselineRunner[TaskT]
    signal_provider: SignalProvider[TaskT]
    governor: Governor = Governor()
    budget: Budget = Budget()

    def plan(self, task: TaskT) -> tuple[BaselineObservation, Decision]:
        baseline = self.baseline_runner(task)
        signals = self.signal_provider(task, baseline)
        decision = self.governor.decide(signals, baseline, self.budget)
        return baseline, decision
