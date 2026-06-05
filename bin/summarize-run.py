#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.store import Store
from harness.verdict import verdict


def render_markdown(problem_id: str, summary: dict[str, object]) -> str:
    status = verdict(summary)
    top_errors = summary.get("top_evaluation_errors") or []
    near_best_structures = summary.get("near_best_structures") or []
    lines = [
        f"# arm64golf run summary: {problem_id}",
        "",
        f"Verdict: {status}",
        "",
        "## Counters",
        "",
        f"- attempts: {summary['attempt_count']}",
        f"- requested candidates: {summary['requested_candidate_count']}",
        f"- candidate responses: {summary['candidate_response_count']}",
        f"- evaluated responses: {summary['evaluation_count']}",
        f"- verified evaluations: {summary['verified_evaluation_count']}",
        f"- failed evaluations: {summary['failed_evaluation_count']}",
        f"- evaluations with error text: {summary['evaluation_error_count']}",
        f"- best verified score: {summary['best_verified_score'] or 'none'}",
        "",
        "## Threshold Evidence",
        "",
        f"- first verified response: {summary['first_verified_response'] or 'none'}",
        f"- first 17-instruction response: {summary['first_17_response'] or 'none'}",
        f"- first 16-instruction response: {summary['first_16_response'] or 'none'}",
        "",
        "PASS/FAIL thresholds use evaluated candidate-response ordinals. PASS-C here means a verified 16-instruction candidate; structural-diversity PASS-C still requires manual review.",
        "",
    ]
    if near_best_structures:
        lines.extend(
            [
                "## Structural Diversity",
                "",
                f"- near-best verified candidates: {summary['near_best_candidate_count']}",
                f"- near-best unique opcode structures: {summary['near_best_unique_structure_count']}",
                "",
            ]
        )
        for item in near_best_structures:
            sequence = " ".join(item["opcode_sequence"])
            lines.append(
                f"- {item['fingerprint']} "
                f"({item['candidate_count']} candidate(s), representative {item['representative_hash_short']}, "
                f"score {item['representative_score']}, {item['instruction_count']} instructions): `{sequence}`"
            )
        lines.append("")
    if top_errors:
        lines.extend(["## Top Evaluation Errors", ""])
        for item in top_errors:
            lines.append(f"- {item['count']}x {item['error']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize an arm64golf run from SQLite evidence.")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "arm64golf.sqlite")
    parser.add_argument("--problem-id", default="sort3-arm64")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--output", type=Path, help="Write the summary to this path.")
    args = parser.parse_args()

    store = Store(args.db)
    try:
        summary = store.run_summary(args.problem_id)
    finally:
        store.close()

    payload = {"problem_id": args.problem_id, "verdict": verdict(summary), **summary}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n" if args.json else render_markdown(args.problem_id, summary)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
