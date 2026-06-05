from __future__ import annotations


SYSTEM_PROMPT = """You are an ARM64 assembly optimizer.
Return only ARM64 assembly instructions for the requested register ABI.
Do not include markdown, prose, labels, directives, memory access, branches, or calls."""


MAIN_TEMPLATE = """Here is the current best ARM64 routine for sort3 ({instruction_count} instructions).

ABI:
- signed int64 inputs in x0, x1, x2
- ascending outputs in x0, x1, x2
- x3 through x8 may be clobbered
- no memory access
- no branches

Current best:
{assembly}

Propose a variant with {target_count} instructions that still produces sorted output.
Output ONLY the assembly, no commentary."""


# Edge-case block surfaced to the model when the operator runs with
# --template failed_context. v0.1 candidates consistently failed test case 2
# (already-sorted ascending) and test case 1 (all-zero/all-equal) because
# their routines unconditionally swap. Including the sentinel inputs +
# expected outputs inline gives the model the exact failure modes to defeat.
FAILED_CONTEXT_BLOCK = """

Must correctly handle these edge cases (no swaps should occur):
- input x0=0, x1=0, x2=0 -> output x0=0, x1=0, x2=0 (all-equal)
- input x0=1, x1=2, x2=3 -> output x0=1, x1=2, x2=3 (already ascending)
- input x0=-1, x1=0, x2=1 -> output x0=-1, x1=0, x2=1 (signed, ascending)
- input x0=-9223372036854775808, x1=0, x2=9223372036854775807
  -> output x0=-9223372036854775808, x1=0, x2=9223372036854775807 (signed extremes)
Use signed comparisons (gt / lt). Routines that always swap fail the
already-sorted and all-equal cases. ARM64 uses `eor` (NOT `xor` from x86)
and `eor` (NOT `eors`) for register-only xor."""


ABLATION_TEMPLATES = {
    "no_failed_context": MAIN_TEMPLATE,
    "strict_no_memory": MAIN_TEMPLATE
    + "\n\nAny load/store instruction, branch, call, label, directive, or commentary is invalid.",
    "structural_hint": MAIN_TEMPLATE
    + "\n\nPrefer branchless compare/select or conditional-swap structures over control flow.",
    "failed_context": MAIN_TEMPLATE + FAILED_CONTEXT_BLOCK,
}


def build_prompt(assembly: str, instruction_count: int, template: str = "no_failed_context") -> list[dict[str, str]]:
    body = ABLATION_TEMPLATES[template].format(
        assembly=assembly.strip(),
        instruction_count=instruction_count,
        target_count=max(instruction_count - 1, 1),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body},
    ]


def extract_assembly(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped + ("\n" if stripped else "")
