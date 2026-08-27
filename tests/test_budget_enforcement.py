import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from smart_llm_router.budget import (
    BudgetLimitExceeded,
    _state_path,
    finalize_workflow_reservation,
    release_workflow_reservation,
    reserve_workflow_budget,
)
from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    InconclusiveModelOutput,
    LLMChoice,
    MAX_GUARDED_INPUT_TOKENS,
    _budget_status,
    _call_openai_compatible,
    _estimated_cost_usd,
    _guarded_input_token_evidence,
    _sanitized_routing_metadata,
    _thinking_plan,
    estimate_messages_tokens,
    run_llm_task,
)


class BudgetEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = Path(tempfile.mkdtemp())
        self.provider = LLMProvider(
            "qwen-frontier-paid",
            "https://qwen.test/v1",
            "QWEN_KEY",
            ("qwen3.7-max",),
            False,
            1,
            "paid",
        )
        self.settings = Settings(
            data_dir=self.data_dir,
            providers=(self.provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            budget_authority_dir=self.data_dir,
        )

    def _write_legacy_budget(
        self,
        root: Path,
        workflow_id: str,
        *,
        maximum: float = 0.02,
        spent: float = 0.006,
        status: str = "active",
        reservations: dict[str, object] | None = None,
        incidents: list[str] | None = None,
    ) -> Path:
        path = _state_path(root, workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "smart_llm_router.workflow_budget.v1",
                    "workflow_id": workflow_id,
                    "workflow_max_cost_usd": maximum,
                    "status": status,
                    "spent_usd": spent,
                    "reservations": reservations or {},
                    "incidents": incidents or [],
                    "created_at": "2026-08-02T10:00:00+00:00",
                    "updated_at": "2026-08-02T11:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_incident_qwen_request_reserves_complete_output_envelope(self) -> None:
        choice = LLMChoice(self.provider, "qwen3.7-max")
        budget = _budget_status(choice, 913, 0.01, output_tokens=1200)
        self.assertTrue(budget["eligible"])
        self.assertEqual(budget["reserved_output_tokens"], 1210)
        self.assertLess(budget["projected_cost_usd"], 0.01)

        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch(
                "smart_llm_router.router._call_openai_compatible",
                return_value=('{"decision":"pass"}', {"prompt_tokens": 913, "completion_tokens": 1200}),
            ) as call:
                result = run_llm_task(
                    self.settings,
                    task="audit",
                    prompt="独立审计一份复杂治理计划",
                    prefer_free=False,
                    paid_fallback=True,
                    quality_target="frontier",
                    privacy="external_allowed",
                    provider="qwen-frontier-paid",
                    model="qwen3.7-max",
                    max_cost_usd=0.01,
                    max_output_tokens=1200,
                )
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result.model, "qwen3.7-max")
        ledger = json.loads((self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertLessEqual(ledger["estimated_cost_usd"], 0.01)
        self.assertEqual(ledger["reserved_output_tokens"], 1210)

    def test_deepseek_incident_forecast_blocks_before_send_reservation_or_cache(self) -> None:
        provider = LLMProvider(
            "deepseek-direct-paid",
            "https://deepseek.test/v1",
            "DEEPSEEK_KEY",
            ("deepseek-v4-pro",),
            False,
            1,
            "paid",
        )
        settings = Settings(
            data_dir=self.data_dir,
            providers=(provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            budget_authority_dir=self.data_dir / "authority",
        )
        choice = LLMChoice(provider, "deepseek-v4-pro")
        self.assertEqual(_estimated_cost_usd(choice, 21476, 700), 0.00995106)
        self.assertEqual(_estimated_cost_usd(choice, 23139, 350), 0.01036997)
        budget = _budget_status(choice, 21476, 0.01, output_tokens=350)
        self.assertFalse(budget["eligible"])
        self.assertEqual(budget["raw_input_tokens_est"], 21476)
        self.assertEqual(budget["guarded_input_tokens"], 24698)
        self.assertEqual(budget["guard_factor"], 1.15)
        self.assertEqual(budget["reserved_output_tokens"], 700)
        self.assertEqual(budget["reason"], "projected_cost_exceeds_limit")
        self.assertGreater(budget["projected_cost_usd"], 0.01)

        with patch.dict(os.environ, {"DEEPSEEK_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch("smart_llm_router.router.estimate_messages_tokens", return_value=21476), patch(
                "smart_llm_router.router._call_openai_compatible"
            ) as send, patch("smart_llm_router.router.reserve_workflow_budget") as reserve, patch(
                "smart_llm_router.router._save_response_cache"
            ) as cache_write:
                with self.assertRaisesRegex(RuntimeError, "budget gate projected_cost_exceeds_limit"):
                    run_llm_task(
                        settings,
                        task="audit",
                        prompt="synthetic incident regression",
                        prefer_free=False,
                        paid_fallback=True,
                        quality_target="frontier",
                        privacy="external_allowed",
                        provider="deepseek-direct-paid",
                        model="deepseek-v4-pro",
                        max_cost_usd=0.01,
                        max_output_tokens=350,
                        workflow_id="synthetic-incident",
                        workflow_max_cost_usd=0.02,
                    )
        send.assert_not_called()
        reserve.assert_not_called()
        cache_write.assert_not_called()
        self.assertFalse((settings.budget_authority_dir / "workflow-budgets").exists())
        incident = json.loads(next((self.data_dir / "budget-incidents").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(incident["decision"], "blocked_before_send")
        self.assertEqual(incident["raw_input_tokens_est"], 21476)
        self.assertEqual(incident["guarded_input_tokens"], 24698)
        self.assertEqual(incident["spend_ceiling_semantics"], "local_forecast_guard_not_provider_enforced")

    def test_guard_factor_and_derived_token_values_fail_closed(self) -> None:
        choice = LLMChoice(self.provider, "qwen3.7-max")
        for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0, 1.14):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _guarded_input_token_evidence(choice, 10, guard_factor=invalid)
        with self.assertRaisesRegex(ValueError, "超出安全范围"):
            _guarded_input_token_evidence(choice, MAX_GUARDED_INPUT_TOKENS)

    def test_invalid_guard_fails_before_cache_send_or_budget_state(self) -> None:
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "true"}, clear=True):
            with patch("smart_llm_router.router._load_response_cache") as cache_read, patch(
                "smart_llm_router.router._call_openai_compatible"
            ) as send, patch("smart_llm_router.router.reserve_workflow_budget") as reserve:
                with self.assertRaisesRegex(ValueError, "有限正数"):
                    run_llm_task(
                        self.settings,
                        task="audit",
                        prompt="synthetic",
                        prefer_free=False,
                        paid_fallback=True,
                        privacy="external_allowed",
                        max_cost_usd=0.01,
                        input_token_guard_factor=float("nan"),
                    )
        cache_read.assert_not_called()
        send.assert_not_called()
        reserve.assert_not_called()

    def test_nonfinite_budget_ceilings_fail_before_cache_send_reservation_or_state(self) -> None:
        for field in ("max_cost_usd", "workflow_max_cost_usd"):
            for invalid in (float("nan"), float("inf"), float("-inf")):
                kwargs = {
                    "task": "audit",
                    "prompt": "synthetic",
                    "prefer_free": False,
                    "paid_fallback": True,
                    "privacy": "external_allowed",
                    "max_cost_usd": 0.01,
                    "workflow_id": "wf-nonfinite",
                    "workflow_max_cost_usd": 0.02,
                }
                kwargs[field] = invalid
                with self.subTest(field=field, invalid=invalid), patch.dict(
                    os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "true"}, clear=True
                ), patch("smart_llm_router.router._load_response_cache") as cache_read, patch(
                    "smart_llm_router.router._call_openai_compatible"
                ) as send, patch("smart_llm_router.router.reserve_workflow_budget") as reserve, patch(
                    "smart_llm_router.router._append_ledger"
                ) as ledger_write, patch("smart_llm_router.router.write_budget_incident") as incident_write:
                    with self.assertRaisesRegex(ValueError, "必须为有限"):
                        run_llm_task(self.settings, **kwargs)
                cache_read.assert_not_called()
                send.assert_not_called()
                reserve.assert_not_called()
                ledger_write.assert_not_called()
                incident_write.assert_not_called()
                self.assertFalse((self.settings.budget_authority_dir / "workflow-budgets").exists())

    def test_internal_budget_status_rejects_nonfinite_ceiling(self) -> None:
        choice = LLMChoice(self.provider, "qwen3.7-max")
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(invalid=invalid):
                budget = _budget_status(choice, 21476, invalid, output_tokens=350)
                self.assertFalse(budget["eligible"])
                self.assertEqual(budget["reason"], "invalid_cost_limit_fails_closed")

    def test_guard_rounding_is_deterministic_for_supported_text_shapes(self) -> None:
        choice = LLMChoice(self.provider, "qwen3.7-max")
        samples = (
            "plain ASCII source code: if (x) return true;",
            "纯中文预算审计样本",
            "mixed 中文 code {\"enabled\": true}",
            json.dumps({"items": [1, 2], "decision": "pass"}, ensure_ascii=False),
        )
        guarded = []
        for sample in samples:
            raw = estimate_messages_tokens([{"role": "user", "content": sample}])
            first = _guarded_input_token_evidence(choice, raw)
            second = _guarded_input_token_evidence(choice, raw)
            self.assertEqual(first, second)
            self.assertGreaterEqual(first["guarded_input_tokens"], raw)
            guarded.append(first["guarded_input_tokens"])
        self.assertEqual(len(guarded), 4)

    def test_qwen_uses_max_completion_tokens_not_answer_only_limit(self) -> None:
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 8},
        }
        with patch.dict(os.environ, {"QWEN_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                _call_openai_compatible(
                    LLMChoice(self.provider, "qwen3.7-max"),
                    messages=[{"role": "user", "content": "test"}],
                    timeout=2,
                    temperature=0,
                    max_tokens=1200,
                )
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["max_completion_tokens"], 1200)
        self.assertNotIn("max_tokens", payload)

    def test_minimax_uses_current_request_shape_and_conservative_price(self) -> None:
        provider = LLMProvider(
            "minimax-frontier-paid",
            "https://api.minimaxi.com/v1",
            "MINIMAX_KEY",
            ("MiniMax-M3",),
            False,
            1,
            "paid",
        )
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 8},
            "base_resp": {"status_code": 0, "status_msg": ""},
        }
        with patch.dict(os.environ, {"MINIMAX_KEY": "test", "SMART_LLM_CNY_PER_USD": "7.2"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                _call_openai_compatible(
                    LLMChoice(provider, "MiniMax-M3"),
                    messages=[{"role": "user", "content": "test"}],
                    timeout=2,
                    temperature=0,
                    max_tokens=1200,
                )
            estimated = _estimated_cost_usd(
                LLMChoice(provider, "MiniMax-M3"),
                1_000_000,
                1_000_000,
            )
            observed_canary_guard = _guarded_input_token_evidence(
                LLMChoice(provider, "MiniMax-M3"),
                48,
            )
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["max_completion_tokens"], 1200)
        self.assertTrue(payload["reasoning_split"])
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(estimated, 2.916666)
        self.assertEqual(observed_canary_guard["guarded_input_tokens"], 213)
        self.assertGreaterEqual(observed_canary_guard["guarded_input_tokens"], 199)
        self.assertEqual(observed_canary_guard["guard_overhead_tokens"], 160)

    def test_minimax_business_error_fails_closed_without_exposing_message(self) -> None:
        provider = LLMProvider(
            "minimax-frontier-paid",
            "https://api.minimaxi.com/v1",
            "MINIMAX_KEY",
            ("MiniMax-M3",),
            False,
            1,
            "paid",
        )
        response = Mock()
        response.json.return_value = {
            "base_resp": {"status_code": 1008, "status_msg": "private provider detail"},
        }
        with patch.dict(os.environ, {"MINIMAX_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaisesRegex(RuntimeError, r"^minimax_api_error:1008$"):
                    _call_openai_compatible(
                        LLMChoice(provider, "MiniMax-M3"),
                        messages=[{"role": "user", "content": "test"}],
                        timeout=2,
                        temperature=0,
                    )

    def test_deepseek_disabled_thinking_uses_official_request_shape(self) -> None:
        provider = LLMProvider(
            "deepseek-direct-paid",
            "https://deepseek.test/v1",
            "DEEPSEEK_KEY",
            ("deepseek-v4-pro",),
            False,
            1,
            "paid",
        )
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "{\"decision\":\"pass\"}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        }
        with patch.dict(os.environ, {"DEEPSEEK_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                _call_openai_compatible(
                    LLMChoice(provider, "deepseek-v4-pro"),
                    messages=[{"role": "user", "content": "return JSON"}],
                    timeout=2,
                    temperature=0,
                    max_tokens=1800,
                    thinking={"type": "disabled"},
                )
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 1800)
        self.assertNotIn("enable_thinking", payload)
        self.assertNotIn("thinking_budget", payload)

    def test_deepseek_vision_exp_preserves_image_and_disabled_thinking_controls(self) -> None:
        provider = LLMProvider(
            "deepseek-direct-paid",
            "https://deepseek.test/v1",
            "DEEPSEEK_KEY",
            ("deepseek-v4-flash-vision-exp",),
            False,
            1,
            "paid",
        )
        image_url = "data:image/png;base64,iVBORw0KGgo="
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "white square"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 3},
        }
        with patch.dict(os.environ, {"DEEPSEEK_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                _call_openai_compatible(
                    LLMChoice(provider, provider.models[0]),
                    messages=messages,
                    timeout=2,
                    temperature=0,
                    max_tokens=64,
                    thinking={"type": "disabled"},
                )
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "deepseek-v4-flash-vision-exp")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["messages"], messages)
        self.assertNotIn("chat_template_kwargs", payload)

    def test_nvidia_deepseek_v4_uses_official_chat_template_kwargs(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://integrate.api.nvidia.com/v1",
            "NVIDIA_KEY",
            ("deepseek-ai/deepseek-v4-flash-0731",),
            True,
            1,
            "trial_quota",
            True,
        )
        response = Mock()
        response.json.return_value = {
            "model": "deepseek-ai/deepseek-v4-flash",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }
        with patch.dict(os.environ, {"NVIDIA_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                _, usage = _call_openai_compatible(
                    LLMChoice(provider, provider.models[0]),
                    messages=[{"role": "user", "content": "test"}],
                    timeout=2,
                    temperature=0,
                    max_tokens=1024,
                )

        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(
            payload["chat_template_kwargs"],
            {"thinking": True, "reasoning_effort": "high"},
        )
        self.assertNotIn("thinking", payload)
        self.assertEqual(
            usage["_routing_metadata"]["served_model"],
            "deepseek-ai/deepseek-v4-flash",
        )
        self.assertEqual(
            _sanitized_routing_metadata(usage)["served_model"],
            "deepseek-ai/deepseek-v4-flash",
        )

    def test_nvidia_deepseek_v4_disabled_thinking_uses_template_flag(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://integrate.api.nvidia.com/v1",
            "NVIDIA_KEY",
            ("deepseek-ai/deepseek-v4-flash-0731",),
            True,
            1,
            "trial_quota",
            True,
        )
        choice = LLMChoice(provider, provider.models[0])
        plan = _thinking_plan(
            choice,
            task="qa",
            total_output_tokens=64,
            thinking_mode="disabled",
            thinking_budget_tokens=None,
            final_answer_reserve_tokens=None,
        )
        self.assertEqual(plan["thinking"], {"type": "disabled"})

        response = Mock()
        response.json.return_value = {
            "model": provider.models[0],
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        }
        with patch.dict(os.environ, {"NVIDIA_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                _call_openai_compatible(
                    choice,
                    messages=[{"role": "user", "content": "test"}],
                    timeout=2,
                    temperature=0,
                    thinking=plan["thinking"],
                )

        payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_template_kwargs"], {"thinking": False})
        self.assertNotIn("thinking", payload)

    def test_nvidia_deepseek_v4_rejects_non_equivalent_served_model(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://integrate.api.nvidia.com/v1",
            "NVIDIA_KEY",
            ("deepseek-ai/deepseek-v4-flash-0731",),
            True,
            1,
            "trial_quota",
            True,
        )
        response = Mock()
        response.json.return_value = {
            "model": "unrelated/model",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        }
        with patch.dict(os.environ, {"NVIDIA_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaisesRegex(RuntimeError, "model_substitution_detected"):
                    _call_openai_compatible(
                        LLMChoice(provider, provider.models[0]),
                        messages=[{"role": "user", "content": "test"}],
                        timeout=2,
                        temperature=0,
                    )

    def test_nvidia_deepseek_v4_rejects_invalid_served_model_metadata(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://integrate.api.nvidia.com/v1",
            "NVIDIA_KEY",
            ("deepseek-ai/deepseek-v4-flash-0731",),
            True,
            1,
            "trial_quota",
            True,
        )
        response = Mock()
        response.json.return_value = {
            "model": "deepseek-ai/deepseek-v4-flash\nforged-log-line",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        }
        with patch.dict(os.environ, {"NVIDIA_KEY": "test"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaisesRegex(RuntimeError, "invalid_served_model"):
                    _call_openai_compatible(
                        LLMChoice(provider, provider.models[0]),
                        messages=[{"role": "user", "content": "test"}],
                        timeout=2,
                        temperature=0,
                    )

    def test_deepseek_final_answer_reserve_disables_unbounded_thinking(self) -> None:
        provider = LLMProvider(
            "deepseek-direct-paid",
            "https://deepseek.test/v1",
            "DEEPSEEK_KEY",
            ("deepseek-v4-pro",),
            False,
            1,
            "paid",
        )
        settings = Settings(
            data_dir=self.data_dir,
            providers=(provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict(os.environ, {"DEEPSEEK_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch(
                "smart_llm_router.router._call_openai_compatible",
                return_value=("{\"decision\":\"pass\"}", {"prompt_tokens": 100, "completion_tokens": 200}),
            ) as call:
                run_llm_task(
                    settings,
                    task="audit",
                    prompt="独立审计并输出 JSON",
                    prefer_free=False,
                    paid_fallback=True,
                    quality_target="frontier",
                    privacy="external_allowed",
                    provider="deepseek-direct-paid",
                    model="deepseek-v4-pro",
                    max_cost_usd=0.01,
                    max_output_tokens=1800,
                    final_answer_reserve_tokens=600,
                )
        self.assertEqual(call.call_args.kwargs["thinking"], {"type": "disabled"})
        self.assertEqual(call.call_args.kwargs["max_tokens"], 1800)
        ledger = json.loads((self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(ledger["thinking_plan"]["mode"], "disabled")
        self.assertEqual(ledger["thinking_plan"]["final_answer_reserve_tokens"], 1800)

    def test_deepseek_enabled_thinking_rejects_fake_final_answer_reserve(self) -> None:
        provider = LLMProvider(
            "deepseek-direct-paid",
            "https://deepseek.test/v1",
            "DEEPSEEK_KEY",
            ("deepseek-v4-pro",),
            False,
            1,
            "paid",
        )
        settings = Settings(
            data_dir=self.data_dir,
            providers=(provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
        )
        with patch.dict(os.environ, {"DEEPSEEK_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "无法保证独立 final-answer reserve"):
                run_llm_task(
                    settings,
                    task="audit",
                    prompt="audit",
                    prefer_free=False,
                    paid_fallback=True,
                    privacy="external_allowed",
                    provider="deepseek-direct-paid",
                    model="deepseek-v4-pro",
                    max_cost_usd=0.01,
                    max_output_tokens=1800,
                    thinking_mode="enabled",
                    final_answer_reserve_tokens=600,
                )

    def test_programmatic_paid_route_requires_single_call_hard_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_cost_usd"):
            run_llm_task(
                self.settings,
                task="audit",
                prompt="audit",
                prefer_free=False,
                paid_fallback=True,
                privacy="external_allowed",
            )

    def test_workflow_reservations_enforce_cumulative_budget(self) -> None:
        first = reserve_workflow_budget(
            self.data_dir,
            workflow_id="wf-test",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.01,
            reserved_cost_usd=0.008,
            stage="plan",
        )
        self.assertIsNone(finalize_workflow_reservation(self.data_dir, first, actual_or_estimated_cost_usd=0.006))
        second = reserve_workflow_budget(
            self.data_dir,
            workflow_id="wf-test",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.01,
            reserved_cost_usd=0.01,
            stage="audit",
        )
        with self.assertRaises(BudgetLimitExceeded) as blocked:
            reserve_workflow_budget(
                self.data_dir,
                workflow_id="wf-test",
                workflow_max_cost_usd=0.02,
                call_max_cost_usd=0.01,
                reserved_cost_usd=0.005,
                stage="verify",
            )
        self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_reservation_rejected")
        self.assertEqual(blocked.exception.incident["decision"], "blocked_before_send")
        # Keep the active reservation to prove the atomic reservation, not only
        # settled spend, participates in the cumulative gate.
        self.assertEqual(second.reserved_cost_usd, 0.01)

    def test_runtime_isolation_cannot_reset_shared_workflow_budget_authority(self) -> None:
        authority = self.data_dir / "canonical-authority"
        legacy = self.data_dir / "standard-legacy-runtime"
        self._write_legacy_budget(legacy, "wf-shared-authority", maximum=0.01, spent=0.004)
        settings_a = Settings(
            data_dir=self.data_dir / "runtime-a",
            providers=(self.provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            budget_authority_dir=authority,
            legacy_budget_dirs=(legacy,),
        )
        settings_b = Settings(
            data_dir=self.data_dir / "runtime-b",
            providers=(self.provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            budget_authority_dir=authority,
            legacy_budget_dirs=(legacy,),
        )
        admitted = {
            "eligible": True,
            "projected_cost_usd": 0.006,
            "reserved_output_tokens": 600,
            "reason": None,
        }
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch("smart_llm_router.router._budget_status", return_value=admitted):
                with patch("smart_llm_router.router._estimated_cost_usd", return_value=0.006):
                    with patch(
                        "smart_llm_router.router._call_openai_compatible",
                        return_value=('{"decision":"pass"}', {"prompt_tokens": 100, "completion_tokens": 500}),
                    ) as call:
                        run_llm_task(
                            settings_a,
                            task="audit",
                            prompt="first",
                            prefer_free=False,
                            paid_fallback=True,
                            privacy="external_allowed",
                            provider="qwen-frontier-paid",
                            model="qwen3.7-max",
                            max_cost_usd=0.007,
                            max_output_tokens=600,
                            workflow_id="wf-shared-authority",
                            workflow_max_cost_usd=0.01,
                            workflow_stage="first",
                        )
                        with self.assertRaisesRegex(RuntimeError, "累计预算不足"):
                            run_llm_task(
                                settings_b,
                                task="audit",
                                prompt="second",
                                prefer_free=False,
                                paid_fallback=True,
                                privacy="external_allowed",
                                provider="qwen-frontier-paid",
                                model="qwen3.7-max",
                                max_cost_usd=0.007,
                                max_output_tokens=600,
                                workflow_id="wf-shared-authority",
                                workflow_max_cost_usd=0.01,
                                workflow_stage="second",
                            )
        self.assertEqual(call.call_count, 1)
        state = json.loads(next((authority / "workflow-budgets").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(state["schema"], "smart_llm_router.workflow_budget.v2")
        self.assertAlmostEqual(state["spent_usd"], 0.01)
        self.assertTrue(str(state["budget_authority_id"]).startswith("ba_"))
        self.assertEqual(state["migration"]["legacy_created_at"], "2026-08-02T10:00:00+00:00")
        self.assertFalse((settings_b.data_dir / "workflow-budgets").exists())

    def test_active_v1_migration_preserves_spend_reservations_incidents_and_timestamps(self) -> None:
        legacy = self.data_dir / "legacy-active"
        authority = self.data_dir / "authority-active"
        old_reservations = {
            "old-r": {
                "reserved_cost_usd": 0.002,
                "call_max_cost_usd": 0.004,
                "stage": "legacy",
                "created_at": "2026-08-02T10:30:00+00:00",
            }
        }
        self._write_legacy_budget(
            legacy,
            "wf-migrate-active",
            spent=0.006,
            reservations=old_reservations,
            incidents=["old-incident"],
        )
        reserve_workflow_budget(
            authority,
            workflow_id="wf-migrate-active",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.003,
            reserved_cost_usd=0.001,
            stage="new",
            legacy_data_dirs=(legacy,),
        )
        state = json.loads(_state_path(authority, "wf-migrate-active").read_text(encoding="utf-8"))
        self.assertEqual(state["schema"], "smart_llm_router.workflow_budget.v2")
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["workflow_max_cost_usd"], 0.02)
        self.assertEqual(state["spent_usd"], 0.006)
        self.assertIn("old-r", state["reservations"])
        self.assertIn("old-incident", state["incidents"])
        self.assertEqual(state["created_at"], "2026-08-02T10:00:00+00:00")
        self.assertEqual(state["migration"]["legacy_updated_at"], "2026-08-02T11:00:00+00:00")
        receipts = list((authority / "migration-receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text(encoding="utf-8"))["decision"], "migrated")

    def test_stopped_v1_migration_remains_stopped(self) -> None:
        legacy = self.data_dir / "legacy-stopped"
        authority = self.data_dir / "authority-stopped"
        self._write_legacy_budget(
            legacy,
            "wf-migrate-stopped",
            status="stopped",
            incidents=["prior-overrun"],
        )
        with self.assertRaises(BudgetLimitExceeded) as blocked:
            reserve_workflow_budget(
                authority,
                workflow_id="wf-migrate-stopped",
                workflow_max_cost_usd=0.02,
                call_max_cost_usd=0.003,
                reserved_cost_usd=0.001,
                legacy_data_dirs=(legacy,),
            )
        self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_stopped")
        state = json.loads(_state_path(authority, "wf-migrate-stopped").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "stopped")
        self.assertIn("prior-overrun", state["incidents"])

    def test_conflicting_authority_and_legacy_limits_fail_closed_with_receipt(self) -> None:
        legacy = self.data_dir / "legacy-conflict"
        authority = self.data_dir / "authority-conflict"
        original = reserve_workflow_budget(
            authority,
            workflow_id="wf-migrate-conflict",
            workflow_max_cost_usd=0.03,
            call_max_cost_usd=0.003,
            reserved_cost_usd=0.001,
        )
        release_workflow_reservation(authority, original)
        self._write_legacy_budget(legacy, "wf-migrate-conflict", maximum=0.02)
        with self.assertRaises(BudgetLimitExceeded) as blocked:
            reserve_workflow_budget(
                authority,
                workflow_id="wf-migrate-conflict",
                workflow_max_cost_usd=0.03,
                call_max_cost_usd=0.003,
                reserved_cost_usd=0.001,
                legacy_data_dirs=(legacy,),
            )
        self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_migration_conflict")
        receipt_path = Path(blocked.exception.incident["migration_receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["decision"], "blocked")
        self.assertEqual(receipt["reason"], "authority_and_legacy_identity_unproven")

    def test_conflicting_multiple_legacy_sources_fail_closed(self) -> None:
        legacy_a = self.data_dir / "legacy-source-a"
        legacy_b = self.data_dir / "legacy-source-b"
        authority = self.data_dir / "authority-multi-conflict"
        self._write_legacy_budget(legacy_a, "wf-migrate-multi", maximum=0.02, spent=0.004)
        self._write_legacy_budget(legacy_b, "wf-migrate-multi", maximum=0.02, spent=0.005)
        with self.assertRaises(BudgetLimitExceeded) as blocked:
            reserve_workflow_budget(
                authority,
                workflow_id="wf-migrate-multi",
                workflow_max_cost_usd=0.02,
                call_max_cost_usd=0.003,
                reserved_cost_usd=0.001,
                legacy_data_dirs=(legacy_a, legacy_b),
            )
        self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_migration_conflict")
        receipt = json.loads(Path(blocked.exception.incident["migration_receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["reason"], "conflicting_legacy_sources")
        self.assertEqual(len(receipt["source_fingerprints"]), 2)

    def test_migration_is_idempotent(self) -> None:
        legacy = self.data_dir / "legacy-idempotent"
        authority = self.data_dir / "authority-idempotent"
        self._write_legacy_budget(legacy, "wf-migrate-idempotent", spent=0.004)
        first = reserve_workflow_budget(
            authority,
            workflow_id="wf-migrate-idempotent",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.003,
            reserved_cost_usd=0.001,
            legacy_data_dirs=(legacy,),
        )
        release_workflow_reservation(authority, first)
        receipt_id = json.loads(_state_path(authority, "wf-migrate-idempotent").read_text(encoding="utf-8"))["migration"]["receipt_id"]
        second = reserve_workflow_budget(
            authority,
            workflow_id="wf-migrate-idempotent",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.003,
            reserved_cost_usd=0.001,
            legacy_data_dirs=(legacy,),
        )
        release_workflow_reservation(authority, second)
        state = json.loads(_state_path(authority, "wf-migrate-idempotent").read_text(encoding="utf-8"))
        self.assertEqual(state["migration"]["receipt_id"], receipt_id)
        self.assertEqual(len(list((authority / "migration-receipts").glob("*.json"))), 1)

    def test_non_finite_legacy_maximum_or_spent_blocks_with_receipt_and_incident(self) -> None:
        cases = (
            ("nan-spent", 0.02, float("nan")),
            ("inf-spent", 0.02, float("inf")),
            ("nan-maximum", float("nan"), 0.001),
            ("inf-maximum", float("inf"), 0.001),
        )
        for name, maximum, spent in cases:
            with self.subTest(name=name):
                legacy = self.data_dir / f"legacy-{name}"
                authority = self.data_dir / f"authority-{name}"
                workflow_id = f"wf-{name}"
                self._write_legacy_budget(legacy, workflow_id, maximum=maximum, spent=spent)
                with self.assertRaises(BudgetLimitExceeded) as blocked:
                    reserve_workflow_budget(
                        authority,
                        workflow_id=workflow_id,
                        workflow_max_cost_usd=0.02,
                        call_max_cost_usd=0.003,
                        reserved_cost_usd=0.001,
                        legacy_data_dirs=(legacy,),
                    )
                self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_migration_rejected")
                receipt = json.loads(Path(blocked.exception.incident["migration_receipt_path"]).read_text(encoding="utf-8"))
                self.assertEqual(receipt["decision"], "blocked")
                self.assertIn("finite", receipt["reason"])
                self.assertTrue(Path(blocked.exception.incident["incident_path"]).is_file())

    def test_non_finite_legacy_reservation_amounts_block_migration(self) -> None:
        cases = (
            ("reserved-nan", float("nan"), 0.003),
            ("reserved-inf", float("inf"), 0.003),
            ("call-nan", 0.001, float("nan")),
            ("call-inf", 0.001, float("inf")),
        )
        for name, reserved, call_max in cases:
            with self.subTest(name=name):
                legacy = self.data_dir / f"legacy-{name}"
                authority = self.data_dir / f"authority-{name}"
                workflow_id = f"wf-{name}"
                self._write_legacy_budget(
                    legacy,
                    workflow_id,
                    reservations={
                        "bad": {
                            "reserved_cost_usd": reserved,
                            "call_max_cost_usd": call_max,
                            "stage": "legacy",
                        }
                    },
                )
                with self.assertRaises(BudgetLimitExceeded) as blocked:
                    reserve_workflow_budget(
                        authority,
                        workflow_id=workflow_id,
                        workflow_max_cost_usd=0.02,
                        call_max_cost_usd=0.003,
                        reserved_cost_usd=0.001,
                        legacy_data_dirs=(legacy,),
                    )
                self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_migration_rejected")
                self.assertTrue(Path(blocked.exception.incident["migration_receipt_path"]).is_file())

    def test_non_finite_direct_reservation_inputs_cannot_create_workflow(self) -> None:
        valid = {
            "workflow_max_cost_usd": 0.02,
            "call_max_cost_usd": 0.003,
            "reserved_cost_usd": 0.001,
        }
        cases = (
            ("workflow-nan", "workflow_max_cost_usd", float("nan")),
            ("workflow-inf", "workflow_max_cost_usd", float("inf")),
            ("call-nan", "call_max_cost_usd", float("nan")),
            ("call-inf", "call_max_cost_usd", float("inf")),
            ("reserved-nan", "reserved_cost_usd", float("nan")),
            ("reserved-inf", "reserved_cost_usd", float("inf")),
        )
        for name, field, value in cases:
            with self.subTest(name=name):
                authority = self.data_dir / f"direct-{name}"
                amounts = dict(valid)
                amounts[field] = value
                with self.assertRaises(BudgetLimitExceeded) as blocked:
                    reserve_workflow_budget(
                        authority,
                        workflow_id=f"wf-direct-{name}",
                        stage="direct",
                        **amounts,
                    )
                self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_invalid_amount")
                self.assertFalse((authority / "workflow-budgets").exists())

    def test_non_finite_settlement_is_blocked_without_mutating_spend(self) -> None:
        for name, value in (("nan", float("nan")), ("inf", float("inf"))):
            with self.subTest(name=name):
                authority = self.data_dir / f"settle-{name}"
                workflow_id = f"wf-settle-{name}"
                reservation = reserve_workflow_budget(
                    authority,
                    workflow_id=workflow_id,
                    workflow_max_cost_usd=0.02,
                    call_max_cost_usd=0.003,
                    reserved_cost_usd=0.001,
                )
                with self.assertRaises(BudgetLimitExceeded) as blocked:
                    finalize_workflow_reservation(
                        authority,
                        reservation,
                        actual_or_estimated_cost_usd=value,
                    )
                self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_invalid_amount")
                state = json.loads(_state_path(authority, workflow_id).read_text(encoding="utf-8"))
                self.assertEqual(state["spent_usd"], 0.0)
                self.assertIn(reservation.reservation_id, state["reservations"])

    def test_non_finite_existing_authority_state_blocks_new_reservation(self) -> None:
        authority = self.data_dir / "authority-corrupt-v2"
        workflow_id = "wf-corrupt-v2"
        path = _state_path(authority, workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "smart_llm_router.workflow_budget.v2",
                    "workflow_id": workflow_id,
                    "budget_authority_id": "ba_test",
                    "workflow_max_cost_usd": 0.02,
                    "status": "active",
                    "spent_usd": float("nan"),
                    "reservations": {},
                    "incidents": [],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(BudgetLimitExceeded) as blocked:
            reserve_workflow_budget(
                authority,
                workflow_id=workflow_id,
                workflow_max_cost_usd=0.02,
                call_max_cost_usd=0.003,
                reserved_cost_usd=0.001,
            )
        self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_authority_state_invalid")

    def test_finite_settlement_overflow_stops_workflow_and_preserves_liability(self) -> None:
        authority = self.data_dir / "authority-finite-overflow"
        workflow_id = "wf-finite-overflow"
        reservation = reserve_workflow_budget(
            authority,
            workflow_id=workflow_id,
            workflow_max_cost_usd=1.7e308,
            call_max_cost_usd=1.7e308,
            reserved_cost_usd=1.0,
            stage="overflow",
        )
        path = _state_path(authority, workflow_id)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["spent_usd"] = 1e308
        path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaises(BudgetLimitExceeded) as blocked:
            finalize_workflow_reservation(
                authority,
                reservation,
                actual_or_estimated_cost_usd=1e308,
            )
        self.assertEqual(blocked.exception.incident["kind"], "workflow_budget_settlement_non_finite")
        self.assertEqual(blocked.exception.incident["decision"], "workflow_stopped")
        self.assertEqual(blocked.exception.incident["liability_lock"], "reservation_preserved")
        stopped = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["spent_usd"], 1e308)
        self.assertIn(reservation.reservation_id, stopped["reservations"])
        self.assertIn(blocked.exception.incident["incident_id"], stopped["incidents"])

        with self.assertRaises(BudgetLimitExceeded) as later:
            reserve_workflow_budget(
                authority,
                workflow_id=workflow_id,
                workflow_max_cost_usd=1.7e308,
                call_max_cost_usd=1.0,
                reserved_cost_usd=0.0,
                stage="later",
            )
        self.assertEqual(later.exception.incident["kind"], "workflow_budget_stopped")

    def test_reservation_variance_inside_authorization_warns_without_stopping(self) -> None:
        reservation = reserve_workflow_budget(
            self.data_dir,
            workflow_id="wf-variance",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.01,
            reserved_cost_usd=0.00563333,
            stage="research_enhance",
        )
        warning = finalize_workflow_reservation(
            self.data_dir,
            reservation,
            actual_or_estimated_cost_usd=0.00594,
        )
        self.assertIsNotNone(warning)
        self.assertEqual(warning["kind"], "reservation_estimate_variance")
        self.assertEqual(warning["decision"], "continue_reconciled")
        self.assertAlmostEqual(warning["variance_usd"], 0.00030667, places=8)
        state = json.loads(next((self.data_dir / "workflow-budgets").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "active")
        self.assertAlmostEqual(state["spent_usd"], 0.00594, places=8)
        self.assertFalse((self.data_dir / "budget-incidents").exists())

    def test_post_call_overrun_stops_workflow_and_emits_incident(self) -> None:
        reservation = reserve_workflow_budget(
            self.data_dir,
            workflow_id="wf-overrun",
            workflow_max_cost_usd=0.02,
            call_max_cost_usd=0.01,
            reserved_cost_usd=0.008,
            stage="audit",
        )
        incident = finalize_workflow_reservation(
            self.data_dir,
            reservation,
            actual_or_estimated_cost_usd=0.01780167,
        )
        self.assertIsNotNone(incident)
        self.assertIn("single_call_hard_limit_exceeded", incident["violations"])
        self.assertEqual(incident["decision"], "workflow_stopped")
        with self.assertRaises(BudgetLimitExceeded) as stopped:
            reserve_workflow_budget(
                self.data_dir,
                workflow_id="wf-overrun",
                workflow_max_cost_usd=0.02,
                call_max_cost_usd=0.01,
                reserved_cost_usd=0.001,
                stage="verify",
            )
        self.assertEqual(stopped.exception.incident["kind"], "workflow_budget_stopped")

    def test_provider_usage_overrun_is_not_returned_as_success(self) -> None:
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch(
                "smart_llm_router.router._call_openai_compatible",
                return_value=("audit result", {"prompt_tokens": 913, "completion_tokens": 3256}),
            ) as call:
                with self.assertRaisesRegex(RuntimeError, "超过硬预算上限"):
                    run_llm_task(
                        self.settings,
                        task="audit",
                        prompt="独立审计一份复杂治理计划",
                        prefer_free=False,
                        paid_fallback=True,
                        quality_target="frontier",
                        privacy="external_allowed",
                        provider="qwen-frontier-paid",
                        model="qwen3.7-max",
                        max_cost_usd=0.01,
                        max_output_tokens=1200,
                        workflow_id="wf-provider-overrun",
                        workflow_max_cost_usd=0.02,
                        workflow_stage="audit",
                    )
        self.assertEqual(call.call_count, 1)
        ledger = [json.loads(line) for line in (self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        incidents = [row for row in ledger if row.get("event") == "budget_incident"]
        self.assertEqual(len(incidents), 1)
        self.assertGreater(incidents[0]["estimated_cost_usd"], 0.01)

    def test_inconclusive_paid_output_settles_observed_provider_usage(self) -> None:
        failure = InconclusiveModelOutput(
            "qwen-frontier-paid/qwen3.7-max",
            reasoning_present=True,
            finish_reason="length",
            usage={"prompt_tokens": 100, "completion_tokens": 1800},
        )
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "所有模型调用失败"):
                    run_llm_task(
                        self.settings,
                        task="research_enhance",
                        prompt="研究增强",
                        prefer_free=False,
                        paid_fallback=True,
                        quality_target="frontier",
                        privacy="external_allowed",
                        provider="qwen-frontier-paid",
                        model="qwen3.7-max",
                        max_cost_usd=0.03,
                        max_output_tokens=2200,
                        workflow_id="wf-inconclusive-usage",
                        workflow_max_cost_usd=0.10,
                        workflow_stage="research_enhance",
                    )
        budget_state = json.loads(next((self.data_dir / "workflow-budgets").glob("*.json")).read_text(encoding="utf-8"))
        self.assertGreater(budget_state["spent_usd"], 0)
        self.assertEqual(budget_state["reservations"], {})
        ledger = json.loads((self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(ledger["cost_basis"], "provider_usage_on_rejected_output")
        self.assertGreater(ledger["estimated_cost_usd"], 0)

    def test_billable_rejected_output_inside_hard_limits_warns_and_keeps_workflow_active(self) -> None:
        failure = InconclusiveModelOutput(
            "qwen-frontier-paid/qwen3.7-max",
            reasoning_present=True,
            finish_reason="length",
            usage={"prompt_tokens": 1458, "completion_tokens": 702},
        )
        admitted_budget = {
            "eligible": True,
            "projected_cost_usd": 0.00563333,
            "reserved_output_tokens": 710,
            "reason": None,
        }
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch("smart_llm_router.router._budget_status", return_value=admitted_budget):
                with patch("smart_llm_router.router._call_openai_compatible", side_effect=failure):
                    with self.assertRaisesRegex(RuntimeError, "所有模型调用失败"):
                        run_llm_task(
                            self.settings,
                            task="research_enhance",
                            prompt="研究增强",
                            prefer_free=False,
                            paid_fallback=True,
                            quality_target="frontier",
                            privacy="external_allowed",
                            provider="qwen-frontier-paid",
                            model="qwen3.7-max",
                            max_cost_usd=0.01,
                            max_output_tokens=700,
                            workflow_id="wf-rejected-inside-auth",
                            workflow_max_cost_usd=0.02,
                            workflow_stage="research_enhance",
                        )
        state = json.loads(next((self.data_dir / "workflow-budgets").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "active")
        self.assertAlmostEqual(state["spent_usd"], 0.00594, places=8)
        rows = [json.loads(line) for line in (self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["event"] for row in rows[-2:]], ["model_failure", "budget_warning"])
        self.assertEqual(rows[-2]["cost_basis"], "provider_usage_on_rejected_output")
        self.assertEqual(rows[-1]["decision"], "continue_reconciled")
        self.assertFalse((self.data_dir / "budget-incidents").exists())

    def test_research_enhance_allocates_qwen_reasoning_and_final_answer_tokens(self) -> None:
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch(
                "smart_llm_router.router._call_openai_compatible",
                return_value=("research result", {"prompt_tokens": 100, "completion_tokens": 600}),
            ) as call:
                run_llm_task(
                    self.settings,
                    task="research_enhance",
                    prompt="研究增强",
                    prefer_free=False,
                    paid_fallback=True,
                    quality_target="frontier",
                    privacy="external_allowed",
                    provider="qwen-frontier-paid",
                    model="qwen3.7-max",
                    max_cost_usd=0.01,
                    max_output_tokens=1200,
                )
        kwargs = call.call_args.kwargs
        self.assertTrue(kwargs["enable_thinking"])
        self.assertEqual(kwargs["thinking_budget_tokens"], 800)
        self.assertEqual(kwargs["max_tokens"], 1200)
        ledger = json.loads((self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(ledger["thinking_plan"]["final_answer_reserve_tokens"], 400)

    def test_no_think_marker_disables_qwen_thinking_and_is_removed_from_prompt(self) -> None:
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch(
                "smart_llm_router.router._call_openai_compatible",
                return_value=("result", {"prompt_tokens": 50, "completion_tokens": 50}),
            ) as call:
                run_llm_task(
                    self.settings,
                    task="research_enhance",
                    prompt="研究增强 /no_think",
                    prefer_free=False,
                    paid_fallback=True,
                    quality_target="frontier",
                    privacy="external_allowed",
                    provider="qwen-frontier-paid",
                    model="qwen3.7-max",
                    max_cost_usd=0.01,
                    max_output_tokens=600,
                )
        self.assertFalse(call.call_args.kwargs["enable_thinking"])
        sent_prompt = call.call_args.kwargs["messages"][-1]["content"]
        self.assertNotIn("/no_think", str(sent_prompt))

    def test_inconclusive_reasoning_without_usage_settles_reserved_worst_case(self) -> None:
        failure = InconclusiveModelOutput(
            "qwen-frontier-paid/qwen3.7-max",
            reasoning_present=True,
            finish_reason="length",
        )
        with patch.dict(os.environ, {"QWEN_KEY": "test", "SMART_LLM_CACHE": "false"}, clear=True):
            with patch("smart_llm_router.router._call_openai_compatible", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "所有模型调用失败"):
                    run_llm_task(
                        self.settings,
                        task="research_enhance",
                        prompt="研究增强",
                        prefer_free=False,
                        paid_fallback=True,
                        quality_target="frontier",
                        privacy="external_allowed",
                        provider="qwen-frontier-paid",
                        model="qwen3.7-max",
                        max_cost_usd=0.03,
                        max_output_tokens=2200,
                        workflow_id="wf-inconclusive-reserve",
                        workflow_max_cost_usd=0.10,
                        workflow_stage="research_enhance",
                    )
        budget_state = json.loads(next((self.data_dir / "workflow-budgets").glob("*.json")).read_text(encoding="utf-8"))
        self.assertGreater(budget_state["spent_usd"], 0)
        ledger = json.loads((self.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(ledger["cost_basis"], "reserved_worst_case_without_provider_usage")
        self.assertEqual(ledger["estimated_cost_usd"], ledger["reserved_cost_usd"])


if __name__ == "__main__":
    unittest.main()
