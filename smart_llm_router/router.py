from __future__ import annotations

import json
import base64
import importlib.util
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .budget import (
    BudgetLimitExceeded,
    BudgetReservation,
    budget_authority_id,
    finalize_workflow_reservation,
    release_workflow_reservation,
    reserve_workflow_budget,
    write_budget_incident,
    write_budget_warning,
)
from .config import LLMProvider, Settings
from .controls import build_control_preflight


DEFAULT_TASK_ORDER = {
    "plan": [
        "qwen-frontier-paid",
        "doubao-frontier-paid",
        "kimi-frontier-paid",
        "zhipu-glm-lowcost",
        "deepseek-direct-paid",
        "gemini-frontier-paid",
    ],
    "research_enhance": [
        "qwen-frontier-paid",
        "kimi-frontier-paid",
        "zhipu-glm-lowcost",
        "gemini-frontier-paid",
        "deepseek-direct-paid",
    ],
    "plan_audit": [
        "deepseek-direct-paid",
        "nvidia-free",
        "nvidia-free-key2",
        "kimi-frontier-paid",
        "zhipu-glm-lowcost",
        "gemini-frontier-paid",
        "qwen-frontier-paid",
    ],
    "execute": [
        "zhipu-glm-lowcost",
        "doubao-frontier-paid",
        "deepseek-direct-paid",
        "qwen-frontier-paid",
        "kimi-frontier-paid",
        "gemini-frontier-paid",
    ],
    "clean": [
        "qwen-free",
        "nvidia-google-free",
        "nvidia-free",
        "doubao-free",
        "openrouter-deepseek-free",
        "openrouter-router-free",
        "groq-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "gemini-paid",
    ],
    "summarize": [
        "qwen-free",
        "nvidia-free",
        "nvidia-google-free",
        "doubao-free",
        "openrouter-deepseek-free",
        "openrouter-router-free",
        "groq-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "gemini-paid",
    ],
    "classify": [
        "openrouter-deepseek-free",
        "nvidia-free",
        "qwen-free",
        "doubao-free",
        "nvidia-google-free",
        "openrouter-router-free",
        "groq-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "gemini-paid",
    ],
    "qa": [
        "nvidia-free",
        "openrouter-deepseek-free",
        "qwen-free",
        "nvidia-google-free",
        "doubao-free",
        "openrouter-router-free",
        "groq-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "gemini-paid",
    ],
    "draft": [
        "nvidia-free",
        "nvidia-google-free",
        "qwen-free",
        "openrouter-deepseek-free",
        "doubao-free",
        "openrouter-router-free",
        "groq-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "gemini-paid",
    ],
    "vision": [
        "nvidia-vision-free",
        "openrouter-vision-free",
        "openrouter-google-free",
        "qwen-vision-lowcost",
        "zhipu-vision-lowcost",
        "gemini-paid",
    ],
    "ocr": [
        "nvidia-vision-free",
        "openrouter-vision-free",
        "openrouter-google-free",
        "qwen-vision-lowcost",
        "zhipu-vision-lowcost",
        "gemini-paid",
    ],
    "transcript_correct": [
        "qwen-free",
        "nvidia-free",
        "nvidia-google-free",
        "openrouter-router-free",
        "groq-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "zhipu-glm-lowcost",
        "gemini-paid",
    ],
    "audit": [
        "qwen-free",
        "nvidia-free",
        "openrouter-router-free",
        "openrouter-google-free",
        "openrouter-deepseek-fallback",
        "zhipu-glm-lowcost",
        "gemini-paid",
    ],
    "verify": [
        "gemini-frontier-paid",
        "doubao-frontier-paid",
        "qwen-frontier-paid",
        "deepseek-direct-paid",
        "zhipu-glm-lowcost",
        "kimi-frontier-paid",
    ],
    "quality_enhance": [
        "kimi-frontier-paid",
        "qwen-frontier-paid",
        "doubao-frontier-paid",
        "zhipu-glm-lowcost",
        "gemini-frontier-paid",
        "deepseek-direct-paid",
    ],
    "code": [
        "openrouter-router-free",
        "nvidia-free",
        "qwen-free",
        "groq-free",
        "openrouter-deepseek-fallback",
        "zhipu-glm-lowcost",
        "gemini-paid",
    ],
    "asr": [],
    "embed": ["qwen-embedding-lowcost", "zhipu-embedding-lowcost"],
    "rerank": ["zhipu-rerank-lowcost"],
    "image_generate": [],
}

PAID_FALLBACK_ORDER = [
    "deepseek-direct-paid",
    "minimax-frontier-paid",
    "openrouter-deepseek-fallback",
    "zhipu-glm-lowcost",
    "qwen-frontier-paid",
    "doubao-frontier-paid",
    "doubao-ark-paid",
    "kimi-frontier-paid",
    "qwen-vision-lowcost",
    "zhipu-vision-lowcost",
    "gemini-frontier-paid",
    "gemini-paid",
]
TASK_TYPES = tuple(DEFAULT_TASK_ORDER)
DEFAULT_MODALITY_HEALTH_TASKS = ("qa", "vision", "ocr", "transcript_correct", "code", "embed", "rerank")

SYSTEM_PROMPTS = {
    "plan": "你是资深规划与架构助手。先澄清目标、约束和验收标准，再给出分阶段方案、关键取舍、风险与回退路径；不要替执行阶段虚构结果。",
    "research_enhance": "你是研究增强助手。只依据带来源和日期的研究证据提出增量修改，逐项说明证据、变化和不采纳理由；不要黑箱重写已经确认的规划。",
    "plan_audit": "你是独立规划挑战审计助手。不要沿用规划或研究增强模型的结论；从原始目标、验收标准、风险、成本和可执行性重新挑错，并区分局部整改与必须重新设计。",
    "execute": "你是资深执行助手。严格按既定目标和约束完成工作，保持最小必要改动，给出可验证产物、测试证据和未解决风险。",
    "draft": "你是一线草稿助手。输出结构化、可复核的初稿，不夸大，不编造。",
    "classify": "你是资料分类助手。优先输出简洁 JSON。",
    "summarize": "你是资料摘要助手。保留术语、出处线索和关键词。",
    "clean": "你是 OCR 文本清洗助手。修正常见错字、断行和页眉页脚，保留原意。",
    "qa": "你是准确简洁的初级问答助手。优先遵守用户明确的输出格式；提供材料时仅依据材料回答，确实无法判断时说不确定。",
    "vision": "你是保守的图像观察助手。只描述图中可见事实，输出结构化 JSON，不做医学诊断、身份识别或确定性预测。",
    "ocr": "你是保守的图像/OCR 观察助手。只提取图中可见文字和版面事实，不补写看不清的内容。",
    "transcript_correct": "你是中文 ASR 转写稿修正助手。只修正口误、同音错字、术语误识别、重复噪声和断句；保持讲者原有顺序、论证链和案例逻辑；不确定处标【待复核】，不要编造。",
    "audit": "你是严格审校助手。检查遗漏、术语错误、结构问题和不可靠推断，输出可执行问题清单。",
    "verify": "你是独立复验助手。不要沿用主模型的结论；从原始目标、输入和证据重新核对，明确通过项、失败项、差异和置信度。",
    "quality_enhance": "你是最终质量提升助手。在不改变事实和边界的前提下，消除遗漏与歧义，提升结构、表达和可执行性，并列明实质改动。",
    "code": "你是代码辅助助手。优先给出可验证、最小改动、风险清楚的建议。",
}

TEXT_TASKS = {"plan", "research_enhance", "plan_audit", "execute", "draft", "classify", "summarize", "clean", "qa", "transcript_correct", "audit", "verify", "quality_enhance", "code"}
VISION_TASKS = {"vision", "ocr"}
LOCAL_ONLY_TASKS = {"asr"}
SPECIALIZED_TASKS = {"image_generate", "video_generate", "tts"}
ROLE_TASKS = {"plan", "research_enhance", "plan_audit", "execute", "audit", "verify", "quality_enhance"}
QUALITY_TARGETS = {"draft", "production", "audit", "frontier"}
ROLE_MIN_QUALITY_BANDS = {
    "draft": 2,
    "production": 3,
    "audit": 4,
    "frontier": 4,
}
ROUTE_HEALTH_MIN_SAMPLES = 3

# Within each role, model order is intentional. Provider priority remains the
# tie-breaker, and environment price overrides still control the budget gate.
ROLE_MODEL_ORDER: dict[str, tuple[str, ...]] = {
    "plan": ("qwen3.7-max", "doubao-seed-2-1-pro", "kimi-k3", "glm-5.2", "deepseek-v4-pro", "gemini-3.1-pro-preview", "gemini-2.5-pro", "doubao-seed-2-0-pro-260215"),
    "research_enhance": ("qwen3.7-max", "kimi-k3", "glm-5.2", "gemini-3.1-pro-preview", "gemini-2.5-pro", "deepseek-v4-pro"),
    "plan_audit": ("deepseek-v4-flash", "deepseek-v4-pro", "kimi-k3", "glm-5.2", "gemini-3.1-pro-preview", "gemini-2.5-pro", "qwen3.7-max"),
    "execute": ("glm-5.2", "doubao-seed-2-0-code-preview-260215", "doubao-seed-2-1-pro", "deepseek-v4-pro", "qwen3.7-plus", "qwen3.7-max", "kimi-k3", "gemini-2.5-pro", "doubao-seed-2-0-pro-260215"),
    "audit": ("gemini-2.5-pro", "gemini-3.1-pro-preview", "qwen3.7-max", "doubao-seed-2-1-pro", "deepseek-v4-pro", "glm-5.2", "kimi-k3", "doubao-seed-2-0-pro-260215"),
    "verify": ("deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-max", "kimi-k3", "glm-5.2", "gemini-2.5-pro", "gemini-3.1-pro-preview", "doubao-seed-2-1-pro", "doubao-seed-2-0-pro-260215", "openai/gpt-oss-120b"),
    "quality_enhance": ("kimi-k3", "qwen3.7-max", "doubao-seed-2-1-pro", "glm-5.2", "gemini-2.5-pro", "deepseek-v4-pro", "doubao-seed-2-0-pro-260215"),
}

# Bands express role fit, not a universal benchmark score. The requested
# quality target determines the minimum capability floor. Among routes that
# clear the same floor, compare expected total cost after reliability rather
# than treating "free" as a separate quality-independent preference.
ROLE_QUALITY_BANDS: dict[str, dict[str, int]] = {
    "plan": {
        "qwen3.7-max": 4,
        "kimi-k3": 4,
        "doubao-seed-2-1-pro": 4,
        "gemini-3.1-pro-preview": 4,
        "glm-5.2": 3,
        "deepseek-v4-pro": 3,
        "gemini-2.5-pro": 3,
        "doubao-seed-2-0-pro-260215": 3,
    },
    "research_enhance": {
        "qwen3.7-max": 4,
        "kimi-k3": 4,
        "glm-5.2": 3,
        "gemini-3.1-pro-preview": 3,
        "gemini-2.5-pro": 3,
        "deepseek-v4-pro": 3,
    },
    "plan_audit": {
        "deepseek-v4-pro": 4,
        "kimi-k3": 4,
        "glm-5.2": 3,
        "gemini-3.1-pro-preview": 4,
        "gemini-2.5-pro": 4,
        "qwen3.7-max": 4,
    },
    "execute": {
        "glm-5.2": 4,
        "doubao-seed-2-0-code-preview-260215": 4,
        "doubao-seed-2-1-pro": 4,
        "deepseek-v4-pro": 3,
        "kimi-k3": 3,
        "qwen3.7-plus": 3,
        "qwen3.7-max": 3,
        "gemini-2.5-pro": 3,
        "doubao-seed-2-0-pro-260215": 3,
    },
    "audit": {
        "gemini-2.5-pro": 4,
        "qwen3.7-max": 4,
        "deepseek-v4-pro": 4,
        "kimi-k3": 4,
        "gemini-3.1-pro-preview": 4,
        "doubao-seed-2-1-pro": 3,
        "glm-5.2": 3,
        "doubao-seed-2-0-pro-260215": 3,
    },
    "verify": {
        "gemini-2.5-pro": 4,
        "deepseek-v4-pro": 4,
        "qwen3.7-max": 4,
        "kimi-k3": 4,
        "gemini-3.1-pro-preview": 4,
        "doubao-seed-2-1-pro": 3,
        "glm-5.2": 3,
        "doubao-seed-2-0-pro-260215": 3,
        "openai/gpt-oss-120b": 2,
    },
    "quality_enhance": {
        "kimi-k3": 4,
        "qwen3.7-max": 3,
        "doubao-seed-2-1-pro": 3,
        "glm-5.2": 3,
        "gemini-2.5-pro": 3,
        "deepseek-v4-pro": 3,
        "doubao-seed-2-0-pro-260215": 3,
    },
}

# Publicly announced models remain candidates until a matching local golden
# gate passes. Keeping the status explicit makes "known but not promoted"
# distinguishable from an unknown or forgotten model.
PENDING_ROLE_CANDIDATES: dict[str, dict[str, str]] = {
    "deepseek-v4-flash": {
        "status": "pending_role_golden_gate",
        "reason": "official_0731_agent_update_but_local_plan_gate_failed_route_stability",
        "version": "DeepSeek-V4-Flash-0731",
    },
}

# Provider catalogs may append a deployment revision to the upstream model ID.
# Normalize only reviewed identities so pending-candidate metadata and request
# adapters apply without granting a role-quality band.
ROLE_MODEL_ALIASES: dict[str, str] = {
    "deepseek-ai/deepseek-v4-flash-0731": "deepseek-v4-flash",
    "deepseek-v4-flash-0731": "deepseek-v4-flash",
}

MULTIMODAL_UNDERSTANDING_ORDER = (
    "doubao-seed-2-0-pro-260215",
    "qwen3.7-plus",
    "kimi-k3",
    "gemini-2.5-pro",
    "gemini-3.1-pro-preview",
    "doubao-seed-2-1-pro",
    "doubao-seed-2-1-turbo",
)

MULTIMODAL_AUDIT_ORDER = (
    "gemini-2.5-pro",
    "kimi-k3",
    "qwen3.7-plus",
    "doubao-seed-2-0-pro-260215",
    "gemini-3.1-pro-preview",
)

MULTIMODAL_QUALITY_BANDS = {
    "gemini-2.5-pro": 4,
    "kimi-k3": 4,
    "qwen3.7-plus": 4,
    "doubao-seed-2-0-pro-260215": 4,
    "gemini-3.1-pro-preview": 4,
    "doubao-seed-2-1-pro": 3,
    "doubao-seed-2-1-turbo": 3,
}

# Conservative public list prices in USD per million tokens. For prices
# published in CNY, conversion happens at runtime using SMART_LLM_CNY_PER_USD.
MODEL_PRICE_CATALOG: dict[str, dict[str, float | str]] = {
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28, "currency": "USD"},
    "deepseek-v4-pro": {"input": 0.435, "output": 0.87, "currency": "USD"},
    "qwen3.7-max": {"input": 12.0, "output": 36.0, "currency": "CNY"},
    "qwen3.7-plus": {"input": 2.0, "output": 8.0, "currency": "CNY"},
    "glm-5.2": {"input": 8.0, "output": 28.0, "currency": "CNY"},
    "doubao-seed-2-1-pro": {"input": 6.0, "output": 30.0, "currency": "CNY"},
    "doubao-seed-2-1-turbo": {"input": 3.0, "output": 15.0, "currency": "CNY"},
    "doubao-seed-2-0-pro-260215": {"input": 3.2, "output": 16.0, "currency": "CNY"},
    "kimi-k3": {"input": 20.0, "output": 100.0, "currency": "CNY"},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0, "currency": "USD"},
    "gemini-3.1-pro-preview": {"input": 2.0, "output": 12.0, "currency": "USD"},
    # MiniMax-M3 has tiered pricing above 512k input tokens. Use the higher
    # public standard-tier price here so local USD budgets never under-reserve.
    "minimax-m3": {"input": 4.2, "output": 16.8, "currency": "CNY"},
    "minimax-m2.7": {"input": 2.1, "output": 8.4, "currency": "CNY"},
}

# Reasoning endpoints can bill hidden reasoning tokens in addition to the
# requested visible answer cap. Reserve a conservative envelope before sending.
MODEL_BILLABLE_OUTPUT_RESERVE_MULTIPLIER: dict[str, float] = {
    "deepseek-v4-pro": 2.0,
}

# Alibaba documents that max_completion_tokens covers reasoning plus answer for
# Qwen 3.7, with a possible difference of up to ten tokens.
MODEL_BILLABLE_OUTPUT_RESERVE_OVERHEAD: dict[str, int] = {
    "qwen3.7-max": 10,
    "qwen3.7-plus": 10,
    "qwen3.6-flash": 10,
}

# Local token counts are forecasts, not provider-enforced spend ceilings.
# Preserve a generic paid-route margin and a larger DeepSeek V4 margin learned
# from the 21476 -> 23139 provider-usage incident when no authoritative
# tokenizer result is available.
DEFAULT_PAID_INPUT_TOKEN_GUARD_FACTOR = 1.10
PROVIDER_INPUT_TOKEN_GUARD_FACTORS: dict[str, float] = {
    "deepseek-direct-paid": 1.15,
}
MODEL_INPUT_TOKEN_GUARD_FACTORS: dict[str, float] = {
    "deepseek-v4-flash": 1.15,
    "deepseek-v4-pro": 1.15,
}
# Provider tokenizers may add a fixed chat-template/system envelope that is
# disproportionate for tiny prompts. The first bounded MiniMax-M3 canary
# reported 199 input tokens for a local estimate of 48; reserve that observed
# fixed delta plus margin without multiplying every large prompt by 4x.
MODEL_INPUT_TOKEN_GUARD_OVERHEAD: dict[str, int] = {
    "minimax-m3": 160,
}
MAX_GUARDED_INPUT_TOKENS = (1 << 63) - 1

