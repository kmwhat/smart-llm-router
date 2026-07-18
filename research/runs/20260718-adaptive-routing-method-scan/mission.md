# Mission

## Objective

Scan current official documentation, maintained GitHub repositories, and primary
research for proven LLM-routing methods, then apply the smallest high-value
improvements to the local Smart LLM Router.

## Baseline

- Project version: 0.4.1 working tree.
- Tests: 46/46 passing before this scan.
- Existing strengths: privacy and modality gates, role quality bands, free-first
  selection within a quality band, persistent cooldowns, dynamic free-model
  discovery, cost estimates, workflow checkpoints, and conditional verification.
- Current controller: Codex/Hermes; the router handles auxiliary and delegated
  provider calls rather than replacing the controller model.

## Research Questions

1. How should live success rate, latency, quota, and retry cost affect selection?
2. How should newly discovered models be evaluated and promoted by task?
3. Which semantic or learned routing methods are useful at this system's scale?
4. Which gateway, evaluation, and observability capabilities should be reused
   rather than reimplemented?
5. What can improve quality and reduce cost without exposing private inputs or
   introducing a large always-on service?

## Constraints

- Do not run or install untrusted GitHub code during discovery.
- Do not expose credentials, private prompts, chats, images, or runtime ledgers.
- Prefer standard-library or existing-project changes over new dependencies.
- Preserve the current role-quality and privacy gates.
- Any production promotion must remain reversible and evidence-backed.

## Deliverables

- `source-pack/official-sources.md`
- `source-scorecard.json`
- `method-notes.md`
- `upgrade-proposals.md`
- `validation-plan.md`
- Tested implementation of the first approved optimization slice.
