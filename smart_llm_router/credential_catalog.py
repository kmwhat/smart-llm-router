from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PROVIDER_ENV = {
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "doubao": "ARK_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "kimi": "KIMI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}

# Provider-specific prefixes and shapes prevent nearby labels, account ids,
# and model names from becoming credential rotation routes. Providers without
# a stable shape keep the conservative generic parser for compatibility.
PROVIDER_SECRET_PATTERNS = {
    "qwen": re.compile(r"sk-[A-Za-z0-9_.-]{16,}"),
    "openrouter": re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,}"),
    "nvidia": re.compile(r"nvapi-[A-Za-z0-9_-]{20,}"),
    "groq": re.compile(r"gsk_[A-Za-z0-9_-]{20,}"),
    "minimax": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
}

HEADING_PATTERNS = (
    ("deepseek", re.compile(r"deepseek", re.I)),
    ("qwen", re.compile(r"qwen|通义千问", re.I)),
    ("doubao", re.compile(r"doubao|豆包|火山方舟", re.I)),
    ("zhipu", re.compile(r"zhipu|智谱|\bglm\b", re.I)),
    ("gemini", re.compile(r"gemini", re.I)),
    ("kimi", re.compile(r"kimi|moonshot|月之暗面", re.I)),
    ("openrouter", re.compile(r"openrouter", re.I)),
    ("nvidia", re.compile(r"nvidia", re.I)),
    ("groq", re.compile(r"groq", re.I)),
    ("minimax", re.compile(r"mini\s*max|minimax|稀宇", re.I)),
)

CATALOG_SECTION_PATTERNS = (
    ("paid_unfunded", re.compile(r"(?:付费.*未充值|未充值.*付费|paid.*unfunded|unfunded.*paid)", re.I)),
    ("free", re.compile(r"(?:免费模型|free\s+models?)", re.I)),
    ("paid", re.compile(r"(?:付费模型|paid\s+models?)", re.I)),
)

NON_MODEL_SECTION = re.compile(
    r"(?:^|\b)(?:x(?:的)?\s*api|twitter|oauth|consumer\s+key|access\s+token|refresh\s+token|client\s+(?:id|secret)|app-only\s+authentication)",
    re.I,
)


@dataclass(frozen=True)
class CredentialCatalogSummary:
    path: str
    providers: tuple[str, ...]
    key_counts: tuple[tuple[str, int], ...]
    endpoint_ids: tuple[str, ...]
    sectioned: bool = False
    billing_key_counts: tuple[tuple[str, str, int], ...] = ()
    skipped_key_counts: tuple[tuple[str, str, int], ...] = ()


def _heading(line: str) -> str | None:
    for provider, pattern in HEADING_PATTERNS:
        if pattern.search(line):
            return provider
    return None


def _catalog_section(line: str) -> str | None:
    for section, pattern in CATALOG_SECTION_PATTERNS:
        if pattern.search(line):
            return section
    return None


def _looks_like_secret(line: str) -> bool:
    if not line or len(line) < 20 or any(char.isspace() for char in line):
        return False
    if line.startswith("projects/") or line.startswith("ep-"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.:/+\-=]+", line))


def _looks_like_provider_secret(provider: str, line: str) -> bool:
    if not _looks_like_secret(line):
        return False
    pattern = PROVIDER_SECRET_PATTERNS.get(provider)
    return pattern.fullmatch(line) is not None if pattern else True


