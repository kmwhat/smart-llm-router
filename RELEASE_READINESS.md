# Public Release Readiness

## 0.9.0 Stable Release — 2026-08-11

Status: stable artifact identity frozen. Protected pull request, CI, tag,
publication, registry acceptance, and runtime projection are separately evidenced;
this repository document does not by itself assert that those external gates ran.

- Package metadata, runtime version, README, changelog, CLI, and the canonical
  GitHub wheel URL all identify `0.9.0`.
- The stable release changes release metadata only; provider routes, production role
  quality bands, privacy policy, paid authorization, and task descriptor defaults
  are unchanged from the accepted 0.9.0rc3 source.
- The portable launcher retains the verified source-binding repair while
  preserving caller working-directory and relative-path behavior.
- MiniMax remains an explicitly authorized paid text fallback without governed
  role-quality promotion. DeepSeek V4 Flash remains pending its role-matched
  audit-quality gates.
- Public source and release artifacts must contain no credential values, private
  environment files, credential catalogs, runtime ledgers, caches, or backups.
- Provider calls, tag creation, publication, accepted-registry changes, and
  Codex/Hermes runtime projection remain outside repository-content assertions.

## 0.9.0rc3 MiniMax Paid Route and Sectioned Catalog Candidate — 2026-08-11

Status: local release candidate only. Protected pull request, CI, tag,
publication, registry acceptance, and runtime projection remain separately gated.

- Package metadata, runtime version, README, changelog, and CLI report
  `0.9.0rc3` without claiming a public wheel, tag, or GitHub Release.
- MiniMax China-region `MiniMax-M3` and `MiniMax-M2.7` are paid text candidates
  that require explicit paid authorization and a finite per-call cost ceiling.
- MiniMax has no `plan`, `audit`, `verify`, or other governed role-quality band;
  health and budget evidence cannot substitute for a role-matched golden gate.
- Section-aware credential catalogs admit funded paid and free sections only.
  Unfunded paid entries are excluded from executable slots and reported only as
  sanitized aggregate counts; legacy unsectioned catalogs remain compatible.
- Public source and release artifacts must contain no credential values, private
  environment files, credential catalogs, runtime ledgers, caches, or backups.
- Further provider calls, role-table changes, publication, accepted-registry
  changes, and Codex/Hermes runtime projection remain outside this candidate gate.

## 0.9.0rc2 NVIDIA DeepSeek V4 Adapter Candidate — 2026-08-10

Status: clean local version candidate and full validation are required before
protected pull request, CI, tag, publication, registry acceptance, or runtime
projection.

- Package metadata, runtime version, README, changelog, and CLI report
  `0.9.0rc2` without claiming a public wheel, tag, or GitHub Release.
- NVIDIA-hosted DeepSeek V4 uses the provider's official
  `chat_template_kwargs` thinking controls; direct DeepSeek behavior is
  unchanged.
- Returned model metadata is bounded and validated; malformed or
  non-equivalent model substitution fails closed.
- The reviewed `deepseek-v4-flash-0731` aliases remain
  `pending_role_golden_gate`, with no `audit` or `plan_audit` quality band.
- The existing public `v0.9.0rc1` tag and prerelease remain immutable history;
  this candidate may use only a new `v0.9.0rc2` tag after all later gates pass.
- Provider calls, paid fallback, role-table changes, publication,
  accepted-registry changes, OCR consumption, and Codex/Hermes runtime
  projection remain outside this candidate gate.

## 0.9.0rc1 OpenRouter Policy and Structured Output Candidate — 2026-08-07

Status: clean canonical candidate commit and local validation are required before
protected pull request, CI, tag, publication, registry acceptance, or runtime projection.

- Package metadata, runtime version, README, changelog, and CLI report `0.9.0rc1`
  without claiming a public wheel, tag, or GitHub Release.
- OpenRouter requests can pin one or more upstream provider slugs, disable provider
  fallback, require Zero Data Retention, and deny data collection per request.
