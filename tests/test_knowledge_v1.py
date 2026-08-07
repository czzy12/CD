import json
import tempfile
import unittest
from pathlib import Path

from bankflow_v2.knowledge import (
    KnowledgeAIError,
    KnowledgeReviewService,
    KnowledgeRuntime,
    RuntimeKnowledgeRepository,
    SemanticConcept,
    validate_knowledge_base,
)
from bankflow_v2.knowledge.ai_fallback import DeepSeekKnowledgeAdapter
from bankflow_v2.knowledge.industry_taxonomy import IndustryTaxonomy
from bankflow_v2.knowledge.models import (
    IndustryConceptRelation,
    IndustryNode,
    IndustryProfile,
    KnowledgeCandidate,
    KnowledgeVersion,
)
from bankflow_v2.knowledge.normalization import (
    build_industry_profile,
    normalize_semantic_text,
    semantic_signature_from_fields,
)
from bankflow_v2.knowledge.relations import RelationKB
from bankflow_v2.knowledge.resolver import IndustryRelationResolver
from bankflow_v2.knowledge.semantic_concepts import SemanticConceptKB
from bankflow_v2.deepseek_adapter import DeepSeekSettings


CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)


def runtime() -> KnowledgeRuntime:
    return KnowledgeRuntime.load(CANONICAL_DIR)


class KnowledgeModelsTests(unittest.TestCase):
    def test_industry_node_round_trip(self):
        node = IndustryNode(
            industry_id="x",
            name="测试行业",
            parent_id="economy",
            level=1,
            aliases=("测试",),
            keywords=("测试词",),
            source="test",
            source_version="v1",
            knowledge_version="kb-v1",
        )
        self.assertEqual(IndustryNode.from_dict(node.to_dict()), node)

    def test_concept_round_trip(self):
        concept = SemanticConcept(
            concept_id="c1",
            name_zh="概念",
            aliases=("别名",),
            keywords=("关键词",),
            parent_concept_id="",
            source="test",
            knowledge_version="kb-v1",
        )
        self.assertEqual(SemanticConcept.from_dict(concept.to_dict()), concept)

    def test_candidate_round_trip(self):
        candidate = KnowledgeCandidate(
            candidate_id="cand-1",
            candidate_type="new_semantic_concept",
            proposed_value={"concept_id": ""},
            reason="reason",
            model="test",
            prompt_version="p1",
            input_signature={"hash": "abc"},
        )
        self.assertEqual(
            KnowledgeCandidate.from_dict(candidate.to_dict()).candidate_id,
            "cand-1",
        )


class KnowledgeVersioningTests(unittest.TestCase):
    def test_default_version(self):
        from bankflow_v2.knowledge import versioning

        version = versioning.default_knowledge_version()
        self.assertEqual(version.knowledge_version, "business-semantic-kb-v1")
        self.assertTrue(version.taxonomy_version)
        self.assertTrue(version.resolver_version)

    def test_fingerprint_changes(self):
        from bankflow_v2.knowledge import versioning

        self.assertNotEqual(
            versioning.fingerprint({"a": 1}),
            versioning.fingerprint({"a": 2}),
        )


class KnowledgeNormalizationTests(unittest.TestCase):
    def test_normalize_whitespace_and_case(self):
        self.assertEqual(
            normalize_semantic_text("  物流 费  "),
            "物流费",
        )

    def test_identifiers_removed(self):
        for value in ("1234567890", "M0EEHDNH", "a3f09e8d77c44bc1"):
            self.assertEqual(normalize_semantic_text(value), "")

    def test_different_merchants_stay_distinct(self):
        first = normalize_semantic_text("示例建材有限公司")
        second = normalize_semantic_text("示例园林景观有限公司")
        self.assertNotEqual(first, second)

    def test_signature_stable_and_versioned(self):
        fields = {"remark": "物流费", "purpose": "运费"}
        signature = semantic_signature_from_fields(fields)
        again = semantic_signature_from_fields(fields)
        self.assertEqual(signature.signature_id, again.signature_id)
        self.assertTrue(signature.signature_version)
        self.assertNotEqual(
            signature.signature_id,
            semantic_signature_from_fields(
                fields,
                signature_version="semantic-signature-v2",
            ).signature_id,
        )


