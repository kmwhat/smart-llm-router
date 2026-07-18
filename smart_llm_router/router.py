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
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from .config import LLMProvider, Settings


DEFAULT_TASK_ORDER = {
    "plan": [
        "qwen-frontier-paid",
        "doubao-frontier-paid",
        "kimi-frontier-paid",
        "zhipu-glm-lowcost",
        "deepseek-direct-paid",
        "gemini-frontier-paid",
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
    "execute": "你是资深执行助手。严格按既定目标和约束完成工作，保持最小必要改动，给出可验证产物、测试证据和未解决风险。",
    "draft": "你是一线草稿助手。输出结构化、可复核的初稿，不夸大，不编造。",
    "classify": "你是资料分类助手。优先输出简洁 JSON。",
    "summarize": "你是资料摘要助手。保留术语、出处线索和关键词。",
    "clean": "你是 OCR 文本清洗助手。修正常见错字、断行和页眉页脚，保留原意。",
    "qa": "你是基于材料的初级问答助手；不确定就说不确定。",
    "vision": "你是保守的图像观察助手。只描述图中可见事实，输出结构化 JSON，不做医学诊断、身份识别或确定性预测。",
    "ocr": "你是保守的图像/OCR 观察助手。只提取图中可见文字和版面事实，不补写看不清的内容。",
    "transcript_correct": "你是中文易学课程 ASR 转写稿修正助手。只修正口误、同音错字、术语误识别、重复噪声和断句；保持老师原讲课顺序、判断链和案例逻辑；不确定处标【待复核】，不要编造。",
    "audit": "你是严格审校助手。检查遗漏、术语错误、结构问题和不可靠推断，输出可执行问题清单。",
    "verify": "你是独立复验助手。不要沿用主模型的结论；从原始目标、输入和证据重新核对，明确通过项、失败项、差异和置信度。",
    "quality_enhance": "你是最终质量提升助手。在不改变事实和边界的前提下，消除遗漏与歧义，提升结构、表达和可执行性，并列明实质改动。",
    "code": "你是代码辅助助手。优先给出可验证、最小改动、风险清楚的建议。",
}

TEXT_TASKS = {"plan", "execute", "draft", "classify", "summarize", "clean", "qa", "transcript_correct", "audit", "verify", "quality_enhance", "code"}
VISION_TASKS = {"vision", "ocr"}
LOCAL_ONLY_TASKS = {"asr"}
SPECIALIZED_TASKS = {"image_generate", "video_generate", "tts"}
ROLE_TASKS = {"plan", "execute", "audit", "verify", "quality_enhance"}
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
    "execute": ("glm-5.2", "doubao-seed-2-0-code-preview-260215", "doubao-seed-2-1-pro", "deepseek-v4-pro", "qwen3.7-plus", "qwen3.7-max", "kimi-k3", "gemini-2.5-pro", "doubao-seed-2-0-pro-260215"),
    "audit": ("gemini-2.5-pro", "gemini-3.1-pro-preview", "qwen3.7-max", "doubao-seed-2-1-pro", "deepseek-v4-pro", "glm-5.2", "kimi-k3", "doubao-seed-2-0-pro-260215"),
    "verify": ("gemini-2.5-pro", "doubao-seed-2-1-pro", "qwen3.7-max", "deepseek-v4-pro", "glm-5.2", "kimi-k3", "gemini-3.1-pro-preview", "doubao-seed-2-0-pro-260215", "openai/gpt-oss-120b"),
    "quality_enhance": ("kimi-k3", "qwen3.7-max", "doubao-seed-2-1-pro", "glm-5.2", "gemini-2.5-pro", "deepseek-v4-pro", "doubao-seed-2-0-pro-260215"),
}

