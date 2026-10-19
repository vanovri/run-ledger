"""Append-only event store with a SHA-256 hash chain."""
from __future__ import annotations

import hashlib
import json
import sqlite3

GENESIS = "0" * 64
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    at TEXT NOT NULL,
    actor_id TEXT,
    actor_role TEXT,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS events_type ON events(type);
"""


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(prev_hash: str, payload_text: str) -> str:
    return hashlib.sha256(f"{prev_hash}\n{payload_text}".encode("utf-8")).hexdigest()


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    if 'hash_version' not in {row['name'] for row in connection.execute('PRAGMA table_info(events)')}:
        connection.execute('ALTER TABLE events ADD COLUMN hash_version INTEGER NOT NULL DEFAULT 1')
        connection.commit()
    return connection


def last_hash(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    return row["hash"] if row else GENESIS


def append(connection: sqlite3.Connection, *, run_id: str, type_: str, at: str, actor: dict | None, payload: dict) -> dict:
    payload_text = canonical(payload)
    prev = last_hash(connection)
    envelope = canonical({'run_id': run_id, 'type': type_, 'at': at,
                          'actor_id': (actor or {}).get('id'), 'actor_role': (actor or {}).get('role'), 'payload': payload})
    entry_hash = digest(prev, envelope)
    cursor = connection.execute(
        "INSERT INTO events(run_id, type, at, actor_id, actor_role, payload, prev_hash, hash, hash_version) VALUES (?,?,?,?,?,?,?,?,2)",
        (run_id, type_, at, (actor or {}).get("id"), (actor or {}).get("role"), payload_text, prev, entry_hash),
    )
    return {"seq": cursor.lastrowid, "hash": entry_hash, "prev_hash": prev}


def existing(connection: sqlite3.Connection, run_id: str, type_: str, at: str, payload: dict) -> bool:
    text = canonical(payload)
    row = connection.execute(
        "SELECT 1 FROM events WHERE run_id=? AND type=? AND at=? AND payload=? LIMIT 1",
        (run_id, type_, at, text),
    ).fetchone()
    return row is not None


def verify_chain(connection: sqlite3.Connection) -> dict:
    previous = GENESIS
    problems = []
    count = 0
    for row in connection.execute("SELECT * FROM events ORDER BY seq"):
        count += 1
        if row["prev_hash"] != previous:
            problems.append(f"seq {row['seq']}: prev_hash mismatch")
        text = row['payload']
        if row['hash_version'] == 2:
            try:
                text = canonical({**{key: row[key] for key in ['run_id', 'type', 'at', 'actor_id', 'actor_role']},
                                  'payload': json.loads(text)})
            except json.JSONDecodeError:
                pass
        expected = digest(row["prev_hash"], text)
        if expected != row["hash"]:
            problems.append(f"seq {row['seq']}: hash mismatch")
        try:
            json.loads(row["payload"])
        except json.JSONDecodeError:
            problems.append(f"seq {row['seq']}: payload is not JSON")
        previous = row["hash"]
    return {"ok": not problems and count > 0, "events": count, "problems": problems}
