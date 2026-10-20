# LEARN

```text
 _      _____    _    ____  _   _
| |    | ____|  / \  |  _ \| \ | |
| |    |  _|   / _ \ | |_) |  \| |
| |___ | |___ / ___ \|  _ <| |\  |
|_____||_____/_/   \_\_| \_\_| \_|

     LLM Equity Analysis & Research Node
```

LEARN is a reusable command-line workspace for producing structured, auditable equity-research reports. Give it one or more stock tickers, an exchange, and an LLM connection; it coordinates specialist research agents, weighs bullish and bearish arguments, and writes a dark-themed HTML report plus machine-readable JSON.

It currently supports NSE, BSE, NASDAQ, and NYSE stocks. Indian reports use lakh/crore conventions and prioritize Indian-market sources such as exchange filings and Screener.

> [!IMPORTANT]
> LEARN is a research aid, not personalized investment advice. LLM output and market data can be incomplete, stale, or incorrect. Verify filings, prices, and important claims before acting.

## Quick start

Prerequisites: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and at least one configured model provider.

```bash
cd /Users/anupam/Desktop/AB/DH/learn
uv sync
uv run learn auth status
uv run learn generate --ticker RELIANCE --exchange nse
```

The default provider is the locally authenticated ChatGPT/Codex connection. The finished report is written under `reports/india/nse/`.

## Copy-and-paste recipes

These commands are intended as shortcuts: usually you only need to replace the ticker.

### One Indian stock

```bash
uv run learn generate --ticker RELIANCE --exchange nse
```

```bash
uv run learn generate --ticker 500325 --exchange bse
```

### One US stock

```bash
uv run learn generate --ticker AAPL --exchange nasdaq
```

```bash
uv run learn generate --ticker IBM --exchange nyse
```

### Several stocks from the same exchange

```bash
uv run learn generate \
  --ticker APOLLO,RELIANCE,PIDILITIND \
  --exchange nse
```

Each ticker gets a completely independent, sequential run. LEARN finishes and saves one report before starting the next, so already completed reports remain intact if a later run hits a provider limit or fails. Every ticker in the comma-separated list must belong to the same exchange.

### Choose an LLM connection

```bash
# ChatGPT subscription login through the local Codex connection
uv run learn generate --ticker RELIANCE --exchange nse --provider chatgpt

# OpenAI API
uv run learn generate --ticker RELIANCE --exchange nse --provider chatgpt_api

# Claude subscription login through Claude Code
uv run learn generate --ticker RELIANCE --exchange nse --provider claude

# Anthropic API
uv run learn generate --ticker RELIANCE --exchange nse --provider claude_api

# Gemini CLI connection (where supported)
uv run learn generate --ticker RELIANCE --exchange nse --provider gemini

# Gemini API
uv run learn generate --ticker RELIANCE --exchange nse --provider gemini_api

# Antigravity/agy using its cached Google login
uv run learn generate --ticker RELIANCE --exchange nse --provider antigravity
```

### Adjust risk and horizons

```bash
uv run learn generate \
  --ticker BRITANNIA \
  --exchange nse \
  --risk conservative \
  --technical-horizon "4-8 weeks" \
  --fundamental-horizon "1 year"
```

Risk choices are `conservative`, `moderate`, and `aggressive`. The default technical horizon is `4-8 weeks`; the default fundamental horizon is `1 year`.

### Override the model and reasoning effort

```bash
uv run learn generate \
  --ticker AAPL \
  --exchange nasdaq \
  --provider chatgpt \
  --model gpt-5.6-terra \
  --reasoning-effort medium
```

Valid reasoning levels are `none`, `low`, `medium`, `high`, `xhigh`, and `max`, subject to provider/model support. Provider defaults and model catalogs live in `config/models.yaml`; command-line flags override them for one run.

### More useful shortcuts

