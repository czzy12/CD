import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from bankflow_v2.auto_detect import Detection
from bankflow_v2.case_accounts import (
    _candidate_manifest,
    confirm_case_roles,
    discover_case_accounts,
    verification_context_from_manifest,
)
from bankflow_v2.models import StatementMetadata, Transaction, TransactionList


def _transactions(name: str, account: str) -> TransactionList:
    return TransactionList(
        [
            Transaction(
                transaction_time=datetime(2026, 1, 1),
                income=Decimal("1.00"),
            )
        ],
        metadata=StatementMetadata(
            account_name=name,
            account_number=account,
            field_confidence={"account_name": 1.0, "account_number": 1.0},
        ),
    )


class CaseAccountTests(unittest.TestCase):
    def test_candidate_scan_auto_includes_reliable_header_accounts_and_attempts_v1d(self):
        files = [
            {
                "scan_status": "scanned",
                "source_file_id": "file-a",
                "account_ref": "account:a",
                "account_number": "6222000000000001",
                "account_name": "甲",
                "bank_id": "ccb",
                "bank_label": "建设银行个人",
                "ownership_evidence_ref": "file-a#header",
                "reliable_counterparty_accounts": ["6222000000000002"],
            },
            {
                "scan_status": "scanned",
                "source_file_id": "file-b",
                "account_ref": "account:b",
                "account_number": "6222000000000002",
                "account_name": "乙",
                "bank_id": "abc_corp",
                "bank_label": "农业银行对公",
                "ownership_evidence_ref": "file-b#header",
                "reliable_counterparty_accounts": ["6222000000000001"],
            },
            {"scan_status": "unusable", "source_file_id": "file-c", "reason": "file_timeout"},
        ]

        manifest = _candidate_manifest(Path("case"), files)

        self.assertEqual(manifest["candidate_status"], "ready_to_run")
        self.assertEqual(manifest["role_confirmation_status"], "not_required_reliable_header_accounts_auto_included")
        self.assertEqual(manifest["v1d_status"], "ready_to_run")
        self.assertEqual(manifest["candidate_pairs"], [{"account_refs": ["account:a", "account:b"], "v1d_status": "to_run", "reliable_counterparty_coverage": {"left_to_right": True, "right_to_left": True}}])
        self.assertTrue(all(account["verification_status"] == "confirmed" for account in manifest["accounts"]))
        self.assertEqual(manifest["files"][2]["reason"], "file_timeout")

    def test_candidate_scan_attempts_v1d_with_one_sided_counterparty_coverage(self):
        files = [
            {
                "scan_status": "scanned", "source_file_id": "file-a", "account_ref": "account:a",
                "account_number": "6222000000000001", "account_name": "甲", "bank_id": "ccb",
                "bank_label": "建设银行个人", "ownership_evidence_ref": "file-a#header",
                "reliable_counterparty_accounts": ["6222000000000002"],
            },
            {
                "scan_status": "scanned", "source_file_id": "file-b", "account_ref": "account:b",
                "account_number": "6222000000000002", "account_name": "乙", "bank_id": "abc_corp",
                "bank_label": "农业银行对公", "ownership_evidence_ref": "file-b#header",
                "reliable_counterparty_accounts": [],
            },
        ]

        manifest = _candidate_manifest(Path("case"), files)

        self.assertEqual(manifest["candidate_status"], "ready_to_run")
        self.assertEqual(manifest["reason"], "mutual_reliable_counterparty_accounts_unavailable")
        self.assertEqual(len(manifest["candidate_accounts"]), 2)
        self.assertEqual(manifest["candidate_pairs"][0]["reliable_counterparty_coverage"], {"left_to_right": True, "right_to_left": False})
    def test_discovers_header_accounts_and_requires_role_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_folder = Path(temp_dir)
            (case_folder / "company.pdf").write_bytes(b"company")
            (case_folder / "personal.pdf").write_bytes(b"personal")

            def detection(path: str) -> Detection:
                return (
                    Detection("abc_corp", "农业银行对公", 98, "test")
                    if path.endswith("company.pdf")
                    else Detection("ccb", "建设银行个人", 98, "test")
                )

            def parsed(path: str, bank_id: str) -> TransactionList:
                return (
                    _transactions("新疆国物能源产业发展有限公司", "30-002401040009217")
                    if bank_id == "abc_corp"
                    else _transactions("韩鹏飞", "6217000480002792404")
                )

            with (
                patch("bankflow_v2.case_accounts.detect_bank_type", side_effect=detection),
                patch("bankflow_v2.case_accounts.extract_transactions", side_effect=parsed),
            ):
                discovery = discover_case_accounts(case_folder)

        self.assertTrue(discovery["case_boundary"]["folder_is_boundary_only"])
        self.assertTrue(discovery["case_boundary"]["files_do_not_imply_same_subject"])
        self.assertEqual(discovery["role_confirmation_status"], "required")
        self.assertEqual(discovery["subjects"], [])
        self.assertEqual(len(discovery["accounts"]), 2)
        self.assertTrue(
            all(account["verification_status"] == "discovered" for account in discovery["accounts"])
        )

        roles = {
            account["account_ref"]: (
                "client_company" if account["bank_id"] == "abc_corp" else "primary_borrower"
            )
            for account in discovery["accounts"]
        }
        manifest = confirm_case_roles(discovery, roles)
        context = verification_context_from_manifest(manifest)

        self.assertEqual(manifest["role_confirmation_status"], "confirmed")
        self.assertEqual(
            {subject["role"] for subject in manifest["subjects"]},
            {"primary_borrower", "client_company"},
        )
        self.assertEqual(len(context["confirmed_owned_accounts"]), 2)
        self.assertEqual(
            {account["account_number"] for account in context["confirmed_owned_accounts"]},
            {"30002401040009217", "6217000480002792404"},
        )
        self.assertTrue(
            all(
                len(account["source_file_ids"]) == 1
                and account["source_file_ids"][0].startswith("sha256:")
                for account in context["confirmed_owned_accounts"]
            )
        )

    def test_does_not_discover_generic_or_unreliable_header_accounts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_folder = Path(temp_dir)
            (case_folder / "generic.pdf").write_bytes(b"generic")
            with patch(
                "bankflow_v2.case_accounts.detect_bank_type",
                return_value=Detection("generic_pdf", "通用 PDF", 92, "test"),
            ):
                discovery = discover_case_accounts(case_folder)

        self.assertEqual(discovery["accounts"], [])
        self.assertEqual(
            discovery["files"][0]["account_discovery_status"],
            "unsupported_or_unconfirmed",
        )

    def test_exports_confirmed_wechat_payment_source_to_verification_context(self):
        context = verification_context_from_manifest(
            {
                "accounts": [],
                "payment_sources": [
                    {
                        "payment_account_type": "wechat_account",
                        "account_ref": "payment:wechat-client",
                        "identity_owner_name": "张三",
                        "identity_number": "110101199001011234",
                        "payment_account_id": "zhangsan_01",
                        "source_file_id": "sha256:wechat",
                        "verification_status": "confirmed",
                        "ownership_evidence_ref": "sha256:wechat#wechat_proof_header.identity_triplet",
                    }
                ],
            }
        )

        self.assertEqual(context["confirmed_owned_accounts"], [])
        self.assertEqual(
            context["confirmed_owned_payment_sources"],
            [
                {
                    "payment_account_type": "wechat_account",
                    "account_ref": "payment:wechat-client",
                    "identity_owner_name": "张三",
                    "identity_number": "110101199001011234",
                    "payment_account_id": "zhangsan_01",
                    "source_file_id": "sha256:wechat",
                    "ownership_evidence_ref": "sha256:wechat#wechat_proof_header.identity_triplet",
                    "verification_status": "confirmed",
                }
            ],
        )

    def test_discovers_wechat_identity_without_parsing_transaction_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_folder = Path(temp_dir)
            (case_folder / "wechat.pdf").write_bytes(b"wechat")
            metadata = StatementMetadata(
                account_name="张三",
                raw_fields={
                    "payment_account_type": "wechat_account",
                    "identity_owner_name": "张三",
                    "identity_number": "110101199001011234",
                    "payment_account_id": "zhangsan_01",
                },
                field_confidence={
                    "identity_owner_name": 1.0,
                    "identity_number": 1.0,
                    "payment_account_id": 1.0,
                },
            )
            with (
                patch(
                    "bankflow_v2.case_accounts.detect_bank_type",
                    return_value=Detection("wechat", "微信流水", 98, "test"),
                ),
                patch(
                    "bankflow_v2.case_accounts.extract_wechat_identity_metadata",
                    return_value=metadata,
                ),
                patch("bankflow_v2.case_accounts.extract_transactions") as extract_transactions,
            ):
                discovery = discover_case_accounts(case_folder)

        self.assertEqual(discovery["accounts"], [])
        self.assertEqual(discovery["files"][0]["account_discovery_status"], "payment_identity_confirmed")
        self.assertEqual(len(discovery["payment_sources"]), 1)
        self.assertEqual(
            discovery["payment_sources"][0]["payment_account_id"],
            "zhangsan_01",
        )
        extract_transactions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
