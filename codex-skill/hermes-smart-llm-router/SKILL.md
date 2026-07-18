---
name: hermes-smart-llm-router
description: Use when Hermes or a local agent should route work through the global role-aware, multimodal, privacy- and budget-gated Smart LLM Router.
---

# Hermes Smart LLM Router

## Runtime

- Launcher: `smart-llm-router`
- Project: `/path/to/smart-llm-router`
- Runtime: `SMART_LLM_RUNTIME_DIR` or the standard user state directory
- Private env: project `.env` or `SMART_LLM_ENV_FILE`
- Credential catalog: optional `SMART_LLM_CREDENTIAL_CATALOG`

Never print private environment files or API keys.

## Workflow

```bash
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router maintain --limit 8
smart-llm-router route-stats --limit 1000
smart-llm-router golden-eval \
  /path/to/smart-llm-router/examples/golden-sets/audit-public-v1.json \
  --provider groq-free --model qwen/qwen3.6-27b \
  --baseline-provider deepseek-direct-paid --baseline-model deepseek-v4-pro \
  --allow-paid
smart-llm-router discover-ark --limit 100
smart-llm-router route-plan \
  "任务描述" --task plan --quality-target frontier --paid-allowed --max-cost-usd 0.05
smart-llm-router workflow-plan \
  /path/to/workflow-contract.json --output-dir /path/to/workflow-runtime
smart-llm-router workflow-check \
  /path/to/workflow-contract.json /path/to/checkpoint.json \
  --output-dir /path/to/workflow-runtime
```

Use five explicit production roles: `plan`, `execute`, `audit`, `verify`, and `quality_enhance`. Select one main model per stage. Enforce minimum role bands `draft=2`, `production=3`, `audit=4`, and `frontier=4`; lower or unregistered models never enter that role task. Among qualified routes, order by degradation, budget eligibility, free status, retry-adjusted expected cost, successful-call P95 latency, quality surplus, stable role order, and provider priority. No qualified route means fail closed, not general-pool fallback. Plan audit differs from planning and final verification differs from execution; five unique providers are not required.

`route-stats` is the local evidence surface. A route needs at least three non-infrastructure health samples before it can be marked degraded. Clear local DNS/network failures are reported separately and do not lower model health. API success is not answer quality and cannot promote a discovered model into a production role without task probes, a golden-set pass, and an explicit quality-band entry.

Before adding a discovered model to `plan`, `execute`, `audit`, `verify`, or `quality_enhance`, Hermes must run `golden-eval`. Stop when candidate hard gates fail; call the paid baseline only after they pass, and obtain a blind review from a third family only after baseline non-regression passes. Then run `promotion-check`. `pass` means eligible for explicit registration only; never edit the role table automatically. Keep private evaluation inputs local and never put credentials in a golden suite.

Choose the role-matched public suite from `plan-public-v1`, `execute-public-v1`,
`audit-public-v1`, and `verify-public-v1`. As of 2026-07-18,
`groq-free/openai/gpt-oss-120b` is explicitly registered at `verify` band 2
after candidate/baseline/third-family review. It is `trial_quota`, is limited to
public low-risk draft verification, and must not outrank band 3/4 routes.

For important work, freeze the objective and measurable success criteria in a workflow contract. Audit the plan before execution, run deterministic checkpoints during execution, and call an independent verifier only when a checkpoint returns `verify_required`. Final delivery requires `complete`; never ignore `stop`.

`not_checked` criteria do not trigger a paid process check before they are due. Any failed or unknown criterion, scope change, missing evidence, objective uncertainty, privacy violation, or budget breach fails closed. Keep `automation_mode=manual_controlled` until Hermes security approval is explicit.

The public template keeps Gemini in free-tier mode. Never route it as paid unless `SMART_LLM_GEMINI_PAID_ENABLED=true` is explicitly configured. Use Gemini free tier only for public, non-sensitive material. Quality enhancement is conditional after a verified quality gap.

OpenRouter and Groq free candidates are discovered dynamically. The runtime refreshes a stale discovery snapshot on demand (default six hours), keeps the last provider snapshot when discovery temporarily fails, and cools a model after 429, timeout, or endpoint failure. Groq availability is quota-backed trial capacity, not guaranteed permanent free capacity. Newly discovered models may serve low-risk general work, but they must pass task probes and receive an explicit role quality band before planning, execution, audit, or final verification. The current exception is the evidence-backed GPT-OSS 120B verification band above; it is registered, not merely discovered.

For audio/video transcription, use local `asr-status` and `transcribe` first. Private palm images, WeChat data, identity data, and raw course media stay local unless external upload is explicitly authorized.

This command bridge does not replace Hermes' conversation model. It routes auxiliary and delegated model work while Hermes remains the controller.