PROVIDER_FAMILY_CATALOG: dict[str, dict[str, Any]] = {
    "local": {
        "env_keys": [],
        "input_modalities": ["audio", "video", "text"],
        "output_modalities": ["text"],
        "task_types": ["asr", "chunk", "glossary_cleanup", "cache"],
        "notes": "Local ffmpeg/whisper/deterministic preprocessing. Use before any remote model.",
    },
    "openrouter": {
        "env_keys": ["OPENROUTER_API_KEY"],
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "task_types": ["classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "audit", "transcript_correct", "code"],
        "notes": "Gateway for free and paid text/vision models; model family is inferred from model id.",
    },
    "deepseek": {
        "env_keys": ["DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"],
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "task_types": ["plan", "research_enhance", "plan_audit", "execute", "transcript_correct", "clean", "summarize", "qa", "draft", "audit", "verify", "quality_enhance", "code"],
        "notes": "Preferred low-cost paid family for transcript correction and structured synthesis when configured directly or through OpenRouter.",
    },
    "qwen": {
        "env_keys": ["DASHSCOPE_API_KEY"],
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text", "image", "video", "embedding", "score"],
        "task_types": ["plan", "research_enhance", "plan_audit", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "asr", "image_generate", "embed", "rerank", "transcript_correct", "audit", "verify", "quality_enhance"],
        "model_modes": {
            "text_reasoning": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
            "vision_ocr": ["qwen-vl-max", "qwen-vl-plus", "qwen-omni"],
            "audio_asr": ["paraformer", "sensevoice", "qwen-audio"],
            "image_video_generation": ["wanx", "qwen-image"],
            "embedding": ["text-embedding-v4", "text-embedding-v3"],
            "rerank": ["gte-rerank"],
        },
        "notes": "DashScope/Qwen API keys can cover text, vision/OCR, audio, image/video generation, embedding, and rerank once concrete model ids/endpoints are configured.",
    },
    "zhipu": {
        "env_keys": ["ZHIPU_API_KEY", "GLM_API_KEY"],
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text", "image", "audio", "video", "embedding", "score"],
        "task_types": ["plan", "research_enhance", "plan_audit", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "asr", "image_generate", "embed", "rerank", "audit", "verify", "quality_enhance", "transcript_correct"],
        "model_modes": {
            "text_reasoning": ["glm-5.2", "glm-5.1", "glm-5", "glm-4.7", "glm-4.6", "glm-4.5", "glm-4.5-air"],
            "vision_ocr": ["glm-5v-turbo", "glm-4.6v", "glm-4v-plus", "glm-4v-flash", "glm-ocr"],
            "image_generation": ["glm-image", "cogview-4", "cogview-3-flash"],
            "video_generation": ["cogvideox-3", "cogvideox-flash", "vidu"],
            "speech_audio": ["glm-tts", "glm-tts-clone", "glm-asr-2512", "glm-realtime", "glm-4-voice"],
            "embedding": ["embedding-3", "embedding-2"],
            "rerank": ["rerank"],
        },
        "notes": "Zhipu/BigModel API keys can cover GLM text/reasoning, GLM-V/OCR, CogView/GLM image, CogVideo/Vidu video, TTS/ASR/realtime audio, embedding, and rerank. Only configured and probed endpoint/model blocks enter executable routing.",
    },
    "doubao": {
        "env_keys": ["ARK_API_KEY", "DOUBAO_API_KEY"],
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text", "image", "audio", "video", "embedding"],
        "task_types": ["plan", "research_enhance", "plan_audit", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "asr", "image_generate", "video_generate", "embed", "audit", "verify", "quality_enhance", "code"],
        "model_modes": {
            "multimodal_reasoning": ["doubao-seed-2.1-pro", "doubao-seed-2.1-turbo", "doubao-seed-2.0-pro", "doubao-seed-2.0-lite"],
            "multimodal_code": ["doubao-seed-2.0-code"],
            "image_generation": ["doubao-seedream-5.0-lite", "doubao-seedream-4.5"],
            "video_generation": ["doubao-seedance-2.0", "doubao-seedance-2.0-fast", "doubao-seedance-2.0-mini"],
            "speech_audio": ["doubao-realtime-voice", "doubao-streaming-asr", "doubao-recording-asr-2.0"],
            "embedding": ["doubao-embedding-vision"],
        },
        "notes": "Volcengine Ark covers Seed 2.1/2.0 multimodal reasoning and code plus Seedream, Seedance, speech, and multimodal embedding. Online inference, Coding Plan, and endpoint ids are separate billing/model-name routes.",
    },
    "groq": {
        "env_keys": ["GROQ_API_KEY"],
        "input_modalities": ["text", "audio"],
        "output_modalities": ["text"],
        "task_types": ["classify", "clean", "summarize", "qa", "draft", "transcript_correct", "asr"],
        "notes": "Fast free/low-cost text and audio-capable family; route lower if network handshakes are unstable.",
    },
    "nvidia": {
        "env_keys": ["NVIDIA_API_KEY"],
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "task_types": ["classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "audit", "transcript_correct", "code"],
        "notes": "NVIDIA NIM free/trial model pool for text and vision.",
    },
    "gemini": {
        "env_keys": ["GEMINI_API_KEY"],
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text"],
        "task_types": ["plan", "research_enhance", "plan_audit", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "audit", "verify", "quality_enhance", "transcript_correct"],
        "notes": "Independent paid multimodal family, especially useful for visual review and cross-vendor verification.",
    },
    "kimi": {
        "env_keys": ["KIMI_API_KEY"],
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "task_types": ["plan", "research_enhance", "plan_audit", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "audit", "verify", "quality_enhance", "transcript_correct", "code"],
        "model_modes": {
            "multimodal_reasoning": ["kimi-k3", "kimi-k2.6"],
        },
        "notes": "Long-context paid multimodal family for knowledge work, long-horizon agents, and final quality enhancement.",
    },
    "minimax": {
        "env_keys": ["MINIMAX_API_KEY"],
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "task_types": ["classify", "clean", "summarize", "qa", "draft", "transcript_correct", "code"],
        "model_modes": {
            "text_reasoning": ["MiniMax-M3", "MiniMax-M2.7"],
        },
        "notes": "China-region paid OpenAI-compatible text route. Role-quality bands remain unregistered until matching golden gates pass.",
    },
}


@dataclass(frozen=True)
class LLMChoice:
    provider: LLMProvider
    model: str


@dataclass(frozen=True)
class LLMResult:
    provider: str
    model: str
    content: str
    cached: bool = False
    complexity: str | None = None
    ledger_id: str | None = None


@dataclass(frozen=True)
class RouteState:
    unavailable_until: datetime | None
    failure_count: int
    reason: str | None


@dataclass(frozen=True)
class RouteHealthEvidence:
    last_success_at: datetime | None
    last_failure_at: datetime | None


class InconclusiveModelOutput(RuntimeError):
    """The endpoint responded, but no user-visible final answer was emitted."""

    def __init__(
        self,
        route: str,
        *,
        reasoning_present: bool,
        finish_reason: str | None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        details = []
        if reasoning_present:
            details.append("reasoning_present")
        if finish_reason:
            details.append(f"finish_reason={finish_reason}")
        suffix = f" ({', '.join(details)})" if details else ""
        super().__init__(f"{route} 未返回最终正文{suffix}")
        self.reasoning_present = reasoning_present
        self.finish_reason = finish_reason
        self.usage = dict(usage or {})


class GovernedInvalidOutput(RuntimeError):
    """A billed response failed the governed output contract and must not fall back."""


class RequestPolicyIncompatibility(RuntimeError):
    """The endpoint rejected request-scoped controls, not the generic route."""

    def __init__(self, status_code: int, reason: str = "request_constraints") -> None:
        super().__init__(
            f"OpenRouter request policy incompatible ({reason}, HTTP {status_code})"
        )
        self.status_code = status_code
        self.reason = reason


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _choice_key(choice: LLMChoice) -> str:
    return f"{choice.provider.name}/{choice.model}"


def _state_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_router_state.json"


def _health_evidence_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_route_health.json"


def _refresh_report_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_pool_refresh_report.json"


def _modality_refresh_report_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_modality_refresh_report.json"


def _maintain_report_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_pool_maintenance_report.json"


def _discovered_free_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_discovered_free_models.json"


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Persist a resumable runtime report without exposing a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _family_name(provider_name: str) -> str:
    provider_name = provider_name.lower()
    if provider_name.startswith("openrouter"):
        return "openrouter"
    if provider_name.startswith("nvidia"):
        return "nvidia"
    if provider_name.startswith("groq"):
        return "groq"
    return provider_name.split("-", 1)[0]


def _provider_family(provider: LLMProvider) -> str:
    text = f"{provider.name} {provider.base_url} {provider.api_key_env}".lower()
    if "openrouter" in text:
        return "openrouter"
    if "nvidia" in text or "integrate.api.nvidia" in text:
        return "nvidia"
    if "dashscope" in text or "qwen" in text or "bailian" in text:
        return "qwen"
    if "zhipu" in text or "bigmodel" in text or "glm" in text:
        return "zhipu"
    if "volces" in text or "doubao" in text or "ark" in text:
        return "doubao"
    if "groq" in text:
        return "groq"
    if "generativelanguage" in text or "gemini" in text or "googleapis" in text:
        return "gemini"
    if "deepseek" in text:
        return "deepseek"
    if "moonshot" in text or "kimi" in text:
        return "kimi"
    if "minimax" in text or "minimaxi.com" in text:
        return "minimax"
    return _family_name(provider.name)


def _model_family(choice: LLMChoice) -> str:
    text = f"{choice.provider.name} {choice.model} {choice.provider.base_url}".lower()
    if "deepseek" in text:
        return "deepseek"
    if "qwen" in text or "dashscope" in text:
        return "qwen"
    if "glm" in text or "zhipu" in text or "bigmodel" in text:
        return "zhipu"
    if "doubao" in text or "seed" in text or "ark" in text:
        return "doubao"
    if "gemini" in text or "google/" in text:
        return "gemini"
    if "kimi" in text or "moonshot" in text:
        return "kimi"
    if "groq" in text or "llama-3.1-8b-instant" in text or "llama-3.3-70b-versatile" in text:
        return "groq"
    if "nvidia" in text or "nemotron" in text:
        return "nvidia"
    return _provider_family(choice.provider)


def _template_provider_for_family(settings: Settings, family: str, source: str = "") -> LLMProvider | None:
    family = family.lower()
    candidates = [
        provider
        for provider in settings.providers
        if provider.name.lower().startswith(family) and os.getenv(provider.api_key_env, "").strip()
    ]
    if not candidates:
        return None
    free_candidates = [provider for provider in candidates if provider.free] or candidates
    specialist_terms = ("vision", "asr", "image", "embed", "rerank", "speech", "tts", "video")
    wants_vision = source.lower().endswith("_vision")
    if wants_vision:
        matching = [provider for provider in free_candidates if "vision" in provider.name.lower()]
    else:
        matching = [
            provider
            for provider in free_candidates
            if not any(term in provider.name.lower() for term in specialist_terms)
        ]
    return sorted(matching or free_candidates, key=lambda provider: (provider.priority, provider.name))[0]


def _template_providers_for_discovered_family(
    settings: Settings,
    family: str,
    source: str = "",
) -> list[LLMProvider]:
    """Return the selected discovery template and its credential rotations."""
    template = _template_provider_for_family(settings, family, source)
    if not template:
        return []
    base_name = re.sub(r"-key\d+$", "", template.name.lower())
    return sorted(
        [
            provider
            for provider in settings.providers
            if provider.free
            and re.sub(r"-key\d+$", "", provider.name.lower()) == base_name
            and provider.base_url == template.base_url
            and os.getenv(provider.api_key_env, "").strip()
        ],
        key=lambda provider: (provider.priority, provider.name),
    )


def _load_discovered_free_models(settings: Settings) -> dict[str, list[dict[str, Any]]]:
    raw = _load_json(_discovered_free_path(settings))
    if not isinstance(raw, dict):
        return {}
    families = raw.get("families")
    if not isinstance(families, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for family, items in families.items():
        if not isinstance(items, list):
            continue
        clean_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            model_id = ""
            source = "discovery"
            free_signal = ""
            if isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or "").strip()
                source = str(item.get("source") or source).strip() or source
                free_signal = str(item.get("free_signal") or "").strip()
            elif isinstance(item, str):
                model_id = item.strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            clean_items.append({"id": model_id, "source": source, "free_signal": free_signal})
        if clean_items:
            out[str(family)] = clean_items
    return out


def _save_discovered_free_models(settings: Settings, families: dict[str, list[dict[str, Any]]]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _discovered_free_path(settings).write_text(
        json.dumps({"updated_at": _now().isoformat(), "families": families}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _record_discovered_free_models(settings: Settings, discovered_sections: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    families = _load_discovered_free_models(settings)
    touched_sources = set(discovered_sections)
    for family, items in list(families.items()):
        retained = [item for item in items if str(item.get("source") or "") not in touched_sources]
        if retained:
            families[family] = retained
        else:
            families.pop(family, None)

    seen = {
        (family, str(item.get("id") or ""))
        for family, items in families.items()
        for item in items
        if str(item.get("id") or "")
    }
    for section_name, rows in discovered_sections.items():
        family = _family_name(section_name)
        for row in rows:
            model_id = str(row.get("id") or row.get("model") or "").strip()
            if not model_id:
                continue
            key = (family, model_id)
            if key in seen:
                continue
            seen.add(key)
            families.setdefault(family, []).append(
                {
                    "id": model_id,
                    "source": section_name,
                    "free_signal": str(row.get("free_signal") or row.get("name") or "").strip(),
                }
            )
    if discovered_sections:
        _save_discovered_free_models(settings, families)
    return families


def _discovery_snapshot_is_stale(settings: Settings) -> bool:
    if not settings.auto_discover_free:
        return False
    raw = _load_json(_discovered_free_path(settings))
    updated_at = raw.get("updated_at") if isinstance(raw, dict) else None
    if not isinstance(updated_at, str) or not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return _now() - updated >= timedelta(hours=settings.discovery_ttl_hours)


def _maybe_auto_discover_free_pool(settings: Settings) -> dict[str, Any] | None:
    if not _discovery_snapshot_is_stale(settings):
        return None
    return discover_free_pool(settings, limit=settings.discovery_limit)


def _benchmark_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_free_model_quick_benchmark.json"


def _ledger_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_cost_ledger.jsonl"


def _cache_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_response_cache.json"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load_route_state(settings: Settings) -> dict[str, RouteState]:
    raw = _load_json(_state_path(settings)) or {}
    states: dict[str, RouteState] = {}
    for key, value in raw.items():
        states[key] = RouteState(
            unavailable_until=_parse_timestamp(value.get("unavailable_until")),
            failure_count=int(value.get("failure_count") or 0),
            reason=str(value.get("reason") or "") or None,
        )
    return states


def _load_route_health(settings: Settings) -> dict[str, RouteHealthEvidence]:
    raw = _load_json(_health_evidence_path(settings)) or {}
    evidence: dict[str, RouteHealthEvidence] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        evidence[key] = RouteHealthEvidence(
            last_success_at=_parse_timestamp(value.get("last_success_at")),
            last_failure_at=_parse_timestamp(value.get("last_failure_at")),
        )
    return evidence


def _save_route_health(settings: Settings, evidence: dict[str, RouteHealthEvidence]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        key: {
            "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
            "last_failure_at": item.last_failure_at.isoformat() if item.last_failure_at else None,
        }
        for key, item in evidence.items()
        if item.last_success_at or item.last_failure_at
    }
    _health_evidence_path(settings).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_route_state(settings: Settings, states: dict[str, RouteState]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    payload = {}
    for key, state in states.items():
        if state.unavailable_until and state.unavailable_until <= now:
            continue
        payload[key] = {
            "unavailable_until": state.unavailable_until.isoformat() if state.unavailable_until else None,
            "failure_count": state.failure_count,
            "reason": state.reason,
        }
    _state_path(settings).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cooldown_for_error(exc: Exception, failure_count: int) -> timedelta:
    text = str(exc).lower()
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return timedelta(seconds=min(24 * 60 * 60, max(30, retry_after)))
    status = _http_status_from_error(exc)
    if status in {404, 410}:
        return timedelta(days=7)
    if status in {401, 403} or "401" in text or "403" in text:
        return timedelta(hours=24)
    if "404" in text or "410" in text:
        return timedelta(days=7)
    if "429" in text or "rate" in text or "quota" in text:
        return timedelta(minutes=min(240, 30 * max(1, failure_count)))
    if "timeout" in text or "timed out" in text:
        return timedelta(minutes=min(60, 10 * max(1, failure_count)))
    if any(code in text for code in ("500", "502", "503", "504")):
        return timedelta(minutes=min(120, 15 * max(1, failure_count)))
    return timedelta(minutes=min(60, 10 * max(1, failure_count)))


def _http_status_from_error(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"\b(4\d\d|5\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def _retry_after_seconds(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw = None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        raw = None
    if not raw:
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        return int(raw)
    try:
        retry_at = datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((retry_at - _now()).total_seconds()))


def _is_available(choice: LLMChoice, states: dict[str, RouteState]) -> bool:
    state = states.get(_choice_key(choice))
    return not state or not state.unavailable_until or state.unavailable_until <= _now()


def _route_health_snapshot(
    settings: Settings,
    choice: LLMChoice,
    states: dict[str, RouteState],
    evidence: dict[str, RouteHealthEvidence],
) -> dict[str, Any]:
    now = _now()
    state = states.get(_choice_key(choice))
    observed = evidence.get(_choice_key(choice))
    routing_eligible = not state or not state.unavailable_until or state.unavailable_until <= now
    last_success_at = observed.last_success_at if observed else None
    last_failure_at = observed.last_failure_at if observed else None
    success_is_latest = bool(
        last_success_at
        and (not last_failure_at or last_success_at > last_failure_at)
    )
    success_is_fresh = bool(
        success_is_latest
        and last_success_at
        and now - last_success_at <= timedelta(hours=settings.health_ttl_hours)
    )
    if not routing_eligible:
        health_status = "unhealthy"
        health_evidence = "active_cooldown"
    elif success_is_fresh:
        health_status = "healthy"
        health_evidence = "recent_success"
    elif last_failure_at and (not last_success_at or last_failure_at >= last_success_at):
        health_status = "unknown"
        health_evidence = "failed_since_last_success"
    else:
        health_status = "unknown"
        health_evidence = "no_recent_success"
    checked_at = max(
        (value for value in (last_success_at, last_failure_at) if value),
        default=None,
    )
    return {
        "health_status": health_status,
        "health_evidence": health_evidence,
        "health_checked_at": checked_at.isoformat() if checked_at else None,
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "routing_eligible": routing_eligible,
        "available_now": health_status == "healthy",
    }


def _is_declared_choice(settings: Settings, choice: LLMChoice) -> bool:
    return any(
        provider.name == choice.provider.name and choice.model in provider.models
        for provider in settings.providers
    )


def _free_only_eligible_provider(provider: LLMProvider) -> bool:
    if not provider.free:
        return False
    return provider.billing_class != "trial_quota" or provider.trial_quota_guarded


def _provider_execution_enabled(provider: LLMProvider) -> bool:
    return not (
        provider.free
        and provider.billing_class == "trial_quota"
        and not provider.trial_quota_guarded
    )


def _is_execution_eligible_choice(
    settings: Settings,
    choice: LLMChoice,
    states: dict[str, RouteState],
    evidence: dict[str, RouteHealthEvidence],
) -> bool:
    if not _provider_execution_enabled(choice.provider):
        return False
    if not _is_available(choice, states):
        return False
    if _is_declared_choice(settings, choice):
        return True
    return _route_health_snapshot(settings, choice, states, evidence)["health_status"] == "healthy"


def _record_success(settings: Settings, choice: LLMChoice, states: dict[str, RouteState]) -> None:
    key = _choice_key(choice)
    evidence = _load_route_health(settings)
    previous = evidence.get(key)
    evidence[key] = RouteHealthEvidence(
        last_success_at=_now(),
        last_failure_at=previous.last_failure_at if previous else None,
    )
    _save_route_health(settings, evidence)
    if key in states:
        states.pop(key, None)
        _save_route_state(settings, states)


def _record_failure(settings: Settings, choice: LLMChoice, states: dict[str, RouteState], exc: Exception) -> None:
    key = _choice_key(choice)
    previous = states.get(key)
    failure_count = (previous.failure_count if previous else 0) + 1
    observed_at = _now()
    states[key] = RouteState(
        unavailable_until=observed_at + _cooldown_for_error(exc, failure_count),
        failure_count=failure_count,
        reason=str(exc).replace("\n", " ")[:240],
    )
    _save_route_state(settings, states)
    evidence = _load_route_health(settings)
    previous_evidence = evidence.get(key)
    evidence[key] = RouteHealthEvidence(
        last_success_at=previous_evidence.last_success_at if previous_evidence else None,
        last_failure_at=observed_at,
    )
    _save_route_health(settings, evidence)


def configured_models(settings: Settings, *, only_free: bool = False) -> list[LLMChoice]:
    choices: list[LLMChoice] = []
    for provider in settings.providers:
        if only_free and not _free_only_eligible_provider(provider):
            continue
        if not os.getenv(provider.api_key_env, "").strip():
            continue
        for model in provider.models:
            choices.append(LLMChoice(provider=provider, model=model))

    discovered = _load_discovered_free_models(settings)
    if discovered:
        existing = {(choice.provider.name, choice.model) for choice in choices}
        for family, items in discovered.items():
            for item in items:
                templates = _template_providers_for_discovered_family(
                    settings,
                    family,
                    str(item.get("source") or ""),
                )
                if not templates:
                    continue
                model = str(item.get("id") or "").strip()
                if not model:
                    continue
                for template in templates:
                    if only_free and not _free_only_eligible_provider(template):
                        continue
                    key = (template.name, model)
                    if key in existing:
                        continue
                    choices.append(
                        LLMChoice(
                            provider=LLMProvider(
                                name=template.name,
                                base_url=template.base_url,
                                api_key_env=template.api_key_env,
                                models=(model,),
                                free=True,
                                priority=template.priority,
                                billing_class=template.billing_class,
                                trial_quota_guarded=template.trial_quota_guarded,
                            ),
                            model=model,
                        )
                    )
                    existing.add(key)
    return choices


def _task_order(task: str) -> list[str]:
    task = normalize_task_type(task)
    raw = os.getenv(f"SMART_LLM_TASK_ORDER_{task.upper()}", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return DEFAULT_TASK_ORDER.get(task, DEFAULT_TASK_ORDER["draft"])


def normalize_task_type(task: str) -> str:
    normalized = (task or "draft").strip().lower().replace("-", "_")
    aliases = {
        "correct": "transcript_correct",
        "transcript": "transcript_correct",
        "asr_correct": "transcript_correct",
        "transcript_clean": "transcript_correct",
        "rewrite": "draft",
        "review": "audit",
        "planning": "plan",
        "strategy": "plan",
        "research": "research_enhance",
        "research_upgrade": "research_enhance",
        "challenge_audit": "plan_audit",
        "planning_audit": "plan_audit",
        "implementation": "execute",
        "executor": "execute",
        "cross_check": "verify",
        "second_check": "verify",
        "polish": "quality_enhance",
        "improve": "quality_enhance",
        "image": "vision",
        "visual": "vision",
        "extract_text": "ocr",
        "image_ocr": "ocr",
        "stt": "asr",
        "speech_to_text": "asr",
        "embedding": "embed",
        "rank": "rerank",
    }
    return aliases.get(normalized, normalized)


def _role_model_aliases(choice: LLMChoice) -> tuple[str, ...]:
    raw = choice.model.lower().strip()
    without_free = re.sub(r":free$", "", raw)
    basename = without_free.rsplit("/", 1)[-1]
    aliases = [raw, without_free, basename]
    aliases.extend(
        ROLE_MODEL_ALIASES[alias]
        for alias in tuple(aliases)
        if alias in ROLE_MODEL_ALIASES
    )
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _is_deepseek_v4_choice(choice: LLMChoice) -> bool:
    return _model_family(choice) == "deepseek" and any(
        alias in {"deepseek-v4-flash", "deepseek-v4-pro"}
        for alias in _role_model_aliases(choice)
    )


def _is_nvidia_deepseek_v4_choice(choice: LLMChoice) -> bool:
    return _provider_family(choice.provider) == "nvidia" and _is_deepseek_v4_choice(choice)


def _role_model_rank(choice: LLMChoice, task: str) -> int:
    ordered = ROLE_MODEL_ORDER.get(normalize_task_type(task), ())
    ranks = [ordered.index(alias) for alias in _role_model_aliases(choice) if alias in ordered]
    return min(ranks) if ranks else 100


def _rank_choices(choices: list[LLMChoice], task: str) -> list[LLMChoice]:
    task = normalize_task_type(task)
    rank = {name: index for index, name in enumerate(_task_order(task))}
    return [
        choice
        for _, choice in sorted(
            enumerate(choices),
            key=lambda item: (
                rank.get(item[1].provider.name, 100),
                _role_model_rank(item[1], task),
                item[1].provider.priority,
                item[0],
            ),
        )
    ]


def _is_general_multimodal_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(
        term in text
        for term in (
            "kimi-k3",
            "kimi-k2.6",
            "qwen3.7-plus",
            "doubao-seed-2-1",
            "doubao-seed-2-0",
            "gemini-2.5-pro",
            "gemini-3.1-pro",
        )
    )


def _is_vision_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {' '.join(choice.provider.models)} {choice.model}".lower()
    vision_terms = ("vision", "vl", "multimodal", "omni", "qwen-vl", "gemini", "glm-5v", "glm-4v", "glm-4.6v", "glm-ocr", "doubao-vision")
    return _is_general_multimodal_choice(choice) or any(term in text for term in vision_terms)


def _is_embedding_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    if "rerank" in text or "reranker" in text:
        return False
    return any(term in text for term in ("embed", "embedding", "bge", "gte", "text-embedding", "text_embedding"))


def _is_rerank_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return "rerank" in text or "reranker" in text or "gte-rerank" in text


def _is_image_generation_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(term in text for term in ("image-generation", "image_gen", "image-lowcost", "zhipu-image", "glm-image", "dall-e", "imagen", "flux", "sdxl", "seedream", "cogview", "wanx", "text2image"))


def _is_video_generation_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(term in text for term in ("video-generation", "video_gen", "cogvideo", "cogvideox", "vidu", "wanx2", "text2video"))


def _is_speech_generation_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(term in text for term in ("tts", "voice", "realtime", "speech-generation", "orpheus"))


def _is_guard_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(term in text for term in ("prompt-guard", "safeguard", "content-safety"))


def _is_code_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(term in text for term in ("coder", "code", "deepseek-coder", "qwen3-coder"))


def _is_audio_choice(choice: LLMChoice) -> bool:
    text = f"{choice.provider.name} {choice.model}".lower()
    return any(term in text for term in ("whisper", "audio", "speech-to-text", "asr", "glm-asr", "paraformer", "sensevoice", "transcribe"))


def _choice_modalities(choice: LLMChoice) -> dict[str, list[str]]:
    if _is_audio_choice(choice):
        return {"input": ["audio", "video"], "output": ["text"]}
    if _is_speech_generation_choice(choice):
        return {"input": ["text", "audio"], "output": ["audio", "text"]}
    if _is_rerank_choice(choice):
        return {"input": ["text"], "output": ["score"]}
    if _is_embedding_choice(choice):
        return {"input": ["text"], "output": ["embedding"]}
    if _is_video_generation_choice(choice):
        return {"input": ["text", "image", "video"], "output": ["video"]}
    if _is_image_generation_choice(choice):
        return {"input": ["text", "image"], "output": ["image"]}
    if _is_general_multimodal_choice(choice):
        inputs = ["text", "image"]
        if _model_family(choice) == "gemini":
            inputs.extend(["audio", "video"])
        return {"input": inputs, "output": ["text"]}
    if _is_vision_choice(choice):
        return {"input": ["text", "image"], "output": ["text"]}
    return {"input": ["text"], "output": ["text"]}


def _choice_task_types(choice: LLMChoice) -> list[str]:
    if _is_audio_choice(choice):
        return ["asr"]
    if _is_speech_generation_choice(choice):
        return ["tts"]
    if _is_rerank_choice(choice):
        return ["rerank"]
    if _is_embedding_choice(choice):
        return ["embed"]
    if _is_video_generation_choice(choice):
        return ["video_generate"]
    if _is_image_generation_choice(choice):
        return ["image_generate"]
    if _is_general_multimodal_choice(choice):
        return sorted(TEXT_TASKS | VISION_TASKS)
    if _is_vision_choice(choice):
        return ["vision", "ocr"]
    if _is_code_choice(choice):
        return ["plan", "research_enhance", "plan_audit", "execute", "code", "clean", "qa", "summarize", "draft", "audit", "verify", "quality_enhance", "transcript_correct"]
    return ["plan", "research_enhance", "plan_audit", "execute", "classify", "clean", "summarize", "qa", "draft", "audit", "verify", "quality_enhance", "transcript_correct"]


def _choice_model_mode(choice: LLMChoice) -> str:
    if _is_audio_choice(choice):
        return "asr"
    if _is_speech_generation_choice(choice):
        return "tts"
    if _is_rerank_choice(choice):
        return "rerank"
    if _is_embedding_choice(choice):
        return "embed"
    if _is_video_generation_choice(choice):
        return "video_generate"
    if _is_image_generation_choice(choice):
        return "image_generate"
    if _is_general_multimodal_choice(choice):
        return "multimodal_reasoning"
    if _is_vision_choice(choice):
        return "vision_ocr"
    if _is_code_choice(choice):
        return "code"
    return "text_reasoning"


def _choice_endpoint_family(choice: LLMChoice) -> str:
    family = _provider_family(choice.provider)
    mode = _choice_model_mode(choice)
    if mode in {"vision_ocr", "image_generate", "video_generate", "asr", "tts", "embed", "rerank"}:
        return f"{family}-{mode}"
    return family


def describe_choice_capability(choice: LLMChoice) -> dict[str, Any]:
    modalities = _choice_modalities(choice)
    model_family = _model_family(choice)
    catalog = PROVIDER_FAMILY_CATALOG.get(model_family) or PROVIDER_FAMILY_CATALOG.get(_provider_family(choice.provider), {})
    pending = next(
        (
            PENDING_ROLE_CANDIDATES[alias]
            for alias in _role_model_aliases(choice)
            if alias in PENDING_ROLE_CANDIDATES
        ),
        None,
    )
    return {
        "provider": choice.provider.name,
        "model": choice.model,
        "provider_family": _provider_family(choice.provider),
        "model_family": model_family,
        "endpoint_family": _choice_endpoint_family(choice),
        "model_mode": _choice_model_mode(choice),
        "free": choice.provider.free,
        "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
        "trial_quota_guarded": choice.provider.trial_quota_guarded,
        "free_only_eligible": _free_only_eligible_provider(choice.provider),
        "execution_enabled": _provider_execution_enabled(choice.provider),
        "priority": choice.provider.priority,
        "input_modalities": modalities["input"],
        "output_modalities": modalities["output"],
        "task_types": _choice_task_types(choice),
        "family_notes": catalog.get("notes"),
        "api_key_env": choice.provider.api_key_env,
        "estimated_input_price_per_million": _price_per_million(choice, "input"),
        "estimated_output_price_per_million": _price_per_million(choice, "output"),
        "price_currency": "USD",
        "role_fit": [
            role
            for role, models in ROLE_MODEL_ORDER.items()
            if any(alias in models for alias in _role_model_aliases(choice))
        ],
        "role_candidate_status": dict(pending) if pending else None,
        "redundancy_identity": f"{model_family}/{choice.model.lower()}",
    }


def _adapter_lifecycle_route_allowed(settings: Settings, choice: LLMChoice) -> bool:
    adapters_dir = settings.data_dir / "adapter-lifecycle" / "adapters"
    if not adapters_dir.is_dir():
        return True
    for path in adapters_dir.glob("*.json"):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        declared_provider = re.sub(r"-key\d+$", "", str(payload.get("provider") or "").lower())
        choice_provider = re.sub(r"-key\d+$", "", choice.provider.name.lower())
        if (
            declared_provider == choice_provider
            and str(payload.get("model") or "").lower() == choice.model.lower()
        ):
            return str(payload.get("current_state") or "").lower() in {"qualified", "production"}
    return True


def _model_choices(settings: Settings, *, task: str, only_free: bool) -> list[LLMChoice]:
    task = normalize_task_type(task)
    choices = [
        choice
        for choice in configured_models(settings, only_free=only_free)
        if _provider_execution_enabled(choice.provider)
        and _adapter_lifecycle_route_allowed(settings, choice)
    ]
    if task in VISION_TASKS:
        choices = [choice for choice in choices if _is_vision_choice(choice)]
    elif task == "embed":
        choices = [choice for choice in choices if _is_embedding_choice(choice)]
    elif task == "rerank":
        choices = [choice for choice in choices if _is_rerank_choice(choice)]
    elif task == "image_generate":
        choices = [choice for choice in choices if _is_image_generation_choice(choice)]
    elif task == "asr":
        choices = [choice for choice in choices if _is_audio_choice(choice)]
    else:
        choices = [
            choice
            for choice in choices
            if not (
                (_is_vision_choice(choice) and not _is_general_multimodal_choice(choice))
                or _is_embedding_choice(choice)
                or _is_rerank_choice(choice)
                or _is_image_generation_choice(choice)
                or _is_video_generation_choice(choice)
                or _is_audio_choice(choice)
                or _is_speech_generation_choice(choice)
                or _is_guard_choice(choice)
            )
        ]
    return _rank_choices(choices, task)


def _choice_matches_provider(choice: LLMChoice, provider_filter: str | None) -> bool:
    needle = (provider_filter or "").strip().lower()
    if not needle:
        return True
    return needle in {
        choice.provider.name.lower(),
        _provider_family(choice.provider).lower(),
        _model_family(choice).lower(),
    }


def _choice_matches_model(choice: LLMChoice, model_filter: str | None) -> bool:
    needle = (model_filter or "").strip().lower()
    if not needle:
        return True
    model = choice.model.lower()
    return needle == model or needle in model


def _is_trusted_local_choice(choice: LLMChoice) -> bool:
    if not choice.provider.free or choice.provider.billing_class != "local":
        return False
    try:
        host = httpx.URL(choice.provider.base_url).host
    except (TypeError, httpx.InvalidURL):
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _filter_choices(
    choices: list[LLMChoice],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> list[LLMChoice]:
    return [
        choice
        for choice in choices
        if _choice_matches_provider(choice, provider) and _choice_matches_model(choice, model)
    ]


def _avoid_route_set(avoid_routes: list[str] | tuple[str, ...] | None) -> set[str]:
    routes: set[str] = set()
    for item in avoid_routes or []:
        text = str(item or "").strip().lower()
        if text:
            routes.add(text)
    return routes


def _split_avoided_choices(choices: list[LLMChoice], avoid_routes: list[str] | tuple[str, ...] | None) -> tuple[list[LLMChoice], list[LLMChoice]]:
    avoid = _avoid_route_set(avoid_routes)
    if not avoid:
        return choices, []
    kept: list[LLMChoice] = []
    avoided: list[LLMChoice] = []
    for choice in choices:
        route = _choice_key(choice).lower()
        provider = choice.provider.name.lower()
        model = choice.model.lower()
        family = _provider_family(choice.provider).lower()
        if route in avoid or provider in avoid or model in avoid or family in avoid:
            avoided.append(choice)
        else:
            kept.append(choice)
    return kept, avoided


def _paid_fallback_choices(settings: Settings, task: str, quality_target: str = "production") -> list[LLMChoice]:
    task = normalize_task_type(task)
    choices = [choice for choice in _model_choices(settings, task=task, only_free=False) if not choice.provider.free]
    if task in VISION_TASKS:
        vision_paid_order = ["qwen-vision-lowcost", "zhipu-vision-paid", "zhipu-vision-lowcost", "doubao-frontier-paid", "gemini-frontier-paid", "kimi-frontier-paid", "qwen-frontier-paid", "gemini-paid"]
        vision_paid = [choice for choice in choices if _is_vision_choice(choice)]
        rank = {name: index for index, name in enumerate(vision_paid_order)}
        return sorted(vision_paid, key=lambda choice: (rank.get(choice.provider.name, 100), choice.provider.priority))
    rank = {name: index for index, name in enumerate(PAID_FALLBACK_ORDER)}
    return sorted(
        choices,
        key=lambda choice: (
            _role_model_rank(choice, task) if task in ROLE_TASKS else 100,
            rank.get(choice.provider.name, 100),
            choice.provider.priority,
        ),
    )


def _dedupe_model_routes(choices: list[LLMChoice]) -> list[LLMChoice]:
    """Collapse key rotations while preserving independent model families."""
    selected: list[LLMChoice] = []
    seen: set[tuple[str, str]] = set()
    for choice in choices:
        identity = (_model_family(choice), choice.model.lower())
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(choice)
    return selected


def _role_quality_band(choice: LLMChoice, role: str) -> int:
    bands = ROLE_QUALITY_BANDS.get(normalize_task_type(role), {})
    return max((bands.get(alias, 0) for alias in _role_model_aliases(choice)), default=0)


def _minimum_role_quality_band(quality_target: str) -> int:
    try:
        return ROLE_MIN_QUALITY_BANDS[quality_target]
    except KeyError as exc:
        raise ValueError(f"不支持的质量档位：{quality_target}") from exc


def _role_policy_choices(
    settings: Settings,
    *,
    role: str,
    quality_target: str,
    input_tokens: int,
    max_cost_usd: float | None,
    paid_allowed: bool,
    history: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    collapse_key_rotations: bool = True,
) -> list[LLMChoice]:
    minimum_band = _minimum_role_quality_band(quality_target)
    choices = [
        choice
        for choice in _model_choices(settings, task=role, only_free=False)
        if _role_quality_band(choice, role) >= minimum_band
        and (
            _free_only_eligible_provider(choice.provider)
            or (paid_allowed and not choice.provider.free)
        )
    ]

    history = history if history is not None else _route_history_map(settings, task=role)

    def sort_key(choice: LLMChoice) -> tuple[int, int, float, float, float, int, int]:
        budget = _budget_status(choice, input_tokens, max_cost_usd)
        projected = budget.get("projected_cost_usd")
        route_history = _choice_route_history(history, role, choice)
        success_probability = float(route_history.get("smoothed_success_rate") or 0.5) if route_history else 0.5
        expected_total_cost = (
            float(projected) / max(success_probability, 0.05)
            if projected is not None
            else float("inf")
        )
        latency_p95 = route_history.get("successful_latency_p95_s") if route_history else None
        if role in {"research_enhance", "plan_audit"}:
            return (
                1 if route_history and route_history.get("degraded") else 0,
                0 if budget["eligible"] else 1,
                -float(_role_quality_band(choice, role)),
                float(_role_model_rank(choice, role)),
                expected_total_cost,
                int(float(latency_p95)) if latency_p95 is not None else 10**9,
                choice.provider.priority,
            )
        return (
            1 if route_history and route_history.get("degraded") else 0,
            0 if budget["eligible"] else 1,
            expected_total_cost,
            float(latency_p95) if latency_p95 is not None else float("inf"),
            -float(_role_quality_band(choice, role)),
            _role_model_rank(choice, role),
            choice.provider.priority,
        )

    ordered = sorted(choices, key=sort_key)
    return _dedupe_model_routes(ordered) if collapse_key_rotations else ordered


def describe_providers(settings: Settings) -> list[dict[str, Any]]:
    return [
        {
            "name": provider.name,
            "base_url": provider.base_url,
            "api_key_env": provider.api_key_env,
            "has_key": bool(os.getenv(provider.api_key_env, "").strip()),
            "models": list(provider.models),
            "free": provider.free,
            "billing_class": provider.billing_class or ("permanent_free" if provider.free else "paid"),
            "trial_quota_guarded": provider.trial_quota_guarded,
            "free_only_eligible": _free_only_eligible_provider(provider),
            "execution_enabled": _provider_execution_enabled(provider),
            "priority": provider.priority,
            "provider_family": _provider_family(provider),
        }
        for provider in settings.providers
    ]


def capability_registry(settings: Settings, *, configured_only: bool = False) -> dict[str, Any]:
    choices = configured_models(settings, only_free=False)
    configured: list[dict[str, Any]] = []
    family_coverage: dict[str, dict[str, Any]] = {}
    for choice in choices:
        capability = describe_choice_capability(choice)
        configured.append(capability)
        for family_key in {capability["provider_family"], capability["model_family"]}:
            row = family_coverage.setdefault(
                family_key,
                {
                    "configured_models": 0,
                    "providers": sorted({provider.name for provider in settings.providers if _provider_family(provider) == family_key}),
                    "has_any_key": False,
                    "input_modalities": set(),
                    "output_modalities": set(),
                    "task_types": set(),
                },
            )
            row["configured_models"] += 1
            row["has_any_key"] = row["has_any_key"] or bool(os.getenv(choice.provider.api_key_env, "").strip())
            row["input_modalities"].update(capability["input_modalities"])
            row["output_modalities"].update(capability["output_modalities"])
            row["task_types"].update(capability["task_types"])

    catalog_rows: list[dict[str, Any]] = []
    for family, meta in PROVIDER_FAMILY_CATALOG.items():
        env_keys = list(meta.get("env_keys") or [])
        configured_row = family_coverage.get(family)
        has_env_key = any(bool(os.getenv(key, "").strip()) for key in env_keys)
        has_configured_provider = bool(configured_row and configured_row.get("configured_models"))
        if configured_only and not has_configured_provider:
            continue
        catalog_rows.append(
            {
                "family": family,
                "configured": has_configured_provider,
                "has_any_key": bool(has_env_key or (configured_row and configured_row.get("has_any_key"))),
                "env_keys": env_keys,
                "configured_models": int(configured_row.get("configured_models", 0)) if configured_row else 0,
                "input_modalities": sorted((configured_row.get("input_modalities") if configured_row else set()) or set(meta.get("input_modalities") or [])),
                "output_modalities": sorted((configured_row.get("output_modalities") if configured_row else set()) or set(meta.get("output_modalities") or [])),
                "task_types": sorted((configured_row.get("task_types") if configured_row else set()) or set(meta.get("task_types") or [])),
                "notes": meta.get("notes"),
                "known_model_modes": meta.get("model_modes", {}),
                "known_input_modalities": sorted(set(meta.get("input_modalities") or [])),
                "known_output_modalities": sorted(set(meta.get("output_modalities") or [])),
                "known_task_types": sorted(set(meta.get("task_types") or [])),
            }
        )

    for row in family_coverage.values():
        row["input_modalities"] = sorted(row["input_modalities"])
        row["output_modalities"] = sorted(row["output_modalities"])
        row["task_types"] = sorted(row["task_types"])

    return {
        "generated_at": _now().isoformat(),
        "families": catalog_rows,
        "configured_choices": configured,
        "missing_recommended_families": [
            row["family"]
            for row in catalog_rows
            if row["family"] in {"zhipu", "doubao"} and not row["configured"]
        ],
    }


def route_status(settings: Settings) -> list[dict[str, Any]]:
    states = _load_route_state(settings)
    evidence = _load_route_health(settings)
    rows = []
    for choice in _rank_choices(configured_models(settings, only_free=False), "qa"):
        state = states.get(_choice_key(choice))
        unavailable_until = state.unavailable_until if state else None
        health = _route_health_snapshot(settings, choice, states, evidence)
        rows.append(
            {
                "provider": choice.provider.name,
                "model": choice.model,
                "free": choice.provider.free,
                **health,
                "catalog_declared": _is_declared_choice(settings, choice),
                "execution_eligible": _is_execution_eligible_choice(settings, choice, states, evidence),
                "unavailable_until": unavailable_until.isoformat() if unavailable_until else None,
                "failure_count": state.failure_count if state else 0,
                "reason": state.reason if state else None,
            }
        )
    return rows


def router_doctor(
    settings: Settings,
    *,
    quality_target: str = "production",
    paid_allowed: bool = False,
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Explain local readiness and role gaps without making network calls."""
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"不支持的质量档位：{quality_target}")
    states = _load_route_state(settings)
    evidence = _load_route_health(settings)
    all_choices = configured_models(settings, only_free=False)
    # Doctor must explain routes that normal execution intentionally excludes,
    # especially unguarded trial quotas, so inspect declared text capability
    # instead of starting from the already-filtered execution pool.
    general_choices = [
        choice for choice in all_choices if "qa" in _choice_task_types(choice)
    ]
    input_tokens = 512
    role_rows: list[dict[str, Any]] = []
    for role in ("plan", "research_enhance", "plan_audit", "execute", "audit", "verify"):
        minimum_band = _minimum_role_quality_band(quality_target)
        eligible = [
            choice
            for choice in _role_policy_choices(
                settings,
                role=role,
                quality_target=quality_target,
                input_tokens=input_tokens,
                max_cost_usd=max_cost_usd,
                paid_allowed=paid_allowed,
                collapse_key_rotations=True,
            )
            if _is_execution_eligible_choice(settings, choice, states, evidence)
            and _budget_status(choice, input_tokens, max_cost_usd)["eligible"]
        ]
        excluded: list[dict[str, Any]] = []
        for choice in general_choices:
            reasons: list[str] = []
            band = _role_quality_band(choice, role)
            if band < minimum_band:
                reasons.append(f"role_quality_band_below_{minimum_band}")
                if any(alias in PENDING_ROLE_CANDIDATES for alias in _role_model_aliases(choice)):
                    reasons.append("pending_role_golden_gate")
            if choice.provider.free and not _provider_execution_enabled(choice.provider):
                reasons.append("trial_quota_guard_missing")
            if not choice.provider.free and not paid_allowed:
                reasons.append("paid_route_requires_opt_in")
            if not _is_available(choice, states):
                reasons.append("active_cooldown")
            budget = _budget_status(choice, input_tokens, max_cost_usd)
            if not budget["eligible"] and budget.get("reason"):
                reasons.append(str(budget["reason"]))
            if reasons:
                excluded.append(
                    {
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "free": choice.provider.free,
                        "role_quality_band": band,
                        "reasons": list(dict.fromkeys(reasons)),
                    }
                )
        excluded.sort(
            key=lambda row: (
                0 if int(row["role_quality_band"]) >= minimum_band else 1,
                0 if row["free"] else 1,
                len(row["reasons"]),
                -int(row["role_quality_band"]),
                str(row["provider"]),
                str(row["model"]),
            )
        )
        selected = eligible[0] if eligible else None
        role_rows.append(
            {
                "role": role,
                "ready": bool(selected),
                "minimum_role_quality_band": minimum_band,
                "selected": (
                    {
                        "provider": selected.provider.name,
                        "model": selected.model,
                        "free": selected.provider.free,
                        "role_quality_band": _role_quality_band(selected, role),
                    }
                    if selected
                    else None
                ),
                "eligible_count": len(eligible),
                "why_not": excluded[:12],
            }
        )

    free_counts = Counter(
        choice.provider.billing_class or "permanent_free"
        for choice in all_choices
        if choice.provider.free
    )
    rotation_groups = Counter(
        (_model_family(choice), choice.model.lower()) for choice in all_choices
    )
    unguarded_trial_routes = [
        choice
        for choice in all_choices
        if choice.provider.free
        and choice.provider.billing_class == "trial_quota"
        and not choice.provider.trial_quota_guarded
    ]
    recommendations: list[str] = []
    if settings.configuration_warnings:
        recommendations.append("repair_or_override_credential_catalog_path")
    if unguarded_trial_routes:
        recommendations.append("verify_hard_stop_before_enabling_trial_quota_routes")
    blocked_roles = [row["role"] for row in role_rows if not row["ready"]]
    if blocked_roles:
        recommendations.append("qualify_free_role_candidates_or_explicitly_allow_budgeted_paid_routes")
    if not all_choices:
        recommendations.append("configure_at_least_one_provider")
    if settings.runtime_fallback_reason:
        recommendations.append("run_status_in_the_same_runtime_or_set_SMART_LLM_RUNTIME_DIR")

    catalog = settings.credential_catalog
    return {
        "schema": "smart_llm_router.doctor.v1",
        "generated_at": _now().isoformat(),
        "status": (
            "pass"
            if all(row["ready"] for row in role_rows)
            and not settings.configuration_warnings
            else "needs_attention"
        ),
        "network_calls": 0,
        "quality_target": quality_target,
        "paid_allowed": paid_allowed,
        "max_cost_usd": max_cost_usd,
        "configuration": {
            "warnings": list(settings.configuration_warnings),
            "credential_catalog_loaded": bool(catalog),
            "credential_catalog_path": catalog.path if catalog else None,
            "credential_catalog_providers": list(catalog.providers) if catalog else [],
            "credential_counts": dict(catalog.key_counts) if catalog else {},
            "credential_catalog_sectioned": bool(catalog and catalog.sectioned),
            "credential_counts_by_billing": [
                {"billing_class": section, "provider": provider, "count": count}
                for section, provider, count in (catalog.billing_key_counts if catalog else ())
            ],
            "credential_skipped_counts": [
                {"billing_class": section, "provider": provider, "count": count}
                for section, provider, count in (catalog.skipped_key_counts if catalog else ())
            ],
            "runtime_dir": str(settings.data_dir),
            "runtime_dir_source": settings.runtime_dir_source,
            "runtime_fallback_active": bool(settings.runtime_fallback_reason),
            "runtime_fallback_reason": settings.runtime_fallback_reason,
            "runtime_expected_dir": str(settings.runtime_expected_dir) if settings.runtime_expected_dir else None,
            "budget_authority_dir": str(settings.budget_authority_dir),
            "budget_authority_id": budget_authority_id(settings.budget_authority_dir),
            "budget_authority_runtime_independent": settings.budget_authority_dir != settings.data_dir,
            "legacy_budget_dirs": [str(path) for path in settings.legacy_budget_dirs],
        },
        "inventory": {
            "provider_count": len(settings.providers),
            "route_count": len(all_choices),
            "general_text_route_count": len(general_choices),
            "free_route_counts_by_billing_class": dict(sorted(free_counts.items())),
            "unguarded_trial_route_count": len(unguarded_trial_routes),
            "key_rotation_group_count": sum(1 for count in rotation_groups.values() if count > 1),
        },
        "roles": role_rows,
        "blocked_roles": blocked_roles,
        "recommendations": recommendations,
    }


def clear_route_state(settings: Settings) -> None:
    path = _state_path(settings)
    if path.exists():
        path.unlink()


def _compressed_image_bytes(path: Path) -> tuple[bytes, str]:
    max_side = int(os.getenv("SMART_LLM_VISION_MAX_SIDE", "1280") or "1280")
    jpeg_quality = int(os.getenv("SMART_LLM_VISION_JPEG_QUALITY", "82") or "82")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            from io import BytesIO

            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
            return buffer.getvalue(), "image/jpeg"
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "vision-image.jpg"
        try:
            subprocess.run(
                [
                    "sips",
                    "-s",
                    "format",
                    "jpeg",
                    "-s",
                    "formatOptions",
                    str(jpeg_quality),
                    "--resampleHeightWidthMax",
                    str(max_side),
                    str(path),
                    "--out",
                    str(out_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if out_path.exists() and out_path.stat().st_size > 0:
                return out_path.read_bytes(), "image/jpeg"
        except Exception:
            pass
    return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/png"


def _image_data_url(image_path: str | Path) -> str:
    path = Path(image_path).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"图片不存在：{path}")
    image_bytes, mime_type = _compressed_image_bytes(path)
    payload = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _image_hash(image_path: str | Path | None) -> str:
    if not image_path:
        return ""
    path = Path(image_path).expanduser()
    if not path.exists() or not path.is_file():
        return ""
    return sha256(path.read_bytes()).hexdigest()


def _messages_for_task(task: str, prompt: str, context: str | None, image_path: str | Path | None = None) -> list[dict[str, Any]]:
    system = SYSTEM_PROMPTS.get(task, SYSTEM_PROMPTS["draft"])
    user = prompt if context is None else "参考材料:\n" + context + "\n\n任务:\n" + prompt
    if image_path:
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            },
        ]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, int(ascii_chars / 4 + non_ascii_chars / 1.7))


def _message_text_for_estimate(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text") or ""))
            elif isinstance(part, dict) and part.get("type") == "image_url":
                text_parts.append("[image]")
        return "\n".join(text_parts)
    return str(content)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_estimate_tokens(_message_text_for_estimate(message)) + 4 for message in messages)


def describe_task_v2(
    task: str,
    prompt: str,
    context: str | None = None,
    *,
    input_modalities: list[str] | None = None,
) -> dict[str, Any]:
    """Return an explainable shadow classification without affecting routing."""
    task = normalize_task_type(task)
    latest = prompt.strip()
    text = f"{prompt}\n{context or ''}".strip()
    lowered = latest.lower()
    modalities = sorted(set(input_modalities or ["text"]))
    token_estimate = _estimate_tokens(text) if text else 0

    explicit_simple_intent = bool(re.fullmatch(
        r"(?:你好|您好|谢谢|感谢|收到|好的?|可以|明白了?|再见|hi|hello|thanks|ok|okay|"
        r"只(?:输出|回复)\s*[a-z0-9_-]{1,24})[!！。,.，?？\s]*",
        lowered,
        flags=re.IGNORECASE,
    ))
    context_dependent = bool(re.search(
        r"(?:刚才|之前|上面|前面|上一轮|前文|上述|按这个|照这个|基于这个)|"
        r"^(?:继续|接着|下一步|再来|往下|把这个|把那个|把它|修改它|改一下)",
        latest,
        flags=re.IGNORECASE,
    ))
    if re.search(
        r"(?:前文不存在|没有前文)|"
        r"(?:不要沿用|无需沿用|不(?:要|必)?参考).{0,10}(?:刚才|之前|上面|前文)",
        latest,
    ):
        context_dependent = False
    requires_tools = bool(re.search(
        r"(?:运行|执行).{0,12}(?:命令|测试|终端)|(?:读取|查看|修改|检查).{0,12}(?:文件|代码|日志|项目)|"
        r"(?:调用|使用).{0,8}(?:工具|终端|浏览器)|"
        r"(?:run|execute).{0,20}(?:command|test)|(?:read|modify|inspect).{0,20}(?:file|code|log|repo)",
        latest,
        flags=re.IGNORECASE,
    ))
    negated_tool_mention = bool(re.search(
        r"(?:不要|无需|不需要|不必|不调用|不使用).{0,16}"
        r"(?:运行|执行|读取|查看|修改|检查|调用|使用|测试|命令|终端|文件|代码|日志|项目|工具|浏览器)",
        latest,
        flags=re.IGNORECASE,
    ))
    if negated_tool_mention:
        requires_tools = False
    meta_literal_task = bool(re.search(
        r"(?:翻译|几个汉字|全称|标题格式|改写得更自然|"
        r"(?:解释|说明).{0,12}(?:这个词|这个短语|什么是|含义)|"
        r"列出.{0,12}(?:字|词)|一般性定义|通用.{0,8}建议|概念说明)",
        latest,
        flags=re.IGNORECASE,
    ))
    if meta_literal_task:
        requires_tools = False
    negative_scope_simple = negated_tool_mention and bool(re.search(
        r"(?:只|直接).{0,8}(?:写一句|回复|输出|解释|说明)",
        latest,
        flags=re.IGNORECASE,
    ))
    simple_intent = explicit_simple_intent or meta_literal_task or negative_scope_simple
    structured_output = bool(re.search(
        r"(?:严格|有效|只(?:输出|返回)).{0,12}(?:json|yaml|xml|schema)|"
        r"(?:结构化输出|json schema|valid json|structured output)",
        latest,
        flags=re.IGNORECASE,
    ))
    if meta_literal_task:
        structured_output = False
    strong_reasoning = task in {"audit", "verify"} or bool(re.search(
        r"(?:深度分析|深入研究|研究报告|根因分析|严谨推导|证明|安全审计|威胁模型|"
        r"deep analysis|research report|root cause|rigorous proof|security audit|threat model)",
        lowered,
    ))
    multi_step = bool(re.search(
        r"(?:多步骤|分阶段|完整流程|端到端|先.+再|第一步|第二步|"
        r"multi-step|step by step|end-to-end|first.+then)",
        lowered,
    ))
    technical_depth = bool(re.search(
        r"(?:架构|迁移|部署|并发|协议|工作流|系统设计|兼容性|"
        r"architecture|migration|deployment|concurrency|protocol|workflow|system design|compatibility)",
        lowered,
    ))
    broad_scope = bool(re.search(
        r"(?:多文件|跨文件|整个项目|完整项目|完整系统|大规模重构|多个模块|"
        r"跨团队|数据迁移.{0,20}(?:灾难恢复|回退|验收)|"
        r"multi-file|cross-file|entire project|complete system|large refactor|multiple modules)",
        lowered,
    ))
    if meta_literal_task:
        strong_reasoning = False
        multi_step = False
        technical_depth = False
        broad_scope = False
    constraint_hits = len(re.findall(
        r"(?:必须|不要|不能|保持|兼容|验证|测试|只允许|最多|至少|限定|"
        r"must|without|keep|compatible|verify|validate|at most|at least)",
        lowered,
    ))
    non_text = [item for item in modalities if item != "text"]

    signal_values = {
        "simple_intent": -0.22 if simple_intent else 0.0,
        "reasoning_depth": 0.22 if strong_reasoning else 0.0,
        "multi_step": 0.12 if multi_step else 0.0,
        "technical_depth": 0.10 if technical_depth else 0.0,
        "scope": 0.16 if broad_scope else 0.0,
        "constraints": min(0.12, constraint_hits * 0.03),
        "context_length": 0.10 if token_estimate > 12_000 else 0.06 if token_estimate > 4_500 else 0.0,
        "tool_requirement": 0.08 if requires_tools else 0.0,
        "structured_output": 0.06 if structured_output else 0.0,
        "input_modality": 0.06 if non_text else 0.0,
    }
    normalized_score = max(0.0, min(1.0, 0.38 + sum(signal_values.values())))
    initial_tier = "simple" if normalized_score < 0.30 else "balanced" if normalized_score < 0.65 else "deep"

    floor_reasons: list[str] = []
    minimum_tier = "simple"
    if strong_reasoning or broad_scope:
        minimum_tier = "deep"
        floor_reasons.append("strong_reasoning_or_broad_scope")
    elif context_dependent or requires_tools or structured_output or non_text:
        minimum_tier = "balanced"
        if context_dependent:
            floor_reasons.append("context_dependent")
        if requires_tools:
            floor_reasons.append("tools_required")
        if structured_output:
            floor_reasons.append("structured_output_required")
        if non_text:
            floor_reasons.append("non_text_input")

    simple_exclusions = [
        reason
        for condition, reason in (
            (not simple_intent, "no_explicit_simple_intent"),
            (context_dependent, "context_dependent"),
            (requires_tools, "tools_required"),
            (structured_output, "structured_output_required"),
            (bool(non_text), "non_text_input"),
            (strong_reasoning or multi_step or technical_depth or broad_scope, "complex_signal"),
        )
        if condition
    ]
    simple_eligible = simple_intent and not simple_exclusions
    tier_rank = {"simple": 0, "balanced": 1, "deep": 2}
    selected_tier = max((initial_tier, minimum_tier), key=tier_rank.__getitem__)
    distance = min(abs(normalized_score - 0.30), abs(normalized_score - 0.65))
    confidence = round(0.5 + 0.5 * (1 - math.exp(-12 * distance)), 3)
    ambiguity_fallback = confidence < 0.65 and tier_rank[minimum_tier] <= tier_rank["balanced"]
    if simple_eligible:
        selected_tier = "simple"
        confidence = 0.95
        ambiguity_fallback = False
    elif ambiguity_fallback:
        selected_tier = "balanced"

    return {
        "schema": "smart_llm_router.task_descriptor.v2",
        "mode": "shadow",
        "classification_version": "task-signals-v2-shadow",
        "input_fingerprint": sha256(text.encode("utf-8")).hexdigest()[:16],
        "normalized_score": round(normalized_score, 3),
        "initial_tier": initial_tier,
        "minimum_tier": minimum_tier,
        "selected_tier": selected_tier,
        "confidence": confidence,
        "ambiguity_fallback": ambiguity_fallback,
        "floor_reasons": floor_reasons,
        "simple_eligibility": {
            "eligible": simple_eligible,
            "exclusions": simple_exclusions,
        },
        "features": {
            "context_dependent": context_dependent,
            "requires_tools": requires_tools,
            "structured_output_required": structured_output,
            "input_modalities": modalities,
            "estimated_input_tokens": token_estimate,
        },
        "signals": [
            {"name": name, "contribution": round(value, 3), "triggered": value != 0}
            for name, value in signal_values.items()
        ],
        "routing_effect": "none",
    }


def _apply_task_descriptor_v2_activation(
    task: str,
    complexity: dict[str, Any],
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    requested = os.getenv("SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    eligible = task not in ROLE_TASKS
    applied = requested and eligible
    legacy_label = complexity.get("legacy_label", complexity["label"])
    descriptor["routing_effect"] = "non_role_complexity" if applied else "none"
    descriptor["mode"] = "controlled" if applied else "shadow"
    complexity["label"] = (
        {"simple": "simple", "balanced": "medium", "deep": "hard"}[descriptor["selected_tier"]]
        if applied
        else legacy_label
    )
    complexity["legacy_label"] = legacy_label
    complexity["complexity_source"] = "task_descriptor_v2" if applied else "legacy"
    complexity["activation"] = {
        "env": "SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED",
        "requested": requested,
        "eligible": eligible,
        "applied": applied,
        "rollback": "unset_or_set_false",
    }
    complexity["policy"] = (
        "free-only preferred"
        if complexity["label"] == "simple"
        else "free-first with paid fallback"
        if complexity["label"] == "medium"
        else "free-first, allow stronger fallback"
    )
    complexity["shadow_descriptor_v2"] = descriptor
    return complexity


def score_task_complexity(task: str, prompt: str, context: str | None = None) -> dict[str, Any]:
    task = normalize_task_type(task)
    text = (prompt + "\n" + (context or "")).strip()
    token_estimate = _estimate_tokens(text) if text else 0
    hard_patterns = (
        "架构", "审计", "安全", "规划", "设计", "重构", "多步骤", "复杂", "推理",
        "对比", "策略", "系统", "代码库", "agent", "workflow", "architecture",
        "audit", "refactor", "debug", "proof", "optimize",
    )
    simple_patterns = ("分类", "清洗", "纠错", "只输出", "json", "摘要", "提取", "改写")
    hard_hits = sum(1 for item in hard_patterns if item.lower() in text.lower())
    simple_hits = sum(1 for item in simple_patterns if item.lower() in text.lower())
    score = 0
    if task in {"draft", "qa"}:
        score += 1
    if task in VISION_TASKS:
        score += 1
    if task in {"transcript_correct", "audit", "code"}:
        score += 1
    if task in ROLE_TASKS:
        score += 2
    if task in {"clean", "classify"}:
        score -= 1
    if token_estimate > 1200:
        score += 1
    if token_estimate > 4500:
        score += 1
    if token_estimate > 12000:
        score += 1
    score += min(3, hard_hits)
    score -= min(2, simple_hits)
    label = "simple" if score <= 0 else "medium" if score <= 2 else "hard"
    complexity = {
        "label": label,
        "score": score,
        "token_estimate": token_estimate,
        "hard_hits": hard_hits,
        "simple_hits": simple_hits,
        "policy": "free-only preferred" if label == "simple" else "free-first with paid fallback" if label == "medium" else "free-first, allow stronger fallback",
    }
    return _apply_task_descriptor_v2_activation(
        task,
        complexity,
        describe_task_v2(task, prompt, context),
    )


def _cache_enabled() -> bool:
    return os.getenv("SMART_LLM_CACHE", "true").strip().lower() not in {"0", "false", "no", "off"}


CACHE_POLICY_VERSION = "cache-policy-v3"

JSON_SCHEMA_SUBSET_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "type",
        "const",
        "enum",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "properties",
        "required",
        "additionalProperties",
        "minProperties",
        "maxProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
)
JSON_SCHEMA_SUBSET_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)
JSON_SCHEMA_SUBSET_MAX_DEPTH = 16
JSON_SCHEMA_SUBSET_MAX_NODES = 256
JSON_SCHEMA_SUBSET_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _cache_key(
    *,
    task: str,
    prompt: str,
    context: str | None,
    prefer_free: bool,
    paid_fallback: bool,
    temperature: float,
    image_hash: str = "",
    provider: str | None = None,
    model: str | None = None,
    avoid_routes: list[str] | tuple[str, ...] | None = None,
    quality_target: str = "production",
    privacy: str = "external_allowed",
    allow_external: bool = False,
    max_cost_usd: float | None = None,
    max_output_tokens: int | None = None,
    thinking_mode: str = "auto",
    thinking_budget_tokens: int | None = None,
    final_answer_reserve_tokens: int | None = None,
    complexity_label: str = "",
    complexity_source: str = "legacy",
    complexity_version: str = "",
    openrouter_upstream_providers: list[str] | tuple[str, ...] | None = None,
    openrouter_allow_fallbacks: bool = True,
    openrouter_require_zdr: bool = False,
    openrouter_deny_data_collection: bool = False,
) -> str:
    payload = {
        "cache_policy_version": CACHE_POLICY_VERSION,
        "task": task,
        "prompt": prompt,
        "context": context or "",
        "image_hash": image_hash,
        "prefer_free": prefer_free,
        "paid_fallback": paid_fallback,
        "temperature": temperature,
        "provider": provider or "",
        "model": model or "",
        "avoid_routes": sorted(_avoid_route_set(avoid_routes)),
        "quality_target": quality_target,
        "privacy": privacy,
        "allow_external": allow_external,
        "max_cost_usd": max_cost_usd,
        "max_output_tokens": max_output_tokens,
        "thinking_mode": thinking_mode,
        "thinking_budget_tokens": thinking_budget_tokens,
        "final_answer_reserve_tokens": final_answer_reserve_tokens,
        "complexity_label": complexity_label,
        "complexity_source": complexity_source,
        "complexity_version": complexity_version,
        "openrouter_upstream_providers": sorted(
            str(item).strip().lower()
            for item in (openrouter_upstream_providers or ())
            if str(item).strip()
        ),
        "openrouter_allow_fallbacks": openrouter_allow_fallbacks,
        "openrouter_require_zdr": openrouter_require_zdr,
        "openrouter_deny_data_collection": openrouter_deny_data_collection,
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _text_fingerprint(text: str | None) -> str:
    if not text:
        return ""
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def _reject_nonfinite_json_constant(value: str) -> Any:
    raise ValueError(f"nonfinite_json_constant:{value}")


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_object_key:{key}")
        result[key] = value
    return result


def _strict_json_loads(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=_reject_nonfinite_json_constant,
        object_pairs_hook=_reject_duplicate_json_pairs,
    )


def _json_value_equality_key(value: Any) -> tuple[Any, ...] | None:
    """Return a hashable JSON Schema equality key; JSON numbers compare by value."""
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, int):
        return ("number", Decimal(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return ("number", Decimal(str(value)))
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        children = [_json_value_equality_key(item) for item in value]
        if any(child is None for child in children):
            return None
        return ("array", *children)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            return None
        children = [
            (key, _json_value_equality_key(child))
            for key, child in sorted(value.items())
        ]
        if any(child is None for _, child in children):
            return None
        return ("object", *children)
    return None


def _json_value_fingerprint(value: Any) -> tuple[Any, ...] | None:
    return _json_value_equality_key(value)


def _json_schema_subset_error(
    schema: Any,
    *,
    path: str = "$",
    depth: int = 0,
    nodes: list[int] | None = None,
) -> str | None:
    """Validate the bounded, dependency-free JSON Schema subset before use."""
    if not isinstance(schema, dict):
        return f"{path}:schema_must_be_object"
    if depth > JSON_SCHEMA_SUBSET_MAX_DEPTH:
        return f"{path}:schema_depth_exceeded"
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > JSON_SCHEMA_SUBSET_MAX_NODES:
        return f"{path}:schema_node_limit_exceeded"
    if any(not isinstance(keyword, str) for keyword in schema):
        return f"{path}:schema_keyword_must_be_string"
    unknown = sorted(set(schema) - JSON_SCHEMA_SUBSET_KEYWORDS)
    if unknown:
        return f"{path}:unsupported_keyword:{unknown[0]}"

    for keyword in ("$schema", "$id", "$comment", "title", "description"):
        if keyword in schema and not isinstance(schema[keyword], str):
            return f"{path}:{keyword}_must_be_string"
    dialect = schema.get("$schema")
    if isinstance(dialect, str) and dialect.rstrip("#") != JSON_SCHEMA_SUBSET_DIALECT:
        return f"{path}:unsupported_schema_dialect"
    for keyword in ("deprecated", "readOnly", "writeOnly"):
        if keyword in schema and not isinstance(schema[keyword], bool):
            return f"{path}:{keyword}_must_be_boolean"
    if "default" in schema and _json_value_fingerprint(schema["default"]) is None:
        return f"{path}:default_must_be_finite_json"
    if "examples" in schema:
        examples = schema["examples"]
        if not isinstance(examples, list) or any(_json_value_fingerprint(item) is None for item in examples):
            return f"{path}:examples_must_be_finite_json_array"

    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        if expected_type not in JSON_SCHEMA_SUBSET_TYPES:
            return f"{path}:unsupported_type:{expected_type}"
    elif isinstance(expected_type, list):
        if (
            not expected_type
            or any(not isinstance(item, str) or item not in JSON_SCHEMA_SUBSET_TYPES for item in expected_type)
            or len(set(expected_type)) != len(expected_type)
        ):
            return f"{path}:type_array_invalid"
    elif expected_type is not None:
        return f"{path}:type_must_be_string_or_array"

    if "const" in schema and _json_value_fingerprint(schema["const"]) is None:
        return f"{path}:const_must_be_finite_json"
    if "enum" in schema:
        enum = schema["enum"]
        fingerprints = [_json_value_fingerprint(item) for item in enum] if isinstance(enum, list) else []
        if not isinstance(enum, list) or not enum or any(item is None for item in fingerprints):
            return f"{path}:enum_must_be_nonempty_finite_json_array"
        if len(set(fingerprints)) != len(fingerprints):
            return f"{path}:enum_values_must_be_unique"

    for keyword in ("minProperties", "maxProperties", "minItems", "maxItems", "minLength", "maxLength"):
        value = schema.get(keyword)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return f"{path}:{keyword}_must_be_nonnegative_integer"
    for lower, upper in (
        ("minProperties", "maxProperties"),
        ("minItems", "maxItems"),
        ("minLength", "maxLength"),
    ):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            return f"{path}:{lower}_exceeds_{upper}"
    for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        value = schema.get(keyword)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            return f"{path}:{keyword}_must_be_finite_number"
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        return f"{path}:uniqueItems_must_be_boolean"
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        return f"{path}:additionalProperties_schema_not_supported"

    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or len(set(required)) != len(required)
    ):
        return f"{path}:required_must_be_unique_string_array"

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            return f"{path}:properties_must_be_object"
        for field, child in properties.items():
            if not isinstance(field, str):
                return f"{path}:property_name_must_be_string"
            error = _json_schema_subset_error(
                child,
                path=f"{path}.properties.{field}",
                depth=depth + 1,
                nodes=nodes,
            )
            if error:
                return error
    items = schema.get("items")
    if items is not None:
        error = _json_schema_subset_error(items, path=f"{path}.items", depth=depth + 1, nodes=nodes)
        if error:
            return error
    for keyword in ("allOf", "anyOf", "oneOf"):
        children = schema.get(keyword)
        if children is None:
            continue
        if not isinstance(children, list) or not children:
            return f"{path}:{keyword}_must_be_nonempty_schema_array"
        for index, child in enumerate(children):
            error = _json_schema_subset_error(
                child,
                path=f"{path}.{keyword}[{index}]",
                depth=depth + 1,
                nodes=nodes,
            )
            if error:
                return error
    if "not" in schema:
        error = _json_schema_subset_error(schema["not"], path=f"{path}.not", depth=depth + 1, nodes=nodes)
        if error:
            return error
    return None


def _required_structured_output_spec(
    complexity: dict[str, Any],
    prompt: str,
    *,
    task: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    features = complexity.get("shadow_descriptor_v2", {}).get("features", {})
    combined = "\n".join(part for part in (prompt, context or "") if part)
    lowered = combined.lower()
    governed_role = normalize_task_type(task or "qa") in {"audit", "verify", "plan_audit"}
    explicit_json = bool(
        "json" in lowered
        and (
            features.get("structured_output_required")
            or re.search(r"(?:json[- ]?only|only\s+(?:raw\s+)?json|strict\s+json|raw\s+json)", lowered)
            or re.search(r"(?:\u53ea|\u4ec5|\u4e25\u683c|\u539f\u59cb).{0,12}json", lowered)
        )
    )
    schema_driven = bool(
        re.search(r"json\s*schema", lowered)
        or re.search(r'"(?:\$schema|required|properties)"\s*:', combined)
    )
    schema: dict[str, Any] | None = None
    if schema_driven:
        decoder = json.JSONDecoder(
            parse_constant=_reject_nonfinite_json_constant,
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
        marker = re.search(r"json\s*schema", combined, flags=re.IGNORECASE)
        search_start = marker.end() if marker else 0
        for match in re.finditer(r"\{", combined[search_start:]):
            try:
                candidate, _ = decoder.raw_decode(combined[search_start + match.start() :])
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(candidate, dict) and any(
                key in candidate for key in ("$schema", "type", "properties", "required")
            ):
                schema = candidate
                break
    if schema_driven and schema is None:
        raise ValueError("governed_json_schema_missing_or_invalid:blocked_before_send")
    if schema is not None:
        schema_error = _json_schema_subset_error(schema)
        if schema_error:
            raise ValueError(f"governed_json_schema_unsupported:{schema_error}:blocked_before_send")
    required_fields = [
        field
        for field in ((schema or {}).get("required") or [])
        if isinstance(field, str) and field
    ]
    required = governed_role or explicit_json or schema_driven
    return {
        "required": required,
        "format": "json" if required else None,
        "governed_role": governed_role,
        "schema_driven": schema_driven,
        "schema": schema,
        "required_fields": required_fields,
    }


def _required_structured_output_format(complexity: dict[str, Any], prompt: str) -> str | None:
    return _required_structured_output_spec(complexity, prompt)["format"]


def _validate_structured_output(
    content: str,
    required_format: str | None,
    *,
    finish_reason: str | None = None,
    output_reached_cap: bool = False,
    required_fields: list[str] | tuple[str, ...] | None = None,
    schema: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    if required_format != "json":
        return True, None
    normalized_finish_reason = (finish_reason or "").strip().lower()
    if normalized_finish_reason == "length":
        return False, "structured_output_truncated_finish_reason_length"
    if normalized_finish_reason and normalized_finish_reason != "stop":
        return False, "structured_output_nonterminal_finish_reason"
    stripped = content.strip()
    if "```" in stripped:
        return False, "structured_output_code_fence_forbidden"
    if not stripped.startswith("{") or not stripped.endswith("}"):
        if output_reached_cap:
            return False, "structured_output_truncated_at_output_cap"
        return False, "structured_output_not_one_complete_raw_json_object"
    try:
        parsed = _strict_json_loads(stripped)
    except (json.JSONDecodeError, TypeError, ValueError):
        if output_reached_cap:
            return False, "structured_output_truncated_at_output_cap"
        return False, "strict_json_parse_failed"
    if not isinstance(parsed, dict):
        return False, "structured_output_root_must_be_object"
    missing = [field for field in (required_fields or ()) if field not in parsed]
    if missing:
        return False, "structured_output_missing_required_fields"
    if schema is not None and _json_schema_subset_error(schema):
        return False, "structured_output_schema_unsupported"
    if schema is not None and not _json_schema_required_fields_present(parsed, schema):
        return False, "structured_output_missing_required_fields"
    if schema is not None and not _json_schema_value_matches(parsed, schema):
        return False, "structured_output_schema_validation_failed"
    return True, None


def _json_schema_required_fields_present(value: Any, schema: Any) -> bool:
    if not isinstance(schema, dict):
        return True
    required = schema.get("required")
    properties = schema.get("properties")
    if isinstance(required, list):
        if not isinstance(value, dict):
            return False
        if any(isinstance(field, str) and field not in value for field in required):
            return False
    if isinstance(properties, dict) and isinstance(value, dict):
        for field, child_schema in properties.items():
            if field in value and not _json_schema_required_fields_present(value[field], child_schema):
                return False
    items = schema.get("items")
    if isinstance(items, dict) and isinstance(value, list):
        return all(_json_schema_required_fields_present(item, items) for item in value)
    return True


def _json_schema_type_matches(value: Any, expected_type: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value)),
        "integer": (
            isinstance(value, int)
            and not isinstance(value, bool)
        )
        or (
            isinstance(value, float)
            and math.isfinite(value)
            and value.is_integer()
        ),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected_type, False)


def _json_schema_value_matches(value: Any, schema: Any) -> bool:
    """Validate the deterministic JSON Schema subset used by governed tasks."""
    if not isinstance(schema, dict):
        return False
    value_fingerprint = _json_value_fingerprint(value)
    if value_fingerprint is None:
        return False
    if "const" in schema and value_fingerprint != _json_value_fingerprint(schema["const"]):
        return False
    enum = schema.get("enum")
    if isinstance(enum, list) and value_fingerprint not in {
        _json_value_fingerprint(item) for item in enum
    }:
        return False
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_json_schema_type_matches(value, item) for item in expected_type):
            return False
    elif isinstance(expected_type, str):
        if not _json_schema_type_matches(value, expected_type):
            return False
    all_of = schema.get("allOf")
    if isinstance(all_of, list) and not all(_json_schema_value_matches(value, child) for child in all_of):
        return False
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(_json_schema_value_matches(value, child) for child in any_of):
        return False
    one_of = schema.get("oneOf")
    if isinstance(one_of, list) and sum(_json_schema_value_matches(value, child) for child in one_of) != 1:
        return False
    not_schema = schema.get("not")
    if isinstance(not_schema, dict) and _json_schema_value_matches(value, not_schema):
        return False
    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list) and any(field not in value for field in required):
            return False
        min_properties = schema.get("minProperties")
        max_properties = schema.get("maxProperties")
        if isinstance(min_properties, int) and len(value) < min_properties:
            return False
        if isinstance(max_properties, int) and len(value) > max_properties:
            return False
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            return False
        for field, child_schema in properties.items():
            if field in value and not _json_schema_value_matches(value[field], child_schema):
                return False
    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            return False
        if isinstance(max_items, int) and len(value) > max_items:
            return False
        if schema.get("uniqueItems") is True:
            item_fingerprints = [_json_value_fingerprint(item) for item in value]
            if len(set(item_fingerprints)) != len(item_fingerprints):
                return False
        items = schema.get("items")
        if isinstance(items, dict) and not all(_json_schema_value_matches(item, items) for item in value):
            return False
    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return False
        if isinstance(max_length, int) and len(value) > max_length:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return False
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            return False
    return True


def _structured_response_format(spec: dict[str, Any]) -> dict[str, Any] | None:
    if spec.get("format") != "json":
        return None
    schema = spec.get("schema")
    if isinstance(schema, dict):
        schema_error = _json_schema_subset_error(schema)
        if schema_error:
            raise ValueError(f"governed_json_schema_unsupported:{schema_error}:blocked_before_send")
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_llm_router_output",
                "strict": True,
                "schema": schema,
            },
        }
    return {"type": "json_object"}


def _schema_required_field_count(schema: Any) -> int:
    if not isinstance(schema, dict):
        return 0
    required = schema.get("required")
    count = sum(1 for field in required if isinstance(field, str) and field) if isinstance(required, list) else 0
    properties = schema.get("properties")
    if isinstance(properties, dict):
        count += sum(_schema_required_field_count(child) for child in properties.values())
    items = schema.get("items")
    if isinstance(items, dict):
        count += _schema_required_field_count(items)
    return count


def _sanitized_completion_metadata(usage: dict[str, Any]) -> dict[str, Any]:
    metadata = usage.get("_completion_metadata")
    if not isinstance(metadata, dict):
        return {"finish_reason": None, "output_reached_requested_token_limit": False}
    return {
        "finish_reason": metadata.get("finish_reason"),
        "output_reached_requested_token_limit": bool(metadata.get("output_reached_requested_token_limit")),
    }


def _sanitized_routing_metadata(usage: dict[str, Any]) -> dict[str, Any]:
    metadata = usage.get("_routing_metadata")
    if not isinstance(metadata, dict):
        return {
            "openrouter_controls_applied": False,
            "requested_upstream_providers": [],
            "provider_fallbacks_allowed": True,
            "zdr_required": False,
            "data_collection_denied": False,
            "structured_response_requested": False,
            "served_provider": None,
            "served_model": None,
            "generation_id": None,
        }
    upstream = metadata.get("requested_upstream_providers")
    return {
        "openrouter_controls_applied": bool(metadata.get("openrouter_controls_applied")),
        "requested_upstream_providers": [
            str(item) for item in upstream if isinstance(item, str)
        ] if isinstance(upstream, list) else [],
        "provider_fallbacks_allowed": bool(metadata.get("provider_fallbacks_allowed", True)),
        "zdr_required": bool(metadata.get("zdr_required")),
        "data_collection_denied": bool(metadata.get("data_collection_denied")),
        "structured_response_requested": bool(metadata.get("structured_response_requested")),
        "served_provider": metadata.get("served_provider") if isinstance(metadata.get("served_provider"), str) else None,
        "served_model": metadata.get("served_model") if isinstance(metadata.get("served_model"), str) else None,
        "generation_id": metadata.get("generation_id") if isinstance(metadata.get("generation_id"), str) else None,
    }


def _load_response_cache(settings: Settings) -> dict[str, Any]:
    raw = _load_json(_cache_path(settings))
    return raw if isinstance(raw, dict) else {}


def _save_response_cache(settings: Settings, cache: dict[str, Any]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    max_items = int(os.getenv("SMART_LLM_CACHE_MAX_ITEMS", "500") or "500")
    if len(cache) > max_items:
        ordered = sorted(cache.items(), key=lambda item: item[1].get("created_at", ""))
        cache = dict(ordered[-max_items:])
    _cache_path(settings).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cached_choice_policy_status(
    settings: Settings,
    cached: dict[str, Any],
    *,
    task: str,
    prefer_free: bool,
    paid_fallback: bool,
    provider: str | None,
    model: str | None,
    quality_target: str,
    privacy: str,
    allow_external: bool,
    max_cost_usd: float | None,
    input_tokens: int,
) -> tuple[LLMChoice | None, str | None]:
    cached_provider = str(cached.get("provider") or "")
    cached_model = str(cached.get("model") or "")
    choices = _model_choices(settings, task=task, only_free=False)
    choice = next(
        (
            item
            for item in choices
            if item.provider.name == cached_provider and item.model == cached_model
        ),
        None,
    )
    if choice is None:
        return None, "route_not_currently_configured"
    if prefer_free and choice.provider.free and not _free_only_eligible_provider(choice.provider):
        return None, "free_route_not_currently_eligible"
    if prefer_free and not paid_fallback and not choice.provider.free:
        return None, "paid_route_not_allowed"
    if privacy == "local_only" and not allow_external and not _is_trusted_local_choice(choice):
        return None, "local_only_route_mismatch"
    if not _choice_matches_provider(choice, provider):
        return None, "provider_filter_mismatch"
    if not _choice_matches_model(choice, model):
        return None, "model_filter_mismatch"
    if task in ROLE_TASKS and _role_quality_band(choice, task) < _minimum_role_quality_band(quality_target):
        return None, "quality_floor_mismatch"
    budget = _budget_status(choice, input_tokens, max_cost_usd)
    if not budget["eligible"]:
        return None, f"budget_gate:{budget['reason']}"
    return choice, None


def _append_ledger(settings: Settings, row: dict[str, Any]) -> str:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ledger_id = sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    row = {"id": ledger_id, **row}
    with _ledger_path(settings).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return ledger_id


def read_cost_ledger(settings: Settings, limit: int = 20) -> list[dict[str, Any]]:
    path = _ledger_path(settings)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:] if limit > 0 else rows


INFRASTRUCTURE_FAILURE_TERMS = (
    "[errno 8]",
    "could not resolve host",
    "name or service not known",
    "network is unreachable",
    "no route to host",
    "connection refused",
    "connection reset by peer",
    "nodename nor servname provided",
    "temporary failure in name resolution",
)


def classify_route_failure(error: str) -> str:
    text = error.strip().lower()
    if any(term in text for term in INFRASTRUCTURE_FAILURE_TERMS):
        return "infrastructure"
    if any(term in text for term in ("429", "rate limit", "rate_limit", "too many requests", "quota", "resource_exhausted")):
        return "quota"
    if any(term in text for term in ("401", "unauthorized", "authentication", "invalid api key")):
        return "authentication"
    if "403" in text or "forbidden" in text:
        return "permission_denied"
    if any(term in text for term in ("404", "410", "model not found", "does not exist", "unsupported model")):
        return "unavailable_model"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(term in text for term in ("empty response", "empty output", "returned empty", "返回空内容", "空响应")):
        return "empty_output"
    return "provider_error"


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 3)


def route_performance_stats(
    settings: Settings,
    *,
    task: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    normalized_task = normalize_task_type(task) if task else None
    rows = read_cost_ledger(settings, limit=max(0, limit))
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    events_scanned = 0
    for row in rows:
        event = str(row.get("event") or "")
        if event not in {"model_call", "model_failure"}:
            continue
        row_task = normalize_task_type(str(row.get("task") or "draft"))
        if normalized_task and row_task != normalized_task:
            continue
        provider = str(row.get("provider") or "").strip()
        model = str(row.get("model") or "").strip()
        if not provider or not model:
            continue
        events_scanned += 1
        key = (row_task, provider.lower(), model.lower())
        aggregate = grouped.setdefault(
            key,
            {
                "task": row_task,
                "provider": provider,
                "model": model,
                "successes": 0,
                "route_failures": 0,
                "infrastructure_failures": 0,
                "successful_latencies": [],
                "observed_estimated_cost_usd": 0.0,
                "failure_classes": Counter(),
                "last_observed_at": None,
            },
        )
        created_at = str(row.get("created_at") or "") or None
        if created_at and (not aggregate["last_observed_at"] or created_at > aggregate["last_observed_at"]):
            aggregate["last_observed_at"] = created_at
        cost = row.get("estimated_cost_usd")
        if isinstance(cost, (int, float)):
            aggregate["observed_estimated_cost_usd"] += float(cost)
        if event == "model_call":
            aggregate["successes"] += 1
            latency = row.get("latency_s")
            if isinstance(latency, (int, float)) and latency >= 0:
                aggregate["successful_latencies"].append(float(latency))
            continue
        failure_class = str(row.get("failure_class") or classify_route_failure(str(row.get("error") or "")))
        aggregate["failure_classes"][failure_class] += 1
        if failure_class == "infrastructure":
            aggregate["infrastructure_failures"] += 1
        else:
            aggregate["route_failures"] += 1

    routes: list[dict[str, Any]] = []
    for aggregate in grouped.values():
        successes = int(aggregate["successes"])
        route_failures = int(aggregate["route_failures"])
        health_samples = successes + route_failures
        success_rate = successes / health_samples if health_samples else None
        smoothed_success_rate = (successes + 1) / (health_samples + 2)
        latencies = list(aggregate.pop("successful_latencies"))
        failure_classes = dict(sorted(aggregate.pop("failure_classes").items()))
        aggregate["health_samples"] = health_samples
        aggregate["success_rate"] = round(success_rate, 4) if success_rate is not None else None
        aggregate["smoothed_success_rate"] = round(smoothed_success_rate, 4)
        aggregate["degraded"] = health_samples >= ROUTE_HEALTH_MIN_SAMPLES and success_rate is not None and success_rate < 0.5
        aggregate["successful_latency_mean_s"] = round(sum(latencies) / len(latencies), 3) if latencies else None
        aggregate["successful_latency_p95_s"] = _percentile_95(latencies)
        aggregate["observed_estimated_cost_usd"] = round(float(aggregate["observed_estimated_cost_usd"]), 8)
        aggregate["failure_classes"] = failure_classes
        routes.append(aggregate)
    routes.sort(key=lambda row: (row["task"], row["provider"].lower(), row["model"].lower()))
    return {
        "generated_at": _now().isoformat(),
        "task": normalized_task,
        "ledger_limit": limit,
        "model_events_scanned": events_scanned,
        "health_min_samples": ROUTE_HEALTH_MIN_SAMPLES,
        "infrastructure_failures_excluded_from_health": True,
        "routes": routes,
    }


def _route_history_map(
    settings: Settings,
    *,
    task: str | None = None,
    limit: int = 1000,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    report = route_performance_stats(settings, task=task, limit=limit)
    return {
        (row["task"], row["provider"].lower(), row["model"].lower()): row
        for row in report["routes"]
    }


def _choice_route_history(
    history: dict[tuple[str, str, str], dict[str, Any]],
    task: str,
    choice: LLMChoice,
) -> dict[str, Any] | None:
    return history.get((normalize_task_type(task), choice.provider.name.lower(), choice.model.lower()))


def _command_path(name: str) -> str | None:
    return shutil.which(name)


def _whisper_cpp_no_gpu_enabled() -> bool:
    return os.getenv("SMART_LLM_ASR_WHISPER_CPP_NO_GPU", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _whisper_cpp_transcribe_command(
    command: str,
    model_path: str | Path,
    wav_path: Path,
    language: str,
    output_stem: Path,
    *,
    no_gpu: bool,
) -> list[str]:
    args = [command]
    if no_gpu:
        args.append("-ng")
    args.extend(
        [
            "-m",
            str(Path(model_path).expanduser()),
            "-f",
            str(wav_path),
            "-l",
            language,
            "-otxt",
            "-osrt",
            "-of",
            str(output_stem),
        ]
    )
    return args


def asr_status(settings: Settings | None = None) -> dict[str, Any]:
    model_path = os.getenv("SMART_LLM_ASR_WHISPER_CPP_MODEL", "").strip()
    whisper_cpp_command = _command_path("whisper-cli") or _command_path("whisper-cpp")
    mlx_ready = bool(importlib.util.find_spec("mlx_whisper"))
    return {
        "ffmpeg": _command_path("ffmpeg"),
        "backends": {
            "whisper_cpp": {
                "command": whisper_cpp_command,
                "model": model_path or None,
                "no_gpu": _whisper_cpp_no_gpu_enabled(),
                "ready": bool(whisper_cpp_command and model_path and Path(model_path).expanduser().exists()),
            },
            "openai_whisper": {
                "command": _command_path("whisper"),
                "ready": bool(_command_path("whisper")),
            },
            "mlx_whisper": {
                "module": mlx_ready,
                "ready": mlx_ready,
            },
        },
        "recommended_for_zh_video": "whisper.cpp with a multilingual ggml model, or mlx-whisper when Python workflow is preferred",
        "data_dir": str(settings.data_dir if settings else Path.home() / ".smart-llm-router"),
    }


def _billable_output_reserve_tokens(choice: LLMChoice, output_tokens: int) -> int:
    multiplier = MODEL_BILLABLE_OUTPUT_RESERVE_MULTIPLIER.get(choice.model.lower(), 1.0)
    overhead = MODEL_BILLABLE_OUTPUT_RESERVE_OVERHEAD.get(choice.model.lower(), 0)
    return max(1, math.ceil(output_tokens * multiplier) + overhead)


def _validate_budget_ceiling(value: float | None, *, name: str, strictly_positive: bool) -> float | None:
    if value is None:
        return None
    try:
        ceiling = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须为有限数") from exc
    if not math.isfinite(ceiling):
        raise ValueError(f"{name} 必须为有限数")
    if strictly_positive and ceiling <= 0:
        raise ValueError(f"{name} 必须为有限正数")
    if not strictly_positive and ceiling < 0:
        raise ValueError(f"{name} 必须为有限非负数")
    return ceiling


def _validate_input_token_guard_factor(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        factor = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("input_token_guard_factor 必须为有限正数") from exc
    minimum = max(
        DEFAULT_PAID_INPUT_TOKEN_GUARD_FACTOR,
        *PROVIDER_INPUT_TOKEN_GUARD_FACTORS.values(),
        *MODEL_INPUT_TOKEN_GUARD_FACTORS.values(),
    )
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("input_token_guard_factor 必须为有限正数")
    if factor < minimum:
        raise ValueError(f"input_token_guard_factor 不得低于当前安全下限 {minimum}")
    return factor


def _guarded_input_token_evidence(
    choice: LLMChoice,
    raw_input_tokens: int,
    *,
    guard_factor: float | None = None,
) -> dict[str, Any]:
    if isinstance(raw_input_tokens, bool) or not isinstance(raw_input_tokens, int):
        raise ValueError("raw_input_tokens_est 必须为非负整数")
    if raw_input_tokens < 0 or raw_input_tokens > MAX_GUARDED_INPUT_TOKENS:
        raise ValueError("raw_input_tokens_est 超出安全范围")
    explicit = _validate_input_token_guard_factor(guard_factor)
    selected = max(
        DEFAULT_PAID_INPUT_TOKEN_GUARD_FACTOR,
        PROVIDER_INPUT_TOKEN_GUARD_FACTORS.get(choice.provider.name, 1.0),
        MODEL_INPUT_TOKEN_GUARD_FACTORS.get(choice.model.lower(), 1.0),
        explicit or 1.0,
    )
    overhead = MODEL_INPUT_TOKEN_GUARD_OVERHEAD.get(choice.model.lower(), 0)
    if not math.isfinite(selected) or selected <= 0:
        raise ValueError("输入 token 安全系数必须为有限正数")
    try:
        guarded_decimal = (
            Decimal(raw_input_tokens) * Decimal(str(selected)) + Decimal(overhead)
        ).to_integral_value(rounding=ROUND_CEILING)
        guarded = int(guarded_decimal)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise ValueError("guarded_input_tokens 计算失败") from exc
    if guarded < raw_input_tokens or guarded > MAX_GUARDED_INPUT_TOKENS:
        raise ValueError("guarded_input_tokens 超出安全范围")
    return {
        "raw_input_tokens_est": raw_input_tokens,
        "guarded_input_tokens": guarded,
        "guard_method": (
            "provider_model_conservative_factor_plus_overhead"
            if overhead
            else "provider_model_conservative_factor"
        ),
        "guard_factor": selected,
        "guard_overhead_tokens": overhead,
    }


def _budget_evidence_fields(budget: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_input_tokens_est": budget.get("raw_input_tokens_est"),
        "guarded_input_tokens": budget.get("guarded_input_tokens"),
        "guard_method": budget.get("guard_method"),
        "guard_factor": budget.get("guard_factor"),
        "guard_overhead_tokens": budget.get("guard_overhead_tokens"),
        "reserved_output_tokens": budget.get("reserved_output_tokens"),
        "projected_cost_usd": budget.get("projected_cost_usd"),
        "spend_ceiling_semantics": "local_forecast_guard_not_provider_enforced",
        "settlement_usage_authority": "provider_reported_usage",
    }


def _budget_status(
    choice: LLMChoice,
    input_tokens: int,
    max_cost_usd: float | None,
    output_tokens: int = 1024,
    *,
    input_token_guard_factor: float | None = None,
) -> dict[str, Any]:
    reserved_output_tokens = (
        _billable_output_reserve_tokens(choice, output_tokens)
        if max_cost_usd is not None and not choice.provider.free
        else output_tokens
    )
    token_evidence = (
        _guarded_input_token_evidence(choice, input_tokens, guard_factor=input_token_guard_factor)
        if max_cost_usd is not None and not choice.provider.free
        else {
            "raw_input_tokens_est": input_tokens,
            "guarded_input_tokens": input_tokens,
            "guard_method": "not_applied_free_or_unbudgeted",
            "guard_factor": 1.0,
            "guard_overhead_tokens": 0,
        }
    )
    projected = _estimated_cost_usd(choice, token_evidence["guarded_input_tokens"], reserved_output_tokens)
    base = {**token_evidence, "projected_cost_usd": projected, "reserved_output_tokens": reserved_output_tokens}
    try:
        max_cost_usd = _validate_budget_ceiling(
            max_cost_usd,
            name="max_cost_usd",
            strictly_positive=False,
        )
    except ValueError:
        return {**base, "eligible": False, "reason": "invalid_cost_limit_fails_closed"}
    if max_cost_usd is None or choice.provider.free:
        return {**base, "eligible": True, "reason": None}
    if projected is None:
        return {**base, "eligible": False, "reason": "unknown_price_fails_closed"}
    if projected > max_cost_usd:
        return {**base, "eligible": False, "reason": "projected_cost_exceeds_limit"}
    return {**base, "eligible": True, "reason": None}


def _max_output_tokens_for_budget(
    choice: LLMChoice,
    input_tokens: int,
    max_cost_usd: float | None,
    *,
    hard_cap: int = 4096,
    input_token_guard_factor: float | None = None,
) -> int | None:
    max_cost_usd = _validate_budget_ceiling(
        max_cost_usd,
        name="max_cost_usd",
        strictly_positive=False,
    )
    if max_cost_usd is None or choice.provider.free:
        return None
    input_price = _price_per_million(choice, "input")
    output_price = _price_per_million(choice, "output")
    if input_price is None or output_price is None or output_price <= 0:
        return None
    guarded = _guarded_input_token_evidence(
        choice,
        input_tokens,
        guard_factor=input_token_guard_factor,
    )["guarded_input_tokens"]
    input_cost = guarded * input_price / 1_000_000
    remaining = max(0.0, max_cost_usd - input_cost)
    multiplier = MODEL_BILLABLE_OUTPUT_RESERVE_MULTIPLIER.get(choice.model.lower(), 1.0)
    overhead = MODEL_BILLABLE_OUTPUT_RESERVE_OVERHEAD.get(choice.model.lower(), 0)
    affordable_envelope = int(remaining * 1_000_000 / output_price * 0.95)
    affordable = int(max(0, affordable_envelope - overhead) / multiplier)
    return max(1, min(hard_cap, affordable))


def recommend_route(
    settings: Settings,
    *,
    task: str,
    prompt: str,
    context: str | None = None,
    prefer_free: bool = True,
    paid_fallback: bool = True,
    quality_target: str = "production",
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    task = normalize_task_type(task)
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"不支持的质量档位：{quality_target}")
    _maybe_auto_discover_free_pool(settings)
    complexity = score_task_complexity(task, prompt, context)
    states = _load_route_state(settings)
    evidence = _load_route_health(settings)
    route_history = _route_history_map(settings, task=task)
    input_tokens = complexity["token_estimate"] + 128
    free = [
        choice
        for choice in _model_choices(settings, task=task, only_free=True)
        if _is_execution_eligible_choice(settings, choice, states, evidence)
    ]
    paid = [
        choice
        for choice in (_paid_fallback_choices(settings, task, quality_target) if paid_fallback else [])
        if _is_execution_eligible_choice(settings, choice, states, evidence)
    ]
    if complexity["label"] == "simple" and prefer_free and task not in VISION_TASKS and task not in ROLE_TASKS and task != "transcript_correct":
        paid = []
    minimum_role_band = _minimum_role_quality_band(quality_target) if task in ROLE_TASKS else None
    if task in ROLE_TASKS:
        role_ordered = [
            choice
            for choice in _role_policy_choices(
                settings,
                role=task,
                quality_target=quality_target,
                input_tokens=input_tokens,
                max_cost_usd=max_cost_usd,
                paid_allowed=paid_fallback,
                history=route_history,
            )
            if _is_execution_eligible_choice(settings, choice, states, evidence)
        ]
        ordered = role_ordered
        prefer_free = bool(ordered and ordered[0].provider.free)
    else:
        ordered = _dedupe_model_routes((free + paid) if prefer_free else (paid + free))
    return {
        "task": task,
        "complexity": complexity,
        "policy": {
            "prefer_free": prefer_free,
            "paid_fallback": bool(paid),
            "quality_target": quality_target,
            "max_cost_usd": max_cost_usd,
            "simple_tasks_disable_paid_by_default": True,
            "minimum_role_quality_band": minimum_role_band,
            "role_selection_rule": "complexity_sets_quality_floor_then_route_health_then_budget_then_retry_adjusted_expected_total_cost_then_latency",
            "historical_health_min_samples": ROUTE_HEALTH_MIN_SAMPLES,
            "infrastructure_failures_excluded_from_health": True,
            "role_tasks_force_paid": False,
            "failed_models_enter_cooldown": True,
            "health_status_values": ["healthy", "unhealthy", "unknown"],
            "catalog_visibility_is_not_health": True,
            "unknown_declared_routes_remain_probe_eligible": True,
            "unknown_discovered_routes_require_refresh_success": True,
            "health_ttl_hours": settings.health_ttl_hours,
            "cache_enabled": _cache_enabled(),
        },
        "recommended_order": [
            {
                "provider": choice.provider.name,
                "model": choice.model,
                "free": choice.provider.free,
                "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
                **_route_health_snapshot(settings, choice, states, evidence),
                "catalog_declared": _is_declared_choice(settings, choice),
                "execution_eligible": _is_execution_eligible_choice(settings, choice, states, evidence),
                "budget": _budget_status(choice, input_tokens, max_cost_usd),
                "role_fit": [role for role, models in ROLE_MODEL_ORDER.items() if choice.model.lower() in models],
                "role_quality_band": _role_quality_band(choice, task) if task in ROLE_TASKS else None,
                "history": _choice_route_history(route_history, task, choice),
                "note": "placeholder endpoint; fix or disable" if choice.model == "your-doubao-endpoint-id" else None,
            }
            for choice in ordered
        ],
    }


def preprocess_input(
    *,
    task: str,
    prompt: str,
    context: str | None = None,
    target_tokens: int = 0,
) -> dict[str, Any]:
    task = normalize_task_type(task)
    raw_text = (prompt + "\n" + (context or "")).strip()
    raw_tokens = _estimate_tokens(raw_text) if raw_text else 0
    complexity = score_task_complexity(task, prompt, context)
    default_target = 160 if raw_tokens < 1200 else 320 if raw_tokens < 4500 else 700
    target_tokens = target_tokens if target_tokens > 0 else default_target
    compressed_context = _extractive_compress(prompt=prompt, context=context or "", target_tokens=target_tokens)
    compressed_tokens = _estimate_tokens((prompt + "\n" + compressed_context).strip()) if compressed_context else _estimate_tokens(prompt)
    compression_ratio = round(compressed_tokens / raw_tokens, 3) if raw_tokens else 1.0
    tier = _preprocess_tier(task=task, prompt=prompt, context=context, complexity=complexity, raw_tokens=raw_tokens, compression_ratio=compression_ratio)
    return {
        "task": task,
        "raw_tokens_est": raw_tokens,
        "compressed_tokens_est": compressed_tokens,
        "estimated_token_reduction": max(0, raw_tokens - compressed_tokens),
        "compression_ratio": compression_ratio,
        "complexity": complexity,
        "tier_decision": tier,
        "three_tier_architecture": [
            {
                "tier": 0,
                "name": "local_rules",
                "role": "cheap deterministic triage, cache lookup, privacy/sensitivity gate, extractive compression",
                "cloud_tokens": 0,
            },
            {
                "tier": 1,
                "name": "free_or_small_local",
                "role": "simple classify/clean/summarize/qa after local compression",
                "cloud_tokens": "free-first or local when available",
            },
            {
                "tier": 2,
                "name": "low_cost_mid_model",
                "role": "context compression, transcript correction, signal fusion, second-pass validation",
                "cloud_tokens": "bounded compressed context",
            },
            {
                "tier": 3,
                "name": "paid_cloud_frontier",
                "role": "only for high-risk, production, hard reasoning, or failed lower tiers",
                "cloud_tokens": "compressed context only",
            },
        ],
        "compressed_context": compressed_context,
        "notes": [
            "This command does not call any model.",
            "Compression is extractive to avoid inventing facts before cloud routing.",
            "Use compressed_context as the cloud context when the tier decision allows external routing.",
        ],
    }


def _preprocess_ledger_summary(preprocessing: dict[str, Any] | None) -> dict[str, Any] | None:
    if not preprocessing:
        return None
    tier = preprocessing.get("tier_decision") or {}
    return {
        "raw_tokens_est": preprocessing.get("raw_tokens_est"),
        "compressed_tokens_est": preprocessing.get("compressed_tokens_est"),
        "estimated_token_reduction": preprocessing.get("estimated_token_reduction"),
        "compression_ratio": preprocessing.get("compression_ratio"),
        "tier": tier.get("tier"),
        "route": tier.get("route"),
        "reason": tier.get("reason"),
        "cloud_allowed": tier.get("cloud_allowed"),
        "paid_allowed": tier.get("paid_allowed"),
    }


def _preprocess_tier(
    *,
    task: str,
    prompt: str,
    context: str | None,
    complexity: dict[str, Any],
    raw_tokens: int,
    compression_ratio: float,
) -> dict[str, Any]:
    text = (prompt + "\n" + (context or "")).strip().lower()
    greeting_markers = ("你好", "hello", "hi", "早上好", "晚上好")
    task_markers = ("整理", "总结", "分析", "写", "生成", "检查", "修复", "提取", "分类", "对比", "review", "fix", "summarize")
    if raw_tokens <= 40 and any(marker in text for marker in greeting_markers) and not any(marker in text for marker in task_markers):
        return {
            "tier": 0,
            "route": "local_rules",
            "reason": "greeting_or_low_value_message",
            "cloud_allowed": False,
            "paid_allowed": False,
        }
    if complexity["label"] == "simple" and raw_tokens <= 700:
        return {
            "tier": 1,
            "route": "free_or_small_local",
            "reason": "simple_low_token_task",
            "cloud_allowed": True,
            "paid_allowed": False,
        }
    if raw_tokens > 1200 and compression_ratio <= 0.45:
        return {
            "tier": 2,
            "route": "preprocess_then_free_or_low_cost_mid_model",
            "reason": "high_context_savings_available",
            "cloud_allowed": True,
            "paid_allowed": complexity["label"] == "hard" or task in {"audit", "transcript_correct"},
        }
    return {
        "tier": 3 if complexity["label"] == "hard" else 2,
        "route": "compressed_context_then_escalate_only_if_needed",
        "reason": "quality_or_reasoning_requires_stronger_route" if complexity["label"] == "hard" else "moderate_task_after_local_triage",
        "cloud_allowed": True,
        "paid_allowed": complexity["label"] == "hard",
    }


def _extractive_compress(*, prompt: str, context: str, target_tokens: int) -> str:
    context = context.strip()
    if not context:
        return ""
    target_chars = max(160, int(target_tokens * 2.2))
    if len(context) <= target_chars:
        return context
    sentences = _split_signal_units(context)
    if not sentences:
        return trim_context(context, target_chars) or ""
    deduped_sentences: list[str] = []
    seen_sentences: set[str] = set()
    for sentence in sentences:
        key = re.sub(r"\s+", "", sentence.lower())
        if key in seen_sentences:
            continue
        seen_sentences.add(key)
        deduped_sentences.append(sentence)
    sentences = deduped_sentences
    prompt_terms = _keyword_set(prompt)
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        terms = _keyword_set(sentence)
        overlap = len(prompt_terms & terms)
        signal_hits = sum(1 for word in ("结论", "问题", "风险", "原因", "步骤", "todo", "error", "failed", "成本", "token", "模型", "路由") if word in sentence.lower())
        length_bonus = min(1.0, len(sentence) / 180)
        scored.append((overlap * 2.0 + signal_hits * 1.5 + length_bonus, index, sentence))
    selected = sorted(scored, key=lambda item: (-item[0], item[1]))[: max(1, min(len(scored), target_tokens // 20 or 1))]
    selected_indexes = {index for _, index, _ in selected}
    ordered = [sentence for index, sentence in enumerate(sentences) if index in selected_indexes]
    result = ""
    for sentence in ordered:
        addition = sentence if not result else "\n" + sentence
        if len(result) + len(addition) > target_chars and result:
            break
        result += addition
    return result.strip() or (trim_context(context, target_chars) or "")


def _split_signal_units(text: str) -> list[str]:
    chunks = re.split(r"(?<=[。！？!?])\s+|\n+", text)
    units: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= 260:
            units.append(chunk)
            continue
        parts = re.split(r"(?<=[，,；;])", chunk)
        buffer = ""
        for part in parts:
            if len(buffer) + len(part) > 220 and buffer:
                units.append(buffer.strip())
                buffer = part
            else:
                buffer += part
        if buffer.strip():
            units.append(buffer.strip())
    return units


def _keyword_set(text: str) -> set[str]:
    ascii_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower()))
    cjk_terms = set(re.findall(r"[\u4e00-\u9fff]{2,6}", text))
    return ascii_words | cjk_terms


def _infer_privacy_mode(
    *,
    privacy: str,
    prompt: str,
    context: str | None,
    input_modalities: list[str],
) -> tuple[str, list[str]]:
    normalized = (privacy or "auto").strip().lower()
    if normalized not in {"auto", "local_only", "external_allowed"}:
        raise ValueError(f"不支持的隐私模式：{privacy}")
    if normalized != "auto":
        return normalized, ["explicit_privacy_mode"]
    text = f"{prompt}\n{context or ''}".lower()
    signals = [
        term
        for term in (
            "聊天记录",
            "对话记录",
            "客户原图",
            "用户原图",
            "私人照片",
            "个人照片",
            "身份证",
            "手机号",
            "家庭住址",
            "病历",
            "银行卡",
            "api key",
            "access token",
            "password",
            "secret",
            "private key",
        )
        if term in text
    ]
    if signals:
        return "local_only", [f"sensitive_signal:{signal}" for signal in signals]
    return "external_allowed", ["no_sensitive_signal_detected"]


def infer_task_descriptor(
    *,
    task: str,
    prompt: str = "",
    context: str | None = None,
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
    domain: str = "general",
    quality_target: str = "draft",
    risk: str | None = None,
    paid_allowed: bool = True,
    privacy: str = "auto",
) -> dict[str, Any]:
    task = normalize_task_type(task)
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"不支持的质量档位：{quality_target}")
    complexity = score_task_complexity(task, prompt, context)
    inferred_input = input_modalities[:] if input_modalities else ["text"]
    inferred_output = output_modalities[:] if output_modalities else ["text"]
    if task in VISION_TASKS and "image" not in inferred_input:
        inferred_input.append("image")
    if task == "asr":
        inferred_input = ["audio", "video"]
        inferred_output = ["text"]
    if task == "image_generate":
        inferred_output = ["image"]
    if task == "embed":
        inferred_output = ["embedding"]
    if task == "rerank":
        inferred_output = ["score"]
    complexity = _apply_task_descriptor_v2_activation(
        task,
        complexity,
        describe_task_v2(
            task,
            prompt,
            context,
            input_modalities=inferred_input,
        ),
    )
    if not risk:
        if quality_target in {"production", "audit", "frontier"} or complexity["label"] == "hard" or task in {"audit", "verify", "transcript_correct"}:
            risk = "high" if complexity["label"] == "hard" else "medium"
        else:
            risk = "low"
    privacy_mode, privacy_reasons = _infer_privacy_mode(
        privacy=privacy,
        prompt=prompt,
        context=context,
        input_modalities=inferred_input,
    )
    if task == "asr" and privacy == "auto":
        privacy_mode = "local_first_external_explicit"
        privacy_reasons = ["raw_audio_defaults_local_first"]
    return {
        "task_type": task,
        "input_modalities": inferred_input,
        "output_modalities": inferred_output,
        "domain": domain,
        "complexity": complexity["label"],
        "risk": risk,
        "context_size": "long" if complexity["token_estimate"] > 12000 else "medium" if complexity["token_estimate"] > 4500 else "small",
        "quality_target": quality_target,
        "privacy": privacy_mode,
        "privacy_reasons": privacy_reasons,
        "paid_allowed": paid_allowed,
        "complexity_detail": complexity,
    }


ROLE_STAGE_PURPOSE = {
    "plan": "目标拆解、架构取舍、验收与回退设计",
    "research_enhance": "基于带URL和日期的互联网来源增量增强规划",
    "plan_audit": "与规划和研究增强家族独立的可执行性挑战审计",
    "execute": "长链路实施、代码或知识工作产出",
    "audit": "跨厂商挑错、风险与遗漏审计",
    "verify": "从原始输入独立复验，不继承主结论",
    "quality_enhance": "事实边界不变的最终结构与表达提升",
}


def _build_role_pipeline(
    settings: Settings,
    *,
    quality_target: str,
    input_tokens: int,
    max_cost_usd: float | None,
    paid_allowed: bool,
) -> list[dict[str, Any]]:
    states = _load_route_state(settings)
    route_history = _route_history_map(settings)
    selected_by_role: dict[str, LLMChoice] = {}
    independent_from = {"plan_audit": "research_enhance", "audit": "plan", "verify": "execute"}
    stages: list[dict[str, Any]] = []
    for role in ("plan", "research_enhance", "plan_audit", "execute", "audit", "verify", "quality_enhance"):
        choices = [
            choice
            for choice in _role_policy_choices(
                settings,
                role=role,
                quality_target=quality_target,
                input_tokens=input_tokens,
                max_cost_usd=max_cost_usd,
                paid_allowed=paid_allowed,
                history=route_history,
            )
            if _is_available(choice, states)
        ]
        source_role = independent_from.get(role)
        excluded_family = _model_family(selected_by_role[source_role]) if source_role and source_role in selected_by_role else None
        candidate_rows: list[dict[str, Any]] = []
        selected_choice: LLMChoice | None = None
        for choice in choices:
            budget = _budget_status(choice, input_tokens, max_cost_usd)
            row = describe_choice_capability(choice)
            row["budget"] = budget
            row["role_quality_band"] = _role_quality_band(choice, role)
            row["minimum_role_quality_band"] = _minimum_role_quality_band(quality_target)
            row["history"] = _choice_route_history(route_history, role, choice)
            row["independent_family"] = excluded_family is None or _model_family(choice) != excluded_family
            candidate_rows.append(row)
            if selected_choice is None and budget["eligible"] and row["independent_family"]:
                selected_choice = choice
        selected = describe_choice_capability(selected_choice) if selected_choice else None
        if selected_choice:
            selected["budget"] = _budget_status(selected_choice, input_tokens, max_cost_usd)
            selected["role_quality_band"] = _role_quality_band(selected_choice, role)
            selected["minimum_role_quality_band"] = _minimum_role_quality_band(quality_target)
            selected["history"] = _choice_route_history(route_history, role, selected_choice)
            selected["selection_reason"] = "complexity_sets_quality_floor_then_health_then_budget_then_retry_adjusted_expected_total_cost_then_latency"
            selected_by_role[role] = selected_choice
        stages.append(
            {
                "stage": role,
                "purpose": ROLE_STAGE_PURPOSE[role],
                "enabled": bool(selected),
                "selected": selected,
                "candidates": candidate_rows[:6],
                "quality_target": quality_target,
                "minimum_role_quality_band": _minimum_role_quality_band(quality_target),
                "selection_rule": "complexity and requested quality set the floor; then route health, budget eligibility, retry-adjusted expected total cost, P95 latency, and stable tie-breakers; free wins only through zero expected monetary cost",
            }
        )
    return stages


def _build_multimodal_route(
    settings: Settings,
    *,
    input_tokens: int,
    max_cost_usd: float | None,
    paid_allowed: bool,
) -> dict[str, Any]:
    states = _load_route_state(settings)
    order = {model: index for index, model in enumerate(MULTIMODAL_UNDERSTANDING_ORDER)}
    choices = [
        choice
        for choice in _dedupe_model_routes(configured_models(settings, only_free=False))
        if (
            _free_only_eligible_provider(choice.provider)
            or (paid_allowed and not choice.provider.free)
        )
        and _is_vision_choice(choice)
        and _is_available(choice, states)
        and choice.model in order
    ]
    choices.sort(
        key=lambda choice: (
            -MULTIMODAL_QUALITY_BANDS.get(choice.model, 0),
            0 if choice.provider.free else 1,
            float((_budget_status(choice, input_tokens, max_cost_usd).get("projected_cost_usd")) or 0.0),
            order[choice.model],
            choice.provider.priority,
        )
    )
    eligible = [
        choice
        for choice in choices
        if _budget_status(choice, input_tokens, max_cost_usd)["eligible"]
    ]
    selected_choice = eligible[0] if eligible else None
    selected_family = _model_family(selected_choice) if selected_choice else None
    audit_order = {model: index for index, model in enumerate(MULTIMODAL_AUDIT_ORDER)}
    audit_choices = sorted(
        (
            choice
            for choice in eligible
            if _model_family(choice) != selected_family and choice.model in audit_order
        ),
        key=lambda choice: (audit_order[choice.model], choice.provider.priority),
    )
    audit_choice = audit_choices[0] if audit_choices else None

    def row(choice: LLMChoice | None) -> dict[str, Any] | None:
        if not choice:
            return None
        result = describe_choice_capability(choice)
        result["budget"] = _budget_status(choice, input_tokens, max_cost_usd)
        return result

    return {
        "stage": "multimodal_understanding",
        "purpose": "图片理解、OCR、图文联合推理；高风险结果再交给独立厂商复核",
        "trigger": ["image", "vision", "ocr", "document_page"],
        "enabled": bool(selected_choice),
        "selected": row(selected_choice),
        "review_with": row(audit_choice),
        "candidates": [row(choice) for choice in choices[:6]],
        "cataloged_not_executable": {
            "image_generation": ["doubao-seedream-5.0-lite", "doubao-seedream-4.5"],
            "video_generation": ["doubao-seedance-2.0", "doubao-seedance-2.0-fast"],
            "speech_audio": ["doubao-realtime-voice", "doubao-streaming-asr", "doubao-recording-asr-2.0"],
            "embedding": ["doubao-embedding-vision"],
        },
        "selection_rule": "chat-compatible models outside active cooldown may be probed; only recent successful calls are reported healthy, while media generation, speech, and embedding need dedicated adapters and probes",
    }


def route_plan(
    settings: Settings,
    *,
    task: str,
    prompt: str = "",
    context: str | None = None,
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
    domain: str = "general",
    quality_target: str = "draft",
    risk: str | None = None,
    paid_allowed: bool = True,
    prefer_free: bool = True,
    limit: int = 12,
    privacy: str = "auto",
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    _maybe_auto_discover_free_pool(settings)
    descriptor = infer_task_descriptor(
        task=task,
        prompt=prompt,
        context=context,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        domain=domain,
        quality_target=quality_target,
        risk=risk,
        paid_allowed=paid_allowed,
        privacy=privacy,
    )
    normalized_task = descriptor["task_type"]
    local_steps = ["cache_lookup", "local_chunking"]
    if normalized_task in {"asr", "transcript_correct"} or "audio" in descriptor["input_modalities"] or "video" in descriptor["input_modalities"]:
        local_steps = ["local_audio_extract", "local_asr", "deterministic_glossary_cleanup", "chunking", "cache_lookup"]
    elif normalized_task in VISION_TASKS:
        local_steps = ["image_resize_or_compress", "cache_lookup"]
    elif normalized_task in {"embed", "rerank"}:
        local_steps = ["deduplicate_inputs", "cache_lookup"]

    if normalized_task == "asr":
        external_choices = [
            describe_choice_capability(choice)
            for choice in _model_choices(settings, task="asr", only_free=False)[:limit]
        ]
        return {
            "descriptor": descriptor,
            "local_steps": local_steps,
            "route_ladder": ["local_asr", "external_speech_model_only_if_configured_and_needed"],
            "recommended_order": external_choices,
            "notes": [
                "ASR stays local first; external adapters are shown for explicit fallback only.",
                "Remote audio upload requires remote-transcribe with --allow-external.",
            ],
        }
    if normalized_task in SPECIALIZED_TASKS:
        return {
            "descriptor": descriptor,
            "local_steps": local_steps,
            "route_ladder": ["capability_registry", "dedicated_provider_adapter_required", "health_probe_after_adapter", "codex_controller_audit_only"],
            "recommended_order": [
                describe_choice_capability(choice)
                for choice in _model_choices(settings, task=normalized_task, only_free=False)[:limit]
            ],
            "paid_fallback_order": [],
            "capability_summary": {
                "configured_families": [row["family"] for row in capability_registry(settings, configured_only=True)["families"]],
                "missing_recommended_families": capability_registry(settings).get("missing_recommended_families", []),
            },
            "notes": [f"Task {normalized_task} requires a dedicated provider adapter; do not execute it through generic chat/completions."],
        }

    paid_fallback = paid_allowed and (
        quality_target in {"production", "audit", "frontier"} or descriptor["risk"] in {"medium", "high"}
    )
    paid_fallback = bool(paid_allowed and paid_fallback)
    recommendation = recommend_route(
        settings,
        task=normalized_task if normalized_task in TASK_TYPES else "draft",
        prompt=prompt,
        context=context,
        prefer_free=prefer_free,
        paid_fallback=paid_fallback,
        quality_target=quality_target,
        max_cost_usd=max_cost_usd,
    )
    ordered: list[dict[str, Any]] = []
    paid_preview: list[dict[str, Any]] = []
    states = _load_route_state(settings)
    evidence = _load_route_health(settings)
    raw_order = recommendation.get("recommended_order") or []
    for item in raw_order[:limit]:
        matching = [
            choice
            for choice in configured_models(settings, only_free=False)
            if choice.provider.name == item.get("provider") and choice.model == item.get("model")
        ]
        if matching:
            capability = describe_choice_capability(matching[0])
            capability["budget"] = item.get("budget")
            state = states.get(_choice_key(matching[0]))
            capability.update(_route_health_snapshot(settings, matching[0], states, evidence))
            capability["cooldown_reason"] = state.reason if state else None
            ordered.append(capability)
        else:
            ordered.append(item)
    if paid_fallback:
        if normalized_task in ROLE_TASKS:
            paid_choices = [
                choice
                for choice in _role_policy_choices(
                    settings,
                    role=normalized_task,
                    quality_target=quality_target,
                    input_tokens=descriptor["complexity_detail"]["token_estimate"] + 128,
                    max_cost_usd=max_cost_usd,
                    paid_allowed=True,
                )
                if not choice.provider.free and _is_available(choice, states)
            ]
        else:
            paid_choices = [
                choice
                for choice in _dedupe_model_routes(
                    _paid_fallback_choices(
                        settings,
                        normalized_task if normalized_task in TASK_TYPES else "draft",
                        quality_target,
                    )
                )
                if _is_available(choice, states)
            ]
        for choice in paid_choices[:6]:
            capability = describe_choice_capability(choice)
            capability["budget"] = _budget_status(
                choice,
                descriptor["complexity_detail"]["token_estimate"] + 128,
                max_cost_usd,
            )
            state = states.get(_choice_key(choice))
            capability.update(_route_health_snapshot(settings, choice, states, evidence))
            capability["cooldown_reason"] = state.reason if state else None
            paid_preview.append(capability)

    ladder = list(local_steps)
    if prefer_free:
        ladder.append("free_pool_coarse_or_main_if_good_enough")
    if paid_fallback:
        ladder.append("low_cost_paid_main_work")
    if descriptor["risk"] == "high" or quality_target in {"audit", "frontier"}:
        ladder.append("independent_second_model_cross_check")
    ladder.append("codex_controller_audit_only")
    return {
        "descriptor": descriptor,
        "local_steps": local_steps,
        "route_ladder": ladder,
        "recommended_order": ordered,
        "paid_fallback_order": paid_preview,
        "role_pipeline": _build_role_pipeline(
            settings,
            quality_target=quality_target,
            input_tokens=descriptor["complexity_detail"]["token_estimate"] + 128,
            max_cost_usd=max_cost_usd,
            paid_allowed=paid_allowed,
        ),
        "multimodal_route": _build_multimodal_route(
            settings,
            input_tokens=descriptor["complexity_detail"]["token_estimate"] + 128,
            max_cost_usd=max_cost_usd,
            paid_allowed=paid_allowed,
        ),
        "capability_summary": {
            "configured_families": [
                row["family"]
                for row in capability_registry(settings, configured_only=True)["families"]
            ],
            "missing_recommended_families": capability_registry(settings).get("missing_recommended_families", []),
        },
        "policy": recommendation.get("policy"),
    }


def _extract_audio_to_wav(input_path: Path, output_path: Path) -> None:
    ffmpeg = _command_path("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("缺少 ffmpeg，无法从视频提取音频。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-i", str(input_path), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def transcribe_media(
    settings: Settings,
    input_file: str | Path,
    *,
    output_dir: str | Path | None = None,
    backend: str = "auto",
    language: str = "zh",
    model: str | None = None,
    keep_audio: bool = False,
) -> dict[str, Any]:
    source = Path(input_file).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"输入文件不存在：{source}")
    out_dir = Path(output_dir).expanduser() if output_dir else settings.data_dir / "transcripts" / source.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"{source.stem}.16k.wav"
    _extract_audio_to_wav(source, wav_path)

    status = asr_status(settings)
    selected = backend
    if backend == "auto":
        if status["backends"]["whisper_cpp"]["ready"]:
            selected = "whisper_cpp"
        elif status["backends"]["mlx_whisper"]["ready"]:
            selected = "mlx_whisper"
        elif status["backends"]["openai_whisper"]["ready"]:
            selected = "openai_whisper"
        else:
            raise RuntimeError("没有可用 ASR 后端。建议安装 whisper.cpp 或 mlx-whisper。")

    transcript_path = out_dir / f"{source.stem}.txt"
    srt_path = out_dir / f"{source.stem}.srt"
    if selected == "whisper_cpp":
        command = status["backends"]["whisper_cpp"]["command"]
        model_path = model or status["backends"]["whisper_cpp"]["model"]
        if not command or not model_path:
            raise RuntimeError("whisper.cpp 未就绪：需要 whisper-cli 命令和 SMART_LLM_ASR_WHISPER_CPP_MODEL 模型路径。")
        subprocess.run(
            _whisper_cpp_transcribe_command(
                command,
                model_path,
                wav_path,
                language,
                out_dir / source.stem,
                no_gpu=bool(status["backends"]["whisper_cpp"]["no_gpu"]),
            ),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    elif selected == "openai_whisper":
        command = status["backends"]["openai_whisper"]["command"]
        whisper_model = model or os.getenv("SMART_LLM_ASR_OPENAI_WHISPER_MODEL", "turbo")
        subprocess.run(
            [command, str(wav_path), "--language", "Chinese" if language in {"zh", "cn", "chinese"} else language, "--model", whisper_model, "--output_dir", str(out_dir), "--output_format", "all"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    elif selected == "mlx_whisper":
        mlx_model = model or os.getenv("SMART_LLM_ASR_MLX_MODEL", "mlx-community/whisper-large-v3-turbo")
        script = (
            "import json, sys, mlx_whisper; "
            "result = mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo=sys.argv[2], language=sys.argv[3]); "
            "print(json.dumps(result, ensure_ascii=False))"
        )
        completed = subprocess.run(
            [os.getenv("PYTHON", "python3"), "-c", script, str(wav_path), mlx_model, language],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        result = json.loads(completed.stdout)
        transcript_path.write_text(str(result.get("text") or ""), encoding="utf-8")
    else:
        raise RuntimeError(f"未知 ASR 后端：{selected}")

    if not transcript_path.exists() or transcript_path.stat().st_size == 0:
        raise RuntimeError(f"ASR 后端执行完成但没有生成有效转写文本：{transcript_path}")

    if not keep_audio:
        try:
            wav_path.unlink()
        except OSError:
            pass
    return {
        "source": str(source),
        "backend": selected,
        "output_dir": str(out_dir),
        "transcript": str(transcript_path) if transcript_path.exists() else None,
        "srt": str(srt_path) if srt_path.exists() else None,
        "audio_kept": keep_audio and wav_path.exists(),
    }


def _price_per_million(choice: LLMChoice, direction: str) -> float | None:
    if choice.provider.free:
        return 0.0
    keys = [
        f"SMART_LLM_PRICE_{choice.provider.name.upper().replace('-', '_')}_{direction.upper()}",
        f"SMART_LLM_PRICE_{choice.model.upper().replace('/', '_').replace('-', '_').replace(':', '_')}_{direction.upper()}",
    ]
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            try:
                return float(value)
            except ValueError:
                return None
    price = MODEL_PRICE_CATALOG.get(choice.model.lower(), {}).get(direction)
    if not isinstance(price, (int, float)):
        return None
    currency = MODEL_PRICE_CATALOG.get(choice.model.lower(), {}).get("currency", "USD")
    if currency == "CNY":
        try:
            cny_per_usd = float(os.getenv("SMART_LLM_CNY_PER_USD", "7.2") or "7.2")
        except ValueError:
            cny_per_usd = 7.2
        return round(float(price) / max(cny_per_usd, 0.01), 6)
    return float(price)


def _estimated_cost_usd(choice: LLMChoice, input_tokens: int, output_tokens: int) -> float | None:
    input_price = _price_per_million(choice, "input")
    output_price = _price_per_million(choice, "output")
    if input_price is None or output_price is None:
        return None
    return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)


def _local_ollama_reasoning_effort(choice: LLMChoice) -> str | None:
    provider = choice.provider
    parsed = urlparse(provider.base_url)
    if (
        provider.billing_class != "local"
        or "ollama" not in provider.name.lower()
        or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}
    ):
        return None
    value = os.getenv("SMART_LLM_OLLAMA_REASONING_EFFORT", "none").strip().lower()
    if value in {"", "auto", "default"}:
        return None
    if value not in {"none", "low", "medium", "high"}:
        raise RuntimeError("SMART_LLM_OLLAMA_REASONING_EFFORT 仅支持 none、low、medium、high 或 auto")
    return value


def _visible_message_text(value: Any) -> str:
    """Extract only user-visible final text from OpenAI-compatible variants."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_visible_message_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        item_type = str(value.get("type") or "").lower()
        if item_type in {"text", "output_text", "message"}:
            for key in ("text", "content", "value"):
                text = _visible_message_text(value.get(key))
                if text:
                    return text
        # A few compatible gateways omit the type field for text blocks.
        if not item_type:
            for key in ("text", "content", "value"):
                text = _visible_message_text(value.get(key))
                if text:
                    return text
    return ""


def _thinking_plan(
    choice: LLMChoice,
    *,
    task: str,
    total_output_tokens: int,
    thinking_mode: str,
    thinking_budget_tokens: int | None,
    final_answer_reserve_tokens: int | None,
) -> dict[str, Any]:
    provider_family = _provider_family(choice.provider)
    model = choice.model.lower()
    is_qwen_hybrid = (
        provider_family == "qwen"
        and model in MODEL_BILLABLE_OUTPUT_RESERVE_OVERHEAD
    )
    is_deepseek_hybrid = (
        provider_family in {"deepseek", "nvidia"}
        and _is_deepseek_v4_choice(choice)
    )
    is_minimax_m3 = provider_family == "minimax" and model == "minimax-m3"
    if not is_qwen_hybrid and not is_deepseek_hybrid and not is_minimax_m3:
        return {
            "mode": "unsupported",
            "enable_thinking": None,
            "thinking_budget_tokens": None,
            "final_answer_reserve_tokens": total_output_tokens,
            "total_output_tokens": total_output_tokens,
        }
    mode = thinking_mode
    if is_minimax_m3:
        if thinking_budget_tokens is not None:
            raise RuntimeError("MiniMax-M3 不支持独立 thinking token budget。")
        if mode == "auto" and final_answer_reserve_tokens is not None:
            mode = "disabled"
        if mode == "disabled":
            return {
                "mode": "disabled",
                "thinking": {"type": "disabled"},
                "enable_thinking": None,
                "thinking_budget_tokens": 0,
                "final_answer_reserve_tokens": total_output_tokens,
                "total_output_tokens": total_output_tokens,
            }
        if mode == "enabled" and final_answer_reserve_tokens is not None:
            raise RuntimeError(
                "MiniMax-M3 thinking=enabled 无法保证独立 final-answer reserve；"
                "请改用 thinking_mode=disabled。"
            )
        return {
            "mode": mode,
            "thinking": {"type": "adaptive"} if mode == "enabled" else None,
            "enable_thinking": None,
            "thinking_budget_tokens": None,
            "final_answer_reserve_tokens": None,
            "total_output_tokens": total_output_tokens,
        }
    if is_deepseek_hybrid:
        if thinking_budget_tokens is not None:
            raise RuntimeError(
                "DeepSeek Chat Completions 不支持独立 thinking token budget；"
                "需要保证最终正文时请使用 thinking_mode=disabled。"
            )
        # DeepSeek exposes an enabled/disabled toggle, but no separate token
        # ceiling for reasoning. In auto mode, a requested final-answer reserve
        # therefore selects non-thinking mode so that the full output envelope
        # is available to the user-visible answer.
        if mode == "auto" and final_answer_reserve_tokens is not None:
            mode = "disabled"
        if mode == "disabled":
            return {
                "mode": "disabled",
                "thinking": {"type": "disabled"},
                "enable_thinking": None,
                "thinking_budget_tokens": 0,
                "final_answer_reserve_tokens": total_output_tokens,
                "total_output_tokens": total_output_tokens,
            }
        if mode == "enabled" and final_answer_reserve_tokens is not None:
            raise RuntimeError(
                "DeepSeek thinking=enabled 无法保证独立 final-answer reserve；"
                "请改用 thinking_mode=disabled。"
            )
        return {
            "mode": mode,
            "thinking": {"type": "enabled"} if mode == "enabled" else None,
            "enable_thinking": None,
            "thinking_budget_tokens": None,
            "final_answer_reserve_tokens": None,
            "total_output_tokens": total_output_tokens,
        }
    if mode == "auto" and task == "research_enhance":
        mode = "enabled"
    if mode == "disabled":
        if thinking_budget_tokens is not None:
            raise RuntimeError("禁用 thinking 时不能同时设置 thinking_budget_tokens。")
        return {
            "mode": "disabled",
            "enable_thinking": False,
            "thinking_budget_tokens": 0,
            "final_answer_reserve_tokens": total_output_tokens,
            "total_output_tokens": total_output_tokens,
        }
    if mode == "auto" and thinking_budget_tokens is None and final_answer_reserve_tokens is None:
        return {
            "mode": "auto",
            "enable_thinking": None,
            "thinking_budget_tokens": None,
            "final_answer_reserve_tokens": None,
            "total_output_tokens": total_output_tokens,
        }
    if total_output_tokens < 2:
        raise RuntimeError("Qwen thinking 与最终正文分配至少需要 2 个输出 token。")
    minimum_final = min(total_output_tokens - 1, max(1, max(128, total_output_tokens // 3)))
    final_tokens = final_answer_reserve_tokens if final_answer_reserve_tokens is not None else minimum_final
    reasoning_tokens = thinking_budget_tokens if thinking_budget_tokens is not None else total_output_tokens - final_tokens
    if reasoning_tokens <= 0 or final_tokens <= 0:
        raise RuntimeError("thinking 预算与最终正文预留都必须为正数。")
    requested_total = reasoning_tokens + final_tokens
    if requested_total > total_output_tokens:
        raise RuntimeError("thinking_budget_tokens + final_answer_reserve_tokens 不能超过 max_output_tokens。")
    return {
        "mode": "enabled" if mode == "enabled" else "auto_bounded",
        "enable_thinking": True,
        "thinking_budget_tokens": reasoning_tokens,
        "final_answer_reserve_tokens": final_tokens,
        "total_output_tokens": requested_total,
    }


def _openrouter_request_policy_incompatibility_reason(
    response: httpx.Response,
    *,
    is_openrouter: bool,
    upstream_providers: tuple[str, ...],
    allow_fallbacks: bool,
    require_zdr: bool,
    deny_data_collection: bool,
    response_format: dict[str, Any] | None,
) -> str | None:
    """Classify only explicit request-constraint mismatches, never status alone."""
    controls_requested = bool(
        upstream_providers
        or not allow_fallbacks
        or require_zdr
        or deny_data_collection
        or response_format
    )
    if not is_openrouter or not controls_requested or response.status_code not in {400, 404, 422, 503}:
        return None
    try:
        payload = response.json()
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if not isinstance(message, str):
        return None
    normalized = " ".join(message.lower().split())[:1024]
    metadata = error.get("metadata") if isinstance(error.get("metadata"), dict) else {}
    error_type = metadata.get("error_type") or payload.get("error_type")
    if error_type in {
        "authentication",
        "permission_denied",
        "payment_required",
        "rate_limit_exceeded",
        "provider_overloaded",
        "provider_unavailable",
        "server",
        "timeout",
    }:
        return None

    no_endpoint_signal = "no endpoint" in normalized
    routing_requirement_signal = any(
        marker in normalized
        for marker in (
            "routing requirement",
            "guardrail restriction",
            "provider restriction",
            "provider selection",
        )
    )
    if require_zdr and any(
        marker in normalized
        for marker in ("zero data retention", "zdr", "data policy")
    ):
        return "zdr_constraint"
    if deny_data_collection and any(
        marker in normalized
        for marker in ("data collection", "data policy", "retain", "training")
    ):
        return "data_collection_constraint"
    if response_format is not None and any(
        marker in normalized
        for marker in (
            "structured output",
            "structured response",
            "json schema",
            "json_schema",
            "response_format",
            "required parameter",
            "parameter support",
        )
    ):
        return "structured_output_constraint"
    if (upstream_providers or not allow_fallbacks) and (
        routing_requirement_signal
        or (
            no_endpoint_signal
            and any(marker in normalized for marker in ("requested provider", "allowed provider"))
        )
    ):
        return "provider_selection_constraint"
    if routing_requirement_signal and no_endpoint_signal:
        return "routing_requirement_constraint"
    return None


def _call_openai_compatible(
    choice: LLMChoice,
    *,
    messages: list[dict[str, Any]],
    timeout: float,
    temperature: float,
    max_tokens: int | None = None,
    enable_thinking: bool | None = None,
    thinking_budget_tokens: int | None = None,
    thinking: dict[str, str] | None = None,
    response_format: dict[str, Any] | None = None,
    openrouter_upstream_providers: list[str] | tuple[str, ...] | None = None,
    openrouter_allow_fallbacks: bool = True,
    openrouter_require_zdr: bool = False,
    openrouter_deny_data_collection: bool = False,
) -> tuple[str, dict[str, Any]]:
    key = os.getenv(choice.provider.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"缺少 API key 环境变量：{choice.provider.api_key_env}")
    effective_temperature = 1 if _model_family(choice) == "kimi" else temperature
    payload: dict[str, Any] = {"model": choice.model, "messages": messages, "temperature": effective_temperature}
    provider_family = _provider_family(choice.provider)
    if max_tokens:
        if provider_family == "minimax" or (
            provider_family == "qwen" and choice.model.lower() in MODEL_BILLABLE_OUTPUT_RESERVE_OVERHEAD
        ):
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
    if provider_family == "minimax":
        # MiniMax reasoning models can include private thinking in content.
        # Split it into reasoning fields so the routed result contains only
        # the user-visible final answer.
        payload["reasoning_split"] = True
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    if thinking_budget_tokens is not None:
        payload["thinking_budget"] = thinking_budget_tokens
    nvidia_deepseek_v4 = _is_nvidia_deepseek_v4_choice(choice)
    if nvidia_deepseek_v4:
        thinking_enabled = not thinking or thinking.get("type") != "disabled"
        payload["chat_template_kwargs"] = {"thinking": thinking_enabled}
        if thinking_enabled:
            payload["chat_template_kwargs"]["reasoning_effort"] = "high"
    elif thinking is not None:
        payload["thinking"] = thinking
    reasoning_effort = _local_ollama_reasoning_effort(choice)
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    is_openrouter = _provider_family(choice.provider) == "openrouter"
    upstream_providers = tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in (openrouter_upstream_providers or ())
            if str(item).strip()
        )
    )
    openrouter_controls_requested = bool(
        upstream_providers
        or not openrouter_allow_fallbacks
        or openrouter_require_zdr
        or openrouter_deny_data_collection
    )
    if openrouter_controls_requested and not is_openrouter:
        raise RuntimeError("OpenRouter 上游 provider/ZDR 控制只能用于 OpenRouter 路线。")
    if response_format is not None and is_openrouter:
        payload["response_format"] = response_format
    provider_preferences: dict[str, Any] = {}
    if upstream_providers:
        provider_preferences["only"] = list(upstream_providers)
    if not openrouter_allow_fallbacks:
        provider_preferences["allow_fallbacks"] = False
    if openrouter_require_zdr:
        provider_preferences["zdr"] = True
    if openrouter_deny_data_collection:
        provider_preferences["data_collection"] = "deny"
    if response_format is not None and is_openrouter:
        provider_preferences["require_parameters"] = True
    if provider_preferences:
        payload["provider"] = provider_preferences
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            choice.provider.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            policy_reason = _openrouter_request_policy_incompatibility_reason(
                exc.response,
                is_openrouter=is_openrouter,
                upstream_providers=upstream_providers,
                allow_fallbacks=openrouter_allow_fallbacks,
                require_zdr=openrouter_require_zdr,
                deny_data_collection=openrouter_deny_data_collection,
                response_format=response_format,
            )
            if policy_reason:
                raise RequestPolicyIncompatibility(
                    int(exc.response.status_code),
                    policy_reason,
                ) from None
            raise
        data = response.json()
    if provider_family == "minimax":
        base_resp = data.get("base_resp") if isinstance(data, dict) else None
        raw_status = base_resp.get("status_code") if isinstance(base_resp, dict) else 0
        try:
            minimax_status = int(raw_status or 0)
        except (TypeError, ValueError):
            minimax_status = -1
        if minimax_status != 0:
            raise RuntimeError(f"minimax_api_error:{minimax_status}")
    raw_served_model = data.get("model")
    served_model = raw_served_model.strip() if isinstance(raw_served_model, str) else None
    served_model = served_model or None
    if nvidia_deepseek_v4 and served_model:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", served_model):
            raise RuntimeError(
                f"{choice.provider.name}/{choice.model} "
                "model_substitution_detected:invalid_served_model"
            )
        served_choice = LLMChoice(choice.provider, served_model)
        if not set(_role_model_aliases(choice)).intersection(_role_model_aliases(served_choice)):
            raise RuntimeError(
                f"{choice.provider.name}/{choice.model} model_substitution_detected:{served_model}"
            )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    usage = dict(usage)
    first_choice = (data.get("choices") or [{}])[0]
    message = first_choice.get("message") if isinstance(first_choice, dict) else {}
    message = message if isinstance(message, dict) else {}
    raw_finish_reason = str(first_choice.get("finish_reason") or "").strip().lower()
    finish_reason = raw_finish_reason if raw_finish_reason in {"stop", "length", "tool_calls", "function_call", "content_filter"} else ("other" if raw_finish_reason else None)
    try:
        completion_tokens = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        completion_tokens = 0
    usage["_completion_metadata"] = {
        "finish_reason": finish_reason,
        "output_reached_requested_token_limit": bool(max_tokens is not None and completion_tokens >= max_tokens),
    }
    served_provider = data.get("provider")
    if not isinstance(served_provider, str):
        served_provider = None
    try:
        generation_id = response.headers.get("x-generation-id")
    except (AttributeError, TypeError):
        generation_id = None
    if not isinstance(generation_id, str):
        generation_id = None
    usage["_routing_metadata"] = {
        "openrouter_controls_applied": bool(is_openrouter and (provider_preferences or response_format)),
        "requested_upstream_providers": list(upstream_providers),
        "provider_fallbacks_allowed": openrouter_allow_fallbacks,
        "zdr_required": openrouter_require_zdr,
        "data_collection_denied": openrouter_deny_data_collection,
        "structured_response_requested": response_format is not None and is_openrouter,
        "served_provider": served_provider,
        "served_model": served_model,
        "generation_id": generation_id,
    }
    content = _visible_message_text(message.get("content"))
    if not content:
        reasoning_present = bool(
            _visible_message_text(message.get("reasoning_content"))
            or _visible_message_text(message.get("reasoning"))
        )
        raise InconclusiveModelOutput(
            f"{choice.provider.name}/{choice.model}",
            reasoning_present=reasoning_present,
            finish_reason=finish_reason,
            usage=usage,
        )
    return content, usage


def _api_endpoint(provider: LLMProvider, endpoint: str) -> str:
    base = provider.base_url.rstrip("/")
    clean_endpoint = endpoint.strip("/")
    if base.endswith("/api/paas/v4") or base.endswith("/paas/v4"):
        return f"{base}/{clean_endpoint}"
    if base.endswith("/api"):
        return f"{base}/paas/v4/{clean_endpoint}"
    return f"{base}/{clean_endpoint}"


def _adapter_choices(settings: Settings, task: str, *, provider_name: str | None = None, model: str | None = None) -> list[LLMChoice]:
    choices = _model_choices(settings, task=task, only_free=False)
    states = _load_route_state(settings)
    filtered: list[LLMChoice] = []
    provider_filter = (provider_name or "").strip().lower()
    model_filter = (model or "").strip().lower()
    for choice in choices:
        if provider_filter and provider_filter not in {choice.provider.name.lower(), _provider_family(choice.provider), _model_family(choice)}:
            continue
        if model_filter and choice.model.lower() != model_filter:
            continue
        if not os.getenv(choice.provider.api_key_env, "").strip():
            continue
        if not _is_available(choice, states):
            continue
        filtered.append(choice)
    return filtered


def _call_embedding_compatible(
    choice: LLMChoice,
    *,
    texts: list[str],
    dimensions: int | None = None,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = os.getenv(choice.provider.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"缺少 API key 环境变量：{choice.provider.api_key_env}")
    if not texts:
        raise RuntimeError("Embedding 输入不能为空。")
    payload: dict[str, Any] = {"model": choice.model, "input": texts if len(texts) > 1 else texts[0]}
    if dimensions:
        payload["dimensions"] = dimensions
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            _api_endpoint(choice.provider, "embeddings"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"{choice.provider.name}/{choice.model} 未返回有效 embedding 数据")
    vectors: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise RuntimeError(f"{choice.provider.name}/{choice.model} 返回 embedding 结构异常")
        vector = item["embedding"]
        vectors.append({"index": int(item.get("index") or len(vectors)), "embedding": vector, "dimensions": len(vector)})
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return vectors, usage


def _call_rerank_compatible(
    choice: LLMChoice,
    *,
    query: str,
    documents: list[str],
    top_n: int = 0,
    return_documents: bool = True,
    return_raw_scores: bool = False,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = os.getenv(choice.provider.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"缺少 API key 环境变量：{choice.provider.api_key_env}")
    if not query.strip():
        raise RuntimeError("Rerank query 不能为空。")
    clean_documents = [doc for doc in documents if doc.strip()]
    if not clean_documents:
        raise RuntimeError("Rerank documents 不能为空。")
    if _provider_family(choice.provider) == "qwen":
        base = choice.provider.base_url.rstrip("/")
        if "dashscope.aliyuncs.com" in base:
            url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        else:
            url = _api_endpoint(choice.provider, "rerank")
        parameters: dict[str, Any] = {"return_documents": return_documents}
        if top_n:
            parameters["top_n"] = top_n
        payload = {
            "model": choice.model,
            "input": {"query": query, "documents": clean_documents},
            "parameters": parameters,
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        output = data.get("output") if isinstance(data, dict) else None
        results = output.get("results") if isinstance(output, dict) else None
    else:
        payload = {
            "model": choice.model,
            "query": query,
            "documents": clean_documents,
            "return_documents": return_documents,
            "return_raw_scores": return_raw_scores,
        }
        if top_n:
            payload["top_n"] = top_n
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                _api_endpoint(choice.provider, "rerank"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise RuntimeError(f"{choice.provider.name}/{choice.model} 未返回有效 rerank 结果")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return results, usage


def embed_texts(
    settings: Settings,
    texts: list[str],
    *,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    timeout: float | None = None,
    allow_paid: bool = False,
) -> dict[str, Any]:
    choices = _adapter_choices(settings, "embed", provider_name=provider, model=model)
    if not allow_paid:
        choices = [choice for choice in choices if _free_only_eligible_provider(choice.provider)]
    if not choices:
        raise RuntimeError("没有无需付费授权的 embedding adapter；付费路线必须显式使用 --allow-paid。")
    states = _load_route_state(settings)
    errors: list[str] = []
    for choice in choices:
        started = time.perf_counter()
        try:
            vectors, usage = _call_embedding_compatible(choice, texts=texts, dimensions=dimensions, timeout=timeout or settings.timeout)
            _record_success(settings, choice, states)
            input_tokens = int(usage.get("prompt_tokens") or sum(_estimate_tokens(text) for text in texts))
            ledger_id = _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "embedding_call",
                    "task": "embed",
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "free": choice.provider.free,
                    "latency_s": round(time.perf_counter() - started, 3),
                    "input_count": len(texts),
                    "dimensions": vectors[0]["dimensions"] if vectors else dimensions,
                    "input_tokens_est": input_tokens,
                    "output_tokens_est": 0,
                    "estimated_cost_usd": _estimated_cost_usd(choice, input_tokens, 0),
                },
            )
            return {
                "provider": choice.provider.name,
                "model": choice.model,
                "endpoint_family": _choice_endpoint_family(choice),
                "input_count": len(texts),
                "usage": usage,
                "ledger_id": ledger_id,
                "data": vectors,
            }
        except Exception as exc:
            _record_failure(settings, choice, states, exc)
            errors.append(f"{choice.provider.name}/{choice.model}: {str(exc).replace(chr(10), ' ')[:180]}")
    raise RuntimeError("所有 embedding adapter 均失败：" + " | ".join(errors))


def rerank_documents(
    settings: Settings,
    *,
    query: str,
    documents: list[str],
    provider: str | None = None,
    model: str | None = None,
    top_n: int = 0,
    return_documents: bool = True,
    return_raw_scores: bool = False,
    timeout: float | None = None,
    allow_paid: bool = False,
) -> dict[str, Any]:
    choices = _adapter_choices(settings, "rerank", provider_name=provider, model=model)
    if not allow_paid:
        choices = [choice for choice in choices if _free_only_eligible_provider(choice.provider)]
    if not choices:
        raise RuntimeError("没有无需付费授权的 rerank adapter；付费路线必须显式使用 --allow-paid。")
    states = _load_route_state(settings)
    errors: list[str] = []
    for choice in choices:
        started = time.perf_counter()
        try:
            results, usage = _call_rerank_compatible(
                choice,
                query=query,
                documents=documents,
                top_n=top_n,
                return_documents=return_documents,
                return_raw_scores=return_raw_scores,
                timeout=timeout or settings.timeout,
            )
            _record_success(settings, choice, states)
            input_tokens = int(usage.get("prompt_tokens") or _estimate_tokens(query + "\n" + "\n".join(documents)))
            ledger_id = _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "rerank_call",
                    "task": "rerank",
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "free": choice.provider.free,
                    "latency_s": round(time.perf_counter() - started, 3),
                    "document_count": len(documents),
                    "input_tokens_est": input_tokens,
                    "output_tokens_est": 0,
                    "estimated_cost_usd": _estimated_cost_usd(choice, input_tokens, 0),
                },
            )
            return {
                "provider": choice.provider.name,
                "model": choice.model,
                "endpoint_family": _choice_endpoint_family(choice),
                "query": query,
                "usage": usage,
                "ledger_id": ledger_id,
                "results": results,
            }
        except Exception as exc:
            _record_failure(settings, choice, states, exc)
            errors.append(f"{choice.provider.name}/{choice.model}: {str(exc).replace(chr(10), ' ')[:180]}")
    raise RuntimeError("所有 rerank adapter 均失败：" + " | ".join(errors))


def _extract_text_payload(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        parts = [_extract_text_payload(item) for item in data]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(data, dict):
        for key in ("text", "transcript", "content"):
            value = _extract_text_payload(data.get(key))
            if value:
                return value
        for key in ("message", "choices", "output", "data", "result"):
            value = _extract_text_payload(data.get(key))
            if value:
                return value
    return ""


def remote_transcribe_media(
    settings: Settings,
    input_file: str | Path,
    *,
    provider: str,
    model: str | None = None,
    language: str = "zh",
    allow_external: bool = False,
    allow_paid: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    if not allow_external:
        raise RuntimeError("远程 ASR 会上传音频；必须显式传入 --allow-external。私密音频默认继续使用本地 ASR。")
    source = Path(input_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    choices = _adapter_choices(settings, "asr", provider_name=provider, model=model)
    if not choices:
        raise RuntimeError("没有匹配且健康的远程 ASR adapter。")
    choice = choices[0]
    if not _free_only_eligible_provider(choice.provider) and not allow_paid:
        raise RuntimeError("远程 ASR 路线可能计费；必须显式传入 --allow-paid。")
    key = os.getenv(choice.provider.api_key_env, "").strip()
    family = _provider_family(choice.provider)
    request_timeout = timeout or max(settings.timeout, 120)
    started = time.perf_counter()
    if family == "zhipu":
        with source.open("rb") as handle, httpx.Client(timeout=request_timeout) as client:
            response = client.post(
                _api_endpoint(choice.provider, "audio/transcriptions"),
                headers={"Authorization": f"Bearer {key}"},
                data={"model": choice.model, "stream": "false"},
                files={"file": (source.name, handle, mimetypes.guess_type(source.name)[0] or "application/octet-stream")},
            )
            response.raise_for_status()
            data = response.json()
    elif family == "qwen":
        raw = source.read_bytes()
        if len(raw) > 10 * 1024 * 1024:
            raise RuntimeError("Qwen3-ASR base64 输入上限为 10 MB；请先本地切块。")
        mime = mimetypes.guess_type(source.name)[0] or "audio/wav"
        audio_data = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        payload = {
            "model": choice.model,
            "input": {"messages": [{"role": "user", "content": [{"audio": audio_data}]}]},
            "parameters": {"asr_options": {"language": language, "enable_itn": True}},
        }
        with httpx.Client(timeout=request_timeout) as client:
            response = client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    else:
        raise RuntimeError(f"尚未实现 {family} 远程 ASR adapter。")
    text = _extract_text_payload(data)
    if not text:
        raise RuntimeError(f"{choice.provider.name}/{choice.model} 未返回转写文本。")
    return {
        "provider": choice.provider.name,
        "model": choice.model,
        "source_name": source.name,
        "uploaded_external": True,
        "latency_s": round(time.perf_counter() - started, 3),
        "text": text,
    }


def generate_image(
    settings: Settings,
    prompt: str,
    *,
    provider: str = "zhipu",
    model: str | None = None,
    size: str = "1024x1024",
    quality: str = "hd",
    allow_paid: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    if not allow_paid:
        raise RuntimeError("图像生成会产生费用；必须显式传入 --allow-paid。")
    choices = _adapter_choices(settings, "image_generate", provider_name=provider, model=model)
    if not choices:
        raise RuntimeError("没有匹配且健康的图像生成 adapter。")
    choice = choices[0]
    if _provider_family(choice.provider) != "zhipu":
        raise RuntimeError("当前生产适配器只实现智谱 GLM-Image；其他厂商保留为候选能力。")
    key = os.getenv(choice.provider.api_key_env, "").strip()
    payload = {"model": choice.model, "prompt": prompt, "size": size, "quality": quality}
    with httpx.Client(timeout=timeout or max(settings.timeout, 120)) as client:
        response = client.post(
            _api_endpoint(choice.provider, "images/generations"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    images = data.get("data") if isinstance(data, dict) else None
    if not isinstance(images, list) or not images:
        raise RuntimeError(f"{choice.provider.name}/{choice.model} 未返回图像结果。")
    return {
        "provider": choice.provider.name,
        "model": choice.model,
        "size": size,
        "quality": quality,
        "paid": True,
        "data": images,
    }


def _write_modality_probe_image(tmpdir: str | Path) -> Path:
    # 1x1 PNG is enough to verify image transport support without leaking real images.
    image_path = Path(tmpdir) / "router-modality-probe.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
    )
    return image_path


def _modality_probe_messages(task: str, *, image_path: str | Path | None = None) -> list[dict[str, Any]]:
    task = normalize_task_type(task)
    if task == "vision":
        return _messages_for_task("vision", "这是连通性小探针。只输出 JSON：{\"ok\":true,\"modality\":\"vision\"}", None, image_path=image_path)
    if task == "ocr":
        return _messages_for_task("ocr", "这是 OCR/视觉输入连通性小探针。若看不清文字，只输出 JSON：{\"ok\":true,\"visible_text\":\"\"}", None, image_path=image_path)
    if task == "transcript_correct":
        return _messages_for_task(
            "transcript_correct",
            "只修正明显同音错字并输出一句话。",
            "讲者说这个接口不是这么调用的，缓存策略要结合并发语境复核。",
        )
    if task == "code":
        return _messages_for_task("code", "只输出 OK：检查 Python 表达式 1 + 1 == 2 是否成立。", None)
    if task == "audit":
        return _messages_for_task("audit", "只输出 OK：这是一条审计连通性探针。", None)
    return _messages_for_task("qa", "只输出 OK 两个字。", None)


def _health_probe_tasks(tasks: list[str] | tuple[str, ...] | None) -> list[str]:
    raw_tasks = tasks or DEFAULT_MODALITY_HEALTH_TASKS
    clean: list[str] = []
    seen: set[str] = set()
    for task in raw_tasks:
        normalized = normalize_task_type(str(task))
        if normalized in SPECIALIZED_TASKS or normalized in LOCAL_ONLY_TASKS:
            continue
        if normalized not in TASK_TYPES or normalized in seen:
            continue
        seen.add(normalized)
        clean.append(normalized)
    return clean


def _probe_chat_choice(
    choice: LLMChoice,
    *,
    messages: list[dict[str, Any]],
    timeout: float,
) -> tuple[str, dict[str, Any], int]:
    """Probe once, then give reasoning models enough room for a final answer."""
    attempts = 0
    for max_tokens in (96, 512):
        attempts += 1
        try:
            content, usage = _call_openai_compatible(
                choice,
                messages=messages,
                timeout=timeout,
                temperature=0,
                max_tokens=max_tokens,
            )
            return content, usage, attempts
        except InconclusiveModelOutput:
            if max_tokens == 512:
                raise
    raise AssertionError("unreachable")


def _emit_refresh_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:
        # Progress rendering must never change routing or health semantics.
        pass


def refresh_model_pool(
    settings: Settings,
    *,
    include_paid: bool = False,
    timeout: float = 6.0,
    limit: int = 0,
    task: str = "qa",
    quality_target: str = "production",
    include_unprotected_trial: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    states = _load_route_state(settings)
    normalized_task = normalize_task_type(task)
    if normalized_task in ROLE_TASKS:
        choices = _role_policy_choices(
            settings,
            role=normalized_task,
            quality_target=quality_target,
            input_tokens=256,
            max_cost_usd=None,
            paid_allowed=include_paid,
            collapse_key_rotations=False,
        )
    else:
        choices = _model_choices(
            settings,
            task=normalized_task if normalized_task in TASK_TYPES else "qa",
            only_free=not include_paid,
        )
    choices = _rank_choices(
        [
            choice
            for choice in choices
            if include_unprotected_trial or _provider_execution_enabled(choice.provider)
        ],
        normalized_task,
    )
    if not include_paid:
        choices = [choice for choice in choices if choice.provider.free]
    if limit > 0:
        choices = choices[:limit]
    rows: list[dict[str, Any]] = []
    messages = [
        {"role": "system", "content": "只做模型连通性测试。不要输出思考过程。"},
        {"role": "user", "content": "最终答案只输出 OK 两个字。"},
    ]
    report_path = _refresh_report_path(settings)
    report: dict[str, Any] = {
        "schema": "smart_llm_router.pool_refresh.v2",
        "status": "running",
        "started_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
        "include_paid": include_paid,
        "include_unprotected_trial": include_unprotected_trial,
        "task": normalized_task,
        "quality_target": quality_target,
        "timeout": timeout,
        "limit": limit,
        "total": len(choices),
        "completed": 0,
        "results": rows,
    }
    _atomic_write_json(report_path, report)
    for index, choice in enumerate(choices, 1):
        started = _now()
        _emit_refresh_progress(
            progress,
            {
                "event": "probe_started",
                "index": index,
                "total": len(choices),
                "provider": choice.provider.name,
                "model": choice.model,
            },
        )
        try:
            content, _usage, attempts = _probe_chat_choice(
                choice,
                messages=messages,
                timeout=timeout,
            )
            _record_success(settings, choice, states)
            row = {
                "provider": choice.provider.name,
                "model": choice.model,
                "free": choice.provider.free,
                "ok": True,
                "endpoint_reachable": True,
                "attempts": attempts,
                "sample": content[:40],
                "checked_at": started.isoformat(),
            }
        except Exception as exc:
            _record_failure(settings, choice, states, exc)
            row = {
                "provider": choice.provider.name,
                "model": choice.model,
                "free": choice.provider.free,
                "ok": False,
                "endpoint_reachable": isinstance(exc, InconclusiveModelOutput),
                "failure_class": "no_final_content" if isinstance(exc, InconclusiveModelOutput) else classify_route_failure(str(exc)),
                "error": str(exc).replace("\n", " ")[:240],
                "checked_at": started.isoformat(),
            }
        rows.append(row)
        report["completed"] = index
        report["updated_at"] = _now().isoformat()
        _atomic_write_json(report_path, report)
        _emit_refresh_progress(
            progress,
            {
                "event": "probe_completed",
                "index": index,
                "total": len(choices),
                "provider": choice.provider.name,
                "model": choice.model,
                "ok": row["ok"],
            },
        )
    report["status"] = "complete"
    report["completed_at"] = _now().isoformat()
    report["updated_at"] = report["completed_at"]
    _atomic_write_json(report_path, report)
    return rows


def refresh_model_pool_by_modality(
    settings: Settings,
    *,
    include_paid: bool = False,
    timeout: float = 6.0,
    limit: int = 0,
    tasks: list[str] | tuple[str, ...] | None = None,
    families: list[str] | tuple[str, ...] | None = None,
    include_unprotected_trial: bool = False,
) -> dict[str, Any]:
    states = _load_route_state(settings)
    probe_tasks = _health_probe_tasks(tasks)
    family_filter = {str(family).strip().lower() for family in (families or []) if str(family).strip()}
    report: dict[str, Any] = {
        "refreshed_at": _now().isoformat(),
        "include_paid": include_paid,
        "include_unprotected_trial": include_unprotected_trial,
        "timeout": timeout,
        "limit_per_task": limit,
        "tasks": probe_tasks,
        "families": sorted(family_filter),
        "results": {},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        probe_image = _write_modality_probe_image(tmpdir)
        for task in probe_tasks:
            choices = _model_choices(settings, task=task, only_free=not include_paid)
            if not include_paid:
                choices = [choice for choice in choices if choice.provider.free]
            if not include_unprotected_trial:
                choices = [choice for choice in choices if _provider_execution_enabled(choice.provider)]
            if family_filter:
                choices = [
                    choice
                    for choice in choices
                    if _provider_family(choice.provider) in family_filter or _model_family(choice) in family_filter
                ]
            if limit > 0:
                choices = choices[:limit]
            rows: list[dict[str, Any]] = []
            image_path = probe_image if task in VISION_TASKS else None
            messages = _modality_probe_messages(task, image_path=image_path)
            for choice in choices:
                started = _now()
                row = {
                    "task": task,
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "provider_family": _provider_family(choice.provider),
                    "model_family": _model_family(choice),
                    "free": choice.provider.free,
                    "input_modalities": _choice_modalities(choice)["input"],
                    "output_modalities": _choice_modalities(choice)["output"],
                    "checked_at": started.isoformat(),
                }
                try:
                    if task == "embed":
                        vectors, _usage = _call_embedding_compatible(choice, texts=["分布式系统需要处理故障恢复。"], dimensions=256, timeout=timeout)
                        _record_success(settings, choice, states)
                        row.update({"ok": True, "sample": f"embedding_dim={vectors[0]['dimensions']}"})
                    elif task == "rerank":
                        results, _usage = _call_rerank_compatible(
                            choice,
                            query="router health check",
                            documents=["relevant route", "unrelated route"],
                            top_n=1,
                            timeout=timeout,
                        )
                        _record_success(settings, choice, states)
                        score = results[0].get("relevance_score") if results else None
                        row.update({"ok": True, "sample": f"top_score={score}"})
                    else:
                        content, _usage = _call_openai_compatible(choice, messages=messages, timeout=timeout, temperature=0, max_tokens=96)
                        _record_success(settings, choice, states)
                        row.update({"ok": True, "sample": content[:80]})
                except Exception as exc:
                    _record_failure(settings, choice, states, exc)
                    row.update({"ok": False, "error": str(exc).replace("\n", " ")[:240]})
                rows.append(row)
            report["results"][task] = rows
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _modality_refresh_report_path(settings).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _maybe_refresh_when_free_pool_empty(
    settings: Settings,
    states: dict[str, RouteState],
    task: str,
    *,
    quality_target: str = "production",
) -> dict[str, RouteState]:
    normalized_task = normalize_task_type(task)
    if normalized_task in ROLE_TASKS:
        free_pool = _role_policy_choices(
            settings,
            role=normalized_task,
            quality_target=quality_target,
            input_tokens=256,
            max_cost_usd=None,
            paid_allowed=False,
            collapse_key_rotations=False,
        )
    else:
        free_pool = _model_choices(settings, task=normalized_task, only_free=True)
    free_pool = [
        choice for choice in free_pool if _provider_execution_enabled(choice.provider)
    ]
    if any(_is_available(choice, states) for choice in free_pool):
        return states
    if not free_pool:
        return states
    refresh_model_pool(
        settings,
        include_paid=False,
        timeout=settings.empty_pool_refresh_timeout,
        limit=settings.empty_pool_refresh_limit,
        task=normalized_task,
        quality_target=quality_target,
    )
    return _load_route_state(settings)


def _tokenize_query(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
    chars = [text[index : index + 2] for index in range(max(0, len(text) - 1)) if "\u4e00" <= text[index] <= "\u9fff"]
    return words + chars


def _iter_text_files(root: Path) -> list[Path]:
    allowed = {".txt", ".md", ".markdown"}
    return [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in allowed and not any(part.startswith(".") for part in path.parts)]


def retrieve_local_context(search_dir: str | Path, query: str, *, limit: int = 5, max_chars: int = 6000) -> str:
    root = Path(search_dir).expanduser()
    if not root.exists():
        raise RuntimeError(f"检索目录不存在：{root}")
    query_terms = Counter(_tokenize_query(query))
    if not query_terms:
        return ""
    scored: list[tuple[float, Path, str]] = []
    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
        for chunk in chunks[:200]:
            terms = Counter(_tokenize_query(chunk[:5000]))
            overlap = sum(min(count, terms.get(term, 0)) for term, count in query_terms.items())
            if overlap <= 0:
                continue
            density = overlap / max(1, _estimate_tokens(chunk))
            scored.append((overlap + density, path, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = []
    used = 0
    for score, path, chunk in scored[: max(1, limit * 3)]:
        snippet = chunk[: min(len(chunk), max(500, max_chars // max(1, limit)))]
        block = f"[source: {path.name}, score: {score:.3f}]\n{snippet}"
        if used + len(block) > max_chars and selected:
            break
        selected.append(block)
        used += len(block)
        if len(selected) >= limit:
            break
    return "\n\n---\n\n".join(selected)


def trim_context(context: str | None, max_chars: int | None) -> str | None:
    if context is None or not max_chars or max_chars <= 0 or len(context) <= max_chars:
        return context
    head = max_chars // 2
    tail = max_chars - head
    return context[:head] + "\n\n[...context trimmed locally...]\n\n" + context[-tail:]


def run_llm_task(
    settings: Settings,
    *,
    task: str,
    prompt: str,
    context: str | None = None,
    prefer_free: bool = True,
    paid_fallback: bool = False,
    temperature: float = 0.2,
    max_context_chars: int | None = None,
    image_path: str | Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    avoid_routes: list[str] | tuple[str, ...] | None = None,
    preprocess: bool = False,
    preprocess_target_tokens: int = 0,
    quality_target: str = "production",
    privacy: str = "auto",
    allow_external: bool = False,
    max_cost_usd: float | None = None,
    max_output_tokens: int | None = None,
    thinking_mode: str = "auto",
    thinking_budget_tokens: int | None = None,
    final_answer_reserve_tokens: int | None = None,
    workflow_id: str | None = None,
    workflow_max_cost_usd: float | None = None,
    workflow_stage: str | None = None,
    request_timeout: float | None = None,
    allow_unqualified_explicit_route: bool = False,
    allow_unprotected_trial_route: bool = False,
    strict_controls: bool = False,
    cache_enabled: bool | None = None,
    input_token_guard_factor: float | None = None,
    openrouter_upstream_providers: list[str] | tuple[str, ...] | None = None,
    openrouter_allow_fallbacks: bool = True,
    openrouter_require_zdr: bool = False,
    openrouter_deny_data_collection: bool = False,
) -> LLMResult:
    control_preflight = build_control_preflight(
        strict_controls=strict_controls,
        explicit_cache_enabled=cache_enabled,
    )
    effective_cache_enabled = control_preflight.effective_cache_enabled
    max_cost_usd = _validate_budget_ceiling(
        max_cost_usd,
        name="max_cost_usd",
        strictly_positive=False,
    )
    workflow_max_cost_usd = _validate_budget_ceiling(
        workflow_max_cost_usd,
        name="workflow_max_cost_usd",
        strictly_positive=True,
    )
    input_token_guard_factor = _validate_input_token_guard_factor(input_token_guard_factor)
    task = normalize_task_type(task)
    workflow_budget_dir = settings.budget_authority_dir
    workflow_budget_authority_id = budget_authority_id(workflow_budget_dir)
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"不支持的质量档位：{quality_target}")
    if paid_fallback and max_cost_usd is None:
        raise ValueError("程序接口启用付费路线时必须设置 max_cost_usd 单次硬上限")
    if max_output_tokens is not None and max_output_tokens <= 0:
        raise ValueError("max_output_tokens 必须为正数")
    thinking_mode = thinking_mode.strip().lower()
    if thinking_mode not in {"auto", "enabled", "disabled"}:
        raise ValueError("thinking_mode 仅支持 auto、enabled 或 disabled")
    if thinking_budget_tokens is not None and thinking_budget_tokens <= 0:
        raise ValueError("thinking_budget_tokens 必须为正数")
    if final_answer_reserve_tokens is not None and final_answer_reserve_tokens <= 0:
        raise ValueError("final_answer_reserve_tokens 必须为正数")
    if bool(workflow_id) != (workflow_max_cost_usd is not None):
        raise ValueError("workflow_id 和 workflow_max_cost_usd 必须同时设置")
    if workflow_id and max_cost_usd is None:
        raise ValueError("工作流预算调用必须同时设置 max_cost_usd 单次硬上限")
    if request_timeout is not None and request_timeout <= 0:
        raise ValueError("request_timeout 必须为正数")
    normalized_upstream_providers = tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in (openrouter_upstream_providers or ())
            if str(item).strip()
        )
    )
    invalid_upstream_providers = [
        item
        for item in normalized_upstream_providers
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", item)
    ]
    if invalid_upstream_providers:
        raise ValueError("OpenRouter upstream provider 必须使用公开 provider slug。")
    openrouter_controls_requested = bool(
        normalized_upstream_providers
        or not openrouter_allow_fallbacks
        or openrouter_require_zdr
        or openrouter_deny_data_collection
    )
    if task in LOCAL_ONLY_TASKS:
        raise RuntimeError(f"任务 {task} 是本地专用流程；请使用 transcribe/asr-status 或 route-plan，而不是 chat 模型调用。")
    if task in {"embed", "rerank"}:
        raise RuntimeError(f"任务 {task} 已有专用 adapter；请使用 smart-llm-router {task} 命令，而不是通用 task/chat 调用。")
    if task in SPECIALIZED_TASKS:
        raise RuntimeError(f"任务 {task} 需要专用 provider adapter；当前只允许 capabilities/route-plan 规划，不直接走 chat/completions。")
    no_think_marker = bool(re.search(r"(?<!\S)/no_think(?!\S)", prompt, flags=re.IGNORECASE))
    if no_think_marker:
        if thinking_mode == "enabled":
            raise ValueError("/no_think 与 thinking_mode=enabled 不能同时使用")
        thinking_mode = "disabled"
        prompt = re.sub(r"(?<!\S)/no_think(?!\S)", " ", prompt, flags=re.IGNORECASE).strip()
    context = trim_context(context, max_context_chars)
    inferred_modalities = ["text", "image"] if image_path else ["text"]
    privacy_mode, privacy_reasons = _infer_privacy_mode(
        privacy=privacy,
        prompt=prompt,
        context=context,
        input_modalities=inferred_modalities,
    )
    preprocessing: dict[str, Any] | None = None
    original_context_fingerprint = _text_fingerprint(context)
    if preprocess:
        preprocessing = preprocess_input(task=task, prompt=prompt, context=context, target_tokens=preprocess_target_tokens)
        if not preprocessing["tier_decision"].get("cloud_allowed", True):
            complexity = preprocessing["complexity"]
            ledger_id = _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "local_preprocess",
                    "task": task,
                    "provider": "local-preprocess",
                    "model": "local_rules",
                    "free": True,
                    "complexity": complexity,
                    "preprocess": _preprocess_ledger_summary(preprocessing),
                    "input_tokens_est": preprocessing["raw_tokens_est"],
                    "output_tokens_est": preprocessing["compressed_tokens_est"],
                    "estimated_cost_usd": 0.0,
                },
            )
            return LLMResult(provider="local-preprocess", model="local_rules", content=json.dumps(preprocessing, ensure_ascii=False, indent=2), cached=False, complexity=complexity["label"], ledger_id=ledger_id)
        if preprocessing.get("compressed_context"):
            context = str(preprocessing["compressed_context"])
    complexity = score_task_complexity(task, prompt, context)
    if complexity["label"] == "simple" and prefer_free and task not in VISION_TASKS and task not in ROLE_TASKS and task != "transcript_correct":
        paid_fallback = False
    image_fingerprint = _image_hash(image_path)
    cache_key = _cache_key(
        task=task,
        prompt=prompt,
        context=context,
        prefer_free=prefer_free,
        paid_fallback=paid_fallback,
        temperature=temperature,
        image_hash=image_fingerprint,
        provider=provider,
        model=model,
        avoid_routes=avoid_routes,
        quality_target=quality_target,
        privacy=privacy_mode,
        allow_external=allow_external,
        max_cost_usd=max_cost_usd,
        max_output_tokens=max_output_tokens,
        thinking_mode=thinking_mode,
        thinking_budget_tokens=thinking_budget_tokens,
        final_answer_reserve_tokens=final_answer_reserve_tokens,
        complexity_label=complexity["label"],
        complexity_source=complexity["complexity_source"],
        complexity_version=complexity["shadow_descriptor_v2"]["classification_version"],
        openrouter_upstream_providers=normalized_upstream_providers,
        openrouter_allow_fallbacks=openrouter_allow_fallbacks,
        openrouter_require_zdr=openrouter_require_zdr,
        openrouter_deny_data_collection=openrouter_deny_data_collection,
    )
    cache_debug = {
        "cache_key": cache_key[:16],
        "prompt_fingerprint": _text_fingerprint(prompt),
        "context_fingerprint": _text_fingerprint(context),
        "original_context_fingerprint": original_context_fingerprint,
        "image_fingerprint": image_fingerprint[:16],
        "provider_filter": provider or "",
        "model_filter": model or "",
        "avoid_routes": list(avoid_routes or []),
        "quality_target": quality_target,
        "privacy": privacy_mode,
        "privacy_reasons": privacy_reasons,
        "max_cost_usd": max_cost_usd,
        "max_output_tokens": max_output_tokens,
        "thinking_mode": thinking_mode,
        "thinking_budget_tokens": thinking_budget_tokens,
        "final_answer_reserve_tokens": final_answer_reserve_tokens,
        "no_think_marker": no_think_marker,
        "workflow_id": workflow_id,
        "workflow_max_cost_usd": workflow_max_cost_usd,
        "workflow_stage": workflow_stage,
        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
        "preprocess": _preprocess_ledger_summary(preprocessing) if preprocessing else None,
        "control_preflight": control_preflight.evidence(),
        "openrouter_request_controls": {
            "requested": openrouter_controls_requested,
            "upstream_providers": list(normalized_upstream_providers),
            "provider_fallbacks_allowed": openrouter_allow_fallbacks,
            "zdr_required": openrouter_require_zdr,
            "data_collection_denied": openrouter_deny_data_collection,
        },
    }
    base_cache_evidence = {
        "requested_cache_enabled": control_preflight.requested_cache_enabled,
        "effective_cache_enabled": effective_cache_enabled,
        "cache_control_source": control_preflight.cache_control_source,
        "cache_hit": False,
        "response_cache_persisted": False,
    }
    required_output_spec = _required_structured_output_spec(complexity, prompt, task=task, context=context)
    required_output_format = required_output_spec["format"]
    response_format = _structured_response_format(required_output_spec)
    if effective_cache_enabled:
        cache = _load_response_cache(settings)
        cached = cache.get(cache_key)
        cached_choice: LLMChoice | None = None
        if isinstance(cached, dict) and cached.get("content"):
            cached_choice, policy_error = _cached_choice_policy_status(
                settings,
                cached,
                task=task,
                prefer_free=prefer_free,
                paid_fallback=paid_fallback,
                provider=provider,
                model=model,
                quality_target=quality_target,
                privacy=privacy_mode,
                allow_external=allow_external,
                max_cost_usd=max_cost_usd,
                input_tokens=int(complexity.get("token_estimate") or 0) + 128,
            )
            if policy_error:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "cache_policy_rejected",
                        "task": task,
                        "provider": cached.get("provider"),
                        "model": cached.get("model"),
                        "free": cached.get("free"),
                        "complexity": complexity,
                        "cache_debug": cache_debug,
                        "policy_error": policy_error,
                        "input_tokens_est": 0,
                        "output_tokens_est": 0,
                        "estimated_cost_usd": 0.0,
                    },
                )
                cache.pop(cache_key, None)
                _save_response_cache(settings, cache)
                cached = None
        if isinstance(cached, dict) and cached.get("content"):
            output_valid, output_error = _validate_structured_output(
                str(cached["content"]),
                required_output_format,
                required_fields=required_output_spec["required_fields"],
                schema=required_output_spec["schema"],
            )
            if not output_valid:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "cache_output_rejected",
                        "task": task,
                        "provider": cached.get("provider"),
                        "model": cached.get("model"),
                        "free": cached.get("free"),
                        "complexity": complexity,
                        "cache_debug": cache_debug,
                        "required_output_format": required_output_format,
                        "output_error": output_error,
                        "input_tokens_est": 0,
                        "output_tokens_est": 0,
                        "estimated_cost_usd": 0.0,
                    },
                )
                cache.pop(cache_key, None)
                _save_response_cache(settings, cache)
                cached = None
        if isinstance(cached, dict) and cached.get("content"):
            ledger_id = _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "cache_hit",
                    "task": task,
                    "provider": cached.get("provider"),
                    "model": cached.get("model"),
                    "free": cached_choice.provider.free if cached_choice else cached.get("free"),
                    "billing_class": (
                        cached_choice.provider.billing_class
                        if cached_choice
                        else cached.get("billing_class")
                    ),
                    "privacy": privacy_mode,
                    "complexity": complexity,
                    "cache_debug": cache_debug,
                    "cache_evidence": {
                        **base_cache_evidence,
                        "cache_hit": True,
                    },
                    "input_tokens_est": 0,
                    "output_tokens_est": 0,
                    "estimated_cost_usd": 0.0,
                },
            )
            return LLMResult(provider=str(cached.get("provider") or "cache"), model=str(cached.get("model") or "cache"), content=str(cached["content"]), cached=True, complexity=complexity["label"], ledger_id=ledger_id)
    local_only_enforced = privacy_mode == "local_only" and not allow_external
    if not local_only_enforced:
        _maybe_auto_discover_free_pool(settings)
    states = _load_route_state(settings)
    if allow_unqualified_explicit_route:
        if not provider or not model:
            raise RuntimeError(
                "未登记角色模型只允许由黄金集以精确 provider/model 显式调用。"
            )
        explicit_pool = [
            choice
            for choice in configured_models(settings, only_free=False)
            if _adapter_lifecycle_route_allowed(settings, choice)
            and task in _choice_task_types(choice)
        ]
        choices = _filter_choices(
            explicit_pool,
            provider=provider,
            model=model,
        )
        choices = [
            choice
            for choice in choices
            if choice.provider.free or paid_fallback
        ]
        if not choices:
            raise RuntimeError(
                f"黄金集没有解析到允许的候选路线：provider={provider} model={model}"
            )
    elif task in ROLE_TASKS:
        if prefer_free and not local_only_enforced:
            states = _maybe_refresh_when_free_pool_empty(
                settings,
                states,
                task,
                quality_target=quality_target,
            )
        role_choices = [
            choice
            for choice in _role_policy_choices(
                settings,
                role=task,
                quality_target=quality_target,
                input_tokens=complexity["token_estimate"] + 128,
                max_cost_usd=max_cost_usd,
                paid_allowed=paid_fallback,
                history=_route_history_map(settings, task=task),
                # Recommendations collapse duplicate model/key routes for
                # readability. Execution must retain them so a throttled or
                # invalid primary key can fall through to the next credential.
                collapse_key_rotations=False,
            )
            if _is_available(choice, states)
        ]
        if not role_choices:
            minimum_band = _minimum_role_quality_band(quality_target)
            raise RuntimeError(
                f"没有满足角色 {task} 的 {quality_target} 最低质量档 {minimum_band} 的可用模型；已失败关闭，不回退到未登记通用模型。"
            )
        choices = role_choices
    elif prefer_free:
        if not local_only_enforced:
            states = _maybe_refresh_when_free_pool_empty(settings, states, task)
        active_free = [choice for choice in _model_choices(settings, task=task, only_free=True) if _is_available(choice, states)]
        paid_pool = [] if not paid_fallback else [
            choice
            for choice in _paid_fallback_choices(settings, task, quality_target)
            if _is_available(choice, states)
        ]
        choices = active_free + paid_pool
    else:
        paid_pool = [] if not paid_fallback else [
            choice
            for choice in _paid_fallback_choices(settings, task, quality_target)
            if _is_available(choice, states)
        ]
        free_pool = [choice for choice in _model_choices(settings, task=task, only_free=True) if _is_available(choice, states)]
        choices = paid_pool + free_pool
    if local_only_enforced:
        choices = [choice for choice in choices if _is_trusted_local_choice(choice)]
        if not choices:
            raise RuntimeError(
                "输入被隐私门识别为 local_only，且没有受信任的本机 loopback 模型可用；已阻止外部模型调用。"
            )
    evidence = _load_route_health(settings)
    choices = [
        choice
        for choice in choices
        if (
            allow_unprotected_trial_route
            and allow_unqualified_explicit_route
            and choice.provider.free
            and choice.provider.billing_class == "trial_quota"
            and _is_available(choice, states)
        )
        or _is_execution_eligible_choice(settings, choice, states, evidence)
    ]
    if provider or model:
        filtered = _filter_choices(choices, provider=provider, model=model)
        if not filtered:
            raise RuntimeError(f"没有匹配 provider/model 过滤条件的可用模型：provider={provider or '-'} model={model or '-'}")
        choices = filtered
    if openrouter_controls_requested:
        choices = [choice for choice in choices if _provider_family(choice.provider) == "openrouter"]
        if not choices:
            raise RuntimeError("请求了 OpenRouter 上游 provider/ZDR 控制，但没有匹配的 OpenRouter 路线；已在发送前失败关闭。")
    preferred_choices, avoided_choices = _split_avoided_choices(choices, avoid_routes)
    if preferred_choices:
        choices = preferred_choices + avoided_choices
    if not choices:
        raise RuntimeError("没有可用模型。请配置 provider 和 API key。")
    messages = _messages_for_task(task, prompt, context, image_path=image_path)
    input_tokens_est = estimate_messages_tokens(messages)
    errors = []
    for choice in choices:
        started = time.perf_counter()
        budget_output_limit = _max_output_tokens_for_budget(
            choice,
            input_tokens_est,
            max_cost_usd,
            input_token_guard_factor=input_token_guard_factor,
        )
        requested_output_limit = max_output_tokens or budget_output_limit or 4096
        thinking_plan = _thinking_plan(
            choice,
            task=task,
            total_output_tokens=requested_output_limit,
            thinking_mode=thinking_mode,
            thinking_budget_tokens=thinking_budget_tokens,
            final_answer_reserve_tokens=final_answer_reserve_tokens,
        )
        # The total reservation is the governed sum of reasoning and final
        # answer allowances when the endpoint exposes separate controls.
        reservation_output_limit = int(thinking_plan["total_output_tokens"])
        budget = _budget_status(
            choice,
            input_tokens_est,
            max_cost_usd,
            output_tokens=reservation_output_limit,
            input_token_guard_factor=input_token_guard_factor,
        )
        if not budget["eligible"]:
            incident = write_budget_incident(
                settings.data_dir,
                {
                    "kind": "single_call_budget_reservation_rejected",
                    "severity": "prevented",
                    "workflow_id": workflow_id,
                    "stage": workflow_stage,
                    "provider": choice.provider.name,
                    "model": choice.model,
                    **_budget_evidence_fields(budget),
                    "input_tokens_est": input_tokens_est,
                    "requested_max_output_tokens": max_output_tokens,
                    "reserved_output_tokens": budget.get("reserved_output_tokens"),
                    "reserved_cost_usd": budget.get("projected_cost_usd"),
                    "call_max_cost_usd": max_cost_usd,
                    "reason": budget["reason"],
                    "decision": "blocked_before_send",
                },
            )
            _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "budget_incident",
                    "incident_id": incident["incident_id"],
                    "incident_path": incident["incident_path"],
                    "incident_kind": incident["kind"],
                    "task": task,
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "workflow_id": workflow_id,
                    "workflow_stage": workflow_stage,
                    "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                    "estimated_cost_usd": 0.0,
                    "budget_forecast": _budget_evidence_fields(budget),
                },
            )
            errors.append(f"{choice.provider.name}/{choice.model}: budget gate {budget['reason']}")
            continue
        effective_output_limit = reservation_output_limit
        reserved_cost = float(budget.get("projected_cost_usd") or 0.0)
        reservation: BudgetReservation | None = None
        reservation_finalized = False
        budget_incident_logged = False
        try:
            if workflow_id and workflow_max_cost_usd is not None and max_cost_usd is not None and not choice.provider.free:
                reservation = reserve_workflow_budget(
                    workflow_budget_dir,
                    workflow_id=workflow_id,
                    workflow_max_cost_usd=workflow_max_cost_usd,
                    call_max_cost_usd=max_cost_usd,
                    reserved_cost_usd=reserved_cost,
                    stage=workflow_stage,
                    legacy_data_dirs=settings.legacy_budget_dirs,
                )
            call_options: dict[str, Any] = {}
            if thinking_plan.get("enable_thinking") is not None:
                call_options["enable_thinking"] = thinking_plan["enable_thinking"]
            if thinking_plan.get("thinking_budget_tokens"):
                call_options["thinking_budget_tokens"] = thinking_plan["thinking_budget_tokens"]
            if thinking_plan.get("thinking") is not None:
                call_options["thinking"] = thinking_plan["thinking"]
            if response_format is not None:
                call_options["response_format"] = response_format
            if openrouter_controls_requested:
                call_options.update(
                    {
                        "openrouter_upstream_providers": normalized_upstream_providers,
                        "openrouter_allow_fallbacks": openrouter_allow_fallbacks,
                        "openrouter_require_zdr": openrouter_require_zdr,
                        "openrouter_deny_data_collection": openrouter_deny_data_collection,
                    }
                )
            content, usage = _call_openai_compatible(
                choice,
                messages=messages,
                timeout=request_timeout or settings.timeout,
                temperature=temperature,
                max_tokens=effective_output_limit,
                **call_options,
            )
            output_tokens_est = int(usage.get("completion_tokens") or _estimate_tokens(content))
            completion_metadata = _sanitized_completion_metadata(usage)
            routing_metadata = _sanitized_routing_metadata(usage)
            completion_metadata["output_reached_requested_token_limit"] = bool(
                completion_metadata["output_reached_requested_token_limit"]
                or (effective_output_limit is not None and output_tokens_est >= effective_output_limit)
            )
            input_tokens = int(usage.get("prompt_tokens") or input_tokens_est)
            settled_cost = _estimated_cost_usd(choice, input_tokens, output_tokens_est)
            incident: dict[str, Any] | None = None
            budget_warning: dict[str, Any] | None = None
            if reservation is not None and settled_cost is not None:
                settlement_event = finalize_workflow_reservation(
                    workflow_budget_dir,
                    reservation,
                    actual_or_estimated_cost_usd=settled_cost,
                )
                reservation_finalized = True
                if settlement_event and settlement_event.get("decision") == "workflow_stopped":
                    incident = settlement_event
                elif settlement_event:
                    budget_warning = settlement_event
            elif max_cost_usd is not None and settled_cost is not None and settled_cost > max_cost_usd + 1e-12:
                incident = write_budget_incident(
                    settings.data_dir,
                    {
                        "kind": "single_call_hard_limit_overrun",
                        "severity": "critical",
                        "workflow_id": workflow_id,
                        "stage": workflow_stage,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "reserved_cost_usd": reserved_cost,
                        "actual_or_estimated_cost_usd": settled_cost,
                        "call_max_cost_usd": max_cost_usd,
                        "decision": "call_rejected_and_paid_routing_stopped",
                    },
                )
            elif settled_cost is not None and settled_cost > reserved_cost + 1e-12:
                budget_warning = write_budget_warning(
                    settings.data_dir,
                    {
                        "kind": "reservation_estimate_variance",
                        "severity": "warning",
                        "workflow_id": workflow_id,
                        "stage": workflow_stage,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "reserved_cost_usd": reserved_cost,
                        "actual_or_estimated_cost_usd": settled_cost,
                        "variance_usd": settled_cost - reserved_cost,
                        "call_max_cost_usd": max_cost_usd,
                        "decision": "continue_reconciled",
                    },
                )
            if budget_warning is not None:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "budget_warning",
                        "warning_id": budget_warning["warning_id"],
                        "warning_path": budget_warning["warning_path"],
                        "warning_kind": budget_warning["kind"],
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "input_tokens_est": input_tokens,
                        "output_tokens_est": output_tokens_est,
                        "reserved_cost_usd": reserved_cost,
                        "estimated_cost_usd": settled_cost,
                        "budget_forecast": _budget_evidence_fields(budget),
                        "variance_usd": budget_warning.get("variance_usd"),
                        "decision": budget_warning.get("decision"),
                    },
                )
            if incident is not None:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "budget_incident",
                        "incident_id": incident["incident_id"],
                        "incident_path": incident["incident_path"],
                        "incident_kind": incident["kind"],
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "input_tokens_est": input_tokens,
                        "output_tokens_est": output_tokens_est,
                        "estimated_cost_usd": settled_cost,
                    },
                )
                budget_incident_logged = True
                raise BudgetLimitExceeded(
                    f"付费调用超过硬预算上限，已生成事故 {incident['incident_id']} 并停止。",
                    incident,
                )
            output_valid, output_error = _validate_structured_output(
                content,
                required_output_format,
                finish_reason=completion_metadata["finish_reason"],
                output_reached_cap=completion_metadata["output_reached_requested_token_limit"],
                required_fields=required_output_spec["required_fields"],
                schema=required_output_spec["schema"],
            )
            if not output_valid:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "invalid_structured_output",
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "free": choice.provider.free,
                        "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
                        "quality_target": quality_target,
                        "privacy": privacy_mode,
                        "complexity": complexity,
                        "cache_debug": cache_debug,
                        "cache_evidence": base_cache_evidence,
                        "required_output_format": required_output_format,
                        "required_field_count": _schema_required_field_count(required_output_spec["schema"])
                        or len(required_output_spec["required_fields"]),
                        "output_error": output_error,
                        "completion_metadata": completion_metadata,
                        "latency_s": round(time.perf_counter() - started, 3),
                        "input_tokens_est": input_tokens,
                        "output_tokens_est": output_tokens_est,
                        "estimated_cost_usd": settled_cost,
                        "reserved_cost_usd": reserved_cost,
                        "budget_forecast": _budget_evidence_fields(budget),
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "settlement_basis": "provider_usage",
                        "reservation_settled": reservation is None or reservation_finalized,
                        "decision": "fail_closed_no_retry_no_fallback",
                    },
                )
                raise GovernedInvalidOutput(
                    f"{choice.provider.name}/{choice.model}: governed structured output invalid ({output_error})"
                )
            _record_success(settings, choice, states)
            response_cache_persisted = False
            if effective_cache_enabled:
                cache = _load_response_cache(settings)
                cache[cache_key] = {
                    "created_at": _now().isoformat(),
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "free": choice.provider.free,
                    "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
                    "privacy": privacy_mode,
                    "allow_external": allow_external,
                    "cache_policy_version": CACHE_POLICY_VERSION,
                    "content": content,
                }
                _save_response_cache(settings, cache)
                response_cache_persisted = True
            ledger_id = _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "model_call",
                    "task": task,
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "free": choice.provider.free,
                    "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
                    "quality_target": quality_target,
                    "privacy": privacy_mode,
                    "max_cost_usd": max_cost_usd,
                    "complexity": complexity,
                    "cache_debug": cache_debug,
                    "cache_evidence": {
                        **base_cache_evidence,
                        "response_cache_persisted": response_cache_persisted,
                    },
                    "latency_s": round(time.perf_counter() - started, 3),
                    "input_tokens_est": input_tokens,
                    "output_tokens_est": output_tokens_est,
                    "estimated_cost_usd": settled_cost,
                    "reserved_cost_usd": reserved_cost,
                    "reserved_output_tokens": budget.get("reserved_output_tokens"),
                    "budget_forecast": _budget_evidence_fields(budget),
                    "thinking_plan": thinking_plan,
                    "completion_metadata": completion_metadata,
                    "routing_metadata": routing_metadata,
                    "workflow_id": workflow_id,
                    "workflow_stage": workflow_stage,
                    "workflow_max_cost_usd": workflow_max_cost_usd,
                    "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                },
            )
            return LLMResult(provider=choice.provider.name, model=choice.model, content=content, cached=False, complexity=complexity["label"], ledger_id=ledger_id)
        except GovernedInvalidOutput as exc:
            if reservation is not None and not reservation_finalized:
                raise RuntimeError("invalid governed output left an unsettled workflow reservation") from exc
            raise RuntimeError(str(exc)) from None
        except BudgetLimitExceeded as exc:
            if reservation is not None and not reservation_finalized:
                release_workflow_reservation(workflow_budget_dir, reservation)
            if not budget_incident_logged:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "budget_incident",
                        "incident_id": exc.incident.get("incident_id"),
                        "incident_path": exc.incident.get("incident_path"),
                        "incident_kind": exc.incident.get("kind"),
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "estimated_cost_usd": 0.0,
                    },
                )
            raise RuntimeError(str(exc)) from None
        except Exception as exc:
            failure_usage = exc.usage if isinstance(exc, InconclusiveModelOutput) else {}
            failure_input_tokens = int(failure_usage.get("prompt_tokens") or input_tokens_est)
            failure_output_tokens = int(failure_usage.get("completion_tokens") or 0)
            failure_usage_usable = any(
                isinstance(failure_usage.get(field), (int, float))
                and math.isfinite(float(failure_usage[field]))
                and float(failure_usage[field]) > 0
                for field in ("prompt_tokens", "completion_tokens")
            )
            failure_cost: float | None = None
            failure_cost_basis: str | None = None
            if not choice.provider.free and isinstance(exc, InconclusiveModelOutput):
                if failure_usage_usable:
                    failure_cost = _estimated_cost_usd(choice, failure_input_tokens, failure_output_tokens)
                    failure_cost_basis = "provider_usage_on_rejected_output"
                else:
                    failure_output_tokens = int(budget.get("reserved_output_tokens") or effective_output_limit or 0)
                    failure_cost = reserved_cost
                    failure_cost_basis = "reserved_worst_case_without_provider_usage"
            failure_incident: dict[str, Any] | None = None
            failure_warning: dict[str, Any] | None = None
            if reservation is not None and not reservation_finalized:
                if failure_cost is not None:
                    failure_settlement = finalize_workflow_reservation(
                        workflow_budget_dir,
                        reservation,
                        actual_or_estimated_cost_usd=failure_cost,
                    )
                    reservation_finalized = True
                    if failure_settlement and failure_settlement.get("decision") == "workflow_stopped":
                        failure_incident = failure_settlement
                    elif failure_settlement:
                        failure_warning = failure_settlement
                else:
                    release_workflow_reservation(workflow_budget_dir, reservation)
            elif failure_cost is not None and max_cost_usd is not None:
                if failure_cost > max_cost_usd + 1e-12:
                    failure_incident = write_budget_incident(
                        settings.data_dir,
                        {
                            "kind": "single_call_hard_limit_overrun",
                            "severity": "critical",
                            "workflow_id": workflow_id,
                            "stage": workflow_stage,
                            "provider": choice.provider.name,
                            "model": choice.model,
                            "reserved_cost_usd": reserved_cost,
                            "actual_or_estimated_cost_usd": failure_cost,
                            "call_max_cost_usd": max_cost_usd,
                            "decision": "call_rejected_and_paid_routing_stopped",
                        },
                    )
                elif failure_cost > reserved_cost + 1e-12:
                    failure_warning = write_budget_warning(
                        settings.data_dir,
                        {
                            "kind": "reservation_estimate_variance",
                            "severity": "warning",
                            "workflow_id": workflow_id,
                            "stage": workflow_stage,
                            "provider": choice.provider.name,
                            "model": choice.model,
                            "reserved_cost_usd": reserved_cost,
                            "actual_or_estimated_cost_usd": failure_cost,
                            "variance_usd": failure_cost - reserved_cost,
                            "call_max_cost_usd": max_cost_usd,
                            "decision": "continue_reconciled",
                        },
                    )
            if required_output_format == "json" and isinstance(exc, InconclusiveModelOutput):
                failure_completion_metadata = _sanitized_completion_metadata(failure_usage)
                if failure_completion_metadata["finish_reason"] is None:
                    failure_completion_metadata["finish_reason"] = exc.finish_reason
                if (
                    not failure_completion_metadata["output_reached_requested_token_limit"]
                    and failure_output_tokens >= effective_output_limit
                ):
                    failure_completion_metadata["output_reached_requested_token_limit"] = True
                failure_output_error = (
                    "structured_output_truncated_finish_reason_length"
                    if (exc.finish_reason or "").strip().lower() == "length"
                    else "structured_output_missing_final_content"
                )
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "invalid_structured_output",
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "free": choice.provider.free,
                        "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
                        "quality_target": quality_target,
                        "privacy": privacy_mode,
                        "complexity": complexity,
                        "cache_debug": cache_debug,
                        "cache_evidence": base_cache_evidence,
                        "required_output_format": required_output_format,
                        "required_field_count": _schema_required_field_count(required_output_spec["schema"])
                        or len(required_output_spec["required_fields"]),
                        "output_error": failure_output_error,
                        "completion_metadata": failure_completion_metadata,
                        "latency_s": round(time.perf_counter() - started, 3),
                        "input_tokens_est": failure_input_tokens,
                        "output_tokens_est": failure_output_tokens,
                        "estimated_cost_usd": 0.0 if choice.provider.free else failure_cost,
                        "reserved_cost_usd": reserved_cost,
                        "budget_forecast": _budget_evidence_fields(budget),
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "settlement_basis": failure_cost_basis or "provider_usage",
                        "reservation_settled": reservation is None or reservation_finalized,
                        "decision": "fail_closed_no_retry_no_fallback",
                    },
                )
                if failure_warning is not None:
                    _append_ledger(
                        settings,
                        {
                            "created_at": _now().isoformat(),
                            "event": "budget_warning",
                            "warning_id": failure_warning["warning_id"],
                            "warning_path": failure_warning["warning_path"],
                            "warning_kind": failure_warning["kind"],
                            "task": task,
                            "provider": choice.provider.name,
                            "model": choice.model,
                            "workflow_id": workflow_id,
                            "workflow_stage": workflow_stage,
                            "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                            "reserved_cost_usd": reserved_cost,
                            "estimated_cost_usd": failure_cost,
                            "variance_usd": failure_warning.get("variance_usd"),
                            "decision": failure_warning.get("decision"),
                        },
                    )
                if failure_incident is not None:
                    _append_ledger(
                        settings,
                        {
                            "created_at": _now().isoformat(),
                            "event": "budget_incident",
                            "incident_id": failure_incident["incident_id"],
                            "incident_path": failure_incident["incident_path"],
                            "incident_kind": failure_incident["kind"],
                            "task": task,
                            "provider": choice.provider.name,
                            "model": choice.model,
                            "workflow_id": workflow_id,
                            "workflow_stage": workflow_stage,
                            "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                            "estimated_cost_usd": failure_cost,
                        },
                    )
                    raise RuntimeError(
                        f"付费无效输出超过硬预算上限，已生成事故 {failure_incident['incident_id']} 并停止。"
                    ) from None
                raise RuntimeError(
                    f"{choice.provider.name}/{choice.model}: governed structured output invalid ({failure_output_error})"
                ) from None
            errors.append(f"{choice.provider.name}/{choice.model}: {exc}")
            health_cooldown_recorded = not isinstance(exc, RequestPolicyIncompatibility)
            if health_cooldown_recorded:
                _record_failure(settings, choice, states, exc)
            failure_class = (
                "request_policy_incompatible"
                if isinstance(exc, RequestPolicyIncompatibility)
                else classify_route_failure(str(exc))
            )
            _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "model_failure",
                    "task": task,
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "free": choice.provider.free,
                    "complexity": complexity,
                    "cache_debug": cache_debug,
                    "cache_evidence": base_cache_evidence,
                    "latency_s": round(time.perf_counter() - started, 3),
                    "input_tokens_est": failure_input_tokens,
                    "output_tokens_est": failure_output_tokens,
                    "estimated_cost_usd": 0.0 if choice.provider.free else failure_cost,
                    "reserved_cost_usd": reserved_cost,
                    "budget_forecast": _budget_evidence_fields(budget),
                    "cost_basis": failure_cost_basis,
                    "thinking_plan": thinking_plan,
                    "workflow_id": workflow_id,
                    "workflow_stage": workflow_stage,
                    "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                    "failure_class": failure_class,
                    "health_cooldown_recorded": health_cooldown_recorded,
                    "request_policy_reason": (
                        exc.reason if isinstance(exc, RequestPolicyIncompatibility) else None
                    ),
                    "error": str(exc).replace("\n", " ")[:240],
                },
            )
            if failure_warning is not None:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "budget_warning",
                        "warning_id": failure_warning["warning_id"],
                        "warning_path": failure_warning["warning_path"],
                        "warning_kind": failure_warning["kind"],
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "reserved_cost_usd": reserved_cost,
                        "estimated_cost_usd": failure_cost,
                        "variance_usd": failure_warning.get("variance_usd"),
                        "decision": failure_warning.get("decision"),
                    },
                )
            if failure_incident is not None:
                _append_ledger(
                    settings,
                    {
                        "created_at": _now().isoformat(),
                        "event": "budget_incident",
                        "incident_id": failure_incident["incident_id"],
                        "incident_path": failure_incident["incident_path"],
                        "incident_kind": failure_incident["kind"],
                        "task": task,
                        "provider": choice.provider.name,
                        "model": choice.model,
                        "workflow_id": workflow_id,
                        "workflow_stage": workflow_stage,
                        "budget_authority_id": workflow_budget_authority_id if workflow_id else None,
                        "estimated_cost_usd": failure_cost,
                    },
                )
                raise RuntimeError(
                    f"付费失败调用超过硬预算上限，已生成事故 {failure_incident['incident_id']} 并停止。"
                ) from None
    raise RuntimeError("所有模型调用失败：" + "\n".join(errors))


