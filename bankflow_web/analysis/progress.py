"""Progress callback values for framework adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    source_index: int = 0
    source_name: str = ""
