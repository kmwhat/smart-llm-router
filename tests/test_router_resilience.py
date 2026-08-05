import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    InconclusiveModelOutput,
    LLMChoice,
    _call_openai_compatible,
    describe_choice_capability,
    refresh_model_pool,
    router_doctor,
)


class RouterResilienceTests(unittest.TestCase):
    def _settings(self, root: Path, providers: tuple[LLMProvider, ...]) -> Settings:
        return Settings(
            data_dir=root,
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=2,
        )

    def test_openai_compatible_content_blocks_are_extracted(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://example.test/v1",
            "API_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        response = Mock()
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "output_text", "text": "OK"},
                            {"type": "text", "text": "完成"},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"completion_tokens": 2},
        }
        with patch.dict(os.environ, {"API_KEY": "secret"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = response
                content, usage = _call_openai_compatible(
                    LLMChoice(provider, provider.models[0]),
                    messages=[{"role": "user", "content": "test"}],
                    timeout=2,
                    temperature=0,
                )

        self.assertEqual(content, "OK\n完成")
        self.assertEqual(usage["completion_tokens"], 2)
        self.assertEqual(
            usage["_completion_metadata"],
            {"finish_reason": "stop", "output_reached_requested_token_limit": False},
        )

    def test_reasoning_without_final_answer_is_inconclusive_not_success(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://example.test/v1",
            "API_KEY",
            ("reasoning-model",),
            True,
            1,
            "permanent_free",
        )
        response = Mock()
        response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "", "reasoning_content": "private chain"},
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 96},
        }
        with patch.dict(os.environ, {"API_KEY": "secret"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaises(InconclusiveModelOutput) as raised:
                    _call_openai_compatible(
                        LLMChoice(provider, provider.models[0]),
                        messages=[{"role": "user", "content": "test"}],
                        timeout=2,
                        temperature=0,
                    )

        self.assertIn("reasoning_present", str(raised.exception))
        self.assertNotIn("private chain", str(raised.exception))
        self.assertEqual(raised.exception.usage["completion_tokens"], 96)

    def test_refresh_retries_inconclusive_probe_and_checkpoints_progress(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://example.test/v1",
            "API_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        progress: list[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            with patch.dict(os.environ, {"API_KEY": "secret"}, clear=True):
                with patch(
                    "smart_llm_router.router._call_openai_compatible",
                    side_effect=[
                        InconclusiveModelOutput(
                            "openrouter-free/example/model:free",
                            reasoning_present=True,
                            finish_reason="length",
                        ),
                        ("OK", {}),
                    ],
                ) as call:
                    rows = refresh_model_pool(settings, progress=progress.append)
            report = json.loads(
                (Path(tmp) / "llm_pool_refresh_report.json").read_text(encoding="utf-8")
            )

        self.assertTrue(rows[0]["ok"])
        self.assertEqual(rows[0]["attempts"], 2)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed"], 1)
        self.assertEqual([row["event"] for row in progress], ["probe_started", "probe_completed"])

    def test_doctor_explains_free_role_exclusion_without_network(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://example.test/v1",
            "NVIDIA_KEY",
            ("deepseek-v4-pro",),
            True,
            1,
            "trial_quota",
            False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            with patch.dict(os.environ, {"NVIDIA_KEY": "secret"}, clear=True):
                report = router_doctor(settings)

        self.assertEqual(report["network_calls"], 0)
        self.assertIn("plan", report["blocked_roles"])
        plan = next(row for row in report["roles"] if row["role"] == "plan")
        excluded = next(row for row in plan["why_not"] if row["model"] == "deepseek-v4-pro")
        self.assertIn("trial_quota_guard_missing", excluded["reasons"])

    def test_flash_0731_is_visible_as_pending_not_silently_promoted(self) -> None:
        provider = LLMProvider(
            "deepseek-direct-paid",
            "https://example.test/v1",
            "DEEPSEEK_KEY",
            ("deepseek-v4-flash",),
            False,
            1,
            "paid",
        )
        choice = LLMChoice(provider=provider, model="deepseek-v4-flash")
        capability = describe_choice_capability(choice)
        self.assertEqual(capability["role_candidate_status"]["version"], "DeepSeek-V4-Flash-0731")
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            with patch.dict(os.environ, {"DEEPSEEK_KEY": "secret"}, clear=True):
                report = router_doctor(settings, paid_allowed=True)
        plan = next(row for row in report["roles"] if row["role"] == "plan")
        excluded = next(row for row in plan["why_not"] if row["model"] == "deepseek-v4-flash")
        self.assertIn("pending_role_golden_gate", excluded["reasons"])


if __name__ == "__main__":
    unittest.main()
