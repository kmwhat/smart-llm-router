# Changelog

All notable changes to this project are documented in this file.

## Unreleased

## 0.9.3 - 2026-08-27

- Made automatic paid vision execution and route planning prefer a route with
  fresh successful health evidence over declared but unproven alternatives.
- Preserved quality ordering when routes have the same health status, so a
  healthy higher-band route still outranks a healthy lower-band route.
- Exposed current health evidence in multimodal route receipts without changing
  audit-band registration, privacy controls, or paid budget requirements.

## 0.9.2 - 2026-08-27

- Added the official exact-ID `deepseek-v4-flash-vision-exp` paid multimodal
  route with OpenAI-compatible inline-image transport and DeepSeek native
  thinking controls.
- Applied conservative peak cache-miss/input and output prices to pre-send
  budget checks, including provider-reported image input tokens.
- Registered Vision Exp only as a production-quality band-3 fallback; its
  experimental status does not grant audit or plan-audit band 4.

## 0.9.1 - 2026-08-27

- Fixed golden-evaluation cost accounting so a failed provider or baseline call
  that reached a terminal settled state remains attributed to the final report,
  including budget-warning outcomes, without double counting.
- Stopped remaining candidate cases after a terminal call failure and retained
  the existing hard-gate behavior that avoids unnecessary paid baseline or
  blind-review work.
- Upgraded the maintained GitHub Actions runtime and pinned every third-party
  Action reference to a full commit SHA with a regression test, without
  changing provider routes, role-quality bands, privacy policy, paid
  authorization, or task descriptor defaults.

## 0.9.0 - 2026-08-11

- Promoted the independently verified 0.9.0 release-candidate series to the
  stable release without changing provider routes, role-quality
  bands, privacy policy, or paid-authorization behavior.
- Preserved caller working-directory semantics while binding the portable
  launcher to its staged source, preventing a same-named package in the caller
  directory from shadowing the intended runtime.
- Consolidated the OpenRouter policy controls, NVIDIA-hosted DeepSeek V4
  compatibility, and budget-guarded MiniMax catalog support described in the
  0.9.0rc1 through 0.9.0rc3 entries below.

## 0.9.0rc3 - 2026-08-11

- Added a China-region paid MiniMax text route for `MiniMax-M3` with
  `MiniMax-M2.7` fallback, current OpenAI-compatible request fields, reasoning
  separation, conservative CNY pricing and tokenizer overhead, and no
  role-quality promotion.
- Added section-aware credential catalog loading for funded paid, free, and
  unfunded paid groups. Unfunded credentials are reported only as sanitized
  counts and are excluded from executable slots.

## 0.9.0rc2 - 2026-08-10

- Adapted NVIDIA-hosted DeepSeek V4 requests to the official
  `chat_template_kwargs` thinking controls while preserving direct DeepSeek
  request behavior.
- Validated and recorded bounded served-model metadata, rejecting malformed or
  non-equivalent model substitution before consuming the response.
- Recognized the reviewed `deepseek-v4-flash-0731` deployment aliases without
  granting an `audit` or `plan_audit` quality band; the route remains pending
  its role-matched quality gates.

## 0.9.0rc1 - 2026-08-07

- Added request-scoped OpenRouter upstream provider allowlists, provider-fallback denial,
  Zero Data Retention enforcement, and data-collection denial. These controls fail closed
  before send when the selected route is not OpenRouter and participate in cache identity.
- Forward schema-driven governed outputs as OpenRouter `response_format=json_schema` with
  strict mode and `require_parameters=true`, while retaining local recursive schema validation.
- Exposed portable-launcher runtime provenance and temporary fallback reason in `doctor`
  so a sandbox-local status view cannot be mistaken for the persistent health ledger.
- Made the bounded JSON Schema validator fail closed on unsupported schemas,
  non-finite JSON, duplicate keys, numeric bounds, and nested required rules.
- Request-policy-specific OpenRouter failures no longer poison generic route
  cooldown only when the sanitized structured error explicitly matches an applied
  request constraint; status codes alone cannot hide ordinary health failures.
- Bounded schema validation now also enforces JSON numeric equality, the declared
  2020-12 dialect, and schema depth/node ceilings.

## 0.8.4 - 2026-08-04

