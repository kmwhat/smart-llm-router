# Security Policy

## Supported Versions

Security fixes are prepared for the latest `0.5.x` release line. Older versions
may receive a fix only when the same change can be applied without weakening
current privacy, budget, or fail-closed behavior.

## Reporting A Vulnerability

Use the repository Security tab and its private vulnerability-reporting flow.
If private reporting is not available, contact the maintainer through a private
channel listed on the repository profile. Do not open a public issue containing
credentials, private prompts, user data, provider responses, or exploit details.

Include the affected version, a minimal public reproduction, expected impact,
and any proposed mitigation. Replace all real keys and private payloads with
synthetic placeholders.

## Secret Handling

- Keep provider credentials in `.env` or another explicitly selected local env file.
- Never commit credential catalogs, runtime ledgers, response caches, or user data.
- Treat any accidentally exposed credential as compromised and rotate it before disclosure.
- Run a secret scan on the complete public history before every release.

## Runtime Boundary

The router sends task content to external providers only when the selected privacy
mode allows it. Unknown paid prices fail closed under a budget. Model discovery
and endpoint health do not grant a model a production quality role automatically.
