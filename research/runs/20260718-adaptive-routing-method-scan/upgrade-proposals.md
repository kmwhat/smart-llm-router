# Upgrade Proposals

## P0: Evidence-Aware Route Health

Status: selected for implementation.

- Add a failure taxonomy that separates infrastructure, quota, authentication,
  timeout, unavailable-model, empty-output, and provider errors.
- Aggregate success rate, smoothed success probability, successful latency, and
  observed estimated cost by task/provider/model.
- Add `route-stats` for inspection.
- Let empirical degradation affect only choices in the same role-quality band.
- Preserve free-first behavior for healthy or not-yet-observed routes.

Expected benefit: fewer repeated calls to broken or rate-limited routes, without
letting local DNS failures incorrectly demote models.

## P1: Golden-Set Promotion Gate

Status: implemented and live-validated. The first discovered free candidate was
held by the gate; see `p1-golden-promotion-results.md`.

- Build small private, task-specific datasets for plan, execute, audit, verify,
  quality enhancement, vision, OCR, and transcript correction.
- Require deterministic checks where possible and blinded pairwise review for
  subjective outputs.
- Compare every candidate against the current simple baseline.
- Promote a discovered model into a role band only after minimum samples and a
  non-regression gate for quality, cost, and privacy.
- Keep imported Promptfoo projects isolated and security-reviewed, or reproduce
  the needed assertion subset locally.

## P2: Controlled Post-Output Escalation

Status: deferred until P1 has labels.

- Add task-specific confidence and defect signals.
- Escalate only failed or low-confidence outputs to a stronger independent model.
- Record avoided spend and quality-recovery evidence.

## P3: Learned Policy Experiment

Status: research only.

- Evaluate a ParetoBandit-style policy offline after enough golden-set and live
  feedback observations exist.
- Use time decay for price, quota, and model-quality drift.
- Reject production promotion unless it beats the deterministic policy on an
  untouched test set and remains explainable and reversible.

## P4: Scale-Triggered Infrastructure

Status: not needed now.

- Adopt OpenTelemetry semantic conventions when cross-process tracing becomes
  necessary.
- Consider LiteLLM or Portkey only if this router must become a multi-user,
  multi-instance gateway with centralized budgets and shared rate limits.
