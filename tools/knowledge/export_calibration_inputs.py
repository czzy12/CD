"""Export the frozen review set concept items as validation-cache input."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge.normalization import semantic_signature_from_fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_set_dir", type=Path)
    parser.add_argument("output_cache_dir", type=Path)
    args = parser.parse_args()
    queue = json.loads(
        (args.review_set_dir / "concept_review_queue.json").read_text(
            encoding="utf-8"
        )
    )
    signatures = args.output_cache_dir / "signatures" / "calibration-d3"
    signatures.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, dict[str, str]] = {}
    for index, item in enumerate(queue):
        fields = dict(item["normalized_safe_semantic_text"])
        signature = semantic_signature_from_fields(fields)
        profile_name = (
            "construction_coal"
            if str(item.get("source", "")) == "unseen-hanpf"
            else "building_material"
        )
        path = signatures / f"sig{index:03d}.json"
        path.write_text(
            json.dumps(
                {
                    "cache_schema_version": 2,
                    "task_type": "business_relevance",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "prompt_version": "business-relevance-mvp-v11",
                    "output_contract_version": "semantic-judgement-v2",
                    "semantic_signature": [
                        [name, value]
                        for name, value in sorted(fields.items())
                    ],
                    "input": {
                        "fields": fields,
                        "classification_constraints": {},
                        "business_context": {"profile_name": profile_name},
                    },
                    "response_item": {
                        "transaction_id": f"cal:{index}",
                        "semantic_judgement": "none",
                        "reason": "calibration-input",
                        "used_fields": [],
                    },
                    "validation_failures": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        mapping[str(item["candidate_id"])] = {
            "signature_hash": signature.signature_id,
            "cache_path": str(path),
            "profile_name": profile_name,
        }
    manifest_path = args.output_cache_dir / "candidate_signature_map.json"
    manifest_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("status=ok")
    print(f"items={len(queue)}")
    print(f"cache_dir={args.output_cache_dir}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
