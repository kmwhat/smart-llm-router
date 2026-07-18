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


def _heading(line: str) -> str | None:
    for provider, pattern in HEADING_PATTERNS:
        if pattern.search(line):
            return provider
    return None


def _looks_like_secret(line: str) -> bool:
    if not line or len(line) < 20 or any(char.isspace() for char in line):
        return False
    if line.startswith("projects/") or line.startswith("ep-"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.:/+\-=]+", line))


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
    values: dict[str, list[str]] = {name: [] for name in PROVIDER_ENV}
    endpoint_ids: list[str] = []
    for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if NON_MODEL_SECTION.search(line):
            current = None
            continue
        heading = _heading(line)
        if heading and not _looks_like_secret(line):
            current = heading
            continue
        endpoint = re.search(r"\bep-[A-Za-z0-9-]+\b", line)
        if current == "doubao" and endpoint:
            endpoint_ids.append(endpoint.group(0))
            continue
        if current and _looks_like_secret(line):
            values[current].append(line)

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
    return CredentialCatalogSummary(
        path=str(source),
        providers=configured,
        key_counts=counts,
        endpoint_ids=tuple(endpoint_ids),
    )
