# Public Release Readiness

Candidate: `0.5.0rc1`

Prepared: 2026-07-18

## Completed Gates

- Isolated candidate created outside the production working tree.
- Personal absolute paths and private credential locations removed.
- Local-only global-install and failed-key canary scripts excluded.
- Old internal canary artifacts excluded from the public history.
- Working-tree and historical secret scans completed with redaction enabled.
- Portable launcher uses the project root, standard user state directory, and explicit environment variables.
- Public CI, dependency updates, security policy, contribution guide, and changelog added.
- Full unit suite passed: 67 tests.
- Python bytecode compilation and portable launcher local smoke test passed.
- Offline wheel and source distribution builds passed for `0.5.0rc1`.
- Direct and observed transitive dependency licenses reviewed.
- Fresh public root commit created without internal repository history.
- Fresh one-commit history re-scanned with no secret findings.
- Apache-2.0 selected and added as the project license.
- Public destination approved as `kmwhat/smart-llm-router`.
- SPDX license expression, license file, and GitHub project URLs added to package metadata.
- Post-license unit tests, bytecode compilation, wheel/sdist builds, and metadata inspection passed.
- Post-license public-tree and distribution-archive secret scans found no leaks.
- SHA-256 checksums generated for both `0.5.0rc1` distribution files.

## Required Before Publication

- Verify the first GitHub Actions matrix run and perform an online clean install.
- Enable GitHub private vulnerability reporting, secret scanning, push protection, and branch protection after repository creation.

Publication remains blocked until GitHub authentication, repository creation, push,
and the first remote CI run complete.
