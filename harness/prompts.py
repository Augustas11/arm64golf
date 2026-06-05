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


ABLATION_TEMPLATES = {
    "no_failed_context": MAIN_TEMPLATE,
    "strict_no_memory": MAIN_TEMPLATE
    + "\n\nAny load/store instruction, branch, call, label, directive, or commentary is invalid.",
    "structural_hint": MAIN_TEMPLATE
    + "\n\nPrefer branchless compare/select or conditional-swap structures over control flow.",
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
