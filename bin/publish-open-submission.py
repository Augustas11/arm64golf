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
from harness.module import load_problem_module
from harness.store import Store


PROBLEM_DIR = REPO_ROOT / "problems" / "sort3-arm64"
OPEN_SUBMISSION_ID = "open-submission"
NON_OPEN_SUBMISSION_ERROR = (
    "candidate already exists with non-open-submission attribution; open-submission cannot overwrite"
)
DIFFERENT_OPEN_SUBMISSION_RECEIPT_ERROR = "candidate exists with different open-submission receipt; investigate"
COMMITTED_EXPORT_ERROR = "sqlite committed but leaderboard export failed; rerun publish or run summarize-run.py"


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def verified_receipt_payload(receipt_path: Path, public_key: Path) -> tuple[dict[str, Any], str]:
    envelope = load_json_object(receipt_path)
    expected_public_key = public_key.read_text().strip()
    if envelope.get("public_key") != expected_public_key:
        raise ValueError("receipt public_key does not match --public-key")
    verify_receipt(receipt_path)
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("receipt payload must be an object")
    signature = envelope.get("signature")
    if not isinstance(signature, str) or not signature:
        raise ValueError("receipt signature must be a non-empty string")
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("kind") != OPEN_SUBMISSION_ID:
        raise ValueError("receipt is not an open-submission receipt")
    validate_attestation(attestation)
    return payload, signature


def require_payload_field(payload: dict[str, Any], field: str) -> Any:
    value = payload.get(field)
    if value is None:
        raise ValueError(f"receipt payload missing {field}")
    return value


def existing_receipt_signature(store: Store, candidate_hash: str) -> str | None:
    row = store.db.execute(
        "SELECT signature FROM receipts WHERE candidate_hash = ?",
        (candidate_hash,),
    ).fetchone()
    if row is None or row["signature"] is None:
        return None
    return str(row["signature"])


def existing_publish_status(store: Store, problem_id: str, candidate_hash: str, signature: str) -> str:
    existing = store.candidate(problem_id, candidate_hash)
    if existing is None:
        return "new"
    if str(existing["model_id"]) != OPEN_SUBMISSION_ID:
        raise ValueError(NON_OPEN_SUBMISSION_ERROR)
    if existing_receipt_signature(store, candidate_hash) == signature:
        return "already published"
    raise ValueError(DIFFERENT_OPEN_SUBMISSION_RECEIPT_ERROR)


def export_committed_leaderboard(store: Store, problem_id: str, leaderboard_json: Path) -> None:
    try:
        store.export_leaderboard(problem_id, leaderboard_json)
    except Exception as exc:
        raise RuntimeError(COMMITTED_EXPORT_ERROR) from exc


def publish(args: argparse.Namespace) -> dict[str, Any]:
    payload, signature = verified_receipt_payload(Path(args.receipt), Path(args.public_key))
    candidate_hash = str(require_payload_field(payload, "candidate_hash"))
    score = int(require_payload_field(payload, "score"))
    problem_id = str(require_payload_field(payload, "problem_id"))
    if payload.get("model_id") != OPEN_SUBMISSION_ID or payload.get("provider_id") != OPEN_SUBMISSION_ID:
        raise ValueError("open-submission receipt must use open-submission model_id/provider_id")

    module = load_problem_module(PROBLEM_DIR)
    assembly_source = Path(args.assembly).read_text()
    if "\x00" in assembly_source:
        raise ValueError("assembly contains NUL byte; reject contestant submission")
    candidate = module.load(assembly_source)
    if candidate.candidate_hash != candidate_hash:
        raise ValueError("assembly does not match receipt candidate_hash")
    if candidate.problem_id != problem_id:
        raise ValueError("assembly problem_id does not match receipt problem_id")
    actual_score = module.score(candidate)
    if actual_score != score:
        raise ValueError("assembly score does not match receipt score")

    store = Store(Path(args.db))
    status = "published"
    try:
        store.begin_immediate()
        try:
            status = existing_publish_status(store, problem_id, candidate_hash, signature)
            if status == "new":
                store.record_candidate(
                    candidate_hash=candidate_hash,
                    problem_id=problem_id,
                    source=candidate.normalized_source,
                    score=score,
                    verified=True,
                    model_id=OPEN_SUBMISSION_ID,
                    provider_id=OPEN_SUBMISSION_ID,
                )

                attempt_id = store.record_attempt(problem_id, OPEN_SUBMISSION_ID, "ok", requested_n=1, response_count=1)
                store.record_evaluation(
                    attempt_id=attempt_id,
                    problem_id=problem_id,
                    candidate_hash=candidate_hash,
                    score=score,
                    verified=True,
                )
                store.record_receipt(candidate_hash, Path(args.receipt), signature)
                status = "published"
            store.commit()
        except Exception:
            store.rollback()
            raise
        export_committed_leaderboard(store, problem_id, Path(args.leaderboard_json))
    finally:
        store.close()

    return {"ok": True, "candidate_hash": candidate_hash, "score": score, "errors": [], "status": status}


def main_logic(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return publish(args)
    except Exception as exc:  # noqa: BLE001 - CLI failures are returned as JSON.
        return {"ok": False, "candidate_hash": None, "score": None, "errors": [str(exc)]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a signed open-submission receipt into the leaderboard.")
    parser.add_argument("--receipt", type=Path, required=True, help="Path to the signed open-submission receipt.")
    parser.add_argument("--assembly", type=Path, required=True, help="Path to the assembly source matching the receipt hash.")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "arm64golf.sqlite")
    parser.add_argument("--leaderboard-json", type=Path, default=REPO_ROOT / "web" / "public" / "leaderboard.json")
    parser.add_argument("--public-key", type=Path, default=REPO_ROOT / "receipts" / "PUBKEY")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = main_logic(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"{result['status']} candidate_hash={result['candidate_hash']} score={result['score']}")
    else:
        for error in result["errors"]:
            print(f"error: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
