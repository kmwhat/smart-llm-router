# Method Notes

## Main Finding

The next improvement should be an evidence loop, not a larger model list or a
second gateway. The router already has strong deterministic gates. Its missing
truth surface is whether a route has recently succeeded for the same task, how
slow it was, and whether failures came from the provider or from local network
infrastructure.

## Chosen Method

1. Keep privacy, modality, task-role quality, and budget eligibility as hard
   gates.
2. Derive route health from the existing append-only ledger.
3. Exclude clear local DNS or network-infrastructure failures from model health.
4. Within the same role-quality band, prefer routes that are not empirically
   degraded before applying the free-first rule.
5. Use smoothed success probability to estimate retry-adjusted cost, then use
   successful-call P95 latency as a later tie-breaker.
6. Expose the evidence through a read-only CLI report.

This combines LiteLLM's health and latency discipline, FrugalGPT's cheap-first
escalation, and ParetoBandit's drift awareness without importing a new runtime.
The policy remains deliberately simple because LLMRouterBench reports that
simple baselines often remain competitive under controlled evaluation.

## Important Boundary

API success is not answer quality. A successful call only proves route health.
Models may enter a task's role-quality band only after a repeatable task-level
golden-set evaluation. History therefore cannot promote an unknown model into a
frontier role by itself.

## Rejected or Deferred

- LiteLLM and Portkey: duplicate the current gateway and provider-adapter layer.
- vLLM Semantic Router: useful architecture but excessive deployment and model
  footprint for this Mac-first personal router.
- RouteLLM and ulab-uiuc/LLMRouter: useful research and evaluation references,
  but unnecessary runtime dependencies.
- ParetoBandit: too early for production here and needs enough labeled outcomes
  to outperform a transparent rule.
- Promptfoo: strong candidate for the next isolated evaluation slice, but its
  configurations and extensions are executable and should not be installed
  globally as part of this health-statistics change.
- Third-party routing skills: none passed provenance, security, and fit checks.
