"""Stable source and transaction identities for traceable verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import Transaction


def source_file_id(source_path: str | Path) -> str:
    """Return a content-based identifier that is independent of the file path."""
    digest = hashlib.sha256()
    with Path(source_path).open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _transaction_payload(transaction: Transaction) -> dict[str, object]:
    return {
        "bank": transaction.bank,
        "page_no": transaction.page_no,
        "row_no": transaction.row_no,
        "source_sequence": transaction.source_sequence,
        "raw_time": transaction.raw_time,
        "raw_amount": transaction.raw_amount,
        "raw_balance": transaction.raw_balance,
        "raw_text": transaction.raw_text,
        "raw_headers": transaction.raw_headers,
        "raw_fields": transaction.raw_fields,
        "source_fields": transaction.source_fields,
    }


def attach_source_evidence(
    transactions: list[Transaction], source_path: str | Path
) -> list[Transaction]:
    """Attach stable IDs and page/row locators without changing parsed values."""
    path = Path(source_path)
    file_id = source_file_id(path)
    for transaction in transactions:
        payload = json.dumps(
            _transaction_payload(transaction),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        transaction.source_file = path.name
        transaction.source_file_id = file_id
        transaction.evidence_locator = f"page={transaction.page_no};row={transaction.row_no}"
        transaction.transaction_id = (
            f"tx:{file_id.removeprefix('sha256:')[:16]}:{hashlib.sha256(payload).hexdigest()[:16]}"
        )
    return transactions