- Governed audit/verify, JSON-only, and schema-driven calls require one complete raw JSON object and fail closed on truncation, fences, parse errors, or missing required fields.
- Invalid structured output records sanitized completion metadata, never caches or falls back, and settles observed provider usage exactly once.
- Reject non-finite single-call and workflow budget ceilings before settings, cache, reservation, state mutation, or provider send; internal budget evaluation also fails closed.
- Added finite, deterministic provider/model input-token forecast guards for paid calls; DeepSeek V4 defaults to at least 1.15 without an authoritative tokenizer.
- Added sanitized forecast evidence and clarified that local max-cost checks are forecasts while provider usage remains settlement authority.
- Added the 21476-to-23139 DeepSeek incident regression and pre-send no-provider/no-reservation/no-cache assertions.

## 0.8.3 - 2026-08-03

### Added

- Added governed `--strict-controls` preflight with a typed static control
  registry and bounded indexed patterns. Unsupported near-miss names fail
  closed before route selection, budget reservation, or provider send.
- Added `--no-cache` to disable both response-cache reads and writes for one
  request while preserving any existing cache bytes.
- Added sanitized ledger evidence for requested/effective cache state, control
  source, cache-hit state, and response-cache persistence.

### Compatibility

- Ordinary non-strict callers retain the 0.8.2 cache behavior.
- Model roles, quality bands, provider priorities, and budget safeguards are unchanged.

## 0.8.2 - 2026-08-02

### Added

- Added DeepSeek V4 `thinking.type=enabled/disabled` request controls.
- Added final-answer reservation semantics for DeepSeek: auto mode selects
  non-thinking output when a final reserve is required, while an incompatible
  explicit enabled mode fails closed before sending.
- Bumped the response cache policy to v3 so DeepSeek thinking modes and final
  answer reservations cannot reuse responses across policy boundaries.

### Fixed

- Prevented DeepSeek V4 Pro plan-audit output caps from being represented as a
  guaranteed final-answer reserve while default thinking can consume the full
  completion envelope.
- Fixed the package-level launcher so an external/global virtual environment
  imports the staged module from `tool/` instead of silently using its installed copy.
- Moved workflow budget state to a stable per-user authority independent from
  `SMART_LLM_RUNTIME_DIR`, with authority identity in doctor, state, and ledgers.
- Added a conservative lazy v1-to-v2 budget migration gate. It preserves legacy
  state, spend, reservations, incidents, and timestamps; ambiguous or conflicting
  sources fail closed and emit a private migration receipt before any paid send.
- Rejected non-finite budget values at legacy import, new reservation, authority
  reuse, and settlement boundaries so JSON NaN or Infinity cannot bypass limits.
- Reordered settlement overflow handling so the result is checked before the
  reservation is removed; overflow stops the workflow and preserves the reservation as liability.

## 0.8.1 - 2026-08-02

### Added

- Added Qwen hybrid-thinking controls through `--thinking-mode`,
  `--thinking-budget-tokens`, `--final-answer-reserve-tokens`, `--no-think`,
  and the `/no_think` prompt marker.
- Added separate reasoning and final-answer reservations for Qwen research
  enhancement so reasoning cannot silently consume the entire completion cap.

### Fixed

- Reclassified settlement cost above the reservation estimate but inside both
  explicit authorization limits as a durable `budget_warning`, not a hard-stop
  incident.
- Kept billable rejected outputs in workflow spend while stopping only for a
  per-call hard-limit breach, cumulative workflow breach, or unknown price.

## 0.8.0 - 2026-08-02

### Added

- Added difficulty-tiered `workflow_contract.v2` planning for simple, standard,
  and complex tasks.
- Added workspace-native Codex subscription controller declarations, Qwen
  research enhancement, DeepSeek plan challenge audit, bounded repair loops,
  delta verification, and deterministic closeout stages.
- Added source provenance gates requiring URLs and access dates for research
  enhancement.
- Added soft, elastic, and anomaly-hard workflow budget levels; soft-target
  overruns warn without stopping execution.
- Added paid failure accounting: inconclusive reasoning responses settle
  provider usage, or the reserved worst-case cost when usage is absent.

### Changed

- Dedicated research and plan-audit roles prioritize the user-approved model
  families after capability and health gates.
- DeepSeek V4 Flash remains ineligible for production roles until a matching
  endpoint golden gate explicitly promotes it.
- Preserved workflow contract v1 behavior for existing callers.

### Tests

- Expanded the deterministic suite from 163 to 174 tests, including elastic-limit authorization, unattended pause, and anomaly hard-stop evidence.

## 0.7.2 - 2026-08-02

### Added

