import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_stale_environment_catalog_is_reported_without_blocking_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "moved-catalog.txt"
            with patch.dict(
                os.environ,
                {"SMART_LLM_CREDENTIAL_CATALOG": str(missing)},
                clear=True,
            ):
                settings = load_settings()

        self.assertIsNone(settings.credential_catalog)
        self.assertEqual(
            settings.configuration_warnings,
            (f"credential_catalog_missing:{missing}",),
        )

    def test_missing_explicit_catalog_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-catalog.txt"
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(FileNotFoundError, "credential catalog not found"):
                    load_settings(credential_catalog=str(missing))

    def test_process_environment_overrides_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "SMART_LLM_RUNTIME_DIR=/from/env-file\n"
                "SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED=true\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "SMART_LLM_RUNTIME_DIR": "/from/process",
                    "SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED": "false",
                },
                clear=True,
            ):
                settings = load_settings(str(env_file))
                activation = os.environ["SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED"]
            self.assertEqual(settings.data_dir, Path("/from/process"))
            self.assertEqual(activation, "false")

    def test_runtime_dir_overrides_legacy_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            with patch.dict(
                os.environ,
                {
                    "SMART_LLM_RUNTIME_DIR": str(runtime),
                    "SMART_LLM_DATA_DIR": str(root / "legacy"),
                },
                clear=False,
            ):
                settings = load_settings()
            self.assertEqual(settings.data_dir, runtime)
            self.assertTrue(settings.auto_discover_free)
            self.assertEqual(settings.discovery_ttl_hours, 6.0)
            self.assertEqual(settings.discovery_limit, 20)
            self.assertEqual(settings.health_ttl_hours, 1.0)

    def test_budget_authority_does_not_follow_runtime_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(
                os.environ,
                {"HOME": str(root), "SMART_LLM_RUNTIME_DIR": str(root / "runtime-a")},
                clear=True,
            ):
                first = load_settings()
            with patch.dict(
                os.environ,
                {"HOME": str(root), "SMART_LLM_RUNTIME_DIR": str(root / "runtime-b")},
                clear=True,
            ):
                second = load_settings()
        self.assertNotEqual(first.data_dir, second.data_dir)
        self.assertEqual(first.budget_authority_dir, second.budget_authority_dir)
        self.assertEqual(first.budget_authority_dir, root / ".smart-llm-router" / "budget-authority")

    def test_paid_keys_register_supported_provider_modes_and_free_gemini(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test",
                "ZHIPU_API_KEY": "test",
                "DASHSCOPE_API_KEY": "test",
                "KIMI_API_KEY": "test",
                "GEMINI_API_KEY": "test",
                "ARK_API_KEY": "test",
            },
            clear=True,
        ):
            settings = load_settings()
        names = {provider.name for provider in settings.providers}
        self.assertIn("deepseek-direct-paid", names)
        self.assertIn("zhipu-vision-paid", names)
        self.assertIn("zhipu-asr-paid", names)
        self.assertIn("zhipu-image-paid", names)
        self.assertIn("qwen-asr-paid", names)
        self.assertIn("qwen-rerank-paid", names)
        self.assertIn("qwen-mm-embedding-paid", names)
        self.assertIn("qwen-frontier-paid", names)
        self.assertIn("kimi-frontier-paid", names)
        self.assertIn("gemini-free", names)
        self.assertNotIn("gemini-frontier-paid", names)
        self.assertIn("doubao-frontier-paid", names)

    def test_gemini_paid_provider_requires_explicit_billing_opt_in(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test",
                "SMART_LLM9_NAME": "gemini-paid",
                "SMART_LLM9_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
                "SMART_LLM9_API_KEY_ENV": "GEMINI_API_KEY",
                "SMART_LLM9_MODELS": "gemini-2.5-flash",
                "SMART_LLM9_FREE": "false",
            },
            clear=True,
        ):
            free_settings = load_settings()
            self.assertNotIn("gemini-paid", {provider.name for provider in free_settings.providers})
            self.assertIn("gemini-free", {provider.name for provider in free_settings.providers})

        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test", "SMART_LLM_GEMINI_PAID_ENABLED": "true"},
            clear=True,
        ):
            paid_settings = load_settings()
        self.assertIn("gemini-frontier-paid", {provider.name for provider in paid_settings.providers})

    def test_groq_defaults_to_trial_quota_not_permanent_free(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test",
                "SMART_LLM1_NAME": "groq-free",
                "SMART_LLM1_BASE_URL": "https://api.groq.com/openai/v1",
                "SMART_LLM1_API_KEY_ENV": "GROQ_API_KEY",
                "SMART_LLM1_MODELS": "qwen/qwen3.6-27b",
                "SMART_LLM1_FREE": "true",
            },
            clear=True,
        ):
            settings = load_settings()
        provider = next(item for item in settings.providers if item.name == "groq-free")
        self.assertEqual(provider.billing_class, "trial_quota")
        self.assertFalse(provider.trial_quota_guarded)

    @patch("smart_llm_router.config.load_dotenv")
    def test_trial_quota_guard_requires_explicit_provider_opt_in(self, _load_dotenv: object) -> None:
        base = {
            "DASHSCOPE_API_KEY": "test",
            "SMART_LLM1_NAME": "qwen-free",
            "SMART_LLM1_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "SMART_LLM1_API_KEY_ENV": "DASHSCOPE_API_KEY",
            "SMART_LLM1_MODELS": "qwen-plus-latest",
            "SMART_LLM1_FREE": "true",
            "SMART_LLM1_BILLING_CLASS": "trial_quota",
        }
        with patch.dict(os.environ, base, clear=True):
            unguarded = load_settings()
        provider = next(item for item in unguarded.providers if item.name == "qwen-free")
        self.assertFalse(provider.trial_quota_guarded)

        with patch.dict(
            os.environ,
            {
                **base,
                "DASHSCOPE_API_KEY_2": "test-2",
                "SMART_LLM1_TRIAL_QUOTA_GUARDED": "true",
            },
            clear=True,
        ):
            guarded = load_settings()
        guarded_routes = [
            item
            for item in guarded.providers
            if item.name in {"qwen-free", "qwen-free-key2"}
        ]
        self.assertEqual(len(guarded_routes), 2)
        self.assertTrue(all(item.trial_quota_guarded for item in guarded_routes))

    def test_private_legacy_namespace_is_not_loaded_by_public_core(self) -> None:
        legacy_prefix = "FENG" + "SHUI"
        with patch.dict(
            os.environ,
            {
                f"{legacy_prefix}_LLM1_NAME": "private-route",
                f"{legacy_prefix}_LLM1_BASE_URL": "https://private.example/v1",
                f"{legacy_prefix}_LLM1_API_KEY_ENV": "PRIVATE_KEY",
                f"{legacy_prefix}_LLM1_MODELS": "private-model",
                "PRIVATE_KEY": "test",
            },
            clear=True,
        ):
            settings = load_settings()
        self.assertNotIn("private-route", {provider.name for provider in settings.providers})


if __name__ == "__main__":
    unittest.main()
