import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    _cache_key,
    _validate_structured_output,
    describe_task_v2,
    infer_task_descriptor,
    recommend_route,
    route_plan,
    run_llm_task,
    score_task_complexity,
)

TIER_RANK = {"simple": 0, "balanced": 1, "deep": 2}
LEGACY_TIER = {"simple": "simple", "medium": "balanced", "hard": "deep"}
CALIBRATION_PATH = Path(__file__).parent / "fixtures" / "task_descriptor_v2_calibration.json"
ADVERSARIAL_PATH = Path(__file__).parent / "fixtures" / "task_descriptor_v2_adversarial.json"


def calibration_metrics() -> dict:
    cases = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))["cases"]
    metrics = {
        "case_count": len(cases),
        "v2_underestimates": 0,
        "legacy_underestimates": 0,
        "v2_overestimates": 0,
        "legacy_overestimates": 0,
        "v2_underestimates_by_group": Counter(),
        "legacy_underestimates_by_group": Counter(),
    }
    for case in cases:
        expected = case["expected_minimum_tier"]
        descriptor = describe_task_v2(
            case["task"],
            case["prompt"],
            case.get("context"),
            input_modalities=case.get("input_modalities"),
        )
        legacy = score_task_complexity(case["task"], case["prompt"], case.get("context"))
        v2_tier = descriptor["selected_tier"]
        legacy_tier = LEGACY_TIER[legacy["label"]]
        if TIER_RANK[v2_tier] < TIER_RANK[expected]:
            metrics["v2_underestimates"] += 1
            metrics["v2_underestimates_by_group"][case["group"]] += 1
        if TIER_RANK[legacy_tier] < TIER_RANK[expected]:
            metrics["legacy_underestimates"] += 1
            metrics["legacy_underestimates_by_group"][case["group"]] += 1
        if TIER_RANK[v2_tier] > TIER_RANK[expected]:
            metrics["v2_overestimates"] += 1
        if TIER_RANK[legacy_tier] > TIER_RANK[expected]:
            metrics["legacy_overestimates"] += 1
    metrics["v2_underestimates_by_group"] = dict(metrics["v2_underestimates_by_group"])
    metrics["legacy_underestimates_by_group"] = dict(metrics["legacy_underestimates_by_group"])
    return metrics


