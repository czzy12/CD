"""Gate F3A tests: pristine holdout boundaries, blank gold, no prediction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f3a-holdout-20260808"
)
FREEZE_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/production-candidate-v2-freeze-20260808"
)
FORBIDDEN_KEYS = {
    "role",
    "trace_strength",
    "routing_state",
    "industry_relevance",
    "concept_id",
    "concept_name",
    "final_relevance",
}


def _load_tool():
    path = REPO_ROOT / "tools" / "knowledge" / "gate_f3a_build_holdout.py"
    spec = importlib.util.spec_from_file_location("gate_f3a_build_holdout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_items():
    lines = (
        OUTPUT_DIR / "production_transaction_evidence_holdout_v1_items.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@unittest.skipUnless(OUTPUT_DIR.is_dir(), "F3A holdout artifacts not present")
class PristineHoldoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tx_manifest = json.loads(
            (
                OUTPUT_DIR
                / "production_transaction_evidence_holdout_v1_manifest.json"
            ).read_text(encoding="utf-8")
        )
        cls.case_manifest = json.loads(
            (
                OUTPUT_DIR / "production_case_holdout_v1_manifest.json"
            ).read_text(encoding="utf-8")
        )
        cls.report = json.loads(
            (OUTPUT_DIR / "gate_f3a_report.json").read_text(
                encoding="utf-8"
            )
        )
        cls.selection = json.loads(
            (OUTPUT_DIR / "holdout_selection_manifest.json").read_text(
                encoding="utf-8"
            )
        )

    def test_candidate_v2_integrity(self):
        manifest = json.loads(
            (FREEZE_DIR / "production_candidate_v2_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for name, digest in manifest["file_checksums"].items():
            self.assertEqual(
                _sha256(REPO_ROOT / name),
                digest,
                f"candidate v2 file changed: {name}",
            )
        self.assertEqual(
            self.report["candidate_v2_integrity_at_end"],
            "verified",
        )

    def test_transaction_items_have_no_candidate_prediction(self):
        items = _read_items()
        self.assertEqual(len(items), self.tx_manifest["actual_count"])
        for item in items:
            self.assertEqual(FORBIDDEN_KEYS.intersection(item), set())

    def test_transaction_gold_blank(self):
        lines = (
            OUTPUT_DIR
            / "production_transaction_evidence_human_gold_v1_blank.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        gold = [json.loads(line) for line in lines if line.strip()]
        self.assertEqual(len(gold), self.tx_manifest["actual_count"])
        for item in gold:
            self.assertEqual(item["status"], "awaiting_human_review")
            self.assertEqual(item["human_business_evidence_role"], "")
            self.assertEqual(item["human_industry_direct_relation"], "")
            self.assertEqual(item["human_business_trace_strength"], "")
            self.assertEqual(item["human_expected_route"], "")

    def test_case_gold_blank(self):
        gold = json.loads(
            (OUTPUT_DIR / "production_case_human_gold_v1_blank.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(gold["status"], "awaiting_human_review")
        self.assertGreaterEqual(len(gold["cases"]), 3)
        for case in gold["cases"]:
            self.assertEqual(case["business_activity_presence"], "")
            self.assertEqual(case["declared_industry_consistency"], "")

    def test_case_pool_overlap_reported(self):
        if not self.case_manifest["transaction_case_pool_disjoint"]:
            self.assertTrue(
                self.case_manifest["case_pool_overlap_with_transaction"]
            )
            self.assertIn(
                "overlap",
                self.case_manifest["overlap_note"],
            )

    def test_duplicate_control(self):
        items = _read_items()
        refs = [item["canonical_transaction_ref"] for item in items]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(
            self.tx_manifest["duplicate_retention"][
                "context_variation_limited"
            ],
            sum(1 for item in items if item["duplicate_retention_reason"]),
        )

    def test_concept_holdout_no_overlap(self):
        self.assertEqual(self.report["concept_holdout_content_overlap"], 0)

    def test_no_prediction_calls(self):
        calls = self.tx_manifest["candidate_prediction_calls"]
        self.assertEqual(calls["knowledge_v1_inference"], 0)
        self.assertEqual(calls["business_evidence_resolver"], 0)
        self.assertEqual(calls["relation_prediction"], 0)
        self.assertEqual(calls["routing_prediction"], 0)
        self.assertEqual(calls["transaction_ai_provider"], 0)
        self.assertEqual(calls["case_ai_provider"], 0)
        case_calls = self.case_manifest["candidate_prediction_calls"]
        self.assertEqual(case_calls["transaction_ai_provider"], 0)
        self.assertEqual(case_calls["case_ai_provider"], 0)

    def test_contamination_registry_exists(self):
        registry = json.loads(
            (
                OUTPUT_DIR
                / "production_holdout_contamination_registry.json"
            ).read_text(encoding="utf-8")
        )
        self.assertGreater(len(registry), 0)

    def test_deterministic_sampling(self):
        tool = _load_tool()
        by_case = {
            "case-a": [
                {
                    "source_case_id": "case-a",
                    "canonical_transaction_ref": f"tx-a-{i}",
                    "declared_industry": "批发业",
                    "month": "2026-01",
                }
                for i in range(25)
            ],
            "case-b": [
                {
                    "source_case_id": "case-b",
                    "canonical_transaction_ref": f"tx-b-{i}",
                    "declared_industry": "零售业",
                    "month": "2026-02",
                }
                for i in range(25)
            ],
        }
        first = tool.select_transaction_instances(by_case)
        second = tool.select_transaction_instances(by_case)
        self.assertEqual(
            [item["canonical_transaction_ref"] for item in first],
            [item["canonical_transaction_ref"] for item in second],
        )
        self.assertLessEqual(
            max(
                sum(
                    1
                    for item in first
                    if item["source_case_id"] == case_id
                )
                for case_id in by_case
            ),
            20,
        )


if __name__ == "__main__":
    unittest.main()
