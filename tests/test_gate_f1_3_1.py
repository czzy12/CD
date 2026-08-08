"""Gate F1.3.1 tests: AI contract validation, coverage regression, lifecycle."""

from __future__ import annotations

import unittest

from bankflow_v2.knowledge.ai_contracts import (
    validate_case_observation,
    validate_transaction_evidence_result,
)
from bankflow_v2.knowledge.coverage import industry_consistency_evidence_coverage
from bankflow_v2.knowledge.routing import (
    CASE_AI_LIFECYCLE,
    ROUTING_AI_ELIGIBLE_TRANSACTION,
    ROUTING_INSUFFICIENT_TRANSACTION,
    ROUTING_LOCAL_RESOLVED,
    TRANSACTION_AI_LIFECYCLE,
    evaluate_routing,
)


class AiContractValidationTest(unittest.TestCase):
    def test_transaction_result_valid(self):
        item = {"item_id": "dev-fee", "fields": {"summary": "项目服务费"}}
        result = {
            "item_id": "dev-fee",
            "role": "operating_expense",
            "trace_strength": "weak",
            "context_dependency": "high",
            "reason": "ambiguous",
            "evidence_refs": ["dev-fee"],
            "confidence": "medium",
        }
        self.assertEqual(
            validate_transaction_evidence_result(result, item),
            [],
        )

    def test_transaction_result_invalid(self):
        item = {"item_id": "dev-fee", "fields": {"summary": "项目服务费"}}
        result = {
            "item_id": "dev-fee",
            "role": "canonical_knowledge",
            "trace_strength": "super",
            "context_dependency": "",
            "reason": "",
            "evidence_refs": ["other"],
            "confidence": "certain",
        }
        failures = validate_transaction_evidence_result(result, item)
        self.assertIn("role_invalid", failures)
        self.assertIn("trace_strength_invalid", failures)
        self.assertIn("reason_missing", failures)
        self.assertIn("evidence_refs_not_allowed", failures)

    def _pack(self, coverage_value="partial"):
        return {
            "evidence_refs": ["tx-1", "tx-2"],
            "evidence_availability": {
                "semantics": {"unavailable_not_absent": True}
            },
            "industry_consistency_evidence_coverage": coverage_value,
        }

    def test_case_observation_valid(self):
        observation = {
            "business_activity_presence": "strong",
            "declared_industry_consistency": "weak",
            "industry_consistency_evidence_coverage": "partial",
            "supporting_evidence_refs": ["tx-1"],
            "contradictory_evidence_refs": [],
            "reasoning_summary": "direct evidence present, KB coverage partial",
            "uncertainty_reason": "coverage",
        }
        self.assertEqual(
            validate_case_observation(
                observation,
                self._pack(),
                coverage={"value": "partial"},
            ),
            [],
        )

    def test_case_observation_insufficient_must_be_undetermined(self):
        observation = {
            "business_activity_presence": "strong",
            "declared_industry_consistency": "none",
            "industry_consistency_evidence_coverage": "insufficient",
            "supporting_evidence_refs": [],
            "contradictory_evidence_refs": [],
            "reasoning_summary": "x",
            "uncertainty_reason": "",
        }
        failures = validate_case_observation(
            observation,
            self._pack("insufficient"),
            coverage={"value": "insufficient"},
        )
        self.assertIn("coverage_insufficient_must_be_undetermined", failures)

    def test_case_observation_partial_not_strong(self):
        observation = {
            "business_activity_presence": "strong",
            "declared_industry_consistency": "strong",
            "industry_consistency_evidence_coverage": "partial",
            "supporting_evidence_refs": [],
            "contradictory_evidence_refs": [],
            "reasoning_summary": "x",
            "uncertainty_reason": "",
        }
        failures = validate_case_observation(
            observation,
            self._pack("partial"),
            coverage={"value": "partial"},
        )
        self.assertIn("coverage_partial_must_not_be_strong", failures)

    def test_case_refs_must_exist_in_pack(self):
        observation = {
            "business_activity_presence": "strong",
            "declared_industry_consistency": "weak",
            "industry_consistency_evidence_coverage": "partial",
            "supporting_evidence_refs": ["tx-999"],
            "contradictory_evidence_refs": [],
            "reasoning_summary": "x",
            "uncertainty_reason": "",
        }
        failures = validate_case_observation(
            observation,
            self._pack(),
            coverage={"value": "partial"},
        )
        self.assertIn("supporting_evidence_refs_not_in_pack", failures)

    def test_lifecycles_stay_separate(self):
        self.assertNotEqual(
            TRANSACTION_AI_LIFECYCLE,
            CASE_AI_LIFECYCLE,
        )


