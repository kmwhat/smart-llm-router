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


if __name__ == "__main__":
    unittest.main()
