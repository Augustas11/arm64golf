from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "sandbox" / "profile.sb"
TMP_ROOT = Path("/private/tmp/arm64golf-sandbox")


def sandbox_available() -> bool:
    return shutil.which("sandbox-exec") is not None and shutil.which("clang") is not None and sys.platform == "darwin"


def run_sandboxed_c(source: str) -> subprocess.CompletedProcess[str]:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="probe-", dir=TMP_ROOT) as tmp:
        tmpdir = Path(tmp)
        c_path = tmpdir / "probe.c"
        exe_path = tmpdir / "probe"
        c_path.write_text(source)
        compile_proc = subprocess.run(
            ["clang", str(c_path), "-o", str(exe_path)],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if compile_proc.returncode != 0:
            raise AssertionError(compile_proc.stderr)
        return subprocess.run(
            ["sandbox-exec", "-f", str(PROFILE), str(exe_path)],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )


@unittest.skipUnless(sandbox_available(), "sandbox-exec is unavailable on this host")
class SandboxProfileTests(unittest.TestCase):
    def test_blocks_filesystem_read_outside_allowlist(self) -> None:
        proc = run_sandboxed_c(
            """
            #include <fcntl.h>
            int main(void) { return open("/etc/passwd", O_RDONLY) >= 0 ? 0 : 1; }
            """
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_filesystem_write_outside_allowlist(self) -> None:
        proc = run_sandboxed_c(
            """
            #include <fcntl.h>
            #include <unistd.h>
            int main(void) { int fd = open("/tmp/arm64golf-forbidden", O_CREAT | O_WRONLY, 0600); return fd >= 0 ? 0 : 1; }
            """
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_network(self) -> None:
        proc = run_sandboxed_c(
            """
            #include <errno.h>
            #include <netinet/in.h>
            #include <string.h>
            #include <sys/socket.h>
            int main(void) {
                int fd = socket(AF_INET, SOCK_STREAM, 0);
                if (fd < 0) return errno == EPERM ? 0 : 2;
                struct sockaddr_in addr;
                memset(&addr, 0, sizeof(addr));
                addr.sin_family = AF_INET;
                addr.sin_port = 9;
                addr.sin_addr.s_addr = 0x0100007f;
                if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0) return 3;
                return errno == EPERM ? 0 : 4;
            }
            """
        )
        self.assertNotIn(proc.returncode, (3, 4), proc.stderr)

    def test_blocks_fork(self) -> None:
        proc = run_sandboxed_c(
            """
            #include <unistd.h>
            int main(void) { return fork() >= 0 ? 0 : 1; }
            """
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_blocks_exec(self) -> None:
        proc = run_sandboxed_c(
            """
            #include <unistd.h>
            int main(void) { char *argv[] = {"/bin/echo", "x", 0}; execv("/bin/echo", argv); return 1; }
            """
        )
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
            timeout=20,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"verified": true', proc.stdout)

    def test_wrong_candidate_fails_native_runner(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".s") as fh:
            fh.write("mov x0, x2\nmov x1, x1\nmov x2, x0\n")
            fh.flush()
            proc = subprocess.run(
                [sys.executable, "sandbox/runner.py", "--candidate", fh.name],
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"verified": false', proc.stdout)

    def test_hanging_candidate_hits_native_timeout(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".s") as fh:
            fh.write("b .\n")
            fh.flush()
            proc = subprocess.run(
                [sys.executable, "sandbox/runner.py", "--candidate", fh.name, "--timeout-ms", "25"],
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["returncode"], 124)
        self.assertEqual(payload["timeout_ms"], 25)

    def test_runner_reports_memory_limit(self) -> None:
        proc = subprocess.run(
            [sys.executable, "sandbox/runner.py", "--memory-limit-mb", "256"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["memory_limit_mb"], 256)
