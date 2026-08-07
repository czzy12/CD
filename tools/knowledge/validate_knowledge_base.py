"""Validate the canonical knowledge base and exit non-zero on errors."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge import validate_knowledge_base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    args = parser.parse_args()
    report = validate_knowledge_base(args.canonical_dir)
    print(f"ok={str(report.ok).lower()}")
    print(f"errors={len(report.errors)}")
    for error in report.errors:
        print(f"error={error}")
    print(f"warnings={len(report.warnings)}")
    for warning in report.warnings:
        print(f"warning={warning}")
    print("counts=" + ",".join(
        f"{key}={value}" for key, value in sorted(report.counts.items())
    ))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
