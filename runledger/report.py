"""Offline currency-separated reports and a redacted review timeline."""
import html
import json


def format_json(summary):
    return json.dumps(summary, indent=2, allow_nan=False)


def amounts_text(amounts):
    return '; '.join(f"{currency}: priced {row['priced_subtotal']}, fees {row['known_fees']}, "
                     f"total {row['total'] if row['total'] is not None else 'incomplete'}, "
                     f"unknown calls {row['unknown_calls']}, unknown fees {row['unknown_fees']}"
                     for currency, row in amounts.items()) or 'No monetary events'


def format_text(summary, currency=None):
    lines = [f"run ledger: {len(summary['runs'])} runs, {summary['totals']['events']} events",
             amounts_text(summary['totals']['amounts']),
             f"unknown-price calls: {summary['totals']['unknown_calls']}",
             f"Recorded human minutes: {summary['totals']['human_minutes']} (not inferred)"]
    for run in summary['runs']:
        lines.extend([f"{run['run_id']} [{run['status'] or 'open'}] {run['task'] or ''}",
                      '  ' + amounts_text(run['amounts'])])
    return '\n'.join(lines)


def format_html(summary, currency=None):
    esc = lambda value: html.escape(str(value))
    rows = ''.join(f"<tr><td>{esc(r['run_id'])}</td><td>{esc((r['actor'] or {}).get('name', 'Unattributed'))}</td>"
                   f"<td>{esc(r['task'] or '')}</td><td>{r['calls']}</td><td>{esc(amounts_text(r['amounts']))}</td>"
                   f"<td>{esc(r['status'] or 'open')}</td></tr>" for r in summary['runs'])
    timeline = ''.join(f"<li><small>#{row['seq']} {esc(row['at'])} | {esc(row['run_id'])}</small>"
                       f"<h3>{esc(row['type'])} · {esc((row['actor'] or {}).get('name', 'Unattributed'))}</h3>"
                       f"<p>{esc(row['text'])}</p><b>{esc(row['decision'] or '')}</b></li>" for row in summary['timeline'])
    return f'''<!DOCTYPE html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent run ledger</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#0b1118;color:#e8f1f8;font:15px/1.6 system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:32px 20px}}h1{{font-size:34px;margin:8px 0}}small{{color:#91a9bb}}
.summary,li{{padding:18px;background:#14202c;border:1px solid #304354;border-radius:10px;margin:14px 0}}
.summary{{color:#91efe0}}.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:650px}}
th,td{{text-align:left;padding:12px;border-bottom:1px solid #304354;vertical-align:top}}ul{{padding:0;list-style:none}}
h3,p{{margin:4px 0}}p,td{{overflow-wrap:anywhere}}footer{{color:#91a9bb;margin:28px 0}}
</style><main><small>LOCAL WORKBENCH / DECIMAL ACCOUNTING</small><h1>Agent run ledger</h1>
<p>Imported records. Included examples are synthetic. Currency totals remain separate.</p>
<div class="summary">{esc(amounts_text(summary['totals']['amounts']))}<br>
Recorded human minutes: {esc(summary['totals']['human_minutes'])}. Never inferred from elapsed time.</div>
<div class="table"><table><thead><tr><th>Run</th><th>Actor</th><th>Task</th><th>Calls</th><th>Amounts</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table></div><h2>Diary and review timeline</h2><ul>{timeline}</ul>
<footer>Hash chain detects edits relative to the stored chain. It is not a signature, external attestation or proof of event truth.
Legacy rows protect payload only. Redaction uses patterns and requires review before sharing.</footer></main></html>'''
