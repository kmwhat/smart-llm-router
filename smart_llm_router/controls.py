from __future__ import annotations

import difflib
import math
import os
import re
from dataclasses import dataclass
from typing import Mapping


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class ControlSpec:
    name: str
    value_type: str


@dataclass(frozen=True)
class ControlPreflight:
    strict_controls: bool
    requested_cache_enabled: bool
    effective_cache_enabled: bool
    cache_control_source: str
    checked_control_count: int

    def evidence(self) -> dict[str, object]:
        return {
            "schema": "smart_llm_router.control_preflight.v1",
            "strict_controls": self.strict_controls,
            "requested_cache_enabled": self.requested_cache_enabled,
            "effective_cache_enabled": self.effective_cache_enabled,
            "cache_control_source": self.cache_control_source,
            "checked_control_count": self.checked_control_count,
            "validation_status": "pass" if self.strict_controls else "not-requested",
        }


class UnsupportedControlError(ValueError):
    """A sanitized governed-control preflight failure."""


_STATIC_SPECS = (
    ControlSpec("SMART_LLM_ASR_MLX_MODEL", "string"),
    ControlSpec("SMART_LLM_ASR_OPENAI_WHISPER_MODEL", "string"),
    ControlSpec("SMART_LLM_ASR_WHISPER_CPP_MODEL", "string"),
    ControlSpec("SMART_LLM_ASR_WHISPER_CPP_NO_GPU", "boolean"),
    ControlSpec("SMART_LLM_AUTO_DISCOVER_FREE", "boolean"),
    ControlSpec("SMART_LLM_CACHE", "boolean"),
    ControlSpec("SMART_LLM_CACHE_MAX_ITEMS", "positive-integer"),
    ControlSpec("SMART_LLM_CNY_PER_USD", "nonnegative-number"),
    ControlSpec("SMART_LLM_CREDENTIAL_CATALOG", "path"),
    ControlSpec("SMART_LLM_CREDENTIAL_CATALOG_FALLBACKS", "path-list"),
    ControlSpec("SMART_LLM_DATA_DIR", "path"),
    ControlSpec("SMART_LLM_DISCOVERY_LIMIT", "positive-integer"),
    ControlSpec("SMART_LLM_DISCOVERY_TTL_HOURS", "nonnegative-number"),
    ControlSpec("SMART_LLM_DOUBAO_FRONTIER_MODELS", "csv"),
    ControlSpec("SMART_LLM_EMPTY_POOL_REFRESH_LIMIT", "positive-integer"),
    ControlSpec("SMART_LLM_EMPTY_POOL_REFRESH_TIMEOUT", "positive-number"),
    ControlSpec("SMART_LLM_ENV_FILE", "path"),
    ControlSpec("SMART_LLM_GEMINI_PAID_ENABLED", "boolean"),
    ControlSpec("SMART_LLM_HEALTH_TTL_HOURS", "nonnegative-number"),
    ControlSpec("SMART_LLM_OLLAMA_REASONING_EFFORT", "string"),
    ControlSpec("SMART_LLM_PYTHON", "path"),
    ControlSpec("SMART_LLM_RUNTIME_DIR", "path"),
    ControlSpec("SMART_LLM_RUNTIME_DIR_SOURCE", "string"),
    ControlSpec("SMART_LLM_RUNTIME_EXPECTED_DIR", "path"),
    ControlSpec("SMART_LLM_RUNTIME_FALLBACK_REASON", "string"),
    ControlSpec("SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED", "boolean"),
    ControlSpec("SMART_LLM_TIMEOUT", "positive-number"),
    ControlSpec("SMART_LLM_VISION_JPEG_QUALITY", "positive-integer"),
    ControlSpec("SMART_LLM_VISION_MAX_SIDE", "positive-integer"),
)

CONTROL_SPECS = {spec.name: spec for spec in _STATIC_SPECS}

