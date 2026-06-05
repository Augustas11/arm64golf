#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REPO = "Augustas11/arm64golf"


def run(cmd: list[str], timeout_s: float = 10.0) -> tuple[int, str]:
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


def check_cmd(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"ok": path is not None, "path": path or ""}


def repo_slug_from_origin(origin: str) -> str:
    value = origin.strip()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("https://github.com/"):
        return value.removeprefix("https://github.com/")
    if value.startswith("git@github.com:"):
        return value.removeprefix("git@github.com:")
    return value


def check_repo_visibility(origin: str, allow_public_launch: bool) -> dict[str, object]:
    slug = repo_slug_from_origin(origin)
    if slug != EXPECTED_REPO:
        return {
            "ok": False,
            "expected": EXPECTED_REPO,
            "repo": slug,
            "visibility": "",
            "summary": "origin does not match expected private test repo",
        }
    if not shutil.which("gh"):
        return {"ok": False, "expected": EXPECTED_REPO, "repo": slug, "visibility": "", "summary": "gh unavailable"}

    code, output = run(["gh", "repo", "view", slug, "--json", "nameWithOwner,url,visibility"], timeout_s=15)
    if code != 0:
        return {"ok": False, "expected": EXPECTED_REPO, "repo": slug, "visibility": "", "summary": output}
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"ok": False, "expected": EXPECTED_REPO, "repo": slug, "visibility": "", "summary": output}

    visibility = str(payload.get("visibility", ""))
    ok = visibility == "PRIVATE" or allow_public_launch
    return {
        "ok": ok,
        "expected": EXPECTED_REPO,
        "repo": payload.get("nameWithOwner", slug),
        "url": payload.get("url", ""),
        "visibility": visibility,
        "private_required": not allow_public_launch,
        "summary": "private test repo verified" if ok else "repo is public but private test mode is required",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local preflight checks before an arm64golf live run.")
    parser.add_argument("--run-tests", action="store_true", help="Run pytest and native sandbox runner.")
    parser.add_argument(
        "--allow-public-launch",
        action="store_true",
        help="Allow a public GitHub repo; use only after explicit public launch approval.",
    )
    args = parser.parse_args()

    checks: dict[str, object] = {
        "python": {"ok": sys.version_info >= (3, 11), "version": sys.version.split()[0]},
        "clang": check_cmd("clang"),
        "sandbox_exec": check_cmd("sandbox-exec"),
        "gh": check_cmd("gh"),
        "vercel": check_cmd("vercel"),
        "macprovider_api_key": {"ok": bool(os.environ.get("MACPROVIDER_API_KEY"))},
        "git_remote_origin": {"ok": False, "value": ""},
        "github_repo_visibility": {"ok": False, "visibility": "", "summary": "not checked"},
        "gh_auth": {"ok": False, "summary": ""},
        "tests": {"ok": None, "summary": "skipped"},
    }

    code, output = run(["git", "remote", "get-url", "origin"])
    checks["git_remote_origin"] = {"ok": code == 0, "value": output}
    if code == 0:
        checks["github_repo_visibility"] = check_repo_visibility(output, args.allow_public_launch)

    if shutil.which("gh"):
        code, output = run(["gh", "auth", "status"], timeout_s=15)
        checks["gh_auth"] = {"ok": code == 0, "summary": output}

    if args.run_tests:
        pytest = REPO_ROOT / ".venv" / "bin" / "pytest"
        python = REPO_ROOT / ".venv" / "bin" / "python"
        pytest_cmd = [str(pytest), "-q"] if pytest.exists() else [sys.executable, "-m", "pytest", "-q"]
        python_cmd = [str(python), "sandbox/runner.py"] if python.exists() else [sys.executable, "sandbox/runner.py"]
        test_code, test_output = run(pytest_cmd, timeout_s=60)
        runner_code, runner_output = run(python_cmd, timeout_s=30)
        checks["tests"] = {
            "ok": test_code == 0 and runner_code == 0,
            "pytest": test_output,
            "sandbox_runner": runner_output,
        }

    print(json.dumps(checks, indent=2, sort_keys=True))

    required = [
        checks["python"],
        checks["clang"],
        checks["sandbox_exec"],
        checks["macprovider_api_key"],
        checks["git_remote_origin"],
        checks["github_repo_visibility"],
        checks["gh_auth"],
    ]
    if args.run_tests:
        required.append(checks["tests"])
    return 0 if all(isinstance(item, dict) and item.get("ok") for item in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