- Governed JSON Schema requests use strict upstream structured-output controls and
  retain a bounded, dependency-free local validation boundary.
- Unsupported schemas, non-finite JSON, duplicate keys, malformed structured output,
  and non-OpenRouter routes with OpenRouter-only controls fail closed before consumption.
- A policy-specific provider failure avoids generic route cooldown only when its
  sanitized structured error explicitly identifies an applied request constraint.
- Portable-launcher diagnostics expose persistent, explicit, or temporary-fallback
  runtime provenance so separate ledgers are not confused.
- Tests and evidence use synthetic inputs only; no private source material, credential,
  provider response, or domain-specific OCR content is included in this candidate.
- Provider calls, paid fallback, tag creation, publication, accepted-registry changes,
  OCR adapter consumption, and Codex/Hermes runtime projection remain outside this gate.

## 0.8.4 Guarded Budget and Strict Controls Candidate — 2026-08-05

Status: publication remains gated by a protected pull request, successful CI,
exact merged-main verification, and separate tag/release authorization.

- Package metadata, runtime version, and changelog report `0.8.4` without
  claiming that a matching public wheel already exists.
- Governed structured-output calls fail closed on malformed, fenced,
  truncated, or schema-invalid JSON and never cache rejected output.
- Strict-control preflight and request-scoped no-cache handling occur before
  route selection, budget reservation, cache mutation, or provider send.
- Paid input-token forecasts apply deterministic conservative guards;
  non-finite cost ceilings are rejected before settings or external effects.
- Workflow budgets use one stable user-level authority and preserve
  reservations and liability when settlement crosses a hard boundary.
- The public launcher uses only explicit environment variables and portable
  defaults; it does not search machine-specific credential-catalog paths.
- Public source and documentation contain no credential values, local catalog
  filenames, personal absolute paths, runtime ledgers, caches, or backups.
- The complete source suite passes 226 tests, bytecode compilation,
  diff-format validation, public-boundary checks, and Gitleaks.
- Provider calls, paid calls, production role-table changes, and automatic
  task-descriptor-v2 activation remain outside this candidate gate.

## 0.7.0 Free-Route and Local-Fallback Candidate — 2026-07-31

Status: protected PR #15 and post-merge main CI complete; this snapshot is
eligible for `v0.7.0` tagging and publication after independent artifact
acceptance.

- Package metadata, runtime version, changelog, and public installation link
  report `0.7.0`.
- Protected push and pull-request CI passed before squash merge, and the
  post-merge `main` workflow passed Python 3.10–3.14 plus `package-smoke`.
- The candidate contains safe NVIDIA discovery, explicit free-route credential
  and health semantics, guarded trial-quota admission, remote-free-first local
  fallback, Ollama compatibility, optional whisper.cpp no-GPU execution, and
  cache-policy revalidation.
- Cache hits are rechecked against the current route inventory, free/privacy
  rules, explicit provider/model constraints, role quality floor, and budget;
  old cache entries remain in a versioned legacy namespace.
- Production role defaults remain unchanged and task descriptor v2 remains
  default off.
- Public quickstart commands remain limited to router configuration,
  recommendation, route planning, free QA execution, health, and ledger
  inspection.
- Local catalogs, private environment files, runtime ledgers, caches, account
  details, and machine-specific configuration are excluded from public source
  and distribution artifacts.
- The source tree and extracted source distribution each passed 139 tests and
  bytecode compilation; the working tree passed diff-format validation.
- A clean Python 3.14 environment installed the wheel with dependencies and
  passed `pip check`, package/runtime version checks, license metadata, CLI
  help, local scoring, and no-credential provider inspection.
- Source, Git history, wheel, and source distribution passed Gitleaks. Archive
  scans found no private absolute paths, credential-catalog filenames, private
  configuration paths, runtime-state files, or router backup material.
- A fresh remote `free-only` QA call and an explicit local `local_only` Ollama
  QA call both returned the required output with a zero-dollar hard budget;
  the exact ledger window contained zero paid model calls.
