"""Case-folder account discovery and one-time role confirmation."""

from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import re
from pathlib import Path

import pdfplumber

from .auto_detect import detect_bank_type
from .evidence import source_file_id
from .models import get_statement_metadata
from .pipeline import extract_transactions
from .wechat import extract_wechat_identity_metadata


MANIFEST_SCHEMA_VERSION = "1.2"
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


def _normalize_masked_account(value: object) -> str | None:
    normalized = re.sub(r"[\s-]+", "", str(value or "")).replace("X", "*").replace("x", "*")
    return normalized if re.fullmatch(r"\d{4}\*{4,}\d{4}", normalized) else None


def _stable_ref(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()[:16]}"


def _wechat_payment_source_record(
    metadata,
    source_file_id_value: str,
) -> dict[str, str] | None:
    raw_fields = metadata.raw_fields
    owner = str(raw_fields.get("identity_owner_name", "")).strip()
    identity_number = str(raw_fields.get("identity_number", "")).strip().upper()
    payment_account_id = str(raw_fields.get("payment_account_id", "")).strip()
    if not (
        metadata.field_confidence.get("identity_owner_name") == 1.0
        and metadata.field_confidence.get("identity_number") == 1.0
        and metadata.field_confidence.get("payment_account_id") == 1.0
        and owner
        and re.fullmatch(r"(?:\d{15}|\d{17}[\dX])", identity_number)
        and payment_account_id
    ):
        return None
    return {
        "payment_account_type": "wechat_account",
        "account_ref": _stable_ref("payment-account", "wechat", identity_number, payment_account_id),
        "identity_owner_name": owner,
        "identity_number": identity_number,
        "payment_account_id": payment_account_id,
        "source_file_id": source_file_id_value,
        "verification_status": "confirmed",
        "ownership_evidence_ref": f"{source_file_id_value}#wechat_proof_header.identity_triplet",
    }


def _scan_case_file(path_text: str) -> dict[str, object]:
    """Read one case PDF without assigning any account role."""
    path = Path(path_text)
    detection = detect_bank_type(str(path))
    file_id = source_file_id(path)
    record: dict[str, object] = {
        "source_file_id": file_id,
        "source_file": path.name,
        "bank_id": detection.bank_id,
        "bank_label": detection.label,
    }
    if not detection.bank_id or detection.bank_id == "generic_pdf":
        record["scan_status"] = "unusable"
        record["reason"] = "unsupported_or_unconfirmed_format"
        return record
    try:
        transactions = extract_transactions(str(path), detection.bank_id)
    except Exception as exc:
        record["scan_status"] = "unusable"
        record["reason"] = "parse_error"
        record["detail"] = str(exc)
        return record

    metadata = get_statement_metadata(transactions)
    account_number = _normalize_full_account(metadata.account_number)
    if not (
        metadata.account_name.strip()
        and account_number is not None
        and metadata.field_confidence.get("account_name") == 1.0
        and metadata.field_confidence.get("account_number") == 1.0
    ):
        masked_account = _normalize_masked_account(metadata.raw_fields.get("masked_account_number"))
        if not (metadata.account_name.strip() and masked_account is not None):
            record["scan_status"] = "unusable"
            record["reason"] = "reliable_header_account_unavailable"
            return record
        record.update({
            "scan_status": "masked_scanned",
            "reason": "masked_header_account_included_with_warning",
            "account_ref": _stable_ref("masked-account", detection.bank_id, masked_account),
            "masked_account_number": masked_account,
            "account_name": metadata.account_name.strip(),
            "ownership_evidence_ref": f"{file_id}#statement_metadata.account_name+masked_account_number",
        })
        return record

    counterparties = {
        normalized
        for transaction in transactions
        if not getattr(transaction, "neutral", False)
        and transaction.transaction_id
        and (transaction.income != 0 or transaction.expense != 0)
        and transaction.field_confidence.get("counterparty_account") == 1.0
        for normalized in [_normalize_full_account(transaction.counterparty_account)]
        if normalized is not None
    }
    record.update(
        {
            "scan_status": "scanned",
            "account_ref": _stable_ref("account", detection.bank_id, account_number),
            "account_number": account_number,
            "account_name": metadata.account_name.strip(),
            "ownership_evidence_ref": f"{file_id}#statement_metadata.account_name+account_number",
            "reliable_counterparty_accounts": sorted(counterparties),
        }
    )
    return record


def _ignored_pdf_reason(path: Path) -> str | None:
    """Return an ignore reason for encrypted or textless PDFs before parsing."""
    try:
        with pdfplumber.open(str(path)) as pdf:
            if not any((page.extract_text() or "").strip() for page in pdf.pages):
                return "image_only_or_no_text_layer_pdf"
    except Exception:
        return "password_protected_or_unreadable_pdf"
    return None


