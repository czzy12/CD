"""Migrate a schema 1.16 standard result to 1.17 without fabricating history."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.result_export import migrate_schema_116_to_117


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    if not args.input_path.is_file():
        print("status=not_started")
        print("reason=input_not_found")
        return 2
    payload = json.loads(args.input_path.read_text(encoding="utf-8"))
    try:
        migrated = migrate_schema_116_to_117(payload)
    except ValueError as exc:
        print("status=not_started")
        print(f"reason={exc}")
        return 2
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("status=ok")
    print(f"schema_version={migrated['schema_version']}")
    print(f"output={args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
