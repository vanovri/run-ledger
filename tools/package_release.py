"""Create a deterministic release ZIP and checksum manifest, then verify both."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
ZIP_PATH = ROOT / "dist" / f"run-ledger-v{VERSION}.zip"
SUMS_PATH = ROOT / "dist" / f"SHA256SUMS-v{VERSION}.txt"
FIXED = (2026, 10, 19, 0, 0, 0)
FILES = [
    ".gitattributes", ".gitignore", "LICENSE", "README.md", "pyproject.toml",
    "fixtures/prices.json", "fixtures/runs.jsonl",
    "runledger/__init__.py", "runledger/cli.py", "runledger/ingest.py",
    "runledger/money.py", "runledger/redact.py", "runledger/report.py", "runledger/store.py",
    "tests/test_runledger.py", "tests/test_audit_regressions.py", "docs/AUDIT.md", ".github/workflows/verify.yml", "tools/package_release.py", "docs/preview.png",
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> dict:
    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("missing: " + ", ".join(missing))
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(FILES):
            info = zipfile.ZipInfo(name, date_time=FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (ROOT / name).read_bytes())
    checksums = {name: sha((ROOT / name).read_bytes()) for name in FILES}
    SUMS_PATH.write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())), encoding="utf-8", newline="\n")
    problems = []
    with zipfile.ZipFile(ZIP_PATH) as archive:
        if sorted(archive.namelist()) != sorted(FILES):
            problems.append("entry list differs")
        if archive.testzip() is not None:
            problems.append("crc failure")
        for name in archive.namelist():
            if sha(archive.read(name)) != checksums[name]:
                problems.append(f"content differs: {name}")
    return {
        "zip": str(ZIP_PATH.relative_to(ROOT)), "bytes": ZIP_PATH.stat().st_size,
        "sha256": sha(ZIP_PATH.read_bytes()), "files": len(FILES),
        "verified": not problems, "problems": problems,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
