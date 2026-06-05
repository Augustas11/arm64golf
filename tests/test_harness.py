from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest

from harness.attest import sign_receipt, verify_receipt
from harness.loop import main as loop_main
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


def test_store_preserves_first_candidate_discovery_and_receipt(tmp_path: Path) -> None:
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
    assert rows[0]["receipt_signature"] == "first-signature"
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
    changed_payload = {**payload, "ts": "2026-06-05T00:00:01Z"}
    again = sign_receipt(changed_payload, tmp_path / "sign.key", tmp_path / "PUBKEY", tmp_path / "receipts")
    assert again == receipt
    assert receipt.path.read_text() == original


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
    assert "bin/validate-receipts.py" in report


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
    assert "air5_model" in payload["blockers"]


def test_ready_live_run_can_report_ready_when_all_checks_pass(monkeypatch) -> None:
    script = load_script("bin/ready-live-run.py")

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
