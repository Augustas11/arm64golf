from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.attest import sign_receipt, verify_receipt
from harness.inference import InferenceError, parse_chat_response
from harness.module import load_problem_module
from harness.store import Store


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
