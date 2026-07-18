import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import generate_image, remote_transcribe_media, route_plan


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
