"""Gate F1.3 tests: Local/AI routing, coverage diagnostic, CaseEvidencePack."""

from __future__ import annotations

import json
import unittest

from bankflow_v2.knowledge.case_evidence_pack import build_case_evidence_pack
from bankflow_v2.knowledge.case_trace import CaseTraceResolver
from bankflow_v2.knowledge.coverage import industry_consistency_evidence_coverage
from bankflow_v2.knowledge.evidence import BusinessEvidenceResolver
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.routing import (
    ROUTING_AI_ELIGIBLE_TRANSACTION,
    ROUTING_INSUFFICIENT_TRANSACTION,
    ROUTING_LOCAL_RESOLVED,
    evaluate_routing,
)


def profile51() -> IndustryProfile:
    return IndustryProfile(
        primary_industry_ids=("51",),
        normalized_products_services=(
            "铝锭大宗贸易",
            "金属材料销售",
            "金属矿石销售",
            "金属制品销售",
            "生产性废旧金属回收",
            "石墨及碳素制品销售",
        ),
        profile_name="test-51-wholesale",
    )


class LocalAiRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = BusinessEvidenceResolver()

    def resolve(self, fields, **kwargs):
        return self.resolver.resolve(fields, **kwargs)

    def test_explicit_tax_local_resolved(self):
        result = self.resolve({"summary": "增值税缴税"})
        self.assertEqual(result["routing_state"], ROUTING_LOCAL_RESOLVED)

    def test_explicit_salary_local_resolved(self):
        result = self.resolve({"summary": "代发工资"})
        self.assertEqual(result["routing_state"], ROUTING_LOCAL_RESOLVED)

    def test_explicit_settlement_local_resolved(self):
        result = self.resolve({"summary": "企业结算卡年费"})
        self.assertEqual(result["routing_state"], ROUTING_LOCAL_RESOLVED)

    def test_explicit_personal_local_resolved(self):
        result = self.resolve({"merchant_name": "黄家龙虾", "summary": "消费"})
        self.assertEqual(result["routing_state"], ROUTING_LOCAL_RESOLVED)
        self.assertEqual(result["role"], "personal_consumption")

    def test_payment_rail_only_local_resolved(self):
        result = self.resolve({"summary": "财付通"})
        self.assertEqual(result["routing_state"], ROUTING_LOCAL_RESOLVED)
        self.assertEqual(result["role"], "neutral_transfer")

    def test_generic_service_fee_ai_eligible(self):
        result = self.resolve({"summary": "项目服务费"})
        self.assertEqual(result["routing_state"], ROUTING_AI_ELIGIBLE_TRANSACTION)
        self.assertEqual(result["trace_strength"], "weak")

    def test_ambiguous_loan_ai_eligible(self):
        result = self.resolve({"summary": "借款"})
        self.assertEqual(result["routing_state"], ROUTING_AI_ELIGIBLE_TRANSACTION)
        self.assertEqual(result["role"], "financing")

    def test_government_interaction_ai_eligible(self):
        result = self.resolve({"counterparty_name": "XX市财政局"})
        self.assertEqual(result["routing_state"], ROUTING_AI_ELIGIBLE_TRANSACTION)
        self.assertEqual(result["role"], "government_interaction")

    def test_generic_company_name_ai_eligible(self):
        result = self.resolve({"counterparty_name": "某某贸易有限公司"})
        self.assertEqual(result["routing_state"], ROUTING_AI_ELIGIBLE_TRANSACTION)

    def test_context_dependent_merchant_ai_eligible(self):
        result = self.resolve(
            {"merchant_name": "某建材批发市场"},
            profile=profile51(),
        )
        self.assertEqual(result["routing_state"], ROUTING_AI_ELIGIBLE_TRANSACTION)
        self.assertEqual(result["role"], "direct_business")
        self.assertEqual(result["trace_strength"], "weak")

    def test_no_evidence_insufficient(self):
        result = self.resolve({})
        self.assertEqual(result["routing_state"], ROUTING_INSUFFICIENT_TRANSACTION)

    def test_unnecessary_ai_call_detected(self):
        local = {
            "transaction_id": "tx-tax",
            "routing_state": ROUTING_LOCAL_RESOLVED,
        }
        metrics = evaluate_routing([local], ai_invoked_ids={"tx-tax"})
        self.assertEqual(metrics["unnecessary_ai_call"], 1)

    def test_missed_ai_call_detected(self):
        ambiguous = {
            "transaction_id": "tx-fee",
            "routing_state": ROUTING_AI_ELIGIBLE_TRANSACTION,
        }
        metrics = evaluate_routing([ambiguous], ai_invoked_ids=set())
        self.assertEqual(metrics["missed_ai_call"], 1)