def _scan_case_file_worker(path_text: str, result_queue) -> None:
    try:
        result_queue.put(_scan_case_file(path_text))
    except Exception as exc:  # pragma: no cover - process-level fallback
        result_queue.put({"scan_status": "unusable", "reason": "worker_error", "detail": str(exc)})


def _candidate_manifest(case_folder: Path, files: list[dict[str, object]]) -> dict[str, object]:
    accounts: dict[str, dict[str, object]] = {}
    masked_accounts: dict[str, dict[str, object]] = {}
    for file_record in files:
        if file_record.get("scan_status") == "masked_scanned":
            account_ref = str(file_record["account_ref"])
            account = masked_accounts.setdefault(account_ref, {
                "account_ref": account_ref, "masked_account_number": file_record["masked_account_number"],
                "account_name": file_record["account_name"], "bank_id": file_record["bank_id"],
                "bank_label": file_record["bank_label"], "source_file_ids": [],
                "warning": "账号已掩码，已纳入同案分析来源；不能用于完整账号精确匹配或唯一双边配对。",
            })
            account["source_file_ids"].append(file_record["source_file_id"])
            continue
        if file_record.get("scan_status") != "scanned":
            continue
        account_ref = str(file_record["account_ref"])
        account = accounts.setdefault(
            account_ref,
            {
                "account_ref": account_ref,
                "account_number": file_record["account_number"],
                "account_name": file_record["account_name"],
                "bank_id": file_record["bank_id"],
                "bank_label": file_record["bank_label"],
                "verification_status": "discovered",
                "role": "unconfirmed",
                "ownership_evidence_refs": [],
                "source_file_ids": [],
                "reliable_counterparty_accounts": set(),
            },
        )
        account["ownership_evidence_refs"].append(file_record["ownership_evidence_ref"])
        account["source_file_ids"].append(file_record["source_file_id"])
        account["reliable_counterparty_accounts"].update(file_record["reliable_counterparty_accounts"])

    candidate_pairs: list[dict[str, object]] = []
    ordered_accounts = sorted(accounts.values(), key=lambda item: str(item["account_ref"]))
    for account in ordered_accounts:
        account["reliable_counterparty_accounts"] = sorted(account["reliable_counterparty_accounts"])
        account["verification_status"] = "confirmed"
        account["confirmation_basis"] = "reliable_statement_header"
        account["role"] = "case_account_no_role_inference"
    for index, left in enumerate(ordered_accounts):
        for right in ordered_accounts[index + 1 :]:
            left_covers_right = right["account_number"] in left["reliable_counterparty_accounts"]
            right_covers_left = left["account_number"] in right["reliable_counterparty_accounts"]
            candidate_pairs.append(
                {
                    "account_refs": [left["account_ref"], right["account_ref"]],
                    "v1d_status": "to_run",
                    "reliable_counterparty_coverage": {
                        "left_to_right": left_covers_right,
                        "right_to_left": right_covers_left,
                    },
                }
            )

    reason = ""
    if len(ordered_accounts) < 2:
        reason = "fewer_than_two_reliable_header_accounts"
    elif not any(
        pair["reliable_counterparty_coverage"]["left_to_right"]
        and pair["reliable_counterparty_coverage"]["right_to_left"]
        for pair in candidate_pairs
    ):
        reason = "mutual_reliable_counterparty_accounts_unavailable"
    return {
        "schema_version": "1.2",
        "case_boundary": {
            "root_folder": ".",
            "folder_is_boundary_only": True,
            "files_do_not_imply_same_subject": True,
        },
        "role_confirmation_status": "not_required_reliable_header_accounts_auto_included",
        "v1c_status": "ready_to_run",
        "v1d_status": "ready_to_run" if len(ordered_accounts) >= 2 else "unavailable",
        "candidate_status": "ready_to_run" if ordered_accounts else "unavailable",
        "reason": reason,
        "accounts": ordered_accounts,
        "candidate_accounts": ordered_accounts,
        "candidate_pairs": candidate_pairs,
        "masked_accounts": sorted(masked_accounts.values(), key=lambda item: str(item["account_ref"])),
        "files": files,
    }


