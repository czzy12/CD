"""Gate F3B tests: review prep, validation, gold freeze logic (no prediction)."""

from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f3b-human-gold-20260808"
)
HOLDOUT_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f3a-1-resume-holdout-20260808"
)


def _load_tool():
    path = REPO_ROOT / "tools" / "knowledge" / "gate_f3b_prep.py"
    spec = importlib.util.spec_from_file_location("gate_f3b_prep", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(REVIEW_DIR.is_dir(), "F3B review artifacts not present")
class F3bPrepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load_tool()
        with open(
            REVIEW_DIR / "transaction_human_review_v1.csv",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            cls.tx_rows = list(csv.DictReader(f))
        with open(
            REVIEW_DIR / "case_human_review_v1.csv",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            cls.case_rows = list(csv.DictReader(f))
        with open(
            REVIEW_DIR / "transaction_qc_rereview_v1.csv",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            cls.qc_rows = list(csv.DictReader(f))

    def test_review_row_counts(self):
        self.assertEqual(len(self.tx_rows), 100)
        self.assertEqual(len(self.case_rows), 5)
        self.assertEqual(len(self.qc_rows), 10)

    def test_no_candidate_prediction_columns(self):
        forbidden = {
            "role",
            "trace_strength",
            "routing_state",
            "industry_relevance",
            "concept_id",
            "concept_name",
            "final_relevance",
        }
        self.assertEqual(forbidden.intersection(self.tx_rows[0]), set())

    def test_gold_columns_blank_in_review_files(self):
        for row in self.tx_rows:
            self.assertEqual(
                row["human_business_evidence_role"],
                "",
            )
            self.assertEqual(row["human_expected_route"], "")
        for row in self.case_rows:
            self.assertEqual(row["business_activity_presence"], "")
            self.assertEqual(row["declared_industry_consistency"], "")

    def test_existing_gold_still_blank(self):
        lines = (
            HOLDOUT_DIR
            / "production_transaction_evidence_human_gold_v1_blank.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        gold = [json.loads(line) for line in lines if line.strip()]
        self.assertEqual(len(gold), 100)
        self.assertTrue(
            all(
                item["status"] == "awaiting_human_review"
                and item["human_business_evidence_role"] == ""
                for item in gold
            )
        )
        case_gold = json.loads(
            (HOLDOUT_DIR / "production_case_human_gold_v1_blank.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(case_gold["status"], "awaiting_human_review")
        self.assertEqual(len(case_gold["cases"]), 5)

    def test_validator_rejects_invalid_enum(self):
        items = [
            {"holdout_item_id": "TXH-V1-0001"},
        ]
        gold = [
            {
                "holdout_item_id": "TXH-V1-0001",
                "human_industry_direct_relation": "super",
                "human_business_evidence_role": "unknown",
                "human_business_trace_strength": "undetermined",
                "human_expected_route": "insufficient_transaction",
                "reviewer_reasoning": "x",
                "reviewer_id": "user",
            }
        ]
        result = self.tool.validate_transaction_gold(gold, items)
        self.assertIn("TXH-V1-0001: invalid industry relation", result["errors"])

    def test_validator_accepts_valid_gold(self):
        items = [
            {
                "holdout_item_id": "TXH-V1-0001",
            }
        ]
        gold = [
            {
                "holdout_item_id": "TXH-V1-0001",
                "human_industry_direct_relation": "weak",
                "human_business_evidence_role": "tax_regulatory",
                "human_business_trace_strength": "medium",
                "human_expected_route": "local_resolved",
                "human_sufficient_information": "true",
                "human_confidence": "medium",
                "supporting_evidence_refs": [],
                "reviewer_reasoning": "recurring tax",
                "reviewer_id": "user",
                "reviewed_at": "2026-08-08",
                "review_standard_version": "human_gold_review_standard_v1",
            }
        ]
        result = self.tool.validate_transaction_gold(gold, items)
        self.assertEqual(result["errors"], [])

    def test_freeze_creates_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = self.tool.freeze_gold(
                output_dir=out,
                tx_gold=[
                    {
                        "holdout_item_id": "TXH-V1-0001",
                        "human_business_evidence_role": "tax_regulatory",
                    }
                ],
                case_gold=[],
                qc_results={"agreement": 1, "major_disagreement": 0},
                reviewer="human_user",
                reviewed_at_range=["2026-08-08"],
                candidate_v2_checksum="x" * 64,
                holdout_checksum="y" * 64,
            )
            self.assertEqual(manifest["prediction_call_count"], 0)
            self.assertEqual(manifest["provider_call_count"], 0)
            self.assertTrue(
                (out / "human_gold_freeze_manifest.json").is_file()
            )
            self.assertTrue(
                (
                    out
                    / "production_transaction_evidence_human_gold_v1.jsonl"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
