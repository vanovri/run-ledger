import json
from decimal import Decimal

import pytest

from runledger.ingest import LogError, export_summary, ingest_file
from runledger.money import MoneyError, PriceTable
from runledger.store import connect, verify_chain


def table(currency='USD'):
    return PriceTable.load({'schema': 'PRICE_TABLE_V1', 'version': 'synthetic-audit-v1',
                            'currency': currency, 'models': {'tiny': {
                                'input_per_million': '0.1', 'output_per_million': '0.1'}}})


def write(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    return path


def event(kind='llm_call', **values):
    return {'type': kind, 'run_id': 'synthetic', 'at': '2026-10-19T00:00:00Z', **values}


def test_sub_micro_costs_round_only_after_aggregation(tmp_path):
    rows = [event(model='tiny', input_tokens=1, output_tokens=0, at=f'2026-10-19T00:00:{i:02}Z') for i in range(10)]
    db = tmp_path / 'ledger.db'
    ingest_file(write(tmp_path, 'small.jsonl', rows), db, table())
    assert export_summary(db)['totals']['amounts']['USD']['total'] == '0.000001'


def test_currency_and_unknown_fees_never_produce_fake_total(tmp_path):
    db = tmp_path / 'ledger.db'
    ingest_file(write(tmp_path, 'usd.jsonl', [event(model='tiny', input_tokens=1_000_000, output_tokens=0)]), db, table())
    ingest_file(write(tmp_path, 'eur.jsonl', [event('fee', amount='3', currency='EUR')]), db, table())
    ingest_file(write(tmp_path, 'unknown.jsonl', [event('fee', amount=None, currency='USD')]), db, table())
    result = export_summary(db)['totals']['amounts']
    assert result['EUR']['total'] == '3.000000'
    assert result['USD']['total'] is None
    assert result['USD']['priced_subtotal'] == '0.100000'
    assert result['USD']['unknown_fees'] == 1


def test_nested_metadata_is_scrubbed_and_actor_required(tmp_path):
    db = tmp_path / 'ledger.db'
    row = event('run_start', actor={'id': 'test', 'name': 'private@example.com', 'role': 'maintainer'},
                metadata={'nested': [{'api_key': 'private-short-value', 'path': '/home/someone/test'}]}, task='safe')
    ingest_file(write(tmp_path, 'redacted.jsonl', [row]), db, table())
    assert b'private@example.com' not in db.read_bytes()
    assert b'private-short-value' not in db.read_bytes()
    assert b'/home/someone' not in db.read_bytes()
    with pytest.raises(LogError, match='actor'):
        ingest_file(write(tmp_path, 'diary.jsonl', [event('diary', text='hello')]), db, table())


def test_ingestion_is_atomic_and_chain_protects_envelope(tmp_path):
    db = tmp_path / 'ledger.db'
    rows = [event(model='tiny', input_tokens=1, output_tokens=0), event('diary', text='missing actor')]
    with pytest.raises(LogError):
        ingest_file(write(tmp_path, 'bad.jsonl', rows), db, table())
    assert export_summary(db)['totals']['events'] == 0
    ingest_file(write(tmp_path, 'good.jsonl', rows[:1]), db, table())
    connection = connect(str(db))
    connection.execute("UPDATE events SET run_id='changed'")
    connection.commit()
    assert not verify_chain(connection)['ok']
    connection.close()
    with pytest.raises(LogError, match='integrity'):
        export_summary(db)


def test_explicit_human_minutes_are_not_elapsed_time(tmp_path):
    db = tmp_path / 'ledger.db'
    ingest_file(write(tmp_path, 'time.jsonl', [event('human_time', minutes='12.5',
                actor={'id': 'person', 'name': 'Reviewer', 'role': 'reviewer'})]), db, table())
    assert export_summary(db)['totals']['human_minutes'] == '12.5'
    with pytest.raises(MoneyError):
        table().quote('tiny', 1, 0, 2)


def test_timezone_and_currency_validation(tmp_path):
    with pytest.raises(MoneyError, match='currency'):
        table('<x>')
    with pytest.raises(LogError, match='timezone'):
        ingest_file(write(tmp_path, 'naive.jsonl', [event(model='tiny', input_tokens=0, output_tokens=0,
                    at='2026-10-19T00:00:00')]), tmp_path / 'ledger.db', table())