# Bands express role fit, not a universal benchmark score. A higher band wins;
# within the same band, a healthy free route wins before projected cost.
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
}

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
        "task_types": ["plan", "execute", "transcript_correct", "clean", "summarize", "qa", "draft", "audit", "verify", "quality_enhance", "code"],
        "notes": "Preferred low-cost paid family for transcript correction and structured synthesis when configured directly or through OpenRouter.",
    },
    "qwen": {
        "env_keys": ["DASHSCOPE_API_KEY"],
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text", "image", "video", "embedding", "score"],
        "task_types": ["plan", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "asr", "image_generate", "embed", "rerank", "transcript_correct", "audit", "verify", "quality_enhance"],
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
        "task_types": ["plan", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "asr", "image_generate", "embed", "rerank", "audit", "verify", "quality_enhance", "transcript_correct"],
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
        "task_types": ["plan", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "asr", "image_generate", "video_generate", "embed", "audit", "verify", "quality_enhance", "code"],
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
        "task_types": ["plan", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "audit", "verify", "quality_enhance", "transcript_correct"],
        "notes": "Independent paid multimodal family, especially useful for visual review and cross-vendor verification.",
    },
    "kimi": {
        "env_keys": ["KIMI_API_KEY"],
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "task_types": ["plan", "execute", "classify", "clean", "summarize", "qa", "draft", "vision", "ocr", "audit", "verify", "quality_enhance", "transcript_correct", "code"],
        "model_modes": {
            "multimodal_reasoning": ["kimi-k3", "kimi-k2.6"],
        },
        "notes": "Long-context paid multimodal family for knowledge work, long-horizon agents, and final quality enhancement.",
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _choice_key(choice: LLMChoice) -> str:
    return f"{choice.provider.name}/{choice.model}"


def _state_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_router_state.json"


def _refresh_report_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_pool_refresh_report.json"


def _modality_refresh_report_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_modality_refresh_report.json"


def _maintain_report_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_pool_maintenance_report.json"


def _discovered_free_path(settings: Settings) -> Path:
    return settings.data_dir / "llm_discovered_free_models.json"


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


def _load_route_state(settings: Settings) -> dict[str, RouteState]:
    raw = _load_json(_state_path(settings)) or {}
    states: dict[str, RouteState] = {}
    for key, value in raw.items():
        until = value.get("unavailable_until")
        parsed_until = None
        if isinstance(until, str) and until:
            try:
                parsed_until = datetime.fromisoformat(until)
            except ValueError:
                parsed_until = None
        states[key] = RouteState(
            unavailable_until=parsed_until,
            failure_count=int(value.get("failure_count") or 0),
            reason=str(value.get("reason") or "") or None,
        )
    return states


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


def _record_success(settings: Settings, choice: LLMChoice, states: dict[str, RouteState]) -> None:
    key = _choice_key(choice)
    if key in states:
        states.pop(key, None)
        _save_route_state(settings, states)


def _record_failure(settings: Settings, choice: LLMChoice, states: dict[str, RouteState], exc: Exception) -> None:
    key = _choice_key(choice)
    previous = states.get(key)
    failure_count = (previous.failure_count if previous else 0) + 1
    states[key] = RouteState(
        unavailable_until=_now() + _cooldown_for_error(exc, failure_count),
        failure_count=failure_count,
        reason=str(exc).replace("\n", " ")[:240],
    )
    _save_route_state(settings, states)


def configured_models(settings: Settings, *, only_free: bool = False) -> list[LLMChoice]:
    choices: list[LLMChoice] = []
    for provider in settings.providers:
        if only_free and not provider.free:
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
                template = _template_provider_for_family(settings, family, str(item.get("source") or ""))
                if not template:
                    continue
                model = str(item.get("id") or "").strip()
                if not model:
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


def _role_model_rank(choice: LLMChoice, task: str) -> int:
    ordered = ROLE_MODEL_ORDER.get(normalize_task_type(task), ())
    try:
        return ordered.index(choice.model.lower())
    except ValueError:
        return 100


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
        return ["plan", "execute", "code", "clean", "qa", "summarize", "draft", "audit", "verify", "quality_enhance", "transcript_correct"]
    return ["plan", "execute", "classify", "clean", "summarize", "qa", "draft", "audit", "verify", "quality_enhance", "transcript_correct"]


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
    return {
        "provider": choice.provider.name,
        "model": choice.model,
        "provider_family": _provider_family(choice.provider),
        "model_family": model_family,
        "endpoint_family": _choice_endpoint_family(choice),
        "model_mode": _choice_model_mode(choice),
        "free": choice.provider.free,
        "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
        "priority": choice.provider.priority,
        "input_modalities": modalities["input"],
        "output_modalities": modalities["output"],
        "task_types": _choice_task_types(choice),
        "family_notes": catalog.get("notes"),
        "api_key_env": choice.provider.api_key_env,
        "estimated_input_price_per_million": _price_per_million(choice, "input"),
        "estimated_output_price_per_million": _price_per_million(choice, "output"),
        "price_currency": "USD",
        "role_fit": [role for role, models in ROLE_MODEL_ORDER.items() if choice.model.lower() in models],
        "redundancy_identity": f"{model_family}/{choice.model.lower()}",
    }


def _model_choices(settings: Settings, *, task: str, only_free: bool) -> list[LLMChoice]:
    task = normalize_task_type(task)
    choices = configured_models(settings, only_free=only_free)
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
    return ROLE_QUALITY_BANDS.get(normalize_task_type(role), {}).get(choice.model.lower(), 0)


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
) -> list[LLMChoice]:
    minimum_band = _minimum_role_quality_band(quality_target)
    choices = [
        choice
        for choice in _model_choices(settings, task=role, only_free=False)
        if _role_quality_band(choice, role) >= minimum_band and (choice.provider.free or paid_allowed)
    ]

    history = history if history is not None else _route_history_map(settings, task=role)

    def sort_key(choice: LLMChoice) -> tuple[int, int, int, float, float, float, int, int]:
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
        return (
            1 if route_history and route_history.get("degraded") else 0,
            0 if budget["eligible"] else 1,
            0 if choice.provider.free else 1,
            expected_total_cost,
            float(latency_p95) if latency_p95 is not None else float("inf"),
            -float(_role_quality_band(choice, role)),
            _role_model_rank(choice, role),
            choice.provider.priority,
        )

    return _dedupe_model_routes(sorted(choices, key=sort_key))


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
    now = _now()
    rows = []
    for choice in _rank_choices(configured_models(settings, only_free=False), "qa"):
        state = states.get(_choice_key(choice))
        unavailable_until = state.unavailable_until if state else None
        rows.append(
            {
                "provider": choice.provider.name,
                "model": choice.model,
                "free": choice.provider.free,
                "available_now": not unavailable_until or unavailable_until <= now,
                "unavailable_until": unavailable_until.isoformat() if unavailable_until else None,
                "failure_count": state.failure_count if state else 0,
                "reason": state.reason if state else None,
            }
        )
    return rows


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
    return {
        "label": label,
        "score": score,
        "token_estimate": token_estimate,
        "hard_hits": hard_hits,
        "simple_hits": simple_hits,
        "policy": "free-only preferred" if label == "simple" else "free-first with paid fallback" if label == "medium" else "free-first, allow stronger fallback",
    }


