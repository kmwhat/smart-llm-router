from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Settings
from .router import (
    QUALITY_TARGETS,
    ROLE_TASKS,
    TASK_TYPES,
    configured_models,
    describe_choice_capability,
    normalize_task_type,
    read_cost_ledger,
    route_performance_stats,
    run_llm_task,
)


GOLDEN_SUITE_SCHEMA = "smart_llm_router.golden_suite.v1"
GOLDEN_REPORT_SCHEMA = "smart_llm_router.golden_report.v1"
BLIND_REVIEW_SCHEMA = "smart_llm_router.blind_review.v1"
PROMOTION_DECISION_SCHEMA = "smart_llm_router.promotion_decision.v1"
SUPPORTED_ASSERTIONS = {
    "contains_all",
    "contains_any",
    "not_contains_any",
    "regex",
    "valid_json",
    "json_required_keys",
    "json_field_equals",
    "min_chars",
    "max_chars",
}
SENSITIVE_FIELD_TERMS = ("api_key", "apikey", "access_token", "secret", "password", "private_key")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _reject_sensitive_fields(payload: Any, path: str = "suite") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).lower().replace("-", "_")
            if any(term in normalized for term in SENSITIVE_FIELD_TERMS):
                raise ValueError(f"golden suite must not contain secret field: {path}.{key}")
            _reject_sensitive_fields(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _reject_sensitive_fields(value, f"{path}[{index}]")


def _ratio(value: Any, *, name: str, default: float) -> float:
    number = float(default if value is None else value)
    if number < 0 or number > 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _normalized_assertion(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("assertion entries must be objects")
    assertion_type = str(payload.get("type") or "").strip()
    if assertion_type not in SUPPORTED_ASSERTIONS:
        raise ValueError(f"unsupported assertion type: {assertion_type or '-'}")
    result: dict[str, Any] = {"type": assertion_type}
    if assertion_type in {"contains_all", "contains_any", "not_contains_any", "json_required_keys"}:
        values = [str(value).strip() for value in payload.get("values", []) if str(value).strip()]
        if not values:
            raise ValueError(f"{assertion_type} requires non-empty values")
        result["values"] = values
    elif assertion_type == "regex":
        pattern = str(payload.get("pattern") or "")
        if not pattern:
            raise ValueError("regex requires pattern")
        re.compile(pattern)
        result["pattern"] = pattern
    elif assertion_type == "json_field_equals":
        path = str(payload.get("path") or "").strip()
        if not path or "value" not in payload:
            raise ValueError("json_field_equals requires path and value")
        result["path"] = path
        result["value"] = payload["value"]
    elif assertion_type in {"min_chars", "max_chars"}:
        value = int(payload.get("value") or 0)
        if value <= 0:
            raise ValueError(f"{assertion_type} requires a positive value")
        result["value"] = value
    return result


def validate_golden_suite(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != GOLDEN_SUITE_SCHEMA:
        raise ValueError("unsupported golden suite schema")
    _reject_sensitive_fields(payload)
    suite_id = str(payload.get("suite_id") or "").strip()
    if not suite_id:
        raise ValueError("suite_id is required")
    task = normalize_task_type(str(payload.get("task") or ""))
    if task not in TASK_TYPES:
        raise ValueError(f"unsupported golden suite task: {task or '-'}")
    quality_target = str(payload.get("quality_target") or "draft")
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"unsupported quality_target: {quality_target}")
    privacy = str(payload.get("privacy") or "external_allowed")
    if privacy not in {"external_allowed", "local_only"}:
        raise ValueError("golden suite privacy must be external_allowed or local_only")
    proposed_role = normalize_task_type(str(payload.get("proposed_role") or task))
    proposed_quality_band = int(payload.get("proposed_quality_band") or 0)
    if proposed_role in ROLE_TASKS and proposed_quality_band not in {1, 2, 3, 4}:
        raise ValueError("role promotion suites require proposed_quality_band between 1 and 4")

    raw_thresholds = payload.get("thresholds") or {}
    if not isinstance(raw_thresholds, dict):
        raise ValueError("thresholds must be an object")
    thresholds = {
        "min_cases": max(3, int(raw_thresholds.get("min_cases") or 5)),
        "min_case_pass_rate": _ratio(raw_thresholds.get("min_case_pass_rate"), name="min_case_pass_rate", default=0.8),
        "max_baseline_case_regression": _ratio(raw_thresholds.get("max_baseline_case_regression"), name="max_baseline_case_regression", default=0.0),
        "max_candidate_cost_usd": float(raw_thresholds.get("max_candidate_cost_usd", 0.0)),
        "max_call_cost_usd": float(raw_thresholds.get("max_call_cost_usd", 0.02)),
        "min_health_samples": max(3, int(raw_thresholds.get("min_health_samples") or 3)),
        "baseline_required": bool(raw_thresholds.get("baseline_required", True)),
        "independent_review_required": bool(raw_thresholds.get("independent_review_required", proposed_role in ROLE_TASKS)),
        "min_candidate_review_pass_rate": _ratio(raw_thresholds.get("min_candidate_review_pass_rate"), name="min_candidate_review_pass_rate", default=0.8),
        "min_candidate_win_or_tie_rate": _ratio(raw_thresholds.get("min_candidate_win_or_tie_rate"), name="min_candidate_win_or_tie_rate", default=0.8),
        "max_candidate_losses": max(0, int(raw_thresholds.get("max_candidate_losses") or 1)),
    }
    if thresholds["max_candidate_cost_usd"] < 0 or thresholds["max_call_cost_usd"] <= 0:
        raise ValueError("cost thresholds must be non-negative and max_call_cost_usd must be positive")

    rubric = [str(item).strip() for item in payload.get("rubric", []) if str(item).strip()]
    if thresholds["independent_review_required"] and not rubric:
        raise ValueError("independent review suites require a non-empty rubric")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("golden suite requires cases")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError("golden cases must be objects")
        case_id = str(raw_case.get("id") or f"case_{index}").strip()
        prompt = str(raw_case.get("prompt") or "").strip()
        if not case_id or not prompt:
            raise ValueError("golden cases require id and prompt")
        if case_id in seen:
            raise ValueError(f"duplicate golden case id: {case_id}")
        seen.add(case_id)
        assertions = [_normalized_assertion(item) for item in raw_case.get("assertions", [])]
        if not assertions:
            raise ValueError(f"golden case {case_id} requires assertions")
        cases.append(
            {
                "id": case_id,
                "prompt": prompt,
                "context": str(raw_case.get("context") or "").strip() or None,
                "image_path": str(raw_case.get("image_path") or "").strip() or None,
                "assertions": assertions,
            }
        )
    return {
        "schema": GOLDEN_SUITE_SCHEMA,
        "suite_id": suite_id,
        "description": str(payload.get("description") or "").strip(),
        "task": task,
        "proposed_role": proposed_role,
        "proposed_quality_band": proposed_quality_band,
        "quality_target": quality_target,
        "privacy": privacy,
        "thresholds": thresholds,
        "rubric": rubric,
        "cases": cases,
    }


def load_golden_suite(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("golden suite root must be an object")
    return validate_golden_suite(payload)


def _json_value(text: str) -> Any:
    stripped = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return json.loads(fence.group(1) if fence else stripped)


def _json_path_value(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate_assertions(content: str, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lowered = content.lower()
    results: list[dict[str, Any]] = []
    parsed_json: Any = None
    json_error: str | None = None
    for assertion in assertions:
        assertion_type = assertion["type"]
        passed = False
        detail = ""
        if assertion_type in {"contains_all", "contains_any", "not_contains_any"}:
            values = assertion["values"]
            matches = [value for value in values if value.lower() in lowered]
            if assertion_type == "contains_all":
                passed = len(matches) == len(values)
            elif assertion_type == "contains_any":
                passed = bool(matches)
            else:
                passed = not matches
            detail = f"matched={matches}"
        elif assertion_type == "regex":
            passed = re.search(assertion["pattern"], content, flags=re.DOTALL) is not None
            detail = f"pattern={assertion['pattern']}"
        elif assertion_type in {"valid_json", "json_required_keys", "json_field_equals"}:
            if parsed_json is None and json_error is None:
                try:
                    parsed_json = _json_value(content)
                except (json.JSONDecodeError, TypeError) as exc:
                    json_error = str(exc)
            if assertion_type == "valid_json":
                passed = json_error is None
                detail = "valid JSON" if passed else f"invalid JSON: {json_error}"
            elif assertion_type == "json_required_keys":
                keys = assertion["values"]
                passed = isinstance(parsed_json, dict) and all(key in parsed_json for key in keys)
                detail = f"required_keys={keys}"
            else:
                actual = _json_path_value(parsed_json, assertion["path"])
                expected = assertion["value"]
                if isinstance(actual, str) and isinstance(expected, str):
                    passed = actual.strip().lower() == expected.strip().lower()
                else:
                    passed = actual == expected
                detail = f"path={assertion['path']} expected={expected!r} actual={actual!r}"
        elif assertion_type == "min_chars":
            passed = len(content.strip()) >= assertion["value"]
            detail = f"chars={len(content.strip())} minimum={assertion['value']}"
        elif assertion_type == "max_chars":
            passed = len(content.strip()) <= assertion["value"]
            detail = f"chars={len(content.strip())} maximum={assertion['value']}"
        results.append({"type": assertion_type, "passed": passed, "detail": detail})
    return results


def _resolve_route(settings: Settings, provider: str, model: str) -> dict[str, Any]:
    provider_value = provider.strip().lower()
    model_value = model.strip().lower()
    matches = [
        choice
        for choice in configured_models(settings, only_free=False)
        if choice.provider.name.lower() == provider_value and choice.model.lower() == model_value
    ]
    if len(matches) != 1:
        raise ValueError(f"route must resolve exactly once: {provider}/{model}; matches={len(matches)}")
    capability = describe_choice_capability(matches[0])
    return {
        "provider": matches[0].provider.name,
        "model": matches[0].model,
        "model_family": capability["model_family"],
        "free": matches[0].provider.free,
        "billing_class": capability["billing_class"],
    }


def _ledger_row(settings: Settings, ledger_id: str | None) -> dict[str, Any] | None:
    if not ledger_id:
        return None
    return next((row for row in reversed(read_cost_ledger(settings, limit=0)) if row.get("id") == ledger_id), None)


def _run_route_cases(
    settings: Settings,
    *,
    suite: dict[str, Any],
    route: dict[str, Any],
    allow_paid: bool,
    stop_on_call_failure: bool = True,
) -> dict[str, Any]:
    if not route["free"] and not allow_paid:
        raise ValueError(f"paid route requires --allow-paid: {route['provider']}/{route['model']}")
    results: list[dict[str, Any]] = []
    previous_cache = os.environ.get("SMART_LLM_CACHE")
    os.environ["SMART_LLM_CACHE"] = "false"
    try:
        route_failed = False
        for case in suite["cases"]:
            if route_failed:
                results.append(
                    {
                        "case_id": case["id"],
                        "call_ok": False,
                        "case_passed": False,
                        "assertions": [],
                        "output": "",
                        "error": "skipped_after_route_failure",
                        "ledger_id": None,
                        "latency_s": None,
                        "estimated_cost_usd": None,
                    }
                )
                continue
            try:
                result = run_llm_task(
                    settings,
                    task=suite["task"],
                    prompt=case["prompt"],
                    context=case["context"],
                    image_path=case["image_path"],
                    prefer_free=route["free"],
                    paid_fallback=allow_paid,
                    provider=route["provider"],
                    model=route["model"],
                    quality_target=suite["quality_target"],
                    privacy=suite["privacy"],
                    max_cost_usd=suite["thresholds"]["max_call_cost_usd"],
                    temperature=0.0,
                )
                ledger = _ledger_row(settings, result.ledger_id) or {}
                assertions = evaluate_assertions(result.content, case["assertions"])
                results.append(
                    {
                        "case_id": case["id"],
                        "call_ok": True,
                        "case_passed": all(item["passed"] for item in assertions),
                        "assertions": assertions,
                        "output": result.content,
                        "ledger_id": result.ledger_id,
                        "latency_s": ledger.get("latency_s"),
                        "estimated_cost_usd": ledger.get("estimated_cost_usd"),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "case_id": case["id"],
                        "call_ok": False,
                        "case_passed": False,
                        "assertions": [],
                        "output": "",
                        "error": str(exc).replace("\n", " ")[:500],
                        "ledger_id": None,
                        "latency_s": None,
                        "estimated_cost_usd": None,
                    }
                )
                route_failed = stop_on_call_failure
    finally:
        if previous_cache is None:
            os.environ.pop("SMART_LLM_CACHE", None)
        else:
            os.environ["SMART_LLM_CACHE"] = previous_cache
    successful = sum(1 for item in results if item["call_ok"])
    passed = sum(1 for item in results if item["case_passed"])
    costs = [float(item["estimated_cost_usd"]) for item in results if isinstance(item.get("estimated_cost_usd"), (int, float))]
    latencies = [float(item["latency_s"]) for item in results if isinstance(item.get("latency_s"), (int, float))]
    return {
        **route,
        "case_count": len(results),
        "successful_calls": successful,
        "passed_cases": passed,
        "case_pass_rate": round(passed / len(results), 4) if results else 0.0,
        "total_estimated_cost_usd": round(sum(costs), 8),
        "unknown_cost_calls": successful - len(costs),
        "mean_latency_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "results": results,
    }


def _blind_review_packet(report: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any] | None:
    baseline = report.get("baseline")
    if not baseline:
        return None
    candidate_results = {row["case_id"]: row for row in report["candidate"]["results"]}
    baseline_results = {row["case_id"]: row for row in baseline["results"]}
    packet_cases: list[dict[str, Any]] = []
    blind_key: dict[str, str] = {}
    for case in suite["cases"]:
        case_id = case["id"]
        candidate_label = "A" if int(sha256(f"{report['report_id']}:{case_id}".encode()).hexdigest()[0], 16) % 2 == 0 else "B"
        baseline_label = "B" if candidate_label == "A" else "A"
        blind_key[case_id] = candidate_label
        outputs = {
            candidate_label: candidate_results[case_id]["output"],
            baseline_label: baseline_results[case_id]["output"],
        }
        packet_cases.append(
            {
                "case_id": case_id,
                "prompt": case["prompt"],
                "context": case["context"],
                "output_a": outputs["A"],
                "output_b": outputs["B"],
            }
        )
    report["blind_key"] = blind_key
    packet_id = "brp_" + _canonical_hash({"report_id": report["report_id"], "cases": packet_cases})[:20]
    report["review_packet_id"] = packet_id
    return {
        "schema": "smart_llm_router.blind_review_packet.v1",
        "review_packet_id": packet_id,
        "report_id": report["report_id"],
        "suite_id": suite["suite_id"],
        "task": suite["task"],
        "rubric": suite["rubric"],
        "instructions": "Judge A and B independently, then choose A, B, or tie. Do not infer model identity.",
        "cases": packet_cases,
    }


def _candidate_passes_baseline_entry(candidate: dict[str, Any], thresholds: dict[str, Any]) -> bool:
    case_count = int(candidate.get("case_count") or 0)
    if case_count < int(thresholds.get("min_cases") or 5):
        return False
    if int(candidate.get("successful_calls") or 0) != case_count:
        return False
    if float(candidate.get("case_pass_rate") or 0.0) < float(thresholds.get("min_case_pass_rate") or 0.8):
        return False
    if int(candidate.get("unknown_cost_calls") or 0) > 0:
        return False
    max_candidate_cost = float(thresholds.get("max_candidate_cost_usd") or 0.0)
    return not max_candidate_cost or float(candidate.get("total_estimated_cost_usd") or 0.0) <= max_candidate_cost


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_golden_evaluation(
    settings: Settings,
    *,
    suite_path: str | Path,
    candidate_provider: str,
    candidate_model: str,
    baseline_provider: str | None = None,
    baseline_model: str | None = None,
    output_dir: str | Path | None = None,
    allow_paid: bool = False,
) -> dict[str, Any]:
    suite_source = Path(suite_path).expanduser().resolve()
    suite = load_golden_suite(suite_source)
    for case in suite["cases"]:
        if case["image_path"] and not Path(case["image_path"]).expanduser().is_absolute():
            case["image_path"] = str((suite_source.parent / case["image_path"]).resolve())
    candidate_route = _resolve_route(settings, candidate_provider, candidate_model)
    if bool(baseline_provider) != bool(baseline_model):
        raise ValueError("baseline provider and model must be supplied together")
    baseline_route = _resolve_route(settings, baseline_provider or "", baseline_model or "") if baseline_provider else None
    if suite["thresholds"]["baseline_required"] and not baseline_route:
        raise ValueError("this golden suite requires a baseline route")
    paid_routes = [route for route in (candidate_route, baseline_route) if route and not route["free"]]
    if paid_routes and not allow_paid:
        names = ", ".join(f"{route['provider']}/{route['model']}" for route in paid_routes)
        raise ValueError(f"paid routes require --allow-paid: {names}")

    created_at = _now().isoformat()
    report_id = "ger_" + _canonical_hash(
        {
            "suite": _canonical_hash(suite),
            "candidate": candidate_route,
            "baseline": baseline_route,
            "created_at": created_at,
        }
    )[:20]
    candidate_result = _run_route_cases(settings, suite=suite, route=candidate_route, allow_paid=allow_paid)
    baseline_entry_passed = _candidate_passes_baseline_entry(candidate_result, suite["thresholds"])
    baseline_result = (
        _run_route_cases(settings, suite=suite, route=baseline_route, allow_paid=allow_paid)
        if baseline_route and baseline_entry_passed
        else None
    )
    report: dict[str, Any] = {
        "schema": GOLDEN_REPORT_SCHEMA,
        "report_id": report_id,
        "created_at": created_at,
        "suite_id": suite["suite_id"],
        "suite_sha256": _canonical_hash(suite),
        "suite_path": str(suite_source),
        "task": suite["task"],
        "proposed_role": suite["proposed_role"],
        "proposed_quality_band": suite["proposed_quality_band"],
        "quality_target": suite["quality_target"],
        "privacy": suite["privacy"],
        "thresholds": suite["thresholds"],
        "candidate": candidate_result,
        "baseline": baseline_result,
        "baseline_status": "completed" if baseline_result else "skipped_candidate_hard_gate" if baseline_route else "not_configured",
        "cache_disabled": True,
    }
    review_packet = _blind_review_packet(report, suite)
    target_root = Path(output_dir).expanduser() if output_dir else settings.data_dir / "golden-evaluations"
    run_dir = target_root / f"{suite['suite_id']}-{report_id[-8:]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.json"
    _write_json(report_path, report)
    review_packet_path = None
    review_template_path = None
    if review_packet:
        review_packet_path = run_dir / "blind-review-packet.json"
        _write_json(review_packet_path, review_packet)
        review_template_path = run_dir / "blind-review-template.json"
        _write_json(
            review_template_path,
            {
                "schema": BLIND_REVIEW_SCHEMA,
                "review_packet_id": review_packet["review_packet_id"],
                "report_id": report_id,
                "reviewer": {"type": "model", "model_family": "", "provider": "", "model": ""},
                "verdicts": [
                    {"case_id": case["case_id"], "winner": "tie", "quality_a": "pass", "quality_b": "pass", "rationale": ""}
                    for case in review_packet["cases"]
                ],
            },
        )
    return {
        "schema": "smart_llm_router.golden_run_manifest.v1",
        "report_id": report_id,
        "suite_id": suite["suite_id"],
        "candidate": {key: report["candidate"][key] for key in ("provider", "model", "case_count", "successful_calls", "passed_cases", "case_pass_rate", "total_estimated_cost_usd")},
        "baseline": {key: report["baseline"][key] for key in ("provider", "model", "case_count", "successful_calls", "passed_cases", "case_pass_rate", "total_estimated_cost_usd")} if report["baseline"] else None,
        "report_path": str(report_path),
        "review_packet_path": str(review_packet_path) if review_packet_path else None,
        "review_template_path": str(review_template_path) if review_template_path else None,
    }


def _load_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    return payload


def build_promotion_decision(
    settings: Settings,
    *,
    report_path: str | Path,
    review_path: str | Path | None = None,
) -> dict[str, Any]:
    report = _load_json_object(report_path, label="golden report")
    if report.get("schema") != GOLDEN_REPORT_SCHEMA:
        raise ValueError("unsupported golden report schema")
    candidate = report.get("candidate") or {}
    baseline = report.get("baseline") or None
    thresholds = report.get("thresholds") or {}
    reasons: list[str] = []
    case_count = int(candidate.get("case_count") or 0)
    if case_count < int(thresholds.get("min_cases") or 5):
        reasons.append("insufficient_golden_cases")
    if int(candidate.get("successful_calls") or 0) != case_count:
        reasons.append("candidate_call_failures")
    if float(candidate.get("case_pass_rate") or 0.0) < float(thresholds.get("min_case_pass_rate") or 0.8):
        reasons.append("candidate_case_pass_rate_below_threshold")
    max_candidate_cost = float(thresholds.get("max_candidate_cost_usd") or 0.0)
    if max_candidate_cost and float(candidate.get("total_estimated_cost_usd") or 0.0) > max_candidate_cost:
        reasons.append("candidate_cost_exceeds_threshold")
    if int(candidate.get("unknown_cost_calls") or 0) > 0:
        reasons.append("candidate_cost_unknown")
    baseline_skipped_for_candidate = report.get("baseline_status") == "skipped_candidate_hard_gate"
    if thresholds.get("baseline_required", True) and not baseline and not baseline_skipped_for_candidate:
        reasons.append("baseline_missing")
    if baseline:
        if int(baseline.get("successful_calls") or 0) != int(baseline.get("case_count") or 0):
            reasons.append("baseline_call_failures")
        regression = float(baseline.get("case_pass_rate") or 0.0) - float(candidate.get("case_pass_rate") or 0.0)
        if regression > float(thresholds.get("max_baseline_case_regression") or 0.0):
            reasons.append("candidate_regresses_against_baseline")

    stats = route_performance_stats(settings, task=str(report.get("task") or ""), limit=1000)
    route_health = next(
        (
            row
            for row in stats["routes"]
            if row["provider"].lower() == str(candidate.get("provider") or "").lower()
            and row["model"].lower() == str(candidate.get("model") or "").lower()
        ),
        None,
    )
    if not route_health or int(route_health.get("health_samples") or 0) < int(thresholds.get("min_health_samples") or 3):
        reasons.append("insufficient_live_health_samples")
    elif route_health.get("degraded"):
        reasons.append("candidate_route_degraded")

    review_summary: dict[str, Any] | None = None
    if thresholds.get("independent_review_required", False):
        if not review_path:
            if reasons:
                review_summary = {"status": "skipped", "reason": "hard_gate_failure", "cost_avoided": True}
            else:
                reasons.append("independent_review_missing")
        else:
            review = _load_json_object(review_path, label="blind review")
            if review.get("schema") != BLIND_REVIEW_SCHEMA:
                raise ValueError("unsupported blind review schema")
            if review.get("report_id") != report.get("report_id") or review.get("review_packet_id") != report.get("review_packet_id"):
                raise ValueError("blind review does not match golden report")
            reviewer = review.get("reviewer") or {}
            reviewer_type = str(reviewer.get("type") or "")
            reviewer_family = str(reviewer.get("model_family") or "").lower()
            compared_families = {str(candidate.get("model_family") or "").lower()}
            if baseline:
                compared_families.add(str(baseline.get("model_family") or "").lower())
            if reviewer_type == "model" and (not reviewer_family or reviewer_family in compared_families):
                reasons.append("reviewer_not_independent")
            elif reviewer_type not in {"model", "human"}:
                reasons.append("reviewer_identity_invalid")
            verdicts = review.get("verdicts") or []
            blind_key = report.get("blind_key") or {}
            if len(verdicts) != case_count or {row.get("case_id") for row in verdicts} != set(blind_key):
                reasons.append("review_case_coverage_incomplete")
            else:
                wins = ties = losses = quality_passes = 0
                for verdict in verdicts:
                    case_id = str(verdict["case_id"])
                    candidate_label = str(blind_key[case_id]).upper()
                    winner = str(verdict.get("winner") or "").upper()
                    candidate_quality = str(verdict.get(f"quality_{candidate_label.lower()}") or "").lower()
                    if winner == candidate_label:
                        wins += 1
                    elif winner == "TIE":
                        ties += 1
                    elif winner in {"A", "B"}:
                        losses += 1
                    else:
                        reasons.append("review_verdict_invalid")
                    if candidate_quality == "pass":
                        quality_passes += 1
                win_or_tie_rate = (wins + ties) / case_count if case_count else 0.0
                review_pass_rate = quality_passes / case_count if case_count else 0.0
                if win_or_tie_rate < float(thresholds.get("min_candidate_win_or_tie_rate") or 0.8):
                    reasons.append("candidate_blind_review_below_baseline")
                if review_pass_rate < float(thresholds.get("min_candidate_review_pass_rate") or 0.8):
                    reasons.append("candidate_review_quality_below_threshold")
                if losses > int(thresholds.get("max_candidate_losses") or 1):
                    reasons.append("candidate_review_losses_exceed_threshold")
                review_summary = {
                    "reviewer": reviewer,
                    "wins": wins,
                    "ties": ties,
                    "losses": losses,
                    "win_or_tie_rate": round(win_or_tie_rate, 4),
                    "candidate_quality_pass_rate": round(review_pass_rate, 4),
                }

    reasons = list(dict.fromkeys(reasons))
    eligible = not reasons
    try:
        current_candidate = _resolve_route(settings, str(candidate.get("provider") or ""), str(candidate.get("model") or ""))
    except ValueError:
        current_candidate = {key: candidate.get(key) for key in ("provider", "model", "model_family", "free", "billing_class")}
    return {
        "schema": PROMOTION_DECISION_SCHEMA,
        "created_at": _now().isoformat(),
        "report_id": report.get("report_id"),
        "suite_id": report.get("suite_id"),
        "candidate": current_candidate,
        "billing_class_at_evaluation": candidate.get("billing_class"),
        "proposed_role": report.get("proposed_role"),
        "proposed_quality_band": report.get("proposed_quality_band"),
        "status": "pass" if eligible else "hold",
        "eligible_for_explicit_role_band_registration": eligible,
        "automatic_production_change": False,
        "reasons": reasons,
        "route_health": route_health,
        "candidate_metrics": {key: candidate.get(key) for key in ("case_count", "successful_calls", "passed_cases", "case_pass_rate", "total_estimated_cost_usd")},
        "baseline_metrics": {key: baseline.get(key) for key in ("provider", "model", "case_pass_rate", "total_estimated_cost_usd")} if baseline else None,
        "review": review_summary,
    }


def write_promotion_decision(decision: dict[str, Any], path: str | Path) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, decision)
    return target
