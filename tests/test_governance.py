import json
import tempfile
import unittest
from pathlib import Path

from smart_llm_router.governance import make_route_receipt, validate_task_contract, write_route_receipt


class GovernanceTests(unittest.TestCase):
    def test_rejects_secret_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "secret"):
            validate_task_contract({"schema": "hermes_router_hub.task_contract.v1", "sensitivity": "secret"})

    def test_rejects_unknown_task_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "task_family"):
            validate_task_contract(
                {
                    "schema": "hermes_router_hub.task_contract.v1",
                    "task_family": "invented_family",
                }
            )

    def test_internal_summary_requires_sanitization_and_approval_for_cloud(self) -> None:
        local_only = validate_task_contract(
            {
                "schema": "hermes_router_hub.task_contract.v1",
                "task_family": "summarize",
                "sensitivity": "internal_summary",
            }
        )
        approved = validate_task_contract(
            {
                "schema": "hermes_router_hub.task_contract.v1",
                "task_family": "summarize",
                "sensitivity": "internal_summary",
                "sanitized_for_external": True,
                "external_processing_approved": True,
            }
        )
        self.assertFalse(local_only["allow_cloud"])
        self.assertTrue(approved["allow_cloud"])
        self.assertNotEqual(local_only["contract_fingerprint"], approved["contract_fingerprint"])

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

    def test_receipt_links_contract_ledger_fallback_and_materialized_output(self) -> None:
        contract = validate_task_contract(
            {
                "schema": "hermes_router_hub.task_contract.v1",
                "task_id": "test-materialized",
                "task_family": "execute",
                "sensitivity": "public",
                "materialization_gate": {
                    "required": True,
                    "parse_json": True,
                    "non_empty": True,
                    "required_fields": ["schema", "result"],
                },
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            output.write_text(json.dumps({"schema": "result.v1", "result": "OK"}), encoding="utf-8")
            receipt = make_route_receipt(
                contract=contract,
                mode="execute",
                selected_provider="provider-a",
                selected_model="model-a",
                cost_class="free",
                paid_fallback_used=False,
                decision_reasons=["selected healthy free route"],
                route_alias="router-auto",
                fallback_chain=[{"provider": "provider-b", "model": "model-b"}],
                ledger_id="ledger-1",
                output_path=str(output),
                production_changed=True,
            )
        self.assertEqual(receipt["contract_fingerprint"], contract["contract_fingerprint"])
        self.assertEqual(receipt["route_alias"], "router-auto")
        self.assertEqual(receipt["ledger_id"], "ledger-1")
        self.assertEqual(receipt["fallback_chain"][0]["provider"], "provider-b")
        self.assertTrue(receipt["output"]["materialized"])
        self.assertEqual(len(receipt["output"]["sha256"]), 64)
        self.assertTrue(receipt["production_changed"])

    def test_execute_mode_does_not_claim_production_change_without_evidence(self) -> None:
        contract = validate_task_contract(
            {"schema": "hermes_router_hub.task_contract.v1", "task_family": "execute"}
        )
        receipt = make_route_receipt(
            contract=contract,
            mode="execute",
            selected_provider=None,
            selected_model=None,
            cost_class="unselected",
            paid_fallback_used=False,
            decision_reasons=["dry execution check"],
        )
        self.assertFalse(receipt["production_changed"])

    def test_execute_mode_fails_closed_when_required_output_is_missing(self) -> None:
        contract = validate_task_contract(
            {
                "schema": "hermes_router_hub.task_contract.v1",
                "task_family": "execute",
                "materialization_gate": {"required": True},
            }
        )
        with self.assertRaisesRegex(ValueError, "output_path"):
            make_route_receipt(
                contract=contract,
                mode="execute",
                selected_provider="provider-a",
                selected_model="model-a",
                cost_class="free",
                paid_fallback_used=False,
                decision_reasons=["execution completed"],
            )


if __name__ == "__main__":
    unittest.main()
