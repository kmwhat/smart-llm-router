# Official Source Pack

Research date: 2026-07-18

## Production Routing and Gateways

- [LiteLLM Router](https://docs.litellm.ai/docs/routing): production routing
  primitives for cooldowns, retries, fallbacks, load balancing, latency-aware
  selection, and cost-aware selection.
- [LiteLLM Adaptive Router](https://docs.litellm.ai/docs/adaptive_router): a beta
  request-class quality estimator with cost/quality weights and cold-start priors.
  It currently requires LiteLLM Proxy and PostgreSQL and documents limitations
  including no latency score and no time decay.
- [LiteLLM Provider Budget Routing](https://docs.litellm.ai/docs/proxy/provider_budget_routing):
  provider, model, and tag-level budgets with Redis for multi-instance state.
- [LiteLLM GitHub](https://github.com/BerriAI/litellm): active unified gateway;
  broad capability surface but substantial overlap with this router.
- [Portkey AI Gateway](https://github.com/Portkey-AI/gateway): retries,
  fallbacks, load balancing, conditional routing, and guardrails. Useful as a
  reference, but it would add a second gateway layer.

## Semantic and Learned Routing

- [vLLM Semantic Router](https://github.com/vllm-project/semantic-router): a
  signal-decision plugin chain for task, complexity, tools, PII, guardrails,
  semantic cache, domain prompts, and multimodal routing.
- [Iris Router paper](https://arxiv.org/abs/2603.04444): the research basis for
  vLLM Semantic Router's modular signal and decision architecture.
- [RouteLLM](https://github.com/lm-sys/RouteLLM) and its
  [paper](https://arxiv.org/abs/2406.18665): preference-data routing between
  strong and weak models plus a reusable evaluation approach.
- [ParetoBandit](https://arxiv.org/abs/2604.00136) and its
  [reference implementation](https://github.com/ParetoBandit/ParetoBandit):
  contextual bandit routing with dollar-budget pacing, geometric forgetting,
  and a model registry that can adapt to drift.
- [FrugalGPT](https://arxiv.org/abs/2305.05176): prompt adaptation, caching,
  approximation, and cascaded escalation to reduce cost while preserving
  quality.
- [Cluster-Route-Escalate](https://arxiv.org/abs/2606.27457): route by task
  cluster, estimate output quality, and escalate only when needed.

## Evaluation and Observability

- [LLMRouterBench](https://arxiv.org/abs/2601.07206) and its
  [repository](https://github.com/ynulihao/LLMRouterBench): a unified benchmark
  across many datasets, models, and router baselines. It reports that simple
  baselines are often competitive and that model-pool curation matters greatly.
- [Promptfoo assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/):
  deterministic, model-graded, and derived-metric assertions for repeatable
  model and prompt evaluation.
- [Promptfoo security policy](https://github.com/promptfoo/promptfoo/security):
  configuration can invoke providers, transforms, and custom JavaScript or
  Python, so imported evaluation projects must be treated as executable code.
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):
  standardized telemetry fields for generative-AI operations and usage.
- [ulab-uiuc LLMRouter](https://github.com/ulab-uiuc/LLMRouter): a maintained
  research framework containing multiple routing approaches and multimodal
  support; useful for experiments, but much heavier than the local runtime.

## Skill Design

- [Anthropic Skills](https://github.com/anthropics/skills): maintained examples
  of concise task-triggered skills with references and evaluation guidance.
- No specific third-party LLM-routing skill found in this scan had enough
  official provenance, security evidence, and local fit to justify installation.

## Live Repository Snapshot

The GitHub metadata below was checked through the GitHub API on 2026-07-18.

| Repository | Recent activity | License metadata | Decision |
| --- | --- | --- | --- |
| BerriAI/litellm | active | NOASSERTION in API | methods only |
| vllm-project/semantic-router | active | Apache-2.0 | methods only |
| lm-sys/RouteLLM | last push in 2024 | Apache-2.0 | evaluation ideas only |
| promptfoo/promptfoo | active | MIT | isolated evaluator candidate |
| Portkey-AI/gateway | maintained | MIT | reject duplicate gateway |
| ParetoBandit/ParetoBandit | early project | Apache-2.0 | future experiment only |
| ynulihao/LLMRouterBench | maintained | license not declared in API | paper methodology only |
| ulab-uiuc/LLMRouter | active | MIT | research sandbox only |
