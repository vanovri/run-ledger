"""Tests for decimal accounting, redaction, ingestion, chain integrity and reports."""
from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from runledger.ingest import LogError, export_summary, ingest_file
from runledger.money import MoneyError, PriceTable, cost, rate, tokens
from runledger.redact import redact
from runledger.report import format_html, format_text
from runledger.store import append, connect, verify_chain

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


@pytest.fixture()
def prices() -> PriceTable:
    return PriceTable.load(json.loads((FIXTURES / "prices.json").read_text(encoding="utf-8")))


@pytest.fixture()
def db(tmp_path) -> Path:
    return tmp_path / "ledger.db"


def test_cost_uses_decimal_quantisation():
    assert cost(1_000_000, Decimal("1.50")) == Decimal("1.500000")
    assert cost(1, Decimal("1.50")) == Decimal("0.000002")  # 0.0000015 rounds half up
    assert cost(0, Decimal("9.00")) == Decimal("0.000000")


def test_quote_separates_cached_tokens(prices):
    known = prices.quote("example-fast", 1200, 400, 200)
    expected = Decimal("0.001500") + Decimal("0.000060") + Decimal("0.002400")
    assert known == expected.quantize(Decimal("0.000001"))
    assert prices.quote("mystery-model", 10, 10) is None


def test_floats_are_rejected(prices):
    with pytest.raises(MoneyError, match="floats"):
        rate(1.5, "rate")
    with pytest.raises(MoneyError, match="integer"):
        tokens(1.5, "tokens")
    with pytest.raises(MoneyError, match="negative"):
        tokens(-1, "tokens")


def test_price_table_version_and_currency_are_required():
    with pytest.raises(MoneyError, match="schema"):
        PriceTable.load({"version": "v", "models": {}})
    with pytest.raises(MoneyError, match="version"):
        PriceTable.load({"schema": "PRICE_TABLE_V1", "models": {}})
    with pytest.raises(MoneyError, match="currency"):
        PriceTable.load({"schema": "PRICE_TABLE_V1", "version": "v", "currency": "US", "models": {}})


def test_redaction_covers_keys_emails_and_paths():
    result = redact("sk-test1234567890abcdef ghp_abcdefghijklmnopqrstuvwxyz012345 ardhya@example.com C:\\Users\\ardhya\\a.txt")
    assert "sk-test" not in result.text
    assert "ghp_" not in result.text
    assert "ardhya@example.com" not in result.text
    assert "C:\\Users\\ardhya" not in result.text
    assert result.total == 4
    assert result.counts["api_key"] == 1


def test_ingest_builds_summary(db, prices):
    stats = ingest_file(FIXTURES / "runs.jsonl", db, prices)
    assert stats["appended"] == 11
    assert stats["unknown_price"] == 1
    assert stats["redactions"]["api_key"] == 1
    summary = export_summary(db)
    assert len(summary["runs"]) == 2
    first = next(run for run in summary["runs"] if run["run_id"] == "run-001")
    assert first["calls"] == 2
    assert first["unknown_calls"] == 0
    assert Decimal(first["cost"]) == Decimal("0.055260")
    second = next(run for run in summary["runs"] if run["run_id"] == "run-002")
    assert second["unknown_calls"] == 1
    assert second["cost"] == "0.000000"
    assert summary["totals"]["unknown_calls"] == 1
    assert summary["totals"]["fees"] == "0.420000"


def test_ingest_is_idempotent(db, prices):
    first = ingest_file(FIXTURES / "runs.jsonl", db, prices)
    second = ingest_file(FIXTURES / "runs.jsonl", db, prices)
    assert first["appended"] == 11
    assert second["appended"] == 0
    assert second["duplicates"] == 11


def test_chain_verifies_and_detects_tampering(db, prices):
    ingest_file(FIXTURES / "runs.jsonl", db, prices)
    connection = connect(str(db))
    try:
        assert verify_chain(connection)["ok"] is True
        connection.execute("UPDATE events SET payload = replace(payload, 'example-fast', 'example-deep') WHERE seq = 2")
        connection.commit()
        result = verify_chain(connection)
        assert result["ok"] is False
        assert any("hash mismatch" in problem for problem in result["problems"])
    finally:
        connection.close()


def test_unknown_fields_and_bad_values_are_rejected(db, prices, tmp_path):
    bad = tmp_path / "bad.jsonl"
    cases = [
        {"type": "llm_call", "run_id": "r", "at": "2026-10-18T00:00:00Z", "model": "example-fast", "input_tokens": 1, "output_tokens": 1, "oops": 1},
        {"type": "llm_call", "run_id": "r", "at": "2026-10-18T00:00:00Z", "model": "example-fast", "input_tokens": -1, "output_tokens": 1},
        {"type": "llm_call", "run_id": "r", "at": "2026-10-18T00:00:00Z", "model": "example-fast", "input_tokens": 1, "output_tokens": 1, "cached_tokens": 2},
        {"type": "diary", "run_id": "r", "at": "not-a-time", "text": "x"},
        {"type": "review", "run_id": "r", "at": "2026-10-18T00:00:00Z", "actor": {"id": "a", "name": "A", "role": "reviewer"}, "decision": "maybe"},
    ]
    for case in cases:
        bad.write_text(json.dumps(case) + "\n", encoding="utf-8")
        with pytest.raises(LogError):
            ingest_file(bad, db, prices)


def test_actor_role_is_validated(db, prices, tmp_path):
    bad = tmp_path / "actor.jsonl"
    bad.write_text(json.dumps({"type": "run_start", "run_id": "r", "at": "2026-10-18T00:00:00Z", "actor": {"id": "a", "name": "A", "role": "admin"}, "task": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(LogError, match="role"):
        ingest_file(bad, db, prices)


def test_text_and_html_reports_render(db, prices):
    ingest_file(FIXTURES / "runs.jsonl", db, prices)
    summary = export_summary(db)
    text = format_text(summary)
    assert "run-001" in text and "unknown-price calls: 1" in text
    page = format_html(summary)
    assert "<!DOCTYPE html>" in page
    assert "Agent run ledger" in page
    assert "0.055260" in page
    assert "sk-test" not in page


def test_html_escapes_actor_names(db, prices, tmp_path):
    log = tmp_path / "x.jsonl"
    log.write_text(json.dumps({"type": "run_start", "run_id": "x", "at": "2026-10-18T00:00:00Z", "actor": {"id": "a", "name": "<script>", "role": "agent"}, "task": "t"}) + "\n", encoding="utf-8")
    ingest_file(log, db, prices)
    assert "<script>" not in format_html(export_summary(db))


def test_empty_ledger_verification_is_not_ok(db):
    connection = connect(str(db))
    try:
        assert verify_chain(connection)["ok"] is False
    finally:
        connection.close()
