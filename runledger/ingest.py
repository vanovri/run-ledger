"""Validate synthetic run logs, redact them, and append to the ledger."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from decimal import Decimal

from .money import MoneyError, PriceTable, as_decimal, fmt, tokens
from .redact import redact
from .store import append, connect, existing

RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
TYPES = {"run_start", "llm_call", "tool_call", "diary", "review", "run_end", "fee"}
ALLOWED = {
    "run_start": {"run_id", "type", "at", "actor", "task", "metadata"},
    "llm_call": {"run_id", "type", "at", "model", "input_tokens", "output_tokens", "cached_tokens"},
    "tool_call": {"run_id", "type", "at", "tool", "status", "duration_ms"},
    "diary": {"run_id", "type", "at", "actor", "text"},
    "review": {"run_id", "type", "at", "actor", "decision", "note"},
    "run_end": {"run_id", "type", "at", "status"},
    "fee": {"run_id", "type", "at", "amount", "currency", "source", "note"},
}


class LogError(ValueError):
    pass


def parse_time(value) -> str:
    if not isinstance(value, str):
        raise LogError("'at' must be an ISO-8601 string")
    text = value.strip()
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LogError(f"invalid timestamp: {value}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_actor(value) -> dict:
    if not isinstance(value, dict):
        raise LogError("actor must be an object with id, name and role")
    actor_id = value.get("id")
    name = value.get("name")
    role = value.get("role")
    if not isinstance(actor_id, str) or not RUN_ID.match(actor_id):
        raise LogError("actor.id must be 1-64 letters, digits, dot, dash or underscore")
    if not isinstance(name, str) or not (1 <= len(name) <= 80):
        raise LogError("actor.name must be 1-80 characters")
    if role not in {"maintainer", "reviewer", "agent", "observer"}:
        raise LogError("actor.role must be maintainer, reviewer, agent or observer")
    return {"id": actor_id, "name": name, "role": role}


def redact_text(text, label: str, limit: int = 4000) -> tuple[str, dict]:
    if not isinstance(text, str):
        raise LogError(f"{label} must be a string")
    if len(text) > limit:
        raise LogError(f"{label} exceeds {limit} characters")
    result = redact(text)
    return result.text, result.counts


def normalize(record: dict, prices: PriceTable) -> tuple[str, str, dict | None, dict, dict]:
    if not isinstance(record, dict):
        raise LogError("each line must be a JSON object")
    type_ = record.get("type")
    if type_ not in TYPES:
        raise LogError(f"unsupported event type: {type_!r}")
    unknown = set(record) - ALLOWED[type_]
    if unknown:
        raise LogError(f"{type_}: unknown fields: {', '.join(sorted(unknown))}")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.match(run_id):
        raise LogError("run_id must be 1-64 letters, digits, dot, dash or underscore")
    at = parse_time(record.get("at"))
    actor = parse_actor(record["actor"]) if "actor" in record else None
    payload: dict = {}
    redactions: dict = {}

    if type_ == "run_start":
        if actor is None:
            raise LogError("run_start requires an actor")
        task, counts = redact_text(record.get("task", ""), "task", 500)
        payload = {"actor": actor, "task": task}
        if "metadata" in record:
            if not isinstance(record["metadata"], dict):
                raise LogError("metadata must be an object")
            payload["metadata"] = record["metadata"]
        redactions = counts
    elif type_ == "llm_call":
        model = record.get("model")
        if not isinstance(model, str) or not model:
            raise LogError("llm_call requires a model")
        in_tokens = tokens(record.get("input_tokens"), "input_tokens")
        out_tokens = tokens(record.get("output_tokens"), "output_tokens")
        cached = tokens(record.get("cached_tokens", 0), "cached_tokens")
        if cached > in_tokens:
            raise LogError("cached_tokens cannot exceed input_tokens")
        amount = prices.quote(model, in_tokens, out_tokens, cached)
        payload = {
            "model": model,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "cached_tokens": cached,
            "amount": None if amount is None else str(amount),
            "currency": prices.currency,
            "price_version": prices.version,
            "price_status": "unknown_price" if amount is None else "priced",
        }
    elif type_ == "tool_call":
        tool = record.get("tool")
        if not isinstance(tool, str) or not tool:
            raise LogError("tool_call requires a tool name")
        status = record.get("status")
        if status not in {"ok", "error"}:
            raise LogError("tool_call.status must be ok or error")
        duration = record.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise LogError("duration_ms must be a non-negative integer")
        payload = {"tool": tool[:80], "status": status, "duration_ms": duration}
    elif type_ == "diary":
        text, counts = redact_text(record.get("text"), "text")
        payload = {"actor": actor, "text": text, "redactions": counts}
        redactions = counts
    elif type_ == "review":
        if actor is None:
            raise LogError("review requires an actor")
        decision = record.get("decision")
        if decision not in {"approved", "rejected", "changes_requested"}:
            raise LogError("review.decision must be approved, rejected or changes_requested")
        note, counts = redact_text(record.get("note", ""), "note")
        payload = {"actor": actor, "decision": decision, "note": note, "redactions": counts}
        redactions = counts
    elif type_ == "run_end":
        status = record.get("status")
        if status not in {"completed", "failed", "aborted"}:
            raise LogError("run_end.status must be completed, failed or aborted")
        payload = {"status": status}
    elif type_ == "fee":
        try:
            amount = as_decimal(record.get("amount"), "fee.amount")
        except MoneyError as exc:
            raise LogError(str(exc)) from exc
        if amount < 0:
            raise LogError("fee.amount cannot be negative")
        currency = record.get("currency", "USD")
        if not isinstance(currency, str) or len(currency) != 3:
            raise LogError("fee.currency must be a three-letter code")
        source = record.get("source", "invoice")
        if not isinstance(source, str) or not source:
            raise LogError("fee.source must be a non-empty string")
        note, counts = redact_text(record.get("note", ""), "note", 500)
        payload = {
            "amount": str(amount.quantize(Decimal("0.000001"))), "currency": currency,
            "source": source[:80], "note": note,
        }
        redactions = counts
    return run_id, type_, actor, payload, redactions


def ingest_file(path: Path, db_path: Path, prices: PriceTable) -> dict:
    connection = connect(str(db_path))
    stats = {"lines": 0, "appended": 0, "duplicates": 0, "redactions": {}, "unknown_price": 0, "runs": set()}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                stats["lines"] += 1
                try:
                    record = json.loads(line)
                    run_id, type_, actor, payload, redactions = normalize(record, prices)
                except (json.JSONDecodeError, LogError, MoneyError) as exc:
                    raise LogError(f"{path.name}:{number}: {exc}") from exc
                if existing(connection, run_id, type_, parse_time(record["at"]), payload):
                    stats["duplicates"] += 1
                    continue
                append(connection, run_id=run_id, type_=type_, at=parse_time(record["at"]), actor=actor, payload=payload)
                stats["appended"] += 1
                stats["runs"].add(run_id)
                for key, value in redactions.items():
                    stats["redactions"][key] = stats["redactions"].get(key, 0) + value
                if type_ == "llm_call" and payload["price_status"] == "unknown_price":
                    stats["unknown_price"] += 1
    finally:
        connection.close()
    stats["runs"] = sorted(stats["runs"])
    return stats


def export_summary(db_path: Path) -> dict:
    connection = connect(str(db_path))
    try:
        rows = connection.execute("SELECT * FROM events ORDER BY seq").fetchall()
    finally:
        connection.close()
    runs: dict[str, dict] = {}
    timeline = []
    totals = {"cost": 0.0, "fees": 0.0, "unknown_calls": 0, "input_tokens": 0, "output_tokens": 0, "diary": 0, "reviews": 0}
    from decimal import Decimal
    cost_total = Decimal("0")
    fee_total = Decimal("0")
    for row in rows:
        payload = json.loads(row["payload"])
        run = runs.setdefault(row["run_id"], {
            "run_id": row["run_id"], "actor": None, "task": None, "started_at": None,
            "ended_at": None, "status": None, "calls": 0, "input_tokens": 0,
            "output_tokens": 0, "cost": Decimal("0"), "unknown_calls": 0,
            "fees": Decimal("0"), "redactions": {}, "reviews": [], "tools": 0,
        })
        if row["type"] == "run_start":
            run["actor"] = payload.get("actor")
            run["task"] = payload.get("task")
            run["started_at"] = row["at"]
        elif row["type"] == "run_end":
            run["ended_at"] = row["at"]
            run["status"] = payload.get("status")
        elif row["type"] == "llm_call":
            run["calls"] += 1
            run["input_tokens"] += payload["input_tokens"]
            run["output_tokens"] += payload["output_tokens"]
            totals["input_tokens"] += payload["input_tokens"]
            totals["output_tokens"] += payload["output_tokens"]
            if payload["amount"] is None:
                run["unknown_calls"] += 1
                totals["unknown_calls"] += 1
            else:
                value = Decimal(payload["amount"])
                run["cost"] += value
                cost_total += value
        elif row["type"] == "fee":
            value = Decimal(payload["amount"])
            run["fees"] += value
            fee_total += value
        elif row["type"] == "tool_call":
            run["tools"] += 1
        elif row["type"] == "diary":
            totals["diary"] += 1
            for key, value in (payload.get("redactions") or {}).items():
                run["redactions"][key] = run["redactions"].get(key, 0) + value
        elif row["type"] == "review":
            totals["reviews"] += 1
            run["reviews"].append({"at": row["at"], "actor": payload.get("actor"), "decision": payload.get("decision"), "note": payload.get("note")})
        timeline.append({"seq": row["seq"], "run_id": row["run_id"], "type": row["type"], "at": row["at"], "actor": row["actor_id"], "hash": row["hash"][:12]})
    summary = {
        "runs": list(runs.values()),
        "totals": {
            **totals,
            "cost": str(cost_total.quantize(Decimal("0.000001"))),
            "fees": str(fee_total.quantize(Decimal("0.000001"))),
            "events": len(rows),
        },
        "timeline": timeline,
    }
    for run in summary["runs"]:
        run["cost"] = str(run["cost"].quantize(Decimal("0.000001")))
        run["fees"] = str(run["fees"].quantize(Decimal("0.000001")))
    return summary
