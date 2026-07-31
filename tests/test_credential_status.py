import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import credential_status, discover_free_pool


class CredentialStatusTests(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            data_dir=root,
            providers=(
                LLMProvider(
                    "openrouter-free",
                    "https://openrouter.ai/api/v1",
                    "OPENROUTER_API_KEY",
                    ("openrouter/free",),
                    True,
                    1,
                    "permanent_free",
                ),
                LLMProvider(
                    "openrouter-disabled-free",
                    "https://openrouter.ai/api/v1",
                    "DISABLED_OPENROUTER_API_KEY",
                    ("disabled/model:free",),
                    True,
                    2,
                    "permanent_free",
                ),
                LLMProvider(
                    "qwen-free",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "DASHSCOPE_API_KEY",
                    ("qwen-flash",),
                    True,
                    2,
                    "trial_quota",
                ),
                LLMProvider(
                    "nvidia-free",
                    "https://integrate.api.nvidia.com/v1",
                    "NVIDIA_API_KEY",
                    ("nvidia/model",),
                    True,
                    3,
                    "trial_quota",
                ),
                LLMProvider(
                    "nvidia-free-key2",
                    "https://integrate.api.nvidia.com/v1",
                    "NVIDIA_API_KEY_2",
                    ("nvidia/model",),
                    True,
                    4,
                    "trial_quota",
                ),
                LLMProvider(
                    "groq-free",
                    "https://api.groq.com/openai/v1",
                    "GROQ_API_KEY",
                    ("groq/model",),
                    True,
                    5,
                    "trial_quota",
                ),
                LLMProvider(
                    "ollama-local",
                    "http://127.0.0.1:11434/v1",
                    "OLLAMA_API_KEY",
                    ("local/model",),
                    True,
                    8,
                    "local",
                ),
                LLMProvider(
                    "deepseek-paid",
                    "https://api.deepseek.com",
                    "DEEPSEEK_API_KEY",
                    ("deepseek/model",),
                    False,
                    9,
                    "paid",
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def test_checks_each_free_remote_credential_without_model_or_paid_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp))
            response_401 = Mock(status_code=401)
            response_400 = Mock(status_code=400)

            def fake_get(url: str, **_: object) -> Mock:
                if "groq.com" in url:
                    raise httpx.ConnectTimeout("timed out")
                return response_401

            with patch.dict(
                os.environ,
                {
                    "OPENROUTER_API_KEY": "orx",
                    "DASHSCOPE_API_KEY": "qwx",
                    "NVIDIA_API_KEY": "nvx1",
                    "NVIDIA_API_KEY_2": "nvx2",
                    "GROQ_API_KEY": "grx",
                    "DEEPSEEK_API_KEY": "dpx",
                    "OLLAMA_API_KEY": "olx",
                },
                clear=True,
            ):
                with patch("smart_llm_router.router.httpx.Client") as client_class:
                    client = client_class.return_value.__enter__.return_value
                    client.get.side_effect = fake_get
                    client.post.return_value = response_400
                    result = credential_status(settings, timeout=3)

        by_slot = {row["credential_slot"]: row for row in result["results"]}
        self.assertEqual(by_slot["OPENROUTER_API_KEY"]["credential_status"], "rejected")
        self.assertEqual(by_slot["DASHSCOPE_API_KEY"]["credential_status"], "rejected")
        self.assertEqual(by_slot["NVIDIA_API_KEY"]["credential_status"], "indeterminate")
        self.assertIsNone(by_slot["NVIDIA_API_KEY"]["credential_accepted"])
        self.assertEqual(by_slot["NVIDIA_API_KEY"]["evidence_scope"], "request_validation_only")
        self.assertEqual(by_slot["NVIDIA_API_KEY_2"]["credential_status"], "indeterminate")
        self.assertIsNone(by_slot["NVIDIA_API_KEY_2"]["credential_accepted"])
        self.assertEqual(by_slot["NVIDIA_API_KEY_2"]["evidence_scope"], "request_validation_only")
        self.assertEqual(by_slot["GROQ_API_KEY"]["credential_status"], "network_error")
        self.assertNotIn("DEEPSEEK_API_KEY", by_slot)
        self.assertNotIn("OLLAMA_API_KEY", by_slot)
        self.assertNotIn("DISABLED_OPENROUTER_API_KEY", by_slot)
        self.assertEqual(result["summary"]["accepted"], 0)
        self.assertEqual(result["summary"]["indeterminate"], 2)
        self.assertEqual(result["summary"]["model_calls"], 0)
        self.assertEqual(result["summary"]["paid_calls"], 0)
        rendered = json.dumps(result)
        for secret in ("orx", "qwx", "nvx", "grx", "dpx", "olx"):
            self.assertNotIn(secret, rendered)

    def test_nvidia_401_and_403_remain_distinct_from_request_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp))
            response_401 = Mock(status_code=401)
            response_403 = Mock(status_code=403)
            with patch.dict(
                os.environ,
                {
                    "NVIDIA_API_KEY": "nvx1",
                    "NVIDIA_API_KEY_2": "nvx2",
                },
                clear=True,
            ):
                with patch("smart_llm_router.router.httpx.Client") as client_class:
                    client = client_class.return_value.__enter__.return_value
                    client.post.side_effect = [response_401, response_403]
                    result = credential_status(settings, families=["nvidia"], timeout=3)

        by_slot = {row["credential_slot"]: row for row in result["results"]}
        self.assertEqual(by_slot["NVIDIA_API_KEY"]["credential_status"], "rejected")
        self.assertFalse(by_slot["NVIDIA_API_KEY"]["credential_accepted"])
        self.assertEqual(by_slot["NVIDIA_API_KEY_2"]["credential_status"], "permission_denied")
        self.assertIsNone(by_slot["NVIDIA_API_KEY_2"]["credential_accepted"])

    def test_rejects_unsupported_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "不支持的凭证检查"):
                credential_status(self._settings(Path(tmp)), families=["deepseek"])

    def test_discovery_labels_public_catalogs_as_not_credential_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp))
            with patch("smart_llm_router.router.discover_openrouter_free", return_value=[]):
                with patch("smart_llm_router.router.discover_nvidia_models", return_value=[]):
                    with patch("smart_llm_router.router.discover_openrouter_vision_free", return_value=[]):
                        with patch("smart_llm_router.router.discover_nvidia_vision_models", return_value=[]):
                            with patch("smart_llm_router.router.discover_groq_models", return_value=[]):
                                result = discover_free_pool(settings, limit=1)

        self.assertEqual(result["openrouter"]["catalog_access"], "public")
        self.assertFalse(result["openrouter"]["credential_validated"])
        self.assertEqual(result["nvidia"]["catalog_access"], "public")
        self.assertFalse(result["nvidia"]["credential_validated"])
        self.assertEqual(result["groq"]["catalog_access"], "authenticated")
        self.assertTrue(result["groq"]["credential_validated"])


if __name__ == "__main__":
    unittest.main()
