import threading
import time
import unittest

from pilot_service.jobs import JobQueue


class SlowTruthList(list[str]):
    def __bool__(self) -> bool:
        result = len(self) != 0
        time.sleep(0.02)
        return result


class InjectedConcurrencyTest(unittest.TestCase):
    def test_two_claimers_do_not_pop_empty_queue(self) -> None:
        queue = JobQueue(SlowTruthList(["only"]))
        start = threading.Barrier(3)
        results = []
        errors = []

        def claim() -> None:
            start.wait()
            try:
                results.append(queue.claim())
            except Exception as exc:  # capture worker-thread failure for assertion
                errors.append(exc)

        workers = [threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(timeout=1)

        self.assertFalse(errors)
        self.assertCountEqual(results, ["only", None])


if __name__ == "__main__":
    unittest.main()
