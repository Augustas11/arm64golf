#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_HTML_IDS = {
    "best-score",
    "attempt-count",
    "candidate-response-count",
    "attribution-line",
    "hero-status",
    "improvement-chart",
    "last-update",
    "leaderboard-rows",
    "pairs-table-rows",
    "trajectory-chart",
}
REQUIRED_ROW_FIELDS = {
    "rank",
    "score",
    "candidate_hash",
    "candidate_hash_short",
    "model_id",
    "provider_id",
    "receipt_signature",
    "receipt_signature_short",
    "discovered_at",
}
REQUIRED_SUMMARY_FIELDS = {
    "attempt_count",
    "requested_candidate_count",
    "candidate_response_count",
    "evaluation_count",
    "verified_evaluation_count",
    "failed_evaluation_count",
    "evaluation_error_count",
    "best_verified_score",
    "first_verified_response",
    "first_17_response",
    "first_16_response",
    "near_best_candidate_count",
    "near_best_unique_structure_count",
    "near_best_structures",
}
REQUIRED_PAIR_FIELDS = {
    "problem_id",
    "provider_id",
    "model_id",
    "template_name",
    "template_id",
    "attribution_kind",
    "evaluated_responses",
    "verified_count",
    "best_verified_score",
    "first_verified_response",
    "first_17_response",
    "first_16_response",
}
REQUIRED_LEAD_PHRASES = (
    "arm64golf — open superoptimization",
    "current shortest verified ARM64 sort3",
    "AlphaDev x86 reference",
    "clang -O3 ARM64 baseline",
    "Best verified per (provider, model, template)",
    "Best-known instruction count over time",
    "Have you seen shorter? Submit it.",
)
FORBIDDEN_INTERNAL_VOCABULARY = (
    "Private test preview",
    "Stage A",
    "Stage B",
    "Stage C",
    "G1 ",
    "G2 ",
    "G3 ",
    "G4 ",
    "calibration",
    "2 providers",
    "2 models",
    "currently 6 pairs",
)


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "script" and values.get("src"):
            self.scripts.append(str(values["src"]))
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(str(values["href"]))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_html(web_dir: Path, errors: list[str]) -> None:
    index = web_dir / "index.html"
    require(index.exists(), "web/index.html is missing", errors)
    if not index.exists():
        return

    parser = IdCollector()
    text = index.read_text()
    normalized_text = " ".join(text.split())
    parser.feed(text)
    missing_ids = sorted(REQUIRED_HTML_IDS - parser.ids)
    require(not missing_ids, f"web/index.html is missing required ids: {', '.join(missing_ids)}", errors)
    require(
        "Powered by air5 + Qwen2.5-Coder-7B</p>" not in text,
        "web/index.html must not statically claim air5/Qwen attribution before live responses",
        errors,
    )
    require(
        "/private/tmp/arm64golf-sandbox" not in text,
        "web/index.html must not embed internal sandbox host paths",
        errors,
    )
    missing_lead_phrases = [phrase for phrase in REQUIRED_LEAD_PHRASES if phrase not in normalized_text]
    require(
        not missing_lead_phrases,
        "web/index.html public lead missing required phrases: " + ", ".join(missing_lead_phrases),
        errors,
    )
    leaked_terms = [term for term in FORBIDDEN_INTERNAL_VOCABULARY if term in normalized_text]
    require(
        not leaked_terms,
        "web/index.html leaks internal vocabulary: " + ", ".join(leaked_terms),
        errors,
    )
    require("./app.js" in parser.scripts, "web/index.html does not load ./app.js", errors)
    require("./styles.css" in parser.stylesheets, "web/index.html does not load ./styles.css", errors)
    require((web_dir / "app.js").exists(), "web/app.js is missing", errors)
    require((web_dir / "styles.css").exists(), "web/styles.css is missing", errors)


