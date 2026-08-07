from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import socket
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from bankflow_web.analysis.cancellation import CancellationToken
from bankflow_web.analysis.progress import ProgressEvent
from bankflow_web.analysis.service import AnalysisCancelled, AnalysisOutcome, AnalysisService, SourceOutcome
from bankflow_web.analysis.source_discovery import CaseDirectoryRegistry
from bankflow_web.analysis.task_manager import AnalysisTaskManager
from bankflow_web.case_session import CaseSession
from bankflow_web.contracts import ApplicationError


def result(transaction_id: str = "tx:new") -> dict[str, object]:
    transaction = Transaction(
        transaction_time=datetime(2026, 1, 1), income=Decimal("1"), expense=Decimal("0"),
        source_file="source.xlsx", source_file_id="sha256:test", transaction_id=transaction_id,
        page_no=1, row_no=1, evidence_locator="page=1;row=1",
    )
    return build_bankflow_result([transaction], ai_config={})


class FakeService:
    def __init__(self, *, block: threading.Event | None = None, fail: bool = False, review: bool = False) -> None:
        self.block = block
        self.fail = fail
        self.review = review
        self.started = threading.Event()
        self.build_called = False

    def run(self, paths, *, cancellation, progress, source_complete, **_kwargs):
        self.started.set()
        progress(ProgressEvent("parsing_source", 0, paths[0].name))
        if self.block is not None:
            while not self.block.wait(0.01):
                if cancellation.requested:
                    raise AnalysisCancelled()
        if self.fail:
            raise RuntimeError("private failure")
        outcome = SourceOutcome(paths[0], "review" if self.review else "included", "需复核" if self.review else "", [], failed=self.review)
        source_complete(outcome)
        if cancellation.requested:
            raise AnalysisCancelled()
        self.build_called = True
        return AnalysisOutcome([outcome], [], result(), 1.25)


def wait_for(manager: AnalysisTaskManager, task_id: str, states: set[str]):
    for _ in range(200):
        value = manager.status(task_id)
        if value.state in states:
            return value
        time.sleep(0.01)
    raise AssertionError("task did not reach expected state")


class SourceDiscoveryTests(unittest.TestCase):
    def test_handle_hides_path_and_preflight_lists_supported_and_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "flow.xlsx").write_bytes(b"fixture")
            (root / "notes.txt").write_text("private", encoding="utf-8")
            registry = CaseDirectoryRegistry()
            selected = registry.register(root)
            selection, preflight = registry.inspect(selected.case_handle)
            encoded = json.dumps(preflight.__dict__, ensure_ascii=False, default=lambda item: item.__dict__)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("private", encoded)
            self.assertEqual(preflight.supported_source_count, 1)
            self.assertEqual(preflight.unsupported_source_count, 1)
            self.assertTrue(preflight.can_start)
            self.assertEqual(selection.sources[0].path.name, "flow.xlsx")

    def test_no_supported_sources_cannot_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.txt").write_text("private", encoding="utf-8")
            registry = CaseDirectoryRegistry()
            selected = registry.register(root)
            _selection, preflight = registry.inspect(selected.case_handle)
            self.assertFalse(preflight.can_start)
            self.assertIn("未找到支持", preflight.warnings[0])

    def test_invalid_handle_is_stable(self):
        with self.assertRaises(ApplicationError) as raised:
            CaseDirectoryRegistry().get("missing")
        self.assertEqual(raised.exception.code, "CASE_HANDLE_INVALID")


class AnalysisTaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.session = CaseSession()
        self.session.load_result_dict(result("tx:old"), case_name="old")

    def promote(self, payload, case_name):
        self.session.load_result_dict(payload, case_name=case_name)
        header = self.session.adapter().case_header()
        return header.case_session_id, header.case_revision, header.transaction_count

    def test_success_progress_and_atomic_replacement(self):
        service = FakeService()
        manager = AnalysisTaskManager(self.promote, service=service)
        old_id = self.session.case_session_id
        started = manager.start("new", [Path("source.xlsx")], {})
        completed = wait_for(manager, started.analysis_task_id, {"completed"})
        self.assertTrue(completed.result_ready)
        self.assertEqual(completed.completed_sources, 1)
        self.assertEqual(completed.success_sources, 1)
        self.assertNotEqual(old_id, completed.case_session_id)
        self.assertEqual(completed.transaction_count, 1)

    def test_duplicate_start_is_rejected(self):
        block = threading.Event()
        service = FakeService(block=block)
        manager = AnalysisTaskManager(self.promote, service=service)
        manager.start("one", [Path("one.xlsx")], {})
        service.started.wait(1)
        with self.assertRaises(ApplicationError) as raised:
            manager.start("two", [Path("two.xlsx")], {})
        self.assertEqual(raised.exception.code, "ANALYSIS_ALREADY_RUNNING")
        block.set()

    def test_cooperative_cancel_does_not_build_or_replace_case(self):
        block = threading.Event()
        service = FakeService(block=block)
        manager = AnalysisTaskManager(self.promote, service=service)
        old_id = self.session.case_session_id
        started = manager.start("new", [Path("source.xlsx")], {})
        service.started.wait(1)
        cancelling = manager.cancel(started.analysis_task_id)
        self.assertEqual(cancelling.state, "cancelling")
        cancelled = wait_for(manager, started.analysis_task_id, {"cancelled"})
        self.assertFalse(cancelled.result_ready)
        self.assertFalse(service.build_called)
        self.assertEqual(old_id, self.session.case_session_id)

    def test_failure_keeps_old_case_and_sanitizes_error(self):
        service = FakeService(fail=True)
        manager = AnalysisTaskManager(self.promote, service=service)
        old_id = self.session.case_session_id
        started = manager.start("new", [Path("source.xlsx")], {})
        failed = wait_for(manager, started.analysis_task_id, {"failed"})
        self.assertEqual(failed.error_code, "ANALYSIS_FAILED")
        self.assertNotIn("private failure", failed.error_message or "")
        self.assertEqual(old_id, self.session.case_session_id)

    def test_review_source_counts_as_review_and_failure_without_changing_schema_status(self):
        manager = AnalysisTaskManager(self.promote, service=FakeService(review=True))
        started = manager.start("new", [Path("source.xlsx")], {})
        completed = wait_for(manager, started.analysis_task_id, {"completed"})
        self.assertEqual(completed.review_sources, 1)
        self.assertEqual(completed.failed_sources, 1)
        self.assertEqual(completed.sources[0].status, "review")

    def test_dismiss_and_stale_task_are_rejected(self):
        manager = AnalysisTaskManager(self.promote, service=FakeService())
        first = manager.start("one", [Path("one.xlsx")], {})
        wait_for(manager, first.analysis_task_id, {"completed"})
        manager.dismiss(first.analysis_task_id)
        with self.assertRaises(ApplicationError):
            manager.status(first.analysis_task_id)


