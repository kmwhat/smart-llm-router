---
name: hermes-smart-llm-router
description: Use when Hermes or a local agent should route work through the global role-aware, multimodal, privacy- and budget-gated Smart LLM Router.
---

# Hermes Smart LLM Router

## Runtime

- Launcher: `smart-llm-router`
- Project: `/path/to/smart-llm-router`
- Runtime: `SMART_LLM_RUNTIME_DIR` or the standard user state directory
- Paid workflow budget authority: `$HOME/.smart-llm-router/budget-authority`, independent of runtime isolation
- Legacy v1 workflow budgets are conservatively imported before paid reservation; conflicts fail closed with a migration receipt
- Private env: project `.env` or `SMART_LLM_ENV_FILE`
- Credential catalog: optional `SMART_LLM_CREDENTIAL_CATALOG`

Never print private environment files or API keys.

## Workflow

```bash
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router doctor --quality-target production
smart-llm-router maintain --limit 8
smart-llm-router route-stats --limit 1000
smart-llm-router recommend "Return OK" --task qa --free-only
smart-llm-router route-plan \
  "Return OK" --task qa --quality-target production
smart-llm-router workflow-plan \
  /path/to/workflow-contract.json --output-dir /path/to/workflow-runtime
smart-llm-router workflow-check \
  /path/to/workflow-contract.json /path/to/checkpoint.json \
  --output-dir /path/to/workflow-runtime
```

Use the workflow v2 difficulty profiles instead of forcing every task through one chain. `simple` uses a workspace-native or cheapest-qualified executor plus deterministic checks. `standard` adds strong Codex planning and independent audit. `complex` declares Codex GPT-5.6 Sol planning, sourced Qwen-Max research enhancement, DeepSeek plan challenge audit, bounded low-cost repairs, original-auditor delta verification, economical execution, deterministic checkpoints, independent final verification, and closeout. Codex subscription stages are controller declarations; Hermes and the router must not claim a provider API invoked the subscription model.

Enforce minimum role bands `draft=2`, `production=3`, `audit=4`, and `frontier=4`; lower or unregistered models never enter that role task. Dedicated `research_enhance` and `plan_audit` roles follow the approved Qwen and DeepSeek families after capability, endpoint health, promotion, privacy, and budget gates. Flash-0731 remains ineligible until a complete current-endpoint role gate passes. Final verification must differ from execution, while delta verification reuses the original auditor identity.

`doctor` is the offline readiness surface: it explains configuration drift,
billing class, role coverage, key rotations, and important exclusion reasons.
`route-stats` is the local evidence surface. A route needs at least three non-infrastructure health samples before it can be marked degraded. Clear local DNS/network failures are reported separately and do not lower model health. API success is not answer quality and cannot promote a discovered model into a production role without task probes, a golden-set pass, and an explicit quality-band entry.

Before adding a discovered model to `plan`, `execute`, `audit`, `verify`, or `quality_enhance`, Hermes must run `golden-eval`. Stop when candidate hard gates fail; call the paid baseline only after they pass, and obtain a blind review from a third family only after baseline non-regression passes. Then run `promotion-check`. `pass` means eligible for explicit registration only; never edit the role table automatically. Keep private evaluation inputs local and never put credentials in a golden suite.

Choose the role-matched public suite from `plan-public-v1`, `execute-public-v1`,
`audit-public-v1`, and `verify-public-v1`. As of 2026-07-18,
`groq-free/openai/gpt-oss-120b` is explicitly registered at `verify` band 2
after candidate/baseline/third-family review. It is `trial_quota`, is limited to
public low-risk draft verification, and must not outrank band 3/4 routes.

For important work, freeze the objective and measurable success criteria in a workflow contract. Research enhancement requires source URLs and access dates. Audit the plan before execution, route local findings to the cheapest qualified repair model, return fundamental objective or architecture failures to Sol, and use deterministic checkpoints during execution. Final delivery requires a full independent result audit, any needed delta repair, the original auditor's delta verification, and a `complete` closeout receipt.

`not_checked` criteria do not trigger a paid process check before they are due. Workflow v2 budget policy separates a warning-only soft target, an automatically authorized elastic limit, and an anomaly hard stop. Privacy violations, credentials, destructive actions, objective deviation, unapproved scope expansion, and anomaly-limit breaches remain fail-closed. Keep `automation_mode=manual_controlled` until Hermes security approval is explicit.

The public template keeps Gemini in free-tier mode. Never route it as paid unless `SMART_LLM_GEMINI_PAID_ENABLED=true` is explicitly configured. Use Gemini free tier only for public, non-sensitive material. Quality enhancement is conditional after a verified quality gap. Never infer a trial-quota hard stop from an API success or a zero-cost response; keep the route blocked until the provider-side hard stop has been confirmed.

OpenRouter and Groq free candidates are discovered dynamically. The runtime refreshes a stale discovery snapshot on demand (default six hours), keeps the last provider snapshot when discovery temporarily fails, and cools a model after 429, timeout, or endpoint failure. Groq availability is quota-backed trial capacity, not guaranteed permanent free capacity. Newly discovered models may serve low-risk general work, but they must pass task probes and receive an explicit role quality band before planning, execution, audit, or final verification. The current exception is the evidence-backed GPT-OSS 120B verification band above; it is registered, not merely discovered.

DeepSeek-V4-Flash-0731 remains a pending candidate after its NVIDIA planning gate passed two public cases and then returned 529. Do not assign it a production role band until a complete matching golden run passes.

For audio/video transcription, use local `asr-status` and `transcribe` first. Private images, chat records, identity data, and raw private media stay local unless external upload is explicitly authorized.

This command bridge does not replace Hermes' conversation model. It routes auxiliary and delegated model work while Hermes remains the controller.