TRANSCRIPT_NOISE_PATTERNS = (
    "请点赞并订阅",
    "感谢观看",
    "字幕由",
)


def _clean_transcript_locally(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(pattern in line for pattern in TRANSCRIPT_NOISE_PATTERNS):
            notes.append(f"removed_noise:{line[:40]}")
            continue
        if re.fullmatch(r"[。.\s]+", line):
            continue
        line = re.sub(r"\s+", " ", line)
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, notes


def _split_text_by_chars(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs or [text]:
        if current and current_len + len(paragraph) + 2 > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        if len(paragraph) > max_chars:
            for index in range(0, len(paragraph), max_chars):
                piece = paragraph[index : index + max_chars].strip()
                if piece:
                    chunks.append(piece)
            continue
        current.append(paragraph)
        current_len += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def transcript_correct(
    settings: Settings,
    input_file: str | Path,
    *,
    output_dir: str | Path | None = None,
    domain: str = "general",
    chunk_chars: int = 3500,
    free_only: bool = True,
    prefer_free: bool = True,
    cross_check: bool = False,
    quality_target: str = "production",
    max_context_chars: int | None = 7000,
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    source = Path(input_file).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"转写稿不存在：{source}")
    out_dir = Path(output_dir).expanduser() if output_dir else source.parent / "corrected"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_text = source.read_text(encoding="utf-8", errors="ignore")
    local_cleaned, local_notes = _clean_transcript_locally(raw_text)
    chunks = _split_text_by_chars(local_cleaned, max(800, chunk_chars))
    corrected_parts: list[str] = []
    chunk_rows: list[dict[str, Any]] = []
    prompt = (
        "修正以下中文 ASR 转写稿。要求：\n"
        "1. 保持讲者原有顺序、论证链、案例过程和口语中的强调点。\n"
        "2. 只修正口误、同音错字、术语误识别、重复噪声和断句。\n"
        "3. 不要改写成营销文案，不要泛化成摘要。\n"
        "4. 不确定的术语用【待复核】标出。\n"
        f"5. 领域或主题：{domain}。只依据原文识别术语，不要凭主题补写内容。\n"
        "6. 下面【待修正原文】就是原文；请直接输出修正后的正文，不要要求我再提供材料。"
    )
    check_prompt = (
        "审校这段已修正转写稿。重点检查术语是否改错、讲者论证链是否遗漏、"
        "是否把口语误改为新错误。只输出问题清单和必要修正建议。"
    )
    for index, chunk in enumerate(chunks, start=1):
        correction_prompt = f"{prompt}\n\n【待修正原文】\n{chunk}\n\n请只输出修正后的正文。"
        result = run_llm_task(
            settings,
            task="transcript_correct",
            prompt=correction_prompt,
            context=None,
            prefer_free=prefer_free,
            paid_fallback=not free_only,
            temperature=0.1,
            max_context_chars=max_context_chars,
            max_cost_usd=max_cost_usd,
        )
        corrected = result.content.strip()
        row: dict[str, Any] = {
            "chunk": index,
            "provider": result.provider,
            "model": result.model,
            "ledger_id": result.ledger_id,
            "cached": result.cached,
            "chars_in": len(chunk),
            "chars_out": len(corrected),
        }
        if cross_check:
            check = run_llm_task(
                settings,
                task="audit",
                prompt=check_prompt,
                context=corrected,
                prefer_free=True,
                paid_fallback=False,
                temperature=0,
                max_context_chars=max_context_chars,
            )
            row["cross_check"] = {
                "provider": check.provider,
                "model": check.model,
                "ledger_id": check.ledger_id,
                "content": check.content,
            }
        corrected_parts.append(f"## chunk {index:03d}\n\n{corrected}")
        chunk_rows.append(row)

    corrected_path = out_dir / f"{source.stem}.corrected.md"
    local_clean_path = out_dir / f"{source.stem}.local-clean.txt"
    report_path = out_dir / f"{source.stem}.correction-report.json"
    local_clean_path.write_text(local_cleaned + "\n", encoding="utf-8")
    corrected_path.write_text("\n\n".join(corrected_parts).strip() + "\n", encoding="utf-8")
    report = {
        "source": str(source),
        "domain": domain,
        "quality_target": quality_target,
        "chunk_chars": chunk_chars,
        "chunks": chunk_rows,
        "local_notes": local_notes[:200],
        "local_cleaned": str(local_clean_path),
        "corrected": str(corrected_path),
        "route_plan": route_plan(
            settings,
            task="transcript_correct",
            prompt=prompt,
            context=local_cleaned[: min(len(local_cleaned), 4000)],
            input_modalities=["text"],
            output_modalities=["text"],
            domain=domain,
            quality_target=quality_target,
            risk="high" if cross_check else "medium",
            paid_allowed=not free_only,
            prefer_free=prefer_free,
            limit=8,
            max_cost_usd=max_cost_usd,
        ),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "source": str(source),
        "corrected": str(corrected_path),
        "local_cleaned": str(local_clean_path),
        "report": str(report_path),
        "chunks": len(chunks),
        "cross_check": cross_check,
    }


def discover_openrouter_free(limit: int = 20) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30) as client:
        response = client.get("https://openrouter.ai/api/v1/models?output_modalities=text")
        response.raise_for_status()
        data = response.json()
    rows = []
    for model in data.get("data") or []:
        model_id = str(model.get("id") or "")
        if model_id.endswith(":free"):
            rows.append(
                {
                    "provider": "openrouter",
                    "id": model_id,
                    "name": model.get("name") or model_id,
                    "context_length": int(model.get("context_length") or 0),
                    "created": int(model.get("created") or 0),
                    "free_signal": ":free suffix in public catalog; credential and runtime probes required",
                    "catalog_access": "public",
                    "credential_validated": False,
                    "runtime_probe_required": True,
                }
            )
    rows.sort(key=lambda row: (row["context_length"], row["created"]), reverse=True)
    return rows[:limit]


def _model_mentions_vision(model: dict[str, Any]) -> bool:
    text = json.dumps(model, ensure_ascii=False).lower()
    vision_terms = (
        "image",
        "vision",
        "multimodal",
        "vl",
        "llava",
        "qwen2-vl",
        "qwen2.5-vl",
        "qwen-vl",
        "minicpm",
        "molmo",
        "pixtral",
        "gemma-3",
        "gemma-4",
        "mistral-small-3.1",
        "phi-3.5-vision",
        "phi-4-multimodal",
    )
    return any(term in text for term in vision_terms)


def discover_openrouter_vision_free(limit: int = 20) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30) as client:
        response = client.get("https://openrouter.ai/api/v1/models")
        response.raise_for_status()
        data = response.json()
    rows = []
    for model in data.get("data") or []:
        model_id = str(model.get("id") or "")
        if not model_id.endswith(":free"):
            continue
        if not _model_mentions_vision(model):
            continue
        rows.append(
            {
                "provider": "openrouter",
                "id": model_id,
                "name": model.get("name") or model_id,
                "context_length": int(model.get("context_length") or 0),
                "created": int(model.get("created") or 0),
                "input_modalities": model.get("architecture", {}).get("input_modalities") if isinstance(model.get("architecture"), dict) else None,
                "free_signal": ":free suffix + vision/image metadata in public catalog; credential and runtime probes required",
                "catalog_access": "public",
                "credential_validated": False,
                "runtime_probe_required": True,
            }
        )
    rows.sort(key=lambda row: (row["context_length"], row["created"]), reverse=True)
    return rows[:limit]


