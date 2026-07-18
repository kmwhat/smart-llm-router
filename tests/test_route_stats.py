import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import _append_ledger, classify_route_failure, recommend_route, route_performance_stats


class RouteStatsTests(unittest.TestCase):
    def _settings(self, providers: tuple[LLMProvider, ...] = ()) -> Settings:
        return Settings(
            data_dir=Path(tempfile.mkdtemp()),
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def _event(self, settings: Settings, **values: object) -> None:
        row = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task": "audit",
            "provider": "gemini-free",
            "model": "gemini-2.5-pro",
            "estimated_cost_usd": 0.0,
            **values,
        }
        _append_ledger(settings, row)

    def test_stats_exclude_infrastructure_failures_from_route_health(self) -> None:
        settings = self._settings()
        self._event(settings, event="model_call", latency_s=1.25)
        self._event(
            settings,
            event="model_failure",
            latency_s=0.01,
            error="[Errno 8] nodename nor servname provided, or not known",
        )
        self._event(
            settings,
            event="model_failure",
            latency_s=0.2,
            error="HTTP 429 rate limit exceeded",
        )

        report = route_performance_stats(settings, task="audit")
        route = report["routes"][0]

        self.assertEqual(route["successes"], 1)
        self.assertEqual(route["route_failures"], 1)
        self.assertEqual(route["infrastructure_failures"], 1)
        self.assertEqual(route["health_samples"], 2)
        self.assertEqual(route["success_rate"], 0.5)
        self.assertEqual(route["successful_latency_p95_s"], 1.25)
        self.assertEqual(route["failure_classes"], {"infrastructure": 1, "quota": 1})
        self.assertFalse(route["degraded"])

    def test_degraded_free_route_loses_to_healthy_paid_route_in_same_band(self) -> None:
        providers = (
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 1, "trial_quota"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        settings = self._settings(providers)
        for _ in range(3):
            self._event(settings, event="model_failure", error="HTTP 429 quota exceeded")
        self._event(
            settings,
            event="model_call",
            provider="deepseek-direct-paid",
            model="deepseek-v4-pro",
            latency_s=0.8,
        )

        with patch.dict(os.environ, {"GEMINI_KEY": "test", "DEEPSEEK_KEY": "test"}, clear=True):
            result = recommend_route(
                settings,
                task="audit",
                prompt="审计生产方案",
                quality_target="frontier",
            )

        self.assertEqual(result["recommended_order"][0]["model"], "deepseek-v4-pro")
        self.assertFalse(result["recommended_order"][0]["free"])
        self.assertTrue(result["recommended_order"][1]["history"]["degraded"])

    def test_higher_quality_band_still_wins_when_its_route_is_degraded(self) -> None:
        providers = (
            LLMProvider("qwen-frontier-paid", "https://qwen.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid"),
            LLMProvider("gemini-free", "https://gemini.test/v1", "GEMINI_KEY", ("gemini-2.5-pro",), True, 2, "trial_quota"),
        )
        settings = self._settings(providers)
        for _ in range(3):
            self._event(
                settings,
                event="model_failure",
                task="plan",
                provider="qwen-frontier-paid",
                model="qwen3.7-max",
                error="HTTP 503 provider unavailable",
            )

        with patch.dict(os.environ, {"QWEN_KEY": "test", "GEMINI_KEY": "test"}, clear=True):
            result = recommend_route(
                settings,
                task="plan",
                prompt="规划复杂生产系统",
                quality_target="frontier",
            )

        self.assertEqual(result["recommended_order"][0]["model"], "qwen3.7-max")
        self.assertEqual(result["recommended_order"][0]["role_quality_band"], 4)
        self.assertTrue(result["recommended_order"][0]["history"]["degraded"])

    def test_success_evidence_beats_an_unproven_paid_route_at_equal_price(self) -> None:
        providers = (
            LLMProvider("qwen-frontier-paid", "https://qwen.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        settings = self._settings(providers)
        self._event(
            settings,
            event="model_call",
            provider="deepseek-direct-paid",
            model="deepseek-v4-pro",
            latency_s=0.8,
        )
        env = {
            "QWEN_KEY": "test",
            "DEEPSEEK_KEY": "test",
            "SMART_LLM_PRICE_QWEN_FRONTIER_PAID_INPUT": "1",
            "SMART_LLM_PRICE_QWEN_FRONTIER_PAID_OUTPUT": "1",
            "SMART_LLM_PRICE_DEEPSEEK_DIRECT_PAID_INPUT": "1",
            "SMART_LLM_PRICE_DEEPSEEK_DIRECT_PAID_OUTPUT": "1",
        }

        with patch.dict(os.environ, env, clear=True):
            result = recommend_route(
                settings,
                task="audit",
                prompt="审计生产方案",
                prefer_free=False,
                quality_target="frontier",
            )

        self.assertEqual(result["recommended_order"][0]["model"], "deepseek-v4-pro")

    def test_failure_classifier_keeps_auth_and_timeout_distinct(self) -> None:
        self.assertEqual(classify_route_failure("HTTP 401 invalid API key"), "authentication")
        self.assertEqual(classify_route_failure("The read operation timed out"), "timeout")


if __name__ == "__main__":
    unittest.main()
