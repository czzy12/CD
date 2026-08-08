"""Gate F2 tests: production-candidate-v2 manifest integrity and lifecycle."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from bankflow_v2.knowledge.freeze import manifest_checksum


REPO_ROOT = Path(__file__).resolve().parents[1]
FREEZE_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/production-candidate-v2-freeze-20260808"
)
V1_FREEZE_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/production-candidate-freeze-20260808"
)
CONCEPT_HOLDOUT_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f1-1-holdout-fitness-20260808"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(FREEZE_DIR.is_dir(), "v2 freeze manifest not present")
class ProductionCandidateV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(
            (FREEZE_DIR / "production_candidate_v2_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        cls.checksums = json.loads(
            (FREEZE_DIR / "production_candidate_v2_checksums.json").read_text(
                encoding="utf-8"
            )
        )

    def test_manifest_checksum_matches_files(self):
        payload = {
            key: value
            for key, value in self.manifest.items()
            if key != "manifest_checksum"
        }
        self.assertEqual(
            manifest_checksum(payload),
            self.manifest["manifest_checksum"],
        )
        self.assertEqual(
            self.checksums["manifest_checksum"],
            self.manifest["manifest_checksum"],
        )

    def test_all_prediction_files_match_sha256(self):
        for name, digest in self.manifest["file_checksums"].items():
            path = REPO_ROOT / name
            self.assertTrue(path.is_file(), f"missing prediction file: {name}")
            self.assertEqual(_sha256(path), digest, f"file changed: {name}")

    def test_no_secrets_in_manifest(self):
        serialized = json.dumps(self.manifest, ensure_ascii=False).casefold()
        for token in (
            "api_key_encrypted",
            "authorization: bearer",
            "dpapi",
        ):
            self.assertNotIn(token, serialized)
        runtime = self.manifest["ai_runtime_config"]
        self.assertFalse(runtime["api_key_in_manifest"])
        self.assertFalse(runtime["secrets_in_manifest"])

    def test_candidate_is_not_promotion(self):
        production = self.manifest["production_mode"]
        self.assertEqual(production["production_resolver"], "legacy_v11")
        self.assertEqual(production["knowledge_v1"], "shadow")
        self.assertFalse(production["candidate_equals_promotion"])

    def test_concept_holdout_retained(self):
        concept = self.manifest["concept_holdout_retention"][
            "production_concept_holdout_v1"
        ]
        self.assertTrue(concept["retained"])
        self.assertEqual(concept["contamination"], 0)
        self.assertTrue(concept["concept_path_compatible"])

    def test_diagnostic_artifacts_isolated(self):
        isolation = self.manifest["diagnostic_artifact_isolation"]
        self.assertTrue(isolation["case_specific_diagnostic_dependency"])
        self.assertEqual(isolation["findings"], [])
        for name in self.manifest["prediction_affecting_files_v2"]:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("D:/Investigator PDF/outputs", text)
            self.assertNotIn("hanpeipei", text)

    def test_pending_not_promoted(self):
        pending = self.manifest["pending_knowledge_state"]
        self.assertFalse(pending["promotion_triggered_by_freeze"])
        self.assertEqual(
            pending["f1_3_1_live_transaction_ai_candidates"]["status"],
            "pending",
        )

    def test_baseline_exists(self):
        baseline = json.loads(
            (FREEZE_DIR / "development_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(baseline["baseline_checksum"])
        self.assertGreater(len(baseline["concept"]), 0)
        self.assertGreater(len(baseline["relation"]), 0)
        self.assertGreater(len(baseline["business_evidence_local"]), 0)
        self.assertIn("case_evidence_pack", baseline)


@unittest.skipUnless(V1_FREEZE_DIR.is_dir(), "v1 freeze manifest not present")
class HistoricalCandidateV1Test(unittest.TestCase):
    def test_v1_historical_freeze_unchanged(self):
        checksums = json.loads(
            (V1_FREEZE_DIR / "production_candidate_checksums.json").read_text(
                encoding="utf-8"
            )
        )
        for name, digest in checksums["file_checksums"].items():
            path = REPO_ROOT / name
            self.assertTrue(path.is_file(), f"missing v1 file: {name}")
            self.assertEqual(_sha256(path), digest, f"v1 file changed: {name}")


@unittest.skipUnless(
    CONCEPT_HOLDOUT_DIR.is_dir(),
    "concept holdout artifacts not present",
)
class ConceptHoldoutIntegrityTest(unittest.TestCase):
    def test_concept_holdout_checksum_unchanged(self):
        manifest = json.loads(
            (CONCEPT_HOLDOUT_DIR / "final_holdout_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        checksum = manifest["concept_holdout"]["checksum"]
        self.assertEqual(len(checksum), 64)
        self.assertEqual(
            checksum,
            "31c51ec32ab42e93e8159a28294638ae100e96e943e60307b8bdbc593763caaa",
        )


if __name__ == "__main__":
    unittest.main()
