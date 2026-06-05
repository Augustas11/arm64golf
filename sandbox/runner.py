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


class SandboxUnavailable(RuntimeError):
    pass


def sandbox_available() -> bool:
    return shutil.which("sandbox-exec") is not None and sys.platform == "darwin"


def run_candidate(problem_dir: Path, source: str, timeout_ms: int = 100) -> dict[str, object]:
    if not sandbox_available():
        raise SandboxUnavailable("sandbox-exec is available only on macOS hosts")

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".s", dir=TMP_ROOT, delete=False) as fh:
        fh.write(source)
        candidate_path = Path(fh.name)

    cmd = [
        "sandbox-exec",
        "-f",
        str(PROFILE),
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--problem",
        str(problem_dir),
        "--candidate",
        str(candidate_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Python startup is outside the candidate routine budget in this
            # interpreter-backed Phase 5 runner. Native execution will enforce
            # timeout_ms around the assembled routine itself.
            timeout=max(timeout_ms / 1000, 5),
            check=False,
        )
    finally:
        try:
            candidate_path.unlink()
        except FileNotFoundError:
            pass

    if proc.returncode != 0:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "error": proc.stderr.strip() or proc.stdout.strip(),
        }
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"invalid runner json: {exc}"}


def child_verify(problem_dir: Path, candidate_path: Path) -> dict[str, object]:
    sys.path.insert(0, str(REPO_ROOT))
    from harness.module import load_problem_module

    module = load_problem_module(problem_dir)
    source = candidate_path.read_text()
    candidate = module.load(source)
    verified = module.verify(candidate)
    return {
        "ok": True,
        "verified": verified,
        "problem_id": candidate.problem_id,
        "candidate_hash": candidate.candidate_hash,
        "score": module.score(candidate),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--problem", type=Path, default=REPO_ROOT / "problems" / "sort3-arm64")
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()

    if args.child:
        if args.candidate is None:
            parser.error("--candidate is required in --child mode")
        print(json.dumps(child_verify(args.problem, args.candidate), sort_keys=True))
        return 0

    module_dir = args.problem
    reference = (module_dir / "reference.s").read_text()
    print(json.dumps(run_candidate(module_dir, reference), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
