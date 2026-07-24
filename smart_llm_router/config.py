from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .credential_catalog import CredentialCatalogSummary, load_model_credential_catalog


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...]
    free: bool
    priority: int
    billing_class: str = ""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    providers: tuple[LLMProvider, ...]
    timeout: float
    empty_pool_refresh_timeout: float
    empty_pool_refresh_limit: int
    auto_discover_free: bool = False
    discovery_ttl_hours: float = 6.0
    discovery_limit: int = 20
    credential_catalog: CredentialCatalogSummary | None = None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "")
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _billing_class(name: str, free: bool, explicit: str = "") -> str:
    value = explicit.strip().lower()
    if value:
        if value not in {"local", "permanent_free", "trial_quota", "paid"}:
            raise ValueError(f"不支持的 BILLING_CLASS：{value}")
        return value
    if not free:
        return "paid"
    if name.lower().startswith(("qwen-free", "nvidia-free", "nvidia-google-free", "nvidia-vision-free", "groq")):
        return "trial_quota"
    return "permanent_free"


def _read_provider(prefix: str, index: int) -> LLMProvider | None:
    name = os.getenv(prefix + "NAME", "").strip()
    base_url = os.getenv(prefix + "BASE_URL", "").strip().rstrip("/")
    api_key_env = os.getenv(prefix + "API_KEY_ENV", "").strip()
    models = _csv_env(prefix + "MODELS")
    if not any((name, base_url, api_key_env, models)):
        return None
    if not name or not base_url or not api_key_env or not models:
        raise ValueError(f"{prefix} 配置不完整：需要 NAME、BASE_URL、API_KEY_ENV、MODELS")
    raw_priority = os.getenv(prefix + "PRIORITY", str(index)).strip()
    return LLMProvider(
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        models=models,
        free=_bool_env(prefix + "FREE", True),
        priority=int(raw_priority) if raw_priority else index,
        billing_class=_billing_class(
            name,
            _bool_env(prefix + "FREE", True),
            os.getenv(prefix + "BILLING_CLASS", ""),
        ),
    )


def _is_gemini_provider(provider: LLMProvider) -> bool:
    return provider.name.lower().startswith("gemini") or "generativelanguage.googleapis.com" in provider.base_url.lower()


