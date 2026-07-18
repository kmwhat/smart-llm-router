# Validation Plan

## P0 Acceptance Gates

1. Existing tests remain green.
2. A successful call contributes success and latency evidence.
3. A provider quota error contributes a route failure and failure class.
4. A clear DNS or local-network infrastructure error is recorded but excluded
   from the model-health denominator.
5. Fewer than three health samples cannot mark a route degraded.
6. A degraded free route loses to a healthy paid route only when both are in the
   same role-quality band.
7. A higher role-quality band still beats a lower band regardless of history.
8. `route-stats` reads the ledger without calling any provider or exposing keys.
9. Live status and a small free-only call still work after the change.

## Promotion Gates for P1 and Later

- Keep a frozen baseline and an untouched test split.
- Record task, candidate, prompt version, evaluator version, cost, latency, and
  outcome without storing prohibited private payloads.
- Require three live health probes before using a newly discovered model for
  ordinary free tasks.
- Require a task-specific golden-set pass before adding a model to a role-quality
  band.
- Require independent review for planning, audit, verification, and subjective
  quality-enhancement promotion.

## Stop and Rollback Conditions

- Any privacy-gate regression.
- Any routing across modalities unsupported by the selected endpoint.
- A lower quality band displacing a higher one due only to historical health.
- Infrastructure-wide errors poisoning model-specific health.
- Significant latency added to local recommendation generation.
- A learned policy that cannot explain, reproduce, or reverse its selection.

## Validation Results

Completed on 2026-07-18:

- Project runtime test suite: 52/52 passed.
- `compileall` and `git diff --check`: passed.
- Real ledger: 41 model events were classified; 23 historical sandbox DNS
  failures were reported as infrastructure and excluded from route health.
- Real audit report: Gemini Free Tier had one successful health sample and was
  correctly left below the three-sample degradation threshold.
- Free-pool refresh: three of five sampled routes returned `OK`; one timeout and
  one retired/not-found endpoint entered the existing cooldown path.
- Live free-only QA: `nvidia-google-free/google/gemma-3n-e4b-it` returned `OK`
  and wrote ledger id `c556079c44c8b51f`.
- Codex and Hermes global skill paths were verified as soft links to the updated
  project skills.

The system Python 3.14 lacks project dependencies and produced import failures;
all authoritative tests used the project's `.venv` runtime, matching the global
launcher.

P1 validation completed on 2026-07-18:

- Full project runtime test suite: 60/60 passed.
- Public `audit-public-v1` live run completed against a free candidate and paid
  baseline without exposing private data or credentials.
- Candidate `groq-free/qwen/qwen3.6-27b` was held after 4/5 successful calls,
  0/5 deterministic case passes, and one 429 quota failure.
- DeepSeek V4 Pro baseline passed 4/5 cases for an estimated USD 0.0021028.
- Independent review was correctly skipped after candidate hard-gate failure.
- Future runs now stop before paid baseline and reviewer calls when earlier
  candidate gates already make promotion impossible.
- Groq default billing was corrected from `permanent_free` to `trial_quota`.

P1 role-suite expansion completed on 2026-07-18:

- Full project runtime test suite: 63/63 passed.
- Added five-case public suites for `plan`, `execute`, and `verify`, plus a
  deterministic `json_field_equals` assertion and first-call failure stop.
- OpenRouter Nemotron Ultra planning candidate: HOLD after one successful call
  followed by an empty response; paid Qwen baseline was skipped.
- OpenRouter Qwen3 Coder execution candidate: HOLD after the first call returned
  429; paid GLM baseline was skipped.
- Groq GPT-OSS 120B verification candidate: 5/5 deterministic passes, ten total
  successful health samples, zero route failures, and zero estimated candidate
  cost under current trial quota.
- DeepSeek V4 Pro verification baseline: 5/5 passes at estimated USD 0.00138374.
- Gemini 2.5 Pro Free Tier blind review: candidate 3 wins, 1 tie, 1 loss; 100%
  candidate quality pass rate and 80% win-or-tie rate.
- Promotion decision: PASS for explicit `verify` band 2 registration only;
  planning and execution candidates remain unregistered.
