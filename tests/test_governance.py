import tempfile
import unittest
from pathlib import Path

from smart_llm_router.governance import make_route_receipt, validate_task_contract, write_route_receipt


class GovernanceTests(unittest.TestCase):
    def test_rejects_secret_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "secret"):
            validate_task_contract({"schema": "hermes_router_hub.task_contract.v1", "sensitivity": "secret"})

    def test_validates_and_writes_receipt(self) -> None:
        contract = validate_task_contract(
            {
                "schema": "hermes_router_hub.task_contract.v1",
                "task_id": "test-1",
                "task_family": "text_light",
                "sensitivity": "public",
                "free_only": True,
                "paid_fallback_allowed": False,
            }
        )
        receipt = make_route_receipt(
            contract=contract,
            mode="dry_run",
            selected_provider=None,
            selected_model=None,
            cost_class="unselected",
            paid_fallback_used=False,
            decision_reasons=["test"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_route_receipt(receipt, tmp)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
