from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "sandbox" / "profile.sb"


def sandbox_available() -> bool:
    return shutil.which("sandbox-exec") is not None and sys.platform == "darwin"


@unittest.skipUnless(sandbox_available(), "sandbox-exec is unavailable on this host")
class SandboxProfileTests(unittest.TestCase):
    def run_sandboxed_python(self, code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sandbox-exec", "-f", str(PROFILE), sys.executable, "-c", code],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )

    def test_blocks_filesystem_read_outside_allowlist(self) -> None:
        proc = self.run_sandboxed_python("open('/etc/passwd').read()")
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_filesystem_write_outside_allowlist(self) -> None:
        proc = self.run_sandboxed_python("open('/tmp/arm64golf-forbidden', 'w').write('x')")
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_network(self) -> None:
        proc = self.run_sandboxed_python(
            "import socket; socket.create_connection(('127.0.0.1', 9), timeout=0.1)"
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_fork(self) -> None:
        proc = self.run_sandboxed_python("import os; os.fork()")
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_exec(self) -> None:
        proc = self.run_sandboxed_python("import os; os.execv('/bin/echo', ['/bin/echo', 'x'])")
        self.assertNotEqual(proc.returncode, 0)


@unittest.skipUnless(sandbox_available(), "sandbox-exec is unavailable on this host")
class SandboxRunnerTests(unittest.TestCase):
    def test_reference_runs_through_sandbox_runner(self) -> None:
        proc = subprocess.run(
            [sys.executable, "sandbox/runner.py"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"verified": true', proc.stdout)
