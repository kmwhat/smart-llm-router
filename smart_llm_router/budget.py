from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class BudgetLimitExceeded(RuntimeError):
    def __init__(self, message: str, incident: dict[str, Any]):
        super().__init__(message)
        self.incident = incident


@dataclass(frozen=True)
class BudgetReservation:
    workflow_id: str
    reservation_id: str
    reserved_cost_usd: float
    call_max_cost_usd: float
    workflow_max_cost_usd: float
    stage: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workflow_key(workflow_id: str) -> str:
    return hashlib.sha256(workflow_id.encode("utf-8")).hexdigest()[:24]


def budget_authority_id(data_dir: Path) -> str:
    canonical = str(data_dir.expanduser().resolve(strict=False))
    return "ba_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _state_path(data_dir: Path, workflow_id: str) -> Path:
    return data_dir / "workflow-budgets" / f"{_workflow_key(workflow_id)}.json"


def _state_fingerprint(state: dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_amount(value: Any, label: str, *, positive: bool = False) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(amount):
        raise ValueError(f"{label} must be finite")
    if positive and amount <= 0:
        raise ValueError(f"{label} must be positive")
    if not positive and amount < 0:
        raise ValueError(f"{label} cannot be negative")
    return amount


def _invalid_amount_incident(
    data_dir: Path,
    *,
    workflow_id: str,
    stage: str | None,
    operation: str,
    error: ValueError,
) -> BudgetLimitExceeded:
    incident = write_budget_incident(data_dir, {
        "kind": "workflow_budget_invalid_amount",
        "severity": "critical",
        "workflow_id": workflow_id,
        "stage": stage,
        "operation": operation,
        "reason": str(error),
        "decision": "blocked_before_send" if operation == "reserve" else "settlement_blocked",
    })
    return BudgetLimitExceeded("工作流预算包含非有限或越界数值，已阻止操作。", incident)


def _validated_authority_amounts(state: dict[str, Any]) -> tuple[float, float, float]:
    maximum = _finite_amount(state.get("workflow_max_cost_usd"), "authority workflow maximum", positive=True)
    spent = _finite_amount(state.get("spent_usd", 0.0), "authority workflow spent")
    active_reserved = 0.0
    reservations = state.get("reservations", {})
    if not isinstance(reservations, dict):
        raise ValueError("authority reservations must be an object")
    for reservation in reservations.values():
        if not isinstance(reservation, dict):
            raise ValueError("authority reservation entry must be an object")
        active_reserved += _finite_amount(
            reservation.get("reserved_cost_usd", 0.0),
            "authority reservation reserved cost",
        )
        _finite_amount(
            reservation.get("call_max_cost_usd", 0.0),
            "authority reservation call maximum",
        )
    if not math.isfinite(active_reserved):
        raise ValueError("authority active reservation total must be finite")
    return maximum, spent, active_reserved


def _write_migration_receipt(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    receipt = dict(payload)
    receipt.setdefault("schema", "smart_llm_router.workflow_budget_migration_receipt.v1")
    receipt.setdefault("receipt_id", "wbmr_" + uuid.uuid4().hex[:16])
    receipt.setdefault("created_at", _now())
    receipt_dir = data_dir / "migration-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.chmod(0o700)
    path = receipt_dir / f"{receipt['receipt_id']}.json"
    temp_path = path.with_suffix(f".{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.chmod(0o600)
    os.replace(temp_path, path)
    receipt["receipt_path"] = str(path)
    return receipt


def _validated_legacy_state(path: Path, workflow_id: str) -> tuple[dict[str, Any], str]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"legacy budget state unreadable:{path}:{exc}") from exc
    if not isinstance(state, dict) or state.get("schema") != "smart_llm_router.workflow_budget.v1":
        raise ValueError(f"unsupported legacy budget schema:{path}")
    if state.get("workflow_id") != workflow_id:
        raise ValueError(f"legacy workflow identity mismatch:{path}")
    if state.get("status") not in {"active", "stopped"}:
        raise ValueError(f"invalid legacy workflow status:{path}")
    if "workflow_max_cost_usd" not in state:
        raise ValueError(f"missing legacy workflow maximum:{path}")
    maximum = _finite_amount(state["workflow_max_cost_usd"], "legacy workflow maximum", positive=True)
    spent = _finite_amount(state.get("spent_usd", 0.0), "legacy workflow spent")
    reservations = state.get("reservations", {})
    if not isinstance(reservations, dict):
        raise ValueError(f"invalid legacy reservations:{path}")
    for reservation in reservations.values():
        if not isinstance(reservation, dict):
            raise ValueError(f"invalid legacy reservation entry:{path}")
        _finite_amount(
            reservation.get("reserved_cost_usd", 0.0),
            "legacy reservation reserved cost",
        )
        _finite_amount(
            reservation.get("call_max_cost_usd", 0.0),
            "legacy reservation call maximum",
        )
    if not isinstance(state.get("incidents", []), list):
        raise ValueError(f"invalid legacy incidents:{path}")
    return state, _state_fingerprint(state)


def _import_legacy_state(
    data_dir: Path,
    state: dict[str, Any],
    *,
    workflow_id: str,
    legacy_data_dirs: tuple[Path, ...],
) -> dict[str, Any] | None:
    candidates: list[tuple[Path, dict[str, Any], str]] = []
    seen_paths: set[str] = set()
    try:
        for root in legacy_data_dirs:
            source = _state_path(root.expanduser(), workflow_id)
            resolved = str(source.resolve(strict=False))
            if resolved in seen_paths or not source.is_file():
                continue
            seen_paths.add(resolved)
            legacy_state, fingerprint = _validated_legacy_state(source, workflow_id)
            candidates.append((source, legacy_state, fingerprint))
    except ValueError as exc:
        receipt = _write_migration_receipt(data_dir, {
            "workflow_id": workflow_id,
            "budget_authority_id": budget_authority_id(data_dir),
            "decision": "blocked",
            "reason": str(exc),
        })
        incident = write_budget_incident(data_dir, {
            "kind": "workflow_budget_migration_rejected",
            "severity": "critical",
            "workflow_id": workflow_id,
            "migration_receipt_id": receipt["receipt_id"],
            "migration_receipt_path": receipt["receipt_path"],
            "reason": str(exc),
            "decision": "blocked_before_send",
        })
        raise BudgetLimitExceeded("旧版工作流预算无法安全迁移，已在发送前阻止。", incident) from None
    if not candidates:
        return None
    fingerprints = {row[2] for row in candidates}
    if len(fingerprints) != 1:
        receipt = _write_migration_receipt(data_dir, {
            "workflow_id": workflow_id,
            "budget_authority_id": budget_authority_id(data_dir),
            "decision": "blocked",
            "reason": "conflicting_legacy_sources",
            "source_paths": [str(row[0]) for row in candidates],
            "source_fingerprints": sorted(fingerprints),
        })
        incident = write_budget_incident(data_dir, {
            "kind": "workflow_budget_migration_conflict",
            "severity": "critical",
            "workflow_id": workflow_id,
            "migration_receipt_id": receipt["receipt_id"],
            "migration_receipt_path": receipt["receipt_path"],
            "reason": "conflicting_legacy_sources",
            "decision": "blocked_before_send",
        })
        raise BudgetLimitExceeded("发现多个不一致的旧版预算来源，已在发送前阻止。", incident)
    fingerprint = candidates[0][2]
    migration = state.get("migration") if isinstance(state.get("migration"), dict) else {}
    if state:
        if migration.get("source_fingerprint") == fingerprint:
            return None
        receipt = _write_migration_receipt(data_dir, {
            "workflow_id": workflow_id,
            "budget_authority_id": budget_authority_id(data_dir),
            "decision": "blocked",
            "reason": "authority_and_legacy_identity_unproven",
            "authority_state_fingerprint": _state_fingerprint(state),
            "source_paths": [str(row[0]) for row in candidates],
            "source_fingerprint": fingerprint,
        })
        incident = write_budget_incident(data_dir, {
            "kind": "workflow_budget_migration_conflict",
            "severity": "critical",
            "workflow_id": workflow_id,
            "migration_receipt_id": receipt["receipt_id"],
            "migration_receipt_path": receipt["receipt_path"],
            "reason": "authority_and_legacy_identity_unproven",
            "decision": "blocked_before_send",
        })
        raise BudgetLimitExceeded("固定 authority 与旧版预算无法证明同一性，已在发送前阻止。", incident)
    legacy_state = dict(candidates[0][1])
    receipt = _write_migration_receipt(data_dir, {
        "workflow_id": workflow_id,
        "budget_authority_id": budget_authority_id(data_dir),
        "decision": "migrated",
        "source_paths": [str(row[0]) for row in candidates],
        "source_fingerprint": fingerprint,
        "preserved": {
            "status": legacy_state.get("status"),
            "workflow_max_cost_usd": legacy_state.get("workflow_max_cost_usd"),
            "spent_usd": legacy_state.get("spent_usd", 0.0),
            "reservation_count": len(legacy_state.get("reservations") or {}),
            "incident_count": len(legacy_state.get("incidents") or []),
            "created_at": legacy_state.get("created_at"),
            "updated_at": legacy_state.get("updated_at"),
        },
    })
    state.update(legacy_state)
    state["schema"] = "smart_llm_router.workflow_budget.v2"
    state["budget_authority_id"] = budget_authority_id(data_dir)
    state["migration"] = {
        "source_fingerprint": fingerprint,
        "source_paths": [str(row[0]) for row in candidates],
        "receipt_id": receipt["receipt_id"],
        "receipt_path": receipt["receipt_path"],
        "migrated_at": receipt["created_at"],
        "legacy_created_at": legacy_state.get("created_at"),
        "legacy_updated_at": legacy_state.get("updated_at"),
    }
    return receipt


@contextmanager
def _locked_state(data_dir: Path, workflow_id: str) -> Iterator[tuple[Path, dict[str, Any]]]:
    path = _state_path(data_dir, workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        try:
            yield path, state
        finally:
            temp_path = path.with_suffix(f".{os.getpid()}.tmp")
            temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp_path.chmod(0o600)
            os.replace(temp_path, path)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_budget_incident(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    incident = dict(payload)
    incident.setdefault("schema", "smart_llm_router.budget_incident.v1")
    incident.setdefault("incident_id", uuid.uuid4().hex[:16])
    incident.setdefault("detected_at", _now())
    incident_dir = data_dir / "budget-incidents"
    incident_dir.mkdir(parents=True, exist_ok=True)
    path = incident_dir / f"{incident['incident_id']}.json"
    path.write_text(json.dumps(incident, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    incident["incident_path"] = str(path)
    return incident


def write_budget_warning(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    warning = dict(payload)
    warning.setdefault("schema", "smart_llm_router.budget_warning.v1")
    warning.setdefault("warning_id", uuid.uuid4().hex[:16])
    warning.setdefault("detected_at", _now())
    warning_dir = data_dir / "budget-warnings"
    warning_dir.mkdir(parents=True, exist_ok=True)
    path = warning_dir / f"{warning['warning_id']}.json"
    path.write_text(json.dumps(warning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    warning["warning_path"] = str(path)
    return warning


def reserve_workflow_budget(
    data_dir: Path,
    *,
    workflow_id: str,
    workflow_max_cost_usd: float,
    call_max_cost_usd: float,
    reserved_cost_usd: float,
    stage: str | None = None,
    legacy_data_dirs: tuple[Path, ...] = (),
) -> BudgetReservation:
    try:
        workflow_max_cost_usd = _finite_amount(workflow_max_cost_usd, "workflow maximum", positive=True)
        call_max_cost_usd = _finite_amount(call_max_cost_usd, "call maximum")
        reserved_cost_usd = _finite_amount(reserved_cost_usd, "reserved cost")
    except ValueError as exc:
        raise _invalid_amount_incident(
            data_dir,
            workflow_id=workflow_id,
            stage=stage,
            operation="reserve",
            error=exc,
        ) from None
    reservation_id = uuid.uuid4().hex[:16]
    with _locked_state(data_dir, workflow_id) as (_path, state):
        _import_legacy_state(
            data_dir,
            state,
            workflow_id=workflow_id,
            legacy_data_dirs=legacy_data_dirs,
        )
        if not state:
            state.update({
                "schema": "smart_llm_router.workflow_budget.v2",
                "workflow_id": workflow_id,
                "budget_authority_id": budget_authority_id(data_dir),
                "workflow_max_cost_usd": workflow_max_cost_usd,
                "status": "active",
                "spent_usd": 0.0,
                "reservations": {},
                "incidents": [],
                "created_at": _now(),
            })
        try:
            configured_max, spent, active_reserved = _validated_authority_amounts(state)
        except ValueError as exc:
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_authority_state_invalid",
                "severity": "critical",
                "workflow_id": workflow_id,
                "stage": stage,
                "reason": str(exc),
                "decision": "blocked_before_send",
            })
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("固定 authority 含无效预算数值，已在发送前阻止。", incident) from None
        configured_authority = str(state.get("budget_authority_id") or "")
        current_authority = budget_authority_id(data_dir)
        if configured_authority and configured_authority != current_authority:
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_authority_mismatch", "severity": "critical",
                "workflow_id": workflow_id,
                "configured_budget_authority_id": configured_authority,
                "requested_budget_authority_id": current_authority,
                "decision": "blocked_before_send",
            })
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("工作流预算 authority 不一致，已在发送前阻止。", incident)
        if not configured_authority:
            state["budget_authority_id"] = current_authority
            state["schema"] = "smart_llm_router.workflow_budget.v2"
        if abs(configured_max - workflow_max_cost_usd) > 1e-9:
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_mismatch", "severity": "critical",
                "workflow_id": workflow_id,
                "configured_workflow_max_cost_usd": configured_max,
                "requested_workflow_max_cost_usd": workflow_max_cost_usd,
                "decision": "blocked_before_send",
            })
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("工作流预算上限与已建立的硬上限不一致，已在发送前阻止。", incident)
        if state.get("status") != "active":
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_stopped", "severity": "critical",
                "workflow_id": workflow_id, "decision": "blocked_before_send",
                "prior_incidents": list(state.get("incidents") or []),
            })
            raise BudgetLimitExceeded("工作流预算已停表，已在发送前阻止。", incident)
        projected = spent + active_reserved + reserved_cost_usd
        if not math.isfinite(projected):
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_projection_non_finite",
                "severity": "critical",
                "workflow_id": workflow_id,
                "stage": stage,
                "decision": "blocked_before_send",
            })
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("工作流累计预算投影不是有限数，已在发送前阻止。", incident)
        if projected > workflow_max_cost_usd + 1e-12:
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_reservation_rejected", "severity": "prevented",
                "workflow_id": workflow_id, "stage": stage, "spent_usd": spent,
                "active_reserved_usd": active_reserved,
                "requested_reservation_usd": reserved_cost_usd,
                "projected_workflow_cost_usd": projected,
                "workflow_max_cost_usd": workflow_max_cost_usd,
                "decision": "blocked_before_send",
            })
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("工作流累计预算不足，已在发送前阻止。", incident)
        state.setdefault("reservations", {})[reservation_id] = {
            "reserved_cost_usd": reserved_cost_usd,
            "call_max_cost_usd": call_max_cost_usd,
            "stage": stage,
            "created_at": _now(),
        }
        state["updated_at"] = _now()
    return BudgetReservation(workflow_id, reservation_id, reserved_cost_usd, call_max_cost_usd, workflow_max_cost_usd, stage)


