from __future__ import annotations

from hashlib import sha256


SYSTEM_PROMPT = """You are an ARM64 assembly optimizer.
Return only ARM64 assembly instructions for the requested register ABI.
Do not include markdown, prose, labels, directives, memory access, branches, or calls."""


# Chain-of-thought variants need to violate two rules from the default
# system prompt — "no prose" and "no markdown" — because the whole point
# of CoT is that the model reasons in prose and emits the final assembly
# in a fenced code block at the end. The CoT system prompt allows prose
# + a single trailing fenced block, but keeps the ABI restrictions
# (registers, no memory access, no branches, no calls).
COT_SYSTEM_PROMPT = """You are an ARM64 assembly optimizer working through a reasoning task.
You may explain your reasoning in prose. Your FINAL answer must be a single fenced
code block containing only ARM64 assembly: no labels, no directives, no memory
access, no branches, no calls. The fenced block must be the last content in your
response."""


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


# Chain-of-thought variant. The temperature sweep (commit f0e4e95) ruled
# out sampling as the binding constraint on the 12-instruction floor — no
# new structures appeared across temp ∈ {0.3, 0.5, 0.9}. The remaining
# cheap prompt experiment is whether STRUCTURED REASONING in the prompt
# lets the model find an instruction to fuse or eliminate. CoT asks the
# model to (1) annotate the current best block-by-block, (2) find a
# redundancy, (3) propose a denser variant. The reasoning lives in the
# response body; the final assembly lives in a fenced code block at the
# end — extract_assembly() now pulls the last fenced block.
#
# Going-in prior: ~15% this breaks 12. CoT can extract one or two saved
# instructions if a denser pattern is adjacent in the model's training
# distribution; it's unlikely to surface fundamentally new structure that
# 200+ dual_example samples plus a temperature sweep failed to find. The
# probe is informative either way: a null result closes the prompt-
# sophistication question on 7B and routes the next experiment to the
# marketplace (different model, same harness).

CHAIN_OF_THOUGHT_BLOCK = """

This task is hard. Reason through it explicitly before emitting code.

Step 1 — annotate the current best. For each block of instructions in
the current routine, write one short line naming:
- what comparison the block implements (which pair of inputs)
- which registers it reads, mutates, and leaves untouched
- whether the block's output is logically necessary given the
  comparators already executed before it

Step 2 — find a redundancy. Identify the single instruction (or pair of
instructions) most likely to be eliminable. Candidates include:
- a `mov` that copies a value that's already in the destination
- a compare-swap that's logically implied by prior compare-swaps
- two consecutive csel writes to the same register that can be fused
- the third comparator in a three-comparator network, when the second
  comparator already guarantees the relevant ordering

Step 3 — produce the dense variant. Output the final routine in a
fenced code block at the END of your response, surrounded by triple
backticks. The block must contain ONLY ARM64 assembly — no comments,
no markdown, no language tag. The block must be strictly fewer than
{instruction_count} instructions.

Format:

(your annotation + redundancy analysis as prose)

```
cmp x0, x1
...
```"""


# CoT can't share MAIN_TEMPLATE's "Output ONLY the assembly, no commentary"
# tail line — that contradicts the CoT block's "reason through it explicitly"
# directive. Build CoT from MAIN_TEMPLATE without that final line so the only
# instructions the model sees about output shape come from the CoT block.
_MAIN_TEMPLATE_WITHOUT_OUTPUT_RULE = MAIN_TEMPLATE.rsplit("\n", 1)[0]
assert _MAIN_TEMPLATE_WITHOUT_OUTPUT_RULE.endswith("instructions that still produces sorted output.")

ABLATION_TEMPLATES["chain_of_thought"] = (
    _MAIN_TEMPLATE_WITHOUT_OUTPUT_RULE + FAILED_CONTEXT_BLOCK + CHAIN_OF_THOUGHT_BLOCK
)


# Templates that should hard-pin target_count to 17 rather than
# `instruction_count - 1`. The drifting target is fine for the original
# failed_context (where the best is the 18-baseline anyway), but harmful
# for the v0.3 variants once non-baseline 24-instruction routines land on
# the leaderboard — without this pin the prompt would start asking for
# "23 instructions" instead of "17", missing the PASS-B threshold.
PASS_B_TARGET_TEMPLATES = frozenset({"pass_b_target", "csel_hint", "dual_example", "chain_of_thought"})
PASS_B_TARGET_COUNT = 17


def template_id(name: str) -> str:
    # A 16-hex sha256 prefix is sufficient for the current registry
    # (<100 templates). Extend this to 32 hex if the template registry grows
    # past that size.
    body = ABLATION_TEMPLATES[name]
    if name == "chain_of_thought":
        body = COT_SYSTEM_PROMPT + body
    return sha256(body.encode("utf-8")).hexdigest()[:16]


def ensure_distinct_template_ids() -> None:
    seen: dict[str, str] = {}
    for name in ABLATION_TEMPLATES:
        current_id = template_id(name)
        previous = seen.get(current_id)
        if previous is not None:
            raise ValueError(f"template_id collision: {previous!r} and {name!r} both map to {current_id}")
        seen[current_id] = name


def build_prompt(assembly: str, instruction_count: int, template: str = "no_failed_context") -> list[dict[str, str]]:
    if template in PASS_B_TARGET_TEMPLATES:
        # Floor at PASS-B threshold (17) when current best is at or above
        # the baseline, but track strictly below the best once we cross
        # into PASS-B/PASS-C territory. Without the min(), a probe run
        # against current best = 12 would still ask the model for "17
        # instructions" — i.e. a worse routine.
        target_count = max(min(instruction_count - 1, PASS_B_TARGET_COUNT), 1)
    else:
        target_count = max(instruction_count - 1, 1)
    body = ABLATION_TEMPLATES[template].format(
        assembly=assembly.strip(),
        instruction_count=instruction_count,
        target_count=target_count,
    )
    system_prompt = COT_SYSTEM_PROMPT if template == "chain_of_thought" else SYSTEM_PROMPT
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": body},
    ]


def extract_assembly(text: str) -> str:
    """Pull ARM64 assembly out of a chat-completion response.

    Three cases, in order:

    1. Response is a single fenced block (possibly with a language tag like
       ```asm`): strip the outer fences. (Original v0.1 behavior.)
    2. Response contains a fenced block somewhere — typically a CoT prompt
       where the model emits reasoning prose followed by ```...``` with
       the final assembly. Use the contents of the LAST fenced block: the
       model is told to put its final answer last, and the last fence is
       the only one we can extract unambiguously when the response also
       includes inline examples mid-reasoning.
    3. No fences — return the stripped text verbatim. The verifier will
       reject if it's not valid assembly.

    Returning the trailing newline matches the v0.1 candidate-loader's
    expectation that the source ends in '\\n' for hash normalization.
    """
    stripped = text.strip()
    if not stripped:
        return ""

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
        return stripped + ("\n" if stripped else "")

    # Case 2: scan for fenced blocks anywhere in the response.
    fence_starts = [i for i, line in enumerate(text.splitlines()) if line.lstrip().startswith("```")]
    if len(fence_starts) >= 2:
        lines = text.splitlines()
        # Last fenced block runs from the second-to-last ``` to the last ```.
        start = fence_starts[-2] + 1
        end = fence_starts[-1]
        body = "\n".join(lines[start:end]).strip()
        if body:
            return body + "\n"

    return stripped + "\n"