class KnowledgeTaxonomyTests(unittest.TestCase):
    def test_canonical_taxonomy_loads_and_has_parent_chain(self):
        taxonomy = IndustryTaxonomy.load(CANONICAL_DIR / "taxonomy.json")
        chain = taxonomy.parent_chain("internal.building_material_trade")
        ids = [node.industry_id for node in chain]
        self.assertEqual(ids[0], "internal.building_material_trade")
        self.assertIn("51", ids)
        self.assertIn("F", ids)

    def test_alias_resolution(self):
        taxonomy = IndustryTaxonomy.load(CANONICAL_DIR / "taxonomy.json")
        self.assertEqual(taxonomy.resolve_id("建材批发"), "internal.building_material_trade")
        self.assertEqual(taxonomy.resolve_id("不存在行业"), "")


class KnowledgeProfileTests(unittest.TestCase):
    def test_four_presets_profile(self):
        taxonomy = IndustryTaxonomy.load(CANONICAL_DIR / "taxonomy.json")
        cases = {
            "建筑材料批发、砂石、水泥": "internal.building_material_trade",
            "建筑工程，煤炭": "47",
            "烟酒零售、超市经营": "internal.alcohol_tobacco_retail",
            "家具电器销售、装饰装修": "internal.furniture_appliance_sales",
        }
        for text, expected_primary in cases.items():
            profile = build_industry_profile(
                {"confirmed_primary_business": text},
                taxonomy,
            )
            self.assertEqual(
                profile.primary_industry_ids,
                (expected_primary,),
                text,
            )


class SemanticResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = runtime()

    def test_exact_alias_hit(self):
        result = self.runtime.semantic_resolver.resolve({"remark": "物流费"})
        self.assertEqual(result.concept_id, "logistics")
        self.assertEqual(result.source, "knowledge_base")
        self.assertEqual(result.confidence, "high")

    def test_keyword_hit(self):
        result = self.runtime.semantic_resolver.resolve(
            {"purpose": "环保工程款"}
        )
        self.assertEqual(result.concept_id, "environmental_engineering_service")

    def test_unknown_returns_undetermined_without_ai(self):
        result = self.runtime.semantic_resolver.resolve({"remark": "银河系量子食堂"})
        self.assertEqual(result.source, "undetermined")
        self.assertFalse(result.ai_used)

    def test_direct_field_priority(self):
        result = self.runtime.semantic_resolver.resolve(
            {
                "counterparty_name": "示例建材有限公司",
                "remark": "货款",
            }
        )
        self.assertEqual(result.concept_id, "goods_payment")


class RelationResolverTests(unittest.TestCase):
    def test_exact_approved(self):
        runtime_instance = runtime()
        resolution = runtime_instance.relation_resolver.resolve(
            industry_id="internal.building_material_trade",
            concept_id="building_material",
        )
        self.assertEqual(resolution.relevance, "strong")
        self.assertEqual(resolution.relation_source, "approved_exact")

    def test_parent_inheritance(self):
        parent = IndustryNode(
            industry_id="parent",
            name="父行业",
            parent_id="economy",
            level=1,
            source="test",
            source_version="v1",
            knowledge_version="kb",
        )
        child = IndustryNode(
            industry_id="child",
            name="子行业",
            parent_id="parent",
            level=2,
            source="test",
            source_version="v1",
            knowledge_version="kb",
        )
        concept = SemanticConcept(
            concept_id="c",
            name_zh="概念",
            source="test",
            knowledge_version="kb",
        )
        relations = RelationKB(
            [
                IndustryConceptRelation(
                    industry_id="parent",
                    concept_id="c",
                    relevance="medium",
                    review_status="approved",
                    source="test",
                )
            ]
        )
        taxonomy = IndustryTaxonomy([parent, child])
        concepts = SemanticConceptKB([concept], [])
        resolver = IndustryRelationResolver(
            relations,
            taxonomy,
            version=KnowledgeVersion(
                taxonomy_version="t",
                semantic_kb_version="s",
                relation_kb_version="r",
            ),
        )
        resolution = resolver.resolve(
            industry_id="child",
            concept_id="c",
            profile=IndustryProfile(primary_industry_ids=("child",)),
        )
        self.assertEqual(resolution.relation_source, "inherited")
        self.assertEqual(resolution.relevance, "medium")

    def test_unknown_relation_undetermined(self):
        resolution = runtime().relation_resolver.resolve(
            industry_id="internal.building_material_trade",
            concept_id="nonexistent_concept",
        )
        self.assertEqual(resolution.relevance, "undetermined")
        self.assertEqual(resolution.relation_source, "undetermined")


