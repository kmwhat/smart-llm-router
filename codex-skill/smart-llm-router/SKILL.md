---
name: smart-llm-router
description: Use when a task should route across free, low-cost, and frontier LLMs by role, modality, privacy, quality, and budget. Supports planning, execution, audit, independent verification, quality enhancement, text, vision/OCR, ASR, embedding, rerank, and provider discovery across DeepSeek, Qwen, GLM, Kimi, Gemini, Doubao/Ark, OpenRouter, NVIDIA, and Groq.
metadata:
  short-description: Cost-aware free-pool LLM routing
---

# Smart LLM Router

Use the standalone router instead of calling provider APIs directly when the user wants low-cost model execution, free-pool fallback, paid low-cost fallback, model health checks, or portable routing across computers.

## Outcome-First Governed Workflow

Choose the smallest sufficient workflow before selecting providers:

- `simple`: Codex Terra or the cheapest qualified executor, deterministic checks, and escalation only on failure or uncertainty.
- `standard`: Codex GPT-5.6 Sol planning, optional sourced research enhancement, independent plan audit, economical execution, and independent final verification.
- `complex`: Codex GPT-5.6 Sol high/xhigh planning; a URL-and-date source pack; Qwen-Max research enhancement; DeepSeek plan challenge audit; cheapest-qualified delta repair; the original auditor's delta verification; economical execution; deterministic checkpoints; full independent final verification; delta repair and closeout.

Codex subscription stages are controller declarations. The router must never claim that a provider API call invoked the user's Codex subscription model. Use `workflow_contract.v2` to record the controller model, reasoning effort, source provenance, repair limits, and soft/elastic/anomaly-hard budget policy.

## Locate the Router

Project root:

```text
/path/to/smart-llm-router
```

If copied elsewhere, use the copied `smart-llm-router` directory. Use the installed
`smart-llm-router` command or `bin/smart-llm-router`. The portable launcher loads
the project `.env` by default or `SMART_LLM_ENV_FILE` when set, and never prints keys.

## Workflow

1. Check configuration without exposing keys:

```bash
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router doctor --quality-target production
smart-llm-router refresh --timeout 6 --limit 5
```

2. Discover current candidate models:

```bash
smart-llm-router discover --limit 20
```

The global runtime automatically refreshes the discovery snapshot when it is older than
`SMART_LLM_DISCOVERY_TTL_HOURS` (default 6). A provider discovery failure retains that
provider's last snapshot. Discovery only admits models to the general free pool; production
roles require benchmark evidence and an explicit quality-band entry before promotion.

3. Refresh the free pool before important work:

```bash
smart-llm-router refresh --timeout 6 --limit 8
smart-llm-router refresh-modalities --timeout 6 --limit 2
```

`doctor` is offline and explains configuration drift, billing class, role
coverage, key rotations, and important exclusion reasons. `refresh` is a live
health probe: it emits progress to stderr and atomically checkpoints a
resumable JSON report after each model.

4. Inspect or clear cooldowns:

```bash
smart-llm-router status
smart-llm-router clear
```

5. Estimate complexity locally before spending tokens:

```bash
smart-llm-router score "Return OK" --task qa
smart-llm-router recommend "Return OK" --task qa --free-only
smart-llm-router route-plan "Return OK" --task qa --quality-target production
smart-llm-router workflow-plan /path/to/workflow-contract.json --output-dir ./runtime/workflows
smart-llm-router workflow-check /path/to/workflow-contract.json /path/to/checkpoint.json --output-dir ./runtime/workflows
```

6. Run tasks:

```bash
smart-llm-router task "Return OK" --task qa --free-only
smart-llm-router task "Audit this public plan" --task audit --paid --max-cost-usd 0.01 --privacy external_allowed
```

All executing commands default to no paid authorization. `task --paid` requires
an explicit `--max-cost-usd`; omitting either causes a local fail-closed result
before any provider request.

7. Review the cost ledger and task-specific route health:

```bash
smart-llm-router ledger --limit 20
smart-llm-router route-stats --task audit --limit 1000
```

