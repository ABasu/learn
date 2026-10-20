from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


SUPPORTED_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelDefaults:
    model: str
    reasoning_effort: str
    available_models: tuple[str, ...]
    provider_defaults: dict[str, str]
    provider_models: dict[str, tuple[str, ...]]

    def model_for(self, provider: str) -> str:
        return self.provider_defaults.get(provider, self.model)

    def models_for(self, provider: str) -> tuple[str, ...]:
        return self.provider_models.get(provider, self.available_models)


def load_model_defaults(path: Path) -> ModelDefaults:
    data = yaml.safe_load(path.read_text()) or {}
    defaults = data.get("defaults", {})
    model = str(defaults.get("model", "")).strip()
    effort = str(defaults.get("reasoning_effort", "")).strip().lower()
    available_models = tuple(str(value).strip() for value in data.get("available_models", []) if str(value).strip())
    raw_provider_defaults = data.get("provider_defaults", {}) or {}
    provider_defaults = {str(key): str(value).strip() for key, value in raw_provider_defaults.items() if str(value).strip()}
    raw_provider_models = data.get("provider_models", {}) or {}
    provider_models = {
        str(provider): tuple(str(value).strip() for value in values if str(value).strip())
        for provider, values in raw_provider_models.items()
    }
    if not model:
        raise ValueError(f"model is missing from {path}")
    if effort not in SUPPORTED_REASONING_EFFORTS:
        allowed = ", ".join(SUPPORTED_REASONING_EFFORTS)
        raise ValueError(f"reasoning_effort in {path} must be one of: {allowed}")
    if not available_models:
        available_models = (model,)
    if model not in available_models:
        raise ValueError(f"default model {model!r} is not listed in available_models in {path}")
    provider_defaults.setdefault("chatgpt", model)
    provider_models.setdefault("chatgpt", available_models)
    for provider, default in provider_defaults.items():
        choices = provider_models.get(provider, ())
        if choices and default not in choices:
            raise ValueError(f"default model {default!r} for {provider} is not listed in provider_models.{provider} in {path}")
    return ModelDefaults(
        model=model,
        reasoning_effort=effort,
        available_models=available_models,
        provider_defaults=provider_defaults,
        provider_models=provider_models,
    )
