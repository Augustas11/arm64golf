#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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


def json_command_check(name: str, cmd: list[str], timeout_s: float = 90.0) -> dict[str, Any]:
    code, output = run(cmd, timeout_s=timeout_s)
    parsed: Any = None
    try:
        parsed = json.loads(output) if output else None
    except json.JSONDecodeError:
        parsed = None
    ok = code == 0 and (not isinstance(parsed, dict) or parsed.get("ok", True) is not False)
    return {
        "name": name,
        "ok": ok,
        "returncode": code,
        "output": parsed if parsed is not None else output,
    }


def preflight_check(run_tests: bool) -> dict[str, Any]:
    cmd = [sys.executable, "bin/preflight.py"]
    if run_tests:
        cmd.append("--run-tests")
    code, output = run(cmd, timeout_s=120.0)
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return {"name": "preflight", "ok": False, "returncode": code, "output": output}

    required_keys = ["python", "clang", "sandbox_exec", "git_remote_origin", "github_repo_visibility", "gh_auth"]
    if run_tests:
        required_keys.append("tests")
    ok = all(isinstance(parsed.get(key), dict) and parsed[key].get("ok") for key in required_keys)
    return {
        "name": "preflight",
        "ok": ok,
        "returncode": code,
        "output": parsed,
        "macprovider_api_key_present": bool(parsed.get("macprovider_api_key", {}).get("ok")),
    }


def air5_model_check(skip: bool, provider_aliases: list[str], url: str) -> dict[str, Any]:
    if skip:
        return {"name": "air5_model", "ok": False, "skipped": True, "summary": "model check skipped"}
    if not os.environ.get("MACPROVIDER_API_KEY") and "api.streamvc.live" in url:
        return {"name": "air5_model", "ok": False, "skipped": True, "summary": "MACPROVIDER_API_KEY is required for API model check"}

    cmd = [sys.executable, "bin/check-air5-model.py", "--url", url]
    for alias in provider_aliases:
        cmd.extend(["--provider-alias", alias])
    return json_command_check("air5_model", cmd, timeout_s=30.0)


def readiness(args: argparse.Namespace) -> dict[str, Any]:
    audit_cmd = [sys.executable, "bin/audit-deliverables.py", "--json"]
    if args.offline_audit:
        audit_cmd.append("--offline")

    checks = [
        json_command_check("deliverable_audit", audit_cmd),
        json_command_check("receipt_validation", [sys.executable, "bin/validate-receipts.py", "--json"]),
        json_command_check("web_validation", [sys.executable, "bin/validate-web.py", "--json"]),
        json_command_check("seed_receipt", [sys.executable, "bin/verify-receipt.py", "receipts/726c3e4c49b5.json"]),
        preflight_check(args.run_tests),
        air5_model_check(args.skip_model_check, args.provider_alias, args.models_url),
    ]
    blockers = [check["name"] for check in checks if not check.get("ok")]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate readiness checks before an arm64golf live search run.")
    parser.add_argument("--offline-audit", action="store_true", help="Skip GitHub API call inside the deliverable audit.")
    parser.add_argument("--run-tests", action="store_true", help="Run pytest and sandbox runner through preflight.")
    parser.add_argument("--skip-model-check", action="store_true", help="Report air5 model check as skipped.")
    parser.add_argument("--models-url", default="https://api.streamvc.live/v1/models")
    parser.add_argument("--provider-alias", action="append", default=["m4"])
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    payload = readiness(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("ready" if payload["ready"] else "not ready")
        for blocker in payload["blockers"]:
            print(f"- {blocker}")
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
