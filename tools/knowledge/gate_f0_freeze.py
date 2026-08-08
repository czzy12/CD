"""Gate F0: freeze the production candidate knowledge_v1 system state."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import versioning


PREDICTION_FILES = (
    "bankflow_v2/knowledge/versioning.py",
    "bankflow_v2/knowledge/semantic_concepts.py",
    "bankflow_v2/knowledge/relations.py",
    "bankflow_v2/knowledge/resolver.py",
    "bankflow_v2/knowledge/normalization.py",
    "bankflow_v2/knowledge/payment_rail.py",
    "bankflow_v2/knowledge/privacy.py",
    "bankflow_v2/knowledge/ai_fallback.py",
    "bankflow_v2/knowledge/ai_validation.py",
    "bankflow_v2/ai_business_observation.py",
    "bankflow_v2/knowledge/canonical/taxonomy.json",
    "bankflow_v2/knowledge/canonical/semantic_concepts.json",
    "bankflow_v2/knowledge/canonical/semantic_aliases.json",
    "bankflow_v2/knowledge/canonical/relations.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> tuple[str, int]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip(), result.returncode


def _pending_counts(db_path: Path) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    if not db_path.is_file():
        return counts
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT candidate_type, prompt_version, review_status "
        "FROM candidates"
    ).fetchall()
    conn.close()
    for candidate_type, prompt_version, status in rows:
        if status == "pending":
            counts[(candidate_type, prompt_version)] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("D:/Investigator PDF/CD-bankflow-refactor"),
    )
    parser.add_argument(
        "--main-cache",
        type=Path,
        default=Path("D:/Investigator PDF/outputs/knowledge-v1-cache/knowledge_v1_runtime.db"),
    )
    parser.add_argument(
        "--d31-cache",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/gate-d3-1-recall-recovery-20260808/"
            "cache-final3/knowledge_v1_runtime.db"
        ),
    )
    parser.add_argument(
        "--gate-e-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/gate-e-legacy-relation-review-20260808"
        ),
    )
    args = parser.parse_args()

    branch, _ = _git(args.repo, "branch", "--show-current")
    commit, _ = _git(args.repo, "rev-parse", "HEAD")
    now = datetime.now(timezone.utc).isoformat()

    file_checksums: dict[str, str] = {}
    for relative in PREDICTION_FILES:
        path = args.repo / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing prediction file: {path}")
        file_checksums[relative.replace("\\", "/")] = _sha256(path)

    main_counts = _pending_counts(args.main_cache)
    d31_counts = _pending_counts(args.d31_cache)
    d3_calibration = sum(
        count
        for (candidate_type, prompt_version), count in main_counts.items()
        if prompt_version == "semantic-concept-v2"
    )
    d31_calibration = sum(
        count
        for (candidate_type, prompt_version), count in d31_counts.items()
        if prompt_version == "semantic-concept-v3"
    )
    gate_d_pending = sum(
        count
        for (candidate_type, prompt_version), count in main_counts.items()
        if prompt_version in {"semantic-concept-v1", "industry-concept-relevance-v1"}
    )
    legacy_relation_pending_db = sum(
        count
        for (candidate_type, prompt_version), count in main_counts.items()
        if candidate_type == "new_industry_relation"
        and prompt_version == "business-relevance-mvp-v11"
    )

    gate_e_summary = {}
    gate_e_promotion = {}
    if (args.gate_e_dir / "gate_e_summary.json").is_file():
        gate_e_summary = json.loads(
            (args.gate_e_dir / "gate_e_summary.json").read_text(encoding="utf-8")
        )
    if (args.gate_e_dir / "legacy_relation_promotion_result.json").is_file():
        gate_e_promotion = json.loads(
            (
                args.gate_e_dir / "legacy_relation_promotion_result.json"
            ).read_text(encoding="utf-8")
        )

    blocked_contract_count = int(
        gate_e_promotion.get("blocked", 0)
        if isinstance(gate_e_promotion, dict)
        else 0
    )
    known_limitations = {
        "gate_e_evidence_specific_none": {
            "count": blocked_contract_count,
            "human_gold": "none",
            "current_local_baseline": "weak",
            "reason": (
                "evidence-specific relation cannot be expressed by "
                "industry x concept-only model"
            ),
        },
        "property_management_06_conditional": {
            "human_gold": "conditional medium",
            "current_canonical": "undetermined / conditional_relation_candidate",
            "reason": "relation-level condition cannot be expressed by current contract",
        },
        "calibration_pending_excluded": {
            "count": d3_calibration + d31_calibration,
            "d3_calibration": d3_calibration,
            "d31_calibration": d31_calibration,
        },
    }

    excluded_pending = {
        "calibration_generated_pending": d3_calibration + d31_calibration,
        "d3_calibration_pending": d3_calibration,
        "d31_calibration_pending": d31_calibration,
        "gate_d_real_ai_pending_db": gate_d_pending,
        "gate_e_legacy_relation_pending_db": legacy_relation_pending_db,
        "gate_e_human_reviewed_not_promoted": (
            int(gate_e_summary.get("total_reviewed", 0))
            if isinstance(gate_e_summary, dict)
            else 0
        ),
        "note": (
            "Gate D/Gate E candidates remain in candidate store without canonical "
            "promotion; human review records are stored in Gate artifacts."
        ),
    }

    manifest_payload = {
        "freeze_version": "production-candidate-v1",
        "freeze_timestamp": now,
        "git_commit": commit,
        "branch": branch,
        "schema_version": "1.17",
        "knowledge_version": versioning.KNOWLEDGE_VERSION,
        "semantic_concepts_version": versioning.SEMANTIC_KB_VERSION,
        "semantic_aliases_version": versioning.ALIAS_KB_VERSION,
        "relation_kb_version": versioning.RELATION_KB_VERSION,
        "resolver_version": versioning.RESOLVER_VERSION,
        "semantic_concept_task_version": versioning.PROMPT_SEMANTIC_CONCEPT_VERSION,
        "relation_task_version": versioning.PROMPT_INDUSTRY_RELATION_VERSION,
        "file_checksums": file_checksums,
        "known_limitations": known_limitations,
        "excluded_pending_inventory": excluded_pending,
        "production_status": "shadow",
        "production_resolver": "legacy_v11",
        "knowledge_v1": "shadow",
        "holdout_not_started": True,
    }
    manifest_checksum = hashlib.sha256(
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        **manifest_payload,
        "manifest_checksum": manifest_checksum,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "production_candidate_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "production_candidate_checksums.json").write_text(
        json.dumps(
            {
                "manifest_checksum": manifest_checksum,
                "file_checksums": file_checksums,
                "canonical_files": {
                    name: file_checksums[name]
                    for name in file_checksums
                    if "/canonical/" in name
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "known_limitations.json").write_text(
        json.dumps(known_limitations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "excluded_pending_inventory.json").write_text(
        json.dumps(excluded_pending, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "freeze_integrity_report.md").write_text(
        _render_report(manifest),
        encoding="utf-8",
    )

    print("status=ok")
    print(f"freeze_version=production-candidate-v1")
    print(f"manifest_checksum={manifest_checksum}")
    print(f"knowledge={versioning.KNOWLEDGE_VERSION}")
    print(f"schema=1.17")
    print(f"output={args.output_dir}")
    return 0


def _render_report(manifest: dict) -> str:
    return "\n".join(
        [
            "# Gate F0 — Production Candidate Freeze",
            "",
            f"- freeze_version：`{manifest['freeze_version']}`",
            f"- git_commit：`{manifest['git_commit']}`",
            f"- branch：`{manifest['branch']}`",
            f"- schema：`{manifest['schema_version']}`",
            f"- knowledge：`{manifest['knowledge_version']}`",
            f"- concepts：`{manifest['semantic_concepts_version']}`",
            f"- aliases：`{manifest['semantic_aliases_version']}`",
            f"- relations：`{manifest['relation_kb_version']}`",
            f"- resolver：`{manifest['resolver_version']}`",
            f"- semantic concept task：`{manifest['semantic_concept_task_version']}`",
            f"- relation task：`{manifest['relation_task_version']}`",
            f"- manifest checksum：`{manifest['manifest_checksum']}`",
            "",
            "## Known Limitations",
            "",
            f"`{json.dumps(manifest['known_limitations'], ensure_ascii=False, indent=2)}`",
            "",
            "## Excluded Pending Inventory",
            "",
            f"`{json.dumps(manifest['excluded_pending_inventory'], ensure_ascii=False, indent=2)}`",
            "",
            "## Production Status",
            "",
            f"- production status：{manifest['production_status']}",
            f"- production resolver：{manifest['production_resolver']}",
            f"- knowledge_v1：{manifest['knowledge_v1']}",
            "- prediction-affecting files checksummed；freeze immutable until Holdout blind run completes.",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
