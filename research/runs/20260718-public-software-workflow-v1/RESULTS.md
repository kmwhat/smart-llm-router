# Quality Target Cost Floor Workflow Results

Status: complete

Workflow: `wf-quality-target-cost-floor-public-v1`

Date: 2026-07-18

## Objective

Make `quality_target` an executable minimum role-quality floor while preserving free-first, health-aware, budget-safe routing. The same rule must govern recommendations, route plans, workflow role pipelines, and direct model execution.

## Delivered Behavior

- `draft` requires role quality band 2 or higher.
- `production` requires role quality band 3 or higher.
- `audit` and `frontier` require role quality band 4.
- Models below the floor or absent from the role-quality registry cannot enter a role route.
- Eligible routes are ordered by route health, budget eligibility, free status, retry-adjusted expected cost, successful P95 latency, quality surplus, stable role order, and provider priority.
- A role task with no qualified route fails closed instead of falling back to an unregistered general-pool model.

## Controlled Workflow

1. Qwen planning timed out, and the Kimi fallback returned HTTP 400 after local prompt compression.
2. The Codex controller froze the minimal implementation plan.
3. Gemini 2.5 Pro performed three independent plan-audit rounds. The first two found blockers; the third approved the exact file scope.
4. GLM execution advice timed out, and the Doubao code route failed closed because its price was unknown.
5. Codex implemented the approved scope in an isolated staging copy.
6. Local tests and the execution checkpoint passed before production synchronization.
7. DeepSeek V4 Pro returned an empty final-verification response. The route was stopped instead of retried.
8. Free Gemini 2.5 Pro completed the independent final verification with all six criteria passing and no blocking findings.
9. The final workflow checkpoint returned `complete` with no drift or scope change.

## Production Validation

- Full unit suite: 67 passed.
- Python compile check: passed.
- Git whitespace check: passed.
- Runtime recommendation check: `draft` admitted the healthy free band-2 GPT-OSS route.
- Runtime recommendation check: `production` excluded band 2 and selected free band-4 Gemini.
- Runtime recommendation check: `frontier` planning retained only band-4 role candidates.
- Runtime route-plan check: role stages reported the shared production floor and preserved independent-family constraints.
- Live free health probe: NVIDIA Gemma returned `OK`, ledger `4e660b85a3d293af`.
- Live production-role call: Gemini executed the `verify` route, ledger `068f2131b9f21e08`.

## Cost And Safety

- Reported successful model cost: USD 0.00 because all successful review calls used free routes.
- Conservative failed-request bound: USD 0.05, equal to the workflow ceiling.
- No API keys, private environment values, or user data were placed in public artifacts.
- No dependency, provider credential, or Hermes unattended-security setting changed.
- Codex and Hermes continue to use symbolic links to this production source tree.

## Evidence

- `workflow-contract.json`: original objective, constraints, budget, and acceptance criteria.
- `plan-design.json`: approved design and deterministic selection sequence.
- `plan-audit-gemini-*.json`: blocking review history and final approval.
- `implementation-evidence.json`: changed-file scope and local validation.
- `execution-routing-evidence.json`: model route outcomes and conservative cost accounting.
- `final-verification-gemini.json`: independent final decision and scope-note adjudication.
- `final-verification-checkpoint.json`: final criterion state submitted to the local workflow gate.
- `execution-checkpoint-receipt.json`: local gate decision allowing production synchronization.
- `final-verification-checkpoint-receipt.json`: local gate decision marking the workflow complete.

## Residual Boundary

A strict quality floor can intentionally produce no route. This is expected fail-closed behavior. Provider model names, prices, quotas, and health remain dynamic inputs and should continue to be refreshed before important workflows.
