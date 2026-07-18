# Method Notes

## Current Result

The router is already partially multimodal. It has executable paths for text,
vision/OCR, local and explicit remote ASR, text embedding, reranking, transcript
correction, and GLM image generation. Video generation and TTS are cataloged
capabilities but do not yet have first-class execution commands/adapters.

Live low-impact probes on 2026-07-18 passed for:

- NVIDIA/Gemma free text QA.
- NVIDIA free vision and OCR.
- Qwen transcript correction.
- Qwen `text-embedding-v4` at 256 dimensions.
- Zhipu `rerank`.
- Local `whisper-cli` with `ggml-large-v3-turbo.bin` readiness.

The free code probe through `openrouter/free` returned empty content. This is
evidence that health must be tracked per task and modality, not per provider.

## Gemini Entitlement Correction

The local Gemini credential no longer has paid funding. The router therefore
treats it as `trial_quota` Free Tier and suppresses all paid Gemini providers
unless `SMART_LLM_GEMINI_PAID_ENABLED=true` is explicitly set after billing is
restored. Official Gemini documentation confirms that 2.5 Pro and Flash-Lite
have free-tier access with lower limits; free-tier content may be used to
improve Google products, so this route is restricted to public, non-sensitive
inputs.

Role selection now follows `privacy/modality -> role quality band -> health and
quota -> free within the same band -> projected total cost`. Free never beats a
higher role-quality band merely because it costs zero. Each stage selects one
main model; fallback happens only after failure. Independence is pairwise where
it matters: plan audit differs from planning, and final verification differs
from execution. Quality enhancement is conditional rather than mandatory.

## Key Design Finding

One API key should be represented as a provider-family credential. It may grant
access to many model modes, but every model mode still needs its own model id,
endpoint adapter, entitlement probe, health state, price unit, and quality
evidence. A key existing in the environment is not proof that every model is
enabled or production-ready.

## Current Gaps

1. Most paid choices have no configured price, so route plans cannot truly rank by cost.
2. Qwen trial/free quota is represented as permanently free even though official pricing describes time-limited free quota for many models.
3. Multiple NVIDIA keys duplicate the same model choices and can look like model diversity when they are only credential diversity.
4. `openrouter/free` is random and rate-limited; it is unsuitable as a quality-critical code or audit default.
5. Risk/privacy inference classifies a palm-photo audit as low risk and externally allowed unless the caller overrides it.
6. Direct DeepSeek is configured, but current paid text fallback often prefers the OpenRouter DeepSeek path first.
7. The runtime ledger/cache/cooldown directory is currently under `/private/tmp`, so reboot persistence is not guaranteed.
8. Video generation and TTS need asynchronous, modality-specific adapters and non-token cost accounting.

## Implemented In This Upgrade

- Added explicit `plan`, `execute`, `audit`, `verify`, and `quality_enhance` roles.
- Registered DeepSeek V4, Qwen 3.7, GLM-5.2, Kimi K3, Gemini Pro, and Doubao Seed 2.1/2.0 candidates under existing provider credentials.
- Added Doubao online-inference discovery while keeping Coding Plan names and endpoint ids as separate routes.
- Added `draft | production | audit | frontier`, privacy inference, and a fail-closed per-call budget gate.
- Added built-in list-price estimates with environment overrides and separated permanent-free, trial-quota, and paid reporting.
- Collapsed same-model key rotations in recommendations while preserving them for runtime failover.
- Changed the global launcher to prefer persistent runtime state and the July 18 credential catalog, with a sandbox fallback.
- Made paid-model cooldowns an actual recommendation and execution filter, and
  sized output-token limits from the per-call budget instead of using one fixed
  cap for every frontier model.

## Frontier Smoke Results

Small live calls on 2026-07-18 passed for six independent paid model families:

- Qwen `qwen3.7-max`.
- Zhipu `glm-5.2`.
- DeepSeek `deepseek-v4-pro`.
- Kimi `kimi-k3`.
- Google `gemini-2.5-pro`.
- Volcengine `doubao-seed-2-0-pro-260215`.

The public Doubao `doubao-seed-2-1-pro` alias returned 404 on the current Ark
online-inference route and was automatically cooled down for seven days. The
verified Seed 2.0 Pro versioned model remains available as the Doubao text and
image-understanding candidate. A local synthetic OCR fixture also passed with
the exact response `DOUBAO 2026|VISION OK`, so route plans now expose it as the
low-cost multimodal understanding branch with an independent Gemini/Kimi review
candidate for high-risk work. Doubao Code, Seedream, Seedance, speech, and
embedding capabilities are cataloged separately and still require their own
adapter and entitlement probes before executable promotion.

These smoke calls prove current credential and endpoint reachability, not full
production promotion. The three-probe and local-golden-set rule below still
applies to each model-mode pair.

## Chosen Method

Use a constrained optimizer:

1. Filter by privacy, modality, endpoint entitlement, health, and quality floor.
2. Reuse local deterministic work, cache, retrieval, and existing artifacts.
3. Choose the lowest expected total cost, including retry and review cost, not only nominal token price.
4. Escalate only when confidence, evidence coverage, schema validation, or model agreement falls below a task threshold.
5. Use an independent provider for high-risk cross-checks; a second key for the same model is not an independent check.

## Goal-Locked Workflow Gate

The primary cost risk is avoidable rework, not nominal token price. Version 0.4
therefore adds a local-only workflow contract and checkpoint gate:

1. Freeze the objective, non-goals, constraints, measurable criteria, and total budget.
2. Audit the plan with an independent model family before execution.
3. Execute one approved role at a time through the existing task command.
4. Check objective alignment, evidence, scope changes, criteria, and cumulative spend at milestones.
5. Spend a conditional verification call only when the local checkpoint detects drift signals.
6. Complete only when final independent verification marks every criterion as pass.

`workflow-plan` and `workflow-check` never call a model. Unattended Hermes work
fails closed unless the contract explicitly records an approved Hermes security
gate. This does not clear or bypass the current host dependency audit findings.

## Rejected

- Enabling every model merely because a provider key exists.
- Blind free-first routing for production and high-risk work.
- Running every task through two models.
- Forcing every governance stage onto a different provider family.
- Treating possession of a Gemini API key as proof of paid entitlement.
- Treating chat-completions as a universal endpoint for ASR, image, video, embedding, rerank, and TTS.
- Uploading private palm photos, chats, or course audio for routine health probes.
