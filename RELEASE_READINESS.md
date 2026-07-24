# Public Release Readiness

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
