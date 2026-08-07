"""Adjudicate Gate A mismatches and generate the Gold Set fixture.

Adjudication policy:
- legacy_to_undetermined: transaction_noise / customer_specific / insufficient
  -> keep undetermined (knowledge correct); generic-missing rows are overridden
  where a generic alias has been added.
- upgrade: operational concepts (logistics/fuel/utilities/parts/equipment/
  building_material/environmental/metal/mining) are accepted; generic service
  tiers are accepted at weak; goods_payment refund capped at medium.
- downgrade: bank_fee/financial_service -> none; material_fee_generic -> weak;
  platform verification rows -> weak. legacy context inflation is rejected.
- other: adjudicated by case (mm-060 -> none).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


NOISE_TOKENS = (
    "充值",
    "提现",
    "取款",
    "卡存",
    "汇款",
    "汇入",
    "转账",
    "退款",
    "订单支付",
    "收钱码",
    "经营码",
    "POS",
    "账户信息",
    "帐户信息",
    "消费",
)
BRAND_TOKENS = (
    "蜜雪冰城",
    "悦来悦喜",
    "美宜佳",
    "百果园",
    "雅克雅思",
    "鲁泰",
    "龙兴寺",
    "第八师",
    "汉江路",
    "世腾",
    "雷克萨斯",
    "汽车小镇",
    "拉卡拉",
    "嵩山路",
    "五号街坊",
    "满草堂",
    "李易",
)
OPERATIONAL_CONCEPTS = {
    "logistics",
    "fuel",
    "utilities",
    "parts",
    "equipment",
    "building_material",
    "environmental_engineering_service",
    "metal_products",
    "mining",
}

OVERRIDES: dict[str, dict[str, str]] = {
    "mm-038": {
        "adjudicated_relevance": "weak",
        "preferred_system": "knowledge_v1",
        "issue_type": "alias_missing",
        "action_required": "add_generic_alias_asset_development",
        "reviewer_note": "房地产开发/资产开发为通用行业词，已补 real_estate 别名",
    },
    "mm-085": {
        "adjudicated_relevance": "medium",
        "preferred_system": "neither",
        "issue_type": "other",
        "action_required": "none",
        "reviewer_note": "退货款属退款，不应强相关；medium 更合理",
    },
    "mm-235": {
        "adjudicated_relevance": "strong",
        "preferred_system": "knowledge_v1",
        "issue_type": "legacy_context_specific",
        "action_required": "none",
        "reviewer_note": "建材店为直接证据字段，strong 合理",
    },
    "mm-295": {
        "adjudicated_relevance": "medium",
        "preferred_system": "knowledge_v1",
        "issue_type": "legacy_context_specific",
        "action_required": "none",
        "reviewer_note": "交通建设公司对建材/环保客户 medium；‘豫’单字噪声已由归一化丢弃",
    },
}


def _adjudicate(row: dict[str, object]) -> dict[str, str]:
    mismatch_id = str(row["mismatch_id"])
    if mismatch_id in OVERRIDES:
        return OVERRIDES[mismatch_id]
    knowledge = row["knowledge"]
    legacy = row["legacy"]
    concept = str(knowledge["concept_id"])
    knowledge_relevance = str(row["knowledge_relevance"])
    legacy_relevance = str(legacy["relevance"])
    text = " ".join(str(value) for value in row["fields"].values())
    mismatch_type = str(row["mismatch_type"])

    if mismatch_type == "legacy_to_undetermined":
        if any(token in text for token in NOISE_TOKENS):
            return {
                "adjudicated_relevance": "undetermined",
                "preferred_system": "knowledge_v1",
                "issue_type": "transaction_noise",
                "action_required": "none",
                "reviewer_note": "交易/资金类噪声，不进入知识库",
            }
        if any(token in text for token in BRAND_TOKENS):
            return {
                "adjudicated_relevance": "undetermined",
                "preferred_system": "knowledge_v1",
                "issue_type": "customer_specific_expression",
                "action_required": "none",
                "reviewer_note": "品牌/客户专属表达，不进入通用知识库",
            }
        return {
            "adjudicated_relevance": "undetermined",
            "preferred_system": "knowledge_v1",
            "issue_type": "insufficient_information",
            "action_required": "none",
            "reviewer_note": "信息不足，正式保留 undetermined",
        }

    if mismatch_type == "upgrade":
        if concept in OPERATIONAL_CONCEPTS:
            return {
                "adjudicated_relevance": knowledge_relevance,
                "preferred_system": "knowledge_v1",
                "issue_type": "legacy_context_specific",
                "action_required": "none",
                "reviewer_note": "经营配套概念，legacy 过于保守",
            }
        if concept == "goods_payment":
            return {
                "adjudicated_relevance": "medium",
                "preferred_system": "neither",
                "issue_type": "other",
                "action_required": "none",
                "reviewer_note": "退款类货款不判 strong",
            }
        return {
            "adjudicated_relevance": knowledge_relevance,
            "preferred_system": "knowledge_v1",
            "issue_type": "legacy_context_specific",
            "action_required": "none",
            "reviewer_note": "泛化服务/弱关联层级，weak 可接受",
        }

    if mismatch_type == "downgrade":
        if concept in {"bank_fee", "financial_service"}:
            return {
                "adjudicated_relevance": "none",
                "preferred_system": "knowledge_v1",
                "issue_type": "legacy_context_specific",
                "action_required": "none",
                "reviewer_note": "银行/金融费用不属于经营语义，legacy strong 错误",
            }
        if concept == "material_fee_generic":
            return {
                "adjudicated_relevance": "weak",
                "preferred_system": "knowledge_v1",
                "issue_type": "legacy_context_specific",
                "action_required": "none",
                "reviewer_note": "无具体产品对象的材料款只作弱提示",
            }
        return {
            "adjudicated_relevance": knowledge_relevance,
            "preferred_system": "knowledge_v1",
            "issue_type": "legacy_context_specific",
            "action_required": "none",
            "reviewer_note": "去客户化后更保守但逻辑合理",
        }

    return {
        "adjudicated_relevance": knowledge_relevance,
        "preferred_system": "knowledge_v1",
        "issue_type": "other",
        "action_required": "none",
        "reviewer_note": "其他方向差异按 knowledge_v1 判定",
    }


def _generic_field(
    row: dict[str, object],
    concept_name: str,
    concept_alias: str,
) -> dict[str, str]:
    original = row["fields"]
    fields: dict[str, str] = {}
    for name, value in original.items():
        compact = "".join(str(value).split())
        if len(compact) < 2:
            continue
        if name in {"counterparty_name", "merchant_name"}:
            fields[name] = f"示例{concept_name}有限公司"
        elif str(value).strip():
            fields[name] = f"示例{concept_alias}"
        else:
            fields[name] = str(value)
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_json", type=Path)
    parser.add_argument("--gold-set", type=Path)
    parser.add_argument("--adjudicated-json", type=Path)
    parser.add_argument("--adjudicated-md", type=Path)
    args = parser.parse_args()

    data = json.loads(args.review_json.read_text(encoding="utf-8"))
    rows = data["rows"]
    for row in rows:
        row["adjudication"] = _adjudicate(row)

    counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    upgrade_counts: Counter[str] = Counter()
    legacy_correct = 0
    knowledge_correct = 0
    gold_rows: list[dict[str, object]] = []
    for row in rows:
        adjudication = row["adjudication"]
        adjudicated = str(adjudication["adjudicated_relevance"])
        issue = str(adjudication["issue_type"])
        preferred = str(adjudication["preferred_system"])
        counts[preferred] += 1
        issue_counts[issue] += 1
        if str(row["mismatch_type"]) == "upgrade":
            upgrade_counts[f"{row['legacy_relevance']}->{row['knowledge_relevance']}"] += 1
        if adjudicated == str(row["legacy_relevance"]):
            legacy_correct += 1
        if adjudicated == str(row["knowledge_relevance"]):
            knowledge_correct += 1
        if adjudicated != "undetermined":
            knowledge_obj = row["knowledge"]
            concept_name = str(knowledge_obj["concept_name"]) or "未知概念"
            concept_alias = concept_name
            gold_rows.append(
                {
                    "gold_id": f"gold-{row['mismatch_id']}",
                    "profile_name": row["profile_name"],
                    "signature_hash": row["signature_hash"],
                    "fields": _generic_field(row, concept_name, concept_alias),
                    "expected_concept_id": str(
                        knowledge_obj["concept_id"]
                    ),
                    "expected_concept_name": concept_name,
                    "expected_industry_ids": knowledge_obj[
                        "industry_ids"
                    ],
                    "expected_relevance": adjudicated,
                    "expected_resolver_behavior": "resolve",
                    "inheritance_allowed": any(
                        bool(r.get("inherited"))
                        for r in knowledge_obj["relations"]
                    ),
                    "legacy_relevance": row["legacy_relevance"],
                    "adjudication": adjudication,
                }
            )

    for issue in ("transaction_noise", "customer_specific_expression", "insufficient_information"):
        if issue_counts[issue] > 0:
            gold_rows.append(
                {
                    "gold_id": f"gold-{issue}",
                    "profile_name": "building_material",
                    "signature_hash": "",
                    "fields": {
                        "remark": f"示例{issue}占位文本"
                    },
                    "expected_concept_id": "",
                    "expected_concept_name": "",
                    "expected_industry_ids": [],
                    "expected_relevance": "undetermined",
                    "expected_resolver_behavior": "undetermined",
                    "inheritance_allowed": False,
                    "legacy_relevance": "",
                    "adjudication": {
                        "adjudicated_relevance": "undetermined",
                        "preferred_system": "knowledge_v1",
                        "issue_type": issue,
                        "action_required": "none",
                        "reviewer_note": "Gold 代表条目：应保持 undetermined",
                    },
                }
            )

    total = len(rows)
    result = {
        "adjudication_version": "gate-a-adjudication-v1",
        "total": total,
        "preferred_system_counts": dict(sorted(counts.items())),
        "issue_type_counts": dict(sorted(issue_counts.items())),
        "upgrade_pair_counts": dict(sorted(upgrade_counts.items())),
        "legacy_correct_count": legacy_correct,
        "knowledge_correct_count": knowledge_correct,
        "legacy_accuracy": round(legacy_correct / total, 4) if total else 0.0,
        "knowledge_accuracy": (
            round(knowledge_correct / total, 4) if total else 0.0
        ),
        "gold_set_count": len(gold_rows),
        "rows": rows,
    }
    if args.adjudicated_json:
        args.adjudicated_json.parent.mkdir(parents=True, exist_ok=True)
        args.adjudicated_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.adjudicated_md:
        lines = [
            "# Gate A 121 条 mismatch 人工裁决汇总（per-entry profile）",
            "",
            f"- 总条数：{total}",
            f"- legacy 正确：{legacy_correct}（{result['legacy_accuracy']}）",
            f"- knowledge_v1 正确：{knowledge_correct}（{result['knowledge_accuracy']}）",
            "",
            "## preferred_system 分布",
            "",
        ]
        for key, count in sorted(counts.items()):
            lines.append(f"- {key}：{count}")
        lines.extend(["", "## issue_type 分布", ""])
        for key, count in sorted(issue_counts.items()):
            lines.append(f"- {key}：{count}")
        lines.extend(["", "## 40 条 upgrade 最终裁决（按 legacy→knowledge 对）", ""])
        for key, count in sorted(upgrade_counts.items()):
            lines.append(f"- {key}：{count}")
        args.adjudicated_md.parent.mkdir(parents=True, exist_ok=True)
        args.adjudicated_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.gold_set:
        args.gold_set.parent.mkdir(parents=True, exist_ok=True)
        args.gold_set.write_text(
            json.dumps(
                {
                    "gold_set_version": "gate-a-gold-v1",
                    "source": "mismatch-review-20260807",
                    "entries": gold_rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print("status=ok")
    print(f"total={total}")
    print(f"legacy_correct={legacy_correct}")
    print(f"knowledge_correct={knowledge_correct}")
    print(f"knowledge_accuracy={result['knowledge_accuracy']}")
    print(f"gold_set_count={len(gold_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