def _load_providers() -> tuple[LLMProvider, ...]:
    providers: list[LLMProvider] = []
    for index in range(1, 25):
        provider = _read_provider(f"SMART_LLM{index}_", index)
        if provider:
            providers.append(provider)
    gemini_paid_enabled = _bool_env("SMART_LLM_GEMINI_PAID_ENABLED", False)
    if not gemini_paid_enabled:
        providers = [provider for provider in providers if not (_is_gemini_provider(provider) and not provider.free)]
    configured_names = {provider.name for provider in providers}
    doubao_frontier_models = _csv_env("SMART_LLM_DOUBAO_FRONTIER_MODELS") or (
        "doubao-seed-2-1-pro",
        "doubao-seed-2-1-turbo",
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-code-preview-260215",
    )
    gemini_provider = (
        LLMProvider(
            "gemini-frontier-paid",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
            ("gemini-2.5-pro", "gemini-3.1-pro-preview"),
            False,
            8,
            "paid",
        )
        if gemini_paid_enabled
        else LLMProvider(
            "gemini-free",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
            ("gemini-2.5-pro", "gemini-2.5-flash-lite"),
            True,
            2,
            "trial_quota",
        )
    )
    automatic = (
        LLMProvider("deepseek-direct-paid", "https://api.deepseek.com", "DEEPSEEK_API_KEY", ("deepseek-v4-flash", "deepseek-v4-pro"), False, 7, "paid"),
        LLMProvider("qwen-frontier-paid", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY", ("qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash"), False, 7, "paid"),
        LLMProvider("kimi-frontier-paid", "https://api.moonshot.cn/v1", "KIMI_API_KEY", ("kimi-k3", "kimi-k2.6"), False, 7, "paid"),
        LLMProvider("doubao-frontier-paid", "https://ark.cn-beijing.volces.com/api/v3", "ARK_API_KEY", doubao_frontier_models, False, 7, "trial_quota"),
        gemini_provider,
        LLMProvider("zhipu-vision-paid", "https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY", ("glm-4.6v", "glm-4v-flash"), False, 8),
        LLMProvider("zhipu-asr-paid", "https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY", ("glm-asr-2512",), False, 8),
        LLMProvider("zhipu-image-paid", "https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY", ("glm-image",), False, 9),
        LLMProvider("qwen-asr-paid", "https://dashscope.aliyuncs.com/api/v1", "DASHSCOPE_API_KEY", ("qwen3-asr-flash",), False, 8),
        LLMProvider("qwen-rerank-paid", "https://dashscope.aliyuncs.com/api/v1", "DASHSCOPE_API_KEY", ("qwen3-rerank",), False, 8),
        LLMProvider("qwen-mm-embedding-paid", "https://dashscope.aliyuncs.com/api/v1", "DASHSCOPE_API_KEY", ("qwen3-vl-embedding",), False, 9),
    )
    endpoint_id = os.getenv("ARK_ENDPOINT_ID", "").strip()
    if endpoint_id:
        automatic += (
            LLMProvider("doubao-ark-paid", "https://ark.cn-beijing.volces.com/api/v3", "ARK_API_KEY", (endpoint_id,), False, 8),
        )
    configured_model_routes = {
        (provider.base_url.rstrip("/"), provider.api_key_env, model)
        for provider in providers
        for model in provider.models
    }
    for provider in automatic:
        missing_models = tuple(
            model
            for model in provider.models
            if (provider.base_url.rstrip("/"), provider.api_key_env, model) not in configured_model_routes
        )
        if provider.name not in configured_names and missing_models and os.getenv(provider.api_key_env, "").strip():
            providers.append(
                LLMProvider(
                    provider.name,
                    provider.base_url,
                    provider.api_key_env,
                    missing_models,
                    provider.free,
                    provider.priority,
                    provider.billing_class,
                )
            )
    # Multiple valid keys from the same vendor become independent routes. This
    # improves availability without leaking or persisting the credential values.
    clones: list[LLMProvider] = []
    for provider in providers:
        for index in range(2, 6):
            env_name = f"{provider.api_key_env}_{index}"
            if os.getenv(env_name, "").strip():
                clones.append(
                    LLMProvider(
                        f"{provider.name}-key{index}",
                        provider.base_url,
                        env_name,
                        provider.models,
                        provider.free,
                        provider.priority + index - 1,
                        provider.billing_class,
                    )
                )
    providers.extend(clones)
    return tuple(sorted(providers, key=lambda provider: provider.priority))


def load_settings(env_file: str | None = None, credential_catalog: str | None = None) -> Settings:
    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)
    catalog_summary = None
    catalog_path = credential_catalog or os.getenv("SMART_LLM_CREDENTIAL_CATALOG", "").strip()
    if catalog_path:
        catalog_summary = load_model_credential_catalog(catalog_path, override=True)
    default_dir = Path.home() / ".smart-llm-router"
    # Runtime placement is a governance concern, not a secret. Let the global
    # launcher override legacy env-file locations without changing key loading.
    data_dir = Path(
        os.getenv("SMART_LLM_RUNTIME_DIR")
        or os.getenv("SMART_LLM_DATA_DIR")
        or str(default_dir)
    ).expanduser()
    timeout = float(os.getenv("SMART_LLM_TIMEOUT") or "45")
    refresh_timeout = float(os.getenv("SMART_LLM_EMPTY_POOL_REFRESH_TIMEOUT", "5") or "5")
    refresh_limit = int(os.getenv("SMART_LLM_EMPTY_POOL_REFRESH_LIMIT", "8") or "8")
    discovery_ttl_hours = float(os.getenv("SMART_LLM_DISCOVERY_TTL_HOURS", "6") or "6")
    discovery_limit = int(os.getenv("SMART_LLM_DISCOVERY_LIMIT", "20") or "20")
    return Settings(
        data_dir=data_dir,
        providers=_load_providers(),
        timeout=timeout,
        empty_pool_refresh_timeout=refresh_timeout,
        empty_pool_refresh_limit=refresh_limit,
        auto_discover_free=_bool_env("SMART_LLM_AUTO_DISCOVER_FREE", True),
        discovery_ttl_hours=max(0.0, discovery_ttl_hours),
        discovery_limit=max(1, discovery_limit),
        credential_catalog=catalog_summary,
    )
