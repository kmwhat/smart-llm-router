from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


ADAPTER_STATES = ("discovered", "shadow", "candidate", "qualified", "production", "retired")
ALLOWED_TRANSITIONS = {
    "discovered": {"shadow", "retired"},
    "shadow": {"candidate", "retired"},
    "candidate": {"shadow", "qualified", "retired"},
    "qualified": {"candidate", "production", "retired"},
    "production": {"qualified", "retired"},
    "retired": set(),
}
DECLARATION_SCHEMA = "smart_llm_router.adapter_declaration.v1"
TRANSITION_SCHEMA = "smart_llm_router.adapter_transition_request.v1"
RECEIPT_SCHEMA = "smart_llm_router.adapter_transition_receipt.v1"
PROMOTION_SCHEMA = "smart_llm_router.promotion_decision.v1"


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _non_empty(value: Any, *, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def validate_adapter_declaration(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != DECLARATION_SCHEMA:
        raise ValueError("unsupported adapter declaration schema")
    current_state = str(payload.get("current_state") or "").strip()
    if current_state not in ADAPTER_STATES:
        raise ValueError(f"unsupported adapter state: {current_state}")
    modalities = payload.get("modalities") or []
    if not isinstance(modalities, list) or not modalities or any(not str(item).strip() for item in modalities):
        raise ValueError("modalities must contain at least one non-empty value")
    adapter_id = _non_empty(payload.get("adapter_id"), name="adapter_id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", adapter_id):
        raise ValueError("adapter_id must be a filesystem-safe identifier")
    declaration = {
        "schema": DECLARATION_SCHEMA,
        "adapter_id": adapter_id,
        "provider": _non_empty(payload.get("provider"), name="provider"),
        "model": _non_empty(payload.get("model"), name="model"),
        "modalities": list(dict.fromkeys(str(item).strip() for item in modalities)),
        "current_state": current_state,
        "billing_class": _non_empty(payload.get("billing_class"), name="billing_class"),
    }
    declaration["adapter_fingerprint"] = _fingerprint(declaration)
    return declaration


def validate_transition_request(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != TRANSITION_SCHEMA:
        raise ValueError("unsupported adapter transition request schema")
    target_state = str(payload.get("target_state") or "").strip()
    if target_state not in ADAPTER_STATES:
        raise ValueError(f"unsupported target state: {target_state}")
    raw_health = payload.get("health_evidence") or {}
    if not isinstance(raw_health, dict):
        raise ValueError("health_evidence must be an object")
    request = {
        "schema": TRANSITION_SCHEMA,
        "target_state": target_state,
        "reason": _non_empty(payload.get("reason"), name="reason"),
        "health_evidence": {
            "canary_passed": bool(raw_health.get("canary_passed", False)),
            "health_samples": max(0, int(raw_health.get("health_samples") or 0)),
            "degraded": bool(raw_health.get("degraded", False)),
        },
        "owner_approved": bool(payload.get("owner_approved", False)),
        "smoke_test_passed": bool(payload.get("smoke_test_passed", False)),
        "rollback_plan": str(payload.get("rollback_plan") or "").strip(),
    }
    request["request_fingerprint"] = _fingerprint(request)
    return request


def _promotion_reasons(adapter: dict[str, Any], decision: dict[str, Any] | None) -> list[str]:
    if not decision:
        return ["promotion_decision_missing"]
    if decision.get("schema") != PROMOTION_SCHEMA:
        return ["promotion_decision_schema_invalid"]
    reasons: list[str] = []
    if decision.get("status") != "pass" or not decision.get("eligible_for_explicit_role_band_registration"):
        reasons.append("promotion_decision_not_passed")
    candidate = decision.get("candidate") or {}
    if str(candidate.get("provider") or "").lower() != adapter["provider"].lower() or str(candidate.get("model") or "").lower() != adapter["model"].lower():
        reasons.append("promotion_candidate_mismatch")
    route_health = decision.get("route_health") or {}
    if int(route_health.get("health_samples") or 0) < 3:
        reasons.append("promotion_health_samples_insufficient")
    if route_health.get("degraded"):
        reasons.append("promotion_route_degraded")
    proposed_band = int(decision.get("proposed_quality_band") or 0)
    if not 1 <= proposed_band <= 4:
        reasons.append("promotion_quality_band_invalid")
    if not str(decision.get("proposed_role") or "").strip():
        reasons.append("promotion_role_missing")
    return reasons


def evaluate_adapter_transition(
    declaration: dict[str, Any],
    transition_request: dict[str, Any],
    *,
    promotion_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = validate_adapter_declaration(declaration)
    request = validate_transition_request(transition_request)
    current_state = adapter["current_state"]
    target_state = request["target_state"]
    reasons: list[str] = []
    if target_state not in ALLOWED_TRANSITIONS[current_state]:
        reasons.append("illegal_state_transition")

    health = request["health_evidence"]
    if current_state == "shadow" and target_state == "candidate":
        if not health["canary_passed"]:
            reasons.append("canary_not_passed")
        if health["health_samples"] < 1:
            reasons.append("insufficient_health_samples")
        if health["degraded"]:
            reasons.append("adapter_route_degraded")
    if (current_state, target_state) in {("candidate", "qualified"), ("qualified", "production")}:
        reasons.extend(_promotion_reasons(adapter, promotion_decision))
    if target_state == "production":
        if not request["owner_approved"]:
            reasons.append("owner_approval_missing")
        if not request["smoke_test_passed"]:
            reasons.append("smoke_test_missing")
        if not request["rollback_plan"]:
            reasons.append("rollback_plan_missing")

    reasons = list(dict.fromkeys(reasons))
    evidence = {
        "health": health,
        "promotion_report_id": (promotion_decision or {}).get("report_id"),
        "promotion_decision_fingerprint": _fingerprint(promotion_decision) if promotion_decision else None,
        "owner_approved": request["owner_approved"],
        "smoke_test_passed": request["smoke_test_passed"],
        "rollback_plan_recorded": bool(request["rollback_plan"]),
    }
    return {
        "schema": RECEIPT_SCHEMA,
        "receipt_id": "atr_" + uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "adapter_id": adapter["adapter_id"],
        "provider": adapter["provider"],
        "model": adapter["model"],
        "modalities": adapter["modalities"],
        "from_state": current_state,
        "to_state": target_state,
        "status": "pass" if not reasons else "hold",
        "reasons": reasons,
        "adapter_fingerprint": adapter["adapter_fingerprint"],
        "request_fingerprint": request["request_fingerprint"],
        "evidence": evidence,
        "automatic_registry_change": False,
        "automatic_production_change": False,
        "next_action": "owner_may_apply_state_change" if not reasons else "resolve_hold_reasons_and_recheck",
    }


def write_adapter_transition_receipt(receipt: dict[str, Any], path: str | Path) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def persist_adapter_transition(
    declaration: dict[str, Any],
    receipt: dict[str, Any],
    directory: str | Path,
) -> dict[str, str | None]:
    adapter = validate_adapter_declaration(declaration)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unsupported adapter transition receipt schema")
    if receipt.get("adapter_fingerprint") != adapter["adapter_fingerprint"]:
        raise ValueError("adapter transition receipt does not match declaration")
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    receipt_path = root / "receipts" / f"{receipt['receipt_id']}.json"
    passed = receipt.get("status") == "pass"
    state_path = root / "adapters" / f"{adapter['adapter_id']}.json" if passed else None
    runtime_state = {
        "state_path": str(state_path) if state_path else None,
        "receipt_path": str(receipt_path),
    }
    receipt["runtime_state"] = runtime_state
    if passed:
        receipt["next_action"] = "state_change_persisted"
    _write_private_json(receipt_path, receipt)
    if state_path:
        state = {
            key: adapter[key]
            for key in ("schema", "adapter_id", "provider", "model", "modalities", "billing_class")
        }
        state.update(
            {
                "current_state": receipt["to_state"],
                "last_transition_receipt_id": receipt["receipt_id"],
                "updated_at": receipt["created_at"],
            }
        )
        _write_private_json(state_path, state)
    return runtime_state
