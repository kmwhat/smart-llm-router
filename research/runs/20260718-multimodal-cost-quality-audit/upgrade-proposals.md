# Upgrade Proposals

## Target Architecture

`task descriptor -> privacy gate -> local/cache/retrieval -> eligible model modes -> quality-cost choice -> selective verification -> ledger`

The objective is: meet the required quality floor, then minimize expected total
cost. Free models win only when they are healthy and good enough for that exact
task.

## P0: Cost And Safety Truth Surface

1. Move runtime state from `/private/tmp` to a persistent private directory.
2. Add a normalized pricing registry with token, image, audio-minute, video-second, request, and cache-hit units.
3. Replace `free: bool` with `permanent_free | trial_quota | paid | local` and track quota expiry/remaining budget.
4. Add per-job, per-day, and per-provider budgets plus a hard `max_cost` gate.
5. Deduplicate choices by provider account, endpoint, and model; track key failover separately from model diversity.
6. Make private palm/user/chat/course inputs `local_only` by default unless external use is explicitly allowed.
7. Prefer healthy DeepSeek direct Flash over the OpenRouter copy for paid text work when direct cost is lower.

## P1: Provider-Family Multimodal Completion

1. Add and probe Zhipu free text/vision/image/video candidates from the official catalog before paid variants.
2. Keep Qwen text embedding as the bulk default; use batch embedding when indexing many documents.
3. Keep Zhipu rerank as the current production default; compare Qwen3 rerank on a local relevance set before switching.
4. Add Groq Whisper as an explicit, non-private remote ASR fallback after local Whisper.
5. Add Kimi vision and current Kimi reasoning/long-context models as candidates, but promote only after cost and quality probes.
6. Add a low-cost Gemini Flash-Lite candidate for multimodal overflow; keep stable models ahead of previews.
7. Implement dedicated async adapters for Qwen/Zhipu/Gemini image, video, and TTS modes where needed.

## P2: Quality-Aware Escalation

1. Build small local golden sets for classify, OCR, palm feature extraction, transcript correction, retrieval, code review, and consultation audit.
2. Record task-level accuracy, evidence coverage, schema validity, latency, retries, and actual provider cost.
3. Escalate only on low confidence, disagreement, missing evidence, failed schema, or high-risk output.
4. For production outputs, use one selected main model per stage and one independent verifier only on high-risk chunks or the final artifact.
5. Let Codex remain the controller, repository editor, and final acceptance layer rather than the bulk processor.

## Recommended Stage Routes

| Stage | Default | Escalation |
|---|---|---|
| Intent/classification | local rules/cache, then healthy free small model | Qwen/DeepSeek Flash only on ambiguity |
| Context compression | retrieval and deterministic compression, then Qwen/NVIDIA free | DeepSeek Flash for production synthesis |
| Knowledge retrieval | Qwen `text-embedding-v4` batch | Zhipu `embedding-3` failover |
| Evidence ranking | Zhipu `rerank` | Qwen3 rerank after benchmark |
| Vision/OCR | local resize/OCR, NVIDIA/Zhipu free vision, then Gemini Free Tier for public inputs | Qwen VL, Zhipu V, Doubao/Kimi for unresolved cases |
| Course ASR | local Whisper | flagged segments only to Groq/Qwen/Zhipu with permission |
| Transcript correction | glossary + chunks + Qwen/NVIDIA free | DeepSeek Flash main, GLM independent check for high-risk chunks |
| Code support | Codex controller, free model for bounded analysis | DeepSeek Flash for bulk review; Codex integrates/tests |
| Planning | local constraints and acceptance extraction | Qwen 3.7 Max; Doubao Seed 2.1 Pro or Kimi K3 as alternatives |
| Long execution | deterministic tools and staged commits | GLM-5.2; Doubao Seed 2.0 Code or DeepSeek V4 Pro as alternatives |
| Independent verification | deterministic acceptance plus source replay, then Gemini 2.5 Pro Free Tier for public inputs | DeepSeek V4 Pro, Doubao Seed 2.x, or another family independent from execution |
| Image generation | only on explicit request | dedicated Zhipu/Qwen/Gemini image adapter with budget gate |
| Final audit | deterministic checks + evidence coverage | one independent Gemini Free Tier or paid specialist check, then Codex acceptance |

Within a role-quality band, free wins. A lower-band free model does not replace a
higher-band specialist. `quality_enhance` stays off unless final verification
records a concrete clarity, expression, or coverage gap.

## Hard Stops

- No external upload when privacy is `local_only`.
- No paid call without known price or explicit budget exception.
- No production promotion from model-list discovery alone.
- No second-model claim when only the API key changed.
- No unbounded retry after 429, timeout, empty output, unsupported modality, or invalid schema.
- No mixing of Volcano Ark online-inference, Coding Plan, and endpoint model names or billing paths.
