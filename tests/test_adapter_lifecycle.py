import json
import tempfile
import unittest
from pathlib import Path

from smart_llm_router.lifecycle import evaluate_adapter_transition, persist_adapter_transition


class AdapterLifecycleTests(unittest.TestCase):
    def _adapter(self, state: str = "discovered") -> dict:
        return {
            "schema": "smart_llm_router.adapter_declaration.v1",
            "adapter_id": "qwen-text-primary",
            "provider": "qwen-free",
            "model": "qwen-plus-latest",
            "modalities": ["text"],
            "current_state": state,
            "billing_class": "trial_quota",
        }

    def _request(self, target: str, **overrides: object) -> dict:
        payload = {
            "schema": "smart_llm_router.adapter_transition_request.v1",
            "target_state": target,
            "reason": "validated lifecycle transition",
            "health_evidence": {
                "canary_passed": True,
                "health_samples": 3,
                "degraded": False,
            },
            "owner_approved": False,
            "smoke_test_passed": False,
            "rollback_plan": "",
        }
        payload.update(overrides)
        return payload

    def _promotion(self, status: str = "pass") -> dict:
        return {
            "schema": "smart_llm_router.promotion_decision.v1",
            "report_id": "report-1",
            "candidate": {"provider": "qwen-free", "model": "qwen-plus-latest"},
            "status": status,
            "eligible_for_explicit_role_band_registration": status == "pass",
            "proposed_role": "audit",
            "proposed_quality_band": 3,
            "route_health": {"health_samples": 3, "degraded": False},
            "reasons": [] if status == "pass" else ["insufficient_live_health_samples"],
        }

    def test_discovered_cannot_skip_directly_to_candidate(self) -> None:
        receipt = evaluate_adapter_transition(self._adapter(), self._request("candidate"))
        self.assertEqual(receipt["status"], "hold")
        self.assertIn("illegal_state_transition", receipt["reasons"])

    def test_shadow_candidate_requires_canary_and_health(self) -> None:
        request = self._request(
            "candidate",
            health_evidence={"canary_passed": False, "health_samples": 0, "degraded": False},
        )
        receipt = evaluate_adapter_transition(self._adapter("shadow"), request)
        self.assertEqual(receipt["status"], "hold")
        self.assertIn("canary_not_passed", receipt["reasons"])
        self.assertIn("insufficient_health_samples", receipt["reasons"])

    def test_candidate_qualified_requires_matching_passed_promotion(self) -> None:
        hold = evaluate_adapter_transition(
            self._adapter("candidate"),
            self._request("qualified"),
            promotion_decision=self._promotion("hold"),
        )
        passed = evaluate_adapter_transition(
            self._adapter("candidate"),
            self._request("qualified"),
            promotion_decision=self._promotion("pass"),
        )
        self.assertEqual(hold["status"], "hold")
        self.assertIn("promotion_decision_not_passed", hold["reasons"])
        self.assertEqual(passed["status"], "pass")
        self.assertFalse(passed["automatic_registry_change"])

    def test_production_requires_owner_smoke_and_rollback_evidence(self) -> None:
        missing = evaluate_adapter_transition(
            self._adapter("qualified"),
            self._request("production"),
            promotion_decision=self._promotion("pass"),
        )
        passed = evaluate_adapter_transition(
            self._adapter("qualified"),
            self._request(
                "production",
                owner_approved=True,
                smoke_test_passed=True,
                rollback_plan="disable adapter and restore previous role registration",
            ),
            promotion_decision=self._promotion("pass"),
        )
        self.assertEqual(missing["status"], "hold")
        self.assertIn("owner_approval_missing", missing["reasons"])
        self.assertIn("smoke_test_missing", missing["reasons"])
        self.assertIn("rollback_plan_missing", missing["reasons"])
        self.assertEqual(passed["status"], "pass")
        self.assertEqual(passed["to_state"], "production")
        self.assertFalse(passed["automatic_production_change"])

    def test_production_can_downgrade_without_promotion_evidence(self) -> None:
        receipt = evaluate_adapter_transition(
            self._adapter("production"),
            self._request(
                "qualified",
                reason="rollback after production health regression",
                health_evidence={"canary_passed": False, "health_samples": 0, "degraded": True},
            ),
        )
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["next_action"], "owner_may_apply_state_change")

    def test_private_state_persists_only_passed_transition(self) -> None:
        adapter = self._adapter("shadow")
        passed = evaluate_adapter_transition(adapter, self._request("candidate"))
        held = evaluate_adapter_transition(adapter, self._request("qualified"))
        with tempfile.TemporaryDirectory() as tmp:
            persisted = persist_adapter_transition(adapter, passed, tmp)
            state = json.loads(Path(str(persisted["state_path"])).read_text(encoding="utf-8"))
            persisted_receipt = json.loads(Path(str(persisted["receipt_path"])).read_text(encoding="utf-8"))
            held_paths = persist_adapter_transition(adapter, held, tmp)
            self.assertEqual(state["current_state"], "candidate")
            self.assertEqual(persisted_receipt["next_action"], "state_change_persisted")
            self.assertEqual(persisted_receipt["runtime_state"], persisted)
            self.assertIsNone(held_paths["state_path"])
            self.assertTrue(Path(str(held_paths["receipt_path"])).is_file())

    def test_adapter_id_must_be_filesystem_safe(self) -> None:
        adapter = self._adapter()
        adapter["adapter_id"] = "../escape"
        with self.assertRaisesRegex(ValueError, "filesystem-safe"):
            evaluate_adapter_transition(adapter, self._request("shadow"))


if __name__ == "__main__":
    unittest.main()
