# Run ledger

An append-only ledger for agent runs: **decimal** cost accounting, a redacted diary, actor attribution and a review timeline — in one SQLite file and one self-contained HTML report.

```sh
runledger ingest fixtures/runs.jsonl --db ledger.db --prices fixtures/prices.json
runledger report --db ledger.db --format html --out ledger.html
runledger verify --db ledger.db
```

![Summary](docs/preview.png)

The sample data is **synthetic**. `example-fast` and `example-deep` are invented models with invented prices; no vendor price list, invoice or customer data is included.

## Why

Agent runs produce two things that are usually kept badly: **money** and **judgement**.

- Costs are summed as floats, so invoices drift by cents and nobody can explain which call caused it.
- A model that has no price is silently costed at zero.
- Diary notes contain tokens, emails and local paths, so they cannot be shared or committed.
- Reviews live in chat, detached from the run they approved.

This ledger keeps those in one append-only place with explicit rules.

## What is guaranteed

| Property | Rule |
| --- | --- |
| Money | `Decimal` only. Floats are rejected at the boundary. Costs quantise to `0.000001` with `ROUND_HALF_UP`. |
| Unknown prices | A model missing from the price table is stored as `unknown_price` with no amount. It is counted separately and never treated as zero. |
| Price versions | Every call records the price table `version` and `currency` used at ingest time. |
| Redaction | Keys, GitHub/AWS tokens, bearer tokens, emails, `C:\Users\…` and `/home/…` are replaced before storage. Counts are kept. |
| Attribution | `run_start`, `diary` and `review` require an actor with `id`, `name` and one of `maintainer`, `reviewer`, `agent`, `observer`. |
| Integrity | Every event is chained: `hash = SHA-256(prev_hash + canonical_payload)`. `verify` reports the first broken link. |
| Idempotency | Re-ingesting the same file appends nothing; duplicates are counted. |

The hash chain proves the **stored sequence was not edited after the fact**. It does not prove the events themselves are true.

## Log format (JSONL)

One JSON object per line. Unknown fields are rejected so typos fail loudly.

```json
{"type":"run_start","run_id":"run-001","at":"2026-10-18T09:00:00Z","actor":{"id":"ardhya","name":"Ardhya","role":"maintainer"},"task":"Add rounding test","metadata":{"branch":"feat/rounding"}}
{"type":"llm_call","run_id":"run-001","at":"2026-10-18T09:00:05Z","model":"example-fast","input_tokens":1200,"output_tokens":400,"cached_tokens":200}
{"type":"tool_call","run_id":"run-001","at":"2026-10-18T09:01:00Z","tool":"pytest","status":"ok","duration_ms":842}
{"type":"diary","run_id":"run-001","at":"2026-10-18T09:02:00Z","actor":{"id":"ardhya","name":"Ardhya","role":"maintainer"},"text":"Checked auth with sk-…"}
{"type":"review","run_id":"run-001","at":"2026-10-18T09:03:00Z","actor":{"id":"reviewer-1","name":"Reviewer","role":"reviewer"},"decision":"approved","note":"Ship it"}
{"type":"fee","run_id":"run-001","at":"2026-10-18T09:04:00Z","amount":"0.42","currency":"USD","source":"invoice","note":"CI minutes"}
{"type":"run_end","run_id":"run-001","at":"2026-10-18T09:05:00Z","status":"completed"}
```

Decisions: `approved`, `rejected`, `changes_requested`. End states: `completed`, `failed`, `aborted`.

## Price table

```json
{
  "schema": "PRICE_TABLE_V1",
  "version": "2026-10-example",
  "currency": "USD",
  "models": {
    "example-fast": { "input_per_million": "1.50", "output_per_million": "6.00", "cached_input_per_million": "0.30" }
  }
}
```

Rates are strings. A model without an entry produces `unknown_price`; the report shows how many calls were unpriced and computes a priced subtotal only.

## Report

`--format text` for terminals, `json` for tooling, `html` for a shareable dashboard. The HTML is one file with no scripts and no external assets; text is escaped.

## CLI

```
runledger ingest LOG... --db DB --prices PRICES
runledger report --db DB [--format text|json|html] [--out FILE]
runledger verify --db DB
```

Exit codes: `0` success, `1` broken chain, `2` invalid input.

## Verification

- 13 tests cover decimal rounding, cached-token pricing, unknown models, float rejection, redaction, actor roles, unknown fields, idempotency, tamper detection, HTML escaping and empty-ledger verification.
- Fixture totals: run-001 = `0.055260 USD`, run-002 = `0.000000 USD` with one unknown-price call; fee `0.420000 USD`.
- `verify` returns `ok: true` on an untouched ledger and reports a hash mismatch after a row is edited.

## Limits

- Single-writer SQLite; no concurrent ingest coordination beyond SQLite's own locking.
- Redaction is pattern-based. It reduces accidental leaks; it is not a data-loss-prevention product.
- The hash chain is not a signature: someone who can rewrite every row can rebuild the chain.
- No budget enforcement or alerts; this is a ledger, not a billing system.
- Timestamps are normalised to UTC but not validated against event order inside a run.
- Synthetic prices and model names only; no vendor price feed is included.

## Development

```sh
python -m pytest -q
python -m runledger.cli ingest fixtures/runs.jsonl --db /tmp/ledger.db --prices fixtures/prices.json
```

MIT — see [LICENSE](LICENSE).