```bash
# Detailed progress
uv run learn generate --ticker RELIANCE --exchange nse --verbose

# Inspect mandatory sources before running
uv run learn sources --ticker BOSCHLTD --exchange nse

# Add a prepared research packet
uv run learn generate --ticker RELIANCE --exchange nse --research-file research.json

# Validate the workflow without live model calls
uv run learn generate --ticker TESTCO --exchange nse --dry-run --output /tmp/TESTCO.html
```

Use `--quiet` when you want minimal terminal output.

## What LEARN produces

For every ticker, LEARN creates:

- A readable HTML investment report with company introduction, summary panels, score tags, price history, technicals, fundamentals, valuation, risks, catalysts, bull case, bear case, peer context, and linked sources.
- A JSON companion containing structured scores, confidence, evidence, recommendations, and report data for future evaluation or backtesting.
- An audit directory containing the request, execution metadata, checkpoint, model responses, usage records, source manifest, and run log.

Default paths follow this pattern:

```text
reports/<country>/<exchange>/TICKER_YYMMDD.html
reports/<country>/<exchange>/TICKER_YYMMDD.json
runtime/runs/<exchange>-<ticker>-<run-id>/
```

For example:

```text
reports/india/nse/RELIANCE_261020.html
reports/india/nse/RELIANCE_261020.json
runtime/runs/nse-RELIANCE-20261020T150330503184Z/
```

## How the analysis works

```text
Ticker + exchange + preferences
              |
              v
   Source plan / research packet
              |
              v
  +-----------------------------------+
  | Fundamentals | Technicals         |
  | Valuation    | Catalysts | Risks  |
  +-----------------------------------+
              |
              v
       Bull and bear adjudicators
              |
              v
       Neutral final adjudicator
              |
              v
        HTML + JSON + audit trail
```

The five specialists use a consistent response schema: score, confidence, evidence points, sources, scenario, and invalidation conditions. Bull- and bear-biased adjudicators then construct the strongest opposing cases. A final neutral adjudicator weighs the evidence, resolves disagreements, and assigns the overall stance and score.

This structure makes the final model compare explicit evidence and structured scores instead of merely summarizing several free-form essays.

## Features

- Multi-agent analysis across fundamentals, technicals, valuation, catalysts, and risks.
- Independent bull, bear, and final adjudication stages.
- Adjustable prompt files kept separate from application code.
- Multiple local-subscription and API-based LLM connections.
- Single-ticker and sequential multi-ticker runs.
- Automatic checkpoints and resumable failed runs.
- Dark, self-contained HTML reports and machine-readable JSON.
- Easily readable analysis score tags for later performance studies.
- Exchange-specific sources, formatting, and report locations.
- Indian numerical conventions for Indian companies; million/billion conventions elsewhere.
- Source manifests, inline citations, logs, execution metadata, and usage records.
- One-year price context with lightweight visualizations when reliable data is available.

## Installation

### 1. Install uv

Follow the official [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/), then confirm:

```bash
uv --version
```

### 2. Install the project environment

```bash
cd /Users/anupam/Desktop/AB/DH/learn
uv sync
```

`uv sync` creates or updates the local virtual environment from `pyproject.toml` and the lock file. You do not need to activate it; prefix project commands with `uv run`.

### 3. Configure at least one provider

LEARN supports two broad connection types:

1. **Local authenticated connections** use an existing consumer/subscription login where the provider permits it: `chatgpt`, `claude`, `gemini`, and `antigravity`.
2. **API connections** use developer credentials and are billed independently of consumer subscriptions: `chatgpt_api`, `claude_api`, and `gemini_api`.

Availability, model names, quotas, and consumer-login rules can change. Run `uv run learn generate --help` to see the choices recognized by your installed version.

## Provider setup

