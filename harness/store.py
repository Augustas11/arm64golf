from __future__ import annotations

import json
import re
import sqlite3
from hashlib import sha256
from pathlib import Path
from typing import Any

from harness.attest import atomic_write_text
from harness.prompts import template_id


_SANDBOX_PATH_RE = re.compile(r"/private/tmp/arm64golf-sandbox/run-[a-z0-9]+/")


def _redact_sandbox_paths(text: str) -> str:
    return _SANDBOX_PATH_RE.sub("sandbox/", text)


SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    candidate_hash TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    source TEXT NOT NULL,
    score INTEGER NOT NULL,
    verified INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id TEXT NOT NULL,
    template TEXT,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    requested_n INTEGER NOT NULL DEFAULT 0,
    response_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS receipts (
    candidate_hash TEXT PRIMARY KEY,
    receipt_path TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    problem_id TEXT NOT NULL,
    candidate_hash TEXT NOT NULL,
    score INTEGER NOT NULL,
    verified INTEGER NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

SEED_MODEL_ID = "reference-baseline"
SEED_PROVIDER_ID = "local-harness"
MAX_LEADERBOARD_PAIRS = 256


def instruction_mnemonics(source: str) -> list[str]:
    mnemonics: list[str] = []
    for raw_line in source.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line or line.startswith("."):
            continue
        if ":" in line:
            label, rest = line.split(":", 1)
            if label.strip() and not label.strip().startswith("."):
                line = rest.strip()
        if not line or line.startswith("."):
            continue
        mnemonics.append(line.split(None, 1)[0].lower())
    return mnemonics


def structural_fingerprint(source: str) -> str:
    sequence = " ".join(instruction_mnemonics(source))
    return sha256(sequence.encode("utf-8")).hexdigest()[:16]


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self._manual_transaction = False
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        column_rows = self.db.execute("PRAGMA table_info(attempts)").fetchall()
        columns = {row["name"] for row in column_rows}
        if "requested_n" not in columns:
            self.db.execute("ALTER TABLE attempts ADD COLUMN requested_n INTEGER NOT NULL DEFAULT 0")
        if "response_count" not in columns:
            self.db.execute("ALTER TABLE attempts ADD COLUMN response_count INTEGER NOT NULL DEFAULT 0")
        refreshed_columns = self.db.execute("PRAGMA table_info(attempts)").fetchall()
        template_column = next((row for row in refreshed_columns if row["name"] == "template"), None)
        if template_column is not None and int(template_column["notnull"]) == 1:
            self._rebuild_attempts_with_nullable_template()

    def _rebuild_attempts_with_nullable_template(self) -> None:
        self.db.execute("ALTER TABLE attempts RENAME TO attempts_old")
        self.db.execute(
            """
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                template TEXT,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                requested_n INTEGER NOT NULL DEFAULT 0,
                response_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """
        )
        self.db.execute(
            """
            INSERT INTO attempts (id, problem_id, template, status, error, requested_n, response_count, created_at)
            SELECT id, problem_id, template, status, error, requested_n, response_count, created_at
            FROM attempts_old
            """
        )
        self.db.execute("DROP TABLE attempts_old")

    def close(self) -> None:
        self.db.close()

    def begin_immediate(self) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self._manual_transaction = True

    def commit(self) -> None:
        self.db.commit()
        self._manual_transaction = False

    def rollback(self) -> None:
        self.db.rollback()
        self._manual_transaction = False

    def _commit_unless_manual_transaction(self) -> None:
        if not self._manual_transaction:
            self.db.commit()

    def record_attempt(
        self,
        problem_id: str,
        template: str | None,
        status: str,
        error: str = "",
        requested_n: int = 0,
        response_count: int = 0,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO attempts (problem_id, template, status, error, requested_n, response_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (problem_id, template, status, error, requested_n, response_count),
        )
        self._commit_unless_manual_transaction()
        return int(cur.lastrowid)

    def record_candidate(
        self,
        *,
        candidate_hash: str,
        problem_id: str,
        source: str,
        score: int,
        verified: bool,
        model_id: str,
        provider_id: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO candidates
            (candidate_hash, problem_id, source, score, verified, model_id, provider_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_hash) DO UPDATE SET
                verified = MAX(candidates.verified, excluded.verified),
                model_id = CASE
                    WHEN candidates.model_id = 'reference-baseline'
                        AND candidates.provider_id = 'local-harness'
                        AND excluded.verified = 1
                        AND excluded.model_id != 'reference-baseline'
                    THEN excluded.model_id
                    ELSE candidates.model_id
                END,
                provider_id = CASE
                    WHEN candidates.model_id = 'reference-baseline'
                        AND candidates.provider_id = 'local-harness'
                        AND excluded.verified = 1
                        AND excluded.model_id != 'reference-baseline'
                    THEN excluded.provider_id
                    ELSE candidates.provider_id
                END,
                discovered_at = CASE
                    WHEN candidates.model_id = 'reference-baseline'
                        AND candidates.provider_id = 'local-harness'
                        AND excluded.verified = 1
                        AND excluded.model_id != 'reference-baseline'
                    THEN excluded.discovered_at
                    ELSE candidates.discovered_at
                END
            """,
            (candidate_hash, problem_id, source, score, int(verified), model_id, provider_id),
        )
        self._commit_unless_manual_transaction()

    def record_receipt(self, candidate_hash: str, receipt_path: Path, signature: str) -> None:
        self.db.execute(
            """
            INSERT INTO receipts (candidate_hash, receipt_path, signature)
            VALUES (?, ?, ?)
            ON CONFLICT(candidate_hash) DO UPDATE SET
                receipt_path = excluded.receipt_path,
                signature = excluded.signature
            """,
            (candidate_hash, str(receipt_path), signature),
        )
        self._commit_unless_manual_transaction()

    def candidate(self, problem_id: str, candidate_hash: str):
        cur = self.db.execute(
            "SELECT * FROM candidates WHERE problem_id = ? AND candidate_hash = ?",
            (problem_id, candidate_hash),
        )
        return cur.fetchone()

    def record_evaluation(
        self,
        *,
        attempt_id: int,
        problem_id: str,
        candidate_hash: str,
        score: int,
        verified: bool,
        error: str = "",
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO evaluations (attempt_id, problem_id, candidate_hash, score, verified, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (attempt_id, problem_id, candidate_hash, score, int(verified), error),
        )
        self._commit_unless_manual_transaction()
        return int(cur.lastrowid)

    def attempt_count(self, problem_id: str) -> int:
        cur = self.db.execute("SELECT COUNT(*) FROM attempts WHERE problem_id = ?", (problem_id,))
        return int(cur.fetchone()[0])

    def attempt_stats(self, problem_id: str) -> dict[str, int]:
        cur = self.db.execute(
            """
            SELECT
                COUNT(*) AS attempt_count,
                COALESCE(SUM(requested_n), 0) AS requested_candidate_count,
                COALESCE(SUM(response_count), 0) AS candidate_response_count
            FROM attempts
            WHERE problem_id = ?
            """,
            (problem_id,),
        )
        row = cur.fetchone()
        return {
            "attempt_count": int(row["attempt_count"]),
            "requested_candidate_count": int(row["requested_candidate_count"]),
            "candidate_response_count": int(row["candidate_response_count"]),
        }

    def run_summary(self, problem_id: str) -> dict[str, Any]:
        stats = self.attempt_stats(problem_id)
        eval_count = self.db.execute(
            "SELECT COUNT(*) FROM evaluations WHERE problem_id = ?",
            (problem_id,),
        ).fetchone()[0]
        verified_count = self.db.execute(
            "SELECT COUNT(*) FROM evaluations WHERE problem_id = ? AND verified = 1",
            (problem_id,),
        ).fetchone()[0]
        first_verified = self._first_verified_eval(problem_id)
        first_17 = self._first_verified_eval(problem_id, max_score=17)
        first_16 = self._first_verified_eval(problem_id, max_score=16)
        best = self.best_candidate(problem_id)
        diversity = self.structural_diversity(problem_id)
        return {
            **stats,
            "evaluation_count": int(eval_count),
            "verified_evaluation_count": int(verified_count),
            "failed_evaluation_count": int(eval_count) - int(verified_count),
            "evaluation_error_count": self.evaluation_error_count(problem_id),
            "top_evaluation_errors": self.evaluation_error_summary(problem_id),
            "best_verified_score": int(best["score"]) if best else None,
            "first_verified_response": self._eval_ordinal(problem_id, first_verified),
            "first_17_response": self._eval_ordinal(problem_id, first_17),
            "first_16_response": self._eval_ordinal(problem_id, first_16),
            "near_best_candidate_count": diversity["candidate_count"],
            "near_best_unique_structure_count": diversity["unique_structure_count"],
            "near_best_structures": diversity["structures"],
        }

    def evaluation_error_count(self, problem_id: str) -> int:
        cur = self.db.execute(
            "SELECT COUNT(*) FROM evaluations WHERE problem_id = ? AND error != ''",
            (problem_id,),
        )
        return int(cur.fetchone()[0])

    def evaluation_error_summary(self, problem_id: str, limit: int = 5) -> list[dict[str, int | str]]:
        cur = self.db.execute(
            """
            SELECT error, COUNT(*) AS count
            FROM evaluations
            WHERE problem_id = ? AND error != ''
            GROUP BY error
            ORDER BY count DESC, error ASC
            LIMIT ?
            """,
            (problem_id, limit),
        )
        return [{"error": _redact_sandbox_paths(row["error"]), "count": int(row["count"])} for row in cur.fetchall()]

    def _eval_ordinal(self, problem_id: str, row: sqlite3.Row | None) -> int | None:
        if row is None:
            return None
        cur = self.db.execute(
            "SELECT COUNT(*) FROM evaluations WHERE problem_id = ? AND id <= ?",
            (problem_id, row["id"]),
        )
        return int(cur.fetchone()[0])

    def _first_verified_eval(self, problem_id: str, max_score: int | None = None) -> sqlite3.Row | None:
        where = "problem_id = ? AND verified = 1"
        params: list[object] = [problem_id]
        if max_score is not None:
            where += " AND score <= ?"
            params.append(max_score)
        cur = self.db.execute(
            f"""
            SELECT *
            FROM evaluations
            WHERE {where}
            ORDER BY id ASC
            LIMIT 1
            """,
            params,
        )
        return cur.fetchone()

    def best_candidate(self, problem_id: str) -> sqlite3.Row | None:
        cur = self.db.execute(
            """
            SELECT * FROM candidates
            WHERE problem_id = ? AND verified = 1
            ORDER BY score ASC, discovered_at ASC
            LIMIT 1
            """,
            (problem_id,),
        )
        return cur.fetchone()

    def structural_diversity(self, problem_id: str, near_best_delta: int = 1, limit: int = 10) -> dict[str, Any]:
        best = self.best_candidate(problem_id)
        if best is None:
            return {
                "candidate_count": 0,
                "unique_structure_count": 0,
                "structures": [],
            }

        max_score = int(best["score"]) + near_best_delta
        cur = self.db.execute(
            """
            SELECT candidate_hash, score, source
            FROM candidates
            WHERE problem_id = ? AND verified = 1 AND score <= ?
            ORDER BY score ASC, discovered_at ASC, candidate_hash ASC
            """,
            (problem_id, max_score),
        )
        structures: dict[str, dict[str, Any]] = {}
        candidate_count = 0
        for row in cur.fetchall():
            candidate_count += 1
            mnemonics = instruction_mnemonics(row["source"])
            fingerprint = structural_fingerprint(row["source"])
            if fingerprint not in structures:
                structures[fingerprint] = {
                    "fingerprint": fingerprint,
                    "candidate_count": 0,
                    "representative_hash_short": row["candidate_hash"][:12],
                    "representative_score": int(row["score"]),
                    "instruction_count": len(mnemonics),
                    "opcode_sequence": mnemonics,
                }
            structures[fingerprint]["candidate_count"] += 1

        ordered = sorted(
            structures.values(),
            key=lambda item: (int(item["representative_score"]), str(item["fingerprint"])),
        )
        return {
            "candidate_count": candidate_count,
            "unique_structure_count": len(structures),
            "structures": ordered[:limit],
        }

    def leaderboard(self, problem_id: str) -> list[dict[str, Any]]:
        cur = self.db.execute(
            """
            SELECT c.*, r.signature
            FROM candidates c
            LEFT JOIN receipts r ON r.candidate_hash = c.candidate_hash
            WHERE c.problem_id = ? AND c.verified = 1
            ORDER BY c.score ASC, c.discovered_at ASC
            """,
            (problem_id,),
        )
        rows = []
        for rank, row in enumerate(cur.fetchall(), start=1):
            rows.append(
                {
                    "rank": rank,
                    "score": row["score"],
                    "candidate_hash": row["candidate_hash"],
                    "candidate_hash_short": row["candidate_hash"][:12],
                    "model_id": row["model_id"],
                    "provider_id": row["provider_id"],
                    "receipt_signature": row["signature"] or "",
                    "receipt_signature_short": (row["signature"] or "")[:16],
                    "discovered_at": row["discovered_at"],
                }
            )
        return rows

    def _receipt_attestation_kind(self, receipt_path: object) -> str | None:
        if not receipt_path:
            return None
        try:
            envelope = json.loads(Path(str(receipt_path)).read_text())
        except (OSError, json.JSONDecodeError):
            return None
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return None
        attestation = payload.get("attestation")
        if not isinstance(attestation, dict):
            return None
        kind = attestation.get("kind")
        return kind if isinstance(kind, str) else None

    def _pair_attribution_kind(self, template_name: str | None, receipt_path: object) -> str:
        if template_name == "mock":
            return "mock"
        if template_name == "open-submission":
            return "open_submission"
        if self._receipt_attestation_kind(receipt_path) == "open-submission":
            return "open_submission"
        return "reference_harness"

    @staticmethod
    def _sort_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            pairs,
            key=lambda pair: (
                pair["best_verified_score"] is None,
                pair["best_verified_score"] if pair["best_verified_score"] is not None else 0,
                -int(pair["evaluated_responses"]),
                str(pair["provider_id"]),
                "" if pair["template_name"] is None else str(pair["template_name"]),
                str(pair["model_id"]),
            ),
        )

    def _run_pairs_with_truncation(self, problem_id: str) -> tuple[list[dict[str, Any]], bool]:
        cur = self.db.execute(
            """
            SELECT
                e.id AS evaluation_id,
                e.score AS evaluation_score,
                e.verified AS evaluation_verified,
                a.template AS template_name,
                c.provider_id AS provider_id,
                c.model_id AS model_id,
                r.receipt_path AS receipt_path
            FROM evaluations e
            JOIN attempts a ON a.id = e.attempt_id
            JOIN candidates c ON c.candidate_hash = e.candidate_hash
                AND c.problem_id = e.problem_id
            LEFT JOIN receipts r ON r.candidate_hash = c.candidate_hash
            WHERE e.problem_id = ?
                AND a.problem_id = ?
                -- Exclude seed rows using both durable seed signals. Older
                -- ledgers may have recorded a seed attempt; current seed-only
                -- exports keep the seed as reference-baseline attribution.
                -- Exclude open-submission rows from pair aggregation: they are
                -- represented as individual leaderboard rows, not synthetic
                -- provider/model/template groups.
                AND a.template IS NOT NULL
                AND a.template != 'seed-baseline'
                AND a.template != 'open-submission'
                AND c.model_id != ?
            ORDER BY
                c.provider_id ASC,
                c.model_id ASC,
                a.template ASC,
                e.id ASC
            """,
            (problem_id, problem_id, SEED_MODEL_ID),
        )

        groups: dict[tuple[str, str, str, str | None, str], dict[str, Any]] = {}
        for row in cur.fetchall():
            raw_template_name = row["template_name"]
            template_name = str(raw_template_name) if raw_template_name is not None else None
            attribution_kind = self._pair_attribution_kind(template_name, row["receipt_path"])
            if attribution_kind == "reference_harness":
                if template_name is None:
                    continue
                try:
                    current_template_id: str | None = template_id(template_name)
                except (KeyError, ValueError):
                    continue
                output_template_name = template_name
            else:
                current_template_id = None
                output_template_name = None

            key = (
                problem_id,
                str(row["provider_id"]),
                str(row["model_id"]),
                current_template_id,
                attribution_kind,
            )
            pair = groups.get(key)
            if pair is None:
                pair = {
                    "problem_id": key[0],
                    "provider_id": key[1],
                    "model_id": key[2],
                    "template_name": output_template_name,
                    "template_id": key[3],
                    "attribution_kind": key[4],
                    "evaluated_responses": 0,
                    "verified_count": 0,
                    "best_verified_score": None,
                    "first_verified_response": None,
                    "first_17_response": None,
                    "first_16_response": None,
                }
                groups[key] = pair

            pair["evaluated_responses"] += 1
            ordinal = int(pair["evaluated_responses"])
            verified = int(row["evaluation_verified"]) == 1
            score = int(row["evaluation_score"])
            if not verified:
                continue

            pair["verified_count"] += 1
            best = pair["best_verified_score"]
            pair["best_verified_score"] = score if best is None else min(int(best), score)
            if pair["first_verified_response"] is None:
                pair["first_verified_response"] = ordinal
            if score <= 17 and pair["first_17_response"] is None:
                pair["first_17_response"] = ordinal
            if score <= 16 and pair["first_16_response"] is None:
                pair["first_16_response"] = ordinal

        ordered = self._sort_pairs(list(groups.values()))
        return ordered[:MAX_LEADERBOARD_PAIRS], len(ordered) > MAX_LEADERBOARD_PAIRS

    def run_pairs(self, problem_id: str) -> list[dict[str, Any]]:
        pairs, _truncated = self._run_pairs_with_truncation(problem_id)
        return pairs

    def export_leaderboard(self, problem_id: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.leaderboard(problem_id)
        stats = self.attempt_stats(problem_id)
        pairs, pairs_truncated = self._run_pairs_with_truncation(problem_id)
        payload = {
            "problem_id": problem_id,
            **stats,
            "run_summary": self.run_summary(problem_id),
            "last_update": rows[0]["discovered_at"] if rows else "",
            "pairs": pairs,
            "rows": rows,
        }
        if pairs_truncated:
            payload["pairs_truncated"] = True
        atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
