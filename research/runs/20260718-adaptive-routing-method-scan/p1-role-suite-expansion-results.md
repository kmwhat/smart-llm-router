# P1 Role-Suite Expansion Results

Validation date: 2026-07-18

## Scope

- Added public five-case golden suites for `plan`, `execute`, and `verify`.
- Added exact JSON-field assertions so verification decisions can be checked
  independently of prose wording.
- Stopped remaining cases after the first route-call failure and skipped paid
  baselines whenever the candidate hard gate failed.
- Kept all suite inputs synthetic, public, and free of credentials.

## Live Decisions

| Role | Candidate | Candidate result | Paid baseline | Decision |
|---|---|---|---|---|
| plan | OpenRouter Nemotron 3 Ultra 550B free | 1 success, then empty response | skipped | HOLD |
| execute | OpenRouter Qwen3 Coder free | first call 429 | skipped | HOLD |
| verify | Groq GPT-OSS 120B trial | 5/5 cases, 10/10 health calls | DeepSeek V4 Pro 5/5 | PASS |

The verification baseline cost was estimated at USD 0.00138374. A Gemini 2.5
Pro Free Tier blind reviewer, from a family different from candidate and
baseline, scored the candidate at three wins, one tie, one loss, with every
candidate response marked quality-pass. The candidate therefore reached the
configured 80% win-or-tie and 80% quality-pass gates.

## Registration Boundary

`groq-free/openai/gpt-oss-120b` is explicitly registered only for `verify`
quality band 2. It is quota-backed trial capacity, not permanent free capacity.
It may handle public, low-risk draft verification and wins only within its
quality band. Band 3/4 routes remain ahead for production, audit, frontier, or
sensitive verification.

Nemotron Ultra and Qwen3 Coder remain ordinary discovered candidates. Their
failed evaluations did not call the paid Qwen or GLM baselines, and no
independent reviewer was needed.

## Runtime Evidence

- `runtime/golden-evaluations/plan-public-v1-8c1fb94b/promotion-decision.json`
- `runtime/golden-evaluations/execute-public-v1-4d8d8c99/promotion-decision.json`
- `runtime/golden-evaluations/verify-public-v1-a392ecca/report.json`
- `runtime/golden-evaluations/verify-public-v1-a392ecca/blind-review-gemini.json`
- `runtime/golden-evaluations/verify-public-v1-a392ecca/promotion-decision.json`
