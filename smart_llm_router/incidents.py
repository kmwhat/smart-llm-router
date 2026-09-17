from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INCIDENT_SCHEMA = "smart_llm_router.route_incident.v1"


def _safe_error(value: str | None) -> str:
    text = str(value or "").replace("\n", " ").strip()
    # Keep classification evidence without persisting URLs, headers, or tokens.
    text = re.sub(r"https?://\S+", "<endpoint>", text)
    text = re.sub(r"(?i)(bearer|api[-_ ]?key|token)(?:\s*[:=]\s*|\s+)\S+", r"\1=<redacted>", text)
    return text[:240]


def write_route_incident(
    data_dir: Path,
    *,
    provider: str,
    model: str,
    task: str,
    failure_class: str,
    status_code: int | None = None,
    error: str | None = None,
    quality_target: str | None = None,
    billing_class: str | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    incident_id = "route_" + uuid.uuid4().hex
    payload: dict[str, Any] = {
        "schema": INCIDENT_SCHEMA,
        "incident_id": incident_id,
        "created_at": created_at,
        "provider": provider,
        "model": model,
        "task": task,
        "failure_class": failure_class,
        "status_code": status_code,
        "error": _safe_error(error),
        "quality_target": quality_target,
        "billing_class": billing_class,
        "secret_values_persisted": False,
        "recommended_action": (
            "quarantine_route_and_require_fresh_health"
            if failure_class in {"unavailable_model", "authentication", "permission_denied"}
            else "cooldown_and_reprobe"
        ),
    }
    directory = data_dir / "incidents"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{incident_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["incident_path"] = str(path)
    return payload


def read_route_incidents(data_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    directory = data_dir / "incidents"
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("route_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            row["incident_path"] = str(path)
            rows.append(row)
        if limit > 0 and len(rows) >= limit:
            break
    return rows
