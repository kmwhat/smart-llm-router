import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from smart_llm_router.config import LLMProvider, Settings
from smart_llm_router.router import (
    LLMChoice,
    RequestPolicyIncompatibility,
    _cache_key,
    _call_openai_compatible,
    _load_route_state,
    _required_structured_output_spec,
    _structured_response_format,
    _validate_structured_output,
    router_doctor,
    run_llm_task,
)


class OpenRouterRequestControlTests(unittest.TestCase):
    def _settings(self, root: Path, provider: LLMProvider) -> Settings:
        return Settings(
            data_dir=root,
            providers=(provider,),
            timeout=5,
            empty_pool_refresh_timeout=1,
            empty_pool_refresh_limit=1,
            runtime_dir_source="temporary_fallback",
            runtime_fallback_reason="persistent_runtime_unwritable",
            runtime_expected_dir=root / "persistent",
        )

    def test_openrouter_payload_applies_pin_zdr_privacy_and_schema_controls(self) -> None:
        provider = LLMProvider(
            "openrouter-vision-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        response = Mock()
        response.headers = {"x-generation-id": "gen-synthetic"}
        response.json.return_value = {
            "provider": "DeepInfra",
            "choices": [{"message": {"content": '{"text":"OK"}'}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 4},
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_llm_router_output",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        }
        with patch.dict(os.environ, {"OPENROUTER_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = response
                content, usage = _call_openai_compatible(
                    LLMChoice(provider, provider.models[0]),
                    messages=[{"role": "user", "content": "synthetic"}],
                    timeout=2,
                    temperature=0,
                    response_format=response_format,
                    openrouter_upstream_providers=("deepinfra",),
                    openrouter_allow_fallbacks=False,
                    openrouter_require_zdr=True,
                    openrouter_deny_data_collection=True,
                )

        payload = client_class.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(content, '{"text":"OK"}')
        self.assertEqual(payload["response_format"], response_format)
        self.assertEqual(
            payload["provider"],
            {
                "only": ["deepinfra"],
                "allow_fallbacks": False,
                "zdr": True,
                "data_collection": "deny",
                "require_parameters": True,
            },
        )
        self.assertEqual(usage["_routing_metadata"]["served_provider"], "DeepInfra")
        self.assertEqual(usage["_routing_metadata"]["generation_id"], "gen-synthetic")

    def test_openrouter_controls_fail_before_send_on_non_openrouter_route(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://example.test/v1",
            "NVIDIA_KEY",
            ("example/model",),
            True,
            1,
            "permanent_free",
        )
        with patch.dict(os.environ, {"NVIDIA_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                with self.assertRaisesRegex(RuntimeError, "只能用于 OpenRouter"):
                    _call_openai_compatible(
                        LLMChoice(provider, provider.models[0]),
                        messages=[{"role": "user", "content": "synthetic"}],
                        timeout=2,
                        temperature=0,
                        openrouter_require_zdr=True,
                    )
        client_class.assert_not_called()

    def test_task_filters_non_openrouter_routes_before_network(self) -> None:
        provider = LLMProvider(
            "nvidia-free",
            "https://example.test/v1",
            "NVIDIA_KEY",
            ("example/model",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), provider)
            with patch.dict(os.environ, {"NVIDIA_KEY": "synthetic"}, clear=True):
                with patch("smart_llm_router.router._call_openai_compatible") as send:
                    with self.assertRaisesRegex(RuntimeError, "发送前失败关闭"):
                        run_llm_task(
                            settings,
                            task="qa",
                            prompt="synthetic",
                            provider="nvidia-free",
                            model="example/model",
                            privacy="external_allowed",
                            openrouter_require_zdr=True,
                        )
        send.assert_not_called()

    def test_schema_transport_and_local_validation_share_one_schema(self) -> None:
        complexity = {"shadow_descriptor_v2": {"features": {"structured_output_required": True}}}
        prompt = (
            'Only raw JSON. JSON Schema: {"type":"object","properties":'
            '{"pages":{"type":"array","items":{"type":"object","properties":'
            '{"page":{"type":"integer"}},"required":["page"],"additionalProperties":false}}},'
            '"required":["pages"],"additionalProperties":false}'
        )
        spec = _required_structured_output_spec(complexity, prompt, task="ocr")
        response_format = _structured_response_format(spec)
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        self.assertEqual(
            _validate_structured_output('{"pages":[{"page":1}]}', "json", schema=spec["schema"]),
            (True, None),
        )
        self.assertEqual(
            _validate_structured_output('{"pages":[{"page":"1"}]}', "json", schema=spec["schema"]),
            (False, "structured_output_schema_validation_failed"),
        )
        self.assertEqual(
            _validate_structured_output('{"pages":[{"page":1,"extra":true}]}', "json", schema=spec["schema"]),
            (False, "structured_output_schema_validation_failed"),
        )

    def test_schema_subset_rejects_nonfinite_bounds_and_nested_required_failures(self) -> None:
        bounded = {
            "type": "object",
            "properties": {"score": {"type": "number", "minimum": 1}},
            "required": ["score"],
            "additionalProperties": False,
        }
        self.assertEqual(
            _validate_structured_output('{"score":0}', "json", schema=bounded),
            (False, "structured_output_schema_validation_failed"),
        )
        self.assertEqual(
            _validate_structured_output('{"score":NaN}', "json", schema=bounded),
            (False, "strict_json_parse_failed"),
        )
        nested_required = {
            "type": "object",
            "anyOf": [{"required": ["left"]}, {"required": ["right"]}],
        }
        self.assertEqual(
            _validate_structured_output('{}', "json", schema=nested_required),
            (False, "structured_output_schema_validation_failed"),
        )

    def test_schema_subset_rejects_unknown_keyword_and_duplicate_output_keys(self) -> None:
        unsupported = {"type": "object", "pattern": "^safe$"}
        self.assertEqual(
            _validate_structured_output('{}', "json", schema=unsupported),
            (False, "structured_output_schema_unsupported"),
        )
        schema = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        self.assertEqual(
            _validate_structured_output('{"value":1,"value":2}', "json", schema=schema),
            (False, "strict_json_parse_failed"),
        )
        self.assertEqual(
            _validate_structured_output('{"value":1.0}', "json", schema=schema),
            (True, None),
        )

    def test_schema_subset_uses_json_numeric_equality_and_bounded_dialect(self) -> None:
        self.assertEqual(
            _validate_structured_output(
                '{"value":1.0}',
                "json",
                schema={"type": "object", "properties": {"value": {"const": 1}}},
            ),
            (True, None),
        )
        self.assertEqual(
            _validate_structured_output(
                '{"values":[1,1.0]}',
                "json",
                schema={
                    "type": "object",
                    "properties": {"values": {"type": "array", "uniqueItems": True}},
                },
            ),
            (False, "structured_output_schema_validation_failed"),
        )
        self.assertEqual(
            _validate_structured_output(
                '{"value":1}',
                "json",
                schema={"type": "object", "properties": {"value": {"enum": [1, 1.0]}}},
            ),
            (False, "structured_output_schema_unsupported"),
        )
        self.assertEqual(
            _validate_structured_output(
                '{}',
                "json",
                schema={"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"},
            ),
            (False, "structured_output_schema_unsupported"),
        )
        self.assertEqual(
            _validate_structured_output(
                '{"value":1.0}',
                "json",
                schema={"type": "object", "properties": {"value": {"type": ["integer", "string"]}}},
            ),
            (True, None),
        )
        self.assertEqual(
            _validate_structured_output(
                '{}',
                "json",
                schema={"type": "object", "properties": {1: {"type": "string"}}},
            ),
            (False, "structured_output_schema_unsupported"),
        )
        deep_schema = {"type": "object"}
        cursor = deep_schema
        for index in range(18):
            child = {"type": "object"}
            cursor["properties"] = {f"level_{index}": child}
            cursor = child
        self.assertEqual(
            _validate_structured_output('{}', "json", schema=deep_schema),
            (False, "structured_output_schema_unsupported"),
        )

    def test_unsupported_schema_blocks_before_cache_or_send(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), provider)
            with patch.dict(os.environ, {"OPENROUTER_KEY": "synthetic"}, clear=True):
                with patch("smart_llm_router.router._load_response_cache") as load_cache:
                    with patch("smart_llm_router.router._call_openai_compatible") as send:
                        with self.assertRaisesRegex(ValueError, "unsupported_keyword:pattern.*blocked_before_send"):
                            run_llm_task(
                                settings,
                                task="verify",
                                prompt='Only raw JSON. JSON Schema: {"type":"object","pattern":"^safe$"}',
                                provider="openrouter-free",
                                model="example/model:free",
                                privacy="external_allowed",
                            )
        load_cache.assert_not_called()
        send.assert_not_called()

    def test_openrouter_explicit_policy_error_is_typed_before_health_accounting(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(
            404,
            request=request,
            json={
                "error": {
                    "code": 404,
                    "message": "No endpoints available matching your guardrail restrictions and data policy",
                }
            },
        )
        with patch.dict(os.environ, {"OPENROUTER_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaises(RequestPolicyIncompatibility) as raised:
                    _call_openai_compatible(
                        LLMChoice(provider, provider.models[0]),
                        messages=[{"role": "user", "content": "synthetic"}],
                        timeout=2,
                        temperature=0,
                        openrouter_require_zdr=True,
                    )
        self.assertEqual(raised.exception.reason, "zdr_constraint")

    def test_openrouter_model_404_with_controls_remains_generic_health_failure(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("missing/model:free",),
            True,
            1,
            "permanent_free",
        )
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(
            404,
            request=request,
            json={
                "error": {
                    "code": 404,
                    "message": "Model not found",
                    "metadata": {"error_type": "not_found"},
                }
            },
        )
        with patch.dict(os.environ, {"OPENROUTER_KEY": "synthetic"}, clear=True):
            with patch("smart_llm_router.router.httpx.Client") as client_class:
                client_class.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaises(httpx.HTTPStatusError):
                    _call_openai_compatible(
                        LLMChoice(provider, provider.models[0]),
                        messages=[{"role": "user", "content": "synthetic"}],
                        timeout=2,
                        temperature=0,
                        openrouter_require_zdr=True,
                    )

    def test_policy_incompatibility_is_ledgered_without_generic_cooldown(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), provider)
            with patch.dict(os.environ, {"OPENROUTER_KEY": "synthetic"}, clear=True):
                with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                    with patch(
                        "smart_llm_router.router._call_openai_compatible",
                        side_effect=RequestPolicyIncompatibility(404),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "request policy incompatible"):
                            run_llm_task(
                                settings,
                                task="qa",
                                prompt="synthetic",
                                provider="openrouter-free",
                                model="example/model:free",
                                privacy="external_allowed",
                                cache_enabled=False,
                                openrouter_require_zdr=True,
                            )
            rows = [
                json.loads(line)
                for line in (Path(tmp) / "llm_cost_ledger.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(_load_route_state(settings), {})
        failure = rows[-1]
        self.assertEqual(failure["failure_class"], "request_policy_incompatible")
        self.assertFalse(failure["health_cooldown_recorded"])
        self.assertEqual(failure["request_policy_reason"], "request_constraints")

    def test_generic_model_404_still_records_route_cooldown(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(404, request=request)
        failure = httpx.HTTPStatusError("model not found", request=request, response=response)
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), provider)
            with patch.dict(os.environ, {"OPENROUTER_KEY": "synthetic"}, clear=True):
                with patch("smart_llm_router.router._maybe_auto_discover_free_pool"):
                    with patch("smart_llm_router.router._call_openai_compatible", side_effect=failure):
                        with self.assertRaisesRegex(RuntimeError, "model not found"):
                            run_llm_task(
                                settings,
                                task="qa",
                                prompt="synthetic",
                                provider="openrouter-free",
                                model="example/model:free",
                                privacy="external_allowed",
                                cache_enabled=False,
                            )
            self.assertEqual(next(iter(_load_route_state(settings).values())).failure_count, 1)

    def test_cache_identity_includes_openrouter_request_controls(self) -> None:
        common = {
            "task": "ocr",
            "prompt": "synthetic",
            "context": None,
            "prefer_free": True,
            "paid_fallback": False,
            "temperature": 0,
        }
        baseline = _cache_key(**common)
        controlled = _cache_key(
            **common,
            openrouter_upstream_providers=("deepinfra",),
            openrouter_allow_fallbacks=False,
            openrouter_require_zdr=True,
        )
        self.assertNotEqual(baseline, controlled)

    def test_doctor_exposes_temporary_runtime_provenance(self) -> None:
        provider = LLMProvider(
            "openrouter-free",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_KEY",
            ("example/model:free",),
            True,
            1,
            "permanent_free",
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(Path(tmp), provider)
            report = router_doctor(settings)
        configuration = report["configuration"]
        self.assertEqual(configuration["runtime_dir_source"], "temporary_fallback")
        self.assertTrue(configuration["runtime_fallback_active"])
        self.assertEqual(configuration["runtime_fallback_reason"], "persistent_runtime_unwritable")
        self.assertIn("run_status_in_the_same_runtime_or_set_SMART_LLM_RUNTIME_DIR", report["recommendations"])


if __name__ == "__main__":
    unittest.main()
