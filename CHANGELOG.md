# Changelog

All notable changes to this project are documented in this file.

## Unreleased

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