class KnowledgeHardGuardTests(unittest.TestCase):
    def test_strength_capped_by_maximum(self):
        profile = IndustryProfile(primary_industry_ids=("internal.building_material_trade",))
        result = runtime().resolve_transaction_fields(
            {"remark": "货款"},
            profile,
        )
        self.assertEqual(result["constraints"]["maximum_allowed_strength"], "weak")
        self.assertEqual(result["final_relevance"], "weak")

    def test_life_concept_none(self):
        profile = IndustryProfile(primary_industry_ids=("internal.building_material_trade",))
        result = runtime().resolve_transaction_fields(
            {"merchant_name": "示例餐厅"},
            profile,
        )
        self.assertEqual(result["final_relevance"], "none")

    def test_unknown_ai_off_undetermined(self):
        result = runtime().resolve_transaction_fields(
            {"remark": "银河系量子食堂"},
            None,
        )
        self.assertEqual(result["final_relevance"], "undetermined")


class KnowledgeRepositoryTests(unittest.TestCase):
    def test_semantic_cache_round_trip(self):
        repository = RuntimeKnowledgeRepository(None)
        repository.semantic_cache_put(
            signature_version="v1",
            signature_hash="hash1",
            concept_id="logistics",
            resolution_source="knowledge_base",
            knowledge_version="kb",
        )
        cached = repository.semantic_cache_get("v1", "hash1")
        self.assertEqual(cached["concept_id"], "logistics")
        self.assertEqual(cached["hit_count"], 1)
        repository.close()

    def test_relation_cache_round_trip(self):
        repository = RuntimeKnowledgeRepository(None)
        repository.relation_cache_put(
            taxonomy_version="t",
            industry_id="i",
            concept_id="c",
            relation_rules_version="r",
            relevance="medium",
            relation_source="approved_exact",
            knowledge_version="kb",
        )
        cached = repository.relation_cache_get(
            taxonomy_version="t",
            industry_id="i",
            concept_id="c",
            relation_rules_version="r",
        )
        self.assertEqual(cached["relevance"], "medium")
        repository.close()

    def test_candidate_dedupe_and_review(self):
        repository = RuntimeKnowledgeRepository(None)
        candidate = KnowledgeCandidate(
            candidate_id="c1",
            candidate_type="new_semantic_concept",
            proposed_value={"concept_id": ""},
            reason="r",
            model="m",
            prompt_version="p",
            input_signature={"hash": "h"},
        )
        self.assertTrue(repository.add_candidate(candidate))
        self.assertFalse(repository.add_candidate(candidate))
        reviewed = repository.review_candidate("c1", "approved")
        self.assertEqual(reviewed.review_status, "approved")
        repository.close()


