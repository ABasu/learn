from __future__ import annotations

from datetime import datetime
from typing import Any


def five_hour_usage(snapshot: dict[str, Any] | None, model: str | None = None) -> dict[str, Any] | None:
    """Select the model-relevant five-hour window from an app-server snapshot."""
    if not snapshot:
        return None
    buckets = snapshot.get("rateLimitsByLimitId") or {}
    candidates: list[tuple[str | None, dict]] = list(buckets.items())
    if not candidates and snapshot.get("rateLimits"):
        candidates = [(snapshot["rateLimits"].get("limitId"), snapshot["rateLimits"])]

    def find(require_model_match: bool) -> dict[str, Any] | None:
        for limit_id, bucket in candidates:
            if require_model_match and model and bucket.get("normalModelSlug") != model:
                continue
            for window_name in ("primary", "secondary"):
                window = bucket.get(window_name)
                if window and window.get("windowDurationMins") == 300:
                    used = int(window["usedPercent"])
                    return {
                        "limit_id": limit_id,
                        "limit_name": bucket.get("limitName"),
                        "model": bucket.get("normalModelSlug"),
                        "window": window_name,
                        "window_minutes": 300,
                        "used_percent": used,
                        "remaining_percent": max(0, 100 - used),
                        "resets_at": window.get("resetsAt"),
                        "ordinary_usage_allowed": snapshot.get("ordinaryUsageAllowed"),
                    }
        return None

    return find(True) or find(False)


def format_usage(label: str, usage: dict[str, Any] | None, previous: dict[str, Any] | None = None) -> str:
    if not usage:
        return f"ChatGPT 5-hour usage {label}: unavailable"
    reset = "unknown"
    if usage.get("resets_at"):
        reset = datetime.fromtimestamp(usage["resets_at"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    message = (
        f"ChatGPT 5-hour usage {label}: {usage['used_percent']}% used, "
        f"{usage['remaining_percent']}% remaining; resets {reset}"
    )
    if previous and previous.get("used_percent") is not None:
        delta = usage["used_percent"] - previous["used_percent"]
        message += f"; report change {delta:+d} percentage point{'s' if abs(delta) != 1 else ''}"
    return message
