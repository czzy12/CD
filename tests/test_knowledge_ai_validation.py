"""Gate D tests: privacy guard, preflight, candidate lifecycle, retry, guards."""

import json
import unittest
from pathlib import Path

from bankflow_v2.deepseek_adapter import DeepSeekSettings
from bankflow_v2.knowledge import (
    build_privacy_preflight,
    build_validation_items,
    call_with_retry,
    guard_item,
    run_concept_validation,
    run_relation_validation,
    split_guarded,
    versioning,
)
from bankflow_v2.knowledge.ai_fallback import DeepSeekKnowledgeAdapter, KnowledgeAIError
from bankflow_v2.knowledge.industry_taxonomy import IndustryTaxonomy
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.relations import RelationKB
from bankflow_v2.knowledge.repository import RuntimeKnowledgeRepository
from bankflow_v2.knowledge.resolver import KnowledgeRuntime as _KR
from bankflow_v2.knowledge.semantic_concepts import SemanticConceptKB


CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)

PROFILE = IndustryProfile(
    primary_industry_ids=("internal.building_material_trade",),
    secondary_industry_ids=("internal.environmental_engineering",),
    taxonomy_version=versioning.TAXONOMY_VERSION,
    profile_name="building_material",
)


def _runtime(repository=None) -> _KR:
    taxonomy = IndustryTaxonomy.load(CANONICAL_DIR / "taxonomy.json")
    concepts = SemanticConceptKB.load(
        CANONICAL_DIR / "semantic_concepts.json",
        CANONICAL_DIR / "semantic_aliases.json",
    )
    relations = RelationKB.load(CANONICAL_DIR / "relations.json")
    return _KR(
        taxonomy=taxonomy,
        concepts=concepts,
        relations=relations,
        repository=repository,
        version=versioning.default_knowledge_version(),
    )


def _unknown_entry() -> dict[str, object]:
    return {
        "signature_hash": "u" * 24,
        "fields": {"remark": "量子秘传杂项支出"},
        "legacy_semantic_judgement": "none",
        "legacy_business_context": {},
    }


class PiiGuardTests(unittest.TestCase):
    def test_blocks_id_card_phone_bank_card_and_path(self):
        id_card = "110101199003077751"
        phone = "13800138000"
        card = "6222021234567890123"
        path = "C:\\Users\\someone\\Downloads\\statement.pdf"
        for value in (id_card, phone, card, path):
            result = guard_item({"remark": value})
            self.assertFalse(result.allowed, value)
            self.assertTrue(result.blocked_fields)

    def test_blocks_identity_and_non_whitelist_keys(self):
        result = guard_item({"id_card": "110101199003077751", "remark": "物流费"})
        self.assertFalse(result.allowed)
        result = guard_item({"local_path": "C:\\x\\y.pdf"})
        self.assertFalse(result.allowed)
        result = guard_item({"full_text": "物流费"})
        self.assertFalse(result.allowed)

    def test_allows_safe_organization_fields(self):
        result = guard_item(
            {
                "counterparty_name": "某某建材有限公司",
                "remark": "物流费",
            }
        )
        self.assertTrue(result.allowed)

    def test_typed_business_field_allows_luhn_invalid_business_identifier(self):
        from bankflow_v2.knowledge.privacy import _luhn_ok

        identifier = "1234567890123456"
        self.assertFalse(_luhn_ok(identifier))
        for field_name in ("product_description", "merchant_category"):
            with self.subTest(field=field_name):
                result = guard_item(
                    {field_name: "某便利店收款流水 " + identifier}
                )
                self.assertTrue(result.allowed)

    def test_luhn_valid_card_still_blocked_in_typed_field(self):
        card = "4111111111111111"
        self.assertTrue(
            guard_item({"product_description": "某门店收款 " + card}).blocked_fields
        )
        self.assertTrue(
            guard_item({"product_description": card}).blocked_fields
        )

    def test_card_hint_blocks_typed_field_even_when_luhn_fails(self):
        result = guard_item(
            {"product_description": "银行卡1234567890123456"}
        )
        self.assertFalse(result.allowed)
        self.assertIn("bank_card", result.reasons)

    def test_free_form_fields_keep_strict_card_block(self):
        for field_name in ("remark", "summary", "purpose"):
            result = guard_item(
                {field_name: "某门店收款 1234567890123456"}
            )
            self.assertFalse(result.allowed)

    def test_classify_bank_card_block(self):
        from bankflow_v2.knowledge.privacy import classify_bank_card_block

        self.assertEqual(
            classify_bank_card_block(
                "product_description",
                "某门店收款 4111111111111111",
            ),
            "true_positive",
        )
        self.assertEqual(
            classify_bank_card_block(
                "product_description",
                "某便利店收款流水 1234567890123456",
            ),
            "false_positive",
        )
        self.assertEqual(
            classify_bank_card_block(
                "remark",
                "某门店收款 1234567890123456",
            ),
            "ambiguous",
        )
        self.assertEqual(
            classify_bank_card_block(
                "product_description",
                "1234567890123456",
            ),
            "ambiguous",
        )


