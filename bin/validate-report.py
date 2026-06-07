#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "REPORT.md"
LEADERBOARD = REPO_ROOT / "web" / "public" / "leaderboard.json"
WRITE_REPORT = REPO_ROOT / "bin" / "write-report.py"


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def load_write_report_module():
    spec = importlib.util.spec_from_file_location("arm64golf_write_report", WRITE_REPORT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {WRITE_REPORT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate() -> list[str]:
    errors: list[str] = []
    require(REPORT.exists(), "REPORT.md is missing", errors)
    require(LEADERBOARD.exists(), "web/public/leaderboard.json is missing", errors)
    require(WRITE_REPORT.exists(), "bin/write-report.py is missing", errors)
    if errors:
        return errors

    try:
        payload = load_json(LEADERBOARD)
    except ValueError as exc:
        return [str(exc)]

    problem_id = payload.get("problem_id")
    summary = payload.get("run_summary")
    pairs = payload.get("pairs")
    require(problem_id == "sort3-arm64", "leaderboard problem_id must be sort3-arm64", errors)
    require(isinstance(summary, dict), "leaderboard run_summary must be an object", errors)
    require(isinstance(pairs, list), "leaderboard pairs must be a list", errors)
    if not isinstance(summary, dict):
        return errors

    try:
        rendered = load_write_report_module().render_report(problem_id, summary, pairs if isinstance(pairs, list) else [])
    except Exception as exc:  # noqa: BLE001 - validator should surface render failures as data.
        return [f"REPORT.md render failed: {exc}"]

    actual = REPORT.read_text()
    pre_live = int(payload.get("candidate_response_count") or 0) == 0

    if pre_live:
        # Pre-live: REPORT.md must be the bare write-report.py output and
        # carry the pending-state assertions. A bona fide live run flips
        # the file into post-live mode (below).
        require(
            actual == rendered,
            "REPORT.md must match bin/write-report.py output for web/public/leaderboard.json",
            errors,
        )
        require("Status: pending" in actual, "REPORT.md must record pending status before live run", errors)
        require(
            "No PASS/FAIL verdict yet" in actual,
            "REPORT.md must state there is no PASS/FAIL verdict before live run",
            errors,
        )
        require(
            "Pending Before PASS/FAIL Run" in actual,
            "REPORT.md must include pending live-run gates",
            errors,
        )
        require(
            "MACPROVIDER_API_KEY" in actual and "air5 coder-model handoff" in actual,
            "REPORT.md must name live credential and air5 handoff blockers",
            errors,
        )
        rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            row = rows[0]
            require(isinstance(row, dict), "pending seed leaderboard row must be an object", errors)
            if isinstance(row, dict):
                require(
                    row.get("model_id") == "reference-baseline" and row.get("provider_id") == "local-harness",
                    "pending seed row must not claim live air5/coder-model attribution",
                    errors,
                )
                require(
                    "reference-baseline` / `local-harness" in actual,
                    "REPORT.md must document seed baseline attribution separately from live model attribution",
                    errors,
                )
    else:
        # Post-live: the rendered output is split into a "head" (title +
        # `Status:` line) and a "body" (everything from `## Run Evidence`
        # onward — the ledger-derived sections). The head must open the
        # report; the body must close it verbatim. Hand-edited narrative
        # sections (network config, verdict interpretation, etc.) may
        # sit between them. That way the auto-generated evidence cannot
        # drift from the leaderboard ledger while leaving room for human
        # interpretation above it. The auto-derived "## Verdict" block
        # falls in the editable middle so a human can expand it
        # (technical-vs-substantive PASS-A, etc.) without the validator
        # treating that as drift.
        body_marker = "## Verdict\n"
        if body_marker in rendered:
            head, body = rendered.split(body_marker, 1)
            body = body_marker + body
            require(
                actual.startswith(head),
                "REPORT.md must start with the title + status line produced by bin/write-report.py",
                errors,
            )
            require(
                actual.endswith(body),
                "REPORT.md must end with the bin/write-report.py ledger sections "
                f"(`{body_marker}` onward) verbatim — hand-edited sections may sit between the status "
                "line and `## Run Evidence`, but the auto body cannot drift",
                errors,
            )
        else:
            # Defensive: write-report.py contract guarantees `## Run
            # Evidence`. If a future refactor renames it, fall back to
            # the strict endswith contract so drift is still caught.
            require(
                actual.endswith(rendered),
                "REPORT.md must end with bin/write-report.py output for web/public/leaderboard.json",
                errors,
            )

        require(
            "Current derived verdict:" in actual,
            "REPORT.md must record the auto-derived verdict line post-live",
            errors,
        )

    # Cross-state invariants — apply pre- and post-live alike.
    require(
        "public launch is intentionally deferred" in actual and "explicit public launch approval" in actual,
        "REPORT.md must preserve private-test/public-launch deferral wording",
        errors,
    )
    require(
        "- PASS-A:" in actual and "- PASS-B:" in actual and "- PASS-C:" in actual and "- FAIL:" in actual,
        "REPORT.md must include all PASS/FAIL criteria",
        errors,
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate REPORT.md against tracked leaderboard evidence.")
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
