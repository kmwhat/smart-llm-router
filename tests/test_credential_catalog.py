import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import load_settings
from smart_llm_router.credential_catalog import load_model_credential_catalog


class CredentialCatalogTests(unittest.TestCase):
    def test_sectioned_catalog_does_not_blindly_activate_new_rotations(self) -> None:
        first = "fixture-" + "a" * 32
        second = "fixture-" + "b" * 32
        sample = f"""
付费模型
DeepSeek
{first}
{second}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "All_API2.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                fresh = load_model_credential_catalog(path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], first)
                self.assertNotIn("DEEPSEEK_API_KEY_2", os.environ)
            with patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": first, "DEEPSEEK_API_KEY_2": second},
                clear=True,
            ):
                retained = load_model_credential_catalog(path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], first)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY_2"], second)

        self.assertEqual(dict(fresh.key_counts), {"deepseek": 1})
        self.assertEqual(dict(retained.key_counts), {"deepseek": 2})
        self.assertEqual(fresh.billing_key_counts, (("paid", "deepseek", 2),))

    def test_sectioned_catalog_loads_active_billing_sections_and_skips_unfunded(self) -> None:
        minimax_key = "sk-" + "m" * 32
        groq_free_key = "gsk_" + "g" * 32
        groq_unfunded_key = "gsk_" + "u" * 32
        gemini_unfunded_key = "fixture-" + "x" * 32
        sample = f"""
付费模型
MiniMax
{minimax_key}
Doubao
fixture-{'d' * 32}
ep-active-001
免费模型
Groq
{groq_free_key}
付费未充值模型
Gemini
{gemini_unfunded_key}
Groq
{groq_unfunded_key}
Doubao
fixture-{'z' * 32}
ep-unfunded-001
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "All_API2.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": gemini_unfunded_key,
                    "GROQ_API_KEY": groq_free_key,
                    "GROQ_API_KEY_2": groq_unfunded_key,
                    "ARK_ENDPOINT_ID": "ep-stale-001",
                },
                clear=True,
            ):
                summary = load_model_credential_catalog(path)
                self.assertEqual(os.environ["MINIMAX_API_KEY"], minimax_key)
                self.assertEqual(os.environ["GROQ_API_KEY"], groq_free_key)
                self.assertNotIn("GROQ_API_KEY_2", os.environ)
                self.assertNotIn("GEMINI_API_KEY", os.environ)
                self.assertEqual(os.environ["ARK_ENDPOINT_ID"], "ep-active-001")

        self.assertTrue(summary.sectioned)
        self.assertEqual(dict(summary.key_counts), {"doubao": 1, "groq": 1, "minimax": 1})
        self.assertEqual(
            set(summary.billing_key_counts),
            {("free", "groq", 1), ("paid", "doubao", 1), ("paid", "minimax", 1)},
        )
        self.assertEqual(
            set(summary.skipped_key_counts),
            {("paid_unfunded", "doubao", 1), ("paid_unfunded", "gemini", 1), ("paid_unfunded", "groq", 1)},
        )
        self.assertEqual(summary.endpoint_ids, ("ep-active-001",))

    def test_sectioned_catalog_registers_minimax_only_as_paid_provider(self) -> None:
        sample = f"""
付费模型
MiniMax
sk-{'m' * 32}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "All_API2.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(credential_catalog=str(path))
        provider = next(item for item in settings.providers if item.name == "minimax-frontier-paid")
        self.assertFalse(provider.free)
        self.assertEqual(provider.billing_class, "paid")
        self.assertEqual(provider.models, ("MiniMax-M3", "MiniMax-M2.7"))

    def test_loads_only_model_provider_sections_and_multiple_keys(self) -> None:
        first = "fixture-" + "a" * 24
        second = "fixture-" + "b" * 24
        sample = f"""
DeepSeek API:
{first}
{second}
Doubao (Volcano Ark)
fixture-{"c" * 24}
接入点 ID ep-test-001
X API KEY
fixture-{"x" * 24}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "All_API.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                summary = load_model_credential_catalog(path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], first)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY_2"], second)
                self.assertEqual(os.environ["ARK_ENDPOINT_ID"], "ep-test-001")
                self.assertNotIn("X_API_KEY", os.environ)
                self.assertIn("deepseek", summary.providers)

    def test_catalog_registers_doubao_endpoint_and_key_rotation(self) -> None:
        sample = f"""
Nvidia
fixture-{"n" * 24}
fixture-{"m" * 24}
Doubao
fixture-{"d" * 24}
ep-test-002
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "All_API.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(credential_catalog=str(path))
            names = {provider.name for provider in settings.providers}
            self.assertIn("doubao-ark-paid", names)

    def test_catalog_registers_kimi_frontier_models(self) -> None:
        sample = f"""
Kimi / Moonshot
fixture-{"k" * 24}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_catalog.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(credential_catalog=str(path))
            providers = {provider.name: provider for provider in settings.providers}
            self.assertIn("kimi-frontier-paid", providers)
            self.assertIn("kimi-k3", providers["kimi-frontier-paid"].models)
            self.assertIn("kimi-k2.6", providers["kimi-frontier-paid"].models)

    def test_catalog_accepts_dotted_qwen_key_format(self) -> None:
        dotted_key = "sk-" + ".".join(("a" * 24, "b" * 24, "c" * 24, "d" * 24))
        sample = f"""
Qwen
{dotted_key}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_catalog.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                summary = load_model_credential_catalog(path)
                self.assertEqual(os.environ["DASHSCOPE_API_KEY"], dotted_key)
            self.assertEqual(dict(summary.key_counts), {"qwen": 1})

    def test_catalog_rejects_non_key_tokens_and_deduplicates_free_provider_keys(self) -> None:
        qwen_key = "sk-" + "q" * 28
        qwen_workspace_key = "sk-ws-" + "w" * 28
        openrouter_key = "sk-or-v1-" + "o" * 64
        nvidia_key = "nvapi-" + "n" * 48
        groq_key = "gsk_" + "g" * 48
        sample = f"""
Qwen
{qwen_key}
workspace-account-identifier
{qwen_workspace_key}
OpenRouter
{openrouter_key}
openrouter-management-label-identifier
NVIDIA
{nvidia_key}
nvidia-account-identifier-that-is-not-a-key
Groq
{groq_key}
{groq_key}
groq-project-identifier-that-is-not-a-key
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_catalog.txt"
            path.write_text(sample, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                summary = load_model_credential_catalog(path)
                self.assertEqual(os.environ["DASHSCOPE_API_KEY"], qwen_key)
                self.assertEqual(os.environ["DASHSCOPE_API_KEY_2"], qwen_workspace_key)
                self.assertEqual(os.environ["OPENROUTER_API_KEY"], openrouter_key)
                self.assertEqual(os.environ["NVIDIA_API_KEY"], nvidia_key)
                self.assertEqual(os.environ["GROQ_API_KEY"], groq_key)
                self.assertNotIn("OPENROUTER_API_KEY_2", os.environ)
                self.assertNotIn("NVIDIA_API_KEY_2", os.environ)
                self.assertNotIn("GROQ_API_KEY_2", os.environ)
            self.assertEqual(
                dict(summary.key_counts),
                {"qwen": 2, "openrouter": 1, "nvidia": 1, "groq": 1},
            )


if __name__ == "__main__":
    unittest.main()