def scan_case_account_candidates(
    case_folder: str | Path,
    file_timeout_seconds: float = 30.0,
) -> dict[str, object]:
    """Read-only candidate scan; it never confirms roles or runs v1D."""
    root = Path(case_folder)
    if not root.is_dir():
        raise ValueError(f"案件文件夹不存在: {root}")
    if file_timeout_seconds <= 0:
        raise ValueError("file_timeout_seconds 必须大于 0")

    files: list[dict[str, object]] = []
    context = multiprocessing.get_context("spawn")
    for path in sorted(root.glob("*.pdf"), key=lambda item: str(item).casefold()):
        relative_path = path.name
        ignored_reason = _ignored_pdf_reason(path)
        if ignored_reason is not None:
            files.append(
                {
                    "source_file_id": source_file_id(path),
                    "source_file": path.name,
                    "relative_path": relative_path,
                    "scan_status": "ignored",
                    "reason": ignored_reason,
                }
            )
            continue
        result_queue = context.Queue()
        process = context.Process(target=_scan_case_file_worker, args=(str(path), result_queue))
        process.start()
        process.join(file_timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join()
            record: dict[str, object] = {
                "source_file_id": source_file_id(path),
                "source_file": path.name,
                "relative_path": relative_path,
                "scan_status": "unusable",
                "reason": "file_timeout",
            }
        else:
            try:
                record = result_queue.get(timeout=1)
            except Exception:
                record = {
                    "source_file_id": source_file_id(path),
                    "source_file": path.name,
                    "scan_status": "unusable",
                    "reason": "worker_result_unavailable",
                }
            record["relative_path"] = relative_path
        result_queue.close()
        if record.get("reason") == "unsupported_or_unconfirmed_format":
            record["scan_status"] = "ignored"
            record["reason"] = "non_statement_or_unconfirmed_format"
        files.append(record)
    return _candidate_manifest(root, files)


def discover_case_accounts(case_folder: str | Path) -> dict[str, object]:
    """Discover reliable statement-header accounts without inferring case roles."""
    root = Path(case_folder)
    if not root.is_dir():
        raise ValueError(f"案件文件夹不存在: {root}")

    accounts_by_ref: dict[str, dict[str, object]] = {}
    payment_sources: list[dict[str, str]] = []
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

        if detection.bank_id == "wechat":
            try:
                payment_source = _wechat_payment_source_record(
                    extract_wechat_identity_metadata(str(path)),
                    file_id,
                )
            except Exception as exc:
                file_record["account_discovery_status"] = "payment_identity_unavailable"
                file_record["reason"] = str(exc)
                files.append(file_record)
                continue
            if payment_source is None:
                file_record["account_discovery_status"] = "payment_identity_unavailable"
                file_record["reason"] = "reliable_wechat_identity_triplet_unavailable"
            else:
                file_record["account_discovery_status"] = "payment_identity_confirmed"
                file_record["payment_account_ref"] = payment_source["account_ref"]
                payment_sources.append(payment_source)
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
        "payment_sources": payment_sources,
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
    """Build confirmed bank-account and WeChat-payment-source context."""
    confirmed_accounts: list[dict[str, str]] = []
    reliable_header_bank_accounts: list[dict[str, str]] = []
    confirmed_payment_sources: list[dict[str, str]] = []
    payment_sources = manifest.get("payment_sources", [])
    if isinstance(payment_sources, list):
        for source in payment_sources:
            if not isinstance(source, dict) or source.get("verification_status") != "confirmed":
                continue
            required = (
                "payment_account_type",
                "account_ref",
                "identity_owner_name",
                "identity_number",
                "payment_account_id",
                "source_file_id",
                "ownership_evidence_ref",
            )
            if source.get("payment_account_type") != "wechat_account" or any(
                not str(source.get(field, "")).strip() for field in required
            ):
                continue
            identity_number = str(source["identity_number"]).strip().upper()
            if not re.fullmatch(r"(?:\d{15}|\d{17}[\dX])", identity_number):
                continue
            confirmed_payment_sources.append(
                {
                    field: identity_number if field == "identity_number" else str(source[field]).strip()
                    for field in required
                }
                | {"verification_status": "confirmed"}
            )
    accounts = manifest.get("accounts", [])
    if not isinstance(accounts, list):
        return {
            "confirmed_owned_accounts": confirmed_accounts,
            "reliable_header_bank_accounts": reliable_header_bank_accounts,
            "confirmed_owned_payment_sources": confirmed_payment_sources,
            "masked_case_accounts": manifest.get("masked_accounts", []),
        }

    for account in accounts:
        if not isinstance(account, dict):
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
        account_record = {
            "account_ref": account_ref,
            "account_number": normalized_account,
            "ownership_evidence_ref": evidence_ref,
            "source_file_ids": [
                str(source_file_id).strip()
                for source_file_id in source_file_ids
                if str(source_file_id).strip()
            ],
        }
        reliable_header_bank_accounts.append(account_record)
        if account.get("verification_status") == "confirmed":
            confirmed_accounts.append({**account_record, "verification_status": "confirmed"})
    return {
        "confirmed_owned_accounts": confirmed_accounts,
        "reliable_header_bank_accounts": reliable_header_bank_accounts,
        "confirmed_owned_payment_sources": confirmed_payment_sources,
        "masked_case_accounts": manifest.get("masked_accounts", []),
    }


def write_case_manifest(manifest: dict[str, object], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
