import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    LLMChoice,
    _load_route_state,
    _record_failure,
    _record_success,
    recommend_route,
    route_status,
)


class HealthSemanticsTests(unittest.TestCase):
    def _settings(self, root: str, providers: tuple[LLMProvider, ...]) -> Settings:
        return Settings(
            data_dir=Path(root),
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            health_ttl_hours=1,
        )

    def test_unknown_is_not_reported_available_but_remains_probe_eligible(self) -> None:
        provider = LLMProvider(
            "qwen-free",
            "https://example.test/v1",
            "QWEN_KEY",
            ("qwen-test",),
            True,
            1,
            "trial_quota",
            True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, (provider,))
            with patch.dict(os.environ, {"QWEN_KEY": "test"}, clear=False):
                row = route_status(settings)[0]

        self.assertEqual(row["health_status"], "unknown")
        self.assertEqual(row["health_evidence"], "no_recent_success")
        self.assertFalse(row["available_now"])
        self.assertTrue(row["routing_eligible"])
        self.assertTrue(row["catalog_declared"])
        self.assertTrue(row["execution_eligible"])

    def test_recent_success_is_healthy_and_stale_success_returns_to_unknown(self) -> None:
        provider = LLMProvider(
            "qwen-free",
            "https://example.test/v1",
            "QWEN_KEY",
            ("qwen-test",),
            True,
            1,
            "trial_quota",
            True,
        )
        choice = LLMChoice(provider, "qwen-test")
        observed_at = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, (provider,))
            with patch.dict(os.environ, {"QWEN_KEY": "test"}, clear=False):
                with patch("smart_llm_router.router._now", return_value=observed_at):
                    states = _load_route_state(settings)
                    _record_success(settings, choice, states)
                    healthy = route_status(settings)[0]
                with patch(
                    "smart_llm_router.router._now",
                    return_value=observed_at + timedelta(hours=2),
                ):
                    stale = route_status(settings)[0]

        self.assertEqual(healthy["health_status"], "healthy")
        self.assertTrue(healthy["available_now"])
        self.assertEqual(stale["health_status"], "unknown")
        self.assertFalse(stale["available_now"])
        self.assertTrue(stale["routing_eligible"])

    def test_active_cooldown_is_unhealthy_and_expiry_does_not_restore_health(self) -> None:
        provider = LLMProvider(
            "qwen-free",
            "https://example.test/v1",
            "QWEN_KEY",
            ("qwen-test",),
            True,
            1,
            "trial_quota",
            True,
        )
        choice = LLMChoice(provider, "qwen-test")
        success_at = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
        failure_at = success_at + timedelta(minutes=5)
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, (provider,))
            with patch.dict(os.environ, {"QWEN_KEY": "test"}, clear=False):
                states = _load_route_state(settings)
                with patch("smart_llm_router.router._now", return_value=success_at):
                    _record_success(settings, choice, states)
                with patch("smart_llm_router.router._now", return_value=failure_at):
                    _record_failure(settings, choice, states, RuntimeError("429 quota"))
                    unhealthy = route_status(settings)[0]
                with patch(
                    "smart_llm_router.router._now",
                    return_value=failure_at + timedelta(hours=5),
                ):
                    expired = route_status(settings)[0]

        self.assertEqual(unhealthy["health_status"], "unhealthy")
        self.assertFalse(unhealthy["routing_eligible"])
        self.assertEqual(expired["health_status"], "unknown")
        self.assertEqual(expired["health_evidence"], "failed_since_last_success")
        self.assertTrue(expired["routing_eligible"])
        self.assertFalse(expired["available_now"])

    def test_success_in_same_runtime_clears_cooldown_and_refreshes_health(self) -> None:
        provider = LLMProvider(
            "openrouter-vision-free",
            "https://example.test/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        choice = LLMChoice(provider, provider.models[0])
        failure_at = datetime(2026, 8, 7, 1, tzinfo=timezone.utc)
        success_at = failure_at + timedelta(minutes=1)
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, (provider,))
            with patch.dict(os.environ, {"OPENROUTER_KEY": "test"}, clear=False):
                states = _load_route_state(settings)
                with patch("smart_llm_router.router._now", return_value=failure_at):
                    _record_failure(settings, choice, states, RuntimeError("synthetic timeout"))
                with patch("smart_llm_router.router._now", return_value=success_at):
                    _record_success(settings, choice, states)
                    row = route_status(settings)[0]

            persisted_states = _load_route_state(settings)

        self.assertEqual(persisted_states, {})
        self.assertEqual(row["health_status"], "healthy")
        self.assertEqual(row["health_evidence"], "recent_success")
        self.assertEqual(row["failure_count"], 0)
        self.assertIsNone(row["unavailable_until"])

    def test_health_semantics_do_not_promote_local_above_remote(self) -> None:
        remote = LLMProvider(
            "qwen-free",
            "https://example.test/v1",
            "QWEN_KEY",
            ("qwen-test",),
            True,
            1,
            "trial_quota",
            True,
        )
        local = LLMProvider(
            "ollama-qwen-local",
            "http://127.0.0.1:11434/v1",
            "OLLAMA_LOCAL_API_KEY",
            ("qwen3.5:4b-q4_K_M",),
            True,
            0,
            "local",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, (local, remote))
            with patch.dict(
                os.environ,
                {"QWEN_KEY": "test", "OLLAMA_LOCAL_API_KEY": "ollama"},
                clear=False,
            ):
                result = recommend_route(
                    settings,
                    task="qa",
                    prompt="只输出 OK",
                    paid_fallback=False,
                )

        self.assertEqual(
            [row["provider"] for row in result["recommended_order"]],
            ["qwen-free", "ollama-qwen-local"],
        )
        self.assertTrue(all(row["health_status"] == "unknown" for row in result["recommended_order"]))
        self.assertTrue(all(row["routing_eligible"] for row in result["recommended_order"]))
        self.assertTrue(all(row["execution_eligible"] for row in result["recommended_order"]))

    def test_unguarded_trial_quota_is_visible_but_not_executable_or_free_only(self) -> None:
        trial = LLMProvider(
            "qwen-free",
            "https://example.test/v1",
            "QWEN_KEY",
            ("qwen-test",),
            True,
            1,
            "trial_quota",
        )
        permanent = LLMProvider(
            "openrouter-free",
            "https://openrouter.test/v1",
            "OPENROUTER_KEY",
            ("openrouter/free",),
            True,
            2,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, (trial, permanent))
            with patch.dict(
                os.environ,
                {"QWEN_KEY": "test", "OPENROUTER_KEY": "test"},
                clear=False,
            ):
                status = route_status(settings)
                result = recommend_route(
                    settings,
                    task="qa",
                    prompt="只输出 OK",
                    paid_fallback=False,
                )

        by_provider = {row["provider"]: row for row in status}
        self.assertFalse(by_provider["qwen-free"]["execution_eligible"])
        self.assertTrue(by_provider["openrouter-free"]["execution_eligible"])
        self.assertEqual(
            [row["provider"] for row in result["recommended_order"]],
            ["openrouter-free"],
        )


if __name__ == "__main__":
    unittest.main()
