"""Print canonical knowledge-base and runtime cache statistics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    RuntimeKnowledgeRepository,
    validate_knowledge_base,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    parser.add_argument("--cache-root", type=Path)
    args = parser.parse_args()
    report = validate_knowledge_base(args.canonical_dir)
    runtime = KnowledgeRuntime.load(args.canonical_dir)
    print("knowledge_version=" + runtime.version.knowledge_version)
    print("taxonomy_version=" + runtime.version.taxonomy_version)
    print("semantic_kb_version=" + runtime.version.semantic_kb_version)
    print("relation_kb_version=" + runtime.version.relation_kb_version)
    print("alias_kb_version=" + runtime.version.alias_kb_version)
    print("resolver_version=" + runtime.version.resolver_version)
    print("canonical_ok=" + str(report.ok).lower())
    for key, value in sorted(report.counts.items()):
        print(f"canonical_{key}={value}")
    if args.cache_root:
        repository = RuntimeKnowledgeRepository(args.cache_root)
        for key, value in sorted(repository.counts().items()):
            print(f"runtime_{key}={value}")
        repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