class AnalysisServiceTests(unittest.TestCase):
    def test_ai_defaults_resolve_inside_builder_and_source_failure_remains_review(self):
        service = AnalysisService()
        service.extract_source = lambda _path: (_ for _ in ()).throw(RuntimeError("parse failed"))
        captured = {}

        def fake_build(transactions, **kwargs):
            captured.update(kwargs)
            return result()

        with patch("bankflow_v2.result_export.build_bankflow_result", fake_build):
            outcome = service.run([Path("source.pdf")])
        self.assertIsNone(captured["ai_config"])
        self.assertIsNone(captured["ai_evaluator"])
        self.assertEqual(outcome.source_results[0].status, "review")
        self.assertTrue(outcome.source_results[0].failed)

    def test_task_manager_forwards_ai_runtime_and_network_permission(self):
        captured = {}

        class RecordingService:
            def run(self, paths, *, cancellation, progress, source_complete, **_kwargs):
                captured.update(_kwargs)
                return AnalysisOutcome(
                    [SourceOutcome(paths[0], "included", "", [], failed=False)],
                    [],
                    result(),
                    1.0,
                )

        manager = AnalysisTaskManager(lambda *_args: ("s", 1, 1), service=RecordingService())
        manager.start(
            "case",
            [Path("one.xlsx")],
            {},
            ai_config={"enabled": True},
            ai_evaluator=lambda _payload: {"results": []},
            allow_external_network=True,
        )
        deadline = time.perf_counter() + 5.0
        while manager.has_active_task() and time.perf_counter() < deadline:
            time.sleep(0.01)
        self.assertEqual(captured["ai_config"], {"enabled": True})
        self.assertIsNotNone(captured["ai_evaluator"])
        self.assertTrue(captured["allow_external_network"])

    def test_cancel_before_first_source_never_builds_result(self):
        token = CancellationToken()
        token.request()
        with self.assertRaises(AnalysisCancelled):
            AnalysisService().run([Path("source.xlsx")], cancellation=token)

    def test_external_network_is_blocked_during_analysis(self):
        service = AnalysisService()
        attempted = []

        def extract(_path):
            attempted.append(True)
            socket.create_connection(("example.invalid", 443))

        service.extract_source = extract
        with patch("bankflow_v2.result_export.build_bankflow_result", return_value=result()):
            outcome = service.run([Path("source.xlsx")])
        self.assertTrue(attempted)
        self.assertTrue(outcome.source_results[0].failed)
        self.assertIn("禁用外部网络", outcome.source_results[0].message)


class CaseSessionAnalysisTests(unittest.TestCase):
    def test_load_result_dict_validates_module_and_updates_identity(self):
        session = CaseSession()
        session.load_result_dict(result("tx:old"), case_name="old")
        old_id, old_revision = session.case_session_id, session.revision
        session.load_result_dict(result("tx:new"), case_name="new", origin="analysis")
        self.assertNotEqual(session.case_session_id, old_id)
        self.assertEqual(session.revision, old_revision + 1)
        self.assertEqual(session.origin, "analysis")
        with self.assertRaises(ApplicationError):
            session.adapter().evidence("tx:old")

    def test_invalid_module_does_not_replace_existing_case(self):
        session = CaseSession()
        session.load_result_dict(result(), case_name="old")
        old_id = session.case_session_id
        invalid = result()
        invalid["module"] = "other"
        with self.assertRaises(ApplicationError):
            session.load_result_dict(invalid, case_name="bad")
        self.assertEqual(session.case_session_id, old_id)


if __name__ == "__main__":
    unittest.main()