class PrivacyPreflightTests(unittest.TestCase):
    def test_preflight_has_required_keys_and_no_raw_values(self):
        items = [
            {
                "signature_hash": "a" * 24,
                "fields": {"remark": "110101199003077751"},
            },
            {
                "signature_hash": "b" * 24,
                "fields": {"counterparty_name": "某某建材有限公司"},
            },
        ]
        preflight = build_privacy_preflight(
            task="semantic-concept-v1",
            prompt_version="semantic-concept-v1",
            provider="deepseek",
            model="deepseek-v4-flash",
            items=items,
        )
        for key in (
            "task",
            "prompt_version",
            "provider",
            "model",
            "signature_count",
            "payload_keys",
            "redacted_fields",
            "privacy_blocked_count",
        ):
            self.assertIn(key, preflight)
        self.assertEqual(preflight["signature_count"], 2)
        self.assertEqual(preflight["privacy_blocked_count"], 1)
        serialized = json.dumps(preflight, ensure_ascii=False)
        self.assertNotIn("110101199003077751", serialized)


class ValidationItemPreparationTests(unittest.TestCase):
    def test_dedup_and_local_resolved_skip(self):
        runtime = _runtime()
        entries = [
            _unknown_entry(),
            {"signature_hash": "v" * 24, "fields": {"remark": "物流费"}, "legacy_business_context": {}},
            {
                "signature_hash": "w" * 24,
                "fields": {"remark": "量子秘传杂项支出"},
                "legacy_business_context": {},
            },
        ]
        items, counts = build_validation_items(entries, runtime, PROFILE)
        self.assertEqual(counts["locally_resolved_skipped"], 1)
        self.assertEqual(counts["eligible_unique_signatures"], 1)
        self.assertEqual(counts["eligible_transactions"], 2)
        self.assertEqual(counts["duplicated_signatures_skipped"], 1)
        self.assertEqual(items[0]["member_count"], 2)

    def test_approved_cache_prevents_ai_call(self):
        repository = RuntimeKnowledgeRepository(None)
        signature = semantic_signature_from_fields({"remark": "量子秘传杂项支出"})
        repository.semantic_cache_put(
            signature_version=signature.signature_version,
            signature_hash=signature.signature_id,
            concept_id="logistics",
            resolution_source="approved",
            knowledge_version=versioning.KNOWLEDGE_VERSION,
            review_status="approved",
        )
        runtime = _runtime(repository)
        items, counts = build_validation_items([_unknown_entry()], runtime, PROFILE)
        self.assertEqual(counts["locally_resolved_skipped"], 1)
        self.assertEqual(len(items), 0)

    def test_guard_split(self):
        items = [
            {
                "signature_hash": "a" * 24,
                "fields": {"remark": "物流费"},
                "source": "test",
            },
            {
                "signature_hash": "b" * 24,
                "fields": {"remark": "110101199003077751"},
                "source": "test",
            },
        ]
        sendable, blocked = split_guarded(items)
        self.assertEqual(len(sendable), 1)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["signature_hash"], "b" * 24)


