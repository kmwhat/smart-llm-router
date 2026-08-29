import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from smart_llm_router.budget import _state_path, finalize_workflow_reservation
from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    InconclusiveModelOutput,
    LLMChoice,
    ProviderRequestRejected,
    _cache_key,
    _call_openai_compatible,
    _estimated_cost_usd,
    _required_structured_output_spec,
    _validate_structured_output,
    describe_task_v2,
    run_llm_task,
)


def completion_usage(*, prompt_tokens: int, completion_tokens: int, finish_reason: str) -> dict:
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "_completion_metadata": {
            "finish_reason": finish_reason,
            "output_reached_requested_token_limit": completion_tokens >= 100,
        },
    }


class GovernedStructuredOutputTests(unittest.TestCase):
    @staticmethod
    def _audit_schema() -> dict:
        fixture = Path(__file__).parent / "fixtures" / "independent_audit_output_contract.json"
        return json.loads(fixture.read_text(encoding="utf-8"))

    def _settings(self, root: Path, providers: tuple[LLMProvider, ...]) -> Settings:
        return Settings(
            data_dir=root,
            providers=providers,
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            budget_authority_dir=root / "budget-authority",
        )

    def test_adversarial_structured_validation_matrix(self) -> None:
        self.assertEqual(
            _validate_structured_output('{"decision":"pass"}', "json", finish_reason="length"),
            (False, "structured_output_truncated_finish_reason_length"),
        )
        self.assertEqual(
            _validate_structured_output('{"decision":"pass"', "json", output_reached_cap=True),
            (False, "structured_output_truncated_at_output_cap"),
        )
        self.assertEqual(
            _validate_structured_output('{"decision":"pass"', "json"),
            (False, "structured_output_not_one_complete_raw_json_object"),
        )
        self.assertEqual(
            _validate_structured_output('```json\n{"decision":"pass"}\n```', "json"),
            (False, "structured_output_code_fence_forbidden"),
        )
        self.assertEqual(
            _validate_structured_output('{"decision":"pass"}', "json", required_fields=["decision", "blocking_findings"]),
            (False, "structured_output_missing_required_fields"),
        )
        self.assertEqual(
            _validate_structured_output('{"decision":"pass","blocking_findings":[]}', "json", finish_reason="stop", required_fields=["decision", "blocking_findings"]),
            (True, None),
        )

    def test_governed_json_allows_only_stop_or_absent_finish_metadata(self) -> None:
        content = '{"decision":"pass","blocking_findings":[]}'
        for finish_reason in ("content_filter", "tool_calls", "function_call", "other"):
            with self.subTest(finish_reason=finish_reason):
                self.assertEqual(
                    _validate_structured_output(content, "json", finish_reason=finish_reason),
                    (False, "structured_output_nonterminal_finish_reason"),
                )
        self.assertEqual(_validate_structured_output(content, "json", finish_reason="stop"), (True, None))
        self.assertEqual(_validate_structured_output(content, "json", finish_reason=None), (True, None))

    def test_nonterminal_finish_reasons_are_terminal_without_side_effects(self) -> None:
        provider = LLMProvider(
            "qwen-frontier-paid",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "QWEN_KEY",
            ("qwen3.7-max", "qwen3.7-plus"),
            False,
            1,
            "paid",
        )
        content = '{"decision":"pass","blocking_findings":[]}'
        for finish_reason in ("content_filter", "tool_calls", "function_call", "other"):
            with self.subTest(finish_reason=finish_reason), tempfile.TemporaryDirectory() as tmp:
                settings = self._settings(Path(tmp), (provider,))
                response = (content, completion_usage(prompt_tokens=20, completion_tokens=8, finish_reason=finish_reason))
                with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "SMART_LLM_CACHE": "true"}, clear=True):
                    with patch("smart_llm_router.router._call_openai_compatible", return_value=response) as send:
                        with self.assertRaisesRegex(RuntimeError, "governed structured output invalid"):
                            run_llm_task(
                                settings,
                                task="audit",
                                prompt="synthetic governed audit",
                                prefer_free=False,
                                paid_fallback=True,
                                quality_target="frontier",
                                privacy="external_allowed",
                                provider="qwen-frontier-paid",
                                model="qwen3.7-max",
                                max_cost_usd=0.01,
                                max_output_tokens=100,
                            )
                ledger = [json.loads(line) for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(send.call_count, 1)
                self.assertEqual([row["event"] for row in ledger], ["invalid_structured_output"])
                self.assertEqual(ledger[0]["output_error"], "structured_output_nonterminal_finish_reason")
                self.assertFalse((settings.data_dir / "llm_response_cache.json").exists())
                self.assertFalse((settings.data_dir / "llm_router_state.json").exists())

    def test_audit_and_context_schema_require_raw_json(self) -> None:
        complexity = {"shadow_descriptor_v2": {"features": {"structured_output_required": False}}}
        audit = _required_structured_output_spec(complexity, "Review this evidence", task="audit")
        schema = _required_structured_output_spec(
            complexity,
            "Return the result",
            task="qa",
            context='JSON Schema: {"type":"object","required":["decision","blocking_findings"]}',
        )
        self.assertTrue(audit["required"])
        self.assertTrue(schema["schema_driven"])
        self.assertEqual(schema["required_fields"], ["decision", "blocking_findings"])

    def test_nested_schema_required_fields_preserve_object_scope(self) -> None:
        complexity = {"shadow_descriptor_v2": {"features": {"structured_output_required": False}}}
        context = (
            'JSON Schema: {"type":"object","required":["payload"],'
            '"properties":{"payload":{"type":"object","required":["decision"],'
            '"properties":{"decision":{"type":"string"}}}}}'
        )
        spec = _required_structured_output_spec(complexity, "Return the result", task="qa", context=context)

        self.assertEqual(spec["required_fields"], ["payload"])
        self.assertEqual(
            _validate_structured_output(
                '{"payload":{"decision":"pass"}}',
                spec["format"],
                required_fields=spec["required_fields"],
                schema=spec["schema"],
            ),
            (True, None),
        )
        self.assertEqual(
            _validate_structured_output(
                '{"payload":{}}',
                spec["format"],
                required_fields=spec["required_fields"],
                schema=spec["schema"],
            ),
            (False, "structured_output_missing_required_fields"),
        )
        self.assertEqual(
            _validate_structured_output(
                '{"decision":"pass"}',
                spec["format"],
                required_fields=spec["required_fields"],
                schema=spec["schema"],
            ),
            (False, "structured_output_missing_required_fields"),
        )

    def test_empty_reasoning_only_audit_is_terminal_and_settled_once(self) -> None:
        providers = (
            LLMProvider("qwen-frontier-paid", "https://qwen.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid"),
            LLMProvider("deepseek-direct-paid", "https://deepseek.test/v1", "DEEPSEEK_KEY", ("deepseek-v4-pro",), False, 2, "paid"),
        )
        first_usage = {"prompt_tokens": 100, "completion_tokens": 100}
        first = InconclusiveModelOutput(
            "synthetic/first",
            reasoning_present=True,
            finish_reason="length",
            usage=first_usage,
        )
        second = ('{"decision":"pass","blocking_findings":[]}', completion_usage(prompt_tokens=10, completion_tokens=10, finish_reason="stop"))
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), providers)
            workflow_id = "synthetic-empty-governed-output"
            with patch.dict(
                os.environ,
                {"QWEN_KEY": "synthetic", "DEEPSEEK_KEY": "synthetic", "SMART_LLM_CACHE": "true"},
                clear=True,
            ):
                with patch("smart_llm_router.router._call_openai_compatible", side_effect=[first, second]) as send, patch(
                    "smart_llm_router.router.finalize_workflow_reservation", wraps=finalize_workflow_reservation
                ) as finalize, patch("smart_llm_router.router.release_workflow_reservation") as release:
                    with self.assertRaisesRegex(RuntimeError, "governed structured output invalid"):
                        run_llm_task(
                            settings,
                            task="audit",
                            prompt="Review this synthetic evidence",
                            prefer_free=False,
                            paid_fallback=True,
                            quality_target="frontier",
                            privacy="external_allowed",
                            max_cost_usd=0.01,
                            max_output_tokens=100,
                            workflow_id=workflow_id,
                            workflow_max_cost_usd=0.02,
                            workflow_stage="audit",
                        )
            ledger = [json.loads(line) for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            state = json.loads(_state_path(settings.budget_authority_dir, workflow_id).read_text(encoding="utf-8"))
            cache_exists = (settings.data_dir / "llm_response_cache.json").exists()
            route_state_exists = (settings.data_dir / "llm_router_state.json").exists()
            used_provider = next(provider for provider in providers if provider.name == ledger[0]["provider"])
            expected_cost = _estimated_cost_usd(LLMChoice(used_provider, ledger[0]["model"]), 100, 100)

        self.assertEqual(send.call_count, 1)
        self.assertEqual(finalize.call_count, 1)
        release.assert_not_called()
        self.assertEqual([row["event"] for row in ledger], ["invalid_structured_output"])
        self.assertAlmostEqual(ledger[0]["estimated_cost_usd"], expected_cost)
        self.assertTrue(ledger[0]["reservation_settled"])
        self.assertAlmostEqual(state["spent_usd"], expected_cost)
        self.assertEqual(state["reservations"], {})
        self.assertFalse(cache_exists)
        self.assertFalse(route_state_exists)

    def test_paid_empty_without_usage_or_reasoning_settles_reserved_liability_once(self) -> None:
        provider = LLMProvider(
            "qwen-frontier-paid",
            "https://qwen.test/v1",
            "QWEN_KEY",
            ("qwen3.7-max",),
            False,
            1,
            "paid",
        )
        failure = InconclusiveModelOutput(
            "synthetic/paid-empty",
            reasoning_present=False,
            finish_reason="length",
            usage={},
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            workflow_id = "synthetic-paid-empty-no-usage"
            with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "SMART_LLM_CACHE": "false"}, clear=True):
                with patch("smart_llm_router.router._call_openai_compatible", side_effect=failure) as send, patch(
                    "smart_llm_router.router.finalize_workflow_reservation", wraps=finalize_workflow_reservation
                ) as finalize, patch("smart_llm_router.router.release_workflow_reservation") as release:
                    with self.assertRaisesRegex(RuntimeError, "governed structured output invalid"):
                        run_llm_task(
                            settings,
                            task="audit",
                            prompt="Review synthetic evidence",
                            prefer_free=False,
                            paid_fallback=True,
                            quality_target="frontier",
                            privacy="external_allowed",
                            provider="qwen-frontier-paid",
                            model="qwen3.7-max",
                            max_cost_usd=0.01,
                            max_output_tokens=100,
                            workflow_id=workflow_id,
                            workflow_max_cost_usd=0.02,
                            workflow_stage="audit",
                        )
            state = json.loads(_state_path(settings.budget_authority_dir, workflow_id).read_text(encoding="utf-8"))
            ledger = [json.loads(line) for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            cache_exists = (settings.data_dir / "llm_response_cache.json").exists()
            route_state_exists = (settings.data_dir / "llm_router_state.json").exists()

        self.assertEqual(send.call_count, 1)
        self.assertEqual(finalize.call_count, 1)
        release.assert_not_called()
        self.assertEqual([row["event"] for row in ledger], ["invalid_structured_output"])
        self.assertGreater(state["spent_usd"], 0)
        self.assertEqual(state["reservations"], {})
        self.assertGreater(ledger[0]["estimated_cost_usd"], 0)
        self.assertEqual(ledger[0]["settlement_basis"], "reserved_worst_case_without_provider_usage")
        self.assertTrue(ledger[0]["reservation_settled"])
        self.assertFalse(cache_exists)
        self.assertFalse(route_state_exists)

    def test_ordinary_nonstructured_empty_output_keeps_resilience(self) -> None:
        providers = (
            LLMProvider("free-first", "https://first.test/v1", "FIRST_KEY", ("model-a",), True, 1, "permanent_free"),
            LLMProvider("free-second", "https://second.test/v1", "SECOND_KEY", ("model-b",), True, 2, "permanent_free"),
        )
        first = InconclusiveModelOutput("synthetic/first", reasoning_present=True, finish_reason="length", usage={})
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), providers)
            with patch.dict(os.environ, {"FIRST_KEY": "synthetic", "SECOND_KEY": "synthetic", "SMART_LLM_CACHE": "false"}, clear=True):
                with patch(
                    "smart_llm_router.router._call_openai_compatible",
                    side_effect=[first, ("ordinary success", completion_usage(prompt_tokens=5, completion_tokens=2, finish_reason="stop"))],
                ) as send:
                    result = run_llm_task(
                        settings,
                        task="qa",
                        prompt="ordinary unstructured response",
                        prefer_free=True,
                        paid_fallback=False,
                        privacy="external_allowed",
                    )
            ledger = [json.loads(line) for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(send.call_count, 2)
        self.assertEqual(result.content, "ordinary success")
        self.assertEqual([row["event"] for row in ledger], ["model_failure", "model_call"])

    def test_invalid_audit_is_terminal_non_success_and_zero_cache(self) -> None:
        provider = LLMProvider(
            "qwen-frontier-paid",
            "https://qwen.test/v1",
            "QWEN_KEY",
            ("qwen3.7-max", "qwen3.7-plus"),
            False,
            1,
            "paid",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            response = (
                '{"decision":"pass"',
                completion_usage(prompt_tokens=100, completion_tokens=100, finish_reason="length"),
            )
            with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "SMART_LLM_CACHE": "true"}, clear=True):
                with patch("smart_llm_router.router._call_openai_compatible", return_value=response) as send:
                    with self.assertRaisesRegex(RuntimeError, "governed structured output invalid"):
                        run_llm_task(
                            settings,
                            task="audit",
                            prompt="synthetic governed audit",
                            prefer_free=False,
                            paid_fallback=True,
                            quality_target="frontier",
                            privacy="external_allowed",
                            provider="qwen-frontier-paid",
                            model="qwen3.7-max",
                            max_cost_usd=0.01,
                            max_output_tokens=100,
                        )
            ledger = [json.loads(line) for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            cache_exists = (settings.data_dir / "llm_response_cache.json").exists()
            route_state_exists = (settings.data_dir / "llm_router_state.json").exists()

        self.assertEqual(send.call_count, 1)
        self.assertEqual(ledger[-1]["event"], "invalid_structured_output")
        self.assertNotIn("model_call", [row["event"] for row in ledger])
        self.assertEqual(ledger[-1]["completion_metadata"]["finish_reason"], "length")
        self.assertTrue(ledger[-1]["completion_metadata"]["output_reached_requested_token_limit"])
        self.assertFalse(cache_exists)
        self.assertFalse(route_state_exists)

    def test_valid_audit_and_ordinary_nonstructured_task_do_not_regress(self) -> None:
        paid = LLMProvider("qwen-frontier-paid", "https://dashscope.aliyuncs.com/compatible-mode/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid")
        free = LLMProvider("current-free", "https://free.test/v1", "FREE_KEY", ("model-a",), True, 1, "permanent_free")
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (paid, free))
            with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "FREE_KEY": "synthetic", "SMART_LLM_CACHE": "false"}, clear=True):
                with patch(
                    "smart_llm_router.router._call_openai_compatible",
                    side_effect=[
                        ('{"decision":"pass","blocking_findings":[]}', completion_usage(prompt_tokens=20, completion_tokens=8, finish_reason="stop")),
                        ("ordinary text remains valid", completion_usage(prompt_tokens=5, completion_tokens=100, finish_reason="length")),
                    ],
                ):
                    audit = run_llm_task(
                        settings,
                        task="audit",
                        prompt="synthetic audit",
                        context='JSON Schema: {"required":["decision","blocking_findings"]}',
                        prefer_free=False,
                        paid_fallback=True,
                        quality_target="frontier",
                        privacy="external_allowed",
                        provider="qwen-frontier-paid",
                        model="qwen3.7-max",
                        max_cost_usd=0.01,
                        max_output_tokens=100,
                    )
                    ordinary = run_llm_task(
                        settings,
                        task="qa",
                        prompt="ordinary unstructured response",
                        prefer_free=True,
                        paid_fallback=False,
                        privacy="external_allowed",
                        provider="current-free",
                        model="model-a",
                        max_output_tokens=100,
                    )

        self.assertEqual(audit.content, '{"decision":"pass","blocking_findings":[]}')
        self.assertEqual(ordinary.content, "ordinary text remains valid")

    def test_invalid_paid_output_settles_actual_usage_exactly_once(self) -> None:
        provider = LLMProvider("qwen-frontier-paid", "https://qwen.test/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid")
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            workflow_id = "synthetic-invalid-output-settlement"
            usage = completion_usage(prompt_tokens=100, completion_tokens=20, finish_reason="length")
            expected_cost = _estimated_cost_usd(LLMChoice(provider, "qwen3.7-max"), 100, 20)
            with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "SMART_LLM_CACHE": "false"}, clear=True):
                with patch("smart_llm_router.router._call_openai_compatible", return_value=('{"decision":"pass"}', usage)), patch(
                    "smart_llm_router.router.finalize_workflow_reservation", wraps=finalize_workflow_reservation
                ) as finalize, patch("smart_llm_router.router.release_workflow_reservation") as release:
                    with self.assertRaisesRegex(RuntimeError, "governed structured output invalid"):
                        run_llm_task(
                            settings,
                            task="audit",
                            prompt="synthetic billed invalid output",
                            prefer_free=False,
                            paid_fallback=True,
                            quality_target="frontier",
                            privacy="external_allowed",
                            provider="qwen-frontier-paid",
                            model="qwen3.7-max",
                            max_cost_usd=0.01,
                            max_output_tokens=100,
                            workflow_id=workflow_id,
                            workflow_max_cost_usd=0.02,
                            workflow_stage="audit",
                        )
            state = json.loads(_state_path(settings.budget_authority_dir, workflow_id).read_text(encoding="utf-8"))
            ledger = [json.loads(line) for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(finalize.call_count, 1)
        release.assert_not_called()
        self.assertAlmostEqual(state["spent_usd"], expected_cost)
        self.assertEqual(state["reservations"], {})
        invalid = next(row for row in ledger if row["event"] == "invalid_structured_output")
        self.assertAlmostEqual(invalid["estimated_cost_usd"], expected_cost)
        self.assertTrue(invalid["reservation_settled"])
        self.assertEqual(invalid["settlement_basis"], "provider_usage")

    def test_explicit_schema_survives_classification_and_cache_identity(self) -> None:
        schema = self._audit_schema()
        descriptor = describe_task_v2(
            "qa",
            "Review the public synthetic evidence.",
            structured_output_required=True,
        )
        self.assertTrue(descriptor["features"]["structured_output_required"])
        common = {
            "task": "qa",
            "prompt": "Review the public synthetic evidence.",
            "context": None,
            "prefer_free": True,
            "paid_fallback": False,
            "temperature": 0.2,
        }
        first = _cache_key(**common, structured_output_schema_fingerprint="schema-a")
        second = _cache_key(**common, structured_output_schema_fingerprint="schema-b")
        self.assertNotEqual(first, second)
        spec = _required_structured_output_spec(
            {"shadow_descriptor_v2": descriptor},
            "Review the public synthetic evidence.",
            task="qa",
            explicit_schema=schema,
        )
        self.assertTrue(spec["schema_driven"])
        self.assertEqual(
            spec["required_fields"],
            ["verdict", "release_blocker", "findings", "confidence"],
        )

    def test_explicit_schema_conflict_fails_closed(self) -> None:
        schema = self._audit_schema()
        with self.assertRaisesRegex(ValueError, "governed_json_schema_conflict:blocked_before_send"):
            _required_structured_output_spec(
                {"shadow_descriptor_v2": {"features": {"structured_output_required": True}}},
                'JSON Schema: {"type":"object","required":["different"]}',
                task="audit",
                explicit_schema=schema,
            )

    def test_qwen_native_json_schema_payload_and_final_answer_reserve(self) -> None:
        provider = LLMProvider(
            "qwen-frontier-paid",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "QWEN_KEY",
            ("qwen3.7-max",),
            False,
            1,
            "paid",
        )
        schema = self._audit_schema()
        valid = json.dumps(
            {
                "verdict": "ACCEPT",
                "release_blocker": False,
                "findings": ["synthetic fixture is complete"],
                "confidence": "high",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "SMART_LLM_CACHE": "false"}, clear=True):
                with patch("smart_llm_router.router._call_openai_compatible", return_value=(valid, completion_usage(prompt_tokens=20, completion_tokens=20, finish_reason="stop"))) as send:
                    result = run_llm_task(
                        settings,
                        task="audit",
                        prompt="Review public synthetic policy evidence.",
                        context=("Public synthetic policy sentence. " * 2000)[:44496],
                        prefer_free=False,
                        paid_fallback=True,
                        quality_target="frontier",
                        privacy="external_allowed",
                        provider="qwen-frontier-paid",
                        model="qwen3.7-max",
                        max_cost_usd=0.05,
                        max_output_tokens=300,
                        structured_output_schema=schema,
                    )
        self.assertEqual(result.content, valid)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(kwargs["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(kwargs["thinking_budget_tokens"], 172)
        self.assertEqual(kwargs["max_tokens"], 300)

    def test_direct_qwen_transports_schema_and_unsupported_route_blocks_before_key(self) -> None:
        schema = self._audit_schema()
        original_schema = json.loads(json.dumps(schema))
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "smart_llm_router_output", "strict": True, "schema": schema},
        }
        qwen = LLMChoice(
            LLMProvider("qwen-frontier-paid", "https://dashscope.aliyuncs.com/compatible-mode/v1", "QWEN_KEY", ("qwen3.7-plus",), False, 1, "paid"),
            "qwen3.7-plus",
        )
        with patch.dict(os.environ, {"QWEN_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                response = client_class.return_value.__enter__.return_value.post.return_value
                response.json.return_value = {
                    "choices": [{"message": {"content": '{"verdict":"ACCEPT","release_blocker":false,"findings":["ok"],"confidence":"high"}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                }
                response.headers = {}
                _call_openai_compatible(
                    qwen,
                    messages=[{"role": "user", "content": "public synthetic"}],
                    timeout=1,
                    temperature=0.2,
                    max_tokens=100,
                    response_format=response_format,
                )
                payload = client_class.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        provider_schema = payload["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema, original_schema)
        self.assertEqual(provider_schema["type"], "object")
        self.assertEqual(provider_schema["required"], schema["required"])
        self.assertFalse(provider_schema["additionalProperties"])
        self.assertNotIn("$schema", provider_schema)
        self.assertNotIn("title", provider_schema)
        findings = provider_schema["properties"]["findings"]
        self.assertEqual(findings["type"], "array")
        self.assertEqual(findings["items"], {"type": "string"})
        for keyword in ("minItems", "maxItems", "uniqueItems"):
            self.assertNotIn(keyword, findings)

        with patch.dict(os.environ, {"QWEN_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                response = client_class.return_value.__enter__.return_value.post.return_value
                response.json.return_value = {
                    "choices": [{"message": {"content": '{"verdict":"ACCEPT","release_blocker":false,"findings":["ok"],"confidence":"high"}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                }
                response.headers = {}
                _, usage = _call_openai_compatible(
                    qwen,
                    messages=[{"role": "user", "content": "public synthetic"}],
                    timeout=1,
                    temperature=0.2,
                    max_tokens=100,
                    enable_thinking=False,
                    response_format=response_format,
                )
                payload = client_class.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertIs(payload["enable_thinking"], False)
        self.assertNotIn("thinking_budget", payload)
        routing = usage["_routing_metadata"]
        self.assertTrue(routing["provider_schema_projected"])
        self.assertEqual(routing["provider_schema_projection_version"], "qwen-json-schema-v1")
        self.assertRegex(routing["provider_schema_fingerprint"], r"^[0-9a-f]{64}$")

        unsupported = LLMChoice(
            LLMProvider("gemini-paid", "https://gemini.test/v1", "MISSING_KEY", ("gemini-2.5-pro",), False, 1, "paid"),
            "gemini-2.5-pro",
        )
        with patch.dict(os.environ, {}, clear=True), patch("smart_llm_router.router.httpx.Client") as client_class:
            with self.assertRaisesRegex(RuntimeError, "provider_native_structured_output_unsupported.*blocked_before_send"):
                _call_openai_compatible(
                    unsupported,
                    messages=[{"role": "user", "content": "public synthetic"}],
                    timeout=1,
                    temperature=0.2,
                    response_format=response_format,
                )
        client_class.assert_not_called()

    def test_qwen_schema_http_400_is_sanitized_and_does_not_expose_body(self) -> None:
        schema = self._audit_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "smart_llm_router_output", "strict": True, "schema": schema},
        }
        qwen = LLMChoice(
            LLMProvider("qwen-frontier-paid", "https://dashscope.aliyuncs.com/compatible-mode/v1", "QWEN_KEY", ("qwen3.7-max",), False, 1, "paid"),
            "qwen3.7-max",
        )
        request = httpx.Request("POST", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        rejected = httpx.Response(
            400,
            request=request,
            json={
                "error": {
                    "code": "InvalidParameter.ResponseFormat",
                    "type": "invalid_request_error",
                    "param": "response_format",
                    "message": "JSON schema invalid; never persist sk-private-secret-value",
                }
            },
        )
        with patch.dict(os.environ, {"QWEN_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = rejected
                with self.assertRaises(ProviderRequestRejected) as caught:
                    _call_openai_compatible(
                        qwen,
                        messages=[{"role": "user", "content": "public synthetic"}],
                        timeout=1,
                        temperature=0.2,
                        max_tokens=100,
                        enable_thinking=False,
                        response_format=response_format,
                    )
        evidence = caught.exception.evidence()
        self.assertEqual(evidence["status_code"], 400)
        self.assertEqual(evidence["reason"], "structured_output_constraint")
        self.assertEqual(evidence["error_code"], "InvalidParameter.ResponseFormat")
        self.assertEqual(evidence["error_type"], "invalid_request_error")
        self.assertEqual(evidence["error_param"], "response_format")
        self.assertTrue(evidence["provider_schema_projected"])
        self.assertNotIn("private-secret", str(caught.exception))
        self.assertNotIn("private-secret", json.dumps(evidence))

        billing = httpx.Response(
            400,
            request=request,
            json={"error": {"code": "Arrearage", "message": "account billing state"}},
        )
        with patch.dict(os.environ, {"QWEN_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = billing
                with self.assertRaises(httpx.HTTPStatusError):
                    _call_openai_compatible(
                        qwen,
                        messages=[{"role": "user", "content": "public synthetic"}],
                        timeout=1,
                        temperature=0.2,
                        response_format=response_format,
                    )

    def test_qwen_schema_rejection_ledger_is_sanitized_zero_cost_and_no_cooldown(self) -> None:
        provider = LLMProvider(
            "qwen-frontier-paid",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "QWEN_KEY",
            ("qwen3.7-max",),
            False,
            1,
            "paid",
        )
        rejection = ProviderRequestRejected(
            400,
            reason="structured_output_constraint",
            error_code="InvalidParameter.ResponseFormat",
            error_type="invalid_request_error",
            error_param="response_format",
            provider_schema_projected=True,
            provider_schema_fingerprint="a" * 64,
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), (provider,))
            with patch.dict(os.environ, {"QWEN_KEY": "synthetic", "SMART_LLM_CACHE": "false"}, clear=True):
                with patch("smart_llm_router.router._call_openai_compatible", side_effect=rejection) as send:
                    with self.assertRaisesRegex(RuntimeError, "所有模型调用失败"):
                        run_llm_task(
                            settings,
                            task="audit",
                            prompt="Review public synthetic evidence.",
                            prefer_free=False,
                            paid_fallback=True,
                            quality_target="frontier",
                            privacy="external_allowed",
                            provider="qwen-frontier-paid",
                            model="qwen3.7-max",
                            max_cost_usd=0.01,
                            max_output_tokens=100,
                            structured_output_schema=self._audit_schema(),
                            workflow_id="synthetic-qwen-schema-rejection",
                            workflow_max_cost_usd=0.01,
                            workflow_stage="audit",
                        )
            ledger = [
                json.loads(line)
                for line in (settings.data_dir / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            state = json.loads(
                _state_path(settings.budget_authority_dir, "synthetic-qwen-schema-rejection").read_text(
                    encoding="utf-8"
                )
            )
            route_state_exists = (settings.data_dir / "llm_router_state.json").exists()
        self.assertEqual(send.call_count, 1)
        self.assertEqual([row["event"] for row in ledger], ["model_failure"])
        self.assertEqual(ledger[0]["failure_class"], "provider_request_rejected")
        self.assertFalse(ledger[0]["health_cooldown_recorded"])
        self.assertEqual(ledger[0]["provider_request_rejection"], rejection.evidence())
        self.assertIsNone(ledger[0]["estimated_cost_usd"])
        self.assertEqual(state["spent_usd"], 0.0)
        self.assertEqual(state["reservations"], {})
        self.assertFalse(route_state_exists)

    def test_qwen_projection_keeps_full_local_schema_authoritative(self) -> None:
        schema = self._audit_schema()
        invalid = json.dumps(
            {
                "verdict": "ACCEPT",
                "release_blocker": False,
                "findings": [],
                "confidence": "high",
            }
        )
        self.assertEqual(
            _validate_structured_output(invalid, "json", finish_reason="stop", schema=schema),
            (False, "structured_output_schema_validation_failed"),
        )

    def test_qwen_unprojectable_combinator_blocks_before_key_and_http(self) -> None:
        schema = {
            "type": "object",
            "allOf": [{"required": ["verdict"], "properties": {"verdict": {"type": "string"}}}],
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "smart_llm_router_output", "strict": True, "schema": schema},
        }
        qwen = LLMChoice(
            LLMProvider("qwen-frontier-paid", "https://dashscope.aliyuncs.com/compatible-mode/v1", "MISSING_KEY", ("qwen3.7-max",), False, 1, "paid"),
            "qwen3.7-max",
        )
        with patch.dict(os.environ, {}, clear=True), patch("smart_llm_router.router.httpx.Client") as client_class:
            with self.assertRaisesRegex(RuntimeError, "qwen_provider_schema_projection_unsupported.*blocked_before_send"):
                _call_openai_compatible(
                    qwen,
                    messages=[{"role": "user", "content": "public synthetic"}],
                    timeout=1,
                    temperature=0.2,
                    response_format=response_format,
                )
        client_class.assert_not_called()

        third_party_qwen = LLMChoice(
            LLMProvider("qwen-compatible-paid", "https://third-party.test/v1", "MISSING_KEY", ("qwen3.7-max",), False, 1, "paid"),
            "qwen3.7-max",
        )
        with patch.dict(os.environ, {}, clear=True), patch("smart_llm_router.router.httpx.Client") as client_class:
            with self.assertRaisesRegex(RuntimeError, "provider_native_structured_output_unsupported.*blocked_before_send"):
                _call_openai_compatible(
                    third_party_qwen,
                    messages=[{"role": "user", "content": "public synthetic"}],
                    timeout=1,
                    temperature=0.2,
                    response_format=response_format,
                )
        client_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
