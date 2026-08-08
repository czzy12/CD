"""Gate D.3B: property_management canonical knowledge tests."""

import json
import unittest
from pathlib import Path

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    versioning,
)
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.schema_117 import _relation_id


CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)


class PropertyManagementConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = KnowledgeRuntime.load(CANONICAL_DIR)

    def test_concept_created_with_generic_definition(self):
        concept = self.runtime.concepts.concept("property_management")
        self.assertIsNotNone(concept)
        self.assertEqual(concept.name_zh, "物业管理")
        self.assertEqual(concept.parent_concept_id, "service")
        self.assertIn("物业管理", concept.description)
        for alias in ("物业", "物业管理", "物业费", "物业服务", "物业公司"):
            self.assertIn(alias, concept.aliases)

    def test_no_merchant_specific_aliases(self):
        concept = self.runtime.concepts.concept("property_management")
        joined = "|".join(concept.aliases)
        for merchant in ("东方花园", "中土基"):
            self.assertNotIn(merchant, joined)
        aliases = json.loads(
            (CANONICAL_DIR / "semantic_aliases.json").read_text(encoding="utf-8")
        )
        alias_texts = "|".join(
            str(item.get("alias_text", ""))
            for item in aliases.get("aliases", [])
        )
        self.assertNotIn("东方花园", alias_texts)
        self.assertNotIn("中土基", alias_texts)

    def test_supporting_signatures_resolve_locally(self):
        profile = IndustryProfile(
            primary_industry_ids=("47",),
            taxonomy_version=versioning.TAXONOMY_VERSION,
        )
        for value in (
            "财付通-微信支付-东方花园物业",
            "财付通-微信支付-中土基物业",
        ):
            resolved = self.runtime.resolve_transaction_fields(
                {"remark": value},
                profile,
            )
            self.assertEqual(
                resolved["semantic"]["concept_id"],
                "property_management",
            )
            self.assertEqual(
                resolved["semantic"]["concept_resolution_source"],
                "exact_alias",
            )

    def test_relation_47_strong_and_06_not_unconditional(self):
        relation_47 = self.runtime.relations.approved(
            "47",
            "property_management",
        )
        self.assertIsNotNone(relation_47)
        self.assertEqual(relation_47.relevance, "strong")
        self.assertIsNone(
            self.runtime.relations.approved(
                "06",
                "property_management",
            )
        )
        profile = IndustryProfile(
            primary_industry_ids=("47", "06"),
            taxonomy_version=versioning.TAXONOMY_VERSION,
        )
        resolved_47 = self.runtime.relation_resolver.resolve(
            industry_id="47",
            concept_id="property_management",
            profile=profile,
        )
        self.assertEqual(resolved_47.relevance, "strong")
        resolved_06 = self.runtime.relation_resolver.resolve(
            industry_id="06",
            concept_id="property_management",
            profile=profile,
        )
        self.assertEqual(resolved_06.relevance, "undetermined")
        self.assertEqual(
            resolved_06.relation_resolution_source,
            "unresolved",
        )

    def test_relation_id_deterministic_snapshot(self):
        first = _relation_id(
            self.runtime,
            "47",
            "property_management",
            "strong",
        )
        second = _relation_id(
            self.runtime,
            "47",
            "property_management",
            "strong",
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("rel-"))


class VersionDeltaTests(unittest.TestCase):
    def test_versions_bumped_and_schema_unchanged(self):
        self.assertEqual(
            versioning.KNOWLEDGE_VERSION,
            "business-semantic-kb-v3",
        )
        self.assertEqual(
            versioning.SEMANTIC_KB_VERSION,
            "semantic-concepts-v3",
        )
        self.assertEqual(
            versioning.RELATION_KB_VERSION,
            "industry-relations-v2",
        )
        self.assertEqual(
            versioning.ALIAS_KB_VERSION,
            "semantic-aliases-v3",
        )
        self.assertEqual(
            versioning.RESOLVER_VERSION,
            "knowledge-v1-resolver-3",
        )
        self.assertEqual(
            versioning.PROMPT_SEMANTIC_CONCEPT_VERSION,
            "semantic-concept-v3",
        )
        from bankflow_v2.result_export import SCHEMA_VERSION

        self.assertEqual(SCHEMA_VERSION, "1.17")


if __name__ == "__main__":
    unittest.main()
