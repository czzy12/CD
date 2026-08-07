"""Runtime knowledge cache (SQLite) separated from canonical Git knowledge."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import KnowledgeCandidate
from .versioning import fingerprint


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeKnowledgeRepository:
    """Cache + candidate store. Never stores customer IDs or raw sensitive text."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else None
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.root / "knowledge_v1_runtime.db"))
        else:
            self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS semantic_cache (
                signature_version TEXT NOT NULL,
                signature_hash TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                resolution_source TEXT NOT NULL,
                knowledge_version TEXT NOT NULL,
                review_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (signature_version, signature_hash)
            );
            CREATE TABLE IF NOT EXISTS relation_cache (
                taxonomy_version TEXT NOT NULL,
                industry_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                relation_rules_version TEXT NOT NULL,
                relevance TEXT NOT NULL,
                relation_source TEXT NOT NULL,
                knowledge_version TEXT NOT NULL,
                review_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (
                    taxonomy_version, industry_id, concept_id,
                    relation_rules_version
                )
            );
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                candidate_key TEXT NOT NULL UNIQUE,
                candidate_type TEXT NOT NULL,
                proposed_value_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                input_signature_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                review_status TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    @staticmethod
    def _candidate_key(candidate: KnowledgeCandidate) -> str:
        return fingerprint(
            {
                "type": candidate.candidate_type,
                "proposed": candidate.proposed_value,
                "input": candidate.input_signature,
            }
        )

    def semantic_cache_get(
        self,
        signature_version: str,
        signature_hash: str,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM semantic_cache "
            "WHERE signature_version = ? AND signature_hash = ?",
            (signature_version, signature_hash),
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            "UPDATE semantic_cache SET hit_count = hit_count + 1 "
            "WHERE signature_version = ? AND signature_hash = ?",
            (signature_version, signature_hash),
        )
        self._conn.commit()
        updated = self._conn.execute(
            "SELECT * FROM semantic_cache "
            "WHERE signature_version = ? AND signature_hash = ?",
            (signature_version, signature_hash),
        ).fetchone()
        return dict(updated)

    def semantic_cache_put(
        self,
        *,
        signature_version: str,
        signature_hash: str,
        concept_id: str,
        resolution_source: str,
        knowledge_version: str,
        review_status: str = "approved",
    ) -> None:
        now = _utcnow()
        self._conn.execute(
            """
            INSERT INTO semantic_cache (
                signature_version, signature_hash, concept_id,
                resolution_source, knowledge_version, review_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signature_version, signature_hash) DO UPDATE SET
                concept_id = excluded.concept_id,
                resolution_source = excluded.resolution_source,
                knowledge_version = excluded.knowledge_version,
                review_status = excluded.review_status,
                updated_at = excluded.updated_at
            """,
            (
                signature_version,
                signature_hash,
                concept_id,
                resolution_source,
                knowledge_version,
                review_status,
                now,
                now,
            ),
        )
        self._conn.commit()

    def relation_cache_get(
        self,
        *,
        taxonomy_version: str,
        industry_id: str,
        concept_id: str,
        relation_rules_version: str,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM relation_cache WHERE taxonomy_version = ? "
            "AND industry_id = ? AND concept_id = ? "
            "AND relation_rules_version = ?",
            (taxonomy_version, industry_id, concept_id, relation_rules_version),
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            "UPDATE relation_cache SET hit_count = hit_count + 1 "
            "WHERE taxonomy_version = ? AND industry_id = ? "
            "AND concept_id = ? AND relation_rules_version = ?",
            (taxonomy_version, industry_id, concept_id, relation_rules_version),
        )
        self._conn.commit()
        return dict(row)

    def relation_cache_put(
        self,
        *,
        taxonomy_version: str,
        industry_id: str,
        concept_id: str,
        relation_rules_version: str,
        relevance: str,
        relation_source: str,
        knowledge_version: str,
        review_status: str = "approved",
    ) -> None:
        now = _utcnow()
        self._conn.execute(
            """
            INSERT INTO relation_cache (
                taxonomy_version, industry_id, concept_id,
                relation_rules_version, relevance, relation_source,
                knowledge_version, review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                taxonomy_version, industry_id, concept_id,
                relation_rules_version
            ) DO UPDATE SET
                relevance = excluded.relevance,
                relation_source = excluded.relation_source,
                knowledge_version = excluded.knowledge_version,
                review_status = excluded.review_status,
                updated_at = excluded.updated_at
            """,
            (
                taxonomy_version,
                industry_id,
                concept_id,
                relation_rules_version,
                relevance,
                relation_source,
                knowledge_version,
                review_status,
                now,
                now,
            ),
        )
        self._conn.commit()

    def add_candidate(self, candidate: KnowledgeCandidate) -> bool:
        key = self._candidate_key(candidate)
        try:
            self._conn.execute(
                """
                INSERT INTO candidates (
                    candidate_id, candidate_key, candidate_type,
                    proposed_value_json, reason, model, prompt_version,
                    input_signature_json, created_at, review_status,
                    reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    key,
                    candidate.candidate_type,
                    json.dumps(candidate.proposed_value, ensure_ascii=False),
                    candidate.reason,
                    candidate.model,
                    candidate.prompt_version,
                    json.dumps(candidate.input_signature, ensure_ascii=False),
                    candidate.created_at,
                    candidate.review_status,
                    candidate.reviewed_at,
                ),
            )
        except sqlite3.IntegrityError:
            return False
        self._conn.commit()
        return True

    def list_candidates(
        self,
        review_status: str | None = None,
    ) -> list[KnowledgeCandidate]:
        if review_status:
            rows = self._conn.execute(
                "SELECT * FROM candidates WHERE review_status = ? "
                "ORDER BY created_at",
                (review_status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM candidates ORDER BY created_at"
            ).fetchall()
        candidates: list[KnowledgeCandidate] = []
        for row in rows:
            candidate = KnowledgeCandidate(
                candidate_id=str(row["candidate_id"]),
                candidate_type=str(row["candidate_type"]),
                proposed_value=json.loads(row["proposed_value_json"]),
                reason=str(row["reason"]),
                model=str(row["model"]),
                prompt_version=str(row["prompt_version"]),
                input_signature=json.loads(row["input_signature_json"]),
                created_at=str(row["created_at"]),
                review_status=str(row["review_status"]),
                reviewed_at=str(row["reviewed_at"]),
            )
            candidates.append(candidate)
        return candidates

    def review_candidate(
        self,
        candidate_id: str,
        review_status: str,
    ) -> KnowledgeCandidate | None:
        if review_status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"invalid review status: {review_status}")
        now = _utcnow()
        cursor = self._conn.execute(
            "UPDATE candidates SET review_status = ?, reviewed_at = ? "
            "WHERE candidate_id = ?",
            (review_status, now, candidate_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            return None
        for candidate in self.list_candidates():
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def counts(self) -> dict[str, int]:
        semantic = self._conn.execute(
            "SELECT COUNT(*) FROM semantic_cache"
        ).fetchone()[0]
        relation = self._conn.execute(
            "SELECT COUNT(*) FROM relation_cache"
        ).fetchone()[0]
        candidates = self._conn.execute(
            "SELECT COUNT(*) FROM candidates"
        ).fetchone()[0]
        return {
            "semantic_cache_entries": int(semantic),
            "relation_cache_entries": int(relation),
            "candidate_entries": int(candidates),
        }

    def close(self) -> None:
        self._conn.close()
