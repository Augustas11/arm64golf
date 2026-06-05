#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SPEC_SECTIONS = [
    "## 1. Goals And Non-goals",
    "## 2. Module Interface",
    "## 3. First Module: `sort3-arm64`",
    "## 4. Inference Path",
    "## 5. Search Loop",
    "## 6. Sandbox",
    "## 7. Receipt Format",
    "## 8. Leaderboard Schema",
    "## 9. Success Criteria",
    "## 10. Out Of Scope",
]

SPEC_NEEDLES = [
    "Can a 7B open-weight coder model, served from a 16GB MacBook Air (air5)",
    "Starting from a textbook 18-instruction ARM64 `sort3`",
    "Does the loop expose any **frontier signal**",
    "No claim about deployment to libc, libc++, compiler runtimes, or any real",
    "baseline()",
    "def load(submission_blob: str) -> Candidate:",
    "def verify(candidate: Candidate) -> bool:",
    "def score(candidate: Candidate) -> int:",
    "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "https://api.streamvc.live/v1/chat/completions",
    "X-MacProvider-Provider: air5",
    "temperature: `0.7`",
    "top_p: `0.95`",
    "\"n\": 8",
    "sandbox-exec",
    "100 ms",
    "256 MB",
    "ed25519",
    "candidate_hash",
    "PASS-A",
    "PASS-B",
    "PASS-C",
    "FAIL",
    "private GitHub repo",
    "public release happens only after explicit launch",
]

README_NEEDLES = [
    "Open-weight coding models on Apple Silicon search the ARM64 sort/hash frontier. Powered by the MacProvider network.",
    "Live leaderboard:",
    "private test preview pending",
    "Public launch is intentionally",
    "## What This Is",
    "AlphaDev",
    "## How To Participate",
    "As a Mac owner",
    "https://github.com/Augustas11/macprovider#for-providers",
    "As a contestant",
    "public submissions are not open in v0.1",
    "https://github.com/Augustas11/arm64golf/issues",
    "## Architecture",
    "X-MacProvider-Provider: air5",
    "ed25519 receipts",
    "## License",
    "MIT",
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def section_order(text: str, sections: list[str], path: str, errors: list[str]) -> None:
    last = -1
    for section in sections:
        index = text.find(section)
        require(index >= 0, f"{path} missing section: {section}", errors)
        if index >= 0:
            require(index > last, f"{path} section is out of order: {section}", errors)
            last = index


def require_needles(text: str, needles: list[str], path: str, errors: list[str]) -> None:
    for needle in needles:
        require(needle in text, f"{path} missing required text: {needle}", errors)


def validate_spec(path: Path = REPO_ROOT / "SPEC.md") -> list[str]:
    errors: list[str] = []
    require(path.exists(), "SPEC.md is missing", errors)
    if not path.exists():
        return errors

    text = path.read_text()
    section_order(text, SPEC_SECTIONS, "SPEC.md", errors)
    require_needles(text, SPEC_NEEDLES, "SPEC.md", errors)
    line_count = len(text.splitlines())
    require(300 <= line_count <= 700, f"SPEC.md should remain roughly 300-600 lines, got {line_count}", errors)
    require(
        "Status: private-test implementation ready; live air5 run pending" in text,
        "SPEC.md must state the current private-test/live-air5-pending status",
        errors,
    )
    require(
        "must not silently switch to another model" in text and "do not switch provider" in text,
        "SPEC.md must forbid silent provider/model switching",
        errors,
    )
    return errors


def validate_readme(path: Path = REPO_ROOT / "README.md") -> list[str]:
    errors: list[str] = []
    require(path.exists(), "README.md is missing", errors)
    if not path.exists():
        return errors

    text = path.read_text()
    require_needles(text, README_NEEDLES, "README.md", errors)
    require(
        not re.search(r"\b(rediscovered|found|discovered)\s+(a\s+)?1[67]-instruction", text, re.IGNORECASE),
        "README.md must not claim a 16/17-instruction result before the live run proves it",
        errors,
    )
    require(
        "currently in private test" in text,
        "README.md must clearly describe the current private-test state",
        errors,
    )
    require(
        "public web page after launch approval" in text,
        "README.md architecture must defer public launch until approval",
        errors,
    )
    return errors


def validate(target: str = "all") -> list[str]:
    errors: list[str] = []
    if target in {"all", "spec"}:
        errors.extend(validate_spec())
    if target in {"all", "readme"}:
        errors.extend(validate_readme())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate arm64golf SPEC.md and README.md contracts.")
    parser.add_argument("--target", choices=["all", "spec", "readme"], default="all")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args()

    errors = validate(args.target)
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
