from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest

from harness.attest import sign_receipt, verify_receipt
from harness.inference import InferenceError, parse_chat_response
from harness.module import load_problem_module
from harness.store import Store


def load_script(path: str):
    spec = importlib.util.spec_from_file_location(path.replace("/", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_sort3_module_and_verify_baseline() -> None:
    module = load_problem_module(Path("problems/sort3-arm64"))
    count, source = module.baseline()
    candidate = module.load(source)
    assert count == 18
    assert candidate.instruction_count == 18
    assert module.verify(candidate)


def test_parse_chat_response_returns_all_choices() -> None:
    raw = b'{"choices":[{"message":{"content":"cmp x0, x1"}},{"message":{"content":"ret"}}]}'
    assert parse_chat_response(raw) == ["cmp x0, x1", "ret"]


def test_parse_chat_response_rejects_malformed_payload() -> None:
    with pytest.raises(InferenceError):
        parse_chat_response(b'{"choices":[{}]}')


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
    store.record_receipt("abc123", tmp_path / "receipt.json", "signature")
    out = tmp_path / "leaderboard.json"
    store.export_leaderboard("sort3-arm64", out)
    payload = json.loads(out.read_text())
    assert payload["rows"][0]["rank"] == 1
    assert payload["rows"][0]["score"] == 17
    assert payload["rows"][0]["receipt_signature"] == "signature"
    store.close()


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