def validate_leaderboard(web_dir: Path, errors: list[str]) -> None:
    path = web_dir / "public" / "leaderboard.json"
    require(path.exists(), "web/public/leaderboard.json is missing", errors)
    if not path.exists():
        return

    try:
        payload = load_json(path)
    except ValueError as exc:
        errors.append(str(exc))
        return

    for field in [
        "problem_id",
        "attempt_count",
        "requested_candidate_count",
        "candidate_response_count",
        "run_summary",
        "pairs",
        "rows",
    ]:
        require(field in payload, f"leaderboard JSON missing top-level field {field}", errors)
    require(payload.get("problem_id") == "sort3-arm64", "leaderboard problem_id must be sort3-arm64", errors)
    require(isinstance(payload.get("rows"), list), "leaderboard rows must be a list", errors)
    require(isinstance(payload.get("pairs"), list), "leaderboard pairs must be a list", errors)
    if "pairs_truncated" in payload:
        require(isinstance(payload.get("pairs_truncated"), bool), "leaderboard pairs_truncated must be a bool", errors)

    summary = payload.get("run_summary")
    require(isinstance(summary, dict), "run_summary must be an object", errors)
    if isinstance(summary, dict):
        missing_summary = sorted(REQUIRED_SUMMARY_FIELDS - set(summary))
        require(not missing_summary, f"run_summary missing fields: {', '.join(missing_summary)}", errors)
        for entry in summary.get("top_evaluation_errors") or []:
            text = entry.get("error", "") if isinstance(entry, dict) else ""
            require(
                "/private/tmp/arm64golf-sandbox" not in text,
                "run_summary.top_evaluation_errors must not leak internal sandbox host paths",
                errors,
            )

    pairs = payload.get("pairs")
    if isinstance(pairs, list):
        for index, pair in enumerate(pairs, start=1):
            require(isinstance(pair, dict), f"pair {index} must be an object", errors)
            if not isinstance(pair, dict):
                continue
            missing_pair = sorted(REQUIRED_PAIR_FIELDS - set(pair))
            require(not missing_pair, f"pair {index} missing fields: {', '.join(missing_pair)}", errors)
            require(pair.get("problem_id") == payload.get("problem_id"), f"pair {index} problem_id must match leaderboard problem_id", errors)
            attribution_kind = pair.get("attribution_kind")
            require(
                attribution_kind in {"reference_harness", "open_submission", "mock"},
                f"pair {index} attribution_kind is invalid",
                errors,
            )
            if attribution_kind == "reference_harness":
                require(pair.get("template_name") is not None, f"pair {index} template_name is required", errors)
                require(pair.get("template_id") is not None, f"pair {index} template_id is required", errors)
            elif attribution_kind in {"open_submission", "mock"}:
                # Open-submission rows are normally excluded from pairs[] by
                # the exporter, but legacy JSON with that attribution remains
                # valid as long as it does not claim prompt-template fields.
                require(pair.get("template_name") is None, f"pair {index} template_name must be null", errors)
                require(pair.get("template_id") is None, f"pair {index} template_id must be null", errors)

    rows = payload.get("rows")
    if isinstance(rows, list):
        require(bool(rows), "leaderboard rows must include at least the seed baseline", errors)
        for index, row in enumerate(rows, start=1):
            require(isinstance(row, dict), f"row {index} must be an object", errors)
            if not isinstance(row, dict):
                continue
            missing_row = sorted(REQUIRED_ROW_FIELDS - set(row))
            require(not missing_row, f"row {index} missing fields: {', '.join(missing_row)}", errors)
            require(row.get("rank") == index, f"row {index} rank must be {index}", errors)
            require(isinstance(row.get("score"), int), f"row {index} score must be an integer", errors)
            require(bool(row.get("receipt_signature")), f"row {index} receipt_signature is empty", errors)
            # Open-submission leaderboard rows are allowed. The pre-live seed
            # attribution check only applies before any candidate responses
            # have been recorded.
            if index == 1 and payload.get("candidate_response_count") == 0:
                require(row.get("model_id") == "reference-baseline", "seed leaderboard row must use reference-baseline model_id", errors)
                require(row.get("provider_id") == "local-harness", "seed leaderboard row must use local-harness provider_id", errors)


def validate(web_dir: Path) -> list[str]:
    errors: list[str] = []
    validate_html(web_dir, errors)
    validate_leaderboard(web_dir, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate static arm64golf leaderboard assets.")
    parser.add_argument("--web-dir", type=Path, default=REPO_ROOT / "web")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args()

    errors = validate(args.web_dir)
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