class FakeConceptAdapter:
    model = "fake-model"

    def __init__(self, results=None, fail_times=0, always_fail=False):
        self.results = results or []
        self.fail_times = fail_times
        self.always_fail = always_fail
        self.calls = 0
        self.sent: list[list[dict[str, object]]] = []

    def resolve_concepts(self, items, *, concept_candidates):
        self.calls += 1
        self.sent.append(items)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise KnowledgeAIError("provider request failed")
        if self.always_fail:
            raise KnowledgeAIError("provider returned invalid JSON")
        return [dict(result) for result in self.results]


class ConceptValidationTests(unittest.TestCase):
    def _items(self):
        runtime = _runtime()
        items, _ = build_validation_items([_unknown_entry()], runtime, PROFILE)
        return runtime, items

    def test_pending_candidate_created_and_idempotent(self):
        runtime, items = self._items()
        repository = RuntimeKnowledgeRepository(None)
        adapter = FakeConceptAdapter(
            [
                {
                    "item_id": items[0]["item_id"],
                    "concept_id": "logistics",
                    "confidence": "high",
                    "reason": "test",
                    "used_fields": ["remark"],
                }
            ]
        )
        first = run_concept_validation(adapter, items, runtime, repository)
        self.assertEqual(first["metrics"]["concept_candidates"], 1)
        self.assertEqual(first["metrics"]["existing_concept_proposed"], 1)
        candidates = repository.list_candidates("pending")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].review_status, "pending")

        second = run_concept_validation(adapter, items, runtime, repository)
        self.assertEqual(second["metrics"]["duplicate_candidate_prevented"], 1)
        self.assertEqual(second["metrics"]["concept_candidates"], 0)
        self.assertEqual(len(repository.list_candidates("pending")), 1)

    def test_insufficient_keeps_unresolved_without_candidate(self):
        runtime, items = self._items()
        repository = RuntimeKnowledgeRepository(None)
        adapter = FakeConceptAdapter(
            [
                {
                    "item_id": items[0]["item_id"],
                    "concept_id": "undetermined",
                    "confidence": "low",
                    "reason": "insufficient",
                    "used_fields": ["remark"],
                }
            ]
        )
        result = run_concept_validation(adapter, items, runtime, repository)
        self.assertEqual(result["metrics"]["insufficient"], 1)
        self.assertEqual(result["metrics"]["concept_candidates"], 0)
        self.assertEqual(len(repository.list_candidates()), 0)
        self.assertEqual(result["metrics"]["items_remaining_unresolved"], 1)

    def test_new_concept_candidate(self):
        runtime, items = self._items()
        repository = RuntimeKnowledgeRepository(None)
        adapter = FakeConceptAdapter(
            [
                {
                    "item_id": items[0]["item_id"],
                    "concept_id": "",
                    "confidence": "medium",
                    "reason": "new generic concept",
                    "used_fields": ["remark"],
                    "new_concept_candidate": {
                        "suggested_concept_id": "new_generic_service",
                        "name_zh": "新通用服务",
                        "reason": "generic",
                    },
                }
            ]
        )
        result = run_concept_validation(adapter, items, runtime, repository)
        self.assertEqual(result["metrics"]["new_concept_proposed"], 1)
        self.assertEqual(result["metrics"]["concept_candidates"], 1)
        candidate = repository.list_candidates("pending")[0]
        self.assertEqual(
            candidate.proposed_value["concept_id"],
            "new_generic_service",
        )

    def test_failed_call_keeps_unresolved_no_candidate(self):
        runtime, items = self._items()
        repository = RuntimeKnowledgeRepository(None)
        adapter = FakeConceptAdapter(always_fail=True)
        result = run_concept_validation(
            adapter,
            items,
            runtime,
            repository,
            attempts=2,
            retry_delay=0,
        )
        self.assertEqual(result["metrics"]["ai_failed"], 1)
        self.assertEqual(result["metrics"]["ai_retry"], 1)
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(len(repository.list_candidates()), 0)
        self.assertEqual(result["metrics"]["items_remaining_unresolved"], 1)

    def test_retry_succeeds_on_second_attempt(self):
        runtime, items = self._items()
        repository = RuntimeKnowledgeRepository(None)
        adapter = FakeConceptAdapter(
            [
                {
                    "item_id": items[0]["item_id"],
                    "concept_id": "logistics",
                    "confidence": "high",
                    "reason": "test",
                    "used_fields": ["remark"],
                }
            ],
            fail_times=1,
        )
        result = run_concept_validation(
            adapter,
            items,
            runtime,
            repository,
            attempts=2,
            retry_delay=0,
        )
        self.assertEqual(result["metrics"]["ai_success"], 1)
        self.assertEqual(result["metrics"]["ai_retry"], 1)
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(result["metrics"]["concept_candidates"], 1)


