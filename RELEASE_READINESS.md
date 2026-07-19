# Public Release Readiness

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
