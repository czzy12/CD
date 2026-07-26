import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from bankflow_v2.auto_detect import Detection
from bankflow_v2.case_accounts import (
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


if __name__ == "__main__":
    unittest.main()
