#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REPO = "Augustas11/arm64golf"


class AuditItem:
    def __init__(self, item_id: str, status: str, summary: str):
        self.id = item_id
        self.status = status
        self.summary = summary

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "status": self.status, "summary": self.summary}


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


def file_exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


def file_contains(path: str, needles: list[str]) -> bool:
    target = REPO_ROOT / path
    if not target.exists():
        return False
    text = target.read_text()
    return all(needle in text for needle in needles)


def json_load(path: str) -> Any:
    return json.loads((REPO_ROOT / path).read_text())


def git_repo_status(check_visibility: bool = True) -> AuditItem:
    code, origin = run(["git", "remote", "get-url", "origin"])
    if code != 0:
        return AuditItem("github_repo", "missing", "origin remote is not configured")
    expected_url = f"https://github.com/{EXPECTED_REPO}.git"
    if origin != expected_url:
        return AuditItem("github_repo", "failed", f"origin is {origin}, expected {expected_url}")
    if not check_visibility:
        return AuditItem("github_repo", "pending", "origin is correct; GitHub visibility was not checked in offline mode")

    output = ""
    for attempt in range(3):
        code, output = run(["gh", "repo", "view", EXPECTED_REPO, "--json", "nameWithOwner,url,visibility"], timeout_s=15)
        if code == 0:
            break
        if attempt < 2:
            time.sleep(1)
    if code != 0:
        return AuditItem("github_repo", "unknown", f"origin is correct but gh visibility check failed: {output}")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return AuditItem("github_repo", "unknown", f"origin is correct but gh returned non-JSON: {output}")
    visibility = payload.get("visibility", "")
    if visibility != "PRIVATE":
        return AuditItem("github_repo", "failed", f"repo visibility is {visibility}; private test mode requires PRIVATE")
    return AuditItem("github_repo", "complete", "private test repo exists at the expected origin")


def audit_items(check_github_visibility: bool = True) -> list[AuditItem]:
    items = [
        git_repo_status(check_github_visibility),
        AuditItem(
            "license",
            "complete" if file_contains("LICENSE", ["MIT License"]) else "missing",
            "MIT license present" if file_exists("LICENSE") else "LICENSE is missing",
        ),
        AuditItem(
            "spec",
            "complete" if spec_doc_ok() else "missing",
            "SPEC.md contract validates: sections, PoC questions, interfaces, gates, and private-test status",
        ),
        AuditItem(
            "readme",
            "complete" if readme_doc_ok() else "missing",
            "README contract validates: recruiting copy, participation paths, architecture, and private launch state",
        ),
        AuditItem(
            "sort3_module",
            "complete" if sort3_module_validator_ok() else "missing",
            "sort3-arm64 contract validates: manifest, 18-instruction reference, 1000+ tests, and baseline verifier",
        ),
        AuditItem(
            "harness",
            "complete" if harness_smoke_ok() else "missing",
            "offline harness smoke passes: mock inference, verifier, score, receipt, SQLite, and leaderboard export",
        ),
        AuditItem(
            "inference_path",
            "complete" if inference_config_ok() else "missing",
            "inference request contract validates: endpoint, coder model, air5 provider header, sampling, and auth behavior",
        ),
        AuditItem(
            "sandbox",
            "complete" if sandbox_validator_ok() else "missing",
            "sandbox contract validates: deny profile, native runner, and escape-vector pytest suite",
        ),
        AuditItem(
            "receipts",
            "complete" if receipt_validator_ok() else "missing",
            "ed25519 public key and leaderboard receipts pass bin/validate-receipts.py",
        ),
        AuditItem(
            "web",
            "complete" if web_validator_ok() else "missing",
            "static leaderboard preview files are present and pass bin/validate-web.py",
        ),
        AuditItem(
            "air5_handoff",
            "pending"
            if file_contains("AIR5_OPERATOR_NOTE.md", ["Status: untested-pending-handoff"])
            else "missing",
            "operator walkthrough is documented as untested-pending-handoff until the air5 operator completes it",
        ),
        AuditItem(
            "live_credentials",
            "complete" if os.environ.get("MACPROVIDER_API_KEY") else "pending",
            "MACPROVIDER_API_KEY is present" if os.environ.get("MACPROVIDER_API_KEY") else "MACPROVIDER_API_KEY is not present",
        ),
    ]

    leaderboard_ok = False
    try:
        payload = json_load("web/public/leaderboard.json")
        leaderboard_ok = bool(payload.get("rows")) and payload.get("run_summary", {}).get("best_verified_score") is not None
    except (OSError, json.JSONDecodeError, TypeError):
        leaderboard_ok = False
    items.append(
        AuditItem(
            "leaderboard_data",
            "complete" if leaderboard_ok else "missing",
            "static leaderboard JSON contains seed row and run summary",
        )
    )

    report_status = "missing"
    report_summary = "REPORT.md is missing"
    if file_exists("REPORT.md"):
        if file_contains("REPORT.md", ["Status: pending", "Pending Before PASS/FAIL Run"]):
            report_status = "pending"
            report_summary = "REPORT.md records pending state and remaining live-run gates"
        if file_contains("REPORT.md", ["Status: pass-a"]) or file_contains("REPORT.md", ["Status: pass-b"]) or file_contains(
            "REPORT.md", ["Status: pass-c"]
        ) or file_contains("REPORT.md", ["Status: fail"]):
            report_status = "complete"
            report_summary = "REPORT.md records a terminal PASS/FAIL outcome"
    items.append(AuditItem("report", report_status, report_summary))

    items.append(
        AuditItem(
            "public_deployment",
            "deferred",
            "public Vercel deployment and DNS are deferred until explicit launch approval",
        )
    )
    return items


def render_markdown(items: list[AuditItem]) -> str:
    lines = ["# arm64golf deliverable audit", ""]
    for item in items:
        lines.append(f"- **{item.id}**: {item.status} - {item.summary}")
    lines.append("")
    return "\n".join(lines)


def web_validator_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-web.py"), "--json"])
    return code == 0


def receipt_validator_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-receipts.py"), "--json"])
    return code == 0


def sort3_module_validator_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-sort3-module.py"), "--json"])
    return code == 0


def harness_smoke_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-harness-smoke.py"), "--json"], timeout_s=90)
    return code == 0


def sandbox_validator_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-sandbox.py"), "--json"], timeout_s=120)
    return code == 0


def inference_config_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-inference-config.py"), "--json"])
    return code == 0


def spec_doc_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-docs.py"), "--target", "spec", "--json"])
    return code == 0


def readme_doc_ok() -> bool:
    code, _ = run([sys.executable, str(REPO_ROOT / "bin" / "validate-docs.py"), "--target", "readme", "--json"])
    return code == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit arm64golf BUILD_PROMPT deliverables from local evidence.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip GitHub API visibility check; use only with a separate private-repo preflight.",
    )
    args = parser.parse_args()

    items = audit_items(check_github_visibility=not args.offline)
    payload = {"items": [item.as_dict() for item in items]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_markdown(items), end="")

    bad_statuses = {"missing", "failed", "unknown"}
    return 1 if any(item.status in bad_statuses for item in items) else 0


if __name__ == "__main__":
    raise SystemExit(main())
