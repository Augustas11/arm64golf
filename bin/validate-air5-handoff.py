#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AIR5_NOTE = REPO_ROOT / "AIR5_OPERATOR_NOTE.md"
OPERATOR_NOTES = REPO_ROOT / "OPERATOR_NOTES.md"

AIR5_REQUIRED_TEXT = [
    "Status: untested-pending-handoff",
    "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "https://api.streamvc.live/v1/chat/completions",
    "X-MacProvider-Provider: air5",
    "Expected download size is roughly 4.5 GB",
    "Expected resident memory during",
    "roughly 5 GB",
    "Serve the coder model in addition to the current default model",
    "If phase3-binary supports only one active model",
    "Do not let arm64golf silently attribute non-coder Qwen responses",
    "curl -fsS https://coordinator.streamvc.live/v1/models",
    "bin/check-air5-model.py --provider-alias m4",
    "https://api.streamvc.live/v1/models",
    "provider id exposed to buyers is `air5`",
    "document the `air5`/`m4` mapping",
    "Preferred kill switch",
    "Emergency kill switch",
    "Coder model downloaded or prewarmed",
    "Kill switch tested or documented as untested-pending-handoff",
]

OPERATOR_REQUIRED_TEXT = [
    "Do not attempt air5 software upgrades, model installs, or phase3-binary",
    "configuration changes from this repo workflow",
    "air5 needs a model download, provider",
    "software upgrade, config edit, reconnect, or kill-switch change",
    "hand that",
    "specific action to Augustas",
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def require_text(path: Path, needles: list[str], errors: list[str]) -> None:
    require(path.exists(), f"{path.name} is missing", errors)
    if not path.exists():
        return
    text = path.read_text()
    for needle in needles:
        require(needle in text, f"{path.name} missing required text: {needle}", errors)


def validate(air5_note: Path = AIR5_NOTE, operator_notes: Path = OPERATOR_NOTES) -> list[str]:
    errors: list[str] = []
    require_text(air5_note, AIR5_REQUIRED_TEXT, errors)
    require_text(operator_notes, OPERATOR_REQUIRED_TEXT, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate arm64golf air5 operator handoff instructions.")
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
