import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import preprocess_input
from smart_llm_router.router import run_llm_task


class PreprocessInputTests(unittest.TestCase):
    def test_greeting_stays_local(self) -> None:
        result = preprocess_input(task="qa", prompt="你好", context=None)

        self.assertEqual(result["tier_decision"]["tier"], 0)
        self.assertFalse(result["tier_decision"]["cloud_allowed"])

    def test_long_context_is_extractively_compressed(self) -> None:
        context = "\n".join(
            [
                "背景：今天系统运行正常，没有异常。",
                "问题：OpenRouter 免费模型出现 429，需要进入冷却。",
                "原因：免费模型池被频繁探活，部分模型触发 rate limit。",
                "步骤：先本地压缩上下文，再用免费模型处理，最后才允许付费模型。",
            ]
            * 80
        )
        result = preprocess_input(task="summarize", prompt="总结路由问题和步骤", context=context, target_tokens=120)

        self.assertLess(result["compressed_tokens_est"], result["raw_tokens_est"])
        self.assertIn("问题", result["compressed_context"])
        self.assertEqual(result["compressed_context"].count("问题：OpenRouter"), 1)
        self.assertIn(result["tier_decision"]["tier"], {2, 3})

    def test_simple_short_task_uses_free_or_small_local_tier(self) -> None:
        result = preprocess_input(task="classify", prompt="把这句话分类成问候或任务：明天提醒我整理文件")

        self.assertEqual(result["tier_decision"]["tier"], 1)
        self.assertFalse(result["tier_decision"]["paid_allowed"])

    def test_task_preprocess_can_return_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                data_dir=Path(tmp),
                providers=(),
                timeout=5,
                empty_pool_refresh_timeout=1,
                empty_pool_refresh_limit=1,
            )
            with patch("smart_llm_router.router._call_openai_compatible") as call:
                result = run_llm_task(settings, task="qa", prompt="你好", preprocess=True)

            call.assert_not_called()
            self.assertEqual(result.provider, "local-preprocess")
            self.assertEqual(result.model, "local_rules")
            self.assertIn('"cloud_allowed": false', result.content)

    def test_task_preprocess_sends_compressed_context_to_model(self) -> None:
        context = "\n".join(
            [
                "背景：今天系统运行正常，没有异常。",
                "问题：OpenRouter 免费模型出现 429，需要进入冷却。",
                "原因：免费模型池被频繁探活，部分模型触发 rate limit。",
                "步骤：先本地压缩上下文，再用免费模型处理，最后才允许付费模型。",
            ]
            * 80
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                data_dir=Path(tmp),
                providers=(
                    LLMProvider(
                        "free-test",
                        "https://example.test/v1",
                        "TEST_API_KEY",
                        ("model-a",),
                        True,
                        1,
                    ),
                ),
                timeout=5,
                empty_pool_refresh_timeout=1,
                empty_pool_refresh_limit=1,
            )

            captured = {}

            def fake_call(choice, *, messages, timeout, temperature, max_tokens=None):
                captured["messages"] = messages
                return "OK", {"prompt_tokens": 10, "completion_tokens": 1}

            with patch.dict("os.environ", {"TEST_API_KEY": "test"}, clear=False):
                with patch("smart_llm_router.router._call_openai_compatible", side_effect=fake_call):
                    result = run_llm_task(
                        settings,
                        task="summarize",
                        prompt="总结路由问题和步骤",
                        context=context,
                        preprocess=True,
                        preprocess_target_tokens=120,
                    )

            self.assertEqual(result.content, "OK")
            user_text = captured["messages"][1]["content"]
            self.assertLess(len(user_text), len(context))
            self.assertIn("OpenRouter", user_text)


if __name__ == "__main__":
    unittest.main()
