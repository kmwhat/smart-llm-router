---
name: smart-llm-router
description: Use when a task should route across free, low-cost, and frontier LLMs by role, modality, privacy, quality, and budget. Supports planning, execution, audit, independent verification, quality enhancement, text, vision/OCR, ASR, embedding, rerank, and provider discovery across DeepSeek, Qwen, GLM, Kimi, Gemini, Doubao/Ark, OpenRouter, NVIDIA, and Groq.
metadata:
  short-description: Cost-aware free-pool LLM routing
---

# Smart LLM Router

Use the standalone router instead of calling provider APIs directly when the user wants low-cost model execution, free-pool fallback, paid low-cost fallback, model health checks, or portable routing across computers.

## Locate the Router

Project root:

```text
/path/to/smart-llm-router
```

If copied elsewhere, use the copied `smart-llm-router` directory. Use the installed
`smart-llm-router` command or `bin/smart-llm-router`. The portable launcher loads
the project `.env` by default or `SMART_LLM_ENV_FILE` when set, and never prints keys.

## Workflow

1. Check configuration without exposing keys:

```bash
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router refresh-modalities --tasks qa,vision,ocr,transcript_correct,code --limit 2
smart-llm-router refresh-modalities --tasks audit --families zhipu --include-paid --limit 1 --timeout 45
smart-llm-router refresh-modalities --tasks embed,rerank --families zhipu --include-paid --limit 1 --timeout 20
```

2. Discover current candidate models:

```bash
smart-llm-router discover --limit 20
smart-llm-router discover-openrouter --limit 20
smart-llm-router discover-nvidia --limit 50
smart-llm-router discover-groq --limit 50
smart-llm-router discover-ark --limit 100
smart-llm-router discover-vision --limit 20
```

The global runtime automatically refreshes the discovery snapshot when it is older than
`SMART_LLM_DISCOVERY_TTL_HOURS` (default 6). A provider discovery failure retains that
provider's last snapshot. Discovery only admits models to the general free pool; production
roles require benchmark evidence and an explicit quality-band entry before promotion.

3. Refresh the free pool before important work:

```bash
smart-llm-router refresh --timeout 6 --limit 8
smart-llm-router refresh-modalities --timeout 6 --limit 2
```

4. Inspect or clear cooldowns:

```bash
smart-llm-router status
smart-llm-router clear
```

5. Estimate complexity locally before spending tokens:

```bash
smart-llm-router score "清洗 OCR：服務狀態 正常" --task clean
smart-llm-router score "审计架构并设计多步骤优化方案" --task draft
smart-llm-router route-plan "修正技术培训转写稿" --task transcript_correct --domain software --quality-target production --paid-allowed
smart-llm-router route-plan "规划、执行并审计系统升级" --task plan --quality-target frontier --paid-allowed --max-cost-usd 0.05
smart-llm-router workflow-plan /path/to/workflow-contract.json --output-dir ./runtime/workflows
smart-llm-router workflow-check /path/to/workflow-contract.json /path/to/checkpoint.json --output-dir ./runtime/workflows
smart-llm-router transcript-correct /path/to/transcript.txt --domain software --paid-main --cross-check
```

6. Run tasks:

```bash
smart-llm-router task "任务提示" --task summarize --context "参考材料"
smart-llm-router task "任务提示" --task classify --free-only
smart-llm-router task "任务提示" --task draft --paid
smart-llm-router task "制定可验收方案" --task plan --quality-target frontier --paid --max-cost-usd 0.05
smart-llm-router task "修正转写稿" --task transcript_correct --context "原始转写..." --paid
smart-llm-router task "总结文档中的缓存失效策略" --task summarize --retrieve-dir /path/to/vault --max-context-chars 6000
smart-llm-router embed "分布式系统需要处理故障恢复" --provider zhipu --model embedding-3 --dimensions 256
smart-llm-router rerank --query "数据库索引优化" "复合索引应结合查询条件设计" "今天适合整理文件" --provider zhipu --model rerank
smart-llm-router embed "分布式系统需要处理故障恢复" --provider qwen --model text-embedding-v4 --dimensions 256
smart-llm-router task "只输出 JSON：判断图片是否包含数据表格" --task vision --image /path/to/document.png --free-only
```

7. Review the cost ledger and task-specific route health:

```bash
smart-llm-router ledger --limit 20
smart-llm-router route-stats --task audit --limit 1000
```

8. Before registering a discovered model in a production role, run the golden-set gate:

