#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

# Self-bootstrap: re-exec under .venv/bin/python if it exists and we aren't
# already running there. The harness's child scripts use sys.executable, so
# once we re-exec the whole chain inherits the venv interpreter. This means
# `python3 bin/ready-live-run.py` Just Works without manual `source .venv/...`.
#
# Note: comparing resolved paths is WRONG — `.venv/bin/python3` is typically
# a symlink to the base interpreter, so both resolve to the same target. The
# canonical "am I in a venv?" test is `sys.prefix != sys.base_prefix`; in a
# venv sys.prefix points at .venv, in the base interpreter they're equal.
_REPO = Path(__file__).resolve().parents[1]
_VENV_PY = _REPO / ".venv" / "bin" / "python3"
_IN_VENV = sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() == (_REPO / ".venv").resolve()
if _VENV_PY.exists() and not _IN_VENV and not os.environ.get("ARM64GOLF_VENV_REEXEC"):
    os.environ["ARM64GOLF_VENV_REEXEC"] = "1"
    os.execv(str(_VENV_PY), [str(_VENV_PY), __file__, *sys.argv[1:]])

import argparse
import json
import subprocess
from typing import Any


REPO_ROOT = _REPO


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


def live_credentials_check() -> dict[str, Any]:
    api_key = bool(os.environ.get("MACPROVIDER_API_KEY"))
    demo_token = bool(os.environ.get("MACPROVIDER_DEMO_TOKEN"))
    present = api_key or demo_token
    which = "MACPROVIDER_API_KEY" if api_key else ("MACPROVIDER_DEMO_TOKEN" if demo_token else "")
    return {
        "name": "live_credentials",
        "ok": present,
        "summary": f"{which} is present" if present else "no live credential present",
        "credential_kind": which,
        "operator_actions": []
        if present
        else ["Set MACPROVIDER_API_KEY (long-lived) or MACPROVIDER_DEMO_TOKEN (24h) before live model checks or inference."],
    }


def air5_model_check(skip: bool, provider_aliases: list[str], url: str) -> dict[str, Any]:
    if skip:
        return {
            "name": "air5_model",
            "ok": False,
            "skipped": True,
            "summary": "model check skipped to avoid touching air5 without operator coordination",
            "operator_actions": [
                "Coordinate with the air5 owner before installing models, upgrading provider software, editing config, or reconnecting the node."
            ],
        }
    have_credential = bool(os.environ.get("MACPROVIDER_API_KEY")) or bool(os.environ.get("MACPROVIDER_DEMO_TOKEN"))
    if not have_credential and "api.streamvc.live" in url:
        return {
            "name": "air5_model",
            "ok": False,
            "skipped": True,
            "summary": "MACPROVIDER_API_KEY or MACPROVIDER_DEMO_TOKEN is required for API model check",
            "operator_actions": ["Set MACPROVIDER_API_KEY or MACPROVIDER_DEMO_TOKEN before checking the authenticated public API."],
        }

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
        live_credentials_check(),
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
