from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bankflow_web import case_workspace


class CaseWorkspaceTests(unittest.TestCase):
    def test_load_manual_context_falls_back_to_same_name_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "韩鹏飞"
            case_dir.mkdir()
            legacy_dir = root / "outputs" / "web-gui-12b2" / "workspaces"
            (legacy_dir / "韩鹏飞-aaaa00000000").mkdir(parents=True)
            legacy_file = (
                legacy_dir
                / "韩鹏飞-aaaa00000000"
                / "manual_case_context.json"
            )
            legacy_file.write_text(
                json.dumps(
                    {
                        "case_id": "韩鹏飞",
                        "confirmation_status": "confirmed",
                        "manual_confirmation": {
                            "confirmed_primary_business": "建筑工程，煤炭",
                            "confirmation_status": "confirmed",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(
                case_workspace,
                "web_output_root",
                return_value=root / "outputs" / "web-gui-12b2",
            ):
                loaded = case_workspace.load_manual_case_context(case_dir)
            self.assertEqual(
                loaded.get("confirmation_status"),
                "confirmed",
            )
            self.assertEqual(
                loaded["manual_confirmation"]["confirmed_primary_business"],
                "建筑工程，煤炭",
            )


if __name__ == "__main__":
    unittest.main()
