"""Gate F1.2 tests: case-level business trace synthesis (Layer C)."""

from __future__ import annotations

import unittest

from bankflow_v2.knowledge.case_trace import CaseTraceResolver


def entry(
    role,
    strength,
    group,
    *,
    month="2026-01",
    direction="expense",
    fields=None,
):
    return {
        "transaction_id": f"tx-{role}-{group}-{month}",
        "role": role,
        "trace_strength": strength,
        "industry_relevance": "weak",
        "direction": direction,
        "amount": "1000",
        "occurred_at": f"{month}-15",
        "evidence_group_key": f"{role}|{group}",
        "fields": fields or {"summary": f"{role}-{group}"},
    }


class CaseTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = CaseTraceResolver()

    def test_diverse_families_strong(self):
        entries = [
            entry("direct_business", "strong", "goods_payment", month="2026-01"),
            entry("direct_business", "strong", "wholesale", month="2026-02"),
            entry("tax_regulatory", "medium", "tax", month="2026-01"),
            entry("tax_regulatory", "medium", "tax", month="2026-02"),
            entry("operating_expense", "medium", "rent", month="2026-01"),
            entry("operating_expense", "medium", "rent", month="2026-02"),
            entry("operating_expense", "medium", "utilities", month="2026-02"),
        ]
        result = self.resolver.synthesize(entries, profile_name="test")
        self.assertEqual(result["business_activity_presence"], "strong")
        self.assertGreaterEqual(
            result["evidence_diversity"]["positive_family_count"],
            3,
        )
        self.assertGreaterEqual(
            result["evidence_diversity"]["distinct_positive_group_count"],
            5,
        )

    def test_duplicate_transfers_not_strong(self):
        entries = [
            entry("neutral_transfer", "undetermined", "transfer", month=f"2026-0{m}")
            for m in range(1, 5)
        ]
        result = self.resolver.synthesize(entries, profile_name="test")
        self.assertEqual(result["business_activity_presence"], "undetermined")
        self.assertEqual(result["dedup"]["group_occurrences"], 1)
        self.assertEqual(result["dedup"]["duplicate_suppressed_count"], 3)

    def test_weak_not_sum_to_strong(self):
        entries = [
            entry("operating_expense", "weak", "advertising"),
            entry("financing", "weak", "loan"),
            entry("government_interaction", "weak", "government"),
        ]
        result = self.resolver.synthesize(entries, profile_name="test")
        self.assertEqual(result["business_activity_presence"], "weak")

    def test_presence_strong_consistency_weak(self):
        entries = [
            entry("direct_business", "weak", "trade", month="2026-01"),
            entry("tax_regulatory", "medium", "tax", month="2026-01"),
            entry("tax_regulatory", "medium", "tax", month="2026-02"),
            entry("operating_expense", "medium", "rent", month="2026-01"),
            entry("operating_expense", "medium", "rent", month="2026-02"),
        ]
        result = self.resolver.synthesize(entries, profile_name="test")
        self.assertEqual(result["business_activity_presence"], "strong")
        self.assertEqual(result["declared_industry_consistency"], "weak")
        self.assertEqual(result["direct_industry_trace"], "weak")

    def test_no_entries_undetermined(self):
        result = self.resolver.synthesize([], profile_name="test")
        self.assertEqual(result["business_activity_presence"], "undetermined")
        self.assertEqual(result["declared_industry_consistency"], "undetermined")

    def test_case_context_alone_is_not_evidence(self):
        result = self.resolver.synthesize(
            [],
            case_context={"declared_industry": "51 批发业"},
            profile_name="test",
        )
        self.assertEqual(result["business_activity_presence"], "undetermined")

    def test_direct_without_industry_tie_is_weak_consistency(self):
        entries = [
            {
                **entry("direct_business", "strong", "goods_payment"),
                "industry_relevance": "undetermined",
            },
            {
                **entry("direct_business", "strong", "wholesale", month="2026-02"),
                "industry_relevance": "undetermined",
            },
        ]
        result = self.resolver.synthesize(entries, profile_name="test")
        self.assertEqual(result["direct_industry_trace"], "weak")
        self.assertEqual(result["declared_industry_consistency"], "weak")


if __name__ == "__main__":
    unittest.main()
