import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.governance import build_workflow_plan, evaluate_workflow_checkpoint, validate_workflow_contract


class WorkflowGovernanceTests(unittest.TestCase):
    def _settings(self) -> Settings:
        providers = (
            LLMProvider("qwen-frontier-paid", "https://qwen.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid"),
            LLMProvider("zhipu-glm-lowcost", "https://glm.test/v1", "GLM_KEY", ("glm-5.2",), False, 2, "paid"),
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 3, "trial_quota"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 4, "paid"),
            LLMProvider("kimi-frontier-paid", "https://kimi.test/v1", "KIMI_KEY", ("kimi-k3",), False, 5, "paid"),
        )
        return Settings(
            data_dir=Path(tempfile.mkdtemp()),
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def _contract(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": "hermes_router_hub.workflow_contract.v1",
            "workflow_id": "wf-test",
            "objective": "交付可验收且不偏离目标的智能路由升级",
            "success_criteria": [
                {"id": "tests", "text": "全部自动化测试通过"},
                {"id": "scope", "text": "未增加未批准范围"},
            ],
            "quality_target": "frontier",
            "privacy": "external_allowed",
            "paid_allowed": True,
            "workflow_budget_usd": 0.05,
            "max_stage_cost_usd": 0.02,
            "max_conditional_checks": 1,
            "automation_mode": "manual_controlled",
        }
        payload.update(overrides)
        return payload

    def test_contract_requires_measurable_success_criteria(self) -> None:
        with self.assertRaisesRegex(ValueError, "success_criteria"):
            validate_workflow_contract(self._contract(success_criteria=[]))

    def test_contract_rejects_unknown_task_type_and_risk(self) -> None:
        with self.assertRaisesRegex(ValueError, "task_type"):
            validate_workflow_contract(self._contract(task_type="invent"))
        with self.assertRaisesRegex(ValueError, "risk"):
            validate_workflow_contract(self._contract(risk="extreme"))

    def test_plan_orders_audit_before_execution_and_reserves_budget(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), self._contract())
        self.assertTrue(result["ready_to_execute"])
        self.assertEqual(
            [stage["stage"] for stage in result["stages"]],
            ["plan_design", "plan_audit", "execute", "process_checkpoint", "final_verify", "quality_enhance"],
        )
        self.assertEqual(result["stages"][0]["selected"]["model"], "qwen3.7-max")
        self.assertEqual(result["stages"][1]["selected"]["model"], "gemini-2.5-pro")
        self.assertTrue(result["stages"][1]["selected"]["free"])
        self.assertEqual(result["stages"][2]["selected"]["model"], "glm-5.2")
        self.assertEqual(result["stages"][3]["call_policy"], "conditional")
        self.assertEqual(result["stages"][-1]["stage"], "quality_enhance")
        self.assertEqual(result["stages"][-1]["call_policy"], "conditional")
        self.assertLess(result["budget"]["projected_required_usd"], result["budget"]["projected_total_ceiling_usd"])
        self.assertLessEqual(result["budget"]["projected_total_ceiling_usd"], 0.05)

    def test_production_workflow_uses_the_shared_band_three_floor(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(
                self._settings(),
                self._contract(quality_target="production"),
            )
        roles = {stage["stage"]: stage for stage in result["stages"]}
        self.assertTrue(result["ready_to_execute"])
        self.assertEqual(roles["plan_design"]["selected"]["minimum_role_quality_band"], 3)
        self.assertEqual(roles["plan_design"]["selected"]["model"], "gemini-2.5-pro")
        self.assertTrue(roles["plan_design"]["selected"]["free"])
        self.assertNotEqual(
            roles["plan_design"]["selected"]["model_family"],
            roles["plan_audit"]["selected"]["model_family"],
        )
        self.assertNotEqual(
            roles["execute"]["selected"]["model_family"],
            roles["final_verify"]["selected"]["model_family"],
        )

    def test_plan_fails_closed_when_workflow_budget_is_too_small(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        contract = self._contract(workflow_budget_usd=0.005, max_stage_cost_usd=0.005)
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), contract)
        self.assertFalse(result["ready_to_execute"])
        self.assertTrue(any("exceeds budget" in reason or "no eligible" in reason for reason in result["hard_stops"]))

    def test_unattended_workflow_requires_explicit_hermes_security_approval(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        contract = self._contract(automation_mode="unattended", hermes_security_approved=False)
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), contract)
        self.assertFalse(result["ready_to_execute"])
        self.assertTrue(any("Hermes security gate" in reason for reason in result["hard_stops"]))

    def test_auto_privacy_fails_closed_when_objective_contains_sensitive_data(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        contract = self._contract(objective="整理私人聊天记录并输出摘要", privacy="auto")
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), contract)
        self.assertEqual(result["effective_privacy"], "local_only")
        self.assertFalse(result["ready_to_execute"])
        self.assertTrue(any("local_only" in reason for reason in result["hard_stops"]))

    def test_checkpoint_requires_verification_when_scope_changes(self) -> None:
        receipt = evaluate_workflow_checkpoint(
            self._contract(),
            {
                "schema": "hermes_router_hub.workflow_checkpoint.v1",
                "workflow_id": "wf-test",
                "stage": "execute",
                "objective_alignment": "aligned",
                "evidence": ["tests:pass"],
                "scope_changes": ["新增未经批准的远程服务"],
                "criterion_status": {"tests": "pass", "scope": "unknown"},
                "spent_usd": 0.01,
            },
        )
        self.assertEqual(receipt["decision"], "verify_required")
        self.assertTrue(receipt["drift_detected"])

    def test_process_checkpoint_does_not_spend_on_criteria_not_due_yet(self) -> None:
        receipt = evaluate_workflow_checkpoint(
            self._contract(),
            {
                "schema": "hermes_router_hub.workflow_checkpoint.v1",
                "workflow_id": "wf-test",
                "stage": "execute",
                "objective_alignment": "aligned",
                "evidence": ["artifact:sha256"],
                "scope_changes": [],
                "criterion_status": {"tests": "pass"},
                "spent_usd": 0.01,
            },
        )
        self.assertEqual(receipt["criterion_status"]["scope"], "not_checked")
        self.assertEqual(receipt["decision"], "continue")

    def test_final_verify_completes_only_when_every_criterion_passes(self) -> None:
        checkpoint = {
            "schema": "hermes_router_hub.workflow_checkpoint.v1",
            "workflow_id": "wf-test",
            "stage": "final_verify",
            "objective_alignment": "aligned",
            "evidence": ["tests:30-pass", "scope:diff-reviewed"],
            "scope_changes": [],
            "criterion_status": {"tests": "pass", "scope": "pass"},
            "spent_usd": 0.03,
        }
        self.assertEqual(evaluate_workflow_checkpoint(self._contract(), checkpoint)["decision"], "complete")
        checkpoint["criterion_status"] = {"tests": "pass", "scope": "unknown"}
        self.assertEqual(evaluate_workflow_checkpoint(self._contract(), checkpoint)["decision"], "stop")


if __name__ == "__main__":
    unittest.main()
