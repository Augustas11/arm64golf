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
    "last-update",
    "leaderboard-rows",
    "promotion-feed",
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
    parser.feed(index.read_text())
    missing_ids = sorted(REQUIRED_HTML_IDS - parser.ids)
    require(not missing_ids, f"web/index.html is missing required ids: {', '.join(missing_ids)}", errors)
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

    for field in ["problem_id", "attempt_count", "requested_candidate_count", "candidate_response_count", "run_summary", "rows"]:
        require(field in payload, f"leaderboard JSON missing top-level field {field}", errors)
    require(payload.get("problem_id") == "sort3-arm64", "leaderboard problem_id must be sort3-arm64", errors)
    require(isinstance(payload.get("rows"), list), "leaderboard rows must be a list", errors)

    summary = payload.get("run_summary")
    require(isinstance(summary, dict), "run_summary must be an object", errors)
    if isinstance(summary, dict):
        missing_summary = sorted(REQUIRED_SUMMARY_FIELDS - set(summary))
        require(not missing_summary, f"run_summary missing fields: {', '.join(missing_summary)}", errors)

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
