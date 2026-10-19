"""Command line interface for the run ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import LogError, export_summary, ingest_file
from .money import MoneyError, PriceTable
from .report import format_html, format_json, format_text
from .store import connect, verify_chain


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runledger", description="Decimal agent run ledger and diary.")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="append JSONL run logs to a ledger")
    ingest.add_argument("logs", nargs="+", type=Path)
    ingest.add_argument("--db", required=True, type=Path)
    ingest.add_argument("--prices", required=True, type=Path)

    report = sub.add_parser("report", help="summarise a ledger")
    report.add_argument("--db", required=True, type=Path)
    report.add_argument("--format", choices=["text", "json", "html"], default="text")
    report.add_argument("--out", type=Path)

    verify = sub.add_parser("verify", help="verify the hash chain")
    verify.add_argument("--db", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "ingest":
            prices = PriceTable.load(json.loads(arguments.prices.read_text(encoding="utf-8")))
            stats = []
            for log in arguments.logs:
                stats.append({"file": str(log), **ingest_file(log, arguments.db, prices)})
            print(json.dumps({"prices_version": prices.version, "currency": prices.currency, "ingested": stats}, indent=2))
            return 0
        if arguments.command == "report":
            summary = export_summary(arguments.db)
            if arguments.format == "json":
                text = format_json(summary)
            elif arguments.format == "html":
                text = format_html(summary)
            else:
                text = format_text(summary)
            if arguments.out:
                arguments.out.parent.mkdir(parents=True, exist_ok=True)
                arguments.out.write_text(text + "\n", encoding="utf-8", newline="\n")
                print(f"wrote {arguments.out}")
            else:
                print(text)
            return 0
        if arguments.command == "verify":
            connection = connect(str(arguments.db))
            try:
                result = verify_chain(connection)
            finally:
                connection.close()
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
    except (LogError, MoneyError, OSError, json.JSONDecodeError) as exc:
        print(f"runledger: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