| Provider | Connection | Credential or login | Repository default model |
|---|---|---|---|
| `chatgpt` | Local ChatGPT/Codex | `learn auth login` | `gpt-5.6-terra` |
| `chatgpt_api` | OpenAI API | `OPENAI_API_KEY` | `gpt-5.6-terra` |
| `claude` | Claude Code | `claude`, then `/login` | `sonnet` |
| `claude_api` | Anthropic API | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| `gemini` | Gemini CLI | Provider CLI login | `pro` |
| `gemini_api` | Gemini API | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-2.5-pro` |
| `antigravity` | Antigravity `agy` | Cached Google login | `gemini-3.8-flash-medium` |

The table reflects repository defaults, not a guarantee that every model is available to every account.

### ChatGPT

```bash
uv run learn auth status
uv run learn auth login
uv run learn auth logout
```

The `chatgpt` provider uses the existing ChatGPT-plan login through the local Codex service and does not require an API key. The `chatgpt_api` provider is separate and requires API credit:

```bash
export OPENAI_API_KEY="your-key"
uv run learn generate --ticker AAPL --exchange nasdaq --provider chatgpt_api
```

### Claude

Install Claude Code, run `claude`, and complete `/login`. Then:

```bash
uv run learn generate --ticker RELIANCE --exchange nse --provider claude
```

For the API connection:

```bash
export ANTHROPIC_API_KEY="your-key"
uv run learn generate --ticker RELIANCE --exchange nse --provider claude_api
```

### Gemini API

```bash
export GEMINI_API_KEY="your-key"
uv run learn generate --ticker AAPL --exchange nasdaq --provider gemini_api
```

`GOOGLE_API_KEY` is also recognized. API usage is billed and quota-controlled separately from a consumer Gemini subscription.

### Antigravity

Install and authenticate the official `agy` command, then verify that it is on `PATH` (or installed at `~/.local/bin/agy`). Run:

```bash
agy
uv run learn generate --ticker RELIANCE --exchange nse --provider antigravity
```

Antigravity is useful for occasionally using the Google-account/free-tier allocation exposed by that client. LEARN records its reported input, output, thinking, cache-read, and total token counts in the run's `usage.json`.

## Model configuration

Edit `config/models.yaml` to change persistent defaults. For example:

```yaml
defaults:
  model: gpt-5.6-terra
  reasoning_effort: low

provider_defaults:
  chatgpt: gpt-5.6-terra
  claude: sonnet
  antigravity: gemini-3.8-flash-medium
```

Use command-line options for a temporary override:

```bash
uv run learn generate \
  --ticker RELIANCE \
  --exchange nse \
  --provider antigravity \
  --model gemini-3.8-flash-low \
  --reasoning-effort low
```

Some model names encode the effort level themselves. LEARN normalizes provider-specific settings before launching a model turn.

## Prompt customization

User-editable prompts are under `prompts/`, separate from Python code and runtime configuration. You can tune a specialist or adjudicator without editing orchestration code.

Typical prompt groups include:

```text
prompts/
├── specialists/
│   ├── fundamentals.*
│   ├── technicals.*
│   ├── valuation.*
│   ├── catalysts.*
│   └── risks.*
└── adjudicators/
    ├── bull.*
    ├── bear.*
    └── final.*
```

Keep the required structured-output fields intact when revising prompts. The orchestration and scoring layers depend on the shared schema.

## Sources and market conventions

Source rules are exchange-aware. For Indian companies, LEARN treats these as important inputs:

- NSE or BSE company announcements and filings.
- Company investor-relations pages, presentations, and annual reports.
- Screener consolidated pages for historical financials and peer comparisons, using URLs such as `https://www.screener.in/company/BOSCHLTD/consolidated/`.

For US companies, regulator filings and company investor-relations materials take priority. Use `learn sources` to inspect the manifest for a ticker and exchange.

Indian reports display values in thousands, lakhs, crores, and thousands of crores as appropriate. Other markets use million and billion conventions.

## Checkpoints and recovery

