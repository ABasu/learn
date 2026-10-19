# Stock Analysis Workspace

A reusable, exchange-aware workspace for generating investment research reports.

## Output convention

Reports are written to:

```text
reports/{country}/{exchange}/{TICKER}_{YYMMDD}.html
```

Examples:

- `reports/us/nasdaq/AAPL_261019.html`
- `reports/india/nse/RELIANCE_261019.html`

Prompts under `prompts/` are the only agent instructions. Application settings live in `config/`; implementation code lives in `src/`.