8. Before registering a discovered model in a production role, run the golden-set gate:

```bash
smart-llm-router golden-eval \
  /path/to/smart-llm-router/examples/golden-sets/audit-public-v1.json \
  --provider groq-free --model qwen/qwen3.6-27b \
  --baseline-provider deepseek-direct-paid --baseline-model deepseek-v4-pro \
  --output-dir ./runtime/golden-evaluations \
  --allow-paid

smart-llm-router promotion-check \
  /path/to/report.json --review /path/to/blind-review.json
```

Use the matching public suite under `examples/golden-sets`: `plan-public-v1`,
`execute-public-v1`, `audit-public-v1`, or `verify-public-v1`. Do not use one
role's suite to promote another role.

## Routing Policy

Default behavior:

- Let task complexity and risk determine the required `quality_target`; planning is not required to use a free model. Treat `draft=2`, `production=3`, `audit=4`, and `frontier=4` as minimum role-quality floors and reject lower or unregistered models.
- Among routes that meet the required capability floor, order by empirical degradation, budget eligibility, retry-adjusted expected total monetary cost, successful-call P95 latency, and stable tie-breakers. Free is not a separate quality preference: it wins only when its zero price survives the same quality, reliability, privacy, and quota gates.
- For non-trivial production work, prevent rework before optimizing token price: freeze the objective and measurable success criteria, audit the plan independently, execute one approved stage, checkpoint drift and evidence, then independently verify the final result against the original objective.
- Use `workflow-plan` for the complete local dry-run and cumulative budget ceiling. Use `workflow-check` after scope changes, meaningful milestones, failures, and final delivery. A `verify_required` or `stop` decision must not be silently overridden.
- Use one selected main model per stage. Planning and execution do not run ensembles; plan audit and final verification are separate governance gates.
- For complex governed work, use Sol/OpenAI for workspace planning, Qwen-Max for sourced research enhancement, DeepSeek for independent plan challenge audit, the cheapest qualified execution route, and a final verifier independent from execution. Flash-0731 cannot replace V4-Pro until the current endpoint passes the matching role golden gate.
- Treat same-model key rotation as availability failover only. Plan audit must differ from planning and research enhancement, final verification must differ from execution, and delta verification must reuse the corresponding original auditor.
- Distinguish `permanent_free`, `trial_quota`, and `paid`; Qwen, NVIDIA, and Ark trial resources are not permanent-free promises.
- Treat paid permission as an execution capability, not a ranking preference. A
  plan may list paid candidates, but `task` may execute them only with both
  `--paid` and `--max-cost-usd`. Programmatic callers must set
  `paid_fallback=True` explicitly.
- Never infer `trial_quota_guarded=true` from an API success or a reported zero-cost response. Confirm the provider-side hard stop separately; otherwise keep the route blocked for ordinary execution.
- A golden-set pass qualifies a candidate for review; it does not override billing, privacy, budget, or independent-audit gates and never promotes the route automatically.
- Fail closed when a route claims free while using `trial_quota`. Set that provider block's
  `SMART_LLM<n>_TRIAL_QUOTA_GUARDED=true` only after verifying current remaining
  free quota and a hard stop that prevents paid overage.
- Use `--privacy auto|local_only|external_allowed`; private images, chat records, identity data, and raw private media fail closed unless external upload is explicitly allowed.
- Use `--max-cost-usd` for every paid call. In workflow v2, exceeding the soft target only warns; execution may continue inside the pre-authorized elastic limit, while the anomaly hard limit remains fail-closed. Unknown paid prices still fail closed.
- If a model fails with 429, timeout, 403/404, or empty content, mark it in cooldown and skip it next time.
- If the free pool appears fully cooled down, run a light refresh; do not enter
  a paid fallback until the current task has explicit paid authorization and a
  hard cost limit.
- Diagnose free remote routes in three separate layers: public/authenticated catalog discovery,
  `credential-status` authentication evidence, and a fresh `refresh` or `task` runtime probe.
  Never treat OpenRouter or NVIDIA public catalog HTTP 200 as credential validation.
  NVIDIA empty-request HTTP 400/422 is request-validation evidence only and
  remains `indeterminate`; it is not accepted-credential evidence.