def _cache_enabled() -> bool:
    return os.getenv("SMART_LLM_CACHE", "true").strip().lower() not in {"0", "false", "no", "off"}


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
) -> str:
    payload = {
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
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _text_fingerprint(text: str | None) -> str:
    if not text:
        return ""
    return sha256(text.encode("utf-8")).hexdigest()[:16]


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
    "nodename nor servname provided",
    "temporary failure in name resolution",
)


def classify_route_failure(error: str) -> str:
    text = error.strip().lower()
    if any(term in text for term in INFRASTRUCTURE_FAILURE_TERMS):
        return "infrastructure"
    if any(term in text for term in ("429", "rate limit", "rate_limit", "too many requests", "quota", "resource_exhausted")):
        return "quota"
    if any(term in text for term in ("401", "403", "unauthorized", "forbidden", "authentication", "invalid api key")):
        return "authentication"
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


def _budget_status(choice: LLMChoice, input_tokens: int, max_cost_usd: float | None, output_tokens: int = 1024) -> dict[str, Any]:
    projected = _estimated_cost_usd(choice, input_tokens, output_tokens)
    if max_cost_usd is None or choice.provider.free:
        return {"eligible": True, "projected_cost_usd": projected, "reason": None}
    if projected is None:
        return {"eligible": False, "projected_cost_usd": None, "reason": "unknown_price_fails_closed"}
    if projected > max_cost_usd:
        return {"eligible": False, "projected_cost_usd": projected, "reason": "projected_cost_exceeds_limit"}
    return {"eligible": True, "projected_cost_usd": projected, "reason": None}