def _nvidia_general_chat_candidate(model_id: str) -> bool:
    """Keep NVIDIA discovery out of specialist-only and non-chat lanes."""
    text = model_id.lower()
    specialist_terms = (
        "embed",
        "bge-",
        "retriever",
        "rerank",
        "rankqa",
        "reward",
        "guard",
        "safety",
        "detector",
        "detection",
        "parse",
        "nvclip",
        "deplot",
        "fuyu",
        "kosmos",
        "vision",
        "-vl",
        "multimodal",
        "omni",
        "vila",
        "neva",
        "diffusion",
        "flux",
        "image",
        "video",
        "cosmos",
        "calibration",
        "translate",
        "whisper",
        "speech",
        "audio",
        "palmyra-fin",
        "palmyra-med",
    )
    if any(term in text for term in specialist_terms):
        return False
    return not _model_mentions_vision({"id": model_id})


def discover_nvidia_models(limit: int = 50) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30) as client:
        response = client.get("https://integrate.api.nvidia.com/v1/models")
        response.raise_for_status()
        data = response.json()
    rows = []
    for model in data.get("data") or []:
        model_id = str(model.get("id") or model.get("name") or "").strip()
        if not model_id or not _nvidia_general_chat_candidate(model_id):
            continue
        rows.append(
            {
                "provider": "nvidia",
                "id": model_id,
                "object": model.get("object") or "",
                "owned_by": model.get("owned_by") or "",
                "billing_class": "trial_quota",
                "model_mode": "text_or_code_candidate",
                "free_signal": "visible in public NVIDIA catalog; credential and runtime probes required",
                "catalog_access": "public",
                "credential_validated": False,
                "runtime_probe_required": True,
            }
        )
    return rows[:limit]


