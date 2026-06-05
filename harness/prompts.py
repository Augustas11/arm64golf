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


# --- v0.3 post-canary variants ------------------------------------------------
#
# Why these exist: v0.3 produced 105 responses, 54 verified, all at scores
# {18, 24}. Zero 17-instruction candidates. The model can find correct routines
# (substantive PASS-A) but never compresses below the baseline. These variants
# target that ceiling specifically before committing to a 10k PASS-B run.
#
# All three are built on `failed_context` (keep the edge-case + ISA-pitfall
# guard rails) and add an explicit instruction-count discipline that does NOT
# drift when the leaderboard's current best changes — they hard-pin the target
# to 17 instead of `instruction_count - 1`, so even after a 24-instruction
# verified routine becomes the current best, the prompt still asks for 17.

PASS_B_TARGET_BLOCK = """

Hard requirement: your output must contain STRICTLY FEWER than 18
instructions. 17 or fewer is the goal; anything ≥18 is rejected. Count
your instructions before emitting. Each non-blank, non-comment line is
one instruction."""

CSEL_HINT_BLOCK = """

The 18-instruction baseline above uses three 6-instruction compare-swap
blocks (cmp / csetm / eor / and / eor / eor — the bitmask-swap idiom).
A denser pattern exists: ARM64 has `csel` (conditional select). One
compare-swap can be done in 4 instructions using csel directly. For
example, swapping x0 and x1 ascending:

    cmp  x0, x1
    csel x3, x1, x0, le   // x3 = max(x0, x1)
    csel x0, x0, x1, le   // x0 = min(x0, x1)
    mov  x1, x3           // x1 = max

Three such blocks form a sorting network in 12 instructions, leaving
headroom below the 18-instruction baseline. Use csel-based compare-
swaps. Output STRICTLY FEWER than 18 instructions."""

DUAL_EXAMPLE_BLOCK = """

For reference: routines like

    cmp x0, x1
    csetm x3, gt
    eor x4, x0, x1
    and x4, x4, x3
    eor x0, x0, x4
    eor x1, x1, x4
    (... three such blocks, 18 instructions total)

are verified but tie the baseline. Longer verified routines
(24 instructions, using extra moves and intermediate scratch) also
exist but do NOT advance the leaderboard. The goal is STRICTLY
FEWER than 18 instructions. Find a denser structure — likely
cmp + csel pairs rather than the cmp + csetm + eor-bitmask trick."""


ABLATION_TEMPLATES.update(
    {
        "pass_b_target": MAIN_TEMPLATE + FAILED_CONTEXT_BLOCK + PASS_B_TARGET_BLOCK,
        "csel_hint": MAIN_TEMPLATE + FAILED_CONTEXT_BLOCK + CSEL_HINT_BLOCK,
        "dual_example": MAIN_TEMPLATE + FAILED_CONTEXT_BLOCK + DUAL_EXAMPLE_BLOCK,
    }
)


# Templates that should hard-pin target_count to 17 rather than
# `instruction_count - 1`. The drifting target is fine for the original
# failed_context (where the best is the 18-baseline anyway), but harmful
# for the v0.3 variants once non-baseline 24-instruction routines land on
# the leaderboard — without this pin the prompt would start asking for
# "23 instructions" instead of "17", missing the PASS-B threshold.
PASS_B_TARGET_TEMPLATES = frozenset({"pass_b_target", "csel_hint", "dual_example"})
PASS_B_TARGET_COUNT = 17


def build_prompt(assembly: str, instruction_count: int, template: str = "no_failed_context") -> list[dict[str, str]]:
    if template in PASS_B_TARGET_TEMPLATES:
        target_count = PASS_B_TARGET_COUNT
    else:
        target_count = max(instruction_count - 1, 1)
    body = ABLATION_TEMPLATES[template].format(
        assembly=assembly.strip(),
        instruction_count=instruction_count,
        target_count=target_count,
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