- Prefer `refresh-modalities` for important checks; it probes text, vision/OCR, transcript correction, and code routes separately instead of treating a generic QA success as global health. It excludes unprotected trial routes unless `--include-unprotected-trial` is explicitly used for an authorized audit.
- The public template keeps Gemini in free-tier mode. Suppress paid Gemini unless `SMART_LLM_GEMINI_PAID_ENABLED=true`; use its free tier only for public, non-sensitive inputs because quota is restricted and free-tier content may be used for product improvement.
- Role routing is quality-and-cost aware across DeepSeek V4, Qwen 3.7, GLM-5.2, Kimi K3, Gemini Free Tier, and Doubao Seed 2.1/2.0. A public model name is only a candidate until its current endpoint passes a live probe.
- DeepSeek-V4-Flash-0731 is a known low-cost candidate, not a promoted role model. The 2026-08-02 NVIDIA planning gate passed two cases and then returned 529, so keep it `pending_role_golden_gate` until a complete role-matched run passes.
- All ordinary tasks default to no paid authorization; complexity controls the
  quality floor, not permission to spend.
- Repeated identical requests can hit the local response cache.
- Governed external calls should add `--strict-controls`; unsupported or
  misspelled `SMART_LLM` controls fail closed before routing, paid reservation,
  or provider send. Use `--no-cache` for an explicit request-scoped no-read,
  no-write cache path; the supported environment control is
  `SMART_LLM_CACHE=false`, not `SMART_LLM_CACHE_ENABLED=false`.
- Each call writes a local JSONL ledger row with model, estimated tokens, latency, cache/failure status, and estimated cost when pricing is configured.
- `route-stats` derives per-task route health from that ledger. It requires at least three health samples before marking a route degraded and excludes clear local DNS/network infrastructure failures from the health denominator.
- API success proves endpoint health, not answer quality. Never promote a discovered model into a production role from health history alone; require task probes, a task-specific golden set, and explicit quality-band registration.
- For subjective roles, the golden report must include a current baseline and a blind review by a model family different from both candidate and baseline, or an independent human reviewer. A `pass` decision grants eligibility for explicit registration only; it never edits the role table automatically.
- Stop evaluation spending by stage: run the candidate hard gates first, call the paid baseline only after they pass, and call an independent reviewer only after baseline non-regression passes.
- Keep public synthetic suites in the project and private user/task suites in local runtime or the governed knowledge lane. Golden suites must never contain credentials or raw prohibited private payloads.
- `groq-free/openai/gpt-oss-120b` passed the 2026-07-18 public verification gate and is explicitly registered at `verify` band 2. Treat it as `trial_quota`, use it only for public low-risk draft verification, and keep band 3/4 models ahead for higher-risk work.
- Use local retrieval before long context calls so only the most relevant snippets go to the model.
- Vision tasks support local `--image` paths and dynamic failover across free vision models. A failed free vision model enters cooldown and the router immediately tries the next configured vision model.
- Use `route-plan` before production or multimodal work. It prints a local task descriptor, modality requirements, local preprocessing steps, free pool, candidate paid fallback, second-model cross-check, and Codex audit boundary without granting execution permission. `embed`, `rerank`, remote ASR, and image generation use dedicated adapters and require their own explicit paid switches before a billable route may run.
- Governed roles are not a requirement to call every model for every task. Complexity selects the stage graph; process checkpoints are local by default, repair is bounded, and delta verification reuses the original auditor.
- Use `capabilities` to inspect provider-family model modes, including text, vision/OCR, ASR/TTS, image/video generation, embedding, rerank, and code coverage. It separates known API-key capability from currently configured/probed executable model routes, and does not print API keys.
- Treat raw `rerank` scores as provider-specific relative ordering signals, not universal absolute relevance thresholds. For production knowledge retrieval, combine rank, top-k, source type, term hits, and second evidence checks.
- Current production candidate path: `embed` prefers Qwen `text-embedding-v4`, then Zhipu `embedding-3`; `rerank` prefers Zhipu `rerank`, but both commands remain blocked until `--allow-paid` is explicit. Qwen `gte-rerank` has a reserved DashScope adapter path but should stay disabled until account/service permission passes `refresh-modalities`.
- Use `transcript-correct` for long-form ASR correction. It chunks the transcript, applies deterministic cleanup, optionally cross-checks, and writes corrected/report artifacts to disk. Paid main correction requires `--paid-main --max-cost-usd`; the cross-check never inherits that paid permission.
- For long transcripts, Codex should only orchestrate and audit; it should not ingest the whole raw transcript.
- Keep Volcano Ark online inference, Coding Plan, and endpoint ids separate. Their base URLs, model names, quotas, and billing paths are not interchangeable. Treat all configured model names as account-scoped candidates until discovery and task probes succeed.