def load_model_credential_catalog(path: str | Path, *, override: bool = True) -> CredentialCatalogSummary:
    """Load only model-provider credentials from the user's free-form catalog.

    The source file may also contain social/API credentials. Those sections are
    deliberately ignored. Values are placed in process memory only and are
    never returned in the summary.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"credential catalog not found: {source}")

    current: str | None = None
    current_section = "legacy"
    sectioned = False
    values: dict[str, list[str]] = {name: [] for name in PROVIDER_ENV}
    values_by_section: dict[str, dict[str, list[str]]] = {
        section: {name: [] for name in PROVIDER_ENV}
        for section in ("legacy", "free", "paid", "paid_unfunded")
    }
    endpoint_ids_by_section: dict[str, list[str]] = {
        section: [] for section in ("legacy", "free", "paid", "paid_unfunded")
    }
    for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if NON_MODEL_SECTION.search(line):
            current = None
            continue
        section = _catalog_section(line)
        if section:
            current_section = section
            sectioned = True
            current = None
            continue
        heading = _heading(line)
        if heading and not _looks_like_secret(line):
            current = heading
            continue
        endpoint = re.search(r"\bep-[A-Za-z0-9-]+\b", line)
        if current == "doubao" and endpoint:
            endpoint_id = endpoint.group(0)
            if endpoint_id not in endpoint_ids_by_section[current_section]:
                endpoint_ids_by_section[current_section].append(endpoint_id)
            continue
        if current and _looks_like_provider_secret(current, line):
            section_values = values_by_section[current_section][current]
            if line not in section_values:
                section_values.append(line)

    admitted_sections = ("free", "paid") if sectioned else ("legacy",)
    existing_values: dict[str, list[str]] = {}
    for provider, env_name in PROVIDER_ENV.items():
        existing_values[provider] = []
        for index in range(1, 21):
            value = os.getenv(env_name if index == 1 else f"{env_name}_{index}", "").strip()
            if value and value not in existing_values[provider]:
                existing_values[provider].append(value)
    endpoint_ids: list[str] = []
    for section in admitted_sections:
        for endpoint_id in endpoint_ids_by_section[section]:
            if endpoint_id not in endpoint_ids:
                endpoint_ids.append(endpoint_id)
    for provider in PROVIDER_ENV:
        for section in admitted_sections:
            for value in values_by_section[section][provider]:
                if value not in values[provider]:
                    values[provider].append(value)

    if sectioned:
        # A section heading is a billing declaration, not proof that every
        # nearby token is a live credential. Preserve rotations already
        # validated into the private environment when they remain in the
        # active sections; otherwise admit only the first candidate.
        for provider, candidates in values.items():
            retained = [value for value in existing_values[provider] if value in candidates]
            values[provider] = retained or candidates[:1]

    # A sectioned catalog is authoritative for providers that it names. Clear
    # stale or explicitly unfunded slots before admitting active credentials;
    # legacy unsectioned catalogs retain the historical additive behaviour.
    if sectioned and override:
        catalog_providers = {
            provider
            for section_values in values_by_section.values()
            for provider, candidates in section_values.items()
            if candidates
        }
        for provider in catalog_providers:
            env_name = PROVIDER_ENV[provider]
            for index in range(1, 21):
                os.environ.pop(env_name if index == 1 else f"{env_name}_{index}", None)
        if "doubao" in catalog_providers:
            os.environ.pop("ARK_ENDPOINT_ID", None)

    for provider, env_name in PROVIDER_ENV.items():
        candidates = values[provider]
        if not candidates:
            continue
        existing = os.getenv(env_name, "").strip()
        primary = existing if existing in candidates else candidates[0]
        if override or not existing:
            os.environ[env_name] = primary
        extras = [value for value in candidates if value != primary]
        for index, value in enumerate(extras, 2):
            extra_name = f"{env_name}_{index}"
            if override or not os.getenv(extra_name):
                os.environ[extra_name] = value

    if endpoint_ids and (override or not os.getenv("ARK_ENDPOINT_ID")):
        os.environ["ARK_ENDPOINT_ID"] = endpoint_ids[0]

    configured = tuple(name for name, candidates in values.items() if candidates)
    counts = tuple((name, len(values[name])) for name in configured)
    billing_counts = tuple(
        (section, provider, len(values_by_section[section][provider]))
        for section in ("free", "paid")
        for provider in PROVIDER_ENV
        if values_by_section[section][provider]
    )
    skipped_counts = tuple(
        ("paid_unfunded", provider, len(values_by_section["paid_unfunded"][provider]))
        for provider in PROVIDER_ENV
        if values_by_section["paid_unfunded"][provider]
    )
    return CredentialCatalogSummary(
        path=str(source),
        providers=configured,
        key_counts=counts,
        endpoint_ids=tuple(endpoint_ids),
        sectioned=sectioned,
        billing_key_counts=billing_counts,
        skipped_key_counts=skipped_counts,
    )
