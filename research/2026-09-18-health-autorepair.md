# Router health auto-repair and finance benchmark

## Official method scan

- Google Gemini OpenAI compatibility: <https://ai.google.dev/gemini-api/docs/openai>. The endpoint is OpenAI-compatible, but model IDs must be taken from the current Google model catalog; a 404 is model/endpoint drift, not a credential success.
- Volcengine Ark maintained SDK: <https://github.com/volcengine/ark-runtime-python>. Ark uses the OpenAI-compatible `/api/v3/chat/completions` path with an endpoint/model identity. Bare stale Seed names are not treated as executable without an explicit current model or endpoint ID.

## Chosen repair

1. 404/410 failures now create a sanitized route incident and quarantine the exact provider/model for 30 days. A fresh successful health call is the only clear path.
2. Gemini frontier defaults no longer include the observed stale `gemini-2.5-pro`; current IDs are supplied by `SMART_LLM_GEMINI_MODELS` or the conservative preview default.
3. Ark frontier routes require `SMART_LLM_DOUBAO_FRONTIER_MODELS` or `ARK_ENDPOINT_ID`; the generic stale model list is not auto-created.
4. Daily health is free/local only. The optional weekly script uses one synthetic call per role, exact route, no fallback, `$0.01` per-call and `$0.05` cumulative workflow ceilings.
5. `investing-public-v1.json` is a public synthetic, seven-part benchmark. It must be run with blind review and different-family review; vendor self-reported rankings never promote a role.

## Rejected alternatives

- Treating a catalog listing as runtime health: rejected because it cannot prove endpoint/model execution.
- Silently replacing a failed route with a lower quality model: rejected; same quality floor and fail-closed behavior remain mandatory.
- Running unconstrained weekly paid probes: rejected; the script has explicit hard ceilings and can be scheduled only with `--include-paid`.

## Hard stops

- Missing/invalid credentials, 401/403, budget reservation ambiguity, repeated truncation, or no independent reviewer keep the route out of production role bands.
- No private finance/account input is included in the benchmark; account observations must remain separate from public market facts.
