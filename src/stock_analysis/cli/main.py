from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from stock_analysis import __version__
from stock_analysis.config import SUPPORTED_REASONING_EFFORTS, load_model_defaults
from stock_analysis.data.sources import sources_for
from stock_analysis.domain import ReportRequest
from stock_analysis.model_providers import (
    AnthropicAPIProvider,
    AntigravityCLIProvider,
    ClaudeCLIProvider,
    CodexAppServerProvider,
    DryRunProvider,
    GeminiAPIProvider,
    GeminiCLIProvider,
    OpenAIAPIProvider,
    ProviderError,
    ProviderTurnError,
    find_codex,
)
from stock_analysis.orchestration.runner import load_checkpoint, run_analysis
from stock_analysis.reports.renderer import render_report
from stock_analysis.run_logging import configure_run_logger
from stock_analysis.usage import five_hour_usage, format_usage


ROOT = Path(__file__).resolve().parents[3]


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class DetailedHelpParser(argparse.ArgumentParser):
    """Show complete subcommand help when the root parser is requested."""

    include_subcommands = False

    def format_help(self) -> str:
        text = super().format_help()
        if not self.include_subcommands:
            return text
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, subparser in action.choices.items():
                    text += f"\n{'=' * 78}\n{name.upper()} COMMAND\n{'=' * 78}\n"
                    text += subparser.format_help()
        return text


def build_parser() -> argparse.ArgumentParser:
    model_defaults = load_model_defaults(ROOT / "config" / "models.yaml")
    providers = ("chatgpt", "chatgpt_api", "claude", "claude_api", "gemini", "gemini_api", "antigravity")
    provider_defaults = ", ".join(f"{name}={model_defaults.model_for(name)}" for name in providers)
    provider_models = "; ".join(f"{name}: {', '.join(model_defaults.models_for(name))}" for name in providers)
    parser = DetailedHelpParser(
        prog="learn",
        description="Generate auditable, exchange-aware stock reports using specialist agents,\nindependent bull/bear adjudicators, and a neutral final adjudicator.",
        epilog="""Configuration precedence:
  command-line override > config/models.yaml

Generated files:
  reports/<country>/<exchange>/TICKER_YYMMDD.html
  reports/<country>/<exchange>/TICKER_YYMMDD.json
  runtime/runs/<run-id>/               audit records and run.log

Quick start:
  uv sync
  uv run learn auth status
  uv run learn generate --ticker RELIANCE --exchange nse
  uv run learn generate --ticker APOLLO,RELIANCE --exchange nse

Use 'uv run learn <command> --help' for focused help.""",
        formatter_class=HelpFormatter,
    )
    parser.include_subcommands = True
    parser.add_argument("--version", action="version", version=f"learn {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser(
        "auth", help="Manage the ChatGPT-plan login", description="Inspect or manage the Codex login reused by the default ChatGPT provider.",
        epilog="Examples:\n  uv run learn auth status\n  uv run learn auth login", formatter_class=HelpFormatter,
    )
    auth.add_argument("action", choices=("status", "login", "logout"), help="Authentication operation to perform")
    generate = sub.add_parser(
        "generate", help="Generate HTML and JSON reports",
        description="Run five specialists, bull/bear adjudicators, and final adjudication; then render HTML, JSON and an audit trail.",
        epilog="""Examples:
  uv run learn generate --ticker RELIANCE --exchange nse
  uv run learn generate --ticker AAPL --exchange nasdaq --risk conservative
  uv run learn generate --ticker RELIANCE --exchange nse --model gpt-5.6-luna --reasoning-effort low --verbose
  uv run learn generate --ticker TESTCO --exchange nse --dry-run
  uv run learn generate --ticker RELIANCE --exchange nse --resume runtime/runs/<failed-run>""",
        formatter_class=HelpFormatter,
    )
    generate.add_argument("--ticker", required=True, help="One ticker or a comma-separated list; all tickers use the same exchange")
    generate.add_argument("--exchange", required=True, choices=("nse", "bse", "nasdaq", "nyse"), help="Listing exchange; determines country prompts, sources and output directory")
    generate.add_argument("--risk", default="moderate", choices=("conservative", "moderate", "aggressive"), help="Investor risk profile used by the adjudicators")
    generate.add_argument("--technical-horizon", default="4-8 weeks", help="Horizon used by the technical-analysis specialist")
    generate.add_argument("--fundamental-horizon", default="1 year", help="Horizon used by the fundamentals specialist")
    generate.add_argument("--as-of", default=date.today().isoformat(), help="Analysis date in YYYY-MM-DD format")
    generate.add_argument(
        "--provider", choices=providers, default="chatgpt",
        help="Provider: account login (chatgpt/claude/antigravity; legacy gemini) or separately billed API (*_api)",
    )
    generate.add_argument(
        "--model", default=argparse.SUPPRESS,
        help=f"Override the selected provider's model. Defaults: {provider_defaults}. Configured models: {provider_models}",
    )
    generate.add_argument("--reasoning-effort", choices=SUPPORTED_REASONING_EFFORTS, default=model_defaults.reasoning_effort, help="Reasoning effort configured for report agents")
    generate.add_argument("--research-file", type=Path, help="Optional JSON packet containing deterministic or proprietary research data")
    generate.add_argument("--output", type=Path, help="Override the generated HTML path; matching JSON uses the same stem")
    generate.add_argument("--resume", type=Path, help="Resume one ticker from a prior run directory or checkpoint.json")
    generate.add_argument("--dry-run", action="store_true", help="Exercise orchestration and rendering without model calls")
    verbosity = generate.add_mutually_exclusive_group()
    verbosity.add_argument("--verbose", action="store_true", help="Show debug-level console logging")
    verbosity.add_argument("--quiet", action="store_true", help="Only show warnings, errors and final output")
    source_cmd = sub.add_parser(
        "sources", help="Show the mandatory source manifest",
        description="Print the exchange-aware source manifest as JSON without running an analysis.",
        epilog="Example:\n  uv run learn sources --ticker BOSCHLTD --exchange nse", formatter_class=HelpFormatter,
    )
    source_cmd.add_argument("--ticker", required=True, help="Exchange ticker symbol")
    source_cmd.add_argument("--exchange", required=True, choices=("nse", "bse", "nasdaq", "nyse"), help="Listing exchange")
    return parser


