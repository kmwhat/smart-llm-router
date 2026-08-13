import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    embed_texts,
    generate_image,
    quick_benchmark,
    refresh_model_pool_by_modality,
    remote_transcribe_media,
    rerank_documents,
    route_plan,
)


class SpecializedAdapterSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            data_dir=Path(tempfile.gettempdir()) / "smart-router-test",
            providers=(),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )

    def test_remote_asr_requires_explicit_external_permission(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "--allow-external"):
            remote_transcribe_media(
                self.settings,
                __file__,
                provider="zhipu",
            )

    def test_image_generation_requires_explicit_paid_permission(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "--allow-paid"):
            generate_image(self.settings, "test")

    def test_remote_asr_requires_explicit_paid_permission(self) -> None:
        settings = Settings(
            data_dir=self.settings.data_dir,
            providers=(
                LLMProvider(
                    "zhipu-asr-paid",
                    "https://open.bigmodel.cn/api/paas/v4",
                    "ZHIPU_API_KEY",
                    ("glm-asr-2512",),
                    False,
                    8,
                    "paid",
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict("os.environ", {"ZHIPU_API_KEY": "test"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "--allow-paid"):
                remote_transcribe_media(
                    settings,
                    __file__,
                    provider="zhipu",
                    allow_external=True,
                )

    def test_embedding_and_rerank_require_explicit_paid_permission(self) -> None:
        settings = Settings(
            data_dir=self.settings.data_dir,
            providers=(
                LLMProvider(
                    "zhipu-embedding-lowcost",
                    "https://open.bigmodel.cn/api/paas/v4",
                    "ZHIPU_API_KEY",
                    ("embedding-3",),
                    False,
                    8,
                    "paid",
                ),
                LLMProvider(
                    "qwen-rerank-paid",
                    "https://dashscope.aliyuncs.com/api/v1",
                    "DASHSCOPE_API_KEY",
                    ("qwen3-rerank",),
                    False,
                    8,
                    "paid",
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict(
            "os.environ",
            {"ZHIPU_API_KEY": "test", "DASHSCOPE_API_KEY": "test"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "--allow-paid"):
                embed_texts(settings, ["test"])
            with self.assertRaisesRegex(RuntimeError, "--allow-paid"):
                rerank_documents(settings, query="test", documents=["a"])

    def test_quick_benchmark_excludes_unprotected_trial_by_default(self) -> None:
        settings = Settings(
            data_dir=self.settings.data_dir,
            providers=(
                LLMProvider(
                    "nvidia-free",
                    "https://integrate.api.nvidia.com/v1",
                    "NVIDIA_API_KEY",
                    ("deepseek-ai/deepseek-v4-pro",),
                    True,
                    1,
                    "trial_quota",
                    False,
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict("os.environ", {"NVIDIA_API_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible") as call:
                report = quick_benchmark(settings, limit=1)
        self.assertEqual(report["candidates"], [])
        call.assert_not_called()

    def test_modality_refresh_excludes_unprotected_trial_by_default(self) -> None:
        settings = Settings(
            data_dir=self.settings.data_dir,
            providers=(
                LLMProvider(
                    "nvidia-free",
                    "https://integrate.api.nvidia.com/v1",
                    "NVIDIA_API_KEY",
                    ("deepseek-ai/deepseek-v4-pro",),
                    True,
                    1,
                    "trial_quota",
                    False,
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict("os.environ", {"NVIDIA_API_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible") as call:
                report = refresh_model_pool_by_modality(settings, tasks=["qa"], limit=1)
        self.assertEqual(report["results"]["qa"], [])
        call.assert_not_called()

    def test_asr_plan_keeps_local_first_and_lists_explicit_fallback(self) -> None:
        settings = Settings(
            data_dir=self.settings.data_dir,
            providers=(
                LLMProvider(
                    "zhipu-asr-paid",
                    "https://open.bigmodel.cn/api/paas/v4",
                    "ZHIPU_API_KEY",
                    ("glm-asr-2512",),
                    False,
                    8,
                ),
            ),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict("os.environ", {"ZHIPU_API_KEY": "test"}):
            plan = route_plan(settings, task="asr", quality_target="production")
        self.assertEqual(plan["descriptor"]["privacy"], "local_first_external_explicit")
        self.assertEqual(plan["route_ladder"][0], "local_asr")
        self.assertEqual(plan["recommended_order"][0]["model"], "glm-asr-2512")


if __name__ == "__main__":
    unittest.main()
