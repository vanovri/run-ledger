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
    return connection


def last_hash(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    return row["hash"] if row else GENESIS


def append(connection: sqlite3.Connection, *, run_id: str, type_: str, at: str, actor: dict | None, payload: dict) -> dict:
    payload_text = canonical(payload)
    prev = last_hash(connection)
    entry_hash = digest(prev, payload_text)
    cursor = connection.execute(
        "INSERT INTO events(run_id, type, at, actor_id, actor_role, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, type_, at, (actor or {}).get("id"), (actor or {}).get("role"), payload_text, prev, entry_hash),
    )
    connection.commit()
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
        expected = digest(row["prev_hash"], row["payload"])
        if expected != row["hash"]:
            problems.append(f"seq {row['seq']}: hash mismatch")
        try:
            json.loads(row["payload"])
        except json.JSONDecodeError:
            problems.append(f"seq {row['seq']}: payload is not JSON")
        previous = row["hash"]
    return {"ok": not problems and count > 0, "events": count, "problems": problems}
