# Changelog

All notable changes to this project are documented in this file.

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
