# Public Release Readiness

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
