"""Text, JSON and self-contained HTML reports."""
from __future__ import annotations

import html
import json
from decimal import Decimal


def format_json(summary: dict) -> str:
    return json.dumps(summary, indent=2, default=str)


def format_text(summary: dict, currency: str = "USD") -> str:
    lines = []
    totals = summary["totals"]
    lines.append(f"run ledger — {len(summary['runs'])} run(s), {totals['events']} event(s)")
    lines.append(f"priced cost: {totals['cost']} {currency} · fees: {totals['fees']} {currency} · unknown-price calls: {totals['unknown_calls']}")
    lines.append("")
    for run in summary["runs"]:
        actor = run.get("actor") or {}
        status = run.get("status") or "open"
        lines.append(f"{run['run_id']}  [{status}]  {actor.get('name', 'unknown')} ({actor.get('role', 'n/a')})")
        if run.get("task"):
            lines.append(f"  task: {run['task']}")
        lines.append(
            f"  calls {run['calls']} · tokens {run['input_tokens']} in / {run['output_tokens']} out · "
            f"cost {run['cost']} {currency} · unknown {run['unknown_calls']} · fees {run['fees']} {currency}"
        )
        if run["reviews"]:
            latest = run["reviews"][-1]
            lines.append(f"  review: {latest['decision']} by {(latest.get('actor') or {}).get('name', 'unknown')}")
        if run["redactions"]:
            lines.append(f"  redactions: {run['redactions']}")
    return "\n".join(lines)


def format_html(summary: dict, currency: str = "USD") -> str:
    totals = summary["totals"]
    rows = []
    for run in summary["runs"]:
        actor = run.get("actor") or {}
        review = run["reviews"][-1]["decision"] if run["reviews"] else "—"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(run['run_id'])}</code></td>"
            f"<td>{html.escape(str(actor.get('name', '—')))}<br><small>{html.escape(str(actor.get('role', '')))}</small></td>"
            f"<td>{html.escape(run.get('task') or '—')}</td>"
            f"<td class='num'>{run['calls']}</td>"
            f"<td class='num'>{run['input_tokens']:,}</td>"
            f"<td class='num'>{run['output_tokens']:,}</td>"
            f"<td class='num'>{run['cost']}</td>"
            f"<td class='num {'warn' if run['unknown_calls'] else ''}'>{run['unknown_calls']}</td>"
            f"<td>{html.escape(str(run.get('status') or 'open'))}</td>"
            f"<td>{html.escape(review)}</td>"
            "</tr>"
        )
    timeline = "".join(
        f"<li><span class='seq'>#{row['seq']}</span> <b>{html.escape(row['type'])}</b> "
        f"<code>{html.escape(row['run_id'])}</code> <small>{html.escape(row['at'])}</small></li>"
        for row in summary["timeline"][-40:]
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Run ledger</title>
<style>
:root{{--bg:#0b1118;--panel:#121b25;--ink:#e8f1f8;--muted:#8ea3b6;--line:#22303d;--accent:#5eead4;--warn:#fbbf24}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",system-ui,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:32px 20px 60px}}
h1{{font-size:22px;margin:0 0 4px}}p.sub{{color:var(--muted);margin:0 0 22px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}}
.card b{{display:block;font-size:22px;font-variant-numeric:tabular-nums}}.card span{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}.warn{{color:var(--warn)}}
code{{font-family:"Cascadia Code",Consolas,monospace;font-size:12px}}
small{{color:var(--muted)}}ul.timeline{{list-style:none;padding:0;margin:24px 0 0;background:var(--panel);border:1px solid var(--line);border-radius:12px}}
ul.timeline li{{padding:8px 12px;border-bottom:1px solid var(--line)}}ul.timeline li:last-child{{border:0}}
.seq{{color:var(--accent);font-family:monospace;margin-right:8px}}
footer{{margin-top:26px;color:var(--muted);font-size:11px}}
</style></head><body><main>
<h1>Agent run ledger</h1>
<p class="sub">Synthetic fixture data · amounts are decimal strings, unknown prices are never guessed.</p>
<div class="cards">
  <div class="card"><span>Runs</span><b>{len(summary['runs'])}</b></div>
  <div class="card"><span>Priced cost ({html.escape(currency)})</span><b>{totals['cost']}</b></div>
  <div class="card"><span>Fees ({html.escape(currency)})</span><b>{totals['fees']}</b></div>
  <div class="card"><span>Unknown-price calls</span><b class="{'warn' if totals['unknown_calls'] else ''}">{totals['unknown_calls']}</b></div>
  <div class="card"><span>Input / output tokens</span><b>{totals['input_tokens']:,} / {totals['output_tokens']:,}</b></div>
  <div class="card"><span>Events</span><b>{totals['events']}</b></div>
</div>
<table><thead><tr><th>Run</th><th>Actor</th><th>Task</th><th>Calls</th><th>In</th><th>Out</th><th>Cost</th><th>Unknown</th><th>Status</th><th>Review</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<ul class="timeline">{timeline}</ul>
<footer>Generated by run-ledger. Hash chain verifies storage integrity, not the truth of the recorded events.</footer>
</main></body></html>"""