def _max_output_tokens_for_budget(
    choice: LLMChoice,
    input_tokens: int,
    max_cost_usd: float | None,
    *,
    hard_cap: int = 4096,
) -> int | None:
    if max_cost_usd is None or choice.provider.free:
        return None
    input_price = _price_per_million(choice, "input")
    output_price = _price_per_million(choice, "output")
    if input_price is None or output_price is None or output_price <= 0:
        return None
    input_cost = input_tokens * input_price / 1_000_000
    remaining = max(0.0, max_cost_usd - input_cost)
    affordable = int(remaining * 1_000_000 / output_price * 0.95)
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
    route_history = _route_history_map(settings, task=task)
    input_tokens = complexity["token_estimate"] + 128
    free = [choice for choice in _model_choices(settings, task=task, only_free=True) if _is_available(choice, states)]
    paid = [
        choice
        for choice in (_paid_fallback_choices(settings, task, quality_target) if paid_fallback else [])
        if _is_available(choice, states)
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
            if _is_available(choice, states)
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
            "role_selection_rule": "quality_floor_then_route_health_then_budget_then_free_then_retry_adjusted_cost_then_latency_then_quality_surplus",
            "historical_health_min_samples": ROUTE_HEALTH_MIN_SAMPLES,
            "infrastructure_failures_excluded_from_health": True,
            "role_tasks_force_paid": False,
            "failed_models_enter_cooldown": True,
            "cache_enabled": _cache_enabled(),
        },
        "recommended_order": [
            {
                "provider": choice.provider.name,
                "model": choice.model,
                "free": choice.provider.free,
                "billing_class": choice.provider.billing_class or ("permanent_free" if choice.provider.free else "paid"),
                "available_now": _is_available(choice, states),
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
            "微信聊天",
            "聊天记录",
            "客户原图",
            "用户原图",
            "手掌照片",
            "掌纹照片",
            "身份证",
            "手机号",
            "api key",
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
    independent_from = {"audit": "plan", "verify": "execute"}
    stages: list[dict[str, Any]] = []
    for role in ("plan", "execute", "audit", "verify", "quality_enhance"):
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
            selected["selection_reason"] = "quality_floor_then_route_health_then_budget_then_free_then_retry_adjusted_cost_then_latency_then_quality_surplus"
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
                "selection_rule": "meet the target quality floor; then route health, budget eligibility, free, retry-adjusted cost, P95 latency, quality surplus, and stable tie-breakers",
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
        if (choice.provider.free or paid_allowed)
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
        "selection_rule": "only healthy and budget-eligible chat-compatible models execute; media generation, speech, and embedding need dedicated adapters and probes",
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
            capability["available_now"] = _is_available(matching[0], states)
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
            capability["available_now"] = _is_available(choice, states)
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
            [command, "-m", str(Path(model_path).expanduser()), "-f", str(wav_path), "-l", language, "-otxt", "-osrt", "-of", str(out_dir / source.stem)],
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


def _call_openai_compatible(choice: LLMChoice, *, messages: list[dict[str, Any]], timeout: float, temperature: float, max_tokens: int | None = None) -> tuple[str, dict[str, Any]]:
    key = os.getenv(choice.provider.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"缺少 API key 环境变量：{choice.provider.api_key_env}")
    payload: dict[str, Any] = {"model": choice.model, "messages": messages, "temperature": temperature}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            choice.provider.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError(f"{choice.provider.name}/{choice.model} 返回内容为空")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
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
) -> dict[str, Any]:
    choices = _adapter_choices(settings, "embed", provider_name=provider, model=model)
    if not choices:
        raise RuntimeError("没有可用 embedding adapter。请配置 zhipu-embedding-lowcost 等 provider block。")
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
) -> dict[str, Any]:
    choices = _adapter_choices(settings, "rerank", provider_name=provider, model=model)
    if not choices:
        raise RuntimeError("没有可用 rerank adapter。请配置 zhipu-rerank-lowcost 等 provider block。")
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
    timeout: float | None = None,
) -> dict[str, Any]:
    if not allow_external:
        raise RuntimeError("远程 ASR 会上传音频；必须显式传入 --allow-external。私密课程默认继续使用本地 ASR。")
    source = Path(input_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    choices = _adapter_choices(settings, "asr", provider_name=provider, model=model)
    if not choices:
        raise RuntimeError("没有匹配且健康的远程 ASR adapter。")
    choice = choices[0]
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
            "老师说这个金门不是这么看，鬼水要按天干语境复核。",
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


def refresh_model_pool(settings: Settings, *, include_paid: bool = False, timeout: float = 6.0, limit: int = 0) -> list[dict[str, Any]]:
    states = _load_route_state(settings)
    choices = _rank_choices(configured_models(settings, only_free=not include_paid), "qa")
    if not include_paid:
        choices = [choice for choice in choices if choice.provider.free]
    if limit > 0:
        choices = choices[:limit]
    rows = []
    messages = [{"role": "system", "content": "只做模型连通性测试。"}, {"role": "user", "content": "只输出 OK 两个字。"}]
    for choice in choices:
        started = _now()
        try:
            content, _usage = _call_openai_compatible(choice, messages=messages, timeout=timeout, temperature=0, max_tokens=24)
            _record_success(settings, choice, states)
            rows.append({"provider": choice.provider.name, "model": choice.model, "free": choice.provider.free, "ok": True, "sample": content[:40], "checked_at": started.isoformat()})
        except Exception as exc:
            _record_failure(settings, choice, states, exc)
            rows.append({"provider": choice.provider.name, "model": choice.model, "free": choice.provider.free, "ok": False, "error": str(exc).replace("\n", " ")[:240], "checked_at": started.isoformat()})
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _refresh_report_path(settings).write_text(json.dumps({"refreshed_at": _now().isoformat(), "include_paid": include_paid, "timeout": timeout, "limit": limit, "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def refresh_model_pool_by_modality(
    settings: Settings,
    *,
    include_paid: bool = False,
    timeout: float = 6.0,
    limit: int = 0,
    tasks: list[str] | tuple[str, ...] | None = None,
    families: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    states = _load_route_state(settings)
    probe_tasks = _health_probe_tasks(tasks)
    family_filter = {str(family).strip().lower() for family in (families or []) if str(family).strip()}
    report: dict[str, Any] = {
        "refreshed_at": _now().isoformat(),
        "include_paid": include_paid,
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
                        vectors, _usage = _call_embedding_compatible(choice, texts=["风水讲究形势与理气。"], dimensions=256, timeout=timeout)
                        _record_success(settings, choice, states)
                        row.update({"ok": True, "sample": f"embedding_dim={vectors[0]['dimensions']}"})
                    elif task == "rerank":
                        results, _usage = _call_rerank_compatible(choice, query="风水气口", documents=["风水重视气口与来龙", "今天适合整理文件"], top_n=1, timeout=timeout)
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


def _maybe_refresh_when_free_pool_empty(settings: Settings, states: dict[str, RouteState], task: str) -> dict[str, RouteState]:
    free_pool = _model_choices(settings, task=task, only_free=True)
    if any(_is_available(choice, states) for choice in free_pool):
        return states
    refresh_model_pool(settings, include_paid=False, timeout=settings.empty_pool_refresh_timeout, limit=settings.empty_pool_refresh_limit)
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
    paid_fallback: bool = True,
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
) -> LLMResult:
    task = normalize_task_type(task)
    if quality_target not in QUALITY_TARGETS:
        raise ValueError(f"不支持的质量档位：{quality_target}")
    if max_cost_usd is not None and max_cost_usd < 0:
        raise ValueError("max_cost_usd 不能为负数")
    if task in LOCAL_ONLY_TASKS:
        raise RuntimeError(f"任务 {task} 是本地专用流程；请使用 transcribe/asr-status 或 route-plan，而不是 chat 模型调用。")
    if task in {"embed", "rerank"}:
        raise RuntimeError(f"任务 {task} 已有专用 adapter；请使用 smart-llm-router {task} 命令，而不是通用 task/chat 调用。")
    if task in SPECIALIZED_TASKS:
        raise RuntimeError(f"任务 {task} 需要专用 provider adapter；当前只允许 capabilities/route-plan 规划，不直接走 chat/completions。")
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
        "preprocess": _preprocess_ledger_summary(preprocessing) if preprocessing else None,
    }
    if _cache_enabled():
        cache = _load_response_cache(settings)
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("content"):
            ledger_id = _append_ledger(
                settings,
                {
                    "created_at": _now().isoformat(),
                    "event": "cache_hit",
                    "task": task,
                    "provider": cached.get("provider"),
                    "model": cached.get("model"),
                    "free": cached.get("free"),
                    "complexity": complexity,
                    "cache_debug": cache_debug,
                    "input_tokens_est": 0,
                    "output_tokens_est": 0,
                    "estimated_cost_usd": 0.0,
                },
            )
            return LLMResult(provider=str(cached.get("provider") or "cache"), model=str(cached.get("model") or "cache"), content=str(cached["content"]), cached=True, complexity=complexity["label"], ledger_id=ledger_id)
    if privacy_mode == "local_only" and not allow_external:
        raise RuntimeError(
            "输入被隐私门识别为 local_only，已阻止外部模型调用。确认资料可上传后使用 --allow-external，或改用本地流程。"
        )
    _maybe_auto_discover_free_pool(settings)
    states = _load_route_state(settings)
    if task in ROLE_TASKS:
        if prefer_free:
            states = _maybe_refresh_when_free_pool_empty(settings, states, task)
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
        states = _maybe_refresh_when_free_pool_empty(settings, states, task)
        active_free = [choice for choice in _model_choices(settings, task=task, only_free=True) if _is_available(choice, states)]
        paid_pool = [] if not paid_fallback else [
            choice
            for choice in _paid_fallback_choices(settings, task, quality_target)
            if _is_available(choice, states)
        ]
        choices = active_free + paid_pool
    else:
        paid_pool = [
            choice
            for choice in _paid_fallback_choices(settings, task, quality_target)
            if _is_available(choice, states)
        ]
        free_pool = [choice for choice in _model_choices(settings, task=task, only_free=True) if _is_available(choice, states)]
        choices = paid_pool + free_pool
    if provider or model:
        filtered = _filter_choices(choices, provider=provider, model=model)
        if not filtered:
            raise RuntimeError(f"没有匹配 provider/model 过滤条件的可用模型：provider={provider or '-'} model={model or '-'}")
        choices = filtered
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
        budget = _budget_status(choice, input_tokens_est, max_cost_usd)
        if not budget["eligible"]:
            errors.append(f"{choice.provider.name}/{choice.model}: budget gate {budget['reason']}")
            continue
        try:
            content, usage = _call_openai_compatible(
                choice,
                messages=messages,
                timeout=settings.timeout,
                temperature=temperature,
                max_tokens=_max_output_tokens_for_budget(choice, input_tokens_est, max_cost_usd),
            )
            _record_success(settings, choice, states)
            output_tokens_est = int(usage.get("completion_tokens") or _estimate_tokens(content))
            input_tokens = int(usage.get("prompt_tokens") or input_tokens_est)
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
                    "latency_s": round(time.perf_counter() - started, 3),
                    "input_tokens_est": input_tokens,
                    "output_tokens_est": output_tokens_est,
                    "estimated_cost_usd": _estimated_cost_usd(choice, input_tokens, output_tokens_est),
                },
            )
            if _cache_enabled():
                cache = _load_response_cache(settings)
                cache[cache_key] = {
                    "created_at": _now().isoformat(),
                    "provider": choice.provider.name,
                    "model": choice.model,
                    "free": choice.provider.free,
                    "content": content,
                }
                _save_response_cache(settings, cache)
            return LLMResult(provider=choice.provider.name, model=choice.model, content=content, cached=False, complexity=complexity["label"], ledger_id=ledger_id)
        except Exception as exc:
            errors.append(f"{choice.provider.name}/{choice.model}: {exc}")
            _record_failure(settings, choice, states, exc)
            failure_class = classify_route_failure(str(exc))
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
                    "latency_s": round(time.perf_counter() - started, 3),
                    "input_tokens_est": input_tokens_est,
                    "output_tokens_est": 0,
                    "estimated_cost_usd": 0.0 if choice.provider.free else None,
                    "failure_class": failure_class,
                    "error": str(exc).replace("\n", " ")[:240],
                },
            )
    raise RuntimeError("所有模型调用失败：" + "\n".join(errors))