def release_workflow_reservation(data_dir: Path, reservation: BudgetReservation) -> None:
    with _locked_state(data_dir, reservation.workflow_id) as (_path, state):
        (state.get("reservations") or {}).pop(reservation.reservation_id, None)
        state["updated_at"] = _now()


def finalize_workflow_reservation(
    data_dir: Path,
    reservation: BudgetReservation,
    *,
    actual_or_estimated_cost_usd: float,
) -> dict[str, Any] | None:
    try:
        reservation_workflow_max = _finite_amount(
            reservation.workflow_max_cost_usd,
            "reservation workflow maximum",
            positive=True,
        )
        reservation_call_max = _finite_amount(reservation.call_max_cost_usd, "reservation call maximum")
        reservation_reserved_cost = _finite_amount(reservation.reserved_cost_usd, "reservation reserved cost")
        actual_or_estimated_cost_usd = _finite_amount(actual_or_estimated_cost_usd, "settlement actual cost")
    except ValueError as exc:
        raise _invalid_amount_incident(
            data_dir,
            workflow_id=reservation.workflow_id,
            stage=reservation.stage,
            operation="settle",
            error=exc,
        ) from None
    with _locked_state(data_dir, reservation.workflow_id) as (_path, state):
        try:
            configured_max, spent_before, _active_reserved = _validated_authority_amounts(state)
        except ValueError as exc:
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_authority_state_invalid",
                "severity": "critical",
                "workflow_id": reservation.workflow_id,
                "stage": reservation.stage,
                "reason": str(exc),
                "decision": "settlement_blocked",
            })
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("固定 authority 含无效预算数值，已阻止结算。", incident) from None
        spent_after = spent_before + actual_or_estimated_cost_usd
        if not math.isfinite(spent_after):
            incident = write_budget_incident(data_dir, {
                "kind": "workflow_budget_settlement_non_finite",
                "severity": "critical",
                "workflow_id": reservation.workflow_id,
                "stage": reservation.stage,
                "reservation_id": reservation.reservation_id,
                "workflow_spent_before_usd": spent_before,
                "actual_or_estimated_cost_usd": actual_or_estimated_cost_usd,
                "liability_lock": "reservation_preserved",
                "decision": "workflow_stopped",
            })
            # The attempted call may already be billable. Keep the reservation
            # as a conservative liability lock and stop the workflow before any
            # settlement mutation can make that liability disappear.
            state["status"] = "stopped"
            state["updated_at"] = _now()
            state.setdefault("incidents", []).append(incident["incident_id"])
            raise BudgetLimitExceeded("工作流结算溢出，已停表并保留预留 liability。", incident)
        (state.get("reservations") or {}).pop(reservation.reservation_id, None)
        state["spent_usd"] = spent_after
        state["updated_at"] = _now()
        violations: list[str] = []
        if actual_or_estimated_cost_usd > reservation_call_max + 1e-12:
            violations.append("single_call_hard_limit_exceeded")
        if abs(configured_max - reservation_workflow_max) > 1e-9:
            violations.append("workflow_hard_limit_identity_mismatch")
        if spent_after > configured_max + 1e-12:
            violations.append("workflow_hard_limit_exceeded")
        if not violations:
            if actual_or_estimated_cost_usd <= reservation_reserved_cost + 1e-12:
                return None
            variance = actual_or_estimated_cost_usd - reservation_reserved_cost
            warning = write_budget_warning(data_dir, {
                "kind": "reservation_estimate_variance",
                "severity": "warning",
                "workflow_id": reservation.workflow_id,
                "stage": reservation.stage,
                "reservation_id": reservation.reservation_id,
                "reserved_cost_usd": reservation_reserved_cost,
                "actual_or_estimated_cost_usd": actual_or_estimated_cost_usd,
                "variance_usd": variance,
                "call_max_cost_usd": reservation_call_max,
                "workflow_spent_before_usd": spent_before,
                "workflow_spent_after_usd": spent_after,
                "workflow_max_cost_usd": reservation_workflow_max,
                "decision": "continue_reconciled",
            })
            state.setdefault("warnings", []).append(warning["warning_id"])
            return warning
        incident = write_budget_incident(data_dir, {
            "kind": "budget_hard_limit_overrun", "severity": "critical",
            "workflow_id": reservation.workflow_id, "stage": reservation.stage,
            "reservation_id": reservation.reservation_id, "violations": violations,
            "reserved_cost_usd": reservation_reserved_cost,
            "actual_or_estimated_cost_usd": actual_or_estimated_cost_usd,
            "call_max_cost_usd": reservation_call_max,
            "workflow_spent_before_usd": spent_before,
            "workflow_spent_after_usd": spent_after,
            "workflow_max_cost_usd": reservation_workflow_max,
            "decision": "workflow_stopped",
        })
        state["status"] = "stopped"
        state.setdefault("incidents", []).append(incident["incident_id"])
        return incident
