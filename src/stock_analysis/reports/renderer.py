from __future__ import annotations

import html
import json
from pathlib import Path


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else "N/A"))


def _paragraphs(value: object) -> str:
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in value) + "</ul>"
    return "".join(f"<p>{_esc(part.strip())}</p>" for part in str(value or "Not supplied.").split("\n") if part.strip())


def _sources(report: dict) -> str:
    sources = report.get("sources") or report.get("source_manifest", [])
    items = []
    for source in sources:
        if isinstance(source, str):
            label, url = source, source
        else:
            label, url = source.get("name", source.get("url", "Source")), source.get("url", "")
        link = f'<a href="{_esc(url)}">{_esc(label)}</a>' if str(url).startswith("http") else _esc(label)
        items.append(f"<li>{link}</li>")
    return "<ol>" + "".join(items) + "</ol>"


def render_report(report: dict, output: Path) -> None:
    score = float(report.get("weighted_score", 0))
    score_text = f"{score:+.2f}"
    specialist_cards = "".join(
        f'<div class="metric"><small>{_esc(name.title())}</small><strong>{float(data["score"]):+.1f}</strong><span>{_esc(data["confidence"])} confidence</span></div>'
        for name, data in report.get("specialist_scores", {}).items()
    )
    sections = [
        ("Company profile", "company_profile"), ("Industry overview", "industry_overview"),
        ("Technicals", "technicals"), ("Fundamentals", "fundamentals"),
        ("Valuation", "valuation"), ("Risks", "risks"), ("Catalysts", "catalysts"),
        ("Sector and peer companies", "sector_and_peers"),
    ]
    body = "".join(f'<section class="card"><h2>{title}</h2>{_paragraphs(report.get(key))}</section>' for title, key in sections)
    metadata = json.dumps({
        key: report.get(key) for key in ("ticker", "exchange", "analysis_date", "price_as_of", "reference_price", "technical_horizon", "fundamental_horizon", "weighted_score", "score_scale", "stance", "confidence")
    }, ensure_ascii=False).replace("</", "<\\/")
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(report.get("ticker"))} investment report</title><style>
:root{{--bg:#07101d;--panel:#101d30;--line:#263954;--text:#eef5ff;--muted:#a9bad0;--cyan:#59d5cf;--amber:#ffbb55}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.62 system-ui,sans-serif}}main{{max-width:1320px;margin:auto;padding:24px}}.hero{{position:relative;padding:34px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(135deg,#102a48,#174b4a)}}h1{{font-size:clamp(34px,6vw,64px);margin:.15em 0}}h2{{margin-top:0}}.eyebrow,small,.muted{{color:var(--muted)}}.tag{{position:absolute;right:28px;top:28px;padding:12px 18px;border-radius:14px;background:#07101dcc;border:1px solid #ffffff33;text-align:center}}.tag strong{{display:block;font-size:30px;color:var(--amber)}}.summary{{max-width:900px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:18px}}.card{{padding:24px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}}.scorecard{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.metric{{padding:14px;border-radius:12px;background:#0a1525;text-align:center}}.metric strong,.metric span{{display:block}}.metric strong{{color:var(--cyan);font-size:23px}}a{{color:#7ce0dc}}.cases{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.break{{margin-top:36px;border-top:2px solid var(--line);padding-top:24px}}@media(max-width:800px){{.grid,.cases{{grid-template-columns:1fr}}.scorecard{{grid-template-columns:repeat(2,1fr)}}.tag{{position:static;display:inline-block}}}}</style></head><body><main>
<header class="hero"><div class="tag" data-analysis-score="{score_text}"><small>Analysis score</small><strong>{score_text}</strong><small>-2 to +2</small></div><div class="eyebrow">{_esc(report.get("exchange"))} · {_esc(report.get("analysis_date"))} · {_esc(report.get("risk_profile"))} risk</div><h1>{_esc(report.get("company_name", report.get("ticker")))} <span class="muted">{_esc(report.get("ticker"))}</span></h1><h2>{_esc(report.get("stance", "neutral").title())} · {_esc(report.get("confidence", "low"))} confidence</h2><div class="summary">{_paragraphs(report.get("executive_summary", report.get("rationale")))}</div></header>
<section class="card" style="margin-top:18px"><h2>Specialist scorecard</h2><div class="scorecard">{specialist_cards}</div></section>
<div class="grid">{body}</div>
<section class="cases break"><article class="card"><h2>Bull case</h2>{_paragraphs(report.get("bull_case"))}</article><article class="card"><h2>Bear case</h2>{_paragraphs(report.get("bear_case"))}</article></section>
<section class="card break"><h2>Sources</h2>{_sources(report)}<h3>Limitations</h3>{_paragraphs(report.get("limitations", []))}</section>
<script id="analysis-metadata" type="application/json">{metadata}</script></main></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document)

