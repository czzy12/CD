"""Gate F1.2 integration invariants (shadow only, frozen candidate intact)."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FREEZE_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/production-candidate-freeze-20260808"
)
GATE_F1_1_DIR = Path(
    "D:/Investigator PDF/outputs/knowledge-v1/gate-f1-1-holdout-fitness-20260808"
)
RELATION_HOLDOUT_DIR = GATE_F1_1_DIR / "relation-holdout"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(FREEZE_DIR.is_dir(), "production freeze manifest not present")
class FrozenCandidateTest(unittest.TestCase):
    def test_frozen_prediction_files_unchanged(self):
        checksums = json.loads(
            (FREEZE_DIR / "production_candidate_checksums.json").read_text(
                encoding="utf-8"
            )
        )
        for name, digest in checksums["file_checksums"].items():
            path = REPO_ROOT / name
            self.assertTrue(path.is_file(), f"missing frozen file: {name}")
            self.assertEqual(_sha256(path), digest, f"frozen file changed: {name}")


@unittest.skipUnless(
    RELATION_HOLDOUT_DIR.is_dir(),
    "relation holdout artifacts not present",
)
class HoldoutStatusTest(unittest.TestCase):
    def test_rh30_marked_superseded_before_gold(self):
        status = json.loads(
            (RELATION_HOLDOUT_DIR / "relation_holdout_status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["status"], "superseded_before_gold")
        self.assertEqual(status["human_labels"], 0)
        self.assertEqual(status["system_run"], 0)
        self.assertTrue(status["usable_as_diagnostic"])

    def test_rh30_human_gold_preserved(self):
        gold = json.loads(
            (RELATION_HOLDOUT_DIR / "relation_human_gold.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(gold["status"], "superseded_before_gold")
        self.assertEqual(gold["reviewed"], 0)
        self.assertEqual(gold["pending"], 30)
        self.assertEqual(gold["decisions"], [])


if __name__ == "__main__":
    unittest.main()
