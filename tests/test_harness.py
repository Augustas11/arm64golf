from __future__ import annotations

import io
import json
import importlib
import importlib.util
import subprocess
import sys
import threading
from hashlib import sha256
from pathlib import Path

import pytest

from harness.attest import sign_receipt, verify_receipt
from harness import attest as attest_module
from harness.store import SEED_MODEL_ID, SEED_PROVIDER_ID
from harness.loop import main as loop_main
from harness.inference import (
    BurstThrottledError,
    InferenceConfig,
    InferenceError,
    MacProviderClient,
    QuotaExhaustedError,
    parse_chat_response,
    parse_stream_response,
)
from harness import inference as inference_module
from harness.module import load_problem_module
from harness.store import Store


def load_script(path: str):
    spec = importlib.util.spec_from_file_location(path.replace("/", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repeating_clock(values: list[float]):
    iterator = iter(values)
    last_seen: float | None = None

    def now() -> float:
        nonlocal last_seen
        try:
            last_seen = next(iterator)
        except StopIteration:
            if last_seen is None:
                raise
        return last_seen

    return now


def test_load_sort3_module_and_verify_baseline() -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    assert count == 18
    assert candidate.instruction_count == 18
    assert module.verify(candidate)


def test_validate_sort3_module_accepts_current_contract() -> None:
    script = load_script("bin/validate-sort3-module.py")
    assert script.validate(Path("problems/sort3-arm64")) == []


def test_validate_sort3_module_rejects_too_few_tests(tmp_path: Path) -> None:
    script = load_script("bin/validate-sort3-module.py")
    problem_dir = tmp_path / "sort3-arm64"
    problem_dir.mkdir()
    (problem_dir / "module.toml").write_text(Path("problems/sort3-arm64/module.toml").read_text())
    (problem_dir / "tests.json").write_text(json.dumps([{"input": [3, 1, 2], "output": [1, 2, 3]}]))

    errors = script.validate(problem_dir)
    assert any("at least 1000 cases" in error for error in errors)


def test_validate_harness_smoke_accepts_successful_loop(tmp_path: Path, monkeypatch) -> None:
    script = load_script("bin/validate-harness-smoke.py")
    leaderboard = tmp_path / "leaderboard.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    leaderboard.write_text(
        json.dumps(
            {
                "problem_id": "sort3-arm64",
                "attempt_count": 1,
                "requested_candidate_count": 1,
                "candidate_response_count": 1,
                "run_summary": {
                    "evaluation_count": 1,
                    "verified_evaluation_count": 1,
                    "failed_evaluation_count": 0,
                    "evaluation_error_count": 0,
                    "best_verified_score": 18,
                    "first_verified_response": 1,
                },
                "rows": [
                    {
                        "score": 18,
                        "model_id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
                        "provider_id": "air5",
                        "receipt_signature": "signature",
                    }
                ],
            }
        )
    )

    monkeypatch.setattr(script.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(script, "run_loop_smoke", lambda workdir: (0, "", leaderboard, receipts))
    monkeypatch.setattr(script, "run", lambda cmd, timeout_s=60.0: (0, '{"ok": true, "errors": []}'))

    assert script.validate() == []


def test_validate_live_run_contract_accepts_current_loop() -> None:
    script = load_script("bin/validate-live-run-contract.py")
    assert script.validate() == []


def test_validate_sandbox_accepts_successful_contract(monkeypatch) -> None:
    script = load_script("bin/validate-sandbox.py")
    monkeypatch.setattr(script.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, timeout_s=60.0):
        if cmd == [script.python_executable(), "-m", "pytest", "-q", str(script.TESTS)]:
            return 0, "9 passed"
        if cmd == [script.python_executable(), str(script.RUNNER)]:
            return (
                0,
                json.dumps(
                    {
                        "ok": True,
                        "verified": True,
                        "score": 18,
                        "timeout_ms": 100,
                        "memory_limit_mb": 256,
                    }
                ),
            )
        raise AssertionError(cmd)

    monkeypatch.setattr(script, "run", fake_run)
    assert script.validate() == []


def test_validate_inference_config_accepts_current_request_contract() -> None:
    script = load_script("bin/validate-inference-config.py")
    assert script.validate() == []


def test_validate_docs_accepts_current_contract() -> None:
    script = load_script("bin/validate-docs.py")
    assert script.validate("all") == []


def test_validate_docs_rejects_premature_readme_result_claim(tmp_path: Path) -> None:
    script = load_script("bin/validate-docs.py")
    readme = tmp_path / "README.md"
    readme.write_text(Path("README.md").read_text() + "\nWe discovered a 17-instruction result.\n")

    errors = script.validate_readme(readme)
    assert any("must not claim" in error for error in errors)


def test_validate_report_accepts_current_report() -> None:
    script = load_script("bin/validate-report.py")
    assert script.validate() == []


def test_validate_report_rejects_stale_report(tmp_path: Path, monkeypatch) -> None:
    """A trailing hand-edit appended after the ledger sections must be
    rejected: post-live, the validator requires REPORT.md to *end*
    with bin/write-report.py output verbatim. Hand-edits live above
    `## Verdict`, not below `## PASS/FAIL Criteria`."""
    script = load_script("bin/validate-report.py")
    stale_report = tmp_path / "REPORT.md"
    stale_report.write_text(Path("REPORT.md").read_text() + "\nmanual stale edit\n")
    monkeypatch.setattr(script, "REPORT", stale_report)

    errors = script.validate()
    assert any("must end with" in error or "auto body cannot drift" in error for error in errors)


def test_validate_report_rejects_seed_air5_attribution(tmp_path: Path, monkeypatch) -> None:
    """Pre-live (candidate_response_count == 0), the seed row must stay
    attributed to reference-baseline/local-harness. After a real run
    lands, live attribution on row 0 is legitimate (the model can
    rediscover the baseline), so this assertion only applies pre-live —
    we force candidate_response_count=0 in the fixture to keep the
    test honest."""
    script = load_script("bin/validate-report.py")
    leaderboard = tmp_path / "leaderboard.json"
    payload = json.loads(Path("web/public/leaderboard.json").read_text())
    payload["candidate_response_count"] = 0
    if isinstance(payload.get("run_summary"), dict):
        payload["run_summary"]["candidate_response_count"] = 0
    payload["rows"][0]["model_id"] = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
    payload["rows"][0]["provider_id"] = "air5"
    leaderboard.write_text(json.dumps(payload))
    monkeypatch.setattr(script, "LEADERBOARD", leaderboard)

    errors = script.validate()
    assert any("must not claim" in error for error in errors)


def test_validate_air5_handoff_accepts_current_contract() -> None:
    script = load_script("bin/validate-air5-handoff.py")
    assert script.validate() == []


def test_validate_air5_handoff_requires_no_touch_operator_boundary(tmp_path: Path) -> None:
    script = load_script("bin/validate-air5-handoff.py")
    operator_notes = tmp_path / "OPERATOR_NOTES.md"
    operator_notes.write_text("missing owner coordination rule\n")

    errors = script.validate(operator_notes=operator_notes)
    assert any("specific action to Augustas" in error for error in errors)


def _capture_request_body(monkeypatch, client: MacProviderClient) -> dict:
    captured: list[dict] = []

    class FakeResponse:
        lines = [
            b'data: {"choices":[{"delta":{"content":"ret\\n"},"finish_reason":null}]}\n',
            b"\n",
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        def __init__(self) -> None:
            self.index = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            if self.index >= len(self.lines):
                return b""
            line = self.lines[self.index]
            self.index += 1
            return line

    def fake_urlopen(req, timeout):
        captured.append(json.loads(req.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(inference_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(inference_module.time, "sleep", lambda s: None)
    client.complete([{"role": "user", "content": "candidate?"}])
    assert captured
    return captured[0]


def test_inference_config_caps_max_tokens_at_256(monkeypatch) -> None:
    """v0.3 pins per-call output at 256 tokens; SSE streaming keeps the
    gateway header timeout from being a load-bearing knob."""
    assert InferenceConfig().max_tokens == 256
    client = MacProviderClient("test-key", InferenceConfig(n=1))
    body = _capture_request_body(monkeypatch, client)
    assert body["max_tokens"] == 256
    assert body["stream"] is True


def test_inference_config_max_tokens_is_overridable(monkeypatch) -> None:
    """The cap must be overridable so probes / ablations can scale it."""
    client = MacProviderClient("test-key", InferenceConfig(n=1, max_tokens=128))
    body = _capture_request_body(monkeypatch, client)
    assert body["max_tokens"] == 128


def test_parse_chat_response_returns_all_choices() -> None:
    raw = b'{"choices":[{"message":{"content":"cmp x0, x1"}},{"message":{"content":"ret"}}]}'
    assert parse_chat_response(raw) == ["cmp x0, x1", "ret"]


def test_parse_chat_response_rejects_malformed_payload() -> None:
    with pytest.raises(InferenceError):
        parse_chat_response(b'{"choices":[{}]}')


def test_parse_stream_response_accumulates_single_choice() -> None:
    raw = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"cmp x0, x1\\n"},"finish_reason":null}]}',
            "",
            'data: {"choices":[{"delta":{"content":"ret\\n"},"finish_reason":null}]}',
            "",
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    assert parse_stream_response(raw) == ["cmp x0, x1\nret\n"]


def test_parse_stream_response_handles_openai_role_and_usage_frames() -> None:
    # Real-world MacProvider/OpenAI shape: leading role-only delta with empty
    # content, content delta, stop delta, then a usage-only frame with
    # `choices: []`. The usage frame is a legitimate protocol frame and must
    # not be classified as malformed_response.
    raw = "\n".join(
        [
            'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}',
            "",
            'data: {"choices":[{"index":0,"delta":{"content":"cmp x0, x1"},"finish_reason":null}]}',
            "",
            'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
            "",
            'data: {"choices":[],"usage":{"total_tokens":35,"prompt_tokens":34,"completion_tokens":1}}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    assert parse_stream_response(raw) == ["cmp x0, x1"]


def test_parse_stream_response_reassembles_multiline_sse_event() -> None:
    raw = "\n".join(
        [
            'data: {"choices":',
            'data: [{"delta":{"content":"cmp"},"finish_reason":null}]}',
            "",
            "event: ignored",
            "id: ignored",
            "retry: 1000",
            ": comment",
            "data: [DONE]",
            "",
        ]
    )
    assert parse_stream_response(raw) == ["cmp"]


def test_parse_stream_response_classifies_truncation() -> None:
    with pytest.raises(InferenceError) as exc_info:
        parse_stream_response('data: {"choices":[{"delta":{"content":"cmp"}}]}\n')
    assert exc_info.value.kind == "stream_truncated"

    with pytest.raises(InferenceError) as bad_json:
        parse_stream_response('data: {"choices":[{"delta":\n\n')
    assert bad_json.value.kind == "stream_truncated"


def test_parse_stream_response_requires_done_after_finish_reason() -> None:
    raw = "\n".join(
        [
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "",
        ]
    )
    with pytest.raises(InferenceError) as exc_info:
        parse_stream_response(raw)
    assert exc_info.value.kind == "stream_truncated"


def test_parse_stream_response_routes_in_band_quota_error() -> None:
    raw = "\n".join(
        [
            'data: {"error":{"code":"quota_exhausted","message":"daily quota exhausted"}}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    with pytest.raises(QuotaExhaustedError) as exc_info:
        parse_stream_response(raw)
    assert exc_info.value.kind == "quota_exhausted"
    assert "daily quota exhausted" in str(exc_info.value)


def test_parse_stream_response_routes_in_band_burst_error() -> None:
    raw = "\n".join(
        [
            'data: {"error":{"code":"rate_limited","message":"slow down"}}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    with pytest.raises(BurstThrottledError) as exc_info:
        parse_stream_response(raw)
    assert exc_info.value.kind == "burst_throttled"
    assert "slow down" in str(exc_info.value)


def test_parse_stream_response_routes_in_band_server_error_without_code() -> None:
    raw = "\n".join(
        [
            'data: {"error":{"message":"boom"}}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    with pytest.raises(InferenceError) as exc_info:
        parse_stream_response(raw)
    assert exc_info.value.kind == "server_error"
    assert "boom" in str(exc_info.value)


def test_parse_stream_response_routes_in_band_server_error_for_unknown_code() -> None:
    raw = "\n".join(
        [
            'data: {"error":{"code":"n_must_be_1","message":"bad n"}}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    with pytest.raises(InferenceError) as exc_info:
        parse_stream_response(raw)
    assert exc_info.value.kind == "server_error"
    assert "bad n" in str(exc_info.value)


def test_parse_stream_response_sanitizes_in_band_server_error_message() -> None:
    server_message = ("a" * 4998) + "\n\x07"
    assert len(server_message) == 5000
    raw = "\n".join(
        [
            "data: " + json.dumps({"error": {"message": server_message}}),
            "",
            "data: [DONE]",
            "",
        ]
    )
    with pytest.raises(InferenceError) as exc_info:
        parse_stream_response(raw)
    message = str(exc_info.value)
    assert exc_info.value.kind == "server_error"
    assert len(message) <= 250
    assert not any((ord(char) < 32 or ord(char) == 127) for char in message)


def test_stream_truncation_surfaces_from_client(monkeypatch) -> None:
    class FakeResponse:
        lines = [
            b'data: {"choices":[{"delta":{"content":"cmp"},"finish_reason":null}]}\n',
        ]

        def __init__(self) -> None:
            self.index = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            if self.index >= len(self.lines):
                return b""
            line = self.lines[self.index]
            self.index += 1
            return line

    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", InferenceConfig(n=1)).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_truncated"


def test_stream_total_deadline_surfaces_from_client(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            return b'data: {"choices":[{"delta":{"content":"cmp"},"finish_reason":null}]}\n'

    monkeypatch.setattr(inference_module.time, "monotonic", _repeating_clock([0.0, 0.0, 2.0]))
    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    config = InferenceConfig(n=1, stream_total_timeout_s=1.0, stream_idle_timeout_s=10.0)
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", config).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_truncated"
    assert "total deadline" in str(exc_info.value)


def test_stream_total_deadline_surfaces_when_readline_times_out(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            raise TimeoutError("read timed out")

    monkeypatch.setattr(inference_module.time, "monotonic", _repeating_clock([0.0, 0.0, 0.0, 0.75]))
    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    config = InferenceConfig(n=1, stream_total_timeout_s=0.5, stream_idle_timeout_s=10.0)
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", config).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_truncated"
    assert "total deadline" in str(exc_info.value)


def test_stream_idle_timeout_surfaces_from_client(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            return b'data: {"choices":[{"delta":{"content":"cmp"},"finish_reason":null}]}\n'

    monkeypatch.setattr(inference_module.time, "monotonic", _repeating_clock([0.0, 0.0, 2.0]))
    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    config = InferenceConfig(n=1, stream_total_timeout_s=10.0, stream_idle_timeout_s=1.0)
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", config).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_idle_timeout"


def test_retry_sleep_respects_stream_total_deadline(monkeypatch) -> None:
    slept: list[float] = []

    def fake_urlopen(req, timeout):
        raise inference_module.urllib.error.HTTPError(
            req.full_url,
            429,
            "too many requests",
            {},
            io.BytesIO(b'{"error":{"code":"rate_limited"}}'),
        )

    monkeypatch.setattr(inference_module.time, "monotonic", _repeating_clock([0.0, 0.0, 0.75]))
    monkeypatch.setattr(inference_module.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(inference_module.urllib.request, "urlopen", fake_urlopen)
    config = InferenceConfig(n=1, max_retries=1, stream_total_timeout_s=1.0, stream_idle_timeout_s=10.0)
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", config).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_truncated"
    assert slept == []


def test_stream_read_oserror_surfaces_as_stream_truncated(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            raise ConnectionResetError("reset")

    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", InferenceConfig(n=1)).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_truncated"


def test_stream_decode_error_surfaces_as_malformed_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            return b"\xff\n"

    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", InferenceConfig(n=1)).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "malformed_response"


def test_stream_max_bytes_cap_surfaces_from_client(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            return b'data: {"choices":[{"delta":{"content":"cmp"},"finish_reason":null}]}\n'

    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    config = InferenceConfig(n=1, stream_max_bytes=10)
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", config).complete([{"role": "user", "content": "candidate?"}])
    assert exc_info.value.kind == "stream_truncated"
    assert "byte cap" in str(exc_info.value)


def test_stream_max_line_cap_surfaces_from_client(monkeypatch) -> None:
    observed_sizes: list[int] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def readline(self, size=-1):
            observed_sizes.append(size)
            return b"x" * size

    monkeypatch.setattr(inference_module.urllib.request, "urlopen", lambda req, timeout: FakeResponse())
    config = InferenceConfig(n=1, stream_max_line_bytes=8)
    with pytest.raises(InferenceError) as exc_info:
        MacProviderClient("test-key", config).complete([{"role": "user", "content": "candidate?"}])
    assert observed_sizes == [8]
    assert exc_info.value.kind == "stream_truncated"
    assert "line cap" in str(exc_info.value)


def test_store_exports_leaderboard(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.record_candidate(
        candidate_hash="abc123",
        problem_id="sort3-arm64",
        source="cmp x0, x1\n",
        score=17,
        verified=True,
        model_id="model",
        provider_id="air5",
    )
    store.record_attempt("sort3-arm64", "template", "ok", requested_n=8, response_count=6)
    store.record_evaluation(
        attempt_id=1,
        problem_id="sort3-arm64",
        candidate_hash="abc123",
        score=17,
        verified=True,
    )
    store.record_receipt("abc123", tmp_path / "receipt.json", "signature")
    out = tmp_path / "leaderboard.json"
    store.export_leaderboard("sort3-arm64", out)
    payload = json.loads(out.read_text())
    assert payload["attempt_count"] == 1
    assert payload["requested_candidate_count"] == 8
    assert payload["candidate_response_count"] == 6
    assert payload["run_summary"]["evaluation_count"] == 1
    assert payload["run_summary"]["failed_evaluation_count"] == 0
    assert payload["run_summary"]["evaluation_error_count"] == 0
    assert payload["run_summary"]["first_17_response"] == 1
    assert payload["last_update"]
    assert payload["rows"][0]["rank"] == 1
    assert payload["rows"][0]["score"] == 17
    assert payload["rows"][0]["receipt_signature"] == "signature"
    store.close()


def test_store_preserves_first_candidate_discovery_and_updates_receipt(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.record_candidate(
        candidate_hash="abc123",
        problem_id="sort3-arm64",
        source="cmp x0, x1\n",
        score=18,
        verified=False,
        model_id="model-a",
        provider_id="air5",
    )
    first = store.best_candidate("sort3-arm64")
    assert first is None

    store.record_candidate(
        candidate_hash="abc123",
        problem_id="sort3-arm64",
        source="cmp x0, x1\nmov x2, x2\n",
        score=17,
        verified=True,
        model_id="model-b",
        provider_id="air6",
    )
    best = store.best_candidate("sort3-arm64")
    assert best is not None
    first_discovered = best["discovered_at"]
    assert best["score"] == 18
    assert best["model_id"] == "model-a"
    assert best["provider_id"] == "air5"

    store.record_candidate(
        candidate_hash="abc123",
        problem_id="sort3-arm64",
        source="cmp x0, x1\nmov x2, x2\n",
        score=17,
        verified=True,
        model_id="model-b",
        provider_id="air6",
    )
    again = store.best_candidate("sort3-arm64")
    assert again is not None
    assert again["discovered_at"] == first_discovered

    store.record_receipt("abc123", tmp_path / "first.json", "first-signature")
    store.record_receipt("abc123", tmp_path / "second.json", "second-signature")
    rows = store.leaderboard("sort3-arm64")
    assert rows[0]["receipt_signature"] == "second-signature"
    store.close()


def test_store_replaces_seed_attribution_after_verified_model_response(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.record_candidate(
        candidate_hash="abc123",
        problem_id="sort3-arm64",
        source="cmp x0, x1\n",
        score=18,
        verified=True,
        model_id=SEED_MODEL_ID,
        provider_id=SEED_PROVIDER_ID,
    )
    seed = store.best_candidate("sort3-arm64")
    assert seed is not None
    assert seed["model_id"] == SEED_MODEL_ID

    store.record_candidate(
        candidate_hash="abc123",
        problem_id="sort3-arm64",
        source="cmp x0, x1\n",
        score=18,
        verified=True,
        model_id="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
        provider_id="air5",
    )
    promoted = store.best_candidate("sort3-arm64")
    assert promoted is not None
    assert promoted["model_id"] == "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
    assert promoted["provider_id"] == "air5"
    store.close()


def test_store_summarizes_near_best_structural_diversity(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    candidates = [
        ("hash-best", 17, "cmp x0, x1\ncsel x0, x0, x1, le\n"),
        ("hash-near", 18, "cmp x0, x1\ncsetm x3, gt\neor x4, x0, x1\n"),
        ("hash-far", 20, "mov x0, x0\n"),
    ]
    for candidate_hash, score, source in candidates:
        store.record_candidate(
            candidate_hash=candidate_hash,
            problem_id="sort3-arm64",
            source=source,
            score=score,
            verified=True,
            model_id="model",
            provider_id="air5",
        )

    summary = store.run_summary("sort3-arm64")
    store.close()

    assert summary["near_best_candidate_count"] == 2
    assert summary["near_best_unique_structure_count"] == 2
    structures = summary["near_best_structures"]
    assert {item["representative_hash_short"] for item in structures} == {"hash-best", "hash-near"}
    assert [item["representative_score"] for item in structures] == [17, 18]
    assert any(item["opcode_sequence"] == ["cmp", "csel"] for item in structures)


def test_receipt_round_trip(tmp_path: Path) -> None:
    payload = {
        "problem_id": "sort3-arm64",
        "candidate_hash": "abc123",
        "score": 18,
        "model_id": "model",
        "provider_id": "air5",
        "harness_version": "0.1.0",
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")
    assert verify_receipt(receipt.path)


def test_receipt_signing_reuses_existing_valid_receipt(tmp_path: Path) -> None:
    payload = {
        "problem_id": "sort3-arm64",
        "candidate_hash": "abc123",
        "score": 18,
        "model_id": "model",
        "provider_id": "air5",
        "harness_version": "0.1.0",
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")
    original = receipt.path.read_text()
    same = sign_receipt(payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")
    assert same == receipt
    assert receipt.path.read_text() == original

    changed_payload = {**payload, "score": 17, "ts": "2026-06-05T00:00:01Z"}
    again = sign_receipt(changed_payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")
    assert again.path == receipt.path
    assert receipt.path.read_text() != original
    changed = json.loads(receipt.path.read_text())
    assert changed["payload"]["score"] == 17


def test_atomic_write_text_uses_unique_temp_paths_for_simultaneous_writers(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "receipt.json"
    contents = ["first receipt\n", "second receipt\n"]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    tmp_names: list[str] = []
    tmp_names_lock = threading.Lock()
    original_replace = attest_module.os.replace

    def synchronized_replace(src, dst):
        with tmp_names_lock:
            tmp_names.append(Path(src).name)
        barrier.wait(timeout=5)
        original_replace(src, dst)

    def write_content(content: str) -> None:
        try:
            attest_module.atomic_write_text(target, content)
        except BaseException as exc:  # noqa: BLE001 - thread failures must be asserted in the parent.
            errors.append(exc)

    monkeypatch.setattr(attest_module.os, "replace", synchronized_replace)
    threads = [threading.Thread(target=write_content, args=(content,)) for content in contents]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert target.read_text() in contents
    assert len(tmp_names) == 2
    assert len(set(tmp_names)) == 2
    assert list(tmp_path.glob("receipt.json.*.tmp")) == []


def test_receipt_signing_preserves_existing_receipt_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    payload = {
        "problem_id": "sort3-arm64",
        "candidate_hash": "abc123",
        "score": 18,
        "model_id": "model",
        "provider_id": "air5",
        "harness_version": "0.1.0",
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")
    original = receipt.path.read_bytes()

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(attest_module.os, "replace", fail_replace)
    changed_payload = {**payload, "score": 17, "ts": "2026-06-05T00:00:01Z"}
    with pytest.raises(OSError, match="simulated replace failure"):
        sign_receipt(changed_payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")

    assert list(receipt.path.parent.glob(f"{receipt.path.name}.*.tmp")) == []
    assert receipt.path.read_bytes() == original
    assert verify_receipt(receipt.path)


def test_seed_only_loop_exports_receipt_backed_leaderboard(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "leaderboard.json"
    receipts_dir = tmp_path / "receipts"
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--seed-only",
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(out),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(receipts_dir / "PUBKEY"),
            "--receipts-dir",
            str(receipts_dir),
        ],
    )
    assert loop_main() == 0
    payload = json.loads(out.read_text())
    assert payload["attempt_count"] == 0
    assert payload["requested_candidate_count"] == 0
    assert payload["candidate_response_count"] == 0
    assert payload["run_summary"]["evaluation_count"] == 0
    assert payload["run_summary"]["failed_evaluation_count"] == 0
    assert payload["run_summary"]["evaluation_error_count"] == 0
    assert payload["rows"][0]["receipt_signature"]
    assert payload["rows"][0]["model_id"] == SEED_MODEL_ID
    assert payload["rows"][0]["provider_id"] == SEED_PROVIDER_ID
    assert list(receipts_dir.glob("*.json"))


def test_mock_response_loop_exports_attempt_and_receipt(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "leaderboard.json"
    receipts_dir = tmp_path / "receipts"
    mock_response = tmp_path / "candidate.s"
    mock_response.write_text(Path("problems/sort3-arm64/reference.s").read_text())
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--rounds",
            "1",
            "--mock-response-file",
            str(mock_response),
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(out),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(receipts_dir / "PUBKEY"),
            "--receipts-dir",
            str(receipts_dir),
        ],
    )
    assert loop_main() == 0
    payload = json.loads(out.read_text())
    assert payload["attempt_count"] == 1
    assert payload["requested_candidate_count"] == 1
    assert payload["candidate_response_count"] == 1
    assert payload["run_summary"]["evaluation_count"] == 1
    assert payload["run_summary"]["failed_evaluation_count"] == 0
    assert payload["run_summary"]["evaluation_error_count"] == 0
    assert payload["run_summary"]["first_verified_response"] == 1
    assert payload["rows"][0]["score"] == 18
    assert payload["rows"][0]["receipt_signature"]
    assert payload["rows"][0]["model_id"] == "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
    assert payload["rows"][0]["provider_id"] == "air5"
    receipt = json.loads((receipts_dir / f"{payload['rows'][0]['candidate_hash_short']}.json").read_text())
    assert receipt["payload"]["attestation"] == {"kind": "mock", "details": {}}


def test_mock_response_loop_records_failed_evaluation_error(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "leaderboard.json"
    receipts_dir = tmp_path / "receipts"
    mock_response = tmp_path / "candidate.s"
    mock_response.write_text("this_is_not_arm64 x0, x1\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--rounds",
            "1",
            "--mock-response-file",
            str(mock_response),
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(out),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(receipts_dir / "PUBKEY"),
            "--receipts-dir",
            str(receipts_dir),
        ],
    )
    assert loop_main() == 0
    payload = json.loads(out.read_text())
    summary = payload["run_summary"]
    assert summary["attempt_count"] == 1
    assert summary["evaluation_count"] == 1
    assert summary["failed_evaluation_count"] == 1
    assert summary["evaluation_error_count"] == 1
    assert summary["top_evaluation_errors"]


def test_mock_response_loop_ledgers_candidate_specific_exceptions(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "leaderboard.json"
    receipts_dir = tmp_path / "receipts"
    mock_response = tmp_path / "candidate.s"
    mock_response.write_text(Path("problems/sort3-arm64/reference.s").read_text())

    import harness.loop as loop

    calls = 0

    def fake_sandbox_result(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"ok": True, "verified": True}
        raise RuntimeError("candidate timeout")

    monkeypatch.setattr(loop, "sandbox_result", fake_sandbox_result)
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--rounds",
            "1",
            "--mock-response-file",
            str(mock_response),
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(out),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(receipts_dir / "PUBKEY"),
            "--receipts-dir",
            str(receipts_dir),
        ],
    )
    assert loop_main() == 0
    summary = json.loads(out.read_text())["run_summary"]
    assert summary["evaluation_count"] == 1
    assert summary["failed_evaluation_count"] == 1
    assert summary["evaluation_error_count"] == 1
    assert "candidate timeout" in summary["top_evaluation_errors"][0]["error"]


def test_live_loop_rejects_model_override_before_inference(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--rounds",
            "1",
            "--api-key",
            "dummy",
            "--model",
            "wrong-model",
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(tmp_path / "leaderboard.json"),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(tmp_path / "receipts" / "PUBKEY"),
            "--receipts-dir",
            str(tmp_path / "receipts"),
        ],
    )
    with pytest.raises(SystemExit, match="pinned model"):
        loop_main()


def test_mock_response_loop_honors_max_candidate_responses(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "leaderboard.json"
    receipts_dir = tmp_path / "receipts"
    mock_response = tmp_path / "candidates.json"
    reference = Path("problems/sort3-arm64/reference.s").read_text()
    mock_response.write_text(json.dumps([reference, reference]))
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--rounds",
            "3",
            "--max-candidate-responses",
            "1",
            "--mock-response-file",
            str(mock_response),
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(out),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(receipts_dir / "PUBKEY"),
            "--receipts-dir",
            str(receipts_dir),
        ],
    )
    assert loop_main() == 0
    payload = json.loads(out.read_text())
    assert payload["attempt_count"] == 1
    assert payload["candidate_response_count"] == 1
    assert payload["run_summary"]["evaluation_count"] == 1


def test_mock_response_loop_does_not_stop_on_pass_a(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "leaderboard.json"
    receipts_dir = tmp_path / "receipts"
    mock_response = tmp_path / "candidate.s"
    mock_response.write_text(Path("problems/sort3-arm64/reference.s").read_text())
    monkeypatch.setattr(
        "sys.argv",
        [
            "loop.py",
            "--rounds",
            "2",
            "--max-candidate-responses",
            "2",
            "--mock-response-file",
            str(mock_response),
            "--db",
            str(tmp_path / "db.sqlite"),
            "--leaderboard-json",
            str(out),
            "--private-key",
            str(tmp_path / "data" / "sign.key"),
            "--public-key",
            str(receipts_dir / "PUBKEY"),
            "--receipts-dir",
            str(receipts_dir),
        ],
    )
    assert loop_main() == 0
    payload = json.loads(out.read_text())
    assert payload["attempt_count"] == 2
    assert payload["candidate_response_count"] == 2
    assert payload["run_summary"]["first_verified_response"] == 1


def test_store_migrates_attempt_accounting_columns(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "old.sqlite"
    db = sqlite3.connect(db_path)
    db.execute(
        """
        CREATE TABLE attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_id TEXT NOT NULL,
            template TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    )
    db.commit()
    db.close()

    store = Store(db_path)
    store.record_attempt("sort3-arm64", "template", "ok", requested_n=8, response_count=8)
    store.record_evaluation(
        attempt_id=1,
        problem_id="sort3-arm64",
        candidate_hash="abc123",
        score=18,
        verified=True,
    )
    assert store.attempt_stats("sort3-arm64") == {
        "attempt_count": 1,
        "requested_candidate_count": 8,
        "candidate_response_count": 8,
    }
    assert store.run_summary("sort3-arm64")["evaluation_count"] == 1
    store.close()


def test_summarize_run_derives_threshold_verdicts(tmp_path: Path) -> None:
    script = load_script("bin/summarize-run.py")
    db_path = tmp_path / "db.sqlite"
    store = Store(db_path)
    other_attempt = store.record_attempt("other-problem", "template", "ok", requested_n=1, response_count=1)
    store.record_evaluation(
        attempt_id=other_attempt,
        problem_id="other-problem",
        candidate_hash="other",
        score=1,
        verified=True,
    )
    for i in range(3):
        attempt_id = store.record_attempt("sort3-arm64", "template", "ok", requested_n=1, response_count=1)
        store.record_candidate(
            candidate_hash=f"hash{i}",
            problem_id="sort3-arm64",
            source="cmp x0, x1\n",
            score=17 if i == 2 else 18,
            verified=i == 2,
            model_id="model",
            provider_id="air5",
        )
        store.record_evaluation(
            attempt_id=attempt_id,
            problem_id="sort3-arm64",
            candidate_hash=f"hash{i}",
            score=17 if i == 2 else 18,
            verified=i == 2,
        )
    summary = store.run_summary("sort3-arm64")
    store.close()

    assert summary["candidate_response_count"] == 3
    assert summary["failed_evaluation_count"] == 2
    assert summary["evaluation_error_count"] == 0
    assert summary["first_verified_response"] == 3
    assert summary["first_17_response"] == 3
    assert script.verdict(summary) == "PASS-B"


def test_summarize_run_reports_pending_without_responses(tmp_path: Path) -> None:
    script = load_script("bin/summarize-run.py")
    store = Store(tmp_path / "db.sqlite")
    summary = store.run_summary("sort3-arm64")
    store.close()
    assert script.verdict(summary) == "PENDING"


def test_write_report_renders_pending_state(tmp_path: Path) -> None:
    script = load_script("bin/write-report.py")
    store = Store(tmp_path / "db.sqlite")
    summary = store.run_summary("sort3-arm64")
    store.close()
    report = script.render_report("sort3-arm64", summary)
    assert "Status: pending" in report
    assert "No PASS/FAIL verdict yet" in report
    assert "public launch is intentionally deferred" in report
    assert "bin/ready-live-run.py" in report
    assert "bin/validate-docs.py" in report
    assert "bin/validate-harness-smoke.py" in report
    assert "bin/validate-live-run-contract.py" in report
    assert "bin/validate-inference-config.py" in report
    assert "bin/validate-sandbox.py" in report
    assert "bin/validate-receipts.py" in report
    assert "bin/validate-report.py" in report
    assert "bin/validate-air5-handoff.py" in report


def test_write_report_renders_pass_b_evidence(tmp_path: Path) -> None:
    script = load_script("bin/write-report.py")
    db_path = tmp_path / "db.sqlite"
    store = Store(db_path)
    for i in range(3):
        attempt_id = store.record_attempt("sort3-arm64", "template", "ok", requested_n=1, response_count=1)
        store.record_candidate(
            candidate_hash=f"hash{i}",
            problem_id="sort3-arm64",
            source="cmp x0, x1\n",
            score=17 if i == 2 else 18,
            verified=i == 2,
            model_id="model",
            provider_id="air5",
        )
        store.record_evaluation(
            attempt_id=attempt_id,
            problem_id="sort3-arm64",
            candidate_hash=f"hash{i}",
            score=17 if i == 2 else 18,
            verified=i == 2,
        )
    summary = store.run_summary("sort3-arm64")
    store.close()
    report = script.render_report("sort3-arm64", summary)
    assert "Status: pass-b" in report
    assert "Current derived verdict: PASS-B." in report
    assert "- first 17-instruction response: 3" in report
    assert "- near-best unique opcode structures: 1" in report


def test_write_report_renders_structural_diversity_evidence(tmp_path: Path) -> None:
    script = load_script("bin/write-report.py")
    store = Store(tmp_path / "db.sqlite")
    for candidate_hash, score, source in [
        ("hash-best", 17, "cmp x0, x1\ncsel x0, x0, x1, le\n"),
        ("hash-near", 18, "cmp x0, x1\ncsetm x3, gt\neor x4, x0, x1\n"),
    ]:
        store.record_candidate(
            candidate_hash=candidate_hash,
            problem_id="sort3-arm64",
            source=source,
            score=score,
            verified=True,
            model_id="model",
            provider_id="air5",
        )
    summary = store.run_summary("sort3-arm64")
    store.close()

    report = script.render_report("sort3-arm64", summary)
    assert "## Structural Diversity Evidence" in report
    assert "manual PASS-C review only" in report
    assert "`cmp csel`" in report
    assert "`cmp csetm eor`" in report


def test_air5_model_check_flattens_unknown_model_schema() -> None:
    script = load_script("bin/check-air5-model.py")
    payload = {
        "data": [
            {
                "id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
                "providers": [{"id": "air5"}],
            }
        ]
    }
    strings = script.flatten_strings(payload)
    assert "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit" in strings
    assert "air5" in strings


def test_air5_model_check_adds_authorization_header(monkeypatch) -> None:
    script = load_script("bin/check-air5-model.py")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"data":[]}'

    def fake_urlopen(req, timeout):
        captured["auth"] = req.headers.get("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)
    assert script.fetch_json("https://example.test/v1/models", 3, "secret") == {"data": []}
    assert captured == {"auth": "Bearer secret", "timeout": 3}


def test_air5_model_check_reports_owner_actions_for_missing_model_and_provider() -> None:
    script = load_script("bin/check-air5-model.py")
    actions = script.operator_actions(False, False, ["air5", "m4"])
    assert any("download/prewarm" in action for action in actions)
    assert any("provider id mapping" in action for action in actions)
    assert all("Report to Augustas for air5-owner coordination" in action for action in actions)
    assert not any(action.startswith("Ask the air5 owner") for action in actions)


def test_preflight_parses_github_origin_urls() -> None:
    script = load_script("bin/preflight.py")
    assert script.repo_slug_from_origin("https://github.com/Augustas11/arm64golf.git") == "Augustas11/arm64golf"
    assert script.repo_slug_from_origin("git@github.com:Augustas11/arm64golf.git") == "Augustas11/arm64golf"


def test_preflight_requires_private_repo_visibility(monkeypatch) -> None:
    script = load_script("bin/preflight.py")

    def fake_run(cmd, timeout_s=10.0):
        assert cmd == ["gh", "repo", "view", "Augustas11/arm64golf", "--json", "nameWithOwner,url,visibility"]
        return 0, '{"nameWithOwner":"Augustas11/arm64golf","url":"https://github.com/Augustas11/arm64golf","visibility":"PUBLIC"}'

    monkeypatch.setattr(script.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(script, "run", fake_run)
    result = script.check_repo_visibility("https://github.com/Augustas11/arm64golf.git", allow_public_launch=False)
    assert result["ok"] is False
    assert result["visibility"] == "PUBLIC"

    allowed = script.check_repo_visibility("https://github.com/Augustas11/arm64golf.git", allow_public_launch=True)
    assert allowed["ok"] is True


def test_preflight_rejects_unexpected_origin() -> None:
    script = load_script("bin/preflight.py")
    result = script.check_repo_visibility("https://github.com/Augustas11/something-else.git", allow_public_launch=False)
    assert result["ok"] is False
    assert result["summary"] == "origin does not match expected private test repo"


def test_deliverable_audit_requires_private_repo(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")

    def fake_run(cmd, timeout_s=10.0):
        if cmd == ["git", "remote", "get-url", "origin"]:
            return 0, "https://github.com/Augustas11/arm64golf.git"
        if cmd == ["gh", "repo", "view", "Augustas11/arm64golf", "--json", "nameWithOwner,url,visibility"]:
            return 0, '{"nameWithOwner":"Augustas11/arm64golf","url":"https://github.com/Augustas11/arm64golf","visibility":"PRIVATE"}'
        raise AssertionError(cmd)

    monkeypatch.setattr(script, "run", fake_run)
    result = script.git_repo_status()
    assert result.status == "complete"
    assert "private test repo" in result.summary


def test_deliverable_audit_rejects_public_repo(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")

    def fake_run(cmd, timeout_s=10.0):
        if cmd == ["git", "remote", "get-url", "origin"]:
            return 0, "https://github.com/Augustas11/arm64golf.git"
        if cmd == ["gh", "repo", "view", "Augustas11/arm64golf", "--json", "nameWithOwner,url,visibility"]:
            return 0, '{"nameWithOwner":"Augustas11/arm64golf","url":"https://github.com/Augustas11/arm64golf","visibility":"PUBLIC"}'
        raise AssertionError(cmd)

    monkeypatch.setattr(script, "run", fake_run)
    result = script.git_repo_status()
    assert result.status == "failed"
    assert "PRIVATE" in result.summary


def test_deliverable_audit_offline_mode_skips_visibility(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")

    def fake_run(cmd, timeout_s=10.0):
        assert cmd == ["git", "remote", "get-url", "origin"]
        return 0, "https://github.com/Augustas11/arm64golf.git"

    monkeypatch.setattr(script, "run", fake_run)
    result = script.git_repo_status(check_visibility=False)
    assert result.status == "pending"
    assert "offline mode" in result.summary


def test_deliverable_audit_uses_spec_doc_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: False)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["spec"].status == "missing"
    assert "SPEC.md contract validates" in items["spec"].summary


def test_deliverable_audit_uses_readme_doc_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: False)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["readme"].status == "missing"
    assert "README contract validates" in items["readme"].summary


def test_deliverable_audit_uses_sort3_contract_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: False)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["sort3_module"].status == "missing"
    assert "contract validates" in items["sort3_module"].summary


def test_deliverable_audit_uses_harness_smoke_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: False)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["harness"].status == "missing"
    assert "offline harness smoke passes" in items["harness"].summary


def test_deliverable_audit_uses_live_run_contract_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: False)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["live_run_contract"].status == "missing"
    assert "response cap" in items["live_run_contract"].summary


def test_deliverable_audit_uses_inference_config_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: False)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["inference_path"].status == "missing"
    assert "inference request contract validates" in items["inference_path"].summary


def test_deliverable_audit_uses_sandbox_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: False)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["sandbox"].status == "missing"
    assert "sandbox contract validates" in items["sandbox"].summary


def test_deliverable_audit_uses_report_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: False)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: True)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["report"].status == "missing"
    assert "tracked leaderboard evidence" in items["report"].summary


def test_deliverable_audit_uses_air5_handoff_validator(monkeypatch) -> None:
    script = load_script("bin/audit-deliverables.py")
    monkeypatch.setattr(script, "git_repo_status", lambda check_github_visibility=True: script.AuditItem("github_repo", "pending", "offline"))
    monkeypatch.setattr(script, "spec_doc_ok", lambda: True)
    monkeypatch.setattr(script, "readme_doc_ok", lambda: True)
    monkeypatch.setattr(script, "sort3_module_validator_ok", lambda: True)
    monkeypatch.setattr(script, "harness_smoke_ok", lambda: True)
    monkeypatch.setattr(script, "live_run_contract_ok", lambda: True)
    monkeypatch.setattr(script, "inference_config_ok", lambda: True)
    monkeypatch.setattr(script, "sandbox_validator_ok", lambda: True)
    monkeypatch.setattr(script, "receipt_validator_ok", lambda: True)
    monkeypatch.setattr(script, "web_validator_ok", lambda: True)
    monkeypatch.setattr(script, "report_validator_ok", lambda: True)
    monkeypatch.setattr(script, "air5_handoff_validator_ok", lambda: False)

    items = {item.id: item for item in script.audit_items(check_github_visibility=False)}
    assert items["air5_handoff"].status == "missing"
    assert "operator walkthrough" in items["air5_handoff"].summary


def test_validate_web_accepts_current_static_assets() -> None:
    script = load_script("bin/validate-web.py")
    assert script.validate(Path("web")) == []


def test_validate_web_rejects_incomplete_leaderboard_row(tmp_path: Path) -> None:
    script = load_script("bin/validate-web.py")
    web_dir = tmp_path / "web"
    (web_dir / "public").mkdir(parents=True)
    (web_dir / "index.html").write_text(Path("web/index.html").read_text())
    (web_dir / "app.js").write_text(Path("web/app.js").read_text())
    (web_dir / "styles.css").write_text(Path("web/styles.css").read_text())
    payload = json.loads(Path("web/public/leaderboard.json").read_text())
    del payload["rows"][0]["receipt_signature"]
    (web_dir / "public" / "leaderboard.json").write_text(json.dumps(payload))

    errors = script.validate(web_dir)
    assert any("receipt_signature" in error for error in errors)


def test_validate_web_rejects_static_air5_seed_overclaim(tmp_path: Path) -> None:
    script = load_script("bin/validate-web.py")
    web_dir = tmp_path / "web"
    (web_dir / "public").mkdir(parents=True)
    html = Path("web/index.html").read_text() + "<p>Powered by air5 + Qwen2.5-Coder-7B</p>"
    (web_dir / "index.html").write_text(html)
    (web_dir / "app.js").write_text(Path("web/app.js").read_text())
    (web_dir / "styles.css").write_text(Path("web/styles.css").read_text())
    (web_dir / "public" / "leaderboard.json").write_text(Path("web/public/leaderboard.json").read_text())

    errors = script.validate(web_dir)
    assert any("statically claim" in error for error in errors)


def test_validate_web_rejects_internal_sandbox_path_in_leaderboard(tmp_path: Path) -> None:
    script = load_script("bin/validate-web.py")
    web_dir = tmp_path / "web"
    (web_dir / "public").mkdir(parents=True)
    (web_dir / "index.html").write_text(Path("web/index.html").read_text())
    (web_dir / "app.js").write_text(Path("web/app.js").read_text())
    (web_dir / "styles.css").write_text(Path("web/styles.css").read_text())
    payload = json.loads(Path("web/public/leaderboard.json").read_text())
    payload.setdefault("run_summary", {}).setdefault("top_evaluation_errors", []).append(
        {"error": "/private/tmp/arm64golf-sandbox/run-abc123/candidate.s:1:1: error: bad", "count": 1}
    )
    (web_dir / "public" / "leaderboard.json").write_text(json.dumps(payload))

    errors = script.validate(web_dir)
    assert any("sandbox host paths" in error for error in errors)


def test_validate_receipts_accepts_current_leaderboard() -> None:
    script = load_script("bin/validate-receipts.py")
    assert script.validate(Path("web/public/leaderboard.json"), Path("receipts")) == []


def test_validate_receipts_rejects_row_score_mismatch(tmp_path: Path) -> None:
    script = load_script("bin/validate-receipts.py")
    leaderboard = tmp_path / "leaderboard.json"
    payload = json.loads(Path("web/public/leaderboard.json").read_text())
    payload["rows"][0]["score"] = 17
    leaderboard.write_text(json.dumps(payload))

    errors = script.validate(leaderboard, Path("receipts"))
    assert any("score" in error for error in errors)


def test_validate_receipts_rejects_bad_known_attestation_shape(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    payload = {
        "attestation": {"kind": "mock", "details": {"not": "empty"}},
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.2.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, tmp_path / "sign.key", receipts / "PUBKEY", receipts)
    envelope = json.loads(receipt.path.read_text())
    leaderboard = tmp_path / "leaderboard.json"
    leaderboard.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "candidate_hash": candidate.candidate_hash,
                        "score": count,
                        "model_id": SEED_MODEL_ID,
                        "provider_id": SEED_PROVIDER_ID,
                        "receipt_signature": envelope["signature"],
                    }
                ]
            }
        )
    )

    script = load_script("bin/validate-receipts.py")
    errors = script.validate(leaderboard, receipts)
    assert any("mock attestation details must be empty" in error for error in errors)


def test_validate_receipts_rejects_reference_attestation_missing_fields(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    payload = {
        "attestation": {
            "kind": "reference-harness",
            "details": {
                "template_name": "csel_hint",
                "temperature": 0.7,
                "top_p": 0.95,
                "n": 8,
            },
        },
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.2.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, tmp_path / "sign.key", receipts / "PUBKEY", receipts)
    envelope = json.loads(receipt.path.read_text())
    leaderboard = tmp_path / "leaderboard.json"
    leaderboard.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "candidate_hash": candidate.candidate_hash,
                        "score": count,
                        "model_id": SEED_MODEL_ID,
                        "provider_id": SEED_PROVIDER_ID,
                        "receipt_signature": envelope["signature"],
                    }
                ]
            }
        )
    )

    script = load_script("bin/validate-receipts.py")
    errors = script.validate(leaderboard, receipts)
    assert any("reference-harness details fields" in error for error in errors)


def test_template_id_is_deterministic_and_body_hash_based() -> None:
    from harness.prompts import ABLATION_TEMPLATES, template_id

    assert template_id("csel_hint") == template_id("csel_hint")
    expected = sha256(ABLATION_TEMPLATES["csel_hint"].encode("utf-8")).hexdigest()[:16]
    assert template_id("csel_hint") == expected


def test_original_template_ids_are_distinct() -> None:
    from harness.prompts import template_id

    names = ["no_failed_context", "strict_no_memory", "structural_hint", "failed_context"]
    assert len({template_id(name) for name in names}) == len(names)


def test_ensure_distinct_template_ids_checks_full_registry() -> None:
    from harness.prompts import ABLATION_TEMPLATES, ensure_distinct_template_ids, template_id

    ensure_distinct_template_ids()
    seen: dict[str, str] = {}
    for name in ABLATION_TEMPLATES:
        current_id = template_id(name)
        assert current_id not in seen, f"{name} collides with {seen.get(current_id)}"
        seen[current_id] = name


def test_template_id_survives_prompt_module_reload() -> None:
    from harness import prompts

    before = prompts.template_id("no_failed_context")
    reloaded = importlib.reload(prompts)
    assert reloaded.template_id("no_failed_context") == before


def test_sign_and_verify_v2_reference_harness_receipt(tmp_path: Path) -> None:
    from harness.loop import HARNESS_VERSION, receipt_payload, reference_attestation

    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"

    payload = receipt_payload(
        candidate,
        count,
        "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
        "air5",
        reference_attestation("csel_hint", 0.7, 0.95, 8),
    )
    receipt = sign_receipt(payload, private_key, public_key, receipts)

    assert verify_receipt(receipt.path)
    envelope = json.loads(receipt.path.read_text())
    assert envelope["payload"]["harness_version"] == HARNESS_VERSION
    assert envelope["payload"]["attestation"] == {
        "kind": "reference-harness",
        "details": {
            "template_id": payload["attestation"]["details"]["template_id"],
            "template_name": "csel_hint",
            "temperature": 0.7,
            "top_p": 0.95,
            "n": 8,
        },
    }


@pytest.mark.parametrize(
    ("template_name", "temperature", "top_p", "n", "message"),
    [
        ("missing", 0.7, 0.95, 8, "unknown template_name"),
        ("csel_hint", -0.1, 0.95, 8, "temperature"),
        ("csel_hint", 2.1, 0.95, 8, "temperature"),
        ("csel_hint", 0.7, 0.0, 8, "top_p"),
        ("csel_hint", 0.7, 1.1, 8, "top_p"),
        ("csel_hint", 0.7, 0.95, 0, "n"),
        ("csel_hint", 0.7, 0.95, 65, "n"),
    ],
)
def test_reference_attestation_rejects_invalid_inputs(
    template_name: str, temperature: float, top_p: float, n: int, message: str
) -> None:
    from harness.loop import reference_attestation

    with pytest.raises(ValueError, match=message):
        reference_attestation(template_name, temperature, top_p, n)


def test_validate_attestation_accepts_forward_compatible_unknown_kind() -> None:
    from harness.loop import validate_attestation

    validate_attestation({"kind": "open-submission", "details": {"team": "future", "scorecard": [1, 2, 3]}})


def test_validate_attestation_rejects_bad_known_or_unserializable_shapes() -> None:
    from harness.loop import validate_attestation

    with pytest.raises(ValueError, match="details must be empty"):
        validate_attestation({"kind": "mock", "details": {"template_name": "csel_hint"}})
    with pytest.raises(ValueError, match="JSON-serializable"):
        validate_attestation({"kind": "open-submission", "details": {"bad": {1, 2}}})


def test_validate_attestation_enforces_details_size_cap() -> None:
    from harness.attest import canonical_json
    from harness.loop import validate_attestation

    empty_blob_size = len(canonical_json({"blob": ""}))
    boundary_blob = "x" * (4096 - empty_blob_size)
    validate_attestation({"kind": "open-submission", "details": {"blob": boundary_blob}})

    with pytest.raises(ValueError, match="attestation.details exceeds 4096-byte cap"):
        validate_attestation({"kind": "open-submission", "details": {"blob": boundary_blob + "x"}})


def test_sign_and_verify_v2_seed_baseline_receipt(tmp_path: Path) -> None:
    from harness.loop import receipt_payload, seed_attestation

    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"

    payload = receipt_payload(candidate, count, SEED_MODEL_ID, SEED_PROVIDER_ID, seed_attestation())
    receipt = sign_receipt(payload, private_key, public_key, receipts)

    assert verify_receipt(receipt.path)
    envelope = json.loads(receipt.path.read_text())
    assert envelope["payload"]["attestation"] == {
        "kind": "seed-baseline",
        "details": {},
    }


def test_verify_receipt_accepts_v1_payload(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    payload = {
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.1.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, private_key, public_key, receipts)

    assert verify_receipt(receipt.path)


def test_validate_receipts_rejects_v1_payload_without_attestation(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    payload = {
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.1.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, private_key, public_key, receipts)
    envelope = json.loads(receipt.path.read_text())
    leaderboard = tmp_path / "leaderboard.json"
    leaderboard.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "candidate_hash": candidate.candidate_hash,
                        "score": count,
                        "model_id": SEED_MODEL_ID,
                        "provider_id": SEED_PROVIDER_ID,
                        "receipt_signature": envelope["signature"],
                    }
                ]
            }
        )
    )

    validate_script = load_script("bin/validate-receipts.py")
    errors = validate_script.validate(leaderboard, receipts)
    assert any("attestation must be an object" in error for error in errors)


def test_upgrade_receipts_to_v2_updates_v1_in_place_and_validator_accepts(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    v1_payload = {
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.1.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(v1_payload, private_key, public_key, receipts)

    upgrade_script = load_script("bin/upgrade-receipts-to-v2.py")
    assert upgrade_script.upgrade_receipts(receipts, private_key, public_key) == [
        (candidate.candidate_hash[:12], "upgraded_to_v2")
    ]
    upgraded_mtime = receipt.path.stat().st_mtime_ns
    assert upgrade_script.upgrade_receipts(receipts, private_key, public_key) == [
        (candidate.candidate_hash[:12], "kept_v2")
    ]
    assert receipt.path.stat().st_mtime_ns == upgraded_mtime

    assert verify_receipt(receipt.path)
    envelope = json.loads(receipt.path.read_text())
    payload = envelope["payload"]
    assert payload["candidate_hash"] == v1_payload["candidate_hash"]
    assert payload["score"] == v1_payload["score"]
    assert payload["model_id"] == v1_payload["model_id"]
    assert payload["provider_id"] == v1_payload["provider_id"]
    assert payload["harness_version"] == "0.2.0"
    assert payload["ts"] == v1_payload["ts"]
    assert payload["attestation"] == {"kind": "seed-baseline", "details": {}}

    leaderboard = tmp_path / "leaderboard.json"
    leaderboard.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "candidate_hash": candidate.candidate_hash,
                        "score": count,
                        "model_id": SEED_MODEL_ID,
                        "provider_id": SEED_PROVIDER_ID,
                        "receipt_signature": envelope["signature"],
                    }
                ]
            }
        )
    )
    validate_script = load_script("bin/validate-receipts.py")
    assert validate_script.validate(leaderboard, receipts) == []


def test_upgrade_receipts_to_v2_classifies_non_seed_legacy_as_unknown(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    payload = {
        "candidate_hash": "17e628abfc2bf6532770a18a46005481a7fccac9f658907076a447b1db96ca0e",
        "harness_version": "0.1.0",
        "model_id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
        "problem_id": "sort3-arm64",
        "provider_id": "air5",
        "score": 24,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, private_key, public_key, receipts)

    upgrade_script = load_script("bin/upgrade-receipts-to-v2.py")
    assert upgrade_script.upgrade_receipts(receipts, private_key, public_key, tmp_path / "missing.sqlite") == [
        ("17e628abfc2b", "upgraded_to_v2")
    ]

    envelope = json.loads(receipt.path.read_text())
    assert envelope["payload"]["ts"] == payload["ts"]
    assert envelope["payload"]["attestation"] == {"kind": "legacy-v1-unknown", "details": {}}


def test_upgrade_receipts_to_v2_refuses_malformed_attestation_without_rewriting(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    payload = {
        "attestation": {"kind": "mock", "details": {"not": "empty"}},
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.1.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, private_key, public_key, receipts)
    original = receipt.path.read_text()

    result = subprocess.run(
        [
            sys.executable,
            "bin/upgrade-receipts-to-v2.py",
            "--receipts-dir",
            str(receipts),
            "--private-key",
            str(private_key),
            "--public-key",
            str(public_key),
            "--db",
            str(tmp_path / "missing.sqlite"),
        ],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "attestation invalid" in result.stdout
    assert "mock attestation details must be empty" in result.stdout
    assert receipt.path.read_text() == original


def test_upgrade_receipts_to_v2_refuses_malformed_seed_attestation_without_rewriting(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    payload = {
        "attestation": {"kind": "seed-baseline", "details": {"leftover": "data"}},
        "candidate_hash": candidate.candidate_hash,
        "harness_version": "0.2.0",
        "model_id": SEED_MODEL_ID,
        "problem_id": candidate.problem_id,
        "provider_id": SEED_PROVIDER_ID,
        "score": count,
        "ts": "2026-06-05T00:00:00Z",
    }
    receipt = sign_receipt(payload, private_key, public_key, receipts)
    original = receipt.path.read_text()

    result = subprocess.run(
        [
            sys.executable,
            "bin/upgrade-receipts-to-v2.py",
            "--receipts-dir",
            str(receipts),
            "--private-key",
            str(private_key),
            "--public-key",
            str(public_key),
            "--db",
            str(tmp_path / "missing.sqlite"),
        ],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "attestation invalid" in result.stdout
    assert "seed-baseline attestation details must be empty" in result.stdout
    assert receipt.path.read_text() == original


def test_upgrade_receipts_to_v2_rejects_loose_private_key_permissions(tmp_path: Path) -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    receipts = tmp_path / "receipts"
    private_key = tmp_path / "data" / "sign.key"
    public_key = receipts / "PUBKEY"
    sign_receipt(
        {
            "candidate_hash": candidate.candidate_hash,
            "harness_version": "0.1.0",
            "model_id": SEED_MODEL_ID,
            "problem_id": candidate.problem_id,
            "provider_id": SEED_PROVIDER_ID,
            "score": count,
            "ts": "2026-06-05T00:00:00Z",
        },
        private_key,
        public_key,
        receipts,
    )
    private_key.chmod(0o644)

    upgrade_script = load_script("bin/upgrade-receipts-to-v2.py")
    with pytest.raises(PermissionError, match="0600"):
        upgrade_script.upgrade_receipts(receipts, private_key, public_key)


def test_ready_live_run_reports_skipped_model_check_as_blocker(monkeypatch) -> None:
    script = load_script("bin/ready-live-run.py")

    def fake_json_command_check(name, cmd, timeout_s=90.0):
        return {"name": name, "ok": True, "returncode": 0, "output": {"ok": True}}

    monkeypatch.setattr(script, "json_command_check", fake_json_command_check)
    monkeypatch.setattr(
        script,
        "preflight_check",
        lambda run_tests: {"name": "preflight", "ok": True, "returncode": 0, "output": {}, "macprovider_api_key_present": False},
    )

    args = type(
        "Args",
        (),
        {
            "offline_audit": True,
            "run_tests": False,
            "skip_model_check": True,
            "provider_alias": ["m4"],
            "models_url": "https://api.streamvc.live/v1/models",
        },
    )()
    payload = script.readiness(args)
    assert payload["ready"] is False
    assert "live_credentials" in payload["blockers"]
    assert "air5_model" in payload["blockers"]
    air5_check = next(check for check in payload["checks"] if check["name"] == "air5_model")
    assert "operator_actions" in air5_check


def test_ready_live_run_can_report_ready_when_all_checks_pass(monkeypatch) -> None:
    script = load_script("bin/ready-live-run.py")
    monkeypatch.setenv("MACPROVIDER_API_KEY", "secret")

    def fake_json_command_check(name, cmd, timeout_s=90.0):
        return {"name": name, "ok": True, "returncode": 0, "output": {"ok": True}}

    monkeypatch.setattr(script, "json_command_check", fake_json_command_check)
    monkeypatch.setattr(
        script,
        "preflight_check",
        lambda run_tests: {"name": "preflight", "ok": True, "returncode": 0, "output": {}, "macprovider_api_key_present": True},
    )
    monkeypatch.setattr(script, "air5_model_check", lambda skip, provider_aliases, url: {"name": "air5_model", "ok": True})

    args = type(
        "Args",
        (),
        {
            "offline_audit": False,
            "run_tests": True,
            "skip_model_check": False,
            "provider_alias": ["m4"],
            "models_url": "https://api.streamvc.live/v1/models",
        },
    )()
    payload = script.readiness(args)
    assert payload["ready"] is True
    assert payload["blockers"] == []


# --- prompt templates ---------------------------------------------------------

def test_ablation_templates_include_failed_context() -> None:
    """The v0.2 failed_context template must exist alongside the original
    no_failed_context / strict_no_memory / structural_hint variants, and
    the v0.3 post-canary instruction-count variants (including the
    chain_of_thought variant from the prompt-sophistication probe) must
    also be registered. Any accidental rename would break --template
    selection on the CLI."""
    from harness.prompts import ABLATION_TEMPLATES

    assert set(ABLATION_TEMPLATES.keys()) == {
        "no_failed_context",
        "strict_no_memory",
        "structural_hint",
        "failed_context",
        "pass_b_target",
        "csel_hint",
        "dual_example",
        "chain_of_thought",
    }


def test_pass_b_target_templates_cap_target_at_17_until_best_below_18() -> None:
    """v0.3 produced verified non-baseline routines at 24 instructions.
    Without a cap, --template csel_hint with current_best=24 would ask
    the model for "23 instructions" — useless for PASS-B. The
    instruction-count variants must cap target_count at 17 (PASS-B
    threshold) so the prompt stays anchored on the PASS-B goal even
    when a verified-but-still-too-long routine becomes the leaderboard
    best."""
    from harness.prompts import build_prompt, PASS_B_TARGET_TEMPLATES

    for template in PASS_B_TARGET_TEMPLATES:
        body = build_prompt(
            assembly="cmp x0, x1\ncsetm x3, gt",
            instruction_count=24,
            template=template,
        )[-1]["content"]
        assert "with 17 instructions" in body, (
            f"{template} must cap target_count at 17 (PASS-B threshold) when "
            f"current best is still ≥18, not drift with the current best"
        )


def test_pass_b_target_templates_track_below_best_once_under_18() -> None:
    """Once a probe lands a sub-18 routine (e.g. the csel_hint probe's
    12-instruction win), the prompt must start asking for "current
    best - 1" rather than continue asking for 17 (which would be a
    worse routine). The cap is a floor at PASS-B until we cross it;
    after that, we track the leaderboard."""
    from harness.prompts import build_prompt, PASS_B_TARGET_TEMPLATES

    for template in PASS_B_TARGET_TEMPLATES:
        body = build_prompt(
            assembly="cmp x0, x1\ncsel x3, x1, x0, le\ncsel x0, x0, x1, le\nmov x1, x3",
            instruction_count=12,
            template=template,
        )[-1]["content"]
        assert "with 11 instructions" in body, (
            f"{template} with current best = 12 must ask for 11, not 17 "
            f"(asking for 17 would be a strict regression)"
        )


def test_pass_b_target_variants_carry_their_signature_hint() -> None:
    """Each v0.3 variant must include its distinguishing language so
    --template selection actually changes prompt content. Catches the
    failure mode where someone aliases all three variants to the same
    block by mistake."""
    from harness.prompts import build_prompt

    pass_b_body = build_prompt("cmp x0, x1", 18, template="pass_b_target")[-1]["content"]
    assert "STRICTLY FEWER than 18" in pass_b_body
    assert "Count" in pass_b_body and "instructions before emitting" in pass_b_body

    csel_body = build_prompt("cmp x0, x1", 18, template="csel_hint")[-1]["content"]
    assert "csel" in csel_body and "compare-swap" in csel_body
    assert "cmp  x0, x1" in csel_body  # worked example present

    dual_body = build_prompt("cmp x0, x1", 18, template="dual_example")[-1]["content"]
    assert "tie the baseline" in dual_body
    assert "24 instructions" in dual_body


def test_failed_context_template_surfaces_edge_cases_and_isa_pitfalls() -> None:
    """The v0.1 canary's dominant failure modes were `case 1 failed`
    (all-equal triple) and `case 2 failed` (already-sorted ascending), plus
    occasional ISA confusion (`xor` from x86; `eors` mis-spelling of `eor`).
    The failed_context template exists exactly to surface these to the model,
    so this test pins each as a hard requirement on the prompt body."""
    from harness.prompts import build_prompt

    messages = build_prompt(
        assembly="cmp x0, x1\ncsetm x3, gt",
        instruction_count=18,
        template="failed_context",
    )
    assert messages[0]["role"] == "system"
    body = messages[-1]["content"]

    # Edge-case 1: all-equal (case 1 in tests.json)
    assert "x0=0, x1=0, x2=0" in body
    # Edge-case 2: already ascending (case 2 in tests.json)
    assert "x0=1, x1=2, x2=3" in body
    # Signed-extremes (case 5 in tests.json) — wider int64 reasoning
    assert "9223372036854775807" in body
    # ISA pitfalls explicitly called out
    assert "eor" in body and "xor" in body  # the contrast must be present
    assert "eors" in body  # the typo we observed in the canary


def test_failed_context_template_preserves_target_count_one_below_current() -> None:
    """The whole search depends on the model being asked for INSTR_COUNT-1
    instructions. failed_context must not break that contract."""
    from harness.prompts import build_prompt

    body = build_prompt(
        assembly="cmp x0, x1",
        instruction_count=17,
        template="failed_context",
    )[-1]["content"]
    assert "Propose a variant with 16 instructions" in body


def test_chain_of_thought_uses_cot_system_prompt_and_asks_for_fenced_output() -> None:
    """CoT can't share the bare 'no markdown, no prose' system prompt of
    the other templates — the whole point is that the model emits prose
    reasoning followed by a fenced code block. Pin both halves: the
    distinct system prompt is used, and the user message asks for the
    final assembly inside triple backticks."""
    from harness.prompts import build_prompt, COT_SYSTEM_PROMPT, SYSTEM_PROMPT

    msgs = build_prompt(
        assembly="cmp x0, x1\ncsel x3, x1, x0, le",
        instruction_count=12,
        template="chain_of_thought",
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == COT_SYSTEM_PROMPT
    assert msgs[0]["content"] != SYSTEM_PROMPT  # we actually swapped, not aliased
    assert "fenced" in COT_SYSTEM_PROMPT.lower() or "fenced" in msgs[1]["content"].lower()
    assert "triple" in msgs[1]["content"] and "backticks" in msgs[1]["content"]
    assert "Step 1" in msgs[1]["content"] and "Step 2" in msgs[1]["content"] and "Step 3" in msgs[1]["content"]


def test_chain_of_thought_tracks_below_current_best() -> None:
    """CoT joins the PASS-B-target set. With current best = 12, target
    must be 11, not 17 (the floor only matters until current best dips
    below 18)."""
    from harness.prompts import build_prompt, PASS_B_TARGET_TEMPLATES

    assert "chain_of_thought" in PASS_B_TARGET_TEMPLATES
    body = build_prompt(
        assembly="cmp x0, x1\ncsel x3, x1, x0, le",
        instruction_count=12,
        template="chain_of_thought",
    )[-1]["content"]
    assert "with 11 instructions" in body or "11 instructions" in body


def test_extract_assembly_strips_outer_fences_when_response_is_pure_code_block() -> None:
    """Original v0.1 behavior — a response that's entirely a fenced
    block (possibly with a language tag) yields the inner assembly."""
    from harness.prompts import extract_assembly

    response = "```asm\ncmp x0, x1\ncsel x0, x0, x1, le\n```"
    assert extract_assembly(response) == "cmp x0, x1\ncsel x0, x0, x1, le\n"


def test_extract_assembly_pulls_last_fenced_block_from_cot_response() -> None:
    """CoT prompt elicits prose reasoning + a final fenced block. The
    extractor must pull the LAST fenced block, not return the whole
    response (which would not be valid assembly and would fail the
    verifier with a useless 'unrecognized mnemonic' error)."""
    from harness.prompts import extract_assembly

    response = (
        "Step 1: the routine has three csel blocks.\n"
        "Step 2: the third block's mov is redundant because x3 was\n"
        "set unconditionally in the prior block.\n\n"
        "Final routine:\n\n"
        "```\n"
        "cmp x0, x1\n"
        "csel x0, x0, x1, le\n"
        "csel x1, x1, x0, gt\n"
        "```\n"
    )
    assert extract_assembly(response) == "cmp x0, x1\ncsel x0, x0, x1, le\ncsel x1, x1, x0, gt\n"


def test_extract_assembly_pulls_final_block_when_response_has_inline_example() -> None:
    """If the model emits multiple fenced blocks (e.g. an inline example
    of the redundancy it identified, then the final dense routine), the
    extractor must take the LAST one — that's where the model was told
    to put its final answer."""
    from harness.prompts import extract_assembly

    response = (
        "The current best is:\n"
        "```\n"
        "cmp x0, x1\ncsel x0, x0, x1, le\nmov x1, x3\n"
        "```\n"
        "The mov is redundant. Denser:\n"
        "```\n"
        "cmp x0, x1\ncsel x0, x0, x1, le\n"
        "```\n"
    )
    assert extract_assembly(response) == "cmp x0, x1\ncsel x0, x0, x1, le\n"


def test_extract_assembly_falls_back_to_stripped_text_when_no_fence() -> None:
    """No code-block fences (e.g. the original failed_context prompts
    where the model emits bare assembly) — extractor returns the
    stripped text with a trailing newline. Pins backward compat for
    the v0.1 / v0.2 prompts."""
    from harness.prompts import extract_assembly

    response = "  cmp x0, x1\ncsel x0, x0, x1, le  \n"
    assert extract_assembly(response) == "cmp x0, x1\ncsel x0, x0, x1, le\n"


def test_non_failed_context_templates_do_not_leak_edge_case_block() -> None:
    """Existing ablation templates must NOT carry the new edge-case block.
    They exist precisely to isolate that variable in the search."""
    from harness.prompts import build_prompt

    for tmpl in ("no_failed_context", "strict_no_memory", "structural_hint"):
        body = build_prompt("cmp x0, x1", 17, template=tmpl)[-1]["content"]
        assert "case 1 failed" not in body and "9223372036854775807" not in body, tmpl
