#!/usr/bin/env python3
"""Bounded daily/weekly Router health cycle.

Daily mode probes free/local routes only. Weekly paid mode is explicit and uses
one synthetic prompt per role, an exact route, a $0.01 single-call ceiling and
a $0.05 workflow ceiling. No provider fallback is allowed by this script.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smart_llm_router.config import load_settings
from smart_llm_router.router import maintain_pool, run_llm_task


ROLE_ROUTES = {
    "plan": ("qwen-frontier-paid", "qwen3.7-max"),
    "execute": ("deepseek-direct-paid", "deepseek-v4-flash"),
    "audit": ("deepseek-direct-paid", "deepseek-v4-pro"),
    "verify": ("deepseek-direct-paid", "deepseek-v4-flash"),
    "research_enhance": ("qwen-frontier-paid", "qwen3.7-max"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-paid", action="store_true")
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    settings = load_settings()
    report: dict[str, object] = {
        "schema": "smart_llm_router.health_cycle.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "paid_enabled": bool(args.include_paid),
        "paid_budget_usd": 0.05 if args.include_paid else 0.0,
        "single_call_budget_usd": 0.01,
        "model_calls": 0,
        "paid_calls": 0,
        "routes": [],
    }
    report["free_health"] = maintain_pool(settings, include_paid=False, timeout=args.timeout, limit=0)
    if args.include_paid:
        for task, (provider, model) in ROLE_ROUTES.items():
            try:
                result = run_llm_task(
                    settings,
                    task=task,
                    prompt=f"Router synthetic health check {task}: only output OK-{task}.",
                    prefer_free=False,
                    paid_fallback=True,
                    provider=provider,
                    model=model,
                    quality_target="production" if task != "audit" else "audit",
                    privacy="external_allowed",
                    max_cost_usd=0.01,
                    workflow_id="router-weekly-health",
                    workflow_max_cost_usd=0.05,
                    request_timeout=args.timeout,
                    strict_controls=True,
                    cache_enabled=False,
                )
                report["routes"].append({"task": task, "provider": result.provider, "model": result.model, "ok": True})
                report["model_calls"] = int(report["model_calls"]) + 1
                report["paid_calls"] = int(report["paid_calls"]) + 1
            except Exception as exc:
                report["routes"].append({"task": task, "provider": provider, "model": model, "ok": False, "error": str(exc)[:240]})
    output = Path(args.output).expanduser() if args.output else settings.data_dir / "health_cycle_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "model_calls": report["model_calls"], "paid_calls": report["paid_calls"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