_PROVIDER_PATTERN = re.compile(
    r"^SMART_LLM(?:[1-9]|1[0-9]|2[0-4])_"
    r"(?:NAME|BASE_URL|API_KEY_ENV|MODELS|FREE|PRIORITY|BILLING_CLASS|TRIAL_QUOTA_GUARDED)$"
)
_PRICE_PATTERN = re.compile(r"^SMART_LLM_PRICE_[A-Z0-9_]+_(?:INPUT|OUTPUT)$")
_TASK_ORDER_PATTERN = re.compile(r"^SMART_LLM_TASK_ORDER_[A-Z0-9_]+$")


def _dynamic_value_type(name: str) -> str | None:
    if _PROVIDER_PATTERN.fullmatch(name):
        if name.endswith(("_FREE", "_TRIAL_QUOTA_GUARDED")):
            return "boolean"
        if name.endswith("_PRIORITY"):
            return "integer"
        if name.endswith("_MODELS"):
            return "csv"
        return "string"
    if _PRICE_PATTERN.fullmatch(name):
        return "nonnegative-number"
    if _TASK_ORDER_PATTERN.fullmatch(name):
        return "csv"
    return None


def is_supported_control_name(name: str) -> bool:
    return name in CONTROL_SPECS or _dynamic_value_type(name) is not None


def _parse_boolean(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise UnsupportedControlError(
        f"governed_control_invalid_value:{name}:expected_boolean"
    )


def _validate_typed_value(name: str, value: str, value_type: str) -> None:
    if value_type in {"string", "path", "path-list", "csv"}:
        return
    if value_type == "boolean":
        _parse_boolean(name, value)
        return
    try:
        number = float(value) if "number" in value_type else int(value)
    except (TypeError, ValueError):
        raise UnsupportedControlError(
            f"governed_control_invalid_value:{name}:expected_{value_type}"
        ) from None
    if "number" in value_type and not math.isfinite(number):
        raise UnsupportedControlError(
            f"governed_control_invalid_value:{name}:expected_{value_type}"
        )
    if value_type.startswith("positive") and number <= 0:
        raise UnsupportedControlError(
            f"governed_control_invalid_value:{name}:expected_{value_type}"
        )
    if value_type.startswith("nonnegative") and number < 0:
        raise UnsupportedControlError(
            f"governed_control_invalid_value:{name}:expected_{value_type}"
        )


def validate_governed_controls(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    source = os.environ if environ is None else environ
    names = sorted(name for name in source if name.startswith("SMART_LLM"))
    unsupported = [name for name in names if not is_supported_control_name(name)]
    if unsupported:
        bad = unsupported[0]
        suggestions = difflib.get_close_matches(bad, CONTROL_SPECS, n=1, cutoff=0.6)
        hint = f":did_you_mean={suggestions[0]}" if suggestions else ""
        raise UnsupportedControlError(
            f"governed_control_unsupported:{bad}{hint}:blocked_before_send"
        )
    for name in names:
        spec = CONTROL_SPECS.get(name)
        value_type = spec.value_type if spec else _dynamic_value_type(name)
        assert value_type is not None
        _validate_typed_value(name, source[name], value_type)
    return tuple(names)


def build_control_preflight(
    *,
    strict_controls: bool,
    explicit_cache_enabled: bool | None = None,
    environ: Mapping[str, str] | None = None,
) -> ControlPreflight:
    source = os.environ if environ is None else environ
    checked = validate_governed_controls(source) if strict_controls else ()
    if explicit_cache_enabled is not None:
        requested = bool(explicit_cache_enabled)
        effective = requested
        control_source = "argument:no-cache" if not requested else "argument:cache-enabled"
    elif "SMART_LLM_CACHE" in source:
        if strict_controls:
            requested = _parse_boolean("SMART_LLM_CACHE", source["SMART_LLM_CACHE"])
        else:
            requested = source["SMART_LLM_CACHE"].strip().lower() not in _FALSE_VALUES
        effective = requested
        control_source = "environment:SMART_LLM_CACHE"
    else:
        requested = True
        effective = True
        control_source = "default:enabled"
    return ControlPreflight(
        strict_controls=strict_controls,
        requested_cache_enabled=requested,
        effective_cache_enabled=effective,
        cache_control_source=control_source,
        checked_control_count=len(checked),
    )