def discover_ark_models(limit: int = 100) -> list[dict[str, Any]]:
    """List model ids visible to the current Ark API key without exposing it."""
    key = os.getenv("ARK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少 ARK_API_KEY")
    with httpx.Client(timeout=30) as client:
        response = client.get(
            "https://ark.cn-beijing.volces.com/api/v3/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        data = response.json()
    rows = []
    for model in data.get("data") or []:
        model_id = str(model.get("id") or model.get("name") or "").strip()
        if model_id:
            version_numbers = [int(value) for value in re.findall(r"(?<!\d)(\d{6,8})(?!\d)", model_id)]
            rows.append(
                {
                    "provider": "doubao",
                    "id": model_id,
                    "owned_by": model.get("owned_by") or "",
                    "multimodal_candidate": any(term in model_id.lower() for term in ("seed-2", "vision", "code")),
                    "version_hint": max(version_numbers, default=0),
                }
            )
    rows.sort(key=lambda row: (row["version_hint"], row["id"]), reverse=True)
    return rows[:limit]


def discover_nvidia_vision_models(limit: int = 50) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30) as client:
        response = client.get("https://integrate.api.nvidia.com/v1/models")
        response.raise_for_status()
        data = response.json()
    rows = []
    for model in data.get("data") or []:
        if not _model_mentions_vision(model):
            continue
        rows.append(
            {
                "provider": "nvidia",
                "id": model.get("id") or model.get("name") or "",
                "object": model.get("object") or "",
                "owned_by": model.get("owned_by") or "",
                "free_signal": "vision-like metadata/name in public NVIDIA catalog; credential and runtime probes required",
                "catalog_access": "public",
                "credential_validated": False,
                "runtime_probe_required": True,
            }
        )
    return rows[:limit]