TRANSCRIPT_NOISE_PATTERNS = (
    "明镜需要您的支持",
    "中文字幕",
    "请不吝点赞",
    "订阅",
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
        if "金门" in line:
            line = line.replace("金门", "景门")
            notes.append("term_fix:金门->景门")
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
    domain: str = "fengshui",
    chunk_chars: int = 3500,
    free_only: bool = False,
    prefer_free: bool = True,
    cross_check: bool = False,
    quality_target: str = "production",
    max_context_chars: int | None = 7000,
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
        "修正以下中文易学课程 ASR 转写稿。要求：\n"
        "1. 保持老师原讲课顺序、判断链、案例过程和口语中的强调点。\n"
        "2. 只修正口误、同音错字、术语误识别、重复噪声和断句。\n"
        "3. 不要改成商业咨询文案，不要泛化成摘要。\n"
        "4. 不确定的术语用【待复核】标出。\n"
        f"5. 领域：{domain}。常见术语包括八卦、五行、天干地支、奇门八门、梅花体用、六爻用神等。\n"
        "6. 下面【待修正原文】就是原文；请直接输出修正后的正文，不要要求我再提供材料。"
    )
    check_prompt = (
        "审校这段已修正课程稿。重点检查术语是否改错、老师案例链是否遗漏、"
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
                paid_fallback=not free_only,
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
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with httpx.Client(timeout=30) as client:
        response = client.get("https://openrouter.ai/api/v1/models?output_modalities=text", headers=headers)
        response.raise_for_status()
        data = response.json()
    rows = []
    for model in data.get("data") or []:
        model_id = str(model.get("id") or "")
        if model_id.endswith(":free"):
            rows.append({"provider": "openrouter", "id": model_id, "name": model.get("name") or model_id, "context_length": int(model.get("context_length") or 0), "created": int(model.get("created") or 0), "free_signal": ":free suffix"})
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
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with httpx.Client(timeout=30) as client:
        response = client.get("https://openrouter.ai/api/v1/models", headers=headers)
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
                "free_signal": ":free suffix + vision/image metadata or model name",
            }
        )
    rows.sort(key=lambda row: (row["context_length"], row["created"]), reverse=True)
    return rows[:limit]