class RelationValidationGuardTests(unittest.TestCase):
    class FakeRelationAdapter:
        model = "fake-model"

        def __init__(self, results):
            self.results = results
            self.calls = 0

        def resolve_relations(self, items, *, industry_nodes):
            self.calls += 1
            return [dict(result) for result in self.results]

    def test_model_strength_capped_by_local_guard(self):
        repository = RuntimeKnowledgeRepository(None)
        runtime = _runtime()
        entry = {
            "item": {
                "item_id": "sig-x",
                "signature_hash": "x" * 24,
                "signature_text_hash": "y" * 24,
                "fields": {"remark": "货款"},
                "industry_ids": ["internal.building_material_trade"],
                "source": "test",
                "member_count": 1,
            },
            "concept_id": "brand_new_concept",
            "concept_name": "新概念",
            "proposal_kind": "new_concept",
            "candidate_id": "c1",
        }
        adapter = self.FakeRelationAdapter(
            [
                {
                    "item_id": "sig-x|internal.building_material_trade",
                    "relevance": "strong",
                    "reason": "test",
                    "constraint_acknowledged": True,
                }
            ]
        )
        result = run_relation_validation(
            adapter,
            [entry],
            runtime,
            repository,
            retry_delay=0,
        )
        self.assertEqual(result["metrics"]["relation_invoked"], 1)
        self.assertEqual(result["metrics"]["guard_adjusted"], 1)
        self.assertEqual(result["metrics"]["relation_candidates"], 1)
        candidate = repository.list_candidates("pending")[0]
        self.assertEqual(candidate.proposed_value["relevance"], "weak")
        self.assertEqual(candidate.proposed_value["model_raw_relevance"], "strong")
        self.assertTrue(candidate.proposed_value["guard_adjusted"])


class RetryAndSafetyTests(unittest.TestCase):
    def test_call_with_retry_limited(self):
        attempts = []

        def fail_twice():
            attempts.append(1)
            raise KnowledgeAIError("boom")

        outcome = call_with_retry(fail_twice, attempts=2, delay=0)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["attempt_count"], 2)
        self.assertEqual(len(attempts), 2)

    def test_disabled_adapter_never_calls_network(self):
        def transport(url, body, headers, timeout):
            raise AssertionError("network must not be called")

        settings = DeepSeekSettings(
            api_key="",
            base_url="https://example.com",
            enabled=False,
            data_authorized=False,
            retention_policy_confirmed=False,
        )
        adapter = DeepSeekKnowledgeAdapter(settings, transport)
        with self.assertRaises(KnowledgeAIError):
            adapter.resolve_concepts(
                [{"item_id": "i1", "fields": {"remark": "物流费"}}],
                concept_candidates=[],
            )


if __name__ == "__main__":
    unittest.main()
