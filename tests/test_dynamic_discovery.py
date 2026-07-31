import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    _load_route_state,
    _model_choices,
    _record_discovered_free_models,
    _record_success,
    discover_nvidia_models,
    run_llm_task,
)


class DynamicDiscoveryTests(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            data_dir=root,
            providers=(
                LLMProvider(
                    "openrouter-vision-free",
                    "https://openrouter.test/api/v1",
                    "OPENROUTER_API_KEY",
                    ("vision/model:free",),
                    True,
                    0,
                    "permanent_free",
                ),
                LLMProvider(
                    "openrouter-router-free",
                    "https://openrouter.test/api/v1",
                    "OPENROUTER_API_KEY",
                    ("openrouter/free",),
                    True,
                    1,
                    "permanent_free",
                ),
                LLMProvider(
                    "groq-free",
                    "https://groq.test/openai/v1",
                    "GROQ_API_KEY",
                    ("llama-3.1-8b-instant",),
                    True,
                    2,
                    "trial_quota",
                    True,
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            auto_discover_free=True,
            discovery_ttl_hours=6,
            discovery_limit=20,
        )

    def test_partial_discovery_retains_untouched_provider_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp))
            _record_discovered_free_models(
                settings,
                {
                    "openrouter": [{"id": "old/openrouter:free"}],
                    "groq": [{"id": "old-groq"}],
                },
            )
            families = _record_discovered_free_models(
                settings,
                {"openrouter": [{"id": "new/openrouter:free"}]},
            )

        self.assertEqual([row["id"] for row in families["openrouter"]], ["new/openrouter:free"])
        self.assertEqual([row["id"] for row in families["groq"]], ["old-groq"])

    def test_stale_snapshot_discovery_requires_successful_probe_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp))

            def discover(current: Settings, limit: int) -> dict:
                self.assertEqual(limit, 20)
                _record_discovered_free_models(
                    current,
                    {"openrouter": [{"id": "new/model:free", "free_signal": ":free suffix"}]},
                )
                return {"openrouter": {"ok": True, "models": [{"id": "new/model:free"}]}}

            with patch.dict(
                os.environ,
                {
                    "OPENROUTER_API_KEY": "test",
                    "GROQ_API_KEY": "test",
                    "SMART_LLM_CACHE": "false",
                },
                clear=True,
            ):
                with patch("smart_llm_router.router.discover_free_pool", side_effect=discover) as discovery:
                    with patch("smart_llm_router.router._call_openai_compatible", return_value=("OK", {})):
                        with self.assertRaisesRegex(RuntimeError, "没有匹配"):
                            run_llm_task(
                                settings,
                                task="qa",
                                prompt="只输出 OK",
                                provider="openrouter",
                                model="new/model:free",
                                paid_fallback=False,
                                privacy="external_allowed",
                            )
                        discovered_choice = next(
                            choice
                            for choice in _model_choices(settings, task="qa", only_free=True)
                            if choice.model == "new/model:free"
                        )
                        _record_success(
                            settings,
                            discovered_choice,
                            _load_route_state(settings),
                        )
                        result = run_llm_task(
                            settings,
                            task="qa",
                            prompt="只输出 OK",
                            provider="openrouter",
                            model="new/model:free",
                            paid_fallback=False,
                            privacy="external_allowed",
                        )
                        run_llm_task(
                            settings,
                            task="qa",
                            prompt="再输出 OK",
                            provider="openrouter",
                            model="new/model:free",
                            paid_fallback=False,
                            privacy="external_allowed",
                        )

            snapshot = json.loads((settings.data_dir / "llm_discovered_free_models.json").read_text(encoding="utf-8"))

        self.assertEqual(result.model, "new/model:free")
        self.assertEqual(result.provider, "openrouter-router-free")
        self.assertEqual(discovery.call_count, 1)
        self.assertEqual(snapshot["families"]["openrouter"][0]["id"], "new/model:free")

    def test_groq_specialized_models_do_not_enter_general_qa_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp))
            _record_discovered_free_models(
                settings,
                {
                    "groq": [
                        {"id": "whisper-large-v3"},
                        {"id": "canopylabs/orpheus-v1-english"},
                        {"id": "meta-llama/llama-prompt-guard-2-86m"},
                        {"id": "qwen/qwen3.6-27b"},
                    ]
                },
            )
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test", "GROQ_API_KEY": "test"}, clear=True):
                models = [choice.model for choice in _model_choices(settings, task="qa", only_free=True)]

        self.assertIn("qwen/qwen3.6-27b", models)
        self.assertNotIn("whisper-large-v3", models)
        self.assertNotIn("canopylabs/orpheus-v1-english", models)
        self.assertNotIn("meta-llama/llama-prompt-guard-2-86m", models)

    def test_nvidia_discovery_filters_specialists_before_applying_limit(self) -> None:
        payload = {
            "data": [
                {"id": "nvidia/nemotron-3-embed-1b"},
                {"id": "nvidia/nemotron-3.5-content-safety"},
                {"id": "meta/llama-3.2-11b-vision-instruct"},
                {"id": "nvidia/nemotron-3-nano-30b-a3b"},
                {"id": "openai/gpt-oss-120b"},
            ]
        }
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                response = client.return_value.__enter__.return_value.get.return_value
                response.json.return_value = payload
                rows = discover_nvidia_models(limit=2)

        self.assertEqual(
            [row["id"] for row in rows],
            ["nvidia/nemotron-3-nano-30b-a3b", "openai/gpt-oss-120b"],
        )
        self.assertTrue(all(row["billing_class"] == "trial_quota" for row in rows))

    def test_discovered_nvidia_models_use_credential_rotation_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                data_dir=Path(tmp),
                providers=(
                    LLMProvider(
                        "nvidia-free",
                        "https://integrate.api.nvidia.test/v1",
                        "NVIDIA_API_KEY",
                        ("old/model",),
                        True,
                        1,
                        "trial_quota",
                        True,
                    ),
                    LLMProvider(
                        "nvidia-free-key2",
                        "https://integrate.api.nvidia.test/v1",
                        "NVIDIA_API_KEY_2",
                        ("old/model",),
                        True,
                        2,
                        "trial_quota",
                        True,
                    ),
                ),
                timeout=5,
                empty_pool_refresh_timeout=1,
                empty_pool_refresh_limit=1,
            )
            _record_discovered_free_models(
                settings,
                {"nvidia": [{"id": "nvidia/nemotron-3-nano-30b-a3b"}]},
            )
            with patch.dict(
                os.environ,
                {"NVIDIA_API_KEY": "first", "NVIDIA_API_KEY_2": "second"},
                clear=True,
            ):
                choices = [
                    choice
                    for choice in _model_choices(settings, task="qa", only_free=True)
                    if choice.model == "nvidia/nemotron-3-nano-30b-a3b"
                ]

        self.assertEqual(
            [choice.provider.name for choice in choices],
            ["nvidia-free", "nvidia-free-key2"],
        )


if __name__ == "__main__":
    unittest.main()
