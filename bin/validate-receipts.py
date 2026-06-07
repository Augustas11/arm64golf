#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.attest import verify_receipt
from harness.loop import validate_attestation


COMPARE_FIELDS = {
    "candidate_hash",
    "score",
    "model_id",
    "provider_id",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def validate_receipt_for_row(row: dict[str, Any], receipts_dir: Path) -> list[str]:
    errors: list[str] = []
    candidate_hash = str(row.get("candidate_hash", ""))
    if not candidate_hash:
        return ["leaderboard row is missing candidate_hash"]

    receipt_path = receipts_dir / f"{candidate_hash[:12]}.json"
    if not receipt_path.exists():
        return [f"missing receipt file for {candidate_hash[:12]}: {receipt_path}"]

    try:
        verify_receipt(receipt_path)
    except Exception as exc:
        errors.append(f"{receipt_path} signature verification failed: {exc}")
        return errors

    try:
        envelope = load_json(receipt_path)
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return [f"{receipt_path} payload must be an object"]

    try:
        validate_attestation(payload.get("attestation"))
    except ValueError as exc:
        errors.append(f"{receipt_path} attestation invalid: {exc}")

    for field in COMPARE_FIELDS:
        if payload.get(field) != row.get(field):
            errors.append(f"{receipt_path} payload {field}={payload.get(field)!r} does not match leaderboard {row.get(field)!r}")
    if envelope.get("signature") != row.get("receipt_signature"):
        errors.append(f"{receipt_path} signature does not match leaderboard receipt_signature")
    return errors


def validate(leaderboard_path: Path, receipts_dir: Path) -> list[str]:
    errors: list[str] = []
    try:
        payload = load_json(leaderboard_path)
    except ValueError as exc:
        return [str(exc)]

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ["leaderboard rows must be a list"]
    if not rows:
        return ["leaderboard rows must include at least one verified candidate"]

    for row in rows:
        if not isinstance(row, dict):
            errors.append("leaderboard row must be an object")
            continue
        errors.extend(validate_receipt_for_row(row, receipts_dir))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate leaderboard rows against signed receipt files.")
    parser.add_argument("--leaderboard", type=Path, default=REPO_ROOT / "web" / "public" / "leaderboard.json")
    parser.add_argument("--receipts-dir", type=Path, default=REPO_ROOT / "receipts")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args()

    errors = validate(args.leaderboard, args.receipts_dir)
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
