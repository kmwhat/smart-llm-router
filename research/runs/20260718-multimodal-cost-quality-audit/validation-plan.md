# Validation Plan

## Acceptance Gates

1. Every executable model mode has an endpoint adapter, entitlement probe, price unit, health state, and task-level quality record.
2. The router can explain why a model was selected and report actual provider/model, privacy decision, cache state, cost, and verification result.
3. A reboot does not erase the cost ledger, cooldowns, cache metadata, or modality health reports.
4. A private palm-photo or consultation task is blocked from external routing by default.
5. A trial quota cannot be reported as permanently free.
6. A paid call is rejected when its estimated upper bound exceeds the task budget.
7. Planning is independently audited before execution, and planning/audit model families differ.
8. Scope changes, missing evidence, unresolved criteria, or uncertain objective alignment require verification.
9. Final delivery fails closed unless all success criteria pass and cumulative spend stays within the workflow budget.
10. Unattended Hermes execution remains blocked without an explicit, current security approval.
11. Gemini paid providers remain absent unless billing is explicitly opted in; the default Gemini route reports `trial_quota` and zero projected API cost.
12. A free model wins only within the same role-quality band, and one successful stage performs exactly one model call.
13. Final quality enhancement is conditional and included only in the workflow budget reserve.

## Minimal Test Matrix

- Text: classify, summarize, long-context synthesis, code review, structured JSON.
- Vision: OCR screenshot, document page, palm feature extraction with synthetic/non-private fixtures.
- Audio: local ASR, low-confidence segment retry, remote permission gate.
- Retrieval: embedding recall, rerank top-k relevance, source coverage.
- Generation: image adapter cost gate and artifact persistence.
- Failure: 429, timeout, empty output, invalid schema, unsupported modality, quota exhausted.

## Promotion Rule

Promote a model-mode route only after it passes three small live probes and the
relevant local golden set. Preview models remain candidates unless they clearly
beat a stable route on both quality and expected total cost.
