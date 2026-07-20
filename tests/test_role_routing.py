import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import LLMChoice, _max_output_tokens_for_budget, _price_per_million, describe_choice_capability, recommend_route, route_plan, run_llm_task


class RoleRoutingTests(unittest.TestCase):
    def _settings(self, providers: tuple[LLMProvider, ...]) -> Settings:
        return Settings(
            data_dir=Path(tempfile.mkdtemp()),
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def test_declared_candidate_is_excluded_until_qualified(self) -> None:
        provider = LLMProvider(
            "nvidia-google-free",
            "https://nvidia.test/v1",
            "NVIDIA_KEY",
            ("google/gemma-3n-e4b-it",),
            True,
            1,
            "trial_quota",
        )
        rotated_provider = LLMProvider(
            "nvidia-google-free-key2",
            provider.base_url,
            "NVIDIA_KEY_2",
            provider.models,
            True,
            2,
            "trial_quota",
        )
        settings = self._settings((provider, rotated_provider))
        adapters = settings.data_dir / "adapter-lifecycle" / "adapters"
        adapters.mkdir(parents=True)
        declaration = {
            "provider": provider.name,
            "model": provider.models[0],
            "current_state": "candidate",
        }
        state_path = adapters / "gemma.json"
        state_path.write_text(json.dumps(declaration), encoding="utf-8")
        with patch.dict(os.environ, {"NVIDIA_KEY": "test", "NVIDIA_KEY_2": "test"}, clear=True):
            candidate = recommend_route(settings, task="qa", prompt="只输出 OK", paid_fallback=False)
            declaration["current_state"] = "qualified"
            state_path.write_text(json.dumps(declaration), encoding="utf-8")
            qualified = recommend_route(settings, task="qa", prompt="只输出 OK", paid_fallback=False)
        self.assertEqual(candidate["recommended_order"], [])
        self.assertEqual(qualified["recommended_order"][0]["model"], provider.models[0])

    def test_frontier_pipeline_uses_independent_model_families(self) -> None:
        providers = (
            LLMProvider("qwen-frontier-paid", "https://dashscope.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid"),
            LLMProvider("zhipu-glm-lowcost", "https://zhipu.test/v1", "GLM_KEY", ("glm-5.2",), False, 2, "paid"),
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 3, "trial_quota"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 4, "paid"),
            LLMProvider("kimi-frontier-paid", "https://kimi.test/v1", "KIMI_KEY", ("kimi-k3",), False, 5, "paid"),
        )
        env = {provider.api_key_env: "test" for provider in providers}
        with patch.dict(os.environ, env, clear=True):
            plan = route_plan(
                self._settings(providers),
                task="plan",
                prompt="规划并交付一个复杂系统",
                quality_target="frontier",
                paid_allowed=True,
            )
        selected = [stage["selected"] for stage in plan["role_pipeline"]]
        self.assertEqual([row["model"] for row in selected], [
            "qwen3.7-max",
            "glm-5.2",
            "gemini-2.5-pro",
            "gemini-2.5-pro",
            "kimi-k3",
        ])
        self.assertEqual(len({row["model_family"] for row in selected}), 4)
        self.assertTrue(selected[2]["free"])
        self.assertTrue(selected[3]["free"])
        self.assertNotEqual(selected[0]["model_family"], selected[2]["model_family"])
        self.assertNotEqual(selected[1]["model_family"], selected[3]["model_family"])

    def test_role_execution_uses_one_free_model_when_quality_band_is_equal(self) -> None:
        providers = (
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 1, "trial_quota"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        with patch.dict(os.environ, {"GEMINI_KEY": "test", "DEEPSEEK_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible", return_value=("OK", {})) as call:
                result = run_llm_task(
                    self._settings(providers),
                    task="audit",
                    prompt="审计这份公开规划",
                    quality_target="frontier",
                    privacy="external_allowed",
                )
        self.assertEqual(result.provider, "gemini-free")
        self.assertEqual(call.call_count, 1)

    def test_stronger_role_band_beats_lower_band_free_model(self) -> None:
        providers = (
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 1, "trial_quota"),
            LLMProvider("qwen-frontier-paid", "https://qwen.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 2, "paid"),
        )
        with patch.dict(os.environ, {"GEMINI_KEY": "test", "QWEN_KEY": "test"}, clear=True):
            plan = route_plan(
                self._settings(providers),
                task="plan",
                prompt="规划复杂生产系统",
                quality_target="frontier",
                paid_allowed=True,
            )
        self.assertEqual(plan["role_pipeline"][0]["selected"]["model"], "qwen3.7-max")
        self.assertFalse(plan["role_pipeline"][0]["selected"]["free"])

    def test_promoted_groq_verifier_is_role_band_two(self) -> None:
        provider = LLMProvider(
            "groq-free",
            "https://groq.test/v1",
            "GROQ_KEY",
            ("openai/gpt-oss-120b",),
            True,
            1,
            "trial_quota",
        )
        with patch.dict(os.environ, {"GROQ_KEY": "test"}, clear=True):
            result = recommend_route(
                self._settings((provider,)),
                task="verify",
                prompt="独立复验公开任务",
                prefer_free=True,
                quality_target="draft",
            )
        self.assertEqual(result["recommended_order"][0]["model"], "openai/gpt-oss-120b")
        self.assertEqual(result["recommended_order"][0]["role_quality_band"], 2)
        self.assertEqual(result["recommended_order"][0]["billing_class"], "trial_quota")

    def test_quality_floor_is_shared_by_recommend_plan_and_direct_run(self) -> None:
        providers = (
            LLMProvider("groq-free", "https://groq.test/v1", "GROQ_KEY", ("openai/gpt-oss-120b",), True, 1, "trial_quota"),
            LLMProvider("unregistered-free", "https://free.test/v1", "FREE_KEY", ("unregistered-chat",), True, 2, "permanent_free"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 3, "paid"),
        )
        settings = self._settings(providers)
        env = {"GROQ_KEY": "test", "FREE_KEY": "test", "DEEPSEEK_KEY": "test", "SMART_LLM_CACHE": "false"}
        with patch.dict(os.environ, env, clear=True):
            recommendation = recommend_route(
                settings,
                task="verify",
                prompt="独立复验公开任务",
                quality_target="draft",
            )
            plan = route_plan(
                settings,
                task="verify",
                prompt="独立复验公开任务",
                quality_target="draft",
            )
            with patch("smart_llm_router.router._call_openai_compatible", return_value=("OK", {})) as call:
                result = run_llm_task(
                    settings,
                    task="verify",
                    prompt="独立复验公开任务",
                    quality_target="draft",
                    privacy="external_allowed",
                )

        self.assertEqual(recommendation["policy"]["minimum_role_quality_band"], 2)
        self.assertEqual([row["model"] for row in recommendation["recommended_order"]], ["openai/gpt-oss-120b", "deepseek-v4-pro"])
        verify_stage = next(row for row in plan["role_pipeline"] if row["stage"] == "verify")
        self.assertEqual(verify_stage["selected"]["model"], "openai/gpt-oss-120b")
        self.assertEqual(verify_stage["minimum_role_quality_band"], 2)
        self.assertEqual(result.model, "openai/gpt-oss-120b")
        self.assertEqual(call.call_count, 1)

    def test_production_excludes_band_two_but_can_use_free_sufficient_band_three(self) -> None:
        verify_providers = (
            LLMProvider("groq-free", "https://groq.test/v1", "GROQ_KEY", ("openai/gpt-oss-120b",), True, 1, "trial_quota"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        execute_providers = (
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 1, "trial_quota"),
            LLMProvider("zhipu-glm-lowcost", "https://glm.test/v1", "GLM_KEY", ("glm-5.2",), False, 2, "paid"),
        )
        env = {"GROQ_KEY": "test", "DEEPSEEK_KEY": "test", "GEMINI_KEY": "test", "GLM_KEY": "test"}
        with patch.dict(os.environ, env, clear=True):
            verify = recommend_route(
                self._settings(verify_providers),
                task="verify",
                prompt="复验生产任务",
                quality_target="production",
            )
            execute = recommend_route(
                self._settings(execute_providers),
                task="execute",
                prompt="执行生产任务",
                quality_target="production",
            )

        self.assertEqual([row["model"] for row in verify["recommended_order"]], ["deepseek-v4-pro"])
        self.assertEqual(verify["policy"]["minimum_role_quality_band"], 3)
        self.assertEqual(execute["recommended_order"][0]["model"], "gemini-2.5-pro")
        self.assertTrue(execute["recommended_order"][0]["free"])
        self.assertEqual(execute["recommended_order"][0]["role_quality_band"], 3)

    def test_frontier_role_fails_closed_without_band_four(self) -> None:
        provider = LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 1, "trial_quota")
        settings = self._settings((provider,))
        with patch.dict(os.environ, {"GEMINI_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            recommendation = recommend_route(
                settings,
                task="plan",
                prompt="规划前沿任务",
                quality_target="frontier",
            )
            with patch("smart_llm_router.router._call_openai_compatible") as call:
                with self.assertRaisesRegex(RuntimeError, "最低质量档 4"):
                    run_llm_task(
                        settings,
                        task="plan",
                        prompt="规划前沿任务",
                        quality_target="frontier",
                        privacy="external_allowed",
                    )
        self.assertEqual(recommendation["recommended_order"], [])
        call.assert_not_called()

    def test_key_rotation_is_collapsed_in_recommendations(self) -> None:
        providers = (
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "KEY_1", ("deepseek-v4-pro",), False, 1, "paid"),
            LLMProvider("deepseek-direct-paid-key2", "https://deepseek.test/v1", "KEY_2", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        with patch.dict(os.environ, {"KEY_1": "one", "KEY_2": "two"}, clear=True):
            result = recommend_route(
                self._settings(providers),
                task="execute",
                prompt="执行复杂重构",
                prefer_free=False,
                quality_target="production",
            )
        self.assertEqual([row["model"] for row in result["recommended_order"]], ["deepseek-v4-pro"])

    def test_privacy_gate_blocks_sensitive_external_call(self) -> None:
        provider = LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "KEY", ("deepseek-v4-pro",), False, 1, "paid")
        with patch.dict(os.environ, {"KEY": "test"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible") as call:
                with self.assertRaisesRegex(RuntimeError, "local_only"):
                    run_llm_task(
                        self._settings((provider,)),
                        task="vision",
                        prompt="分析这张私人照片",
                        prefer_free=False,
                    )
        call.assert_not_called()

    def test_unknown_paid_price_fails_closed_under_budget(self) -> None:
        provider = LLMProvider("unknown-paid", "https://example.test/v1", "KEY", ("unknown-pro",), False, 1, "paid")
        with patch.dict(os.environ, {"KEY": "test"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible") as call:
                with self.assertRaisesRegex(RuntimeError, "unknown_price_fails_closed"):
                    run_llm_task(
                        self._settings((provider,)),
                        task="draft",
                        prompt="执行任务",
                        prefer_free=False,
                        max_cost_usd=1.0,
                    )
        call.assert_not_called()

    def test_builtin_prices_are_available_without_env_overrides(self) -> None:
        provider = LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "KEY", ("deepseek-v4-pro",), False, 1, "paid")
        choice = LLMChoice(provider=provider, model="deepseek-v4-pro")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_price_per_million(choice, "input"), 0.435)
            self.assertEqual(_price_per_million(choice, "output"), 0.87)

    def test_budget_converts_to_model_specific_output_limit(self) -> None:
        provider = LLMProvider("gemini-frontier-paid", "https://gemini.test/v1", "KEY", ("gemini-2.5-pro",), False, 1, "paid")
        choice = LLMChoice(provider=provider, model="gemini-2.5-pro")
        limit = _max_output_tokens_for_budget(choice, input_tokens=100, max_cost_usd=0.03)
        self.assertIsNotNone(limit)
        self.assertGreater(limit, 1024)
        self.assertLessEqual(limit, 4096)

    def test_doubao_frontier_enters_text_and_vision_routes(self) -> None:
        provider = LLMProvider(
            "doubao-frontier-paid",
            "https://ark.cn-beijing.volces.com/api/v3",
            "ARK_KEY",
            ("doubao-seed-2-1-pro",),
            False,
            1,
            "trial_quota",
        )
        choice = LLMChoice(provider=provider, model="doubao-seed-2-1-pro")
        capability = describe_choice_capability(choice)
        self.assertEqual(capability["billing_class"], "trial_quota")
        self.assertIn("image", capability["input_modalities"])
        self.assertIn("plan", capability["task_types"])
        self.assertIn("vision", capability["task_types"])
        with patch.dict(os.environ, {"ARK_KEY": "test"}, clear=True):
            result = recommend_route(
                self._settings((provider,)),
                task="plan",
                prompt="规划复杂多模态任务",
                prefer_free=False,
                quality_target="frontier",
            )
        self.assertEqual(result["recommended_order"][0]["model"], "doubao-seed-2-1-pro")

    def test_paid_recommendation_skips_cooled_frontier_model(self) -> None:
        provider = LLMProvider(
            "doubao-frontier-paid",
            "https://ark.cn-beijing.volces.com/api/v3",
            "ARK_KEY",
            ("doubao-seed-2-1-pro", "doubao-seed-2-0-pro-260215"),
            False,
            1,
            "trial_quota",
        )
        with patch.dict(os.environ, {"ARK_KEY": "test"}, clear=True):
            with patch(
                "smart_llm_router.router._is_available",
                side_effect=lambda choice, states: choice.model != "doubao-seed-2-1-pro",
            ):
                result = recommend_route(
                    self._settings((provider,)),
                    task="plan",
                    prompt="规划任务",
                    prefer_free=False,
                    quality_target="production",
                )
                plan = route_plan(
                    self._settings((provider,)),
                    task="plan",
                    prompt="规划任务",
                    prefer_free=False,
                    quality_target="production",
                )
        self.assertEqual(
            [row["model"] for row in result["recommended_order"]],
            ["doubao-seed-2-0-pro-260215"],
        )
        self.assertEqual(
            [row["model"] for row in plan["paid_fallback_order"]],
            ["doubao-seed-2-0-pro-260215"],
        )

    def test_multimodal_route_selects_verified_doubao_and_independent_review(self) -> None:
        providers = (
            LLMProvider(
                "doubao-frontier-paid",
                "https://ark.test/v3",
                "ARK_KEY",
                ("doubao-seed-2-0-pro-260215",),
                False,
                1,
                "trial_quota",
            ),
            LLMProvider(
                "gemini-free",
                "https://gemini.test/v1",
                "GEMINI_KEY",
                ("gemini-2.5-pro",),
                True,
                2,
                "trial_quota",
            ),
        )
        with patch.dict(os.environ, {"ARK_KEY": "test", "GEMINI_KEY": "test"}, clear=True):
            plan = route_plan(
                self._settings(providers),
                task="vision",
                prompt="读取图片并复核",
                quality_target="frontier",
                max_cost_usd=0.05,
            )
        route = plan["multimodal_route"]
        self.assertEqual(route["selected"]["model"], "gemini-2.5-pro")
        self.assertTrue(route["selected"]["free"])
        self.assertEqual(route["review_with"]["model"], "doubao-seed-2-0-pro-260215")
        self.assertIn("doubao-seedance-2.0", route["cataloged_not_executable"]["video_generation"])


if __name__ == "__main__":
    unittest.main()
