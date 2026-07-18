# Dependency License Snapshot

Reviewed: 2026-07-18

This is a release-preparation snapshot, not legal advice. The project uses lower
bounds rather than a lock file, so every release should regenerate and review the
resolved dependency set produced by CI.

## Direct Dependencies

| Package | Reviewed Version | License |
|---|---:|---|
| `httpx` | 0.28.1 | BSD-3-Clause |
| `Pillow` | 12.2.0 | MIT-CMU |
| `python-dotenv` | 1.2.2 | BSD-3-Clause |

## Observed Transitive Dependencies

| Package | Reviewed Version | License |
|---|---:|---|
| `httpcore` | 1.0.9 | BSD-3-Clause |
| `anyio` | 4.13.0 | MIT |
| `certifi` | 2026.4.22 | MPL-2.0 |
| `idna` | 3.15 | BSD-3-Clause |
| `h11` | 0.16.0 | MIT |

Primary license references:

- <https://github.com/encode/httpx/blob/master/LICENSE.md>
- <https://github.com/python-pillow/Pillow/blob/main/LICENSE>
- <https://github.com/theskumar/python-dotenv/blob/main/LICENSE>

No obvious incompatibility was identified in this engineering review. The project
license and any formal legal review remain owner decisions.
