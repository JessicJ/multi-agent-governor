import unittest

from magov import BaselineObservation, GovernorSession, Mode, TaskSignals


class GovernorSessionTests(unittest.TestCase):
    def test_baseline_runs_before_signal_provider(self) -> None:
        calls: list[str] = []

        def baseline_runner(task: str) -> BaselineObservation:
            calls.append(f"baseline:{task}")
            return BaselineObservation(confidence=0.92, verified=True)

        def signal_provider(
            task: str, baseline: BaselineObservation
        ) -> TaskSignals:
            calls.append(f"signals:{baseline.confidence}")
            return TaskSignals()

        baseline, decision = GovernorSession(
            baseline_runner=baseline_runner,
            signal_provider=signal_provider,
        ).plan("demo")

        self.assertEqual(calls, ["baseline:demo", "signals:0.92"])
        self.assertEqual(baseline.confidence, 0.92)
        self.assertEqual(decision.mode, Mode.SINGLE)


if __name__ == "__main__":
    unittest.main()
