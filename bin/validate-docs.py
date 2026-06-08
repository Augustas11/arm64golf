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
    "## 11. Open Submission Track (Stage C)",
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
    "*arm64golf is an open, signed leaderboard for the shortest ARM64 routines.*",
    "Live as of 2026-06-08. The challenge is live",
    "## Why this matters",
    "ARM64 powers iPhones, M-series Macs, modern Androids, AWS Graviton servers",
    "AlphaDev (DeepMind, 2023)",
    "No equivalent public ARM64 result exists",
    "## What we'll deliver",
    "A public, append-only log of shortest ARM64 implementations",
    "deterministic verifier and an ed25519 signature",
    "Citeable, immutable hashes that a paper or libc patch can reference",
    "Today the leaderboard is at sort3 with a current best of 12 instructions",
    "AlphaDev never published an ARM64 sort3 number",
    "## How to join",
    "### Host a Mac",
    "https://github.com/Augustas11/macprovider#for-providers",
    "### Write a routine",
    "https://github.com/Augustas11/arm64golf/issues/new?template=open-submission.md",
    "submissions/CONTRIBUTING.md",
    "### Contribute a prompt",
    "prompts/CONTRIBUTING.md",
    "## How verification works",
    "deny-by-default macOS `sandbox-exec` profile against 1200 deterministic test cases",
    "receipts/PUBKEY",
    "## Run it yourself",
    "git clone https://github.com/Augustas11/arm64golf.git",
    ".venv/bin/pytest tests/test_harness.py -q",
    "python3 -m http.server 8765 --directory web",
    "cat web/public/leaderboard.json",
    ".venv/bin/python bin/verify-receipt.py <receipt-path>",
    ".venv/bin/python bin/validate-open-submission-flow.py --json",
    "MACPROVIDER_API_KEY",
    "--allow-marketplace-attribution",
    "## Links",
    "[SPEC.md](SPEC.md)",
    "[REPORT.md](REPORT.md)",
    "[bin/](bin/)",
    "## License",
    "MIT",
]

README_SECTIONS = [
    "# arm64golf",
    "## Why this matters",
    "## What we'll deliver",
    "## How to join",
    "### Host a Mac",
    "### Write a routine",
    "### Contribute a prompt",
    "## How verification works",
    "## Run it yourself",
    "## Links",
    "## License",
]

README_FORBIDDEN_INTERNAL_VOCABULARY = [
    "Private test preview",
    "private test",
    "private preview",
    "v0.1 proof of concept",
    "public submissions are not open",
    "pinned to air5",
    "eventual public research leaderboard",
    "Stage A",
    "Stage B",
    "Stage C",
    "G1",
    "G2",
    "G3",
    "G4",
    "2 providers",
    "2 models",
    "currently 6 pairs",
    "calibration",
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
    require(300 <= line_count <= 850, f"SPEC.md should remain roughly 300-850 lines, got {line_count}", errors)
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
    section_order(text, README_SECTIONS, "README.md", errors)
    require_needles(text, README_NEEDLES, "README.md", errors)
    line_count = len(text.splitlines())
    require(line_count <= 150, f"README.md should stay concise, got {line_count} lines", errors)
    readme_text_lower = text.lower()
    leaked_terms = [
        term for term in README_FORBIDDEN_INTERNAL_VOCABULARY if term.lower() in readme_text_lower
    ]
    require(
        not leaked_terms,
        "README.md leaks internal vocabulary: " + ", ".join(leaked_terms),
        errors,
    )
    require(
        not re.search(r"\b(rediscovered|found|discovered)\s+(a\s+)?1[67]-instruction", text, re.IGNORECASE),
        "README.md must not claim a 16/17-instruction result before the live run proves it",
        errors,
    )
    require(
        "libc has adopted" not in text.lower() and "compiler vendors have adopted" not in text.lower(),
        "README.md must not claim compiler or libc adoption",
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