def discover_nvidia_models(limit: int = 50) -> list[dict[str, Any]]:
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少 NVIDIA_API_KEY")
    with httpx.Client(timeout=30) as client:
        response = client.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        data = response.json()
    return [{"provider": "nvidia", "id": model.get("id") or model.get("name") or "", "object": model.get("object") or "", "owned_by": model.get("owned_by") or "", "free_signal": "available in NVIDIA NIM account"} for model in (data.get("data") or [])[:limit]]


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
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少 NVIDIA_API_KEY")
    with httpx.Client(timeout=30) as client:
        response = client.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {key}"})
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
                "free_signal": "available in NVIDIA NIM account + vision-like metadata/name",
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
    return [{"provider": "groq", "id": model.get("id") or "", "owned_by": model.get("owned_by") or "", "active": model.get("active"), "context_window": model.get("context_window") or model.get("context_length") or "", "free_signal": "available in Groq account"} for model in (data.get("data") or [])[:limit]]


def discover_free_pool(settings: Settings, limit: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in {
        "openrouter": lambda: discover_openrouter_free(limit),
        "nvidia": lambda: discover_nvidia_models(limit),
        "openrouter_vision": lambda: discover_openrouter_vision_free(limit),
        "nvidia_vision": lambda: discover_nvidia_vision_models(limit),
        "groq": lambda: discover_groq_models(limit),
    }.items():
        try:
            out[name] = {"ok": True, "models": fn()}
        except Exception as exc:
            out[name] = {"ok": False, "error": str(exc).replace("\n", " ")[:240], "models": []}
    _record_discovered_free_models(
        settings,
        {name: value["models"] for name, value in out.items() if value.get("ok") and isinstance(value.get("models"), list)},
    )
    return out


def discover_vision_pool(settings: Settings, limit: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in {
        "openrouter_vision": lambda: discover_openrouter_vision_free(limit),
        "nvidia_vision": lambda: discover_nvidia_vision_models(limit),
    }.items():
        try:
            out[name] = {"ok": True, "models": fn()}
        except Exception as exc:
            out[name] = {"ok": False, "error": str(exc).replace("\n", " ")[:240], "models": []}
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

def quick_vision_benchmark(settings: Settings, image_path: str | Path, *, timeout: float = 12.0, limit: int = 8) -> dict[str, Any]:
    candidates = _rank_choices(configured_models(settings, only_free=True), "vision")[:limit]
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


def quick_benchmark(settings: Settings, *, timeout: float = 8.0, limit: int = 12) -> dict[str, Any]:
    tasks = {
        "smoke": "只输出 OK。",
        "classify": "只输出 JSON：给《麻衣神相 手相掌纹》分类，字段 domain, keywords, confidence。",
        "clean": "清洗 OCR：生命綫 深長，智惠线 分明，感凊線 上扬；不 可 执 一 而 断。",
    }
    candidates = _rank_choices(configured_models(settings, only_free=True), "qa")[:limit]
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