class TaskDescriptorV2Tests(unittest.TestCase):
    def _settings(self) -> Settings:
        return Settings(
            data_dir=Path(tempfile.mkdtemp()),
            providers=(),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def test_explicit_simple_intent_is_eligible(self) -> None:
        descriptor = describe_task_v2("qa", "谢谢")
        self.assertTrue(descriptor["simple_eligibility"]["eligible"])
        self.assertEqual(descriptor["selected_tier"], "simple")

    def test_short_context_dependent_request_has_balanced_floor(self) -> None:
        descriptor = describe_task_v2("qa", "按刚才的方案继续")
        self.assertTrue(descriptor["features"]["context_dependent"])
        self.assertEqual(descriptor["minimum_tier"], "balanced")
        self.assertNotEqual(descriptor["selected_tier"], "simple")

    def test_output_constraint_does_not_hide_tool_requirement(self) -> None:
        descriptor = describe_task_v2("qa", "运行终端并验证全部测试，只输出 OK")
        self.assertTrue(descriptor["features"]["requires_tools"])
        self.assertEqual(descriptor["minimum_tier"], "balanced")
        self.assertFalse(descriptor["simple_eligibility"]["eligible"])

    def test_available_modality_is_an_explicit_floor(self) -> None:
        descriptor = describe_task_v2("vision", "检查内容", input_modalities=["text", "image"])
        self.assertEqual(descriptor["minimum_tier"], "balanced")
        self.assertIn("non_text_input", descriptor["floor_reasons"])

    def test_strict_json_requires_balanced_tier(self) -> None:
        descriptor = describe_task_v2("qa", "只返回严格 JSON schema")
        self.assertTrue(descriptor["features"]["structured_output_required"])
        self.assertEqual(descriptor["minimum_tier"], "balanced")

    def test_cross_file_scope_requires_deep_tier(self) -> None:
        descriptor = describe_task_v2("code", "完成跨文件架构迁移并保持兼容")
        self.assertEqual(descriptor["minimum_tier"], "deep")
        self.assertEqual(descriptor["selected_tier"], "deep")

    def test_receipt_has_no_raw_prompt_or_private_path(self) -> None:
        prompt = "检查 /Users/example/private/project 并保持安全"
        descriptor = describe_task_v2("audit", prompt)
        serialized = str(descriptor)
        self.assertNotIn(prompt, serialized)
        self.assertNotIn("/Users/example/private/project", serialized)
        self.assertEqual(len(descriptor["input_fingerprint"]), 16)
        self.assertEqual(descriptor["routing_effect"], "none")

    def test_score_recommend_and_plan_share_shadow_descriptor(self) -> None:
        prompt = "按刚才的方案继续"
        score = score_task_complexity("qa", prompt)
        recommendation = recommend_route(
            self._settings(),
            task="qa",
            prompt=prompt,
            paid_fallback=False,
        )
        plan = route_plan(
            self._settings(),
            task="qa",
            prompt=prompt,
            paid_allowed=False,
        )
        score_shadow = score["shadow_descriptor_v2"]
        recommend_shadow = recommendation["complexity"]["shadow_descriptor_v2"]
        plan_shadow = plan["descriptor"]["complexity_detail"]["shadow_descriptor_v2"]
        self.assertEqual(score_shadow, recommend_shadow)
        self.assertEqual(score_shadow, plan_shadow)
        self.assertEqual(plan["recommended_order"], [])

    def test_route_plan_passes_non_text_modalities_to_shadow_descriptor(self) -> None:
        descriptor = infer_task_descriptor(
            task="vision",
            prompt="检查内容",
            input_modalities=["text", "image"],
        )
        shadow = descriptor["complexity_detail"]["shadow_descriptor_v2"]
        self.assertEqual(shadow["features"]["input_modalities"], ["image", "text"])
        self.assertEqual(shadow["minimum_tier"], "balanced")

    def test_sixty_case_calibration_has_no_v2_underestimation(self) -> None:
        metrics = calibration_metrics()
        self.assertEqual(metrics["case_count"], 60)
        self.assertEqual(metrics["v2_underestimates"], 0, metrics)
        self.assertEqual(metrics["v2_underestimates_by_group"], {}, metrics)

    def test_blind_reviewed_adversarial_cases_match_adjudicated_tiers(self) -> None:
        cases = json.loads(ADVERSARIAL_PATH.read_text(encoding="utf-8"))["cases"]
        disagreements = []
        for case in cases:
            actual = describe_task_v2(
                case["task"],
                case["prompt"],
                input_modalities=case.get("input_modalities"),
            )["selected_tier"]
            if actual != case["expected_tier"]:
                disagreements.append((case["id"], case["expected_tier"], actual))
        self.assertEqual(len(cases), 30)
        self.assertEqual(disagreements, [])

    def test_controlled_activation_defaults_off(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED", None)
            complexity = score_task_complexity("qa", "把“安全审计”翻译成英文")
        self.assertEqual(complexity["label"], complexity["legacy_label"])
        self.assertEqual(complexity["complexity_source"], "legacy")
        self.assertFalse(complexity["activation"]["applied"])
        self.assertEqual(complexity["shadow_descriptor_v2"]["routing_effect"], "none")

    def test_controlled_activation_changes_only_non_role_complexity(self) -> None:
        with patch.dict(os.environ, {"SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED": "true"}):
            complexity = score_task_complexity("qa", "把“安全审计”翻译成英文")
        self.assertEqual(complexity["legacy_label"], "hard")
        self.assertEqual(complexity["label"], "simple")
        self.assertEqual(complexity["complexity_source"], "task_descriptor_v2")
        self.assertTrue(complexity["activation"]["applied"])
        self.assertEqual(complexity["shadow_descriptor_v2"]["routing_effect"], "non_role_complexity")

    def test_controlled_activation_never_changes_role_task_complexity(self) -> None:
        with patch.dict(os.environ, {"SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED": "true"}):
            descriptor = infer_task_descriptor(
                task="audit",
                prompt="把“安全审计”翻译成英文",
                quality_target="frontier",
            )
        complexity = descriptor["complexity_detail"]
        self.assertEqual(complexity["label"], complexity["legacy_label"])
        self.assertEqual(complexity["complexity_source"], "legacy")
        self.assertTrue(complexity["activation"]["requested"])
        self.assertFalse(complexity["activation"]["eligible"])
        self.assertFalse(complexity["activation"]["applied"])
        self.assertEqual(descriptor["quality_target"], "frontier")
        self.assertEqual(complexity["shadow_descriptor_v2"]["routing_effect"], "none")

    def test_controlled_activation_has_one_step_rollback(self) -> None:
        prompt = "把“安全审计”翻译成英文"
        with patch.dict(os.environ, {"SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED": "true"}):
            enabled = score_task_complexity("qa", prompt)
        with patch.dict(os.environ, {"SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED": "false"}):
            rolled_back = score_task_complexity("qa", prompt)
        self.assertNotEqual(enabled["label"], enabled["legacy_label"])
        self.assertEqual(rolled_back["label"], rolled_back["legacy_label"])
        self.assertFalse(rolled_back["activation"]["applied"])

    def test_controlled_activation_uses_a_distinct_cache_namespace(self) -> None:
        common = {
            "task": "qa",
            "prompt": "把“安全审计”翻译成英文",
            "context": None,
            "prefer_free": True,
            "paid_fallback": False,
            "temperature": 0.2,
        }
        legacy_key = _cache_key(
            **common,
            complexity_label="hard",
            complexity_source="legacy",
        )
        v2_key = _cache_key(
            **common,
            complexity_label="simple",
            complexity_source="task_descriptor_v2",
            complexity_version="task-signals-v2-shadow",
        )
        self.assertNotEqual(legacy_key, v2_key)
        next_version_key = _cache_key(
            **common,
            complexity_label="simple",
            complexity_source="task_descriptor_v2",
            complexity_version="task-signals-v2-next",
        )
        self.assertNotEqual(v2_key, next_version_key)

    def test_strict_json_rejects_markdown_fences(self) -> None:
        self.assertEqual(_validate_structured_output('{"status":"ok"}', "json"), (True, None))
        self.assertEqual(
            _validate_structured_output('```json\n{"status":"ok"}\n```', "json"),
            (False, "strict_json_parse_failed"),
        )

    def test_strict_json_rejection_falls_back_without_cooling_healthy_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                data_dir=Path(tmp),
                providers=(
                    LLMProvider("first-free", "https://first.test/v1", "FIRST_KEY", ("model-a",), True, 1),
                    LLMProvider("second-free", "https://second.test/v1", "SECOND_KEY", ("model-b",), True, 2),
                ),
                timeout=5,
                empty_pool_refresh_timeout=1,
                empty_pool_refresh_limit=1,
            )
            responses = [
                ('```json\n{"status":"ok"}\n```', {"prompt_tokens": 5, "completion_tokens": 5}),
                ('{"status":"ok"}', {"prompt_tokens": 5, "completion_tokens": 3}),
            ]
            with patch.dict(
                os.environ,
                {"FIRST_KEY": "test", "SECOND_KEY": "test", "SMART_LLM_CACHE": "false"},
                clear=False,
            ):
                with patch("smart_llm_router.router._call_openai_compatible", side_effect=responses) as call:
                    result = run_llm_task(
                        settings,
                        task="qa",
                        prompt='只返回严格 JSON：{"status":"ok"}',
                        paid_fallback=False,
                        privacy="external_allowed",
                    )
            ledger = [
                json.loads(line)
                for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            state_path = settings.data_dir / "llm_router_state.json"
            state_exists = state_path.exists()

        self.assertEqual(call.call_count, 2)
        self.assertEqual(result.provider, "second-free")
        self.assertEqual(result.content, '{"status":"ok"}')
        self.assertEqual([row["event"] for row in ledger], ["model_output_rejected", "model_call"])
        self.assertFalse(state_exists)


if __name__ == "__main__":
    unittest.main()