def _auth(action: str) -> int:
    codex = find_codex()
    args = [codex, "login", "status"] if action == "status" else [codex, "login"] if action == "login" else [codex, "logout"]
    return subprocess.run(args, check=False).returncode


def parse_tickers(value: str) -> list[str]:
    tickers = [part.strip().upper() for part in value.split(",")]
    if not tickers or any(not ticker for ticker in tickers):
        raise ValueError("--ticker must be one symbol or a comma-separated list without empty values")
    if len(set(tickers)) != len(tickers):
        raise ValueError("--ticker contains a duplicate symbol")
    return tickers


def _request(args: argparse.Namespace, ticker: str) -> ReportRequest:
    return ReportRequest(ticker, args.exchange, args.risk, args.technical_horizon, args.fundamental_horizon, args.as_of)


def _read_usage(provider, model: str, logger, label: str, previous: dict | None = None) -> dict | None:
    try:
        usage = five_hour_usage(provider.get_rate_limits(), model)
    except Exception as exc:
        logger.warning("ChatGPT 5-hour usage %s could not be read: %s", label, exc)
        logger.debug("Usage-read traceback", exc_info=True)
        return None
    logger.info(format_usage(label, usage, previous))
    return usage


def _create_provider(provider_name: str, model: str, reasoning_effort: str, logger=None):
    if provider_name == "chatgpt":
        return CodexAppServerProvider(model, reasoning_effort, ROOT)
    if provider_name == "chatgpt_api":
        return OpenAIAPIProvider(model, reasoning_effort)
    if provider_name == "claude":
        return ClaudeCLIProvider(model, reasoning_effort, ROOT)
    if provider_name == "claude_api":
        return AnthropicAPIProvider(model, reasoning_effort)
    if provider_name == "gemini":
        return GeminiCLIProvider(model, reasoning_effort, ROOT)
    if provider_name == "gemini_api":
        return GeminiAPIProvider(model, reasoning_effort)
    if provider_name == "antigravity":
        return AntigravityCLIProvider(model, reasoning_effort, ROOT, on_retry=logger.warning if logger else None)
    raise ValueError(f"unknown provider: {provider_name}")


