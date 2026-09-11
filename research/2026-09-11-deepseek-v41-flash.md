# DeepSeek V4.1 Flash synchronization note

## Decision

- Keep the production DeepSeek API request ID `deepseek-v4-flash`. The official
  API model list and integration docs define this stable alias; do not invent a
  `deepseek-v4.1-flash` API ID.
- Update the Router's descriptive candidate version to
  `DeepSeek-V4.1-Flash`, while retaining `pending_role_golden_gate`. A model
  announcement or open-weight model card is not a role-quality promotion.
- Reserve current peak cache-miss/output prices of USD 0.44 / 1.32 per million
  tokens so budget authorization remains conservative across peak/off-peak
  periods.
- Do not infer API image support for the text alias from the open-weight model.
  The official API still exposes image input through the separate experimental
  `deepseek-v4-flash-vision-exp` route.

## Primary sources

- DeepSeek official API model list:
  <https://api-docs.deepseek.com/api/list-models/>
- DeepSeek official models and pricing:
  <https://api-docs.deepseek.com/quick_start/pricing/>
- DeepSeek official thinking-mode controls:
  <https://api-docs.deepseek.com/guides/thinking_mode/>
- DeepSeek official open-weight model card:
  <https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash>

## Rejected alternatives

- A temporary or guessed versioned API model ID: rejected because it is not in
  the official API model list.
- Automatic audit/plan-audit band promotion: rejected until a role-matched,
  settled, no-fallback golden gate passes on the served V4.1 route.
- Treating the base text alias as multimodal: rejected because current API docs
  reserve image input for the separate Vision Exp model.

## Validation plan

Run the Router's targeted candidate and pricing tests, then its complete test
suite, compileall, `git diff --check`, and Gitleaks. Hermes may use the stable
API alias with `reasoning_effort=max`; retain a reversible configuration backup
and the existing fallback chain. A paid live model call requires a bounded
explicit budget and is not implied by this metadata synchronization.
