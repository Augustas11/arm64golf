from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.module import Candidate, ResearchProblem, count_instructions, hash_normalized_source, normalize_assembly


PROBLEM_ID = "sort3-arm64"
MODULE_DIR = Path(__file__).resolve().parent
MASK64 = (1 << 64) - 1
SIGN64 = 1 << 63


class VerificationError(ValueError):
    pass


class Sort3Arm64Problem(ResearchProblem):
    problem_id = PROBLEM_ID
    root = MODULE_DIR

    def baseline(self) -> tuple[int, str]:
        source = (self.root / "reference.s").read_text()
        return count_instructions(source), source

    def load(self, submission_blob: str) -> Candidate:
        normalized = normalize_assembly(submission_blob)
        return Candidate(
            problem_id=self.problem_id,
            source=submission_blob,
            normalized_source=normalized,
            candidate_hash=hash_normalized_source(normalized),
            instruction_count=count_instructions(normalized),
            metadata={},
        )

    def verify(self, candidate: Candidate) -> bool:
        try:
            for case in load_tests():
                got = run_candidate(candidate.normalized_source, case["input"])
                if got != case["output"]:
                    return False
        except VerificationError:
            return False
        return True

    def score(self, candidate: Candidate) -> int:
        return candidate.instruction_count


_PROBLEM = Sort3Arm64Problem()


def baseline() -> tuple[int, str]:
    return _PROBLEM.baseline()


def load(submission_blob: str) -> Candidate:
    return _PROBLEM.load(submission_blob)


def verify(candidate: Candidate) -> bool:
    return _PROBLEM.verify(candidate)


def score(candidate: Candidate) -> int:
    return _PROBLEM.score(candidate)


def load_tests() -> list[dict[str, list[int]]]:
    with (MODULE_DIR / "tests.json").open() as fh:
        tests = json.load(fh)
    if not isinstance(tests, list):
        raise VerificationError("tests.json must contain a list")
    return tests


def normalize_source(source: str) -> str:
    return normalize_assembly(source)


def run_candidate(source: str, inputs: Iterable[int]) -> list[int]:
    values = list(inputs)
    if len(values) != 3:
        raise VerificationError("sort3 requires exactly three inputs")

    regs = {f"x{i}": 0 for i in range(31)}
    regs.update({"x0": to_u64(values[0]), "x1": to_u64(values[1]), "x2": to_u64(values[2])})
    cmp_result: int | None = None

    for line in normalize_source(source).splitlines():
        op, operands = parse_instruction(line)
        if op == "cmp":
            lhs, rhs = expect_operands(op, operands, 2)
            cmp_result = to_s64(read_operand(regs, lhs)) - to_s64(read_operand(regs, rhs))
        elif op == "cset":
            dst, cond = expect_operands(op, operands, 2)
            write_reg(regs, dst, 1 if condition_holds(cond, cmp_result) else 0)
        elif op == "csetm":
            dst, cond = expect_operands(op, operands, 2)
            write_reg(regs, dst, MASK64 if condition_holds(cond, cmp_result) else 0)
        elif op == "csel":
            dst, lhs, rhs, cond = expect_operands(op, operands, 4)
            value = read_operand(regs, lhs) if condition_holds(cond, cmp_result) else read_operand(regs, rhs)
            write_reg(regs, dst, value)
        elif op == "neg":
            dst, src = expect_operands(op, operands, 2)
            write_reg(regs, dst, -read_operand(regs, src))
        elif op == "eor":
            dst, lhs, rhs = expect_operands(op, operands, 3)
            write_reg(regs, dst, read_operand(regs, lhs) ^ read_operand(regs, rhs))
        elif op == "and":
            dst, lhs, rhs = expect_operands(op, operands, 3)
            write_reg(regs, dst, read_operand(regs, lhs) & read_operand(regs, rhs))
        elif op == "mov":
            dst, src = expect_operands(op, operands, 2)
            write_reg(regs, dst, read_operand(regs, src))
        elif op == "add":
            dst, lhs, rhs = expect_operands(op, operands, 3)
            write_reg(regs, dst, read_operand(regs, lhs) + read_operand(regs, rhs))
        elif op == "sub":
            dst, lhs, rhs = expect_operands(op, operands, 3)
            write_reg(regs, dst, read_operand(regs, lhs) - read_operand(regs, rhs))
        else:
            raise VerificationError(f"unsupported instruction: {op}")

    return [to_s64(regs["x0"]), to_s64(regs["x1"]), to_s64(regs["x2"])]


def parse_instruction(line: str) -> tuple[str, list[str]]:
    parts = line.split(maxsplit=1)
    op = parts[0].lower()
    operands = [part.strip().lower() for part in parts[1].split(",")] if len(parts) == 2 else []
    return op, operands


def expect_operands(op: str, operands: list[str], count: int) -> list[str]:
    if len(operands) != count:
        raise VerificationError(f"{op} expects {count} operands")
    return operands


def condition_holds(cond: str, cmp_result: int | None) -> bool:
    if cmp_result is None:
        raise VerificationError(f"condition {cond} used before cmp")
    match cond:
        case "gt":
            return cmp_result > 0
        case "ge":
            return cmp_result >= 0
        case "lt":
            return cmp_result < 0
        case "le":
            return cmp_result <= 0
        case "eq":
            return cmp_result == 0
        case "ne":
            return cmp_result != 0
        case _:
            raise VerificationError(f"unsupported condition: {cond}")


def read_operand(regs: dict[str, int], operand: str) -> int:
    if operand == "xzr":
        return 0
    if operand.startswith("#"):
        return int(operand[1:], 0) & MASK64
    if operand not in regs:
        raise VerificationError(f"unsupported register: {operand}")
    return regs[operand]


def write_reg(regs: dict[str, int], reg: str, value: int) -> None:
    if reg == "xzr":
        return
    if reg not in regs:
        raise VerificationError(f"unsupported destination register: {reg}")
    regs[reg] = value & MASK64


def to_u64(value: int) -> int:
    return value & MASK64


def to_s64(value: int) -> int:
    value &= MASK64
    return value - (1 << 64) if value & SIGN64 else value


if __name__ == "__main__":
    base_count, base_source = baseline()
    candidate = load(base_source)
    print(
        json.dumps(
            {
                "problem_id": PROBLEM_ID,
                "baseline_instructions": base_count,
                "candidate_hash": candidate.candidate_hash,
                "verified": verify(candidate),
            },
            sort_keys=True,
        )
    )
