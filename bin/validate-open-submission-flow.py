#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.attest import ensure_keypair


def run_json(cmd: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output = result.stdout.strip() or result.stderr.strip()
        raise RuntimeError(f"{Path(cmd[1]).name} failed: {output}")
    return json.loads(result.stdout)


def validate() -> list[str]:
    errors: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="arm64golf-open-submission-") as tmp:
            workdir = Path(tmp)
            receipts = workdir / "receipts"
            data = workdir / "data"
            receipts.mkdir()
            data.mkdir()
            private_key = data / "sign.key"
            public_key = receipts / "PUBKEY"
            ensure_keypair(private_key, public_key)

            assembly = workdir / "example.s"
            attestation = workdir / "example.attestation.json"
            assembly.write_text((REPO_ROOT / "submissions" / "example.s").read_text())
            attestation.write_text((REPO_ROOT / "submissions" / "example.attestation.json").read_text())

            verified = run_json(
                [
                    sys.executable,
                    "bin/verify-candidate.py",
                    "--assembly",
                    str(assembly),
                    "--attestation",
                    str(attestation),
                    "--receipts-dir",
                    str(receipts),
                    "--private-key",
                    str(private_key),
                    "--public-key",
                    str(public_key),
                    "--json",
                ],
                REPO_ROOT,
            )
            if not verified.get("ok"):
                raise RuntimeError(f"verify-candidate failed: {verified.get('errors')}")
            candidate_hash = str(verified["candidate_hash"])
            receipt = receipts / f"{candidate_hash[:12]}.json"
            if not receipt.exists():
                raise RuntimeError("receipt was not written")
            envelope = json.loads(receipt.read_text())
            if envelope.get("payload", {}).get("attestation", {}).get("kind") != "open-submission":
                raise RuntimeError("receipt kind is not open-submission")

            db_path = workdir / "arm64golf.sqlite"
            leaderboard = workdir / "leaderboard.json"
            published = run_json(
                [
                    sys.executable,
                    "bin/publish-open-submission.py",
                    "--receipt",
                    str(receipt),
                    "--assembly",
                    str(assembly),
                    "--db",
                    str(db_path),
                    "--leaderboard-json",
                    str(leaderboard),
                    "--public-key",
                    str(public_key),
                    "--json",
                ],
                REPO_ROOT,
            )
            if not published.get("ok"):
                raise RuntimeError(f"publish-open-submission failed: {published.get('errors')}")

            db = sqlite3.connect(db_path)
            try:
                candidate_count = db.execute("SELECT COUNT(*) FROM candidates WHERE candidate_hash = ?", (candidate_hash,)).fetchone()[0]
                evaluation_count = db.execute("SELECT COUNT(*) FROM evaluations WHERE candidate_hash = ? AND verified = 1", (candidate_hash,)).fetchone()[0]
                receipt_count = db.execute("SELECT COUNT(*) FROM receipts WHERE candidate_hash = ?", (candidate_hash,)).fetchone()[0]
            finally:
                db.close()
            if candidate_count != 1 or evaluation_count != 1 or receipt_count != 1:
                raise RuntimeError("SQLite did not record candidate, evaluation, and receipt rows")

            payload = json.loads(leaderboard.read_text())
            if not any(row.get("candidate_hash") == candidate_hash for row in payload.get("rows", [])):
                raise RuntimeError("leaderboard rows missing published candidate")
            if any(pair.get("attribution_kind") == "open_submission" for pair in payload.get("pairs", [])):
                raise RuntimeError("leaderboard pairs should exclude open_submission entries")

            receipt_check = run_json(
                [
                    sys.executable,
                    "bin/validate-receipts.py",
                    "--leaderboard",
                    str(leaderboard),
                    "--receipts-dir",
                    str(receipts),
                    "--json",
                ],
                REPO_ROOT,
            )
            if not receipt_check.get("ok"):
                raise RuntimeError(f"validate-receipts failed: {receipt_check.get('errors')}")
    except Exception as exc:  # noqa: BLE001 - validation reports every smoke failure as data.
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the open-submission verify and publish flow.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args()

    errors = validate()
    payload = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif errors:
        for error in errors:
            print(error, file=sys.stderr)
    else:
        print("ok")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
