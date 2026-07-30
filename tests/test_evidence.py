import unittest

from magov import (
    DecisionAction,
    DecisionReceipt,
    EvidenceFact,
    EvidenceSource,
)


class DecisionReceiptTests(unittest.TestCase):
    def test_receipt_exposes_reasons_without_model_confidence(self) -> None:
        receipt = DecisionReceipt(
            decision_id="decision-001",
            task_id="python-pr-01",
            action=DecisionAction.STOP,
            current_agents=2,
            max_agents=4,
            recommended_total_agents=2,
            reasons=(
                EvidenceFact(
                    code="coverage_complete",
                    statement="All changed files met their review requirement.",
                    source=EvidenceSource.RUNTIME,
                ),
            ),
            governance_tokens=50,
            total_task_tokens=1000,
        )

        payload = receipt.to_dict()

        self.assertEqual(payload["action"], "stop")
        self.assertEqual(payload["governance_token_share"], 0.05)
        self.assertNotIn("confidence", payload)


if __name__ == "__main__":
    unittest.main()