LEARN saves progress after completed stages. If a provider quota expires, a model turn fails, or a response is empty, the terminal prints a resume command and preserves the checkpoint.

```bash
uv run learn generate \
  --ticker RELIANCE \
  --exchange nse \
  --resume runtime/runs/nse-RELIANCE-<run-id>
```

The exact resume command in the log includes the original provider, model, effort, risk, horizons, and date. Copy that command where possible. Resume mode accepts one ticker because each checkpoint belongs to one independent analysis.

## Usage and quota reporting

- `chatgpt` records the available five-hour-window percentage and reset time when the local service exposes them. It cannot reliably convert that allowance into an absolute token count.
- `antigravity` records the token categories reported by `agy`, including input, output, thinking, cache reads, and total tokens.
- API providers remain subject to their own billing, rate limits, and account dashboards.

Usage details are saved in `usage.json` when the provider supplies them.

## Command reference

```bash
uv run learn --help
uv run learn auth --help
uv run learn generate --help
uv run learn sources --help
```

Core `generate` options:

| Option | Purpose |
|---|---|
| `--ticker` | One ticker or a comma-separated list |
| `--exchange` | `nse`, `bse`, `nasdaq`, or `nyse` |
| `--risk` | `conservative`, `moderate`, or `aggressive` |
| `--technical-horizon` | Time horizon for technical analysis |
| `--fundamental-horizon` | Time horizon for fundamental analysis |
| `--as-of` | Fix the analysis date |
| `--provider` | Select the LLM connection |
| `--model` | Override that provider's configured model |
| `--reasoning-effort` | Override the configured effort level |
| `--research-file` | Add a local structured research packet |
| `--resume` | Continue a checkpointed single-ticker run |
| `--output` | Override the destination for a single report |
| `--verbose` | Show detailed progress and diagnostics |
| `--quiet` | Reduce terminal output |
| `--dry-run` | Validate/report without live model calls |

## Project layout

```text
learn/
├── config/               # Provider, model, scoring, and source configuration
├── prompts/              # User-editable specialist and adjudicator prompts
├── reports/              # Generated reports by country and exchange
├── runtime/runs/         # Checkpoints, logs, usage, and audit artifacts
├── src/stock_analysis/   # CLI, providers, orchestration, and rendering
├── tests/                 # Unit tests
├── pyproject.toml         # Package metadata and `learn` command
├── uv.lock                # Reproducible dependency lock
└── README.md
```

## Development and verification

```bash
uv sync
uv run python -m unittest discover -s tests/unit -v
uv run learn --help
uv run learn generate --help
```

## Troubleshooting

### A local provider starts with the wrong model

Provider-specific defaults should prevent a ChatGPT model from being sent to Claude, Gemini, or Antigravity. Inspect `config/models.yaml`, or pass `--model` explicitly using a model supported by the selected provider.

### A run stops midway

Use the printed resume command. Completed stages are stored in `checkpoint.json` and should not be repeated.

### Antigravity reports no model output

LEARN retries one empty successful response. If the second response is still empty, it stops cleanly and saves a resumable checkpoint. Check the `agy` login/quota, then resume.

### A provider rejects structured output

Different providers support different JSON Schema dialects. LEARN translates schemas where needed, but an older provider CLI may still be incompatible. Update that CLI and retry from the checkpoint.

### Price history is unavailable

LEARN should not invent OHLCV data. When a reliable one-year series cannot be retrieved, the report may use a simpler verified snapshot or explicitly state the limitation.

### Scores look wrong or remain at zero

Inspect the generated JSON and specialist responses in the audit directory. Each specialist must return the required numeric score and confidence fields for the renderer to display them correctly.

## Responsible use

Treat every report as a starting point for due diligence. Check primary filings, validate current prices and corporate actions, distinguish facts from scenarios, and review the report date before using its conclusions. Past performance, model confidence, and a high analysis score do not guarantee future returns.