class CoverageRegressionTest(unittest.TestCase):
    def _entry(self, role, relevance, routing, group):
        return {
            "role": role,
            "industry_relevance": relevance,
            "routing_state": routing,
            "evidence_group_key": f"{role}|{group}",
        }

    def test_exact_approved_relation_sufficient(self):
        entries = [
            self._entry(
                "direct_business",
                "strong",
                ROUTING_LOCAL_RESOLVED,
                "goods_payment",
            )
        ]
        coverage = industry_consistency_evidence_coverage(
            entries,
            relation_kb_covered_count=1,
            relation_kb_total_count=1,
        )
        self.assertEqual(coverage["value"], "sufficient")

    def test_parent_only_relation_partial(self):
        entries = [
            self._entry(
                "direct_business",
                "weak",
                ROUTING_LOCAL_RESOLVED,
                "goods_payment",
            )
        ]
        coverage = industry_consistency_evidence_coverage(
            entries,
            relation_kb_covered_count=0,
            relation_kb_total_count=1,
        )
        self.assertEqual(coverage["value"], "partial")

    def test_no_approved_relation_insufficient(self):
        coverage = industry_consistency_evidence_coverage(
            [],
            relation_kb_covered_count=0,
            relation_kb_total_count=0,
        )
        self.assertEqual(coverage["value"], "unavailable")

    def test_unresolved_concept_insufficient(self):
        entries = [
            self._entry(
                "unknown",
                "undetermined",
                ROUTING_INSUFFICIENT_TRANSACTION,
                "unknown",
            )
        ]
        coverage = industry_consistency_evidence_coverage(
            entries,
            relation_kb_covered_count=0,
            relation_kb_total_count=1,
        )
        self.assertEqual(coverage["value"], "insufficient")

    def test_explicit_canonical_none_is_known_none(self):
        entries = [
            self._entry(
                "personal_consumption",
                "none",
                ROUTING_LOCAL_RESOLVED,
                "dining",
            )
        ]
        coverage = industry_consistency_evidence_coverage(
            entries,
            relation_kb_covered_count=1,
            relation_kb_total_count=1,
        )
        self.assertEqual(coverage["relation_known_none_count"], 1)
        self.assertFalse(coverage["relation_not_known_treated_as_none"])


class RoutingMetricRegressionTest(unittest.TestCase):
    def test_deferred_vs_live(self):
        ambiguous = [
            {
                "transaction_id": "tx-a",
                "routing_state": ROUTING_AI_ELIGIBLE_TRANSACTION,
            }
        ]
        deferred = evaluate_routing(
            ambiguous,
            ai_invoked_ids=set(),
            execution_mode="deferred",
        )
        live = evaluate_routing(
            ambiguous,
            ai_invoked_ids=set(),
            execution_mode="live",
        )
        self.assertEqual(deferred["ai_execution_deferred"], 1)
        self.assertEqual(deferred["missed_ai_call"], 0)
        self.assertEqual(live["ai_execution_deferred"], 0)
        self.assertEqual(live["missed_ai_call"], 1)


if __name__ == "__main__":
    unittest.main()