def _generate_one(args: argparse.Namespace, ticker: str, model: str, reasoning_effort: str, research: dict) -> dict:
    started = time.monotonic()
    request = _request(args, ticker)
    resume_state = load_checkpoint(args.resume, request) if args.resume else None
    stamp = datetime.strptime(request.as_of, "%Y-%m-%d").strftime("%y%m%d")
    output = args.output or ROOT / "reports" / request.country / request.exchange / f"{request.ticker}_{stamp}.html"
    run_id = f"{request.exchange}-{request.ticker}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    run_dir = ROOT / "runtime" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    log_file = run_dir / "run.log"
    checkpoint_path = run_dir / "checkpoint.json"
    usage_path = run_dir / "usage.json"
    logger = configure_run_logger(log_file, verbose=args.verbose, quiet=args.quiet)
    (run_dir / "request.json").write_text(json.dumps(request.as_dict(), indent=2))
    execution = {
        "provider": "dry-run" if args.dry_run else args.provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "resumed_from": str(args.resume.resolve()) if args.resume else None,
    }
    (run_dir / "execution.json").write_text(json.dumps(execution, indent=2))
    logger.info("Run %s", run_id)
    logger.info("Request: %s:%s | risk %s | technicals %s | fundamentals %s", request.exchange.upper(), request.ticker, request.risk, request.technical_horizon, request.fundamental_horizon)
    logger.info("Provider: %s | model: %s | reasoning effort: %s", execution["provider"], model, reasoning_effort)
    logger.info("Run log: %s", log_file)
    logger.info("Checkpoint: %s", checkpoint_path)
    if args.resume:
        logger.info("Resuming saved state from %s", args.resume)
    try:
        if args.dry_run:
            provider = DryRunProvider()
        else:
            descriptions = {
                "chatgpt": "Starting Codex app-server using the existing ChatGPT login",
                "chatgpt_api": "Connecting to the OpenAI Responses API",
                "claude": "Starting Claude CLI using its existing subscription login",
                "claude_api": "Connecting to the Anthropic Messages API",
                "gemini": "Starting Gemini CLI using its existing Google login",
                "gemini_api": "Connecting to the Gemini generateContent API",
                "antigravity": "Starting Antigravity CLI using its cached Google login",
            }
            logger.info(descriptions[args.provider])
            provider = _create_provider(args.provider, model, reasoning_effort, logger)
        logger.info("Model provider ready")
        usage_before = None
        usage_after = None
        with provider:
            if args.provider == "chatgpt" and not args.dry_run:
                usage_before = _read_usage(provider, model, logger, "before")
                usage_path.write_text(json.dumps({"before": usage_before, "after": None, "delta_percentage_points": None}, indent=2))
            try:
                report, audit = run_analysis(provider, request, research, logger, checkpoint_path, resume_state)
            finally:
                if args.provider == "chatgpt" and not args.dry_run:
                    usage_after = _read_usage(provider, model, logger, "after", usage_before)
                    delta = None
                    if usage_before and usage_after:
                        delta = usage_after["used_percent"] - usage_before["used_percent"]
                    usage_path.write_text(json.dumps({"before": usage_before, "after": usage_after, "delta_percentage_points": delta}, indent=2))
                elif args.provider == "antigravity" and not args.dry_run:
                    provider_usage = provider.get_usage()
                    if provider_usage:
                        usage_path.write_text(json.dumps(provider_usage, indent=2))
                        totals = provider_usage.get("totals", {})
                        logger.info(
                            "Antigravity usage: %s total tokens (%s input, %s output, %s thinking, %s cache reads) across %s model turns",
                            totals.get("total_tokens", 0), totals.get("input_tokens", 0),
                            totals.get("output_tokens", 0), totals.get("thinking_tokens", 0),
                            totals.get("cache_read_tokens", 0), len(provider_usage.get("calls", [])),
                        )
        logger.info("Rendering report")
        render_report(report, output)
        json_output = output.with_suffix(".json")
        json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        (run_dir / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False))
        elapsed = time.monotonic() - started
        manifest = {
            "status": "complete", "html": str(output), "json": str(json_output), "log": str(log_file),
            "usage": str(usage_path) if usage_path.exists() else None, "elapsed_seconds": round(elapsed, 3),
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        logger.info("Report written: %s", output)
        logger.info("Machine-readable data written: %s", json_output)
        logger.info("Run completed successfully in %.1fs", elapsed)
    except (Exception, KeyboardInterrupt) as exc:
        provider_pause = isinstance(exc, ProviderTurnError) and exc.resumable
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "paused" if provider_pause else "failed"
        elapsed = time.monotonic() - started
        marker = "PAUSED" if status == "paused" else "FAILED"
        (run_dir / marker).write_text(datetime.now(timezone.utc).isoformat())
        error_code = exc.code if isinstance(exc, ProviderTurnError) else None
        resume_parts = [
            "uv", "run", "learn", "generate", "--ticker", request.ticker, "--exchange", request.exchange,
            "--risk", request.risk, "--technical-horizon", request.technical_horizon,
            "--fundamental-horizon", request.fundamental_horizon, "--as-of", request.as_of,
            "--provider", args.provider, "--model", model, "--reasoning-effort", reasoning_effort,
            "--resume", str(run_dir),
        ]
        if args.research_file:
            resume_parts.extend(["--research-file", str(args.research_file.resolve())])
        if args.output:
            resume_parts.extend(["--output", str(args.output.resolve())])
        if args.verbose:
            resume_parts.append("--verbose")
        elif args.quiet:
            resume_parts.append("--quiet")
        resume_command = shlex.join(resume_parts)
        failure_manifest = {
            "status": status, "error": str(exc) or type(exc).__name__, "error_code": error_code,
            "checkpoint": str(checkpoint_path), "resume_command": resume_command,
            "log": str(log_file), "usage": str(usage_path) if usage_path.exists() else None,
            "elapsed_seconds": round(elapsed, 3),
        }
        (run_dir / "manifest.json").write_text(json.dumps(failure_manifest, indent=2))
        logger.warning("Run %s after %.1fs: %s", status, elapsed, str(exc) or type(exc).__name__)
        logger.warning("Saved checkpoint: %s", checkpoint_path)
        logger.warning("Resume with: %s", resume_command)
        logger.debug("Failure traceback", exc_info=True)
        setattr(exc, "run_dir", run_dir)
        setattr(exc, "resume_command", resume_command)
        raise
    print(f"Report: {output}")
    print(f"Data:   {json_output}")
    print(f"Audit:  {run_dir}")
    print(f"Log:    {log_file}")
    print(f"Model:  {model} ({reasoning_effort} effort)")
    return {"ticker": request.ticker, "report": str(output), "run_dir": str(run_dir)}


def _generate(args: argparse.Namespace) -> int:
    tickers = parse_tickers(args.ticker)
    if len(tickers) > 1 and args.output:
        raise ValueError("--output cannot be used with multiple tickers; each report uses its standard output path")
    if len(tickers) > 1 and args.resume:
        raise ValueError("--resume accepts exactly one ticker")
    defaults = load_model_defaults(ROOT / "config" / "models.yaml")
    model = getattr(args, "model", None) or defaults.model_for(args.provider)
    reasoning_effort = args.reasoning_effort or defaults.reasoning_effort
    research = json.loads(args.research_file.read_text()) if args.research_file else {}
    completed: list[dict] = []
    if len(tickers) > 1:
        print(f"Batch: {len(tickers)} independent reports on {args.exchange.upper()}")
    for index, ticker in enumerate(tickers, start=1):
        if len(tickers) > 1:
            print(f"\n=== [{index}/{len(tickers)}] {args.exchange.upper()}:{ticker} ===", flush=True)
        try:
            completed.append(_generate_one(args, ticker, model, reasoning_effort, research))
        except ProviderTurnError as exc:
            print(f"\nBatch stopped after {len(completed)} completed report(s).", file=sys.stderr)
            print(f"Saved state: {getattr(exc, 'run_dir', 'see latest run directory')}", file=sys.stderr)
            print(f"Resume: {getattr(exc, 'resume_command', 'see manifest.json')}", file=sys.stderr)
            return 75 if exc.resumable else 2
        except Exception:
            if completed:
                print(f"\nPreserved {len(completed)} completed report(s) before the failure.", file=sys.stderr)
            raise
    if len(tickers) > 1:
        print(f"\nBatch complete: {len(completed)}/{len(tickers)} reports written.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "auth":
            return _auth(args.action)
        if args.command == "sources":
            request = ReportRequest(args.ticker, args.exchange)
            print(json.dumps([source.as_dict() for source in sources_for(request)], indent=2))
            return 0
        return _generate(args)
    except (ValueError, ProviderError, json.JSONDecodeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: run interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

