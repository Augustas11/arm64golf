#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], timeout_s: float = 90.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def validate() -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="arm64golf-live-contract-") as tmp:
        root = Path(tmp)
        leaderboard = root / "leaderboard.json"
        receipts_dir = root / "receipts"
        private_key = root / "data" / "sign.key"
        public_key = receipts_dir / "PUBKEY"
        mock = root / "responses.json"
        reference = (REPO_ROOT / "problems" / "sort3-arm64" / "reference.s").read_text()
        mock.write_text(json.dumps(["this_is_not_arm64 x0, x1\n", reference]))

        code, output = run(
            [
                sys.executable,
                "harness/loop.py",
                "--rounds",
                "1",
                "--max-candidate-responses",
                "2",
                "--mock-response-file",
                str(mock),
                "--db",
                str(root / "db.sqlite"),
                "--leaderboard-json",
                str(leaderboard),
                "--private-key",
                str(private_key),
                "--public-key",
                str(public_key),
                "--receipts-dir",
                str(receipts_dir),
            ]
        )
        require(code == 0, f"harness loop contract run failed: {output}", errors)
        require(leaderboard.exists(), "contract run did not export leaderboard JSON", errors)
        if errors:
            return errors

        try:
            payload = load_json(leaderboard)
        except ValueError as exc:
            return [str(exc)]

        summary = payload.get("run_summary")
        require(isinstance(summary, dict), "run_summary must be an object", errors)
        if not isinstance(summary, dict):
            return errors

        require(payload.get("attempt_count") == 1, "contract run must record exactly one attempt", errors)
        require(payload.get("requested_candidate_count") == 2, "contract run must request two capped candidates", errors)
        require(payload.get("candidate_response_count") == 2, "contract run must count two candidate responses", errors)
        require(summary.get("evaluation_count") == 2, "contract run must evaluate both candidate responses", errors)
        require(summary.get("verified_evaluation_count") == 1, "contract run must verify the baseline candidate", errors)
        require(summary.get("failed_evaluation_count") == 1, "contract run must log invalid assembly as a failed evaluation", errors)
        require(summary.get("evaluation_error_count") == 1, "contract run must preserve invalid-assembly error text", errors)
        require(summary.get("first_verified_response") == 2, "first verified ordinal must reflect candidate-response order", errors)
        require(summary.get("candidate_response_count") == 2, "summary response count must match capped response count", errors)

        rows = payload.get("rows")
        require(isinstance(rows, list) and bool(rows), "leaderboard must include the verified baseline row", errors)
        if isinstance(rows, list) and rows:
            require(bool(rows[0].get("receipt_signature")), "verified leaderboard row must have a receipt signature", errors)
            require(
                rows[0].get("model_id") == "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
                "verified model response matching the seed hash must carry coder-model attribution",
                errors,
            )
            require(
                rows[0].get("provider_id") == "air5",
                "verified model response matching the seed hash must carry air5 attribution",
                errors,
            )
        require(public_key.exists(), "contract run must publish an ed25519 public key", errors)
        require(bool(list(receipts_dir.glob("*.json"))), "contract run must write at least one receipt JSON", errors)
        code, output = run(
            [
                sys.executable,
                "harness/loop.py",
                "--rounds",
                "1",
                "--model",
                "wrong-model",
                "--provider",
                "air5",
                "--api-key",
                "dummy",
                "--db",
                str(root / "wrong-model.sqlite"),
                "--leaderboard-json",
                str(root / "wrong-model-leaderboard.json"),
                "--private-key",
                str(root / "wrong-model" / "sign.key"),
                "--public-key",
                str(root / "wrong-model" / "PUBKEY"),
                "--receipts-dir",
                str(root / "wrong-model" / "receipts"),
            ]
        )
        require(code != 0, "live run must reject non-pinned model attribution", errors)
        require("pinned model" in output, "non-pinned model rejection must name the pinned-model rule", errors)
        code, output = run(
            [
                sys.executable,
                "harness/loop.py",
                "--rounds",
                "0",
                "--model",
                "wrong-model",
                "--provider",
                "air8gb",
                "--allow-marketplace-attribution",
                "--api-key",
                "dummy",
                "--db",
                str(root / "marketplace-model.sqlite"),
                "--leaderboard-json",
                str(root / "marketplace-model-leaderboard.json"),
                "--private-key",
                str(root / "marketplace-model" / "sign.key"),
                "--public-key",
                str(root / "marketplace-model" / "PUBKEY"),
                "--receipts-dir",
                str(root / "marketplace-model" / "receipts"),
            ]
        )
        require(code == 0, f"marketplace attribution flag must accept non-pinned tuples: {output}", errors)
        require("pinned model" not in output, "marketplace attribution flag must not emit pinned-model rejection", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate live-run accounting, cap, failure logging, and receipt contracts.")
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
