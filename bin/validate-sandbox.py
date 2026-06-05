#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = REPO_ROOT / "sandbox" / "profile.sb"
RUNNER = REPO_ROOT / "sandbox" / "runner.py"
TESTS = REPO_ROOT / "sandbox" / "tests" / "test_sandbox.py"


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


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def python_executable() -> str:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def validate_profile_contract(errors: list[str]) -> None:
    require(PROFILE.exists(), "sandbox/profile.sb is missing", errors)
    if not PROFILE.exists():
        return

    text = PROFILE.read_text()
    required_fragments = [
        "(deny default)",
        "(deny network*)",
        "(deny process-fork)",
        "(deny process-exec",
        "(deny file-read*",
        "(deny file-write*",
        "/etc/passwd",
        "/tmp/arm64golf-forbidden",
    ]
    for fragment in required_fragments:
        require(fragment in text, f"sandbox/profile.sb must contain {fragment}", errors)


def validate_runner_contract(errors: list[str]) -> None:
    require(RUNNER.exists(), "sandbox/runner.py is missing", errors)
    require(TESTS.exists(), "sandbox/tests/test_sandbox.py is missing", errors)
    require(shutil.which("clang") is not None, "clang is required for sandbox validation", errors)
    require(shutil.which("sandbox-exec") is not None, "sandbox-exec is required for sandbox validation", errors)
    if errors:
        return

    code, output = run([python_executable(), "-m", "pytest", "-q", str(TESTS)], timeout_s=90)
    require(code == 0, f"sandbox pytest failed: {output}", errors)

    code, output = run([python_executable(), str(RUNNER)], timeout_s=30)
    if code != 0:
        errors.append(f"sandbox runner reference command failed: {output}")
        return
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        errors.append(f"sandbox runner did not emit JSON: {exc}: {output}")
        return

    require(payload.get("ok") is True, "sandbox runner reference result must have ok=true", errors)
    require(payload.get("verified") is True, "sandbox runner reference candidate must verify", errors)
    require(payload.get("score") == 18, "sandbox runner reference score must be 18", errors)
    require(payload.get("timeout_ms") == 100, "sandbox runner default timeout_ms must be 100", errors)
    require(payload.get("memory_limit_mb") == 256, "sandbox runner default memory_limit_mb must be 256", errors)


def validate() -> list[str]:
    errors: list[str] = []
    validate_profile_contract(errors)
    validate_runner_contract(errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the arm64golf macOS sandbox contract.")
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
