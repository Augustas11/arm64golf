#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.store import Store
from harness.verdict import verdict


def render_report(problem_id: str, summary: dict[str, object]) -> str:
    status = verdict(summary)
    top_errors = summary.get("top_evaluation_errors") or []
    near_best_structures = summary.get("near_best_structures") or []
    pending_live = status == "PENDING" and int(summary["candidate_response_count"] or 0) == 0

    lines = [
        "# arm64golf v0.1 Report",
        "",
        f"Status: {status.lower()}",
        "",
        "## Verdict",
        "",
    ]
    if pending_live:
        lines.extend(
            [
                "No PASS/FAIL verdict yet. The search has not started because the air5 operator handoff and live MacProvider credentials are still pending.",
                "",
            ]
        )
    else:
        lines.extend([f"Current derived verdict: {status}.", ""])

    lines.extend(
        [
            "## Run Evidence",
            "",
            f"- problem: `{problem_id}`",
            f"- attempts: {summary['attempt_count']}",
            f"- requested candidates: {summary['requested_candidate_count']}",
            f"- candidate responses: {summary['candidate_response_count']}",
            f"- evaluated responses: {summary['evaluation_count']}",
            f"- verified evaluations: {summary['verified_evaluation_count']}",
            f"- failed evaluations: {summary['failed_evaluation_count']}",
            f"- evaluations with error text: {summary['evaluation_error_count']}",
            f"- best verified score: {summary['best_verified_score'] or 'none'}",
            f"- first verified response: {summary['first_verified_response'] or 'none'}",
            f"- first 17-instruction response: {summary['first_17_response'] or 'none'}",
            f"- first 16-instruction response: {summary['first_16_response'] or 'none'}",
            f"- near-best verified candidates: {summary['near_best_candidate_count']}",
            f"- near-best unique opcode structures: {summary['near_best_unique_structure_count']}",
            "",
        ]
    )

    if near_best_structures:
        lines.extend(["## Structural Diversity Evidence", ""])
        for item in near_best_structures:
            sequence = " ".join(item["opcode_sequence"])
            lines.append(
                f"- `{item['fingerprint']}`: {item['candidate_count']} candidate(s), "
                f"representative `{item['representative_hash_short']}`, score {item['representative_score']}, "
                f"{item['instruction_count']} instructions: `{sequence}`"
            )
        lines.extend(
            [
                "",
                "This evidence is for manual PASS-C review only; automatic PASS-C still requires a verified 16-instruction candidate.",
                "",
            ]
        )

    if top_errors:
        lines.extend(["## Top Evaluation Errors", ""])
        for item in top_errors:
            lines.append(f"- {item['count']}x {item['error']}")
        lines.append("")

    lines.extend(
        [
            "## Current Evidence",
            "",
            "- Private GitHub repo exists at `https://github.com/Augustas11/arm64golf`; public launch is intentionally deferred.",
            "- Baseline candidate verifies locally on 1200 deterministic `sort3-arm64` tests through the native ARM64 sandbox runner.",
            "- The native runner enforces the v0.1 candidate caps inside the generated verifier executable: 100 ms wall-clock by default and 256 MB address/data memory by default.",
            "- Seed receipt exists at `receipts/726c3e4c49b5.json` and is verifiable with `bin/verify-receipt.py`.",
            "- Static leaderboard contains the seed baseline row and run-summary counters.",
            "- SQLite records every evaluated response separately from deduped candidates, preserving score, verification result, and sandbox/compiler error text.",
            "- `bin/summarize-run.py` and `bin/write-report.py` derive run status from the SQLite attempt/evaluation ledger.",
            "- The harness enforces `--max-candidate-responses` for live runs and continues past PASS-A by default so the same run can still probe for PASS-B/PASS-C.",
            "- `bin/preflight.py` and `bin/check-air5-model.py` exist for reproducible operator readiness and model visibility checks.",
            "- `bin/preflight.py` also verifies the GitHub repo remains private during the test phase unless `--allow-public-launch` is explicitly used after launch approval.",
            "",
            "## Pending Before PASS/FAIL Run",
            "",
            "- Complete the air5 coder-model handoff.",
            "- Confirm live provider id and model availability with `bin/check-air5-model.py`.",
            "- Provide `MACPROVIDER_API_KEY` for authenticated model checks and live inference.",
            "- Run the search harness with `MACPROVIDER_API_KEY`.",
            "- Deploy `web/` to a preview/private target if needed. Configure `arm64golf.streamvc.live` only after explicit public launch approval.",
            "",
            "## PASS/FAIL Criteria",
            "",
            "- PASS-A: one verified ARM64 candidate within 200 evaluated candidate responses.",
            "- PASS-B: one verified 17-instruction ARM64 candidate within 10,000 evaluated candidate responses.",
            "- PASS-C: verified 16-instruction candidate or manually reviewed structural diversity beyond PASS-B.",
            "- FAIL: none of the above within 10,000 evaluated candidate responses.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write REPORT.md from arm64golf run evidence.")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "arm64golf.sqlite")
    parser.add_argument("--problem-id", default="sort3-arm64")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "REPORT.md")
    args = parser.parse_args()

    store = Store(args.db)
    try:
        summary = store.run_summary(args.problem_id)
    finally:
        store.close()

    args.output.write_text(render_report(args.problem_id, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
