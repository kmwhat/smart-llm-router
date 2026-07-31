import os
import unittest
from unittest.mock import patch

from smart_llm_router.config import LLMProvider
from smart_llm_router.router import LLMChoice, _call_openai_compatible, _messages_for_task


class OllamaCompatibilityTests(unittest.TestCase):
    def _choice(self, provider: LLMProvider) -> LLMChoice:
        return LLMChoice(provider=provider, model=provider.models[0])

    def test_local_ollama_disables_reasoning_by_default(self) -> None:
        provider = LLMProvider(
            "ollama-local",
            "http://127.0.0.1:11434/v1",
            "OLLAMA_LOCAL_API_KEY",
            ("qwen3.5:4b-q4_K_M",),
            True,
            0,
            "local",
        )
        with patch.dict(os.environ, {"OLLAMA_LOCAL_API_KEY": "ollama"}, clear=False):
            with patch("smart_llm_router.router.httpx.Client") as client:
                response = client.return_value.__enter__.return_value.post.return_value
                response.json.return_value = {
                    "choices": [{"message": {"content": "OK"}}],
                    "usage": {},
                }
                content, _usage = _call_openai_compatible(
                    self._choice(provider),
                    messages=[{"role": "user", "content": "只输出 OK"}],
                    timeout=10,
                    temperature=0,
                )

        self.assertEqual(content, "OK")
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning_effort"], "none")

    def test_remote_provider_does_not_receive_ollama_reasoning_control(self) -> None:
        provider = LLMProvider(
            "qwen-free",
            "https://example.test/v1",
            "QWEN_API_KEY",
            ("qwen-test",),
            True,
            1,
            "trial_quota",
        )
        with patch.dict(os.environ, {"QWEN_API_KEY": "test"}, clear=False):
            with patch("smart_llm_router.router.httpx.Client") as client:
                response = client.return_value.__enter__.return_value.post.return_value
                response.json.return_value = {
                    "choices": [{"message": {"content": "OK"}}],
                    "usage": {},
                }
                _call_openai_compatible(
                    self._choice(provider),
                    messages=[{"role": "user", "content": "OK"}],
                    timeout=10,
                    temperature=0,
                )

        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertNotIn("reasoning_effort", payload)

    def test_qa_prompt_prioritizes_explicit_output_format_without_context(self) -> None:
        messages = _messages_for_task("qa", "只输出 OK", None)

        self.assertIn("优先遵守用户明确的输出格式", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "只输出 OK")


if __name__ == "__main__":
    unittest.main()
