#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "sort3-arm64"
REFERENCE = REPO_ROOT / "problems" / "sort3-arm64" / "reference.s"


def run(cmd: list[str], timeout_s: float = 60.0) -> tuple[int, str]:
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


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def python_executable() -> str:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def run_loop_smoke(workdir: Path) -> tuple[int, str, Path, Path]:
    db = workdir / "arm64golf.sqlite"
    leaderboard = workdir / "leaderboard.json"
    receipts = workdir / "receipts"
    private_key = workdir / "data" / "sign.key"
    public_key = receipts / "PUBKEY"

    cmd = [
        python_executable(),
        "harness/loop.py",
        "--rounds",
        "1",
        "--mock-response-file",
        str(REFERENCE),
        "--db",
        str(db),
        "--leaderboard-json",
        str(leaderboard),
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
        "--receipts-dir",
        str(receipts),
        "--max-candidate-responses",
        "1",
    ]
    code, output = run(cmd, timeout_s=60.0)
    return code, output, leaderboard, receipts


def validate_leaderboard(leaderboard: Path, receipts: Path, errors: list[str]) -> None:
    require(leaderboard.exists(), "loop smoke did not export leaderboard JSON", errors)
    if not leaderboard.exists():
        return

    try:
        payload = load_json(leaderboard)
    except ValueError as exc:
        errors.append(str(exc))
        return

    require(payload.get("problem_id") == PROBLEM_ID, "leaderboard problem_id must be sort3-arm64", errors)
    require(payload.get("attempt_count") == 1, "loop smoke must record one attempt", errors)
    require(payload.get("requested_candidate_count") == 1, "loop smoke must request one candidate", errors)
    require(payload.get("candidate_response_count") == 1, "loop smoke must record one candidate response", errors)

    summary = payload.get("run_summary")
    require(isinstance(summary, dict), "leaderboard run_summary must be an object", errors)
    if isinstance(summary, dict):
        require(summary.get("evaluation_count") == 1, "loop smoke must record one evaluation", errors)
        require(summary.get("verified_evaluation_count") == 1, "loop smoke candidate must verify", errors)
        require(summary.get("failed_evaluation_count") == 0, "loop smoke must not record failed evaluations", errors)
        require(summary.get("evaluation_error_count") == 0, "loop smoke must not record evaluation errors", errors)
        require(summary.get("best_verified_score") == 18, "loop smoke best verified score must be 18", errors)
        require(summary.get("first_verified_response") == 1, "loop smoke first verified response must be 1", errors)

    rows = payload.get("rows")
    require(isinstance(rows, list) and bool(rows), "leaderboard rows must include a verified candidate", errors)
    if isinstance(rows, list) and rows:
        row = rows[0]
        require(isinstance(row, dict), "leaderboard first row must be an object", errors)
        if isinstance(row, dict):
            require(row.get("score") == 18, "leaderboard first row score must be 18", errors)
            require(row.get("model_id"), "leaderboard first row must include model attribution", errors)
            require(row.get("provider_id") == "air5", "leaderboard first row provider must be air5", errors)
            require(bool(row.get("receipt_signature")), "leaderboard first row must include a receipt signature", errors)

    code, output = run(
        [
            python_executable(),
            "bin/validate-receipts.py",
            "--leaderboard",
            str(leaderboard),
            "--receipts-dir",
            str(receipts),
            "--json",
        ]
    )
    require(code == 0, f"loop smoke receipt validation failed: {output}", errors)


def validate() -> list[str]:
    errors: list[str] = []
    require(REFERENCE.exists(), "reference assembly is missing", errors)
    require(shutil.which("clang") is not None, "clang is required for harness smoke", errors)
    require(shutil.which("sandbox-exec") is not None, "sandbox-exec is required for harness smoke", errors)
    if errors:
        return errors

    with tempfile.TemporaryDirectory(prefix="arm64golf-harness-smoke-", dir="/private/tmp") as tmp:
        workdir = Path(tmp)
        code, output, leaderboard, receipts = run_loop_smoke(workdir)
        require(code == 0, f"harness loop smoke failed: {output}", errors)
        if code == 0:
            validate_leaderboard(leaderboard, receipts, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an offline end-to-end arm64golf harness smoke.")
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
