from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_settings
from .evaluation import build_promotion_decision, run_golden_evaluation, write_promotion_decision
from .governance import (
    build_workflow_plan,
    evaluate_workflow_checkpoint,
    make_route_receipt,
    validate_task_contract,
    write_route_receipt,
    write_workflow_artifact,
)
from .router import (
    TASK_TYPES,
    capability_registry,
    clear_route_state,
    describe_providers,
    discover_free_pool,
    discover_groq_models,
    discover_ark_models,
    discover_nvidia_models,
    discover_nvidia_vision_models,
    discover_openrouter_free,
    discover_openrouter_vision_free,
    discover_vision_pool,
    maintain_pool,
    quick_benchmark,
    quick_vision_benchmark,
    preprocess_input,
    read_cost_ledger,
    recommend_route,
    route_performance_stats,
    route_plan,
    retrieve_local_context,
    refresh_model_pool,
    refresh_model_pool_by_modality,
    asr_status,
    route_status,
    run_llm_task,
    score_task_complexity,
    transcript_correct,
    transcribe_media,
    embed_texts,
    generate_image,
    remote_transcribe_media,
    rerank_documents,
)


TASK_CHOICES = sorted(TASK_TYPES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smart-llm-router", description="智能 LLM 路由：免费池优先、失败冷却、低价付费兜底")
    parser.add_argument("--env-file", help="指定 .env 文件，默认读取当前目录 .env")
    parser.add_argument("--credential-catalog", help="模型厂商凭据目录文件；仅在进程内装载，不输出值")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="查看 provider 配置摘要，不输出 key")
    caps = sub.add_parser("capabilities", help="查看 provider-family 多模态能力注册表，不输出 key")
    caps.add_argument("--configured-only", action="store_true", help="只显示当前已配置的 family")
    sub.add_parser("status", help="查看模型冷却状态")
    sub.add_parser("clear", help="清空模型冷却状态")
    ledger = sub.add_parser("ledger", help="查看最近的成本/调用账本")
    ledger.add_argument("--limit", type=int, default=20)
    route_stats = sub.add_parser("route-stats", help="按任务/provider/model 汇总近期成功率、失败类型、延迟和成本")
    route_stats.add_argument("--task", choices=TASK_CHOICES)
    route_stats.add_argument("--limit", type=int, default=1000, help="最多读取最近多少条账本记录；0 表示全部")

    golden_eval = sub.add_parser("golden-eval", help="运行任务黄金集：候选与基线逐题实测，并生成独立盲审包")
    golden_eval.add_argument("suite_file")
    golden_eval.add_argument("--provider", required=True, help="候选 provider 精确名称")
    golden_eval.add_argument("--model", required=True, help="候选 model 精确名称")
    golden_eval.add_argument("--baseline-provider", help="基线 provider 精确名称")
    golden_eval.add_argument("--baseline-model", help="基线 model 精确名称")
    golden_eval.add_argument("--output-dir")
    golden_eval.add_argument("--allow-paid", action="store_true", help="允许候选或基线调用付费路线；仍受 suite 单次成本门约束")

    promotion = sub.add_parser("promotion-check", help="本地检查黄金集、健康、成本和独立盲审证据；不自动修改生产角色表")
    promotion.add_argument("report_file")
    promotion.add_argument("--review", help="独立盲审结果 JSON")
    promotion.add_argument("--output", help="晋级判定落盘路径；默认写到 report 同目录的 promotion-decision.json")

    contract = sub.add_parser("contract-plan", help="验证 Hermes Router Hub 任务契约并生成 dry-run 路由回执")
    contract.add_argument("contract_file")
    contract.add_argument("--receipt-dir")

    workflow_plan = sub.add_parser("workflow-plan", help="生成规划审查、执行、过程检查和最终复验工作流；不调用模型")
    workflow_plan.add_argument("contract_file")
    workflow_plan.add_argument("--output-dir")

    workflow_check = sub.add_parser("workflow-check", help="本地检查工作流阶段证据、预算和目标偏离；不调用模型")
    workflow_check.add_argument("contract_file")
    workflow_check.add_argument("checkpoint_file")
    workflow_check.add_argument("--output-dir")

    score = sub.add_parser("score", help="本地评估任务复杂度，不调用模型")
    score.add_argument("prompt")
    score.add_argument("--task", choices=TASK_CHOICES, default="draft")
    score.add_argument("--context")

    preprocess = sub.add_parser("preprocess", help="本地端侧预处理：分类、压缩上下文、估算 token 节省，不调用模型")
    preprocess.add_argument("prompt")
    preprocess.add_argument("--task", choices=TASK_CHOICES, default="draft")
    preprocess.add_argument("--context")
    preprocess.add_argument("--context-file", help="从文件读取参考材料，仅在本地抽取压缩")
    preprocess.add_argument("--target-tokens", type=int, default=0, help="压缩后上下文目标 token；0 为按输入长度自动决定")

    recommend = sub.add_parser("recommend", help="只做本地任务分析并输出推荐模型顺序，不调用模型")
    recommend.add_argument("prompt")
    recommend.add_argument("--task", choices=TASK_CHOICES, default="draft")
    recommend.add_argument("--context")
    recommend.add_argument("--paid", action="store_true", help="付费优先")
    recommend.add_argument("--free-only", action="store_true", help="只展示免费路线")
    recommend.add_argument("--quality-target", choices=["draft", "production", "audit", "frontier"], default="production")
    recommend.add_argument("--max-cost-usd", type=float, help="单次调用预算上限；未知价格的付费模型会失败关闭")

    plan = sub.add_parser("route-plan", help="按任务/模态输出成本质量路由计划，不调用模型")
    plan.add_argument("prompt", nargs="?", default="")
    plan.add_argument("--task", choices=TASK_CHOICES, default="draft")
    plan.add_argument("--context")
    plan.add_argument("--context-file", help="从文件读取参考材料，仅用于本地评分/规划")
    plan.add_argument("--input-modalities", default="", help="逗号分隔，例如 text,image,audio")
    plan.add_argument("--output-modalities", default="", help="逗号分隔，例如 text,image")
    plan.add_argument("--domain", default="general")
    plan.add_argument("--quality-target", choices=["draft", "production", "audit", "frontier"], default="draft")
    plan.add_argument("--risk", choices=["low", "medium", "high"])
    plan.add_argument("--paid-allowed", action="store_true", help="允许低价付费模型进入路线")
    plan.add_argument("--paid", action="store_true", help="付费优先")
    plan.add_argument("--limit", type=int, default=12)
    plan.add_argument("--privacy", choices=["auto", "local_only", "external_allowed"], default="auto")
    plan.add_argument("--max-cost-usd", type=float, help="单阶段调用预算上限；未知价格的付费模型会失败关闭")

    sub.add_parser("asr-status", help="检查本地视频/音频转文字后端")

    transcribe = sub.add_parser("transcribe", help="本地视频/音频转文字，默认免费本地 ASR")
    transcribe.add_argument("input_file")
    transcribe.add_argument("--output-dir")
    transcribe.add_argument("--backend", choices=["auto", "whisper_cpp", "openai_whisper", "mlx_whisper"], default="auto")
    transcribe.add_argument("--language", default="zh")
    transcribe.add_argument("--model", help="ASR 模型名或模型文件路径")
    transcribe.add_argument("--keep-audio", action="store_true")

    remote_asr = sub.add_parser("remote-transcribe", help="显式上传音频到已配置的厂商 ASR；私密资料默认不要使用")
    remote_asr.add_argument("input_file")
    remote_asr.add_argument("--provider", required=True, choices=["zhipu", "qwen"])
    remote_asr.add_argument("--model")
    remote_asr.add_argument("--language", default="zh")
    remote_asr.add_argument("--timeout", type=float)
    remote_asr.add_argument("--allow-external", action="store_true", help="确认允许将该音频上传到指定厂商")

    correct = sub.add_parser("transcript-correct", help="长篇 ASR 转写稿分块纠错，并落盘 corrected/report")
    correct.add_argument("input_file")
    correct.add_argument("--output-dir")
    correct.add_argument("--domain", default="general", help="转写内容所属领域或主题，例如 software、finance、general")
    correct.add_argument("--chunk-chars", type=int, default=3500)
    correct.add_argument("--free-only", action="store_true", help="只允许免费模型，禁用低价付费主修正")
    correct.add_argument("--paid-main", action="store_true", help="主修正优先使用低价付费模型")
    correct.add_argument("--cross-check", action="store_true", help="对每块增加二次模型交验")
    correct.add_argument("--quality-target", choices=["draft", "production", "audit"], default="production")
    correct.add_argument("--max-context-chars", type=int, default=7000)

    embed = sub.add_parser("embed", help="专用文本向量化 adapter，不走 chat/completions")
    embed.add_argument("texts", nargs="*", help="待向量化文本；也可用 --input-file")
    embed.add_argument("--input-file", help="从文件读取文本；默认整文件作为一条输入")
    embed.add_argument("--split-lines", action="store_true", help="配合 --input-file 时按非空行拆分输入")
    embed.add_argument("--provider", help="限定 provider 名或 family，如 zhipu")
    embed.add_argument("--model", help="限定模型，如 embedding-3")
    embed.add_argument("--dimensions", type=int, help="向量维度，例如 256、512、1024、2048")
    embed.add_argument("--timeout", type=float, help="单请求超时秒数")
    embed.add_argument("--full", action="store_true", help="输出完整向量；默认只输出维度和前 8 维预览")

    rerank = sub.add_parser("rerank", help="专用文本重排序 adapter，不走 chat/completions")
    rerank.add_argument("documents", nargs="*", help="候选文本；也可用 --documents-file")
    rerank.add_argument("--query", required=True, help="查询文本")
    rerank.add_argument("--documents-file", help="从文件按非空行读取候选文本")
    rerank.add_argument("--provider", help="限定 provider 名或 family，如 zhipu")
    rerank.add_argument("--model", help="限定模型，如 rerank")
    rerank.add_argument("--top-n", type=int, default=0, help="只返回前 N 条；0 为返回全部")
    rerank.add_argument("--return-raw-scores", action="store_true", help="请求返回 raw scores")
    rerank.add_argument("--timeout", type=float, help="单请求超时秒数")

    image_gen = sub.add_parser("image-generate", help="专用图像生成 adapter；必须显式允许付费")
    image_gen.add_argument("prompt")
    image_gen.add_argument("--provider", default="zhipu")
    image_gen.add_argument("--model")
    image_gen.add_argument("--size", default="1024x1024")
    image_gen.add_argument("--quality", default="hd")
    image_gen.add_argument("--timeout", type=float)
    image_gen.add_argument("--allow-paid", action="store_true")

    refresh = sub.add_parser("refresh", help="主动探活模型池并更新冷却状态")
    refresh.add_argument("--include-paid", action="store_true", help="同时探活付费模型")
    refresh.add_argument("--timeout", type=float, default=6.0, help="单模型超时秒数")
    refresh.add_argument("--limit", type=int, default=0, help="最多探活多少个模型，0 为全部")
    refresh_modalities = sub.add_parser("refresh-modalities", help="按任务/模态探活模型池，更新冷却状态并写入模态报告")
    refresh_modalities.add_argument("--include-paid", action="store_true", help="同时探活付费模型")
    refresh_modalities.add_argument("--timeout", type=float, default=6.0, help="单模型超时秒数")
    refresh_modalities.add_argument("--limit", type=int, default=0, help="每个任务最多探活多少个模型，0 为全部")
    refresh_modalities.add_argument("--tasks", default="qa,vision,ocr,transcript_correct,code", help="逗号分隔任务，如 qa,vision,ocr,transcript_correct,code")
    refresh_modalities.add_argument("--families", default="", help="只探测指定 provider/model family，逗号分隔，如 zhipu,qwen,deepseek")

    discover = sub.add_parser("discover", help="聚合发现 OpenRouter/NVIDIA/Groq 候选模型")
    discover.add_argument("--limit", type=int, default=20)
    discover_or = sub.add_parser("discover-openrouter", help="发现 OpenRouter :free 模型")
    discover_or.add_argument("--limit", type=int, default=20)
    discover_nv = sub.add_parser("discover-nvidia", help="发现 NVIDIA 当前 key 可见模型")
    discover_nv.add_argument("--limit", type=int, default=50)
    discover_groq = sub.add_parser("discover-groq", help="发现 Groq 当前 key 可见模型")
    discover_groq.add_argument("--limit", type=int, default=50)
    discover_ark = sub.add_parser("discover-ark", help="发现火山方舟当前 key 可见的模型 ID")
    discover_ark.add_argument("--limit", type=int, default=100)
    discover_vision = sub.add_parser("discover-vision", help="发现免费/试用视觉模型候选")
    discover_vision.add_argument("--limit", type=int, default=20)
    discover_or_vision = sub.add_parser("discover-openrouter-vision", help="发现 OpenRouter :free 视觉模型候选")
    discover_or_vision.add_argument("--limit", type=int, default=20)
    discover_nv_vision = sub.add_parser("discover-nvidia-vision", help="发现 NVIDIA 当前 key 可见视觉模型候选")
    discover_nv_vision.add_argument("--limit", type=int, default=50)

    maintain = sub.add_parser("maintain", help="自动发现免费模型并对整池做健康检查")
    maintain.add_argument("--include-paid", action="store_true", help="同时探活付费模型")
    maintain.add_argument("--timeout", type=float, default=6.0, help="单模型超时秒数")
    maintain.add_argument("--limit", type=int, default=0, help="最多发现/探活多少个模型，0 为全部")

    bench = sub.add_parser("benchmark", help="快速实测免费池模型表现")
    bench.add_argument("--timeout", type=float, default=8.0)
    bench.add_argument("--limit", type=int, default=12)
    vision_bench = sub.add_parser("benchmark-vision", help="快速实测免费视觉模型表现")
    vision_bench.add_argument("image", help="用于视觉 smoke 的本地图片")
    vision_bench.add_argument("--timeout", type=float, default=12.0)
    vision_bench.add_argument("--limit", type=int, default=8)

    task = sub.add_parser("task", help="执行一次路由调用")
    task.add_argument("prompt")
    task.add_argument("--task", choices=TASK_CHOICES, default="draft")
    task.add_argument("--context")
    task.add_argument("--context-file", help="从文件读取参考材料")
    task.add_argument("--image", help="本地图片路径；用于 vision 或支持图片的多模态任务")
    task.add_argument("--retrieve-dir", help="先从本地 txt/md 资料目录检索相关片段并注入 context")
    task.add_argument("--retrieve-limit", type=int, default=5)
    task.add_argument("--max-context-chars", type=int, default=0, help="本地裁剪 context 的最大字符数，0 为不裁剪")
    task.add_argument("--paid", action="store_true", help="付费优先，但仍按低价兜底排序")
    task.add_argument("--free-only", action="store_true", help="只允许免费模型，禁用付费兜底")
    task.add_argument("--provider", help="限定 provider 名、provider family 或 model family，如 qwen / qwen-free / nvidia")
    task.add_argument("--model", help="限定模型名，可为完整模型 ID 或其唯一子串")
    task.add_argument("--avoid-route", action="append", default=[], help="避开已使用路线 provider/model；可重复传入，用于多模型对照")
    task.add_argument("--preprocess", action="store_true", help="调用模型前先做本地端侧预处理/抽取式压缩；低价值输入可直接本地返回")
    task.add_argument("--preprocess-target-tokens", type=int, default=0, help="预处理压缩后的上下文目标 token；0 为自动")
    task.add_argument("--quality-target", choices=["draft", "production", "audit", "frontier"], default="production")
    task.add_argument("--privacy", choices=["auto", "local_only", "external_allowed"], default="auto")
    task.add_argument("--allow-external", action="store_true", help="确认允许把自动识别为敏感的输入发送到外部模型")
    task.add_argument("--max-cost-usd", type=float, help="单次调用预算上限；未知价格的付费模型会失败关闭")
    task.add_argument("--temperature", type=float, default=0.2)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = load_settings(args.env_file, args.credential_catalog)

    if args.command == "providers":
        print(json.dumps(describe_providers(settings), ensure_ascii=False, indent=2))
    elif args.command == "capabilities":
        print(json.dumps(capability_registry(settings, configured_only=args.configured_only), ensure_ascii=False, indent=2))
    elif args.command == "status":
        print(json.dumps(route_status(settings), ensure_ascii=False, indent=2))
    elif args.command == "ledger":
        print(json.dumps(read_cost_ledger(settings, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "route-stats":
        print(json.dumps(route_performance_stats(settings, task=args.task, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "golden-eval":
        print(
            json.dumps(
                run_golden_evaluation(
                    settings,
                    suite_path=args.suite_file,
                    candidate_provider=args.provider,
                    candidate_model=args.model,
                    baseline_provider=args.baseline_provider,
                    baseline_model=args.baseline_model,
                    output_dir=args.output_dir,
                    allow_paid=args.allow_paid,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "promotion-check":
        decision = build_promotion_decision(settings, report_path=args.report_file, review_path=args.review)
        output_path = args.output or str(Path(args.report_file).expanduser().resolve().parent / "promotion-decision.json")
        decision["artifact_path"] = str(write_promotion_decision(decision, output_path))
        print(json.dumps(decision, ensure_ascii=False, indent=2))
    elif args.command == "contract-plan":
        payload = json.loads(Path(args.contract_file).read_text(encoding="utf-8"))
        validated = validate_task_contract(payload)
        receipt = make_route_receipt(
            contract=validated,
            mode="dry_run",
            selected_provider=None,
            selected_model=None,
            cost_class="unselected",
            paid_fallback_used=False,
            decision_reasons=["task contract validated", "execution route not selected in dry-run mode"],
        )
        if args.receipt_dir:
            receipt["receipt_path"] = str(write_route_receipt(receipt, args.receipt_dir))
        print(json.dumps({"contract": validated, "receipt": receipt}, ensure_ascii=False, indent=2))
    elif args.command == "workflow-plan":
        payload = json.loads(Path(args.contract_file).read_text(encoding="utf-8"))
        result = build_workflow_plan(settings, payload)
        if args.output_dir:
            result["artifact_path"] = str(write_workflow_artifact(result, args.output_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "workflow-check":
        contract_payload = json.loads(Path(args.contract_file).read_text(encoding="utf-8"))
        checkpoint_payload = json.loads(Path(args.checkpoint_file).read_text(encoding="utf-8"))
        result = evaluate_workflow_checkpoint(contract_payload, checkpoint_payload)
        if args.output_dir:
            result["artifact_path"] = str(write_workflow_artifact(result, args.output_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "score":
        print(json.dumps(score_task_complexity(args.task, args.prompt, args.context), ensure_ascii=False, indent=2))
    elif args.command == "preprocess":
        context = args.context
        if args.context_file:
            with open(args.context_file, encoding="utf-8") as handle:
                context = handle.read()
        print(json.dumps(preprocess_input(task=args.task, prompt=args.prompt, context=context, target_tokens=args.target_tokens), ensure_ascii=False, indent=2))
    elif args.command == "recommend":
        print(json.dumps(recommend_route(settings, task=args.task, prompt=args.prompt, context=args.context, prefer_free=not args.paid, paid_fallback=not args.free_only, quality_target=args.quality_target, max_cost_usd=args.max_cost_usd), ensure_ascii=False, indent=2))
    elif args.command == "route-plan":
        context = args.context
        if args.context_file:
            with open(args.context_file, encoding="utf-8") as handle:
                context = handle.read()
        input_modalities = [item.strip() for item in args.input_modalities.split(",") if item.strip()] or None
        output_modalities = [item.strip() for item in args.output_modalities.split(",") if item.strip()] or None
        print(
            json.dumps(
                route_plan(
                    settings,
                    task=args.task,
                    prompt=args.prompt,
                    context=context,
                    input_modalities=input_modalities,
                    output_modalities=output_modalities,
                    domain=args.domain,
                    quality_target=args.quality_target,
                    risk=args.risk,
                    paid_allowed=args.paid_allowed,
                    prefer_free=not args.paid,
                    limit=args.limit,
                    privacy=args.privacy,
                    max_cost_usd=args.max_cost_usd,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "asr-status":
        print(json.dumps(asr_status(settings), ensure_ascii=False, indent=2))
    elif args.command == "transcribe":
        print(json.dumps(transcribe_media(settings, args.input_file, output_dir=args.output_dir, backend=args.backend, language=args.language, model=args.model, keep_audio=args.keep_audio), ensure_ascii=False, indent=2))
    elif args.command == "remote-transcribe":
        print(json.dumps(remote_transcribe_media(settings, args.input_file, provider=args.provider, model=args.model, language=args.language, allow_external=args.allow_external, timeout=args.timeout), ensure_ascii=False, indent=2))
    elif args.command == "transcript-correct":
        print(
            json.dumps(
                transcript_correct(
                    settings,
                    args.input_file,
                    output_dir=args.output_dir,
                    domain=args.domain,
                    chunk_chars=args.chunk_chars,
                    free_only=args.free_only,
                    prefer_free=not args.paid_main,
                    cross_check=args.cross_check,
                    quality_target=args.quality_target,
                    max_context_chars=args.max_context_chars,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "embed":
        texts = list(args.texts or [])
        if args.input_file:
            with open(args.input_file, encoding="utf-8") as handle:
                raw = handle.read()
            texts.extend([line.strip() for line in raw.splitlines() if line.strip()] if args.split_lines else [raw.strip()])
        texts = [text for text in texts if text]
        if not texts:
            parser.error("embed 需要至少一条文本，或使用 --input-file")
        result = embed_texts(settings, texts, provider=args.provider, model=args.model, dimensions=args.dimensions, timeout=args.timeout)
        if not args.full:
            compact = {key: value for key, value in result.items() if key != "data"}
            compact["data"] = [
                {"index": item["index"], "dimensions": item["dimensions"], "embedding_preview": item["embedding"][:8]}
                for item in result.get("data", [])
            ]
            result = compact
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "rerank":
        documents = list(args.documents or [])
        if args.documents_file:
            with open(args.documents_file, encoding="utf-8") as handle:
                documents.extend([line.strip() for line in handle.read().splitlines() if line.strip()])
        documents = [doc for doc in documents if doc]
        if not documents:
            parser.error("rerank 需要至少一条候选文本，或使用 --documents-file")
        print(json.dumps(rerank_documents(settings, query=args.query, documents=documents, provider=args.provider, model=args.model, top_n=args.top_n, return_raw_scores=args.return_raw_scores, timeout=args.timeout), ensure_ascii=False, indent=2))
    elif args.command == "image-generate":
        print(json.dumps(generate_image(settings, args.prompt, provider=args.provider, model=args.model, size=args.size, quality=args.quality, allow_paid=args.allow_paid, timeout=args.timeout), ensure_ascii=False, indent=2))
    elif args.command == "clear":
        clear_route_state(settings)
        print("模型冷却状态已清空。")
    elif args.command == "refresh":
        print(json.dumps(refresh_model_pool(settings, include_paid=args.include_paid, timeout=args.timeout, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "refresh-modalities":
        tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
        families = [item.strip() for item in args.families.split(",") if item.strip()]
        print(json.dumps(refresh_model_pool_by_modality(settings, include_paid=args.include_paid, timeout=args.timeout, limit=args.limit, tasks=tasks, families=families), ensure_ascii=False, indent=2))
    elif args.command == "discover":
        print(json.dumps(discover_free_pool(settings, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-openrouter":
        print(json.dumps(discover_openrouter_free(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-nvidia":
        print(json.dumps(discover_nvidia_models(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-groq":
        print(json.dumps(discover_groq_models(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-ark":
        print(json.dumps(discover_ark_models(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-vision":
        print(json.dumps(discover_vision_pool(settings, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-openrouter-vision":
        print(json.dumps(discover_openrouter_vision_free(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "discover-nvidia-vision":
        print(json.dumps(discover_nvidia_vision_models(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "maintain":
        print(json.dumps(maintain_pool(settings, include_paid=args.include_paid, timeout=args.timeout, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "benchmark":
        print(json.dumps(quick_benchmark(settings, timeout=args.timeout, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "benchmark-vision":
        print(json.dumps(quick_vision_benchmark(settings, args.image, timeout=args.timeout, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "task":
        context = args.context
        if args.context_file:
            with open(args.context_file, encoding="utf-8") as handle:
                context = handle.read()
        if args.retrieve_dir:
            retrieved = retrieve_local_context(args.retrieve_dir, args.prompt + "\n" + (context or ""), limit=args.retrieve_limit, max_chars=args.max_context_chars or 6000)
            context = retrieved if not context else retrieved + "\n\n---\n\n" + context
        result = run_llm_task(
            settings,
            task=args.task,
            prompt=args.prompt,
            context=context,
            prefer_free=not args.paid,
            paid_fallback=not args.free_only,
            temperature=args.temperature,
            max_context_chars=args.max_context_chars or None,
            image_path=args.image,
            provider=args.provider,
            model=args.model,
            avoid_routes=args.avoid_route,
            preprocess=args.preprocess,
            preprocess_target_tokens=args.preprocess_target_tokens,
            quality_target=args.quality_target,
            privacy=args.privacy,
            allow_external=args.allow_external,
            max_cost_usd=args.max_cost_usd,
        )
        cached = " cached" if result.cached else ""
        complexity = f" complexity={result.complexity}" if result.complexity else ""
        ledger_id = f" ledger={result.ledger_id}" if result.ledger_id else ""
        print(f"模型：{result.provider}/{result.model}{cached}{complexity}{ledger_id}")
        print(result.content)
    else:
        parser.error(f"未知命令：{args.command}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from None
