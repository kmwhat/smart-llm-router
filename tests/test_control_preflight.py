import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.cli import build_parser, main
from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.controls import (
    UnsupportedControlError,
    build_control_preflight,
    validate_governed_controls,
)
from smart_llm_router.router import run_llm_task


class GovernedControlPreflightTests(unittest.TestCase):
    def _settings(self, root: str, *, paid: bool = False) -> Settings:
        provider = LLMProvider(
            "synthetic-paid" if paid else "synthetic-free",
            "https://synthetic.invalid/v1",
            "SYNTHETIC_API_KEY",
            ("synthetic-model",),
            not paid,
            1,
            "paid" if paid else "permanent_free",
        )
        return Settings(
            data_dir=Path(root) / "runtime",
            providers=(provider,),
            timeout=1,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            budget_authority_dir=Path(root) / "budget-authority",
            legacy_budget_dirs=(),
        )

    def _ledger_row(self, root: str) -> dict[str, object]:
        rows = (Path(root) / "runtime" / "llm_cost_ledger.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        return json.loads(rows[-1])

    def test_registry_accepts_static_indexed_price_and_task_order_controls(self) -> None:
        controls = {
            "SMART_LLM_CACHE": "false",
            "SMART_LLM2_TRIAL_QUOTA_GUARDED": "true",
            "SMART_LLM_PRICE_SYNTHETIC_PAID_INPUT": "0.1",
            "SMART_LLM_TASK_ORDER_QA": "synthetic-free",
        }
        self.assertEqual(validate_governed_controls(controls), tuple(sorted(controls)))

    def test_near_miss_is_sanitized_and_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            UnsupportedControlError,
            r"governed_control_unsupported:SMART_LLM_CACHE_ENABLED.*SMART_LLM_CACHE.*blocked_before_send",
        ):
            validate_governed_controls({"SMART_LLM_CACHE_ENABLED": "false"})

    def test_static_float_controls_reject_all_nonfinite_forms(self) -> None:
        for name in ("SMART_LLM_CNY_PER_USD", "SMART_LLM_TIMEOUT"):
            for value in ("nan", "inf", "+inf", "-inf", "Infinity", "-Infinity"):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(
                        UnsupportedControlError,
                        rf"governed_control_invalid_value:{name}:expected_",
                    ):
                        validate_governed_controls({name: value})

    def test_dynamic_price_controls_reject_all_nonfinite_forms(self) -> None:
        name = "SMART_LLM_PRICE_SYNTHETIC_INPUT"
        for value in ("nan", "inf", "+inf", "-inf", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    UnsupportedControlError,
                    rf"governed_control_invalid_value:{name}:expected_nonnegative-number",
                ):
                    validate_governed_controls({name: value})

    def test_cli_strict_preflight_runs_before_settings_load(self) -> None:
        argv = ["smart-llm-router", "task", "synthetic", "--strict-controls"]
        with patch.object(sys, "argv", argv):
            with patch.dict(
                os.environ,
                {"SMART_LLM_CACHE_ENABLED": "false"},
                clear=True,
            ):
                with patch("smart_llm_router.cli.load_settings") as load:
                    with self.assertRaises(UnsupportedControlError):
                        main()
        load.assert_not_called()

    def test_nonfinite_cli_strict_preflight_runs_before_settings_load(self) -> None:
        argv = ["smart-llm-router", "task", "synthetic", "--strict-controls"]
        for name in ("SMART_LLM_CNY_PER_USD", "SMART_LLM_PRICE_SYNTHETIC_INPUT"):
            for value in ("nan", "inf", "-inf"):
                with self.subTest(name=name, value=value):
                    with patch.object(sys, "argv", argv):
                        with patch.dict(os.environ, {name: value}, clear=True):
                            with patch("smart_llm_router.cli.load_settings") as load:
                                with self.assertRaises(UnsupportedControlError):
                                    main()
                    load.assert_not_called()

    def test_programmatic_strict_failure_precedes_send_reservation_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp, paid=True)
            with patch.dict(
                os.environ,
                {
                    "SMART_LLM_CACHE_ENABLED": "false",
                    "SYNTHETIC_API_KEY": "synthetic",
                },
                clear=True,
            ):
                with patch("smart_llm_router.router._call_openai_compatible") as send:
                    with patch("smart_llm_router.router.reserve_workflow_budget") as reserve:
                        with self.assertRaises(UnsupportedControlError):
                            run_llm_task(
                                settings,
                                task="draft",
                                prompt="synthetic",
                                prefer_free=False,
                                paid_fallback=True,
                                max_cost_usd=0.01,
                                workflow_id="wf-synthetic",
                                workflow_max_cost_usd=0.02,
                                strict_controls=True,
                                privacy="external_allowed",
                            )
            send.assert_not_called()
            reserve.assert_not_called()
            self.assertFalse(settings.data_dir.exists())
            self.assertFalse(settings.budget_authority_dir.exists())

    def test_nonfinite_programmatic_failure_has_zero_pre_send_side_effects(self) -> None:
        for name in ("SMART_LLM_CNY_PER_USD", "SMART_LLM_PRICE_SYNTHETIC_INPUT"):
            for value in ("nan", "inf", "-inf"):
                with self.subTest(name=name, value=value):
                    with tempfile.TemporaryDirectory() as tmp:
                        settings = self._settings(tmp, paid=True)
                        with patch.dict(
                            os.environ,
                            {name: value, "SYNTHETIC_API_KEY": "synthetic"},
                            clear=True,
                        ):
                            with patch(
                                "smart_llm_router.router._call_openai_compatible"
                            ) as send:
                                with patch(
                                    "smart_llm_router.router.reserve_workflow_budget"
                                ) as reserve:
                                    with patch(
                                        "smart_llm_router.router._load_response_cache"
                                    ) as load_cache:
                                        with self.assertRaises(
                                            UnsupportedControlError
                                        ):
                                            run_llm_task(
                                                settings,
                                                task="draft",
                                                prompt="synthetic",
                                                prefer_free=False,
                                                paid_fallback=True,
                                                max_cost_usd=0.01,
                                                workflow_id="wf-synthetic",
                                                workflow_max_cost_usd=0.02,
                                                strict_controls=True,
                                                privacy="external_allowed",
                                            )
                        send.assert_not_called()
                        reserve.assert_not_called()
                        load_cache.assert_not_called()
                        self.assertFalse(settings.data_dir.exists())
                        self.assertFalse(settings.budget_authority_dir.exists())

    def test_explicit_no_cache_skips_read_write_and_preserves_existing_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp)
            settings.data_dir.mkdir(parents=True)
            cache_path = settings.data_dir / "llm_response_cache.json"
            before = b'{"sentinel":"preserve-exactly"}\n'
            cache_path.write_bytes(before)
            with patch.dict(os.environ, {"SYNTHETIC_API_KEY": "synthetic"}, clear=True):
                with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                    with patch(
                        "smart_llm_router.router._call_openai_compatible",
                        return_value=("FRESH", {"prompt_tokens": 3, "completion_tokens": 1}),
                    ) as send:
                        with patch("smart_llm_router.router._load_response_cache") as load_cache:
                            result = run_llm_task(
                                settings,
                                task="draft",
                                prompt="synthetic no cache",
                                privacy="external_allowed",
                                strict_controls=True,
                                cache_enabled=False,
                            )
            self.assertEqual(result.content, "FRESH")
            self.assertFalse(result.cached)
            self.assertEqual(send.call_count, 1)
            load_cache.assert_not_called()
            self.assertEqual(cache_path.read_bytes(), before)
            evidence = self._ledger_row(tmp)["cache_evidence"]
            self.assertEqual(
                evidence,
                {
                    "requested_cache_enabled": False,
                    "effective_cache_enabled": False,
                    "cache_control_source": "argument:no-cache",
                    "cache_hit": False,
                    "response_cache_persisted": False,
                },
            )

    def test_supported_environment_false_creates_no_cache_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(tmp)
            with patch.dict(
                os.environ,
                {
                    "SMART_LLM_CACHE": "false",
                    "SYNTHETIC_API_KEY": "synthetic",
                },
                clear=True,
            ):
                with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                    with patch(
                        "smart_llm_router.router._call_openai_compatible",
                        return_value=("FRESH", {"prompt_tokens": 3, "completion_tokens": 1}),
                    ):
                        run_llm_task(
                            settings,
                            task="draft",
                            prompt="synthetic env no cache",
                            privacy="external_allowed",
                            strict_controls=True,
                        )
            self.assertFalse((settings.data_dir / "llm_response_cache.json").exists())
            evidence = self._ledger_row(tmp)["cache_evidence"]
            self.assertFalse(evidence["effective_cache_enabled"])
            self.assertEqual(
                evidence["cache_control_source"], "environment:SMART_LLM_CACHE"
            )
            self.assertFalse(evidence["cache_hit"])
            self.assertFalse(evidence["response_cache_persisted"])

    def test_parser_exposes_governed_strict_and_explicit_no_cache(self) -> None:
        args = build_parser().parse_args(
            ["task", "synthetic", "--strict-controls", "--no-cache"]
        )
        self.assertTrue(args.strict_controls)
        self.assertTrue(args.no_cache)
        preflight = build_control_preflight(
            strict_controls=args.strict_controls,
            explicit_cache_enabled=False,
            environ={},
        )
        self.assertFalse(preflight.effective_cache_enabled)


if __name__ == "__main__":
    unittest.main()
