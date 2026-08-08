"""Gate F3A.1 Resume tests: 0808 ingestion, independent pools, gold standard."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f3a-1-resume-holdout-20260808"
)
REGISTRY_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f3a-1-holdout-20260808"
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
    path = REPO_ROOT / "tools" / "knowledge" / "gate_f3a_1_resume.py"
    spec = importlib.util.spec_from_file_location("gate_f3a_1_resume", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(OUTPUT_DIR.is_dir(), "F3A.1 resume artifacts not present")
class ResumeHoldoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load_tool()
        cls.inventory = json.loads(
            (OUTPUT_DIR / "0808_case_inventory.json").read_text(
                encoding="utf-8"
            )
        )
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
            (OUTPUT_DIR / "gate_f3a_1_resume_report.json").read_text(
                encoding="utf-8"
            )
        )

    def test_inventory_excludes_development_case(self):
        self.assertEqual(len(self.inventory), 15)
        excluded = [
            row for row in self.inventory if row["eligibility_status"] == "excluded"
        ]
        self.assertEqual(len(excluded), 1)
        self.assertIn("李娟", excluded[0]["source_directory"])
        eligible = [
            row for row in self.inventory if row["eligibility_status"] == "eligible"
        ]
        self.assertEqual(len(eligible), 14)

    def test_addresses_are_booleans_only(self):
        serialized = json.dumps(self.inventory, ensure_ascii=False)
        for row in self.inventory:
            if row["eligibility_status"] != "eligible":
                continue
            self.assertIn("company_address_available", row)
            self.assertIn("home_address_available", row)
            self.assertIsInstance(row["company_address_available"], bool)
            self.assertIsInstance(row["home_address_available"], bool)
        # No full address values inside holdout items.
        items_text = (
            OUTPUT_DIR
            / "production_transaction_evidence_holdout_v1_items.jsonl"
        ).read_text(encoding="utf-8")
        for token in ("家庭住址", "公司地址", "家庭地址"):
            self.assertNotIn(token, items_text)

    def test_metadata_provenance(self):
        registry = json.loads(
            (REGISTRY_DIR / "manual_external_metadata_registry.json").read_text(
                encoding="utf-8"
            )
        )
        confirmed = [
            entry
            for entry in registry["entries"]
            if entry.get("human_confirmed") is True
        ]
        self.assertGreaterEqual(len(confirmed), 14)
        for entry in confirmed:
            self.assertEqual(
                entry["metadata_source_type"],
                "human_collected_case_material",
            )
            self.assertFalse(entry["transaction_evidence_used_for_metadata"])
            self.assertEqual(entry["confirmation_status"], "human_confirmed")

    def test_pools_disjoint(self):
        self.assertTrue(self.case_manifest["transaction_case_pool_disjoint"])
        self.assertEqual(
            self.case_manifest["case_pool_overlap_with_transaction"],
            [],
        )

    def test_transaction_target_reached(self):
        self.assertEqual(self.tx_manifest["actual_count"], 100)
        self.assertGreaterEqual(self.tx_manifest["case_count"], 8)
        lines = (
            OUTPUT_DIR
            / "production_transaction_evidence_holdout_v1_items.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        items = [json.loads(line) for line in lines if line.strip()]
        self.assertEqual(len(items), 100)
        for item in items:
            self.assertEqual(FORBIDDEN_KEYS.intersection(item), set())

    def test_case_holdout_size(self):
        self.assertEqual(self.case_manifest["actual_count"], 5)

    def test_reserve_exists(self):
        reserve = json.loads(
            (OUTPUT_DIR / "reserve_cases.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(reserve["count"], 1)

    def test_concept_overlap_zero(self):
        self.assertEqual(self.report["eligible_cases"], 14)
        # Concept overlap was reported as 0 during construction; ensure no
        # eligible case is marked contaminated.
        self.assertTrue(
            all(
                row["contamination_status"] == "clean"
                for row in self.inventory
                if row["eligibility_status"] == "eligible"
            )
        )

    def test_gold_blank(self):
        lines = (
            OUTPUT_DIR
            / "production_transaction_evidence_human_gold_v1_blank.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        gold = [json.loads(line) for line in lines if line.strip()]
        self.assertEqual(len(gold), 100)
        self.assertEqual(gold[0]["status"], "awaiting_human_review")
        case_gold = json.loads(
            (OUTPUT_DIR / "production_case_human_gold_v1_blank.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(case_gold["status"], "awaiting_human_review")
        self.assertEqual(len(case_gold["cases"]), 5)

    def test_ocr_and_prediction_zero(self):
        self.assertEqual(self.report["ocr_calls"], 0)
        calls = self.report["prediction_calls"]
        self.assertEqual(calls["knowledge_v1_inference"], 0)
        self.assertEqual(calls["transaction_ai"], 0)
        self.assertEqual(calls["case_ai"], 0)
        self.assertEqual(calls["local_evidence"], 0)
        self.assertEqual(calls["relation"], 0)
        self.assertEqual(calls["routing"], 0)
        tool_source = (
            REPO_ROOT / "tools" / "knowledge" / "gate_f3a_1_resume.py"
        ).read_text(encoding="utf-8")
        for token in ("paddleocr", "tesseract", "pytesseract", "easyocr"):
            self.assertNotIn(token, tool_source.casefold())

    def test_checksums_and_lineage(self):
        checksums = json.loads(
            (OUTPUT_DIR / "holdout_checksums.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(checksums), 10)
        lineage = json.loads(
            (OUTPUT_DIR / "holdout_lineage.json").read_text(encoding="utf-8")
        )
        self.assertTrue(lineage["initial_f3a_construction"])
        self.assertEqual(lineage["final_0808_selection"]["transaction_count"], 100)

    def test_review_standard_frozen(self):
        standard = json.loads(
            (OUTPUT_DIR / "human_gold_review_standard_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(standard["standard_version"], "human_gold_review_standard_v1")
        self.assertIn("business_activity_presence", standard)
        self.assertIn("declared_industry_consistency", standard)

    def test_deterministic_pool_split(self):
        ids = [f"case-{i}" for i in range(14)]
        first = self.tool.split_pools(ids)
        second = self.tool.split_pools(ids)
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), 8)
        self.assertEqual(len(first[1]), 5)
        self.assertEqual(len(first[2]), 1)


@unittest.skipUnless(FREEZE_DIR.is_dir(), "candidate v2 freeze not present")
class CandidateIntegrityResumeTest(unittest.TestCase):
    def test_candidate_v2_unchanged(self):
        import hashlib

        manifest = json.loads(
            (FREEZE_DIR / "production_candidate_v2_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for name, digest in manifest["file_checksums"].items():
            path = REPO_ROOT / name
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual, digest, f"changed: {name}")


if __name__ == "__main__":
    unittest.main()