- A timed-out first-choice free endpoint entered cooldown and the production
  recommendation correctly advanced to the recently successful remote free
  route while retaining local models as final fallback.

## 0.6.0 Credential Catalog Hardening Candidate — 2026-07-30

Status: local candidate complete; protected CI and publication authorization remain pending.

- Package metadata, runtime version, changelog, and public installation link report `0.6.0`.
- The public diff is limited to credential-catalog hardening, dotted Qwen key
  compatibility, synthetic tests, and matching release metadata.
- Provider-specific shapes reject nearby labels and account identifiers, while
  repeated credentials are deduplicated before rotation slots are created.
- Tests use synthetic credentials only; local catalogs, private environments,
  runtime ledgers, and account-specific paths are excluded from the source and
  distribution artifacts.
- The clean `origin/main` candidate passed the complete local suite, bytecode
  compilation, public-boundary tests, working-tree Gitleaks, wheel installation,
  `pip check`, CLI help, and installed dotted-Qwen parser smoke tests.
- Extracted wheel and source distribution scans found no personal paths,
  credential-catalog filenames, plaintext secret patterns, or Gitleaks findings.
- Release automation must rebuild and attest artifacts from the protected tag.
- Commit, push, tag, release creation, and retirement of the previous
  prerelease require separate explicit authorization.

## 0.6.0rc3 Task Descriptor v2 Candidate — 2026-07-24

Status: release baseline locked to protected `main` commit `48484a8e78568a740bd18fd2962d065800ab9567`; publication state is represented by the external Git tag and GitHub Release, not inferred from this source snapshot.

- Package metadata, runtime, changelog, and public installation link all report `0.6.0rc3`.
- Task descriptor v2 remains default off, affects only non-role complexity when explicitly enabled, and has a one-step rollback.
- Response-cache keys separate legacy and v2 decisions by effective complexity label, classifier source, and classifier version.
- Explicit process-environment values take precedence over `.env`, keeping activation and rollback deterministic.
- Strict JSON requests reject fenced or otherwise non-parseable responses, try the next eligible route, and fail closed without globally cooling a healthy endpoint.
- The complete local suite passed with 106 tests, bytecode compilation, public-boundary checks, and Gitleaks.
- The first source archive exposed a missing-fixture gate: it included `test_task_descriptor_v2.py` but not its JSON fixtures. `MANIFEST.in` now includes public test JSON, and the rebuilt sdist passed all 105 tests after extraction.
- Extracted wheel and sdist scans found no personal absolute paths, private domain terms, runtime files, private-key markers, token patterns, or Gitleaks findings.
- A clean Python 3.14 environment installed the wheel with dependencies, passed `pip check`, matched runtime/distribution versions, and exercised help, default-off scoring, explicit v2 scoring, and route planning.
- The global launcher passed help, score, and read-only recommendation cold starts with `/dev/null` configuration and an isolated runtime.
- Final local artifact hashes are recorded outside the package in the SkillCenter acceptance receipt so the source archive does not contain a self-referential checksum.
- Completed gates: intentional scope review, protected Python 3.10-3.14 and package-smoke CI, independent review, and merge-tree verification.
- Release automation must still verify that the tag matches the package version, rebuild and test artifacts, generate checksums and attestations, and publish a prerelease.

## 0.6.0rc2 Public-Surface Correction — 2026-07-20

Status: local correction candidate passed; ready for protected CI, not committed, tagged, or published.

