#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_DIR = REPO_ROOT / "problems" / "sort3-arm64"
EXPECTED_PROBLEM_ID = "sort3-arm64"
EXPECTED_BASELINE_INSTRUCTIONS = 18
EXPECTED_TIME_BUDGET_MS = 100
EXPECTED_MEMORY_BUDGET_MB = 256

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.module import load_problem_module  # noqa: E402


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_manifest(problem_dir: Path, errors: list[str]) -> int:
    manifest_path = problem_dir / "module.toml"
    require(manifest_path.exists(), "module.toml is missing", errors)
    if not manifest_path.exists():
        return 1000

    try:
        manifest = tomllib.loads(manifest_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"module.toml is invalid TOML: {exc}")
        return 1000

    require(manifest.get("problem_id") == EXPECTED_PROBLEM_ID, "module.toml problem_id must be sort3-arm64", errors)
    require(manifest.get("license") == "MIT", "module.toml license must be MIT", errors)

    hardware = manifest.get("hardware")
    require(isinstance(hardware, dict), "module.toml [hardware] section is missing", errors)
    if isinstance(hardware, dict):
        require(hardware.get("arch") == "arm64", "module.toml hardware.arch must be arm64", errors)
        require(hardware.get("os") == "macos", "module.toml hardware.os must be macos", errors)

    eval_config = manifest.get("eval")
    require(isinstance(eval_config, dict), "module.toml [eval] section is missing", errors)
    min_tests = 1000
    if isinstance(eval_config, dict):
        require(
            eval_config.get("time_budget_ms") == EXPECTED_TIME_BUDGET_MS,
            f"module.toml eval.time_budget_ms must be {EXPECTED_TIME_BUDGET_MS}",
            errors,
        )
        require(
            eval_config.get("memory_budget_mb") == EXPECTED_MEMORY_BUDGET_MB,
            f"module.toml eval.memory_budget_mb must be {EXPECTED_MEMORY_BUDGET_MB}",
            errors,
        )
        min_tests_raw = eval_config.get("min_tests", 1000)
        require(isinstance(min_tests_raw, int), "module.toml eval.min_tests must be an integer", errors)
        if isinstance(min_tests_raw, int):
            min_tests = min_tests_raw
            require(min_tests >= 1000, "module.toml eval.min_tests must be at least 1000", errors)

    sandbox = manifest.get("sandbox")
    require(isinstance(sandbox, dict), "module.toml [sandbox] section is missing", errors)
    if isinstance(sandbox, dict):
        profile = sandbox.get("profile")
        require(isinstance(profile, str) and bool(profile), "module.toml sandbox.profile must be set", errors)
        if isinstance(profile, str) and profile:
            require((problem_dir / profile).resolve().exists(), f"sandbox profile does not exist: {profile}", errors)
        require(sandbox.get("filesystem") == "deny", "module.toml sandbox.filesystem must be deny", errors)
        require(sandbox.get("network") == "deny", "module.toml sandbox.network must be deny", errors)
        require(sandbox.get("process_spawn") == "deny", "module.toml sandbox.process_spawn must be deny", errors)

    return min_tests


def validate_tests(problem_dir: Path, min_tests: int, errors: list[str]) -> None:
    tests_path = problem_dir / "tests.json"
    require(tests_path.exists(), "tests.json is missing", errors)
    if not tests_path.exists():
        return

    try:
        tests = load_json(tests_path)
    except ValueError as exc:
        errors.append(str(exc))
        return

    require(isinstance(tests, list), "tests.json must contain a list", errors)
    if not isinstance(tests, list):
        return

    require(len(tests) >= min_tests, f"tests.json must contain at least {min_tests} cases", errors)
    for index, case in enumerate(tests, start=1):
        require(isinstance(case, dict), f"test case {index} must be an object", errors)
        if not isinstance(case, dict):
            continue
        inputs = case.get("input")
        outputs = case.get("output")
        require(isinstance(inputs, list) and len(inputs) == 3, f"test case {index} input must be a triple", errors)
        require(isinstance(outputs, list) and len(outputs) == 3, f"test case {index} output must be a triple", errors)
        if isinstance(inputs, list):
            require(all(isinstance(value, int) for value in inputs), f"test case {index} input values must be integers", errors)
        if isinstance(outputs, list):
            require(all(isinstance(value, int) for value in outputs), f"test case {index} output values must be integers", errors)
        if isinstance(inputs, list) and isinstance(outputs, list) and len(inputs) == 3 and len(outputs) == 3:
            require(outputs == sorted(inputs), f"test case {index} output must be sorted(input)", errors)


def validate_module_behavior(problem_dir: Path, errors: list[str]) -> None:
    for required in ["reference.s", "reference_source.c", "module.py"]:
        require((problem_dir / required).exists(), f"{required} is missing", errors)

    if not (problem_dir / "module.py").exists() or not (problem_dir / "reference.s").exists():
        return

    try:
        module = load_problem_module(problem_dir)
        baseline_count, baseline_source = module.baseline()
        candidate = module.load(baseline_source)
        verified = module.verify(candidate)
        score = module.score(candidate)
    except Exception as exc:  # noqa: BLE001 - validator should report all module import/behavior failures.
        errors.append(f"sort3 module behavior check failed: {exc}")
        return

    require(
        baseline_count == EXPECTED_BASELINE_INSTRUCTIONS,
        f"baseline() must report {EXPECTED_BASELINE_INSTRUCTIONS} instructions",
        errors,
    )
    require(
        candidate.instruction_count == EXPECTED_BASELINE_INSTRUCTIONS,
        f"loaded reference candidate must have {EXPECTED_BASELINE_INSTRUCTIONS} instructions",
        errors,
    )
    require(score == EXPECTED_BASELINE_INSTRUCTIONS, f"score(reference) must be {EXPECTED_BASELINE_INSTRUCTIONS}", errors)
    require(bool(verified), "reference candidate must verify against all tests", errors)


def validate(problem_dir: Path) -> list[str]:
    errors: list[str] = []
    min_tests = validate_manifest(problem_dir, errors)
    validate_tests(problem_dir, min_tests, errors)
    validate_module_behavior(problem_dir, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the sort3-arm64 problem module contract.")
    parser.add_argument("--problem-dir", type=Path, default=PROBLEM_DIR)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args()

    errors = validate(args.problem_dir)
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
