"""Deterministic freeze manifest helpers for Gate F0."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_checksums(files: Mapping[str, bytes]) -> dict[str, str]:
    return {name: sha256_hex(data) for name, data in files.items()}


def manifest_checksum(payload: Mapping[str, Any]) -> str:
    return sha256_hex(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
