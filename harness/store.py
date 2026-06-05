from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


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
    template TEXT NOT NULL,
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
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(attempts)")}
        if "requested_n" not in columns:
            self.db.execute("ALTER TABLE attempts ADD COLUMN requested_n INTEGER NOT NULL DEFAULT 0")
        if "response_count" not in columns:
            self.db.execute("ALTER TABLE attempts ADD COLUMN response_count INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self.db.close()

    def record_attempt(
        self,
        problem_id: str,
        template: str,
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
        self.db.commit()
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
            INSERT OR REPLACE INTO candidates
            (candidate_hash, problem_id, source, score, verified, model_id, provider_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (candidate_hash, problem_id, source, score, int(verified), model_id, provider_id),
        )
        self.db.commit()

    def record_receipt(self, candidate_hash: str, receipt_path: Path, signature: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO receipts (candidate_hash, receipt_path, signature) VALUES (?, ?, ?)",
            (candidate_hash, str(receipt_path), signature),
        )
        self.db.commit()

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

    def export_leaderboard(self, problem_id: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.leaderboard(problem_id)
        stats = self.attempt_stats(problem_id)
        payload = {
            "problem_id": problem_id,
            **stats,
            "last_update": rows[0]["discovered_at"] if rows else "",
            "rows": rows,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
