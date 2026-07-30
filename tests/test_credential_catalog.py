import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import load_settings
from smart_llm_router.credential_catalog import load_model_credential_catalog


class CredentialCatalogTests(unittest.TestCase):
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
