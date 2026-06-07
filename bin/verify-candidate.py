#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ATTESTATION_JSON_SIZE_LIMIT = 16 * 1024
FORBIDDEN_MODULES = {
    "harness.inference",
    "httpx",
    "requests",
    "urllib",
    "urllib.error",
    "urllib.request",
}
_PREEXISTING_FORBIDDEN_MODULES = {name for name in FORBIDDEN_MODULES if name in sys.modules}

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.attest import sign_receipt, verify_receipt
from harness.loop import (
    HARNESS_VERSION,
    sandbox_verify,
    sanitize_open_submission_attestation,
    utc_now,
    validate_attestation,
)
from harness.module import load_problem_module


def _assert_no_forbidden_transitive_imports() -> None:
    loaded = {name for name in FORBIDDEN_MODULES if name in sys.modules}
    newly_loaded = loaded - _PREEXISTING_FORBIDDEN_MODULES
    if newly_loaded:
        raise RuntimeError(f"verify-candidate imported forbidden modules: {sorted(newly_loaded)}")


_assert_no_forbidden_transitive_imports()


def load_json_object(path: Path) -> dict[str, object]:
    if path.stat().st_size > ATTESTATION_JSON_SIZE_LIMIT:
        raise ValueError("attestation JSON exceeds 16384-byte limit")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("attestation JSON must be an object")
    return value


def require_operator_keys(private_key: Path, public_key: Path) -> None:
    if not private_key.exists() or not public_key.exists():
        raise FileNotFoundError(
            "sign.key missing; this tool requires an existing operator key, run the harness once to create one"
        )
    mode = private_key.stat().st_mode & 0o777
    if mode != 0o600:
        raise PermissionError(f"{private_key} must have mode 0600; got {mode:04o}")


def normalize_open_submission_attestation(value: dict[str, object]) -> dict[str, object]:
    attestation = dict(value)
    input_kind = attestation.get("kind")
    if input_kind is None:
        attestation["kind"] = "open-submission"
    elif input_kind != "open-submission":
        raise ValueError("verify-candidate only signs open-submission attestations")
    attestation = sanitize_open_submission_attestation(attestation)
    validate_attestation(attestation)
    return attestation


def existing_receipt_payload(receipts_dir: Path, candidate_hash: str, public_key: Path) -> dict[str, object] | None:
    path = receipts_dir / f"{candidate_hash[:12]}.json"
    if not path.exists():
        return None
    envelope = json.loads(path.read_text())
    if envelope.get("public_key") != public_key.read_text().strip():
        raise ValueError(
            "existing receipt was signed by a different public key; refusing to overwrite or dedup; "
            f"investigate receipts/{candidate_hash[:12]}.json"
        )
    verify_receipt(path)
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{path} payload must be an object")
    if payload.get("candidate_hash") != candidate_hash:
        raise ValueError(f"{path} candidate_hash does not match {candidate_hash}")
    if payload.get("model_id") != "open-submission" or payload.get("provider_id") != "open-submission":
        raise ValueError(f"{path} is not an open-submission receipt")
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("kind") != "open-submission":
        raise ValueError(f"{path} is not an open-submission receipt")
    return payload


def open_submission_payload(candidate, score: int, attestation: dict[str, object], ts: str) -> dict[str, object]:
    return {
        "attestation": attestation,
        "candidate_hash": candidate.candidate_hash,
        "harness_version": HARNESS_VERSION,
        "model_id": "open-submission",
        "problem_id": candidate.problem_id,
        "provider_id": "open-submission",
        "score": score,
        "ts": ts,
    }


def main_logic(args: argparse.Namespace) -> dict[str, Any]:
    candidate_hash: str | None = None
    score: int | None = None
    errors: list[str] = []

    try:
        problem_dir = Path(args.problem)
        module = load_problem_module(problem_dir)
        assembly_content = Path(args.assembly).read_text()
        attestation = normalize_open_submission_attestation(load_json_object(Path(args.attestation)))
        candidate = module.load(assembly_content)
        candidate_hash = candidate.candidate_hash
        if not sandbox_verify(problem_dir, module, candidate, args.timeout_ms, args.memory_limit_mb):
            raise ValueError("verifier rejected candidate")
        score = module.score(candidate)
        receipts_dir = Path(args.receipts_dir)
        receipts_dir.mkdir(parents=True, exist_ok=True)
        require_operator_keys(Path(args.private_key), Path(args.public_key))
        existing_payload = existing_receipt_payload(receipts_dir, candidate.candidate_hash, Path(args.public_key))
        ts = str(existing_payload.get("ts")) if existing_payload is not None else utc_now()
        payload = open_submission_payload(candidate, score, attestation, ts)
        if existing_payload is not None and existing_payload != payload:
            raise ValueError(
                "existing receipt has different attestation; resubmit via issue if you intend to update"
            )
        sign_receipt(payload, Path(args.private_key), Path(args.public_key), receipts_dir)
    except Exception as exc:  # noqa: BLE001 - all CLI failures are reported uniformly.
        errors.append(str(exc))

    if errors:
        candidate_hash = None
        score = None
    return {"ok": not errors, "candidate_hash": candidate_hash, "score": score, "errors": errors}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify and sign an open-submission ARM64 candidate.")
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--problem", type=Path, default=REPO_ROOT / "problems" / "sort3-arm64")
    parser.add_argument("--receipts-dir", type=Path, default=REPO_ROOT / "receipts")
    parser.add_argument("--private-key", type=Path, default=REPO_ROOT / "data" / "sign.key")
    parser.add_argument("--public-key", type=Path, default=REPO_ROOT / "receipts" / "PUBKEY")
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--memory-limit-mb", type=int, default=256)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = main_logic(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"ok candidate_hash={result['candidate_hash']} score={result['score']}")
    else:
        for error in result["errors"]:
            print(f"error: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
