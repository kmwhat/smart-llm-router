from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Settings
from .router import TASK_TYPES, route_plan


SENSITIVITY_CLASSES = ("public", "external_cacheable", "internal_summary", "internal_raw", "secret")
WORKFLOW_STAGES = ("plan_design", "plan_audit", "execute", "process_checkpoint", "final_verify", "quality_enhance")
QUALITY_TARGETS = ("production", "audit", "frontier")
PRIVACY_MODES = ("auto", "local_only", "external_allowed")
AUTOMATION_MODES = ("manual_controlled", "unattended")
RISK_LEVELS = ("low", "medium", "high")


def validate_task_contract(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != "hermes_router_hub.task_contract.v1":
        raise ValueError("unsupported task contract schema")
    sensitivity = str(payload.get("sensitivity") or "public")
    if sensitivity not in SENSITIVITY_CLASSES:
        raise ValueError(f"unsupported sensitivity: {sensitivity}")
    free_only = bool(payload.get("free_only", True))
    paid_allowed = bool(payload.get("paid_fallback_allowed", False))
    cloud_raw = bool(payload.get("internal_raw_cloud_allowed", False))
    if free_only and paid_allowed:
        raise ValueError("free_only and paid_fallback_allowed cannot both be true")
    if sensitivity == "secret":
        raise ValueError("secret material must not be routed to a model")
    if sensitivity == "internal_raw" and cloud_raw:
        raise ValueError("internal_raw cloud routing requires a separate explicit execution approval")
    return {
        "task_id": str(payload.get("task_id") or "task-unknown"),
        "agent": str(payload.get("agent") or "codex"),
        "task_family": str(payload.get("task_family") or "text_light"),
        "sensitivity": sensitivity,
        "free_only": free_only,
        "paid_fallback_allowed": paid_allowed,
        "allow_cloud": sensitivity in {"public", "external_cacheable", "internal_summary"},
        "route_receipt_required": bool(payload.get("route_receipt_required", True)),
    }


def make_route_receipt(
    *,
    contract: dict[str, Any],
    mode: str,
    selected_provider: str | None,
    selected_model: str | None,
    cost_class: str,
    paid_fallback_used: bool,
    decision_reasons: list[str],
    output_path: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "hermes_router_hub.route_receipt.v1",
        "receipt_id": "rr_" + uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "agent": contract["agent"],
        "task_id": contract["task_id"],
        "task_family": contract["task_family"],
        "sensitivity": contract["sensitivity"],
        "selected_provider": selected_provider,
        "selected_model": selected_model,
        "cost_class": cost_class,
        "allow_cloud": contract["allow_cloud"],
        "paid_fallback_used": paid_fallback_used,
        "fallback_chain": [],
        "decision_reasons": decision_reasons,
        "output": {"materialized": bool(output_path), "path": output_path},
        "production_changed": mode == "execute",
    }


def write_route_receipt(receipt: dict[str, Any], directory: str | Path) -> Path:
    target_dir = Path(directory).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{receipt['receipt_id']}.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _normalized_criteria(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("success_criteria must contain at least one measurable criterion")
    criteria: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            criterion_id = f"criterion_{index}"
            text = item.strip()
        elif isinstance(item, dict):
            criterion_id = str(item.get("id") or f"criterion_{index}").strip()
            text = str(item.get("text") or "").strip()
        else:
            raise ValueError("success_criteria entries must be strings or objects")
        if not criterion_id or not text:
            raise ValueError("success_criteria entries require non-empty id and text")
        if criterion_id in seen:
            raise ValueError(f"duplicate success criterion id: {criterion_id}")
        seen.add(criterion_id)
        criteria.append({"id": criterion_id, "text": text})
    return criteria


def validate_workflow_contract(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != "hermes_router_hub.workflow_contract.v1":
        raise ValueError("unsupported workflow contract schema")
    objective = str(payload.get("objective") or "").strip()
    if not objective:
        raise ValueError("workflow objective is required")
    quality_target = str(payload.get("quality_target") or "production")
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"unsupported workflow quality_target: {quality_target}")
    privacy = str(payload.get("privacy") or "auto")
    if privacy not in PRIVACY_MODES:
        raise ValueError(f"unsupported workflow privacy: {privacy}")
    automation_mode = str(payload.get("automation_mode") or "manual_controlled")
    if automation_mode not in AUTOMATION_MODES:
        raise ValueError(f"unsupported automation_mode: {automation_mode}")
    task_type = str(payload.get("task_type") or "execute")
    if task_type not in TASK_TYPES:
        raise ValueError(f"unsupported workflow task_type: {task_type}")
    risk = str(payload.get("risk") or "high")
    if risk not in RISK_LEVELS:
        raise ValueError(f"unsupported workflow risk: {risk}")
    budget = float(payload.get("workflow_budget_usd", 0.05))
    max_stage_cost = float(payload.get("max_stage_cost_usd", min(0.02, budget)))
    if budget <= 0 or max_stage_cost <= 0:
        raise ValueError("workflow and stage budgets must be positive")
    if max_stage_cost > budget:
        raise ValueError("max_stage_cost_usd cannot exceed workflow_budget_usd")
    max_conditional_checks = int(payload.get("max_conditional_checks", 1))
    if max_conditional_checks < 0 or max_conditional_checks > 3:
        raise ValueError("max_conditional_checks must be between 0 and 3")
    return {
        "schema": "hermes_router_hub.workflow_contract.v1",
        "workflow_id": str(payload.get("workflow_id") or "wf_" + uuid.uuid4().hex),
        "objective": objective,
        "objective_fingerprint": sha256(objective.encode("utf-8")).hexdigest()[:16],
        "task_type": task_type,
        "domain": str(payload.get("domain") or "general"),
        "risk": risk,
        "quality_target": quality_target,
        "privacy": privacy,
        "paid_allowed": bool(payload.get("paid_allowed", True)),
        "workflow_budget_usd": round(budget, 6),
        "max_stage_cost_usd": round(max_stage_cost, 6),
        "max_conditional_checks": max_conditional_checks,
        "automation_mode": automation_mode,
        "hermes_security_approved": bool(payload.get("hermes_security_approved", False)),
        "success_criteria": _normalized_criteria(payload.get("success_criteria")),
        "constraints": [str(item).strip() for item in payload.get("constraints", []) if str(item).strip()],
        "non_goals": [str(item).strip() for item in payload.get("non_goals", []) if str(item).strip()],
    }


def _stage_from_role(role: dict[str, Any], *, stage: str, purpose: str, required_inputs: list[str]) -> dict[str, Any]:
    selected = role.get("selected") or None
    budget = (selected or {}).get("budget") or {}
    return {
        "stage": stage,
        "role": role.get("stage"),
        "purpose": purpose,
        "call_policy": "required",
        "selected": selected,
        "projected_cost_usd": budget.get("projected_cost_usd"),
        "required_inputs": required_inputs,
        "required_evidence": ["artifact_fingerprint", "criterion_status", "decision_reasons"],
    }


def build_workflow_plan(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    contract = validate_workflow_contract(payload)
    route = route_plan(
        settings,
        task="plan",
        prompt=contract["objective"],
        domain=contract["domain"],
        quality_target=contract["quality_target"],
        risk=contract["risk"],
        paid_allowed=contract["paid_allowed"],
        prefer_free=not contract["paid_allowed"],
        privacy=contract["privacy"],
        max_cost_usd=contract["max_stage_cost_usd"],
    )
    effective_privacy = str((route.get("descriptor") or {}).get("privacy") or contract["privacy"])
    roles = {row["stage"]: row for row in route.get("role_pipeline", [])}
    required_roles = ("plan", "audit", "execute", "verify")
    stages = [
        _stage_from_role(
            roles.get("plan", {}),
            stage="plan_design",
            purpose="冻结目标、约束、非目标、实施步骤、验收方法和回退方案",
            required_inputs=["objective", "constraints", "non_goals", "success_criteria"],
        ),
        _stage_from_role(
            roles.get("audit", {}),
            stage="plan_audit",
            purpose="在执行前独立审查规划的遗漏、错误假设、成本和不可验收项",
            required_inputs=["plan_design_artifact", "objective", "success_criteria"],
        ),
        _stage_from_role(
            roles.get("execute", {}),
            stage="execute",
            purpose="只按已通过审查的规划实施，任何范围变化先进入检查点",
            required_inputs=["approved_plan", "plan_audit_findings", "success_criteria"],
        ),
        {
            "stage": "process_checkpoint",
            "role": "verify",
            "purpose": "本地检查目标对齐、证据、范围变化、累计成本和验收进度；发现漂移才调用独立模型",
            "call_policy": "conditional",
            "selected": (roles.get("verify", {}) or {}).get("selected"),
            "projected_cost_usd": (((roles.get("verify", {}) or {}).get("selected") or {}).get("budget") or {}).get("projected_cost_usd"),
            "required_inputs": ["current_artifact", "approved_plan", "success_criteria", "spent_usd"],
            "required_evidence": ["artifact_fingerprint", "objective_alignment", "criterion_status", "scope_changes"],
            "trigger_conditions": ["scope_change", "failed_or_unknown_criterion", "missing_evidence", "objective_uncertain"],
        },
        _stage_from_role(
            roles.get("verify", {}),
            stage="final_verify",
            purpose="从原始目标和验收标准独立复验最终结果，并检查是否偏离主线",
            required_inputs=["final_artifact", "objective", "approved_plan", "success_criteria", "all_checkpoint_receipts"],
        ),
    ]
    if contract["quality_target"] == "frontier":
        quality_stage = _stage_from_role(
            roles.get("quality_enhance", {}),
            stage="quality_enhance",
            purpose="只在最终复验通过且明确存在表达或覆盖缺口时改善质量，不改变事实与范围",
            required_inputs=["verified_final_artifact", "final_verify_receipt"],
        )
        quality_stage["call_policy"] = "conditional"
        quality_stage["trigger_conditions"] = ["verified_quality_gap", "clarity_gap", "coverage_gap"]
        stages.append(quality_stage)

    hard_stops: list[str] = []
    if contract["automation_mode"] == "unattended" and not contract["hermes_security_approved"]:
        hard_stops.append("unattended execution blocked until Hermes security gate is explicitly approved")
    if effective_privacy == "local_only":
        hard_stops.append("local_only workflow cannot execute the selected external model stages")
    missing_roles = [role for role in required_roles if not (roles.get(role, {}) or {}).get("selected")]
    if missing_roles:
        hard_stops.append("no eligible selected model for roles: " + ", ".join(missing_roles))
    planner_family = (((roles.get("plan", {}) or {}).get("selected") or {}).get("model_family"))
    auditor_family = (((roles.get("audit", {}) or {}).get("selected") or {}).get("model_family"))
    if planner_family and planner_family == auditor_family:
        hard_stops.append("plan audit must use a model family independent from planning")
    executor_family = (((roles.get("execute", {}) or {}).get("selected") or {}).get("model_family"))
    verifier_family = (((roles.get("verify", {}) or {}).get("selected") or {}).get("model_family"))
    if executor_family and executor_family == verifier_family:
        hard_stops.append("final verification must use a model family independent from execution")

    required_costs = [float(stage["projected_cost_usd"]) for stage in stages if stage["call_policy"] == "required" and stage.get("projected_cost_usd") is not None]
    unknown_required = [stage["stage"] for stage in stages if stage["call_policy"] == "required" and stage.get("projected_cost_usd") is None]
    checkpoint_reserve = float(stages[3].get("projected_cost_usd") or 0) * contract["max_conditional_checks"]
    quality_reserve = sum(
        float(stage.get("projected_cost_usd") or 0)
        for stage in stages
        if stage["stage"] == "quality_enhance" and stage["call_policy"] == "conditional"
    )
    conditional_cost = checkpoint_reserve + quality_reserve
    projected_required = round(sum(required_costs), 6)
    projected_ceiling = round(projected_required + conditional_cost, 6)
    if unknown_required:
        hard_stops.append("required stages have unknown projected cost: " + ", ".join(unknown_required))
    if projected_ceiling > contract["workflow_budget_usd"]:
        hard_stops.append(
            f"projected workflow ceiling {projected_ceiling:.6f} exceeds budget {contract['workflow_budget_usd']:.6f}"
        )

    return {
        "schema": "hermes_router_hub.workflow_plan.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract": contract,
        "effective_privacy": effective_privacy,
        "stages": stages,
        "budget": {
            "workflow_budget_usd": contract["workflow_budget_usd"],
            "max_stage_cost_usd": contract["max_stage_cost_usd"],
            "projected_required_usd": projected_required,
            "reserved_conditional_usd": round(conditional_cost, 6),
            "reserved_checkpoint_usd": round(checkpoint_reserve, 6),
            "reserved_quality_enhance_usd": round(quality_reserve, 6),
            "projected_total_ceiling_usd": projected_ceiling,
        },
        "gates": {
            "planning_must_pass_audit_before_execute": True,
            "scope_change_requires_checkpoint": True,
            "failed_or_unknown_criterion_requires_verification": True,
            "final_delivery_requires_all_criteria_pass": True,
            "quality_enhancement_cannot_change_scope": True,
        },
        "ready_to_execute": not hard_stops,
        "hard_stops": hard_stops,
        "execution_boundary": "Use the existing smart-llm-router task command one stage at a time; this plan never calls a model.",
    }


def evaluate_workflow_checkpoint(contract_payload: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
    contract = validate_workflow_contract(contract_payload)
    if checkpoint.get("schema") != "hermes_router_hub.workflow_checkpoint.v1":
        raise ValueError("unsupported workflow checkpoint schema")
    if str(checkpoint.get("workflow_id") or "") != contract["workflow_id"]:
        raise ValueError("checkpoint workflow_id does not match contract")
    stage = str(checkpoint.get("stage") or "")
    if stage not in WORKFLOW_STAGES:
        raise ValueError(f"unsupported workflow stage: {stage}")
    alignment = str(checkpoint.get("objective_alignment") or "uncertain")
    if alignment not in {"aligned", "uncertain", "deviated"}:
        raise ValueError(f"unsupported objective_alignment: {alignment}")
    evidence = [str(item).strip() for item in checkpoint.get("evidence", []) if str(item).strip()]
    scope_changes = [str(item).strip() for item in checkpoint.get("scope_changes", []) if str(item).strip()]
    raw_status = checkpoint.get("criterion_status") or {}
    criterion_status = {
        row["id"]: str(raw_status.get(row["id"], "not_checked"))
        for row in contract["success_criteria"]
    }
    invalid_statuses = sorted({value for value in criterion_status.values() if value not in {"pass", "fail", "unknown", "not_checked"}})
    if invalid_statuses:
        raise ValueError("unsupported criterion statuses: " + ", ".join(invalid_statuses))
    spent_usd = float(checkpoint.get("spent_usd", 0.0))
    reasons: list[str] = []
    hard_stop = False
    if spent_usd > contract["workflow_budget_usd"]:
        reasons.append("workflow budget exceeded")
        hard_stop = True
    if alignment == "deviated":
        reasons.append("objective deviation detected")
        hard_stop = True
    elif alignment == "uncertain":
        reasons.append("objective alignment is uncertain")
    if scope_changes:
        reasons.append("scope changed after plan approval")
    if not evidence:
        reasons.append("checkpoint evidence is missing")
    failed = [key for key, value in criterion_status.items() if value == "fail"]
    unresolved_values = {"unknown", "not_checked"} if stage == "final_verify" else {"unknown"}
    unresolved = [key for key, value in criterion_status.items() if value in unresolved_values]
    if failed:
        reasons.append("failed criteria: " + ", ".join(failed))
    if unresolved:
        reasons.append("unresolved criteria: " + ", ".join(unresolved))

    if stage == "final_verify":
        if failed or unresolved or not evidence or alignment != "aligned" or scope_changes:
            hard_stop = True
        decision = "stop" if hard_stop else "complete"
    elif hard_stop:
        decision = "stop"
    elif reasons:
        decision = "verify_required"
    else:
        decision = "continue"
    return {
        "schema": "hermes_router_hub.workflow_checkpoint_receipt.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workflow_id": contract["workflow_id"],
        "stage": stage,
        "decision": decision,
        "objective_alignment": alignment,
        "drift_detected": bool(reasons),
        "drift_reasons": reasons,
        "criterion_status": criterion_status,
        "evidence_count": len(evidence),
        "scope_changes": scope_changes,
        "spent_usd": round(spent_usd, 6),
        "remaining_budget_usd": round(max(0.0, contract["workflow_budget_usd"] - spent_usd), 6),
    }


def write_workflow_artifact(payload: dict[str, Any], directory: str | Path) -> Path:
    target_dir = Path(directory).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    workflow_id = str((payload.get("contract") or {}).get("workflow_id") or payload.get("workflow_id") or "workflow")
    artifact_type = str(payload.get("schema") or "artifact").split(".")[-2]
    target = target_dir / f"{workflow_id}.{artifact_type}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
