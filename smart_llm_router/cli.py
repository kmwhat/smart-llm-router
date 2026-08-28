from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__

from .config import load_settings
from .controls import build_control_preflight
from .evaluation import build_promotion_decision, run_golden_evaluation, write_promotion_decision
from .governance import (
    build_workflow_plan,
    evaluate_workflow_checkpoint,
    make_route_receipt,
    validate_task_contract,
    write_route_receipt,
    write_workflow_artifact,
)
from .lifecycle import evaluate_adapter_transition, persist_adapter_transition, write_adapter_transition_receipt
from .router import (
    TASK_TYPES,
    capability_registry,
    clear_route_state,
    credential_status,
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
    router_doctor,
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
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="查看 provider 配置摘要，不输出 key")
    doctor = sub.add_parser("doctor", help="离线检查配置、免费池、角色覆盖和被排除原因；不调用模型")
    doctor.add_argument("--quality-target", choices=["draft", "production", "audit", "frontier"], default="production")
    doctor.add_argument("--paid-allowed", action="store_true", help="只在诊断中展示可用付费路线，不执行调用")
    doctor.add_argument("--max-cost-usd", type=float, help="诊断每阶段预算门；不会发起付费调用")
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
    golden_eval.add_argument("--allow-unprotected-trial", action="store_true", help="显式允许黄金集消耗尚未声明硬停保护的试用额度；不会令其自动晋级")

    promotion = sub.add_parser("promotion-check", help="本地检查黄金集、健康、成本和独立盲审证据；不自动修改生产角色表")
    promotion.add_argument("report_file")
    promotion.add_argument("--review", help="独立盲审结果 JSON")
    promotion.add_argument("--output", help="晋级判定落盘路径；默认写到 report 同目录的 promotion-decision.json")

    lifecycle = sub.add_parser("adapter-lifecycle", help="本地评估适配器状态迁移并生成回执；不自动修改注册表")
    lifecycle.add_argument("adapter_file", help="适配器声明 JSON")
    lifecycle.add_argument("transition_file", help="状态迁移请求 JSON")
    lifecycle.add_argument("--promotion-decision", help="qualified/production 必需的 promotion decision JSON")
    lifecycle.add_argument("--output", help="迁移回执落盘路径；省略时仅输出 stdout")
    lifecycle.add_argument("--state-dir", help="显式指定私有运行态目录；PASS 时更新声明并保存回执")

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
    remote_asr.add_argument("--allow-paid", action="store_true", help="显式授权调用可能计费的远程 ASR 路线")

    correct = sub.add_parser("transcript-correct", help="长篇 ASR 转写稿分块纠错，并落盘 corrected/report")
    correct.add_argument("input_file")
    correct.add_argument("--output-dir")
    correct.add_argument("--domain", default="general", help="转写内容所属领域或主题，例如 software、finance、general")
    correct.add_argument("--chunk-chars", type=int, default=3500)
    correct.add_argument("--free-only", action="store_true", help="只允许免费模型；这是默认行为")
    correct.add_argument("--paid-main", action="store_true", help="显式授权主修正使用付费模型")
    correct.add_argument("--max-cost-usd", type=float, help="付费主修正每个分块的成本硬上限")
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
    embed.add_argument("--allow-paid", action="store_true", help="显式授权调用付费 embedding adapter")

    rerank = sub.add_parser("rerank", help="专用文本重排序 adapter，不走 chat/completions")
    rerank.add_argument("documents", nargs="*", help="候选文本；也可用 --documents-file")
    rerank.add_argument("--query", required=True, help="查询文本")
    rerank.add_argument("--documents-file", help="从文件按非空行读取候选文本")
    rerank.add_argument("--provider", help="限定 provider 名或 family，如 zhipu")
    rerank.add_argument("--model", help="限定模型，如 rerank")
    rerank.add_argument("--top-n", type=int, default=0, help="只返回前 N 条；0 为返回全部")
    rerank.add_argument("--return-raw-scores", action="store_true", help="请求返回 raw scores")
    rerank.add_argument("--timeout", type=float, help="单请求超时秒数")
    rerank.add_argument("--allow-paid", action="store_true", help="显式授权调用付费 rerank adapter")

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
    refresh.add_argument("--task", choices=TASK_CHOICES, default="qa", help="按任务或角色限定探活池")
    refresh.add_argument("--quality-target", choices=["draft", "production", "audit", "frontier"], default="production")
    refresh.add_argument("--include-unprotected-trial", action="store_true", help="显式探测尚未声明硬停保护的试用额度路线；只用于审计，不会令其进入生产执行")
    refresh.add_argument("--no-progress", action="store_true", help="不在 stderr 输出逐模型进度；最终 JSON 仍写 stdout")
    refresh_modalities = sub.add_parser("refresh-modalities", help="按任务/模态探活模型池，更新冷却状态并写入模态报告")
    refresh_modalities.add_argument("--include-paid", action="store_true", help="同时探活付费模型")
    refresh_modalities.add_argument("--timeout", type=float, default=6.0, help="单模型超时秒数")
    refresh_modalities.add_argument("--limit", type=int, default=0, help="每个任务最多探活多少个模型，0 为全部")
    refresh_modalities.add_argument("--tasks", default="qa,vision,ocr,transcript_correct,code", help="逗号分隔任务，如 qa,vision,ocr,transcript_correct,code")
    refresh_modalities.add_argument("--families", default="", help="只探测指定 provider/model family，逗号分隔，如 zhipu,qwen,deepseek")
    refresh_modalities.add_argument("--include-unprotected-trial", action="store_true", help="显式探测尚未声明硬停保护的试用额度路线")

    credential_check = sub.add_parser("credential-status", help="只检查免费远端凭证认证状态；不调用模型、不输出 key")
    credential_check.add_argument("--families", default="openrouter,qwen,nvidia,groq", help="逗号分隔 family，仅支持 openrouter,qwen,nvidia,groq")
    credential_check.add_argument("--timeout", type=float, default=10.0, help="单个凭证认证探针超时秒数")

    discover = sub.add_parser("discover", help="聚合发现 OpenRouter/NVIDIA/Groq 候选模型")
    discover.add_argument("--limit", type=int, default=20)
    discover_or = sub.add_parser("discover-openrouter", help="从 OpenRouter 公共目录发现 :free 候选；不验证凭证")
    discover_or.add_argument("--limit", type=int, default=20)
    discover_nv = sub.add_parser("discover-nvidia", help="从 NVIDIA 公共目录发现候选；不验证凭证")
    discover_nv.add_argument("--limit", type=int, default=50)
    discover_groq = sub.add_parser("discover-groq", help="通过 Groq 认证目录发现候选；仍需真实调用验证")
    discover_groq.add_argument("--limit", type=int, default=50)
    discover_ark = sub.add_parser("discover-ark", help="发现火山方舟当前 key 可见的模型 ID")
    discover_ark.add_argument("--limit", type=int, default=100)
    discover_vision = sub.add_parser("discover-vision", help="发现免费/试用视觉模型候选")
    discover_vision.add_argument("--limit", type=int, default=20)
    discover_or_vision = sub.add_parser("discover-openrouter-vision", help="从 OpenRouter 公共目录发现 :free 视觉候选；不验证凭证")
    discover_or_vision.add_argument("--limit", type=int, default=20)
    discover_nv_vision = sub.add_parser("discover-nvidia-vision", help="从 NVIDIA 公共目录发现视觉候选；不验证凭证")
    discover_nv_vision.add_argument("--limit", type=int, default=50)

    maintain = sub.add_parser("maintain", help="自动发现免费模型并对整池做健康检查")
    maintain.add_argument("--include-paid", action="store_true", help="同时探活付费模型")
    maintain.add_argument("--timeout", type=float, default=6.0, help="单模型超时秒数")
    maintain.add_argument("--limit", type=int, default=0, help="最多发现/探活多少个模型，0 为全部")

    bench = sub.add_parser("benchmark", help="快速实测免费池模型表现")
    bench.add_argument("--timeout", type=float, default=8.0)
    bench.add_argument("--limit", type=int, default=12)
    bench.add_argument("--include-unprotected-trial", action="store_true", help="显式允许审计未声明硬停保护的试用额度路线")
    vision_bench = sub.add_parser("benchmark-vision", help="快速实测免费视觉模型表现")
    vision_bench.add_argument("image", help="用于视觉 smoke 的本地图片")
    vision_bench.add_argument("--timeout", type=float, default=12.0)
    vision_bench.add_argument("--limit", type=int, default=8)
    vision_bench.add_argument("--include-unprotected-trial", action="store_true", help="显式允许审计未声明硬停保护的试用额度路线")

    task = sub.add_parser("task", help="执行一次路由调用")
    task.add_argument("prompt")
    task.add_argument("--task", choices=TASK_CHOICES, default="draft")
    task.add_argument("--context")
    task.add_argument("--context-file", help="从文件读取参考材料")
    task.add_argument("--json-schema-file", help="读取显式 JSON Schema；仅受支持的 provider-native 路线可执行")
    task.add_argument("--image", help="本地图片路径；用于 vision 或支持图片的多模态任务")
    task.add_argument("--retrieve-dir", help="先从本地 txt/md 资料目录检索相关片段并注入 context")
    task.add_argument("--retrieve-limit", type=int, default=5)
    task.add_argument("--max-context-chars", type=int, default=0, help="本地裁剪 context 的最大字符数，0 为不裁剪")
    task.add_argument("--paid", action="store_true", help="显式授权付费路线；同时必须设置 --max-cost-usd")
    task.add_argument("--free-only", action="store_true", help="只允许免费模型；这是默认行为")
    task.add_argument("--provider", help="限定 provider 名、provider family 或 model family，如 qwen / qwen-free / nvidia")
    task.add_argument("--model", help="限定模型名，可为完整模型 ID 或其唯一子串")
    task.add_argument("--avoid-route", action="append", default=[], help="避开已使用路线 provider/model；可重复传入，用于多模型对照")
    task.add_argument("--preprocess", action="store_true", help="调用模型前先做本地端侧预处理/抽取式压缩；低价值输入可直接本地返回")
    task.add_argument("--preprocess-target-tokens", type=int, default=0, help="预处理压缩后的上下文目标 token；0 为自动")
    task.add_argument("--quality-target", choices=["draft", "production", "audit", "frontier"], default="production")
    task.add_argument("--privacy", choices=["auto", "local_only", "external_allowed"], default="auto")
    task.add_argument("--allow-external", action="store_true", help="确认允许把自动识别为敏感的输入发送到外部模型")
    task.add_argument("--max-cost-usd", type=float, help="单次调用预算上限；未知价格的付费模型会失败关闭")
    task.add_argument("--input-token-guard-factor", type=float, help="提高本地输入 token 预算预留系数；不得低于内置安全下限")
    task.add_argument("--max-output-tokens", type=int, help="限制本次模型最终输出长度；免费与付费路线都生效")
    task.add_argument("--thinking-mode", choices=["auto", "enabled", "disabled"], default="auto", help="Qwen/DeepSeek 混合思考控制")
    task.add_argument("--thinking-budget-tokens", type=int, help="Qwen reasoning token 硬上限")
    task.add_argument("--final-answer-reserve-tokens", type=int, help="为最终正文单独预留的 token")
    task.add_argument("--no-think", action="store_true", help="等价于 --thinking-mode disabled；也支持 prompt 中的 /no_think")
    task.add_argument("--strict-controls", action="store_true", help="治理调用在路由、预留和发送前严格校验 SMART_LLM 控制变量")
    task.add_argument("--openrouter-upstream-provider", action="append", default=[], help="按 OpenRouter provider slug 限定上游承载方；可重复")
    task.add_argument("--openrouter-no-fallbacks", action="store_true", help="禁止 OpenRouter 在上游 provider 之间隐式回退")
    task.add_argument("--openrouter-require-zdr", action="store_true", help="要求 OpenRouter 仅路由到零数据保留 endpoint")
    task.add_argument("--openrouter-deny-data-collection", action="store_true", help="要求 OpenRouter 排除会收集/训练输入的 provider")
    task.add_argument("--no-cache", action="store_true", help="显式禁用本次请求的响应缓存读取与写入")
    task.add_argument("--workflow-id", help="跨调用累计预算的工作流 ID")
    task.add_argument("--workflow-max-cost-usd", type=float, help="工作流累计成本硬上限")
    task.add_argument("--workflow-stage", help="本次调用的工作流阶段名")
    task.add_argument("--timeout", type=float, help="本次单模型超时秒数；省略时使用全局设置")
    task.add_argument("--temperature", type=float, default=0.2)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "task":
        if args.paid and args.free_only:
            parser.error("task 不能同时使用 --paid 和 --free-only")
        if args.paid and args.max_cost_usd is None:
            parser.error("task 使用 --paid 时必须同时设置 --max-cost-usd")
        if args.max_cost_usd is not None and (not math.isfinite(args.max_cost_usd) or args.max_cost_usd < 0):
            parser.error("task 的 --max-cost-usd 必须为有限非负数")
        if bool(args.workflow_id) != (args.workflow_max_cost_usd is not None):
            parser.error("task 的 --workflow-id 和 --workflow-max-cost-usd 必须同时设置")
        if args.workflow_id and args.max_cost_usd is None:
            parser.error("工作流预算调用必须同时设置 --max-cost-usd")
        if args.workflow_max_cost_usd is not None and (
            not math.isfinite(args.workflow_max_cost_usd) or args.workflow_max_cost_usd <= 0
        ):
            parser.error("task 的 --workflow-max-cost-usd 必须为有限正数")
        if args.no_think and args.thinking_mode == "enabled":
            parser.error("task 不能同时使用 --no-think 和 --thinking-mode enabled")
        # Governed callers must reject unsupported controls before loading
        # provider configuration, selecting a route, reserving budget, or
        # sending a request. The returned object is rebuilt inside
        # run_llm_task so programmatic callers receive the same protection.
        build_control_preflight(
            strict_controls=args.strict_controls,
            explicit_cache_enabled=False if args.no_cache else None,
        )
    if args.command == "transcript-correct":
        if args.paid_main and args.free_only:
            parser.error("transcript-correct 不能同时使用 --paid-main 和 --free-only")
        if args.paid_main and args.max_cost_usd is None:
            parser.error("transcript-correct 使用 --paid-main 时必须同时设置 --max-cost-usd")
    settings = load_settings(args.env_file, args.credential_catalog)

    if args.command == "providers":
        print(json.dumps(describe_providers(settings), ensure_ascii=False, indent=2))
    elif args.command == "doctor":
        print(json.dumps(router_doctor(settings, quality_target=args.quality_target, paid_allowed=args.paid_allowed, max_cost_usd=args.max_cost_usd), ensure_ascii=False, indent=2))
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
                    allow_unprotected_trial=args.allow_unprotected_trial,
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
    elif args.command == "adapter-lifecycle":
        adapter = json.loads(Path(args.adapter_file).read_text(encoding="utf-8"))
        transition = json.loads(Path(args.transition_file).read_text(encoding="utf-8"))
        promotion_decision = (
            json.loads(Path(args.promotion_decision).read_text(encoding="utf-8"))
            if args.promotion_decision
            else None
        )
        receipt = evaluate_adapter_transition(adapter, transition, promotion_decision=promotion_decision)
        if args.state_dir:
            receipt["runtime_state"] = persist_adapter_transition(adapter, receipt, args.state_dir)
        if args.output:
            receipt["artifact_path"] = str(write_adapter_transition_receipt(receipt, args.output))
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
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
        print(json.dumps(remote_transcribe_media(settings, args.input_file, provider=args.provider, model=args.model, language=args.language, allow_external=args.allow_external, allow_paid=args.allow_paid, timeout=args.timeout), ensure_ascii=False, indent=2))
    elif args.command == "transcript-correct":
        print(
            json.dumps(
                transcript_correct(
                    settings,
                    args.input_file,
                    output_dir=args.output_dir,
                    domain=args.domain,
                    chunk_chars=args.chunk_chars,
                    free_only=not args.paid_main,
                    prefer_free=not args.paid_main,
                    cross_check=args.cross_check,
                    quality_target=args.quality_target,
                    max_context_chars=args.max_context_chars,
                    max_cost_usd=args.max_cost_usd,
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
        result = embed_texts(settings, texts, provider=args.provider, model=args.model, dimensions=args.dimensions, timeout=args.timeout, allow_paid=args.allow_paid)
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
        print(json.dumps(rerank_documents(settings, query=args.query, documents=documents, provider=args.provider, model=args.model, top_n=args.top_n, return_raw_scores=args.return_raw_scores, timeout=args.timeout, allow_paid=args.allow_paid), ensure_ascii=False, indent=2))
    elif args.command == "image-generate":
        print(json.dumps(generate_image(settings, args.prompt, provider=args.provider, model=args.model, size=args.size, quality=args.quality, allow_paid=args.allow_paid, timeout=args.timeout), ensure_ascii=False, indent=2))
    elif args.command == "clear":
        clear_route_state(settings)
        print("模型冷却状态已清空。")
    elif args.command == "refresh":
        progress = None if args.no_progress else lambda row: print(json.dumps(row, ensure_ascii=False), file=sys.stderr, flush=True)
        print(json.dumps(refresh_model_pool(settings, include_paid=args.include_paid, timeout=args.timeout, limit=args.limit, task=args.task, quality_target=args.quality_target, include_unprotected_trial=args.include_unprotected_trial, progress=progress), ensure_ascii=False, indent=2))
    elif args.command == "refresh-modalities":
        tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
        families = [item.strip() for item in args.families.split(",") if item.strip()]
        print(json.dumps(refresh_model_pool_by_modality(settings, include_paid=args.include_paid, timeout=args.timeout, limit=args.limit, tasks=tasks, families=families, include_unprotected_trial=args.include_unprotected_trial), ensure_ascii=False, indent=2))
    elif args.command == "credential-status":
        families = [item.strip() for item in args.families.split(",") if item.strip()]
        print(json.dumps(credential_status(settings, families=families, timeout=args.timeout), ensure_ascii=False, indent=2))
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
        print(json.dumps(quick_benchmark(settings, timeout=args.timeout, limit=args.limit, include_unprotected_trial=args.include_unprotected_trial), ensure_ascii=False, indent=2))
    elif args.command == "benchmark-vision":
        print(json.dumps(quick_vision_benchmark(settings, args.image, timeout=args.timeout, limit=args.limit, include_unprotected_trial=args.include_unprotected_trial), ensure_ascii=False, indent=2))
    elif args.command == "task":
        context = args.context
        structured_output_schema = None
        if args.json_schema_file:
            try:
                structured_output_schema = json.loads(
                    Path(args.json_schema_file).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                parser.error(f"无法读取有效的 --json-schema-file：{exc}")
            if not isinstance(structured_output_schema, dict):
                parser.error("--json-schema-file 根节点必须是 JSON object")
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
            paid_fallback=args.paid,
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
            max_output_tokens=args.max_output_tokens,
            thinking_mode="disabled" if args.no_think else args.thinking_mode,
            thinking_budget_tokens=args.thinking_budget_tokens,
            final_answer_reserve_tokens=args.final_answer_reserve_tokens,
            structured_output_schema=structured_output_schema,
            workflow_id=args.workflow_id,
            workflow_max_cost_usd=args.workflow_max_cost_usd,
            workflow_stage=args.workflow_stage,
            request_timeout=args.timeout,
            strict_controls=args.strict_controls,
            cache_enabled=False if args.no_cache else None,
            input_token_guard_factor=args.input_token_guard_factor,
            openrouter_upstream_providers=args.openrouter_upstream_provider,
            openrouter_allow_fallbacks=not args.openrouter_no_fallbacks,
            openrouter_require_zdr=args.openrouter_require_zdr,
            openrouter_deny_data_collection=args.openrouter_deny_data_collection,
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