def discover_groq_models(limit: int = 50) -> list[dict[str, Any]]:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少 GROQ_API_KEY")
    with httpx.Client(timeout=30) as client:
        response = client.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        data = response.json()
    return [
        {
            "provider": "groq",
            "id": model.get("id") or "",
            "owned_by": model.get("owned_by") or "",
            "active": model.get("active"),
            "context_window": model.get("context_window") or model.get("context_length") or "",
            "free_signal": "visible through authenticated Groq catalog; runtime probe required",
            "catalog_access": "authenticated",
            "credential_validated": True,
            "runtime_probe_required": True,
        }
        for model in (data.get("data") or [])[:limit]
    ]


CREDENTIAL_STATUS_FAMILIES = ("openrouter", "qwen", "nvidia", "groq")


def _credential_probe_target(provider: LLMProvider) -> tuple[str, str]:
    family = _provider_family(provider)
    if family == "openrouter":
        return "GET", "https://openrouter.ai/api/v1/key"
    if family in {"qwen", "groq"}:
        return "GET", provider.base_url.rstrip("/") + "/models"
    if family == "nvidia":
        return "POST", provider.base_url.rstrip("/") + "/chat/completions"
    raise ValueError(f"不支持凭证探测的 provider family：{family}")


def _probe_credential(provider: LLMProvider, *, timeout: float) -> dict[str, Any]:
    family = _provider_family(provider)
    key = os.getenv(provider.api_key_env, "").strip()
    base = {
        "provider_family": family,
        "provider_name": provider.name,
        "credential_slot": provider.api_key_env,
        "model_call_performed": False,
        "paid_call_performed": False,
        "callability": "not_tested",
    }
    if not key:
        return {
            **base,
            "probe_method": "none",
            "http_status": None,
            "credential_status": "missing",
            "credential_accepted": False,
            "evidence_scope": "configuration_only",
        }

    method, url = _credential_probe_target(provider)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "POST":
                response = client.post(url, headers=headers, json={})
            else:
                response = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        return {
            **base,
            "probe_method": method,
            "http_status": None,
            "credential_status": "network_error",
            "credential_accepted": None,
            "evidence_scope": "network_path_only",
            "error_type": type(exc).__name__,
        }
    except httpx.TransportError as exc:
        return {
            **base,
            "probe_method": method,
            "http_status": None,
            "credential_status": "network_error",
            "credential_accepted": None,
            "evidence_scope": "network_path_only",
            "error_type": type(exc).__name__,
        }
    except Exception as exc:
        return {
            **base,
            "probe_method": method,
            "http_status": None,
            "credential_status": "indeterminate",
            "credential_accepted": None,
            "evidence_scope": "probe_error",
            "error_type": type(exc).__name__,
        }

    status = response.status_code
    evidence_scope = "credential_authentication"
    if 200 <= status < 300:
        credential_status = "accepted"
        credential_accepted: bool | None = True
    elif family == "nvidia" and status in {400, 422}:
        credential_status = "indeterminate"
        credential_accepted = None
        evidence_scope = "request_validation_only"
    elif status == 401:
        credential_status = "rejected"
        credential_accepted = False
    elif status == 403:
        credential_status = "permission_denied"
        credential_accepted = None
    else:
        credential_status = "indeterminate"
        credential_accepted = None
    return {
        **base,
        "probe_method": method,
        "http_status": status,
        "credential_status": credential_status,
        "credential_accepted": credential_accepted,
        "evidence_scope": evidence_scope,
    }


