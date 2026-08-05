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
TASK_FAMILIES = tuple(sorted(set(TASK_TYPES) | {"text_light", "text_deep", "tool_only"}))
WORKFLOW_STAGES = (
    "plan_design",
    "research_enhance",
    "plan_audit",
    "plan_repair",
    "plan_delta_verify",
    "execute",
    "process_checkpoint",
    "final_verify",
    "result_repair",
    "final_delta_verify",
    "closeout",
    "quality_enhance",
)
WORKFLOW_CONTRACT_SCHEMAS = ("hermes_router_hub.workflow_contract.v1", "hermes_router_hub.workflow_contract.v2")
WORKFLOW_COMPLEXITY_TIERS = ("simple", "standard", "complex")
QUALITY_TARGETS = ("production", "audit", "frontier")
PRIVACY_MODES = ("auto", "local_only", "external_allowed")
AUTOMATION_MODES = ("manual_controlled", "unattended")
RISK_LEVELS = ("low", "medium", "high")

DEFAULT_REDESIGN_TRIGGERS = (
    "objective_invalid",
    "architecture_unworkable",
    "acceptance_design_invalid",
    "security_model_invalid",
)


def _materialization_gate(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("materialization_gate") or {}
    if not isinstance(raw, dict):
        raise ValueError("materialization_gate must be an object")
    required_fields = raw.get("required_fields") or []
    if not isinstance(required_fields, list) or any(not str(field).strip() for field in required_fields):
        raise ValueError("materialization_gate.required_fields must be a list of non-empty field names")
    return {
        "required": bool(raw.get("required", False)),
        "parse_json": bool(raw.get("parse_json", False)),
        "non_empty": bool(raw.get("non_empty", True)),
        "required_fields": [str(field).strip() for field in required_fields],
    }


def _contract_fingerprint(contract: dict[str, Any]) -> str:
    canonical = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_task_contract(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != "hermes_router_hub.task_contract.v1":
        raise ValueError("unsupported task contract schema")
    sensitivity = str(payload.get("sensitivity") or "public")
    if sensitivity not in SENSITIVITY_CLASSES:
        raise ValueError(f"unsupported sensitivity: {sensitivity}")
    task_family = str(payload.get("task_family") or "text_light")
    if task_family not in TASK_FAMILIES:
        raise ValueError(f"unsupported task_family: {task_family}")
    free_only = bool(payload.get("free_only", True))
    paid_allowed = bool(payload.get("paid_fallback_allowed", False))
    cloud_raw = bool(payload.get("internal_raw_cloud_allowed", False))
    sanitized_for_external = bool(payload.get("sanitized_for_external", False))
    external_processing_approved = bool(payload.get("external_processing_approved", False))
    if free_only and paid_allowed:
        raise ValueError("free_only and paid_fallback_allowed cannot both be true")
    if sensitivity == "secret":
        raise ValueError("secret material must not be routed to a model")
    if sensitivity == "internal_raw" and cloud_raw:
        raise ValueError("internal_raw cloud routing requires a separate explicit execution approval")
    allow_cloud = sensitivity in {"public", "external_cacheable"} or (
        sensitivity == "internal_summary" and sanitized_for_external and external_processing_approved
    )
    contract = {
        "schema": "hermes_router_hub.task_contract.v1",
        "task_id": str(payload.get("task_id") or "task-unknown"),
        "agent": str(payload.get("agent") or "codex"),
        "task_family": task_family,
        "sensitivity": sensitivity,
        "free_only": free_only,
        "paid_fallback_allowed": paid_allowed,
        "sanitized_for_external": sanitized_for_external,
        "external_processing_approved": external_processing_approved,
        "allow_cloud": allow_cloud,
        "route_receipt_required": bool(payload.get("route_receipt_required", True)),
        "materialization_gate": _materialization_gate(payload),
    }
    contract["contract_fingerprint"] = _contract_fingerprint(contract)
    return contract


def validate_materialized_output(path: str | Path, gate: dict[str, Any]) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"materialized output is not a file: {target}")
    content = target.read_bytes()
    if gate.get("non_empty", True) and not content:
        raise ValueError("materialized output is empty")
    parsed: Any = None
    if gate.get("parse_json") or gate.get("required_fields"):
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("materialized output is not valid UTF-8 JSON") from exc
    required_fields = gate.get("required_fields") or []
    if required_fields:
        if not isinstance(parsed, dict):
            raise ValueError("materialized output must be a JSON object when required_fields are configured")
        missing = [field for field in required_fields if field not in parsed]
        if missing:
            raise ValueError(f"materialized output missing required fields: {', '.join(missing)}")
    return {
        "materialized": True,
        "path": str(target),
        "size_bytes": len(content),
        "sha256": sha256(content).hexdigest(),
        "validated_at": datetime.now(timezone.utc).isoformat(),
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
    route_alias: str | None = None,
    fallback_chain: list[dict[str, Any] | str] | None = None,
    ledger_id: str | None = None,
    output_path: str | None = None,
    production_changed: bool = False,
) -> dict[str, Any]:
    output = {"materialized": False, "path": None, "size_bytes": None, "sha256": None, "validated_at": None}
    if output_path:
        output = validate_materialized_output(output_path, contract.get("materialization_gate") or {})
    elif (contract.get("materialization_gate") or {}).get("required") and mode == "execute":
        raise ValueError("materialization gate requires an output_path for execute mode")
    return {
        "schema": "hermes_router_hub.route_receipt.v1",
        "receipt_id": "rr_" + uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "agent": contract["agent"],
        "task_id": contract["task_id"],
        "contract_fingerprint": contract["contract_fingerprint"],
        "task_family": contract["task_family"],
        "sensitivity": contract["sensitivity"],
        "route_alias": route_alias,
        "selected_provider": selected_provider,
        "selected_model": selected_model,
        "cost_class": cost_class,
        "allow_cloud": contract["allow_cloud"],
        "paid_fallback_used": paid_fallback_used,
        "fallback_chain": list(fallback_chain or []),
        "ledger_id": ledger_id,
        "decision_reasons": decision_reasons,
        "output": output,
        "production_changed": bool(production_changed),
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


def _normalized_budget_policy(payload: dict[str, Any], schema: str) -> dict[str, float]:
    if schema == "hermes_router_hub.workflow_contract.v1":
        workflow_budget = float(payload.get("workflow_budget_usd", 0.05))
        max_stage_cost = float(payload.get("max_stage_cost_usd", min(0.02, workflow_budget)))
        if workflow_budget <= 0 or max_stage_cost <= 0:
            raise ValueError("workflow and stage budgets must be positive")
        if max_stage_cost > workflow_budget:
            raise ValueError("max_stage_cost_usd cannot exceed workflow_budget_usd")
        return {
            "soft_target_usd": round(workflow_budget, 6),
            "elastic_limit_usd": round(workflow_budget, 6),
            "anomaly_hard_limit_usd": round(workflow_budget, 6),
            "max_stage_cost_usd": round(max_stage_cost, 6),
        }

    raw = payload.get("budget_policy") or {}
    if not isinstance(raw, dict):
        raise ValueError("budget_policy must be an object")
    soft = float(raw.get("soft_target_usd", 0.03))
    elastic = float(raw.get("elastic_limit_usd", 0.10))
    hard = float(raw.get("anomaly_hard_limit_usd", 0.25))
    max_stage = float(raw.get("max_stage_cost_usd", min(0.03, elastic)))
    if min(soft, elastic, hard, max_stage) <= 0:
        raise ValueError("budget_policy values must be positive")
    if not soft <= elastic <= hard:
        raise ValueError("budget_policy must satisfy soft_target <= elastic_limit <= anomaly_hard_limit")
    if max_stage > elastic:
        raise ValueError("budget_policy.max_stage_cost_usd cannot exceed elastic_limit_usd")
    return {
        "soft_target_usd": round(soft, 6),
        "elastic_limit_usd": round(elastic, 6),
        "anomaly_hard_limit_usd": round(hard, 6),
        "max_stage_cost_usd": round(max_stage, 6),
    }


def _normalized_workspace_planner(raw: Any, complexity_tier: str) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("workspace_planner must be an object")
    default_model = "gpt-5.6-terra" if complexity_tier == "simple" else "gpt-5.6-sol"
    default_effort = "medium" if complexity_tier == "simple" else "high" if complexity_tier == "standard" else "xhigh"
    model = str(raw.get("model") or default_model).strip()
    effort = str(raw.get("reasoning_effort") or default_effort).strip()
    if model not in {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}:
        raise ValueError(f"unsupported workspace planner model: {model}")
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError(f"unsupported workspace planner reasoning_effort: {effort}")
    if complexity_tier == "complex" and model != "gpt-5.6-sol":
        raise ValueError("complex workflows require gpt-5.6-sol as workspace planner")
    return {
        "provider": "codex-subscription",
        "model": model,
        "model_family": "openai",
        "reasoning_effort": effort,
        "resource_class": "subscription_quota",
        "workspace_native": True,
        "router_executable": False,
        "marginal_cash_cost_usd": 0.0,
    }


def _normalized_research_sources(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("research_sources must be a list")
    sources: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("research_sources entries must be objects")
        url = str(item.get("url") or "").strip()
        accessed_at = str(item.get("accessed_at") or "").strip()
        title = str(item.get("title") or url).strip()
        if not url.startswith(("https://", "http://")) or not accessed_at:
            raise ValueError("research_sources entries require url and accessed_at")
        sources.append({"title": title, "url": url, "accessed_at": accessed_at})
    return sources


def validate_workflow_contract(payload: dict[str, Any]) -> dict[str, Any]:
    schema = str(payload.get("schema") or "")
    if schema not in WORKFLOW_CONTRACT_SCHEMAS:
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
    complexity_tier = str(payload.get("complexity_tier") or ({"low": "simple", "medium": "standard", "high": "complex"}[risk]))
    if complexity_tier not in WORKFLOW_COMPLEXITY_TIERS:
        raise ValueError(f"unsupported complexity_tier: {complexity_tier}")
    budget_policy = _normalized_budget_policy(payload, schema)
    max_conditional_checks = int(payload.get("max_conditional_checks", 1))
    if max_conditional_checks < 0 or max_conditional_checks > 3:
        raise ValueError("max_conditional_checks must be between 0 and 3")
    max_plan_repair_loops = int(payload.get("max_plan_repair_loops", 1))
    max_result_repair_loops = int(payload.get("max_result_repair_loops", 1))
    if max_plan_repair_loops not in {0, 1, 2} or max_result_repair_loops not in {0, 1, 2}:
        raise ValueError("repair loop limits must be between 0 and 2")
    research_required = bool(payload.get("research_required", complexity_tier == "complex"))
    research_sources = _normalized_research_sources(payload.get("research_sources"))
    workspace_planner = _normalized_workspace_planner(payload.get("workspace_planner"), complexity_tier)
    redesign_triggers = [
        str(item).strip()
        for item in payload.get("redesign_triggers", DEFAULT_REDESIGN_TRIGGERS)
        if str(item).strip()
    ]
    source_manifest_fingerprint = _contract_fingerprint({"sources": research_sources})[:16]
    return {
        "schema": schema,
        "workflow_id": str(payload.get("workflow_id") or "wf_" + uuid.uuid4().hex),
        "objective": objective,
        "objective_fingerprint": sha256(objective.encode("utf-8")).hexdigest()[:16],
        "task_type": task_type,
        "domain": str(payload.get("domain") or "general"),
        "risk": risk,
        "complexity_tier": complexity_tier,
        "quality_target": quality_target,
        "privacy": privacy,
        "paid_allowed": bool(payload.get("paid_allowed", True)),
        "workflow_budget_usd": budget_policy["elastic_limit_usd"],
        "max_stage_cost_usd": budget_policy["max_stage_cost_usd"],
        "budget_policy": budget_policy,
        "max_conditional_checks": max_conditional_checks,
        "max_plan_repair_loops": max_plan_repair_loops,
        "max_result_repair_loops": max_result_repair_loops,
        "automation_mode": automation_mode,
        "hermes_security_approved": bool(payload.get("hermes_security_approved", False)),
        "success_criteria": _normalized_criteria(payload.get("success_criteria")),
        "constraints": [str(item).strip() for item in payload.get("constraints", []) if str(item).strip()],
        "non_goals": [str(item).strip() for item in payload.get("non_goals", []) if str(item).strip()],
        "workspace_planner": workspace_planner,
        "workspace_execution_required": bool(payload.get("workspace_execution_required", complexity_tier != "simple")),
        "research_required": research_required,
        "research_sources": research_sources,
        "source_manifest_fingerprint": source_manifest_fingerprint,
        "redesign_triggers": redesign_triggers,
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


def _stage_from_selected(
    selected: dict[str, Any] | None,
    *,
    stage: str,
    role: str,
    purpose: str,
    required_inputs: list[str],
    call_policy: str,
    trigger_conditions: list[str] | None = None,
) -> dict[str, Any]:
    budget = (selected or {}).get("budget") or {}
    row = {
        "stage": stage,
        "role": role,
        "purpose": purpose,
        "call_policy": call_policy,
        "selected": selected,
        "projected_cost_usd": budget.get("projected_cost_usd", 0.0 if role in {"codex_controller", "local_gate"} else None),
        "required_inputs": required_inputs,
        "required_evidence": ["artifact_fingerprint", "criterion_status", "decision_reasons"],
    }
    if trigger_conditions:
        row["trigger_conditions"] = trigger_conditions
    return row


def _controller_stage(contract: dict[str, Any]) -> dict[str, Any]:
    selected = dict(contract["workspace_planner"])
    selected["selection_reason"] = "workspace_native_planning_then_complexity_adjusted_reasoning"
    selected["budget"] = {
        "eligible": True,
        "projected_cost_usd": 0.0,
        "cash_cost_basis": "included_subscription_quota",
    }
    return _stage_from_selected(
        selected,
        stage="plan_design",
        role="codex_controller",
        purpose="使用最理解工作区的Codex模型冻结目标、边界、架构、验收、风险与回滚",
        required_inputs=["objective", "constraints", "non_goals", "success_criteria", "workspace_state"],
        call_policy="controller_required",
    )


def _codex_execution_fallback(complexity_tier: str) -> dict[str, Any]:
    model = "gpt-5.6-luna" if complexity_tier == "simple" else "gpt-5.6-terra"
    return {
        "provider": "codex-subscription",
        "model": model,
        "model_family": "openai",
        "resource_class": "subscription_quota",
        "workspace_native": True,
        "router_executable": False,
        "budget": {"eligible": True, "projected_cost_usd": 0.0, "cash_cost_basis": "included_subscription_quota"},
        "selection_reason": "workspace_native_fallback_when_no_cheaper_eligible_external_executor",
    }


def _build_legacy_workflow_plan(contract: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    effective_privacy = str((route.get("descriptor") or {}).get("privacy") or contract["privacy"])
    roles = {row["stage"]: row for row in route.get("role_pipeline", [])}
    stages = [
        _stage_from_role(roles.get("plan", {}), stage="plan_design", purpose="冻结目标、约束、非目标、实施步骤、验收方法和回退方案", required_inputs=["objective", "constraints", "non_goals", "success_criteria"]),
        _stage_from_role(roles.get("audit", {}), stage="plan_audit", purpose="在执行前独立审查规划的遗漏、错误假设、成本和不可验收项", required_inputs=["plan_design_artifact", "objective", "success_criteria"]),
        _stage_from_role(roles.get("execute", {}), stage="execute", purpose="只按已通过审查的规划实施，任何范围变化先进入检查点", required_inputs=["approved_plan", "plan_audit_findings", "success_criteria"]),
        _stage_from_selected(
            (roles.get("verify", {}) or {}).get("selected"),
            stage="process_checkpoint",
            role="verify",
            purpose="本地检查目标对齐、证据、范围变化、累计成本和验收进度；发现漂移才调用独立模型",
            required_inputs=["current_artifact", "approved_plan", "success_criteria", "spent_usd"],
            call_policy="conditional",
            trigger_conditions=["scope_change", "failed_or_unknown_criterion", "missing_evidence", "objective_uncertain"],
        ),
        _stage_from_role(roles.get("verify", {}), stage="final_verify", purpose="从原始目标和验收标准独立复验最终结果，并检查是否偏离主线", required_inputs=["final_artifact", "objective", "approved_plan", "success_criteria", "all_checkpoint_receipts"]),
    ]
    if contract["quality_target"] == "frontier":
        quality_stage = _stage_from_role(roles.get("quality_enhance", {}), stage="quality_enhance", purpose="只在最终复验通过且明确存在表达或覆盖缺口时改善质量，不改变事实与范围", required_inputs=["verified_final_artifact", "final_verify_receipt"])
        quality_stage["call_policy"] = "conditional"
        quality_stage["trigger_conditions"] = ["verified_quality_gap", "clarity_gap", "coverage_gap"]
        stages.append(quality_stage)
    hard_stops: list[str] = []
    if contract["automation_mode"] == "unattended" and not contract["hermes_security_approved"]:
        hard_stops.append("unattended execution blocked until Hermes security gate is explicitly approved")
    if effective_privacy == "local_only":
        hard_stops.append("local_only workflow cannot execute the selected external model stages")
    missing_roles = [role for role in ("plan", "audit", "execute", "verify") if not (roles.get(role, {}) or {}).get("selected")]
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
    quality_reserve = sum(float(stage.get("projected_cost_usd") or 0) for stage in stages if stage["stage"] == "quality_enhance" and stage["call_policy"] == "conditional")
    conditional_cost = checkpoint_reserve + quality_reserve
    projected_required = round(sum(required_costs), 6)
    projected_ceiling = round(projected_required + conditional_cost, 6)
    if unknown_required:
        hard_stops.append("required stages have unknown projected cost: " + ", ".join(unknown_required))
    if projected_ceiling > contract["workflow_budget_usd"]:
        hard_stops.append(f"projected workflow ceiling {projected_ceiling:.6f} exceeds budget {contract['workflow_budget_usd']:.6f}")
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
    if contract["schema"] == "hermes_router_hub.workflow_contract.v1":
        return _build_legacy_workflow_plan(contract, route)

    effective_privacy = str((route.get("descriptor") or {}).get("privacy") or contract["privacy"])
    roles = {row["stage"]: row for row in route.get("role_pipeline", [])}
    tier = contract["complexity_tier"]
    research_selected = (roles.get("research_enhance", {}) or {}).get("selected")
    plan_auditor = (roles.get("plan_audit", {}) or {}).get("selected")
    routed_executor = (roles.get("execute", {}) or {}).get("selected")
    executor = _codex_execution_fallback(tier) if contract["workspace_execution_required"] else routed_executor
    generic_verifier = (roles.get("verify", {}) or {}).get("selected")
    verifier = plan_auditor if plan_auditor and (plan_auditor or {}).get("model_family") != (executor or {}).get("model_family") else generic_verifier

    stages: list[dict[str, Any]] = [_controller_stage(contract)]
    if tier != "simple":
        research_policy = "required" if contract["research_required"] else "conditional"
        stages.append(
            _stage_from_selected(
                research_selected,
                stage="research_enhance",
                role="research_enhance",
                purpose="Qwen-Max依据带URL和日期的互联网证据增量增强规划，不替代Sol原始设计",
                required_inputs=["plan_design_artifact", "research_sources", "source_manifest_fingerprint"],
                call_policy=research_policy,
                trigger_conditions=None if research_policy == "required" else ["knowledge_gap", "time_sensitive_knowledge", "external_method_gap"],
            )
        )
        stages.extend(
            [
                _stage_from_selected(
                    plan_auditor,
                    stage="plan_audit",
                    role="plan_audit",
                    purpose="DeepSeek独立挑战审查Sol规划与Qwen增强后的遗漏、错误假设和不可执行点",
                    required_inputs=["objective", "success_criteria", "plan_design_artifact", "research_enhancement", "research_sources"],
                    call_policy="required",
                ),
                _stage_from_selected(
                    executor,
                    stage="plan_repair",
                    role="execute",
                    purpose="只修复规划审计指出的局部差异；根本性缺陷返回Sol重设计",
                    required_inputs=["plan_audit_findings", "approved_design_baseline"],
                    call_policy="conditional",
                    trigger_conditions=["local_plan_findings"],
                ),
                _stage_from_selected(
                    plan_auditor,
                    stage="plan_delta_verify",
                    role="plan_audit",
                    purpose="复用原规划审计模型，只核验整改差异和新冲突",
                    required_inputs=["plan_audit_findings", "plan_repair_diff"],
                    call_policy="conditional",
                    trigger_conditions=["plan_repair_completed"],
                ),
            ]
        )

    stages.append(
        _stage_from_selected(
            executor,
            stage="execute",
            role="execute",
            purpose="使用满足结果门槛的最便宜模型实施；工作区工具任务优先订阅内Codex执行器",
            required_inputs=["approved_plan", "success_criteria", "scope_boundary"],
            call_policy="required" if executor and executor.get("router_executable", True) else "controller_required",
        )
    )
    stages.append(
        _stage_from_selected(
            verifier,
            stage="process_checkpoint",
            role="local_gate",
            purpose="默认用测试、规则、指纹和验收矩阵检查；只有语义不确定或高风险节点才调用模型",
            required_inputs=["current_artifact", "approved_plan", "success_criteria", "scope_changes", "spent_usd"],
            call_policy="conditional",
            trigger_conditions=["scope_change", "irreversible_high_risk_action", "failed_or_unknown_criterion", "missing_evidence", "objective_uncertain"],
        )
    )
    if tier != "simple":
        stages.extend(
            [
                _stage_from_selected(
                    verifier,
                    stage="final_verify",
                    role="verify",
                    purpose="在隔离上下文中从原始目标和冻结规划完整审计最终成果",
                    required_inputs=["final_artifact", "objective", "approved_plan", "success_criteria", "all_checkpoint_receipts", "cost_metrics"],
                    call_policy="required",
                ),
                _stage_from_selected(
                    executor,
                    stage="result_repair",
                    role="execute",
                    purpose="最便宜合格模型只修复最终审计阻断项；非阻断建议按收益进入本轮或intake",
                    required_inputs=["final_verify_findings", "final_artifact"],
                    call_policy="conditional",
                    trigger_conditions=["blocking_final_findings"],
                ),
                _stage_from_selected(
                    verifier,
                    stage="final_delta_verify",
                    role="verify",
                    purpose="复用原最终审计模型，只核验成果整改差异",
                    required_inputs=["final_verify_findings", "result_repair_diff"],
                    call_policy="conditional",
                    trigger_conditions=["result_repair_completed"],
                ),
            ]
        )
    stages.append(
        _stage_from_selected(
            {"provider": "local", "model": "deterministic-closeout", "model_family": "local", "budget": {"eligible": True, "projected_cost_usd": 0.0}},
            stage="closeout",
            role="local_gate",
            purpose="确认全部标准、证据、回滚点、发布登记和采用状态后收口",
            required_inputs=["criterion_status", "verification_receipts", "release_or_rollback_state"],
            call_policy="local_required",
        )
    )

    hard_stops: list[str] = []
    warnings: list[str] = []
    approval_required: list[str] = []
    if contract["automation_mode"] == "unattended" and not contract["hermes_security_approved"]:
        hard_stops.append("unattended execution blocked until Hermes security gate is explicitly approved")
    required_external = [stage for stage in stages if stage["call_policy"] == "required"]
    if effective_privacy == "local_only" and required_external:
        hard_stops.append("local_only workflow cannot execute required external model stages")
    if contract["research_required"] and tier != "simple" and not contract["research_sources"]:
        hard_stops.append("research enhancement requires sources with URL and accessed_at")
    missing_required = [stage["stage"] for stage in stages if stage["call_policy"] in {"required", "controller_required"} and not stage.get("selected")]
    if missing_required:
        hard_stops.append("no eligible selected model for stages: " + ", ".join(missing_required))

    planner_family = contract["workspace_planner"]["model_family"]
    research_family = (research_selected or {}).get("model_family")
    auditor_family = (plan_auditor or {}).get("model_family")
    if tier != "simple" and auditor_family in {planner_family, research_family}:
        hard_stops.append("plan audit must be independent from both workspace planning and research enhancement")
    executor_family = (executor or {}).get("model_family")
    verifier_family = (verifier or {}).get("model_family")
    if tier != "simple" and executor_family and executor_family == verifier_family:
        hard_stops.append("final verification must use a model family independent from execution")

    required_costs = [float(stage["projected_cost_usd"]) for stage in stages if stage["call_policy"] in {"required", "controller_required", "local_required"} and stage.get("projected_cost_usd") is not None]
    unknown_required = [stage["stage"] for stage in stages if stage["call_policy"] == "required" and stage.get("projected_cost_usd") is None]
    if unknown_required:
        hard_stops.append("required stages have unknown projected cost: " + ", ".join(unknown_required))
    conditional_cost = 0.0
    for stage in stages:
        if stage["call_policy"] != "conditional":
            continue
        multiplier = contract["max_conditional_checks"] if stage["stage"] == "process_checkpoint" else 1
        conditional_cost += float(stage.get("projected_cost_usd") or 0.0) * multiplier
    projected_required = round(sum(required_costs), 6)
    projected_ceiling = round(projected_required + conditional_cost, 6)
    budget_policy = contract["budget_policy"]
    if projected_ceiling > budget_policy["anomaly_hard_limit_usd"]:
        hard_stops.append("projected workflow ceiling exceeds anomaly hard limit")
    elif projected_ceiling > budget_policy["elastic_limit_usd"]:
        approval_required.append("projected workflow ceiling exceeds automatic elastic limit")
    elif projected_ceiling > budget_policy["soft_target_usd"]:
        warnings.append("projected workflow ceiling exceeds soft target; continue within elastic limit")

    return {
        "schema": "hermes_router_hub.workflow_plan.v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract": contract,
        "effective_privacy": effective_privacy,
        "stages": stages,
        "budget": {
            **budget_policy,
            "projected_required_usd": projected_required,
            "reserved_conditional_usd": round(conditional_cost, 6),
            "projected_total_ceiling_usd": projected_ceiling,
            "status": "hard_stop" if hard_stops else "approval_required" if approval_required else "within_elastic" if warnings else "within_soft_target",
        },
        "gates": {
            "planning_must_pass_audit_before_execute": tier != "simple",
            "research_sources_require_url_and_date": True,
            "fundamental_plan_findings_return_to_sol": True,
            "scope_change_requires_checkpoint": True,
            "process_checkpoints_are_local_by_default": True,
            "final_delivery_requires_all_criteria_pass": True,
            "delta_verification_reuses_original_auditor": True,
            "soft_budget_excess_does_not_stop": True,
            "flash_requires_role_golden_gate": True,
        },
        "warnings": warnings,
        "approval_required": approval_required,
        "ready_to_execute": not hard_stops and not approval_required,
        "hard_stops": hard_stops,
        "execution_boundary": "This plan declares Codex subscription stages but cannot invoke them; external stages use smart-llm-router one at a time with explicit privacy and paid authorization.",
    }


def evaluate_workflow_checkpoint(contract_payload: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
    contract = validate_workflow_contract(contract_payload)
    expected_checkpoint_schema = "hermes_router_hub.workflow_checkpoint.v2" if contract["schema"].endswith(".v2") else "hermes_router_hub.workflow_checkpoint.v1"
    if checkpoint.get("schema") != expected_checkpoint_schema:
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
    budget_warnings: list[str] = []
    hard_stop = False
    if contract["schema"].endswith(".v1"):
        if spent_usd > contract["workflow_budget_usd"]:
            reasons.append("workflow budget exceeded")
            hard_stop = True
    else:
        policy = contract["budget_policy"]
        if spent_usd > policy["anomaly_hard_limit_usd"]:
            reasons.append("anomaly hard budget exceeded")
            hard_stop = True
        elif spent_usd > policy["elastic_limit_usd"]:
            reasons.append("elastic budget exceeded")
        elif spent_usd > policy["soft_target_usd"]:
            budget_warnings.append("soft budget exceeded; continue within elastic limit")
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
    terminal_stages = {"final_verify", "final_delta_verify", "closeout"}
    unresolved_values = {"unknown", "not_checked"} if stage in terminal_stages else {"unknown"}
    unresolved = [key for key, value in criterion_status.items() if value in unresolved_values]
    if failed:
        reasons.append("failed criteria: " + ", ".join(failed))
    if unresolved:
        reasons.append("unresolved criteria: " + ", ".join(unresolved))

    if contract["schema"].endswith(".v1"):
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
    else:
        repair_loop_count = int(checkpoint.get("repair_loop_count", 0))
        redesign_required = bool(checkpoint.get("redesign_required", False))
        if hard_stop:
            decision = "stop"
        elif "elastic budget exceeded" in reasons:
            decision = "authorization_required"
        elif stage == "plan_audit" and redesign_required:
            decision = "redesign_required"
        elif stage in {"plan_audit", "plan_delta_verify"} and (failed or unresolved or not evidence):
            decision = "repair_required" if repair_loop_count < contract["max_plan_repair_loops"] else "stop"
        elif stage in {"final_verify", "final_delta_verify"} and (failed or unresolved or not evidence or alignment != "aligned" or scope_changes):
            decision = "repair_required" if repair_loop_count < contract["max_result_repair_loops"] else "stop"
        elif stage == "closeout":
            decision = "complete" if not reasons and evidence and alignment == "aligned" else "stop"
        elif reasons:
            decision = "verify_required"
        else:
            decision = "continue"
    return {
        "schema": "hermes_router_hub.workflow_checkpoint_receipt.v2" if contract["schema"].endswith(".v2") else "hermes_router_hub.workflow_checkpoint_receipt.v1",
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
        "remaining_anomaly_budget_usd": round(max(0.0, contract["budget_policy"]["anomaly_hard_limit_usd"] - spent_usd), 6),
        "budget_warnings": budget_warnings,
    }


def write_workflow_artifact(payload: dict[str, Any], directory: str | Path) -> Path:
    target_dir = Path(directory).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    workflow_id = str((payload.get("contract") or {}).get("workflow_id") or payload.get("workflow_id") or "workflow")
    artifact_type = str(payload.get("schema") or "artifact").split(".")[-2]
    target = target_dir / f"{workflow_id}.{artifact_type}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
