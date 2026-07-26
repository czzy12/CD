"""Case-folder account discovery and one-time role confirmation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .auto_detect import detect_bank_type
from .evidence import source_file_id
from .models import get_statement_metadata
from .pipeline import extract_transactions


MANIFEST_SCHEMA_VERSION = "1.1"
CONFIRMABLE_ROLES = {
    "primary_borrower",
    "co_borrower",
    "client_company",
    "other",
}


def _normalize_full_account(value: object) -> str | None:
    normalized = re.sub(r"[\s-]+", "", str(value or ""))
    if not normalized.isdigit() or not 12 <= len(normalized) <= 32:
        return None
    return normalized


def _stable_ref(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()[:16]}"


def discover_case_accounts(case_folder: str | Path) -> dict[str, object]:
    """Discover reliable statement-header accounts without inferring case roles."""
    root = Path(case_folder)
    if not root.is_dir():
        raise ValueError(f"案件文件夹不存在: {root}")

    accounts_by_ref: dict[str, dict[str, object]] = {}
    files: list[dict[str, object]] = []
    pdf_paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".pdf"
    ]
    for path in sorted(pdf_paths, key=lambda item: str(item).casefold()):
        relative_path = path.relative_to(root).as_posix()
        file_id = source_file_id(path)
        detection = detect_bank_type(str(path))
        file_record: dict[str, object] = {
            "source_file_id": file_id,
            "source_file": path.name,
            "relative_path": relative_path,
            "bank_id": detection.bank_id,
            "bank_label": detection.label,
        }
        if not detection.bank_id or detection.bank_id == "generic_pdf":
            file_record["account_discovery_status"] = "unsupported_or_unconfirmed"
            files.append(file_record)
            continue

        try:
            transactions = extract_transactions(str(path), detection.bank_id)
            metadata = get_statement_metadata(transactions)
        except Exception as exc:
            file_record["account_discovery_status"] = "parse_error"
            file_record["reason"] = str(exc)
            files.append(file_record)
            continue

        normalized_account = _normalize_full_account(metadata.account_number)
        reliable = (
            bool(metadata.account_name.strip())
            and normalized_account is not None
            and metadata.field_confidence.get("account_name") == 1.0
            and metadata.field_confidence.get("account_number") == 1.0
        )
        if not reliable:
            file_record["account_discovery_status"] = "reliable_header_account_unavailable"
            files.append(file_record)
            continue

        account_ref = _stable_ref("account", detection.bank_id, normalized_account)
        evidence_ref = f"{file_id}#statement_metadata.account_name+account_number"
        account = accounts_by_ref.setdefault(
            account_ref,
            {
                "account_ref": account_ref,
                "account_number": normalized_account,
                "account_name": metadata.account_name.strip(),
                "bank_id": detection.bank_id,
                "bank_label": detection.label,
                "verification_status": "discovered",
                "role": "unconfirmed",
                "ownership_evidence_refs": [],
                "source_file_ids": [],
            },
        )
        if evidence_ref not in account["ownership_evidence_refs"]:
            account["ownership_evidence_refs"].append(evidence_ref)
        if file_id not in account["source_file_ids"]:
            account["source_file_ids"].append(file_id)
        file_record["account_discovery_status"] = "discovered"
        file_record["account_ref"] = account_ref
        files.append(file_record)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "case_boundary": {
            "root_folder": ".",
            "folder_is_boundary_only": True,
            "files_do_not_imply_same_subject": True,
        },
        "role_confirmation_status": "required",
        "subjects": [],
        "accounts": list(accounts_by_ref.values()),
        "files": files,
    }


def confirm_case_roles(
    discovery: dict[str, object],
    role_by_account_ref: dict[str, str],
) -> dict[str, object]:
    """Confirm a role for selected discovered accounts without re-entering numbers."""
    manifest = copy.deepcopy(discovery)
    accounts = manifest.get("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("accounts 必须为列表")

    known_refs = {
        str(account.get("account_ref", ""))
        for account in accounts
        if isinstance(account, dict)
    }
    unknown_refs = set(role_by_account_ref) - known_refs
    if unknown_refs:
        raise ValueError(f"未知 account_ref: {sorted(unknown_refs)}")
    invalid_roles = set(role_by_account_ref.values()) - CONFIRMABLE_ROLES
    if invalid_roles:
        raise ValueError(f"不支持的角色: {sorted(invalid_roles)}")

    subjects_by_ref: dict[str, dict[str, str]] = {}
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_ref = str(account.get("account_ref", ""))
        role = role_by_account_ref.get(account_ref)
        if role is None:
            continue
        account_name = str(account.get("account_name", "")).strip()
        subject_ref = _stable_ref("subject", role, account_name)
        account["role"] = role
        account["subject_ref"] = subject_ref
        account["verification_status"] = "confirmed"
        subjects_by_ref.setdefault(
            subject_ref,
            {
                "subject_ref": subject_ref,
                "display_name": account_name,
                "role": role,
                "verification_status": "confirmed",
            },
        )

    manifest["subjects"] = list(subjects_by_ref.values())
    manifest["role_confirmation_status"] = (
        "confirmed"
        if accounts
        and all(
            isinstance(account, dict)
            and account.get("verification_status") == "confirmed"
            for account in accounts
        )
        else "partial"
    )
    return manifest


def verification_context_from_manifest(manifest: dict[str, object]) -> dict[str, object]:
    """Build the v1C context from confirmed manifest accounts."""
    confirmed_accounts: list[dict[str, str]] = []
    accounts = manifest.get("accounts", [])
    if not isinstance(accounts, list):
        return {"confirmed_owned_accounts": confirmed_accounts}

    for account in accounts:
        if not isinstance(account, dict) or account.get("verification_status") != "confirmed":
            continue
        evidence_refs = account.get("ownership_evidence_refs", [])
        evidence_ref = (
            str(evidence_refs[0]).strip()
            if isinstance(evidence_refs, list) and evidence_refs
            else ""
        )
        normalized_account = _normalize_full_account(account.get("account_number"))
        account_ref = str(account.get("account_ref", "")).strip()
        if not account_ref or not evidence_ref or normalized_account is None:
            continue
        source_file_ids = account.get("source_file_ids", [])
        if not isinstance(source_file_ids, list):
            source_file_ids = []
        confirmed_accounts.append(
            {
                "account_ref": account_ref,
                "account_number": normalized_account,
                "verification_status": "confirmed",
                "ownership_evidence_ref": evidence_ref,
                "source_file_ids": [
                    str(source_file_id).strip()
                    for source_file_id in source_file_ids
                    if str(source_file_id).strip()
                ],
            }
        )
    return {"confirmed_owned_accounts": confirmed_accounts}


def write_case_manifest(manifest: dict[str, object], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