def credential_status(
    settings: Settings,
    *,
    families: list[str] | tuple[str, ...] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    requested = tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in (families or CREDENTIAL_STATUS_FAMILIES)
            if str(item).strip()
        )
    )
    unsupported = [family for family in requested if family not in CREDENTIAL_STATUS_FAMILIES]
    if unsupported:
        raise ValueError("不支持的凭证检查 family：" + ",".join(unsupported))

    targets: list[LLMProvider] = []
    seen: set[tuple[str, str]] = set()
    for family in requested:
        candidates = sorted(
            (
                provider
                for provider in settings.providers
                if provider.free
                and provider.billing_class != "local"
                and not provider.api_key_env.startswith("DISABLED_")
                and _provider_family(provider) == family
            ),
            key=lambda provider: (provider.priority, provider.name),
        )
        for provider in candidates:
            identity = (family, provider.api_key_env)
            if identity in seen:
                continue
            seen.add(identity)
            targets.append(provider)

    results = [_probe_credential(provider, timeout=timeout) for provider in targets]
    return {
        "scope": "configured_free_remote_credentials",
        "families": list(requested),
        "results": results,
        "summary": {
            "credential_slots": len(results),
            "accepted": sum(row["credential_status"] == "accepted" for row in results),
            "rejected": sum(row["credential_status"] == "rejected" for row in results),
            "permission_denied": sum(row["credential_status"] == "permission_denied" for row in results),
            "network_error": sum(row["credential_status"] == "network_error" for row in results),
            "missing": sum(row["credential_status"] == "missing" for row in results),
            "indeterminate": sum(row["credential_status"] == "indeterminate" for row in results),
            "model_calls": 0,
            "paid_calls": 0,
        },
    }


