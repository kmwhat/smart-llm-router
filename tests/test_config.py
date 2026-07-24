import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import load_settings


class ConfigTests(unittest.TestCase):
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