class CoverageDiagnosticTest(unittest.TestCase):
    def test_relation_not_known_not_none(self):
        entries = [
            {
                "role": "direct_business",
                "evidence_group_key": "direct_business|goods_payment",
                "industry_relevance": "undetermined",
                "routing_state": ROUTING_LOCAL_RESOLVED,
            }
        ]
        coverage = industry_consistency_evidence_coverage(
            entries,
            relation_kb_covered_count=0,
            relation_kb_total_count=0,
        )
        self.assertEqual(coverage["value"], "partial")
        self.assertFalse(coverage["relation_not_known_treated_as_none"])

    def test_known_none_is_distinct_from_unknown(self):
        entries = [
            {
                "role": "personal_consumption",
                "evidence_group_key": "personal_consumption|dining",
                "industry_relevance": "none",
                "routing_state": ROUTING_LOCAL_RESOLVED,
            }
        ]
        coverage = industry_consistency_evidence_coverage(
            entries,
            relation_kb_covered_count=1,
            relation_kb_total_count=1,
        )
        self.assertEqual(coverage["relation_known_none_count"], 1)
        self.assertEqual(coverage["relation_undetermined_count"], 0)

    def test_case_consistency_uses_coverage_qualification(self):
        entries = [
            {
                "transaction_id": "tx-1",
                "role": "direct_business",
                "trace_strength": "strong",
                "industry_relevance": "undetermined",
                "direction": "expense",
                "amount": "1000",
                "occurred_at": "2026-01-15",
                "evidence_group_key": "direct_business|goods_payment",
                "fields": {"summary": "铝锭货款"},
            },
            {
                "transaction_id": "tx-2",
                "role": "direct_business",
                "trace_strength": "strong",
                "industry_relevance": "undetermined",
                "direction": "income",
                "amount": "2000",
                "occurred_at": "2026-02-15",
                "evidence_group_key": "direct_business|wholesale",
                "fields": {"summary": "金属材料销售"},
            },
        ]
        result = CaseTraceResolver().synthesize(
            entries,
            relation_kb_covered_count=0,
            relation_kb_total_count=0,
            profile_name="test",
        )
        self.assertEqual(result["declared_industry_consistency"], "weak")
        self.assertEqual(
            result["industry_consistency_evidence_coverage"],
            "partial",
        )
        self.assertTrue(result["industry_consistency_coverage_qualification"])


class CaseEvidencePackTest(unittest.TestCase):
    def _entries(self):
        return [
            {
                "transaction_id": "tx-1",
                "role": "direct_business",
                "trace_strength": "strong",
                "routing_state": ROUTING_LOCAL_RESOLVED,
                "industry_relevance": "undetermined",
                "direction": "expense",
                "amount": "1000",
                "occurred_at": "2026-01-15",
                "evidence_group_key": "direct_business|goods_payment",
                "fields": {"summary": "铝锭货款"},
            },
            {
                "transaction_id": "tx-2",
                "role": "direct_business",
                "trace_strength": "strong",
                "routing_state": ROUTING_LOCAL_RESOLVED,
                "industry_relevance": "undetermined",
                "direction": "expense",
                "amount": "900",
                "occurred_at": "2026-01-20",
                "evidence_group_key": "direct_business|goods_payment",
                "fields": {"summary": "铝锭货款"},
            },
            {
                "transaction_id": "tx-3",
                "role": "tax_regulatory",
                "trace_strength": "medium",
                "routing_state": ROUTING_LOCAL_RESOLVED,
                "industry_relevance": "undetermined",
                "direction": "expense",
                "amount": "500",
                "occurred_at": "2026-02-10",
                "evidence_group_key": "tax_regulatory|tax",
                "fields": {"summary": "增值税"},
            },
        ]

    def test_deterministic_and_pii_safe(self):
        first = build_case_evidence_pack(
            self._entries(),
            case_ref="case-abc",
            declared_industry="51 批发业",
        )
        second = build_case_evidence_pack(
            self._entries(),
            case_ref="case-abc",
            declared_industry="51 批发业",
        )
        first_without_ts = {
            key: value
            for key, value in first.items()
            if key not in {"generated_at"}
        }
        second_without_ts = {
            key: value
            for key, value in second.items()
            if key not in {"generated_at"}
        }
        self.assertEqual(
            json.dumps(first_without_ts, ensure_ascii=False, sort_keys=True),
            json.dumps(second_without_ts, ensure_ascii=False, sort_keys=True),
        )
        self.assertTrue(first["pii_safe"])
        serialized = json.dumps(
            {
                key: value
                for key, value in first.items()
                if key not in {"pii_check", "generated_at"}
            },
            ensure_ascii=False,
        )
        for key in ("customer_name", "id_card", "account", "phone"):
            self.assertNotIn(key, serialized)

    def test_refs_preserved_and_dedup(self):
        pack = build_case_evidence_pack(
            self._entries(),
            case_ref="case-abc",
        )
        self.assertIn("tx-1", pack["evidence_refs"])
        self.assertIn("tx-2", pack["evidence_refs"])
        self.assertEqual(pack["evidence_group_count"], 2)
        direct = pack["family_summaries"]["direct_business"]
        self.assertEqual(direct["occurrence_count"], 2)
        self.assertEqual(direct["group_count"], 1)

    def test_evidence_diversity_preserved(self):
        pack = build_case_evidence_pack(
            self._entries(),
            case_ref="case-abc",
        )
        self.assertEqual(
            sorted(pack["family_summaries"]),
            ["direct_business", "tax_regulatory"],
        )


if __name__ == "__main__":
    unittest.main()
