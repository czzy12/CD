"""Rebuild/validate the canonical industry taxonomy (offline maintenance)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge import IndustryTaxonomy, validate_knowledge_base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    path = args.canonical_dir / "taxonomy.json"
    taxonomy = IndustryTaxonomy.load(path)
    report = validate_knowledge_base(args.canonical_dir)
    print(f"taxonomy_version={taxonomy.version}")
    print(f"source={taxonomy.source}")
    print(f"nodes={len(taxonomy._nodes)}")
    print(f"valid={str(report.ok).lower()}")
    if not report.ok:
        for error in report.errors:
            print(f"error={error}")
        return 1
    if args.write:
        path.write_text(
            json.dumps(taxonomy.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"written={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