- Added atomic cross-call workflow budget reservations through `--workflow-id`,
  `--workflow-max-cost-usd`, and `--workflow-stage`.
- Added durable budget incident artifacts and ledger events for prevented
  reservations, provider usage overruns, and stopped workflows.

### Fixed

- Reserved the complete caller-requested output envelope before sending paid
  requests. Qwen 3.7 now uses `max_completion_tokens` so the cap includes both
  reasoning and answer tokens, plus the documented ten-token variance reserve.
- Rejected provider responses whose reported or estimated charge exceeds the
  per-call reservation, per-call hard limit, or cumulative workflow limit.
- Required programmatic callers that enable paid fallback to supply the same
  explicit per-call hard limit already required by the CLI.

## 0.7.1 - 2026-08-02

### Added

- Added an offline `doctor` report that explains credential drift, route
  inventory, role coverage, trial-quota guards, and per-model exclusion reasons
  without making network calls.
- Added resumable refresh reports and JSONL-style progress events on stderr.
- Added an explicit audit-only switch for probing unprotected trial-quota
  routes without admitting them to normal execution.

### Changed

- Preserved credential rotations during real role execution while continuing to
  collapse them in recommendations and plans.
- Allowed golden-set evaluation to call an exact unqualified candidate route;
  normal role calls retain the production quality floor.
- Retried inconclusive reasoning-model health probes with a larger output budget
  and distinguished endpoint reachability from a missing final answer.
- Changed role ordering so complexity and risk determine the quality floor and
  qualified routes compete on retry-adjusted expected total cost; free is no
  longer an independent preference ahead of cost and reliability.
- Registered DeepSeek-V4-Flash-0731 as an explicit pending candidate after its
  NVIDIA planning gate passed two cases and then failed with 529; no production
  quality band was granted.
- Added a bounded per-suite request timeout for slower reasoning candidates.

### Fixed

- Closed a paid-routing authorization gap where `task` treated the absence of
  `--free-only` as permission to try paid fallbacks. Executing tasks now
  require explicit `--paid` plus `--max-cost-usd`, and the programmatic API
  defaults `paid_fallback` to false.
- Applied the same fail-closed billing policy to remote ASR, transcript
  correction, embedding, rerank, quick benchmarks, and modality refreshes.
  Unprotected trial routes require an explicit audit-only switch.
- Made configuration tests independent of the installed private `.env`, and
  added execution-path regressions for paid and trial-quota gates.
- A missing catalog path inherited from `.env` is now a visible configuration
  warning instead of a global startup failure. An explicitly supplied missing
  path still fails closed.
- OpenAI-compatible content arrays are parsed without exposing reasoning fields,
  and Kimi-compatible calls retain their required temperature behavior.

## 0.7.0 - 2026-07-31

### Added

- Added safe NVIDIA free-endpoint discovery that separates general text and
  code candidates from specialized vision, embedding, rerank, safety, reward,
  detection, and parsing models while preserving same-provider key rotation.
- Added credential-status probes that distinguish catalog visibility,
  authentication evidence, request validation, and real model callability
  without printing credentials.
- Added tri-state route health and explicit execution eligibility so unknown,
  cooled-down, and recently successful routes are not conflated.
- Added local Ollama compatibility for public fallback models and an optional
  whisper.cpp no-GPU flag for hosts where the GPU path is unstable.

### Changed

- Kept ordinary non-sensitive work remote-free-first while preserving local
  models for `local_only` privacy and final zero-cost fallback.
- Required `trial_quota` routes to have an explicit hard-stop guard before they
  may enter free-only execution.
- Revalidated cached responses against the current provider/model inventory,
  free-only eligibility, privacy, explicit route constraints, role quality
  floor, and cost budget before returning them.
- Moved previous cache entries into a versioned legacy namespace instead of
  clearing unrelated runtime state.

### Fixed

- Prevented historical cached responses from retired or reclassified routes
  from satisfying current `free-only` or `local_only` requests.
- Prevented public model catalogs and request-validation responses from being
  reported as successful credential or endpoint checks.
- Improved Ollama request/response compatibility and local ASR command
  construction without changing production role defaults.

### Tests

- Added regression coverage for cache policy, credential semantics, NVIDIA
  discovery filtering, health admission, Ollama compatibility, and local ASR.

## 0.6.0 - 2026-07-30

### Security

- Restricted Qwen, OpenRouter, NVIDIA, and Groq credential-catalog entries to
  provider-specific key shapes so nearby labels and account identifiers cannot
  become rotation routes.
