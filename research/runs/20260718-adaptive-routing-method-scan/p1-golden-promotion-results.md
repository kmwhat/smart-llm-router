# P1 Golden-Set Promotion Results

Validation date: 2026-07-18

## Implemented Surface

- `golden-eval`: validates a secret-free suite, disables response cache, runs a
  candidate, conditionally runs a baseline, and creates local evidence.
- `promotion-check`: combines deterministic quality, relative baseline,
  candidate cost, task-specific route health, and independent blind review.
- Supported deterministic assertions: JSON validity and required keys,
  contains-all/any, prohibited terms, regex, and character bounds.
- Subjective production-role promotion requires a blind reviewer whose model
  family differs from both candidate and baseline, or an independent human.
- A passing decision grants eligibility for explicit role-band registration;
  it never edits `ROLE_QUALITY_BANDS` automatically.

## First Live Candidate

- Suite: `audit-public-v1`, five public synthetic audit cases.
- Proposed role/band: `audit`, band 2.
- Candidate: `groq-free/qwen/qwen3.6-27b`, current billing class
  `trial_quota`.
- Baseline: `deepseek-direct-paid/deepseek-v4-pro`.
- Candidate calls: 4/5 successful; one 429 quota failure.
- Candidate deterministic result: 0/5 cases passed.
- Baseline calls: 5/5 successful; 4/5 cases passed.
- Baseline estimated total cost: USD 0.0021028.
- Candidate task health after the run: five samples, 80% call success, P95
  successful latency 5.244 seconds.

The four candidate outputs exposed long `<think>` traces of roughly 6,000 or
more characters before the requested answer. They therefore failed JSON-only
and maximum-length requirements even when relevant risks appeared later in the
output. This is a real production-format and controllability defect, not an
assertion-parser error.

## Decision

Status: `HOLD`.

Reasons:

- `candidate_call_failures`
- `candidate_case_pass_rate_below_threshold`
- `candidate_regresses_against_baseline`

Independent blind review was intentionally skipped after hard-gate failure, so
no third-model cost was spent. The candidate remains available for low-risk
general work but is not eligible for the `audit` role band.

Runtime evidence:

- `runtime/golden-evaluations/audit-public-v1-a34e9d9e/report.json`
- `runtime/golden-evaluations/audit-public-v1-a34e9d9e/promotion-decision.json`

## Cost-Control Improvement Triggered by the Run

The evaluator now uses staged stopping for future runs:

1. Run candidate deterministic and cost gates.
2. Run the paid baseline only if candidate hard gates pass.
3. Run an independent blind reviewer only if baseline non-regression passes.

This prevents a weak free candidate from triggering avoidable paid baseline and
review calls.