Task defaults from the latest benchmark:

- `research_enhance`: Qwen 3.7 Max first, with sourced evidence and explicit change tracking.
- `plan_audit`: DeepSeek V4 Pro until Flash-0731 passes a complete current-endpoint audit gate.
- `classify`: OpenRouter DeepSeek free first.
- `clean`: Qwen first, then stable NVIDIA/Gemma candidates.
- `qa`: NVIDIA Nemotron Super first.
- `summarize`: Qwen/NVIDIA stable models first.
- `vision`: NVIDIA/OpenRouter free first for routine work; the paid multimodal branch uses verified Doubao Seed 2.0 Pro for low-cost image understanding and Gemini/Kimi for high-risk independent review.
- `transcript_correct`: local glossary cleanup first, then Qwen/NVIDIA/OpenRouter/Groq free candidates, then DeepSeek/Gemini low-cost paid fallback when allowed.
- `audit` and high-value `transcript_correct`: use DeepSeek as low-cost main fallback and GLM/Zhipu as an independent cross-check when configured and healthy.
- `ocr`: same model pool as vision, with conservative text extraction prompts.
- `audit`: Qwen/NVIDIA free first, then low-cost paid fallback for production checks.
- `verify`: Groq `openai/gpt-oss-120b` is an approved band-2 trial route for public draft verification; production and frontier verification still use an independent band-3/4 model.
- `groq-free`: configured but should remain lower priority if network handshake timeouts persist.

## Configuration

Use `.env.example` as the template. API keys must stay in `.env` and must not be printed in answers.

Provider blocks use:

```text
SMART_LLM1_NAME=provider-name
SMART_LLM1_BASE_URL=https://example.com/v1
SMART_LLM1_API_KEY_ENV=PROVIDER_API_KEY
SMART_LLM1_MODELS=model-a,model-b
SMART_LLM1_FREE=true
SMART_LLM1_BILLING_CLASS=permanent_free
SMART_LLM1_PRIORITY=1
```

Valid billing classes are `local`, `permanent_free`, `trial_quota`, and `paid`.
The portable launcher stores state under `SMART_LLM_RUNTIME_DIR` or the standard
user state directory. An optional credential catalog is loaded only when
`SMART_LLM_CREDENTIAL_CATALOG` is explicitly set.
Paid workflow budgets use the separate canonical authority at
`$HOME/.smart-llm-router/budget-authority`; changing `SMART_LLM_RUNTIME_DIR`
must never reset cumulative workflow spend.
Before the first paid reservation for an existing workflow, conservatively
import any standard-runtime v1 budget state into the canonical authority. Keep
status, limits, spend, reservations, incidents, and timestamps; ambiguous or
conflicting sources must fail closed with a migration receipt.
Treat every budget amount as valid only when it is finite; reject NaN and
positive or negative Infinity before migration, reservation, or settlement.

## Validation

After changes, run:

```bash
python -m compileall smart_llm_router
smart-llm-router credential-status
smart-llm-router refresh --timeout 6 --limit 5
smart-llm-router task "只输出 OK" --task qa --free-only
```

Do not run large benchmark sweeps unless the user explicitly asks; free providers can rate-limit.
