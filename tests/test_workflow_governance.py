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
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 3, "trial_quota", True),
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

    def _v2_contract(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": "hermes_router_hub.workflow_contract.v2",
            "workflow_id": "wf-v2-test",
            "objective": "交付按难度分级、研究增强、独立审计和增量复验的智能路由升级",
            "success_criteria": [
                {"id": "tests", "text": "全部自动化测试通过"},
                {"id": "scope", "text": "未增加未批准范围"},
            ],
            "task_type": "execute",
            "domain": "software",
            "risk": "high",
            "complexity_tier": "complex",
            "quality_target": "frontier",
            "privacy": "external_allowed",
            "paid_allowed": True,
            "workspace_execution_required": True,
            "research_required": True,
            "research_sources": [
                {
                    "title": "OpenAI model guidance",
                    "url": "https://developers.openai.com/api/docs/guides/latest-model",
                    "accessed_at": "2026-08-02",
                }
            ],
            "budget_policy": {
                "soft_target_usd": 0.03,
                "elastic_limit_usd": 0.10,
                "anomaly_hard_limit_usd": 0.25,
                "max_stage_cost_usd": 0.03,
            },
            "max_conditional_checks": 1,
            "max_plan_repair_loops": 1,
            "max_result_repair_loops": 1,
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

    def test_v2_complex_workflow_uses_confirmed_three_family_planning_loop(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), self._v2_contract())
        self.assertTrue(result["ready_to_execute"])
        self.assertEqual(
            [stage["stage"] for stage in result["stages"]],
            [
                "plan_design",
                "research_enhance",
                "plan_audit",
                "plan_repair",
                "plan_delta_verify",
                "execute",
                "process_checkpoint",
                "final_verify",
                "result_repair",
                "final_delta_verify",
                "closeout",
            ],
        )
        stages = {stage["stage"]: stage for stage in result["stages"]}
        self.assertEqual(stages["plan_design"]["selected"]["model"], "gpt-5.6-sol")
        self.assertEqual(stages["research_enhance"]["selected"]["model"], "qwen3.7-max")
        self.assertEqual(stages["plan_audit"]["selected"]["model"], "deepseek-v4-pro")
        self.assertEqual(stages["plan_delta_verify"]["selected"]["model"], "deepseek-v4-pro")
        self.assertEqual(stages["execute"]["selected"]["model"], "gpt-5.6-terra")
        self.assertEqual(stages["final_verify"]["selected"]["model"], "deepseek-v4-pro")
        self.assertEqual(stages["final_delta_verify"]["selected"]["model"], "deepseek-v4-pro")
        self.assertTrue(result["gates"]["delta_verification_reuses_original_auditor"])

    def test_v2_simple_workflow_skips_external_planning_and_audit_chain(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(
                self._settings(),
                self._v2_contract(
                    complexity_tier="simple",
                    risk="low",
                    quality_target="production",
                    research_required=False,
                    research_sources=[],
                    workspace_execution_required=True,
                ),
            )
        self.assertTrue(result["ready_to_execute"])
        self.assertEqual(
            [stage["stage"] for stage in result["stages"]],
            ["plan_design", "execute", "process_checkpoint", "closeout"],
        )
        self.assertEqual(result["stages"][0]["selected"]["model"], "gpt-5.6-terra")

    def test_v2_required_research_fails_closed_without_provenance(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), self._v2_contract(research_sources=[]))
        self.assertFalse(result["ready_to_execute"])
        self.assertTrue(any("URL and accessed_at" in reason for reason in result["hard_stops"]))

    def test_v2_soft_budget_warning_does_not_stop(self) -> None:
        env = {"QWEN_KEY": "test", "GLM_KEY": "test", "GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "KIMI_KEY": "test"}
        budget = {
            "soft_target_usd": 0.000001,
            "elastic_limit_usd": 0.10,
            "anomaly_hard_limit_usd": 0.25,
            "max_stage_cost_usd": 0.03,
        }
        with patch.dict(os.environ, env, clear=True):
            result = build_workflow_plan(self._settings(), self._v2_contract(budget_policy=budget))
        self.assertTrue(result["ready_to_execute"])
        self.assertEqual(result["budget"]["status"], "within_elastic")
        self.assertTrue(result["warnings"])

    def test_v2_checkpoint_over_elastic_limit_requires_authorization(self) -> None:
        checkpoint = {
            "schema": "hermes_router_hub.workflow_checkpoint.v2",
            "workflow_id": "wf-v2-test",
            "stage": "execute",
            "objective_alignment": "aligned",
            "evidence": ["tests:pass"],
            "scope_changes": [],
            "criterion_status": {"tests": "pass", "scope": "pass"},
            "spent_usd": 0.100001,
        }
        result = evaluate_workflow_checkpoint(self._v2_contract(), checkpoint)
        self.assertEqual(result["decision"], "authorization_required")
        self.assertIn("elastic budget exceeded", result["drift_reasons"])
        self.assertEqual(result["remaining_budget_usd"], 0.0)

    def test_v2_unattended_checkpoint_cannot_silently_cross_elastic_limit(self) -> None:
        contract = self._v2_contract(automation_mode="unattended", hermes_security_approved=True)
        checkpoint = {
            "schema": "hermes_router_hub.workflow_checkpoint.v2",
            "workflow_id": "wf-v2-test",
            "stage": "execute",
            "objective_alignment": "aligned",
            "evidence": ["tests:pass"],
            "scope_changes": [],
            "criterion_status": {"tests": "pass", "scope": "pass"},
            "spent_usd": 0.11,
        }
        result = evaluate_workflow_checkpoint(contract, checkpoint)
        self.assertEqual(result["decision"], "authorization_required")

    def test_v2_checkpoint_over_anomaly_limit_stops(self) -> None:
        checkpoint = {
            "schema": "hermes_router_hub.workflow_checkpoint.v2",
            "workflow_id": "wf-v2-test",
            "stage": "execute",
            "objective_alignment": "aligned",
            "evidence": ["tests:pass"],
            "scope_changes": [],
            "criterion_status": {"tests": "pass", "scope": "pass"},
            "spent_usd": 0.250001,
        }
        result = evaluate_workflow_checkpoint(self._v2_contract(), checkpoint)
        self.assertEqual(result["decision"], "stop")
        self.assertIn("anomaly hard budget exceeded", result["drift_reasons"])

    def test_v2_checkpoint_routes_fundamental_plan_failure_back_to_sol(self) -> None:
        checkpoint = {
            "schema": "hermes_router_hub.workflow_checkpoint.v2",
            "workflow_id": "wf-v2-test",
            "stage": "plan_audit",
            "objective_alignment": "aligned",
            "evidence": ["audit:finding"],
            "scope_changes": [],
            "criterion_status": {"tests": "unknown", "scope": "pass"},
            "spent_usd": 0.02,
            "redesign_required": True,
            "repair_loop_count": 0,
        }
        result = evaluate_workflow_checkpoint(self._v2_contract(), checkpoint)
        self.assertEqual(result["decision"], "redesign_required")

    def test_v2_final_failure_uses_one_repair_loop_then_stops(self) -> None:
        checkpoint = {
            "schema": "hermes_router_hub.workflow_checkpoint.v2",
            "workflow_id": "wf-v2-test",
            "stage": "final_verify",
            "objective_alignment": "aligned",
            "evidence": ["audit:blocker"],
            "scope_changes": [],
            "criterion_status": {"tests": "fail", "scope": "pass"},
            "spent_usd": 0.04,
            "repair_loop_count": 0,
        }
        first = evaluate_workflow_checkpoint(self._v2_contract(), checkpoint)
        self.assertEqual(first["decision"], "repair_required")
        self.assertTrue(first["budget_warnings"])
        checkpoint["repair_loop_count"] = 1
        second = evaluate_workflow_checkpoint(self._v2_contract(), checkpoint)
        self.assertEqual(second["decision"], "stop")


if __name__ == "__main__":
    unittest.main()