- Deduplicated repeated credentials within a provider section.

### Fixed

- Accepted dotted Qwen key formats while retaining the `sk-` prefix and
  provider-section boundary.

## 0.6.0rc3 - 2026-07-24

### Changed

- Added a default-off task descriptor v2 that can affect only non-role task complexity; production roles retain their existing quality floors.
- Added explicit activation receipts and one-step rollback through `SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED=false` or by unsetting the variable.
- Isolated response-cache keys by effective complexity label, classifier source, and classifier version.
- Preserved explicit process-environment overrides over `.env`, so controlled activation and rollback remain reliable.
- Required directly parseable JSON when a task explicitly requests strict JSON; rejected model or cached output now falls through without globally cooling a healthy endpoint.

## 0.6.0rc2 - 2026-07-20

### Changed

- Reduced the public quickstart to core router operations: configuration, recommendation, route planning, execution, health, and ledger inspection.
- Removed workload-specific prompts, direct paid-provider examples, and peripheral adapter commands from public common-command and validation sections.
- Replaced local runtime/account wording with portable public policy language.

## 0.6.0rc1 - 2026-07-20

### Changed

- Hardened task contracts with a strict task-family allowlist and explicit sanitization plus approval gates before `internal_summary` may use cloud routes.
- Linked route receipts to stable contract fingerprints, route aliases, fallback chains, ledger ids, and validated output hashes.
- Added a fail-closed materialization gate for required, non-empty JSON artifacts and required fields.
- Stopped inferring `production_changed` from execution mode; callers must provide evidence-backed state explicitly.
- Added a six-state adapter lifecycle with fail-closed promotion gates, evidence fingerprints, and non-mutating transition receipts.
- Required canary and health evidence for candidate entry, passed golden-set promotion evidence for qualification, and owner/smoke/rollback evidence for production.
- Kept downgrade and retirement transitions available without upward-promotion evidence so incident rollback cannot be blocked by governance checks.
- Added optional private lifecycle-state persistence with atomic writes, restrictive permissions, immutable receipts, and PASS-only adapter state updates.
- Added a deterministic public QA golden suite for screening general low-cost QA candidates without weakening production-role review gates.
- Tightened the general QA golden gate to require all deterministic cases after a candidate missed the rule-based next-action case.
- Enforced private lifecycle declarations during route selection: declared adapters must be qualified or production, while undeclared legacy routes remain compatible.
- Made persisted PASS receipts report `state_change_persisted` and include their runtime paths in the stored receipt, removing the stale owner-action message after state application.
- Included public contracts, golden suites, skills, setup documentation, and CI metadata in source distributions, with CI/release assertions for required examples.

## 0.5.0rc2 - 2026-07-18

### Changed

- Replaced domain-specific README, Codex skill, Hermes skill, probe, and benchmark examples with neutral software, document, OCR, and training-transcript scenarios.
- Generalized transcript correction to use `general` by default and accept the caller's domain label without injecting a built-in glossary.
- Removed private legacy configuration namespaces from the public core.

### Fixed

- Removed a hard-coded transcript term replacement that could silently alter unrelated source material before model review.
- Aligned the package `__version__` value with distribution metadata.

### Tests

- Added public-package boundary checks that fail CI when private domain defaults re-enter shipped files.
- Expanded the unit suite from 67 to 71 tests.

## 0.5.0rc1 - 2026-07-18

### Added

- Goal-locked workflow contracts, planning audits, process checkpoints, and final verification gates.
- Role-aware quality floors for planning, execution, audit, verification, and conditional quality enhancement.
- Ledger-derived route health, retry-adjusted expected cost, and P95 latency ordering.
- Golden-set evaluation and explicit model-promotion checks.
- Dynamic OpenRouter, NVIDIA, Groq, Ark, and multimodal capability discovery.
- Dedicated embedding, rerank, ASR, image-generation, and multimodal route planning surfaces.
- Portable launcher, public CI, dependency updates, security policy, and contribution guidance.
- Apache-2.0 licensing and public project metadata.

### Changed

- Qualified healthy free routes now outrank unnecessary paid routes at the same required quality level.
- Role routing fails closed when no registered model reaches the requested quality target.
- Provider credentials, runtime state, and optional credential catalogs are selected only through local configuration.

### Security

- Public artifacts exclude API keys, private paths, user data, runtime ledgers, and response caches.
- Paid routes with unknown prices fail closed when a task budget is active.