```bash
smart-llm-router golden-eval \
  /path/to/smart-llm-router/examples/golden-sets/audit-public-v1.json \
  --provider groq-free --model qwen/qwen3.6-27b \
  --baseline-provider deepseek-direct-paid --baseline-model deepseek-v4-pro \
  --output-dir ./runtime/golden-evaluations \
  --allow-paid

smart-llm-router promotion-check \
  /path/to/report.json --review /path/to/blind-review.json
```

Use the matching public suite under `examples/golden-sets`: `plan-public-v1`,
`execute-public-v1`, `audit-public-v1`, or `verify-public-v1`. Do not use one
role's suite to promote another role.

## Routing Policy

Default behavior:

- Treat `quality_target` as a minimum role-quality floor: `draft=2`, `production=3`, `audit=4`, and `frontier=4`. Reject lower or unregistered role models. Among qualified routes, order by empirical degradation, budget eligibility, free status, retry-adjusted expected cost, successful-call P95 latency, quality surplus, stable role order, and provider priority. If no route meets the floor, fail closed instead of using the general pool.
- For non-trivial production work, prevent rework before optimizing token price: freeze the objective and measurable success criteria, audit the plan independently, execute one approved stage, checkpoint drift and evidence, then independently verify the final result against the original objective.
- Use `workflow-plan` for the complete local dry-run and cumulative budget ceiling. Use `workflow-check` after scope changes, meaningful milestones, failures, and final delivery. A `verify_required` or `stop` decision must not be silently overridden.
- Use one selected main model per stage. Planning and execution do not run ensembles; plan audit and final verification are separate governance gates.
- Use explicit production roles: Qwen/Kimi for planning, GLM/DeepSeek for execution, Gemini Free Tier/DeepSeek/Qwen for audit, a family different from execution for verification, and conditional Kimi/Qwen quality enhancement.
- Treat same-model key rotation as availability failover only. Plan audit must differ from planning, and final verification must differ from execution; the five roles do not require five unique providers.
- Distinguish `permanent_free`, `trial_quota`, and `paid`; Qwen, NVIDIA, and Ark trial resources are not permanent-free promises.
- Use `--privacy auto|local_only|external_allowed`; private images, chat records, identity data, and raw private media fail closed unless external upload is explicitly allowed.
- Use `--max-cost-usd` for a hard task budget. Unknown paid prices fail closed when a budget is present.
- If a model fails with 429, timeout, 403/404, or empty content, mark it in cooldown and skip it next time.
- If the free pool appears fully cooled down, run a light refresh before using paid fallback.
- Prefer `refresh-modalities` for important checks; it probes text, vision/OCR, transcript correction, and code routes separately instead of treating a generic QA success as global health.
- The public template keeps Gemini in free-tier mode. Suppress paid Gemini unless `SMART_LLM_GEMINI_PAID_ENABLED=true`; use its free tier only for public, non-sensitive inputs because quota is restricted and free-tier content may be used for product improvement.
- Role routing is quality-and-cost aware across DeepSeek V4, Qwen 3.7, GLM-5.2, Kimi K3, Gemini Free Tier, and Doubao Seed 2.1/2.0. A public model name is only a candidate until its current endpoint passes a live probe.
- Simple tasks are scored locally and default to free-only behavior.
- Repeated identical requests can hit the local response cache.
- Each call writes a local JSONL ledger row with model, estimated tokens, latency, cache/failure status, and estimated cost when pricing is configured.
- `route-stats` derives per-task route health from that ledger. It requires at least three health samples before marking a route degraded and excludes clear local DNS/network infrastructure failures from the health denominator.
- API success proves endpoint health, not answer quality. Never promote a discovered model into a production role from health history alone; require task probes, a task-specific golden set, and explicit quality-band registration.
- For subjective roles, the golden report must include a current baseline and a blind review by a model family different from both candidate and baseline, or an independent human reviewer. A `pass` decision grants eligibility for explicit registration only; it never edits the role table automatically.
- Stop evaluation spending by stage: run the candidate hard gates first, call the paid baseline only after they pass, and call an independent reviewer only after baseline non-regression passes.
- Keep public synthetic suites in the project and private user/task suites in local runtime or the governed knowledge lane. Golden suites must never contain credentials or raw prohibited private payloads.
- `groq-free/openai/gpt-oss-120b` passed the 2026-07-18 public verification gate and is explicitly registered at `verify` band 2. Treat it as `trial_quota`, use it only for public low-risk draft verification, and keep band 3/4 models ahead for higher-risk work.
- Use local retrieval before long context calls so only the most relevant snippets go to the model.
- Vision tasks support local `--image` paths and dynamic failover across free vision models. A failed free vision model enters cooldown and the router immediately tries the next configured vision model.
- Use `route-plan` before production or multimodal work. It prints a local task descriptor, modality requirements, local preprocessing steps, free pool, low-cost paid fallback, second-model cross-check, and Codex audit boundary. `embed` and `rerank` use dedicated adapters; image/video generation and ASR/TTS still require dedicated adapters before direct execution.
- The five roles are governance stages, not a requirement to call five models for every task. Process checkpoints are local by default; quality enhancement is conditional and runs only after a verified quality gap.
- Use `capabilities` to inspect provider-family model modes, including text, vision/OCR, ASR/TTS, image/video generation, embedding, rerank, and code coverage. It separates known API-key capability from currently configured/probed executable model routes, and does not print API keys.
- Treat raw `rerank` scores as provider-specific relative ordering signals, not universal absolute relevance thresholds. For production knowledge retrieval, combine rank, top-k, source type, term hits, and second evidence checks.
- Current production hot path: `embed` defaults to Qwen `text-embedding-v4`, then Zhipu `embedding-3`; `rerank` defaults to Zhipu `rerank`. Qwen `gte-rerank` has a reserved DashScope adapter path but should stay disabled until account/service permission passes `refresh-modalities`.
- Use `transcript-correct` for long-form ASR correction. It chunks the transcript, applies deterministic cleanup, routes correction through low-cost models, optionally cross-checks, and writes corrected/report artifacts to disk.
- For long transcripts, Codex should only orchestrate and audit; it should not ingest the whole raw transcript.
- Keep Volcano Ark online inference, Coding Plan, and endpoint ids separate. Their base URLs, model names, quotas, and billing paths are not interchangeable. Treat all configured model names as account-scoped candidates until discovery and task probes succeed.

