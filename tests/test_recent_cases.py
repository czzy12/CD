from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from gui_verification import VerificationWorkspace
from gui_verification_app import (
    MANUAL_CASE_CONTEXT_FILENAME,
    STANDARD_RESULT_FILENAME,
    VerificationMainWindow,
    save_manual_case_context,
)
from recent_cases import RecentCaseStore


def transaction(index: int = 1) -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 7, 28, 9, 30),
        expense=Decimal("10000.00"),
        balance=Decimal("2234.00"),
        source_file="sample.pdf",
        source_file_id="sha256:sample",
        transaction_id=f"tx:recent:{index}",
        page_no=2,
        row_no=index,
        evidence_locator=f"page=2;row={index}",
        counterparty_name="某公司",
        counterparty_account="6222021234567890",
        purpose="购车定金",
        raw_text="某公司 6222021234567890 购车定金",
        raw_fields=["某公司", "6222021234567890", "购车定金"],
        field_confidence={"counterparty_name": 1.0, "purpose": 1.0},
    )


def standard_result() -> dict[str, object]:
    return build_bankflow_result([transaction()], ai_config={})


class RecentCaseStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_completed_case_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecentCaseStore(root / "app" / "recent_cases.json")
            window = VerificationMainWindow(store)
            window.case_dir = root / "case-a"
            window.case_dir.mkdir()

            window.on_finished([], [], standard_result())

            self.assertEqual(len(store.load()), 1)
            self.assertEqual(store.load()[0]["case_name"], "case-a")

    def test_restart_reads_existing_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-a"
            case_dir.mkdir()
            store = RecentCaseStore(root / "recent_cases.json")
            store.upsert({"case_name": "案件A", "schema_version": "1.16"}, case_dir=case_dir)

            restarted = RecentCaseStore(store.path)

            self.assertEqual(restarted.load()[0]["case_name"], "案件A")

    def test_same_case_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / "case-a"
            case_dir.mkdir()
            store = RecentCaseStore(Path(directory) / "recent_cases.json")
            store.upsert({"case_name": "旧名称"}, case_dir=case_dir)
            store.upsert({"case_name": "新名称"}, case_dir=case_dir)

            records = store.load()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["case_name"], "新名称")

    def test_most_recent_case_is_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            store = RecentCaseStore(root / "recent_cases.json")
            store.upsert({"case_name": "较早"}, case_dir=first, updated_at="2026-07-01T08:00:00+08:00")
            store.upsert({"case_name": "最近"}, case_dir=second, updated_at="2026-08-01T08:00:00+08:00")

            self.assertEqual([item["case_name"] for item in store.load()], ["最近", "较早"])

    def test_open_existing_case_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-a"
            case_dir.mkdir()
            (case_dir / STANDARD_RESULT_FILENAME).write_text(
                json.dumps(standard_result(), ensure_ascii=False), encoding="utf-8"
            )
            store = RecentCaseStore(root / "recent_cases.json")
            window = VerificationMainWindow(store)

            opened = window._open_existing_case_path(case_dir)

            self.assertTrue(opened)
            self.assertEqual(len(store.load()), 1)

    def test_import_compatible_result_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "imported.json"
            result_path.write_text(json.dumps(standard_result(), ensure_ascii=False), encoding="utf-8")
            store = RecentCaseStore(root / "recent_cases.json")
            window = VerificationMainWindow(store)

            self.assertTrue(window._load_standard_result_path(result_path))
            self.assertEqual(store.load()[0]["result_path"], os.path.normcase(str(result_path.resolve())))

    def test_incompatible_result_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "invalid.json"
            result_path.write_text('{"schema_version":"1.15"}', encoding="utf-8")
            store = RecentCaseStore(root / "recent_cases.json")
            window = VerificationMainWindow(store)

            with patch("gui_verification_app.QMessageBox.warning"):
                loaded = window._load_standard_result_path(result_path)

            self.assertFalse(loaded)
            self.assertEqual(store.load(), [])

    def test_missing_path_is_marked_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecentCaseStore(Path(directory) / "recent_cases.json")
            store.upsert({"case_name": "失效案件"}, case_dir=Path(directory) / "missing")

            self.assertFalse(store.load()[0]["available"])

    def test_unavailable_record_can_be_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecentCaseStore(root / "recent_cases.json")
            record = store.upsert({"case_name": "失效案件"}, case_dir=root / "missing")
            window = VerificationMainWindow(store)

            window.remove_recent_case(str(record["record_id"]))

            self.assertEqual(store.load(), [])

    def test_corrupt_index_degrades_to_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent_cases.json"
            path.write_text("{not-json", encoding="utf-8")
            store = RecentCaseStore(path)

            self.assertEqual(store.load(), [])
            self.assertTrue(store.last_load_was_corrupt)

    def test_index_contains_no_transaction_or_sensitive_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-a"
            case_dir.mkdir()
            store = RecentCaseStore(root / "recent_cases.json")
            window = VerificationMainWindow(store)
            window.case_dir = case_dir

            window._record_recent_case(standard_result(), "案件A")
            payload = store.path.read_text(encoding="utf-8")

            for forbidden in ("original_transactions", "transaction_id", "counterparty_name", "6222021234567890"):
                self.assertNotIn(forbidden, payload)

    def test_history_open_restores_manual_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-a"
            case_dir.mkdir()
            (case_dir / STANDARD_RESULT_FILENAME).write_text(
                json.dumps(standard_result(), ensure_ascii=False), encoding="utf-8"
            )
            save_manual_case_context(
                case_dir,
                {},
                {"confirmed_primary_business": "环保工程", "confirmation_status": "confirmed"},
            )
            store = RecentCaseStore(root / "recent_cases.json")
            record = store.upsert({"case_name": "案件A"}, case_dir=case_dir)
            window = VerificationMainWindow(store)

            window.open_recent_case(record)

            self.assertEqual(
                window._manual_context["manual_confirmation"]["confirmed_primary_business"],
                "环保工程",
            )
            self.assertTrue((case_dir / MANUAL_CASE_CONTEXT_FILENAME).exists())

    def test_history_open_keeps_evidence_jump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case-a"
            case_dir.mkdir()
            (case_dir / STANDARD_RESULT_FILENAME).write_text(
                json.dumps(standard_result(), ensure_ascii=False), encoding="utf-8"
            )
            store = RecentCaseStore(root / "recent_cases.json")
            record = store.upsert({"case_name": "案件A"}, case_dir=case_dir)
            window = VerificationMainWindow(store)

            window.open_recent_case(record)
            window.workspace.show_evidence("tx:recent:1")

            self.assertEqual(window.workspace.evidence_panel._transaction_ids, ["tx:recent:1"])

    def test_current_case_navigation_is_disabled_before_load(self):
        workspace = VerificationWorkspace()

        self.assertFalse(workspace.navigation_by_route["case"].isEnabled())
        self.assertEqual(workspace.header.title.text(), "尚未加载案件")


if __name__ == "__main__":
    unittest.main()
