#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.attest import sign_receipt
from harness.loop import HARNESS_VERSION, legacy_v1_unknown_attestation, reference_attestation, seed_attestation


SEED_BASELINE_CANDIDATE_HASH = "726c3e4c49b564d0d9ed5613da861ba72c6107951a48939bb932a1d338076040"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def require_private_key_permissions(private_key: Path) -> None:
    if not private_key.exists():
        return
    mode = private_key.stat().st_mode & 0o777
    if mode != 0o600:
        raise PermissionError(f"{private_key} must have mode 0600; got {mode:04o}")


def known_candidate_hashes(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    db = sqlite3.connect(db_path)
    try:
        return {str(row[0]) for row in db.execute("SELECT candidate_hash FROM candidates")}
    finally:
        db.close()


def sync_receipt_index(db_path: Path, receipt_path: Path) -> None:
    if not db_path.exists():
        return
    envelope = load_json(receipt_path)
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    candidate_hash = str(payload.get("candidate_hash", ""))
    signature = str(envelope.get("signature", ""))
    if not candidate_hash or not signature:
        raise ValueError("receipt candidate_hash and signature must be present")
    db = sqlite3.connect(db_path)
    try:
        db.execute(
            """
            INSERT INTO receipts (candidate_hash, receipt_path, signature)
            VALUES (?, ?, ?)
            ON CONFLICT(candidate_hash) DO UPDATE SET
                receipt_path = excluded.receipt_path,
                signature = excluded.signature
            """,
            (candidate_hash, str(receipt_path), signature),
        )
        db.commit()
    finally:
        db.close()


def legacy_attestation(candidate_hash: str, known_hashes: set[str]) -> dict[str, object]:
    if candidate_hash not in known_hashes and known_hashes:
        raise ValueError(f"{candidate_hash[:12]} is not present in candidate database")
    if candidate_hash == SEED_BASELINE_CANDIDATE_HASH:
        return seed_attestation()
    return legacy_v1_unknown_attestation()


def normalized_attestation(payload: dict[str, Any], known_hashes: set[str]) -> dict[str, object]:
    candidate_hash = str(payload.get("candidate_hash", ""))
    if not candidate_hash:
        raise ValueError("payload candidate_hash must be present")

    attestation = payload.get("attestation")
    if not isinstance(attestation, dict):
        return legacy_attestation(candidate_hash, known_hashes)

    kind = attestation.get("kind")
    details = attestation.get("details")
    if isinstance(kind, str) and isinstance(details, dict):
        if kind in {"seed-baseline", "legacy-v1-unknown"}:
            return legacy_attestation(candidate_hash, known_hashes)
        return {"kind": kind, "details": details}

    if kind == "reference-harness":
        return reference_attestation(
            str(attestation.get("template_name")),
            float(attestation.get("temperature")),
            float(attestation.get("top_p")),
            int(attestation.get("n")),
        )
    return legacy_attestation(candidate_hash, known_hashes)


def upgrade_receipt(path: Path, private_key: Path, public_key: Path, receipts_dir: Path, known_hashes: set[str]) -> str:
    envelope = load_json(path)
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    upgraded = dict(payload)
    upgraded["attestation"] = normalized_attestation(payload, known_hashes)
    upgraded["harness_version"] = HARNESS_VERSION
    if upgraded == payload:
        return "kept_v2"

    sign_receipt(upgraded, private_key, public_key, receipts_dir)
    return "upgraded_to_v2"


def upgrade_receipts(
    receipts_dir: Path,
    private_key: Path,
    public_key: Path,
    db_path: Path = REPO_ROOT / "data" / "arm64golf.sqlite",
) -> list[tuple[str, str]]:
    require_private_key_permissions(private_key)
    known_hashes = known_candidate_hashes(db_path)
    results: list[tuple[str, str]] = []
    for path in sorted(receipts_dir.glob("*.json")):
        short_hash = path.stem
        try:
            status = upgrade_receipt(path, private_key, public_key, receipts_dir, known_hashes)
            sync_receipt_index(db_path, path)
        except Exception as exc:  # noqa: BLE001 - continue through all receipt files.
            status = f"error: {exc}"
        results.append((short_hash, status))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Upgrade v1 seed-baseline receipts to receipt payload v2.")
    parser.add_argument("--receipts-dir", type=Path, default=REPO_ROOT / "receipts")
    parser.add_argument("--private-key", type=Path, default=REPO_ROOT / "data" / "sign.key")
    parser.add_argument("--public-key", type=Path, default=REPO_ROOT / "receipts" / "PUBKEY")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "arm64golf.sqlite")
    args = parser.parse_args()

    results = upgrade_receipts(args.receipts_dir, args.private_key, args.public_key, args.db)
    for short_hash, status in results:
        print(f"{short_hash}: {status}")
    return 1 if any(status.startswith("error:") for _, status in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