def discover_free_pool(settings: Settings, limit: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (fn, metadata) in {
        "openrouter": (
            lambda: discover_openrouter_free(limit),
            {"catalog_access": "public", "credential_validated": False, "runtime_probe_required": True},
        ),
        "nvidia": (
            lambda: discover_nvidia_models(limit),
            {"catalog_access": "public", "credential_validated": False, "runtime_probe_required": True},
        ),
        "openrouter_vision": (
            lambda: discover_openrouter_vision_free(limit),
            {"catalog_access": "public", "credential_validated": False, "runtime_probe_required": True},
        ),
        "nvidia_vision": (
            lambda: discover_nvidia_vision_models(limit),
            {"catalog_access": "public", "credential_validated": False, "runtime_probe_required": True},
        ),
        "groq": (
            lambda: discover_groq_models(limit),
            {"catalog_access": "authenticated", "credential_validated": True, "runtime_probe_required": True},
        ),
    }.items():
        try:
            out[name] = {**metadata, "ok": True, "models": fn()}
        except Exception as exc:
            out[name] = {**metadata, "credential_validated": False, "ok": False, "error": str(exc).replace("\n", " ")[:240], "models": []}
    _record_discovered_free_models(
        settings,
        {name: value["models"] for name, value in out.items() if value.get("ok") and isinstance(value.get("models"), list)},
    )
    return out


def discover_vision_pool(settings: Settings, limit: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (fn, metadata) in {
        "openrouter_vision": (
            lambda: discover_openrouter_vision_free(limit),
            {"catalog_access": "public", "credential_validated": False, "runtime_probe_required": True},
        ),
        "nvidia_vision": (
            lambda: discover_nvidia_vision_models(limit),
            {"catalog_access": "public", "credential_validated": False, "runtime_probe_required": True},
        ),
    }.items():
        try:
            out[name] = {**metadata, "ok": True, "models": fn()}
        except Exception as exc:
            out[name] = {**metadata, "ok": False, "error": str(exc).replace("\n", " ")[:240], "models": []}
    _record_discovered_free_models(
        settings,
        {name: value["models"] for name, value in out.items() if value.get("ok") and isinstance(value.get("models"), list)},
    )
    return out


def maintain_pool(settings: Settings, *, include_paid: bool = False, timeout: float = 6.0, limit: int = 0) -> dict[str, Any]:
    discovery = discover_free_pool(settings, limit=limit or 20)
    health = refresh_model_pool_by_modality(settings, include_paid=include_paid, timeout=timeout, limit=limit)
    report = {
        "refreshed_at": _now().isoformat(),
        "include_paid": include_paid,
        "timeout": timeout,
        "limit": limit,
        "discovery": discovery,
        "health_by_modality": health,
    }
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _maintain_report_path(settings).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

def quick_vision_benchmark(
    settings: Settings,
    image_path: str | Path,
    *,
    timeout: float = 12.0,
    limit: int = 8,
    include_unprotected_trial: bool = False,
) -> dict[str, Any]:
    candidates = [
        choice
        for choice in configured_models(settings, only_free=True)
        if include_unprotected_trial or _provider_execution_enabled(choice.provider)
    ]
    candidates = _rank_choices(candidates, "vision")[:limit]
    prompt = "只输出 JSON，字段：has_hand(boolean), visible_parts(array), quality_issues(array), summary(string)。"
    result = {"created_at": _now().isoformat(), "image": str(image_path), "candidates": []}
    for choice in candidates:
        item: dict[str, Any] = {"provider": choice.provider.name, "model": choice.model}
        started = time.perf_counter()
        try:
            content, _usage = _call_openai_compatible(
                choice,
                messages=_messages_for_task("vision", prompt, None, image_path=image_path),
                timeout=timeout,
                temperature=0,
                max_tokens=300,
            )
            item.update({"ok": True, "latency_s": round(time.perf_counter() - started, 3), "content": content[:800]})
        except Exception as exc:
            item.update({"ok": False, "latency_s": round(time.perf_counter() - started, 3), "error": str(exc).replace("\n", " ")[:240]})
        result["candidates"].append(item)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "llm_vision_quick_benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def quick_benchmark(
    settings: Settings,
    *,
    timeout: float = 8.0,
    limit: int = 12,
    include_unprotected_trial: bool = False,
) -> dict[str, Any]:
    tasks = {
        "smoke": "只输出 OK。",
        "classify": "只输出 JSON：判断《分布式缓存故障复盘》属于架构、运维还是测试，字段 domain, keywords, confidence。",
        "clean": "清洗 OCR：服務狀態 正常，緩存命中率 穩定；請 保 留 原 意。",
    }
    candidates = [
        choice
        for choice in configured_models(settings, only_free=True)
        if include_unprotected_trial or _provider_execution_enabled(choice.provider)
    ]
    candidates = _rank_choices(candidates, "qa")[:limit]
    result = {"created_at": _now().isoformat(), "candidates": []}
    for choice in candidates:
        item: dict[str, Any] = {"provider": choice.provider.name, "model": choice.model, "tasks": {}}
        for name, prompt in tasks.items():
            started = time.perf_counter()
            try:
                content, _usage = _call_openai_compatible(choice, messages=[{"role": "user", "content": prompt}], timeout=timeout, temperature=0, max_tokens=120)
                item["tasks"][name] = {"ok": True, "latency_s": round(time.perf_counter() - started, 3), "content": content[:220]}
            except Exception as exc:
                item["tasks"][name] = {"ok": False, "latency_s": round(time.perf_counter() - started, 3), "error": str(exc).replace("\n", " ")[:240]}
                if name == "smoke":
                    break
        oks = [row for row in item["tasks"].values() if row.get("ok")]
        item["successes"] = len(oks)
        item["avg_latency_s"] = round(sum(row["latency_s"] for row in oks) / len(oks), 3) if oks else None
        result["candidates"].append(item)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _benchmark_path(settings).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