Task defaults from the latest benchmark:

- `classify`: OpenRouter DeepSeek free first.
- `clean`: Qwen first, then stable NVIDIA/Gemma candidates.
- `qa`: NVIDIA Nemotron Super first.
- `summarize`: Qwen/NVIDIA stable models first.
- `vision`: NVIDIA/OpenRouter free first for routine work; the paid multimodal branch uses verified Doubao Seed 2.0 Pro for low-cost image understanding and Gemini/Kimi for high-risk independent review.
- `transcript_correct`: local glossary cleanup first, then Qwen/NVIDIA/OpenRouter/Groq free candidates, then DeepSeek/Gemini low-cost paid fallback when allowed.
- `audit` and high-value `transcript_correct`: use DeepSeek as low-cost main fallback and GLM/Zhipu as an independent cross-check when configured and healthy.
- `ocr`: same model pool as vision, with conservative text extraction prompts.
- `audit`: Qwen/NVIDIA free first, then low-cost paid fallback for production checks.
- `verify`: Groq `openai/gpt-oss-120b` is an approved band-2 trial route for public draft verification; production and frontier verification still use an independent band-3/4 model.
- `groq-free`: configured but should remain lower priority if network handshake timeouts persist.

## Configuration

Use `.env.example` as the template. API keys must stay in `.env` and must not be printed in answers.

Provider blocks use:

```text
SMART_LLM1_NAME=provider-name
SMART_LLM1_BASE_URL=https://example.com/v1
SMART_LLM1_API_KEY_ENV=PROVIDER_API_KEY
SMART_LLM1_MODELS=model-a,model-b
SMART_LLM1_FREE=true
SMART_LLM1_BILLING_CLASS=permanent_free
SMART_LLM1_PRIORITY=1
```

Valid billing classes are `local`, `permanent_free`, `trial_quota`, and `paid`.
The portable launcher stores state under `SMART_LLM_RUNTIME_DIR` or the standard
user state directory. An optional credential catalog is loaded only when
`SMART_LLM_CREDENTIAL_CATALOG` is explicitly set.

## Validation

After changes, run:

```bash
python -m compileall smart_llm_router
smart-llm-router refresh --timeout 6 --limit 5
smart-llm-router task "只输出 OK" --task qa --free-only
smart-llm-router task "只输出 JSON：判断图片是否包含数据表格" --task vision --image /path/to/document.png --free-only
```

Do not run large benchmark sweeps unless the user explicitly asks; free providers can rate-limit.
