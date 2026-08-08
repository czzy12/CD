"""Gate F3A.1 tests: manual metadata registry boundaries (no OCR)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f3a-1-holdout-20260808"
)


def _load_tool():
    path = REPO_ROOT / "tools" / "knowledge" / "gate_f3a_1_expand.py"
    spec = importlib.util.spec_from_file_location("gate_f3a_1_expand", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(
    OUTPUT_DIR.is_dir(),
    "F3A.1 registry artifacts not present",
)
class ManualMetadataRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load_tool()
        cls.registry = json.loads(
            (
                OUTPUT_DIR / "manual_external_metadata_registry.json"
            ).read_text(encoding="utf-8")
        )

    def test_registry_entries_have_required_fields(self):
        self.assertGreater(len(self.registry["entries"]), 0)
        required = {
            "anonymized_case_id",
            "source_case_ref",
            "metadata_source_type",
            "source_reference",
            "declared_industry",
            "business_description",
            "human_confirmed",
            "entered_by",
            "entered_at",
            "confirmation_status",
            "transaction_evidence_used_for_metadata",
        }
        for entry in self.registry["entries"]:
            self.assertTrue(required.issubset(entry))
            self.assertFalse(entry["transaction_evidence_used_for_metadata"])

    def test_all_entries_pending_and_blank(self):
        pending = [
            entry
            for entry in self.registry["entries"]
            if entry.get("metadata_source_type") == "manual_screenshot_review"
        ]
        self.assertGreater(len(pending), 0)
        for entry in pending:
            self.assertFalse(entry["human_confirmed"])
            self.assertEqual(entry["declared_industry"], "")
            self.assertEqual(entry["business_description"], "")

    def test_confirmed_0808_entries_have_provenance(self):
        confirmed = self.tool.load_confirmed_entries(
            OUTPUT_DIR / "manual_external_metadata_registry.json"
        )
        self.assertGreaterEqual(len(confirmed), 14)
        for entry in confirmed:
            self.assertEqual(
                entry["metadata_source_type"],
                "human_collected_case_material",
            )
            self.assertEqual(entry["entered_by"], "human_user")
            self.assertFalse(entry["transaction_evidence_used_for_metadata"])
            self.assertTrue(entry["declared_industry"])

    def test_screenshot_candidates_found(self):
        candidates = self.tool.find_screenshot_candidates()
        self.assertGreater(len(candidates), 0)

    def test_ocr_not_used(self):
        tool_source = (
            REPO_ROOT
            / "tools"
            / "knowledge"
            / "gate_f3a_1_expand.py"
        ).read_text(encoding="utf-8")
        for token in ("paddleocr", "tesseract", "pytesseract", "easyocr"):
            self.assertNotIn(token, tool_source.casefold())


if __name__ == "__main__":
    unittest.main()
