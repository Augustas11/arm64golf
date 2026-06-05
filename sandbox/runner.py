from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = REPO_ROOT / "sandbox" / "profile.sb"
TMP_ROOT = Path("/private/tmp/arm64golf-sandbox")
DEFAULT_MEMORY_LIMIT_MB = 256


class SandboxUnavailable(RuntimeError):
    pass


def sandbox_available() -> bool:
    return shutil.which("sandbox-exec") is not None and sys.platform == "darwin"


def run_candidate(
    problem_dir: Path,
    source: str,
    timeout_ms: int = 100,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> dict[str, object]:
    if not sandbox_available():
        raise SandboxUnavailable("sandbox-exec is available only on macOS hosts")
    if shutil.which("clang") is None:
        raise SandboxUnavailable("clang is required to assemble native ARM64 candidates")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    if memory_limit_mb <= 0:
        raise ValueError("memory_limit_mb must be positive")

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=TMP_ROOT) as tmp:
        tmpdir = Path(tmp)
        asm_path = tmpdir / "candidate.s"
        main_path = tmpdir / "main.c"
        exe_path = tmpdir / "candidate-test"

        sys.path.insert(0, str(REPO_ROOT))
        from harness.module import load_problem_module

        module = load_problem_module(problem_dir)
        candidate = module.load(source)
        asm_path.write_text(native_assembly(candidate.normalized_source))
        main_path.write_text(
            native_harness_c(module.load_tests(), timeout_ms=timeout_ms, memory_limit_mb=memory_limit_mb)
        )

        compile_proc = subprocess.run(
            ["clang", str(main_path), str(asm_path), "-o", str(exe_path)],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if compile_proc.returncode != 0:
            return {
                "ok": True,
                "verified": False,
                "problem_id": candidate.problem_id,
                "candidate_hash": candidate.candidate_hash,
                "score": module.score(candidate),
                "error": compile_proc.stderr.strip() or compile_proc.stdout.strip(),
            }

        cmd = ["sandbox-exec", "-f", str(PROFILE), str(exe_path)]
        process_timeout_s = max(timeout_ms / 1000 + 1.0, 4.0)
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=process_timeout_s,
            check=False,
        )

        return {
            "ok": True,
            "verified": proc.returncode == 0,
            "problem_id": candidate.problem_id,
            "candidate_hash": candidate.candidate_hash,
            "score": module.score(candidate),
            "returncode": proc.returncode,
            "timeout_ms": timeout_ms,
            "memory_limit_mb": memory_limit_mb,
            "error": proc.stderr.strip() or proc.stdout.strip(),
        }


def native_assembly(candidate_source: str) -> str:
    body = "\n".join(f"    {line}" for line in candidate_source.splitlines() if line.strip())
    return f""".text
.globl _candidate
.p2align 2
_candidate:
{body}
    ret

.globl _run_one
.p2align 2
_run_one:
    stp x29, x30, [sp, #-32]!
    str x19, [sp, #16]
    mov x29, sp
    mov x19, x0
    mov x0, x1
    mov x1, x2
    mov x2, x3
    bl _candidate
    stp x0, x1, [x19]
    str x2, [x19, #16]
    ldr x19, [sp, #16]
    ldp x29, x30, [sp], #32
    ret
"""


def native_harness_c(
    cases: list[dict[str, list[int]]],
    timeout_ms: int = 100,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> str:
    rows = []
    for case in cases:
        values = case["input"] + case["output"]
        rows.append("    {" + ", ".join(c_int64(value) for value in values) + "},")
    joined = "\n".join(rows)
    timeout_sec = timeout_ms // 1000
    timeout_usec = (timeout_ms % 1000) * 1000
    memory_limit_bytes = memory_limit_mb * 1024 * 1024
    return f"""#include <stdint.h>
#include <signal.h>
#include <stdio.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <unistd.h>

extern void run_one(int64_t out[3], int64_t a, int64_t b, int64_t c);

typedef struct {{
    int64_t a;
    int64_t b;
    int64_t c;
    int64_t x;
    int64_t y;
    int64_t z;
}} Case;

static const Case cases[] = {{
{joined}
}};

static void timeout_handler(int signum) {{
    (void)signum;
    _exit(124);
}}

static void arm_timeout(void) {{
    signal(SIGALRM, timeout_handler);
    struct itimerval timer = {{
        .it_value = {{ .tv_sec = {timeout_sec}, .tv_usec = {timeout_usec} }},
        .it_interval = {{ .tv_sec = 0, .tv_usec = 0 }},
    }};
    if (setitimer(ITIMER_REAL, &timer, NULL) != 0) {{
        _exit(125);
    }}
}}

static void cap_memory(void) {{
    const rlim_t limit = (rlim_t){memory_limit_bytes};
    struct rlimit mem = {{ .rlim_cur = limit, .rlim_max = limit }};
#ifdef RLIMIT_AS
    setrlimit(RLIMIT_AS, &mem);
#endif
#ifdef RLIMIT_DATA
    setrlimit(RLIMIT_DATA, &mem);
#endif
}}

int main(void) {{
    cap_memory();
    arm_timeout();
    for (unsigned long i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {{
        int64_t out[3] = {{0, 0, 0}};
        run_one(out, cases[i].a, cases[i].b, cases[i].c);
        if (out[0] != cases[i].x || out[1] != cases[i].y || out[2] != cases[i].z) {{
            fprintf(stderr, "case %lu failed\\n", i);
            return 1;
        }}
    }}
    return 0;
}}
"""


def c_int64(value: int) -> str:
    return f"(int64_t)UINT64_C(0x{value & ((1 << 64) - 1):016x})"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", type=Path, default=REPO_ROOT / "problems" / "sort3-arm64")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--memory-limit-mb", type=int, default=DEFAULT_MEMORY_LIMIT_MB)
    args = parser.parse_args()

    module_dir = args.problem
    source = args.candidate.read_text() if args.candidate else (module_dir / "reference.s").read_text()
    print(
        json.dumps(
            run_candidate(module_dir, source, timeout_ms=args.timeout_ms, memory_limit_mb=args.memory_limit_mb),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
