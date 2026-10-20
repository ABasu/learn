from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

from stock_analysis.data.sources import Source, sources_for
from stock_analysis.domain import ReportRequest
from stock_analysis.model_providers import ModelProvider


SPECIALISTS = ("fundamentals", "technicals", "valuation", "catalysts", "risks")
ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT_VERSION = 1


@contextmanager
def _heartbeat(logger: logging.Logger, label: str, interval: float = 30.0):
    """Emit periodic progress while a blocking model call is active."""
    stopped = threading.Event()
    started = time.monotonic()

    def report() -> None:
        while not stopped.wait(interval):
            logger.info("Still working: %s | %.0fs elapsed", label, time.monotonic() - started)

    thread = threading.Thread(target=report, name=f"progress-{label}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text())


def load_checkpoint(path: Path, request: ReportRequest) -> dict:
    checkpoint_path = path / "checkpoint.json" if path.is_dir() else path
    data = json.loads(checkpoint_path.read_text())
    if data.get("version") != CHECKPOINT_VERSION:
        raise ValueError(f"unsupported checkpoint version in {checkpoint_path}")
    if data.get("request") != request.as_dict():
        raise ValueError(f"checkpoint request does not match this ticker/exchange: {checkpoint_path}")
    return data


def _save_checkpoint(
    path: Path | None,
    request: ReportRequest,
    specialists: dict,
    scenarios: dict,
    next_stage: str,
    *,
    status: str = "in_progress",
    error: str | None = None,
    final: dict | None = None,
) -> None:
    if path is None:
        return
    data = {
        "version": CHECKPOINT_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "next_stage": next_stage,
        "request": request.as_dict(),
        "specialists": specialists,
        "scenarios": scenarios,
        "final": final,
        "error": error,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    temporary.replace(path)


def calculate_weighted_score(component_scores: dict, scoring_path: Path | None = None) -> float:
    config = yaml.safe_load((scoring_path or ROOT / "config" / "scoring.yaml").read_text())
    weights = config["weights"]
    missing = set(weights) - set(component_scores)
    if missing:
        raise ValueError("final specialist_scores is missing: " + ", ".join(sorted(missing)))
    if abs(sum(float(weight) for weight in weights.values()) - 1.0) > 1e-9:
        raise ValueError("scoring weights must sum to 1.0")
    value = sum(float(component_scores[role]["score"]) * float(weight) for role, weight in weights.items())
    return round(max(-2.0, min(2.0, value)), 2)


def extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        # Structured-output transports can occasionally concatenate progress
        # and final messages or append a code fence. Decode complete objects
        # individually and keep the terminal one rather than treating the
        # entire combined string as a single JSON document.
        decoder = json.JSONDecoder()
        candidates = []
        for match in re.finditer(r"\{", text):
            try:
                candidate, _ = decoder.raw_decode(text, match.start())
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                candidates.append(candidate)
        if not candidates:
            raise ValueError("model response did not contain a complete JSON object")
        value = candidates[-1]
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


def validate_specialist(value: dict) -> None:
    required = {"score", "confidence", "findings", "evidence", "sources", "bull_scenario", "bear_scenario", "risks", "missing_data", "invalidation"}
    missing = required - value.keys()
    if missing:
        raise ValueError("specialist response is missing: " + ", ".join(sorted(missing)))
    if not -2 <= float(value["score"]) <= 2:
        raise ValueError("specialist score must be between -2 and +2")
    if value["confidence"] not in {"low", "medium", "high"}:
        raise ValueError("invalid specialist confidence")


def _prompt_context(request: ReportRequest, sources: list[Source], research: dict) -> str:
    exchange_prompt = ROOT / "prompts" / "exchanges" / request.country / f"{request.exchange}.md"
    common_prompt = ROOT / "prompts" / "exchanges" / request.country / "common.md"
    return "\n\n".join([
        "REPORT REQUEST\n" + json.dumps(request.as_dict(), indent=2),
        "MANDATORY SOURCE MANIFEST\n" + json.dumps([source.as_dict() for source in sources], indent=2),
        "EXCHANGE INSTRUCTIONS\n" + common_prompt.read_text() + "\n" + exchange_prompt.read_text(),
        "SCORING CONFIGURATION\n" + (ROOT / "config" / "scoring.yaml").read_text(),
        "RESEARCH PACKET\n" + json.dumps(research, indent=2),
        "Evidence discipline: use browsing when available; distinguish facts from inference; do not invent figures; list unavailable inputs in missing_data.",
    ])


def _specialist_prompt(role: str, context: str) -> str:
    contract = load_schema("analyst_response.schema.json")
    return "\n\n".join([
        (ROOT / "prompts" / "shared" / f"{role}.md").read_text(),
        context,
        "Return only one JSON object matching this exact schema:\n" + json.dumps(contract, indent=2),
    ])


def _adjudicator_prompt(role: str, context: str, specialist_outputs: dict) -> str:
    return "\n\n".join([
        (ROOT / "prompts" / "shared" / f"{role}.md").read_text(),
        context,
        "SPECIALIST OUTPUTS\n" + json.dumps(specialist_outputs, indent=2),
        "Return only one JSON object using the same specialist schema. Judge evidence rather than averaging scores mechanically.",
    ])


def _final_prompt(context: str, specialist_outputs: dict, scenarios: dict) -> str:
    return "\n\n".join([
        (ROOT / "prompts" / "shared" / "adjudicator.md").read_text(),
        context,
        "SPECIALIST OUTPUTS\n" + json.dumps(specialist_outputs, indent=2),
        "INDEPENDENT SCENARIO ADJUDICATIONS\n" + json.dumps(scenarios, indent=2),
        "Return only one JSON object matching the supplied final schema. Preserve evidence dates and direct source URLs.",
    ])


def run_analysis(
    provider: ModelProvider,
    request: ReportRequest,
    research: dict | None = None,
    logger: logging.Logger | None = None,
    checkpoint_path: Path | None = None,
    resume_state: dict | None = None,
) -> tuple[dict, dict]:
    logger = logger or logging.getLogger(__name__)
    run_started = time.monotonic()
    research = research or {}
    sources = sources_for(request)
    required_sources = sum(source.required for source in sources)
    logger.info("Research plan ready: %d sources (%d mandatory), research packet: %s", len(sources), required_sources, "supplied" if research else "not supplied")
    context = _prompt_context(request, sources, research)
    specialist_schema = load_schema("analyst_response.schema.json")
    specialists: dict[str, dict] = dict((resume_state or {}).get("specialists", {}))
    scenarios: dict[str, dict] = dict((resume_state or {}).get("scenarios", {}))
    total_agents = len(SPECIALISTS) + 3
    completed_agents = len(specialists) + len(scenarios)
    if resume_state:
        logger.info("Resuming checkpoint: %d specialists and %d scenario adjudicators already complete", len(specialists), len(scenarios))
    _save_checkpoint(checkpoint_path, request, specialists, scenarios, "specialist:fundamentals")
    for role in SPECIALISTS:
        if role in specialists:
            logger.info("[%d/%d] Reusing completed specialist: %s", SPECIALISTS.index(role) + 1, total_agents, role)
            continue
        started = time.monotonic()
        logger.info("[%d/%d] Starting specialist: %s", completed_agents + 1, total_agents, role)
        try:
            with _heartbeat(logger, f"specialist {role}"):
                raw = provider.complete(_specialist_prompt(role, context), specialist_schema)
            logger.debug("Specialist %s returned %d characters", role, len(raw))
            response = extract_json_object(raw)
        except Exception as exc:
            _save_checkpoint(checkpoint_path, request, specialists, scenarios, f"specialist:{role}", status="paused", error=str(exc))
            logger.error("[%d/%d] Specialist %s failed after %.1fs: %s", completed_agents + 1, total_agents, role, time.monotonic() - started, exc)
            raise
        validate_specialist(response)
        specialists[role] = response
        completed_agents += 1
        logger.info(
            "[%d/%d] Completed specialist: %s | score %+.2f | %s confidence | %.1fs",
            completed_agents, total_agents, role, float(response["score"]), response["confidence"], time.monotonic() - started,
        )
        remaining = [candidate for candidate in SPECIALISTS if candidate not in specialists]
        next_stage = f"specialist:{remaining[0]}" if remaining else "adjudicator:bull"
        _save_checkpoint(checkpoint_path, request, specialists, scenarios, next_stage)

    for role in ("bull_adjudicator", "bear_adjudicator"):
        started = time.monotonic()
        label = role.removesuffix("_adjudicator")
        if label in scenarios:
            logger.info("[%d/%d] Reusing completed %s adjudicator", completed_agents, total_agents, label)
            continue
        logger.info("[%d/%d] Starting %s adjudicator", completed_agents + 1, total_agents, label)
        try:
            with _heartbeat(logger, f"{label} adjudicator"):
                raw = provider.complete(_adjudicator_prompt(role, context, specialists), specialist_schema)
            logger.debug("%s adjudicator returned %d characters", label.title(), len(raw))
            response = extract_json_object(raw)
        except Exception as exc:
            _save_checkpoint(checkpoint_path, request, specialists, scenarios, f"adjudicator:{label}", status="paused", error=str(exc))
            logger.error("[%d/%d] %s adjudicator failed after %.1fs: %s", completed_agents + 1, total_agents, label, time.monotonic() - started, exc)
            raise
        validate_specialist(response)
        scenarios[label] = response
        completed_agents += 1
        logger.info(
            "[%d/%d] Completed %s adjudicator | score %+.2f | %s confidence | %.1fs",
            completed_agents, total_agents, label, float(response["score"]), response["confidence"], time.monotonic() - started,
        )
        next_stage = "adjudicator:bear" if label == "bull" else "adjudicator:final"
        _save_checkpoint(checkpoint_path, request, specialists, scenarios, next_stage)

    final_schema = load_schema("adjudication.schema.json")
    started = time.monotonic()
    logger.info("[%d/%d] Starting final adjudicator", completed_agents + 1, total_agents)
    try:
        with _heartbeat(logger, "final adjudicator"):
            raw = provider.complete(_final_prompt(context, specialists, scenarios), final_schema)
        logger.debug("Final adjudicator returned %d characters", len(raw))
        final = extract_json_object(raw)
    except Exception as exc:
        _save_checkpoint(checkpoint_path, request, specialists, scenarios, "adjudicator:final", status="paused", error=str(exc))
        logger.error("[%d/%d] Final adjudicator failed after %.1fs: %s", completed_agents + 1, total_agents, time.monotonic() - started, exc)
        raise
    model_weighted_score = max(-2, min(2, float(final["weighted_score"])))
    calculated_score = calculate_weighted_score(final["specialist_scores"])
    if abs(model_weighted_score - calculated_score) > 0.01:
        logger.warning(
            "Final adjudicator supplied weighted score %+.2f; configured component weights produce %+.2f. Using configured result.",
            model_weighted_score, calculated_score,
        )
    final["weighted_score"] = calculated_score
    completed_agents += 1
    logger.info(
        "[%d/%d] Completed final adjudicator | score %+.2f | %s | %s confidence | %.1fs",
        completed_agents, total_agents, final["weighted_score"], final["stance"], final["confidence"], time.monotonic() - started,
    )
    final["ticker"] = request.ticker
    final["exchange"] = request.exchange.upper()
    final["country"] = request.country
    final["analysis_date"] = request.as_of
    final["technical_horizon"] = request.technical_horizon
    final["fundamental_horizon"] = request.fundamental_horizon
    final["risk_profile"] = request.risk
    final["source_manifest"] = [source.as_dict() for source in sources]
    # Final adjudication can revise component scores after reconciling evidence;
    # its schema-bound scorecard is canonical for display and future backtests.
    final["score_scale"] = "-2_to_+2"
    audit = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request": request.as_dict(),
        "sources": [source.as_dict() for source in sources],
        "specialists": specialists,
        "scenarios": scenarios,
        "final": final,
    }
    _save_checkpoint(checkpoint_path, request, specialists, scenarios, "complete", status="complete", final=final)
    logger.info("Analysis complete in %.1fs", time.monotonic() - run_started)
    return final, audit

