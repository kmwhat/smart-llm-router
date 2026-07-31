import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    _cache_key,
    _cached_choice_policy_status,
    run_llm_task,
)


class CachePolicyTests(unittest.TestCase):
    def _settings(self, root: str, providers: tuple[LLMProvider, ...]) -> Settings:
        return Settings(
            data_dir=Path(root),
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def _write_cache(self, root: str, key: str, **overrides: object) -> None:
        row = {
            "created_at": "2026-07-28T00:00:00+00:00",
            "provider": "legacy-free",
            "model": "legacy-model",
            "free": True,
            "content": "OLD",
        }
        row.update(overrides)
        (Path(root) / "llm_response_cache.json").write_text(
            json.dumps({key: row}),
            encoding="utf-8",
        )

    def test_cache_key_separates_external_override_and_budget(self) -> None:
        common = {
            "task": "qa",
            "prompt": "只输出 OK",
            "context": None,
            "prefer_free": True,
            "paid_fallback": False,
            "temperature": 0.2,
            "privacy": "local_only",
        }
        local_key = _cache_key(**common, allow_external=False)
        external_key = _cache_key(**common, allow_external=True)
        budget_key = _cache_key(**common, allow_external=False, max_cost_usd=0.01)
        with patch("smart_llm_router.router.CACHE_POLICY_VERSION", "cache-policy-v1"):
            legacy_policy_key = _cache_key(**common, allow_external=False)
        self.assertNotEqual(local_key, external_key)
        self.assertNotEqual(local_key, budget_key)
        self.assertNotEqual(local_key, legacy_policy_key)

    def test_current_same_policy_cache_still_hits(self) -> None:
        provider = LLMProvider(
            "current-free",
            "https://free.test/v1",
            "FREE_KEY",
            ("model-a",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"FREE_KEY": "test"}, clear=True):
                with patch("smart_llm_router.router._cache_key", return_value="same-policy"):
                    self._write_cache(
                        tmp,
                        "same-policy",
                        provider="current-free",
                        model="model-a",
                        content="CACHED",
                    )
                    with patch("smart_llm_router.router._call_openai_compatible") as call:
                        result = run_llm_task(
                            self._settings(tmp, (provider,)),
                            task="qa",
                            prompt="cache hit",
                            paid_fallback=False,
                            privacy="external_allowed",
                        )
        self.assertTrue(result.cached)
        self.assertEqual(result.content, "CACHED")
        call.assert_not_called()

    def test_removed_provider_cache_is_rejected_and_falls_back(self) -> None:
        local = LLMProvider(
            "ollama-local",
            "http://127.0.0.1:11434/v1",
            "OLLAMA_KEY",
            ("local-model",),
            True,
            0,
            "local",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OLLAMA_KEY": "local"}, clear=True):
                with patch("smart_llm_router.router._cache_key", return_value="stale"):
                    self._write_cache(tmp, "stale")
                    with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                        with patch(
                            "smart_llm_router.router._call_openai_compatible",
                            return_value=("FRESH", {}),
                        ) as call:
                            result = run_llm_task(
                                self._settings(tmp, (local,)),
                                task="qa",
                                prompt="removed provider",
                                paid_fallback=False,
                                privacy="external_allowed",
                            )
                ledger = [
                    json.loads(line)
                    for line in (Path(tmp) / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                cache = json.loads(
                    (Path(tmp) / "llm_response_cache.json").read_text(encoding="utf-8")
                )
        self.assertFalse(result.cached)
        self.assertEqual(result.provider, "ollama-local")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(ledger[0]["event"], "cache_policy_rejected")
        self.assertEqual(ledger[0]["policy_error"], "route_not_currently_configured")
        self.assertEqual(next(iter(cache.values()))["cache_policy_version"], "cache-policy-v2")
        self.assertEqual(next(iter(cache.values()))["billing_class"], "local")
        self.assertEqual(next(iter(cache.values()))["privacy"], "external_allowed")
        self.assertFalse(next(iter(cache.values()))["allow_external"])

    def test_reclassified_paid_route_is_not_returned_to_free_only(self) -> None:
        paid = LLMProvider(
            "legacy-free",
            "https://paid.test/v1",
            "PAID_KEY",
            ("legacy-model",),
            False,
            1,
            "paid",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"PAID_KEY": "test"}, clear=True):
                with patch("smart_llm_router.router._cache_key", return_value="stale"):
                    self._write_cache(tmp, "stale")
                    with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                        with patch("smart_llm_router.router._maybe_refresh_when_free_pool_empty", return_value={}):
                            with patch("smart_llm_router.router._call_openai_compatible") as call:
                                with self.assertRaisesRegex(RuntimeError, "没有可用模型"):
                                    run_llm_task(
                                        self._settings(tmp, (paid,)),
                                        task="qa",
                                        prompt="free only",
                                        paid_fallback=False,
                                        privacy="external_allowed",
                                    )
                ledger = [
                    json.loads(line)
                    for line in (Path(tmp) / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                ]
        call.assert_not_called()
        self.assertEqual(ledger[0]["policy_error"], "paid_route_not_allowed")

    def test_local_only_rejects_external_cache_and_uses_loopback(self) -> None:
        remote = LLMProvider(
            "remote-free",
            "https://free.test/v1",
            "REMOTE_KEY",
            ("remote-model",),
            True,
            1,
            "permanent_free",
        )
        local = LLMProvider(
            "ollama-local",
            "http://127.0.0.1:11434/v1",
            "OLLAMA_KEY",
            ("local-model",),
            True,
            0,
            "local",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"REMOTE_KEY": "test", "OLLAMA_KEY": "local"},
                clear=True,
            ):
                with patch("smart_llm_router.router._cache_key", return_value="stale"):
                    self._write_cache(
                        tmp,
                        "stale",
                        provider="remote-free",
                        model="remote-model",
                    )
                    with patch(
                        "smart_llm_router.router._call_openai_compatible",
                        return_value=("LOCAL", {}),
                    ) as call:
                        result = run_llm_task(
                            self._settings(tmp, (local, remote)),
                            task="qa",
                            prompt="private",
                            paid_fallback=False,
                            privacy="local_only",
                        )
                ledger = [
                    json.loads(line)
                    for line in (Path(tmp) / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                ]
        self.assertFalse(result.cached)
        self.assertEqual(result.provider, "ollama-local")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(ledger[0]["event"], "cache_policy_rejected")
        self.assertEqual(ledger[0]["policy_error"], "local_only_route_mismatch")

    def test_provider_filter_revalidates_cached_origin(self) -> None:
        remote = LLMProvider(
            "remote-free",
            "https://free.test/v1",
            "REMOTE_KEY",
            ("remote-model",),
            True,
            1,
            "permanent_free",
        )
        local = LLMProvider(
            "ollama-local",
            "http://127.0.0.1:11434/v1",
            "OLLAMA_KEY",
            ("local-model",),
            True,
            0,
            "local",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"REMOTE_KEY": "test", "OLLAMA_KEY": "local"},
                clear=True,
            ):
                with patch("smart_llm_router.router._cache_key", return_value="stale"):
                    self._write_cache(
                        tmp,
                        "stale",
                        provider="remote-free",
                        model="remote-model",
                    )
                    with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                        with patch(
                            "smart_llm_router.router._call_openai_compatible",
                            return_value=("LOCAL", {}),
                        ) as call:
                            result = run_llm_task(
                                self._settings(tmp, (local, remote)),
                                task="qa",
                                prompt="provider filter",
                                provider="ollama-local",
                                paid_fallback=False,
                                privacy="external_allowed",
                            )
                ledger = [
                    json.loads(line)
                    for line in (Path(tmp) / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                ]
        self.assertFalse(result.cached)
        self.assertEqual(result.provider, "ollama-local")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(ledger[0]["event"], "cache_policy_rejected")
        self.assertEqual(ledger[0]["policy_error"], "provider_filter_mismatch")

    def test_free_only_revalidates_current_eligibility(self) -> None:
        provider = LLMProvider(
            "current-free",
            "https://free.test/v1",
            "FREE_KEY",
            ("model-a",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"FREE_KEY": "test"}, clear=True):
                with patch(
                    "smart_llm_router.router._free_only_eligible_provider",
                    return_value=False,
                ):
                    choice, reason = _cached_choice_policy_status(
                        self._settings(tmp, (provider,)),
                        {"provider": "current-free", "model": "model-a"},
                        task="qa",
                        prefer_free=True,
                        paid_fallback=False,
                        provider=None,
                        model=None,
                        quality_target="production",
                        privacy="external_allowed",
                        allow_external=False,
                        max_cost_usd=None,
                        input_tokens=128,
                    )
        self.assertIsNone(choice)
        self.assertEqual(reason, "free_route_not_currently_eligible")

    def test_model_filter_revalidates_cached_origin(self) -> None:
        provider = LLMProvider(
            "current-free",
            "https://free.test/v1",
            "FREE_KEY",
            ("model-a",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"FREE_KEY": "test"}, clear=True):
                choice, reason = _cached_choice_policy_status(
                    self._settings(tmp, (provider,)),
                    {"provider": "current-free", "model": "model-a"},
                    task="qa",
                    prefer_free=True,
                    paid_fallback=False,
                    provider=None,
                    model="model-b",
                    quality_target="production",
                    privacy="external_allowed",
                    allow_external=False,
                    max_cost_usd=None,
                    input_tokens=128,
                )
        self.assertIsNone(choice)
        self.assertEqual(reason, "model_filter_mismatch")

    def test_role_quality_floor_revalidates_cached_origin(self) -> None:
        provider = LLMProvider(
            "current-free",
            "https://free.test/v1",
            "FREE_KEY",
            ("openai/gpt-oss-120b",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"FREE_KEY": "test"}, clear=True):
                choice, reason = _cached_choice_policy_status(
                    self._settings(tmp, (provider,)),
                    {
                        "provider": "current-free",
                        "model": "openai/gpt-oss-120b",
                    },
                    task="verify",
                    prefer_free=True,
                    paid_fallback=False,
                    provider=None,
                    model=None,
                    quality_target="production",
                    privacy="external_allowed",
                    allow_external=False,
                    max_cost_usd=None,
                    input_tokens=128,
                )
        self.assertIsNone(choice)
        self.assertEqual(reason, "quality_floor_mismatch")

    def test_budget_gate_revalidates_cached_origin(self) -> None:
        provider = LLMProvider(
            "current-paid",
            "https://paid.test/v1",
            "PAID_KEY",
            ("deepseek-v4-pro",),
            False,
            1,
            "paid",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"PAID_KEY": "test"}, clear=True):
                choice, reason = _cached_choice_policy_status(
                    self._settings(tmp, (provider,)),
                    {"provider": "current-paid", "model": "deepseek-v4-pro"},
                    task="qa",
                    prefer_free=False,
                    paid_fallback=True,
                    provider=None,
                    model=None,
                    quality_target="production",
                    privacy="external_allowed",
                    allow_external=False,
                    max_cost_usd=0.0,
                    input_tokens=128,
                )
        self.assertIsNone(choice)
        self.assertEqual(reason, "budget_gate:projected_cost_exceeds_limit")


if __name__ == "__main__":
    unittest.main()