- The public quickstart is limited to router configuration, recommendation, route planning, execution, health, and ledger inspection.
- Workload-specific prompts, direct paid-provider examples, and peripheral adapter commands were removed from README, packaged Codex/Hermes skills, and provider validation examples.
- Runtime/account-specific wording was replaced with portable policy language.
- Public boundary tests prevent the removed workload examples and peripheral commands from returning to shipped documentation.
- Full local suite passed: 86 tests, bytecode compilation, Gitleaks, working-tree boundary scan, wheel/sdist build, and extracted-sdist boundary scan.
- Local candidate SHA-256: wheel `6f1884604771742b560bc6213c57b003027605483f0888be7de384f9258fe757`; source distribution `65cb1f39380ed5d91f3af293d8e3ed3080f1eaf30e5374640f5e74dea5cc8a6b`.
- `v0.6.0rc1` remains immutable historical evidence; this correction will use a new `v0.6.0rc2` tag only after protected CI passes.

## 0.6.0rc1 Local Candidate — 2026-07-20

Status: ready to commit for protected CI; not committed, pushed, tagged, or published.

- Package metadata and runtime both report `0.6.0rc1`.
- A clean Python 3.14 environment installed the wheel, passed `pip check`, and exercised `--help`, `score`, `contract-plan`, and `adapter-lifecycle`.
- The source distribution now explicitly includes public task-contract, adapter-lifecycle, and QA golden-set examples through `MANIFEST.in`; CI and release workflows assert the required examples are present.
- Extracted wheel and source-distribution scans found no personal absolute paths, private domain terms, private-key markers, or token patterns; Gitleaks also reported no leaks.
- Local candidate SHA-256: wheel `7fbfeba7a51a4aa2e9149e2f70eba83cc93b00e9a276b2369d1fb7bbebc4444f`; source distribution `2b8180312410808dccadaafb710f1195ec3c3be4fc4838c55657bdad16183e22`.
- These local hashes are audit evidence only. Release automation must rebuild and attest its own artifacts.
- Remaining publication gates: review and commit the intended scope, push through protected Python 3.10-3.14 and `package-smoke` CI, then explicitly approve the release tag.

Candidate: `0.5.0rc2`

Prepared: 2026-07-18

## Completed Gates

- Isolated candidate created outside the production working tree.
- Personal absolute paths and private credential locations removed.
- Local-only global-install and failed-key canary scripts excluded.
- Old internal canary artifacts excluded from the public history.
- Working-tree and historical secret scans completed with redaction enabled.
- Portable launcher uses the project root, standard user state directory, and explicit environment variables.
- Public CI, dependency updates, security policy, contribution guide, and changelog added.
- Full unit suite passed: 71 tests.
- Python bytecode compilation and portable launcher local smoke test passed.
- Wheel and source distribution builds passed for `0.5.0rc2`.
- Direct and observed transitive dependency licenses reviewed.
- Fresh public root commit created without internal repository history.
- Fresh one-commit history re-scanned with no secret findings.
- Apache-2.0 selected and added as the project license.
- Public destination approved as `kmwhat/smart-llm-router`.
- SPDX license expression, license file, and GitHub project URLs added to package metadata.
- Post-license unit tests, bytecode compilation, wheel/sdist builds, and metadata inspection passed.
- Post-license public-tree and distribution-archive secret scans found no leaks.
- Public-package boundary tests confirm that shipped files contain no private domain defaults.
- GitHub Actions now installs and exercises the built wheel in a clean environment.
- Main branch protection requires Python 3.10-3.14 tests and the `package-smoke` job.
- Tag-triggered release automation rebuilds, tests, smoke-installs, checksums, attests, and publishes distribution artifacts.

## Publication Result

- The domain-neutral public-core change passed all six required CI jobs and was merged through pull request #7.
- The reproducible release workflow passed all six required CI jobs and was merged through pull request #8.
- `v0.5.0rc2` was published as a prerelease from the protected `main` branch.
- Release workflow run #1 rebuilt the package, reran 71 tests, smoke-installed the wheel, generated checksums, and published three artifacts.
- Downloaded wheel and source-distribution assets passed `SHA256SUMS` verification and a second private-domain boundary scan.
- GitHub artifact attestation #35972124 records SLSA provenance for all three release artifacts.
- The `v0.5.0rc1` release now points new installations to `v0.5.0rc2`.

All publication gates for `v0.5.0rc2` are complete.