class KnowledgeValidatorTests(unittest.TestCase):
    def test_canonical_valid(self):
        report = validate_knowledge_base(CANONICAL_DIR)
        self.assertTrue(report.ok, report.errors)
        self.assertGreater(report.counts["concepts"], 0)

    def test_detects_sensitive_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            taxonomy = json.loads((CANONICAL_DIR / "taxonomy.json").read_text(encoding="utf-8"))
            taxonomy["nodes"][0]["name"] = "测试 6222020200001234567"
            (root / "taxonomy.json").write_text(
                json.dumps(taxonomy, ensure_ascii=False),
                encoding="utf-8",
            )
            for name in (
                "semantic_concepts.json",
                "semantic_aliases.json",
                "relations.json",
            ):
                (root / name).write_text(
                    (CANONICAL_DIR / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            report = validate_knowledge_base(root)
            self.assertFalse(report.ok)
            self.assertTrue(
                any("sensitive" in error for error in report.errors)
            )

    def test_detects_alias_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "taxonomy.json",
                "semantic_concepts.json",
                "relations.json",
            ):
                (root / name).write_text(
                    (CANONICAL_DIR / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            aliases = json.loads(
                (CANONICAL_DIR / "semantic_aliases.json").read_text(encoding="utf-8")
            )
            aliases["aliases"][0]["concept_id"] = "logistics"
            aliases["aliases"][1]["alias_text"] = aliases["aliases"][0]["alias_text"]
            (root / "semantic_aliases.json").write_text(
                json.dumps(aliases, ensure_ascii=False),
                encoding="utf-8",
            )
            report = validate_knowledge_base(root)
            self.assertFalse(report.ok)
            self.assertTrue(
                any("alias conflict" in error for error in report.errors)
            )


class KnowledgeReviewTests(unittest.TestCase):
    def test_propose_approve_promotes_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            canonical.mkdir()
            for name in (
                "taxonomy.json",
                "semantic_concepts.json",
                "semantic_aliases.json",
                "relations.json",
            ):
                (canonical / name).write_text(
                    (CANONICAL_DIR / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            repository = RuntimeKnowledgeRepository(root / "cache")
            review = KnowledgeReviewService(repository, canonical)
            candidate = review.propose(
                candidate_type="new_semantic_concept",
                proposed_value={
                    "concept_id": "new_concept",
                    "name_zh": "新概念",
                },
                reason="test",
                model="test",
                prompt_version="p1",
                input_signature={"hash": "h"},
            )
            self.assertEqual(candidate.review_status, "pending")
            approved = review.approve(candidate.candidate_id)
            self.assertEqual(approved.review_status, "approved")
            concepts = json.loads(
                (canonical / "semantic_concepts.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                any(
                    item.get("concept_id") == "new_concept"
                    for item in concepts["concepts"]
                )
            )
            repository.close()

    def test_reject(self):
        repository = RuntimeKnowledgeRepository(None)
        review = KnowledgeReviewService(repository, CANONICAL_DIR)
        candidate = review.propose(
            candidate_type="new_alias",
            proposed_value={"alias_text": "测试别名", "concept_id": "logistics"},
            reason="test",
            model="test",
            prompt_version="p1",
            input_signature={"hash": "h"},
        )
        rejected = review.reject(candidate.candidate_id)
        self.assertEqual(rejected.review_status, "rejected")
        repository.close()


class KnowledgeAIAdapterTests(unittest.TestCase):
    def _settings(self) -> DeepSeekSettings:
        return DeepSeekSettings(
            api_key="test-key",
            enabled=True,
            data_authorized=True,
            retention_policy_confirmed=True,
            base_url="https://example.com",
        )

    @staticmethod
    def _envelope(results: list[dict[str, object]]) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"results": results},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def test_concept_adapter_validates_and_filters_fields(self):
        captured = {}

        def transport(url, body, headers, timeout):
            captured["body"] = body.decode("utf-8")
            return self._envelope(
                [
                    {
                        "item_id": "i1",
                        "concept_id": "logistics",
                        "confidence": "high",
                        "reason": "运费",
                        "used_fields": ["remark"],
                    }
                ]
            )

        adapter = DeepSeekKnowledgeAdapter(self._settings(), transport)
        results = adapter.resolve_concepts(
            [
                {
                    "item_id": "i1",
                    "fields": {
                        "remark": "运费",
                        "amount": "100.00",
                        "date": "2026-01-01",
                    },
                }
            ],
            concept_candidates=[{"concept_id": "logistics"}],
        )
        self.assertEqual(results[0]["concept_id"], "logistics")
        payload = json.loads(captured["body"])
        user = json.loads(payload["messages"][1]["content"])
        sent_fields = user["items"][0]["fields"]
        self.assertNotIn("amount", sent_fields)
        self.assertNotIn("date", sent_fields)
        self.assertIn("remark", sent_fields)

    def test_concept_adapter_rejects_unknown_field_reference(self):
        def transport(url, body, headers, timeout):
            return self._envelope(
                [
                    {
                        "item_id": "i1",
                        "concept_id": "logistics",
                        "confidence": "high",
                        "reason": "r",
                        "used_fields": ["amount"],
                    }
                ]
            )

        adapter = DeepSeekKnowledgeAdapter(self._settings(), transport)
        with self.assertRaises(KnowledgeAIError):
            adapter.resolve_concepts(
                [{"item_id": "i1", "fields": {"remark": "运费"}}],
                concept_candidates=[],
            )

    def test_relation_adapter_requires_acknowledgement(self):
        def transport(url, body, headers, timeout):
            return self._envelope(
                [
                    {
                        "item_id": "i1",
                        "relevance": "medium",
                        "reason": "r",
                        "constraint_acknowledged": False,
                    }
                ]
            )

        adapter = DeepSeekKnowledgeAdapter(self._settings(), transport)
        with self.assertRaises(KnowledgeAIError):
            adapter.resolve_relations(
                [{"item_id": "i1", "industry_id": "51", "concept_id": "logistics"}],
                industry_nodes=[],
            )


if __name__ == "__main__":
    unittest.main()
