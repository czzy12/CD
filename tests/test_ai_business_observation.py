import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.ai_business_observation import (
    AI_PROMPT_VERSION,
    build_ai_business_observation,
)
from bankflow_v2.models import Transaction


def business_tx(
    transaction_id: str,
    *,
    counterparty_name: str = "",
    purpose: str = "",
) -> Transaction:
    transaction = Transaction(
        datetime(2026, 1, 2),
        income=Decimal("1000"),
        transaction_id=transaction_id,
        source_file_id="source:bank",
        evidence_locator="page=1;row=2",
        counterparty_name=counterparty_name,
        purpose=purpose,
    )
    if counterparty_name:
        transaction.field_confidence["counterparty_name"] = 1.0
    if purpose:
        transaction.field_confidence["purpose"] = 1.0
    return transaction


def case_context() -> dict[str, object]:
    return {
        "search_context": {
            "work_units": ["河南省润恒环保工程有限公司"],
            "declared_industries": ["环保工程"],
        }
    }


def cao_case_context() -> dict[str, object]:
    return {
        "search_context": {
            "work_units": ["河南省润恒环保工程有限公司"],
            "declared_industries": ["建筑材料批发投资"],
        },
        "business_context": {
            "declared_work_description": "建筑材料批发投资",
            "declared_work_status": "declared_unverified",
            "company_name": "河南省润恒环保工程有限公司",
            "confirmed_primary_business": "",
            "confirmed_products_or_services": "",
            "confirmation_status": "unconfirmed",
            "effective_primary_business": "建筑材料批发投资",
            "effective_products_or_services": "",
            "ai_business_relevance_eligible": True,
            "eligibility_reason": "explicit_declared_work_description",
        },
    }


class AiBusinessObservationTests(unittest.TestCase):
    def test_company_name_only_does_not_call_evaluator(self):
        calls = []
        context = {
            "search_context": {
                "work_units": ["新疆汇品建安商贸有限公司"],
                "declared_industries": [],
            },
            "business_context": {
                "declared_work_description": "",
                "company_name": "新疆汇品建安商贸有限公司",
                "confirmed_primary_business": "",
                "confirmation_status": "unconfirmed",
                "ai_business_relevance_eligible": False,
                "eligibility_reason": (
                    "business_context_confirmation_required"
                ),
                "confirmation_reason": "company_name_only",
            },
        }

        observation = build_ai_business_observation(
            [business_tx("tx:one", purpose="材料采购")],
            context,
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "provider": "test-provider",
                "model": "test-model",
                "api_key_available": True,
                "allow_business_names": True,
            },
            evaluator=lambda payload: calls.append(payload),
        )

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["reason"],
            "business_context_confirmation_required",
        )
        self.assertEqual(calls, [])

    def test_sends_confirmed_business_separately_from_company_name(self):
        captured = {}
        context = {
            "search_context": {
                "work_units": ["示例商贸有限公司"],
                "declared_industries": [],
            },
            "business_context": {
                "declared_work_description": "",
                "declared_work_status": "unavailable",
                "declared_work_source": "",
                "declared_work_source_ref": "",
                "company_name": "示例商贸有限公司",
                "confirmed_primary_business": "货物运输",
                "confirmed_products_or_services": "普通货物道路运输",
                "confirmation_status": "confirmed",
                "effective_primary_business": "货物运输",
                "effective_products_or_services": "普通货物道路运输",
                "ai_business_relevance_eligible": True,
                "eligibility_reason": "confirmed_primary_business",
            },
        }

        def evaluator(payload):
            captured.update(payload)
            return [{
                "transaction_id": "tx:one",
                "semantic_judgement": "medium",
                "reason": "用途与人工确认的运输业务相关，需复核",
                "used_fields": ["purpose"],
            }]

        observation = build_ai_business_observation(
            [business_tx("tx:one", purpose="运输服务费")],
            context,
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "provider": "test-provider",
                "model": "test-model",
                "api_key_available": True,
                "allow_business_names": True,
            },
            evaluator=evaluator,
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            captured["business_context"]["confirmed_primary_business"],
            "货物运输",
        )
        self.assertEqual(
            captured["business_context"][
                "confirmed_products_or_services"
            ],
            "普通货物道路运输",
        )
        self.assertEqual(
            captured["business_context"]["declared_work_units"],
            ["示例商贸有限公司"],
        )
        self.assertEqual(
            captured["business_context"]["company_name_context_role"],
            "auxiliary_only",
        )
        self.assertFalse(
            any(
                "护栏" in instruction or "塑木" in instruction
                for instruction in captured["instructions"]
            )
        )

    def test_defaults_to_authorization_missing_without_calling_evaluator(self):
        calls = []

        observation = build_ai_business_observation(
            [business_tx("tx:one", purpose="五金采购")],
            case_context(),
            evaluator=lambda payload: calls.append(payload),
        )

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["reason"],
            "ai_data_authorization_missing",
        )
        self.assertEqual(calls, [])

    def test_keeps_exact_declared_unit_match_as_deterministic_candidate(self):
        observation = build_ai_business_observation(
            [
                business_tx(
                    "tx:direct",
                    counterparty_name="河南省润恒环保工程有限公司",
                )
            ],
            case_context(),
        )

        candidate = observation["value"]["deterministic_candidates"][0]
        self.assertEqual(candidate["classification"], "directly_related")
        self.assertEqual(candidate["transaction_id"], "tx:direct")
        self.assertEqual(candidate["decision_source"], "deterministic_exact_match")

    def test_accepts_only_traceable_structured_evaluator_result(self):
        captured = {}

        def evaluator(payload):
            captured.update(payload)
            return [{
                "transaction_id": "tx:possible",
                "semantic_judgement": "medium",
                "reason": "用途字段出现五金采购，需要结合申报业务人工复核",
                "used_fields": ["purpose"],
            }]

        observation = build_ai_business_observation(
            [business_tx("tx:possible", purpose="五金采购")],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "test-provider",
                "model": "test-model",
            },
            evaluator=evaluator,
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["ai_candidates"][0]["classification"],
            "possibly_related",
        )
        self.assertNotIn("source_file", str(captured))
        self.assertNotIn("counterparty_account", str(captured))
        self.assertEqual(
            observation["parameters"]["model"],
            "test-model",
        )

    def test_rejects_fabricated_transaction_or_field_reference(self):
        observation = build_ai_business_observation(
            [business_tx("tx:possible", purpose="五金采购")],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "test-provider",
                "model": "test-model",
            },
            evaluator=lambda payload: [{
                "transaction_id": "tx:fabricated",
                "semantic_judgement": "strong",
                "reason": "虚构",
                "used_fields": ["不存在字段"],
            }],
        )

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(observation["value"]["reason"], "ai_response_invalid")
        self.assertEqual(
            observation["value"]["failure_detail"],
            "item_1:transaction_id_unknown",
        )
        self.assertEqual(observation["value"]["ai_candidates"], [])

    def test_rejects_partial_response_that_leaves_input_unclassified(self):
        observation = build_ai_business_observation(
            [
                business_tx("tx:one", purpose="五金采购"),
                business_tx("tx:two", purpose="设备维护"),
            ],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "test-provider",
                "model": "test-model",
            },
            evaluator=lambda payload: [{
                "transaction_id": "tx:one",
                "semantic_judgement": "medium",
                "reason": "仅返回一笔",
                "used_fields": ["purpose"],
            }],
        )

        self.assertEqual(observation["value"]["reason"], "ai_response_invalid")
        self.assertEqual(
            observation["value"]["failure_detail"],
            "coverage:response_item_missing",
        )

    def test_reports_provider_unavailable_after_authorization(self):
        observation = build_ai_business_observation(
            [business_tx("tx:possible", purpose="五金采购")],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "test-provider",
                "model": "test-model",
            },
        )

        self.assertEqual(observation["value"]["reason"], "ai_provider_unavailable")

    def test_reports_missing_api_key_after_authorization(self):
        observation = build_ai_business_observation(
            [business_tx("tx:possible", purpose="五金采购")],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": False,
            },
        )

        self.assertEqual(observation["value"]["reason"], "ai_api_key_missing")

    def test_discards_ai_candidates_when_provider_times_out(self):
        def timeout(_payload):
            raise TimeoutError

        observation = build_ai_business_observation(
            [business_tx("tx:possible", purpose="五金采购")],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=timeout,
        )

        self.assertEqual(observation["value"]["reason"], "ai_provider_failed")
        self.assertEqual(observation["value"]["ai_candidates"], [])

    def test_does_not_send_generic_transaction_type_only(self):
        row = Transaction(
            datetime(2026, 1, 2),
            income=Decimal("1000"),
            transaction_id="tx:generic",
            source_file_id="source:bank",
            transaction_type="二维码收款",
        )
        row.field_confidence["transaction_type"] = 1.0
        calls = []

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: calls.append(payload),
        )

        self.assertEqual(
            observation["value"]["reason"],
            "ai_input_candidates_unavailable",
        )
        self.assertEqual(observation["value"]["ai_input_candidate_count"], 0)
        self.assertEqual(calls, [])

    def test_keeps_informative_business_name_with_generic_transaction_type(self):
        row = Transaction(
            datetime(2026, 1, 2),
            expense=Decimal("2000"),
            transaction_id="tx:wine-shop",
            source_file_id="source:bank",
            counterparty_name="金乡县明清酒水经营部",
            transaction_type="商户消费",
        )
        row.field_confidence.update({
            "counterparty_name": 1.0,
            "transaction_type": 1.0,
        })
        captured = {}
        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: (
                captured.update(payload)
                or [{
                    "transaction_id": "tx:wine-shop",
                    "semantic_judgement": "medium",
                    "reason": "企业名称包含酒水经营，需要结合用途人工复核",
                    "used_fields": ["counterparty_name"],
                }]
            ),
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(observation["value"]["ai_input_candidate_count"], 1)
        self.assertEqual(
            captured["transactions"][0]["fields"]["counterparty_name"],
            "金乡县明清酒水经营部",
        )
        self.assertNotIn(
            "transaction_type",
            captured["transactions"][0]["fields"],
        )

    def test_does_not_send_generic_bank_summary_only(self):
        row = Transaction(
            datetime(2026, 1, 2),
            expense=Decimal("2000"),
            transaction_id="tx:bank-transfer",
            source_file_id="source:bank",
            summary="8跨行4汇款",
        )
        row.field_confidence["summary"] = 1.0

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: [],
        )

        self.assertEqual(
            observation["value"]["reason"],
            "ai_input_candidates_unavailable",
        )

    def test_does_not_send_generic_summary_with_informative_business_name(self):
        row = Transaction(
            datetime(2026, 1, 2),
            expense=Decimal("2000"),
            transaction_id="tx:business-transfer",
            source_file_id="source:bank",
            counterparty_name="宜城市杭艺建材厂",
            summary="8跨行4汇款",
        )
        row.field_confidence.update({
            "counterparty_name": 1.0,
            "summary": 1.0,
        })
        captured = {}

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: (
                captured.update(payload)
                or [{
                    "transaction_id": "tx:business-transfer",
                    "semantic_judgement": "medium",
                    "reason": "建材属于具体行业产品，需人工复核用途",
                    "used_fields": ["counterparty_name"],
                }]
            ),
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            captured["transactions"][0]["fields"],
            {"counterparty_name": "宜城市杭艺建材厂"},
        )

    def test_does_not_send_opaque_alphanumeric_remark_with_business_name(self):
        row = Transaction(
            datetime(2026, 1, 2),
            income=Decimal("2000"),
            transaction_id="tx:opaque-remark",
            source_file_id="source:bank",
            counterparty_name="贵州荣盛（集团）建材有限公司",
            remark="M0EEHDNH",
        )
        row.field_confidence.update({
            "counterparty_name": 1.0,
            "remark": 1.0,
        })
        captured = {}

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: (
                captured.update(payload)
                or [{
                    "transaction_id": "tx:opaque-remark",
                    "semantic_judgement": "medium",
                    "reason": "建材名称与申报行业相关，但无具体用途",
                    "used_fields": ["counterparty_name"],
                }]
            ),
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            captured["transactions"][0]["fields"],
            {"counterparty_name": "贵州荣盛（集团）建材有限公司"},
        )

    def test_rejects_direct_classification_based_only_on_business_name(self):
        row = Transaction(
            datetime(2026, 1, 2),
            expense=Decimal("2000"),
            transaction_id="tx:environment-company",
            source_file_id="source:bank",
            counterparty_name="合肥景硕环保科技有限公司",
        )
        row.field_confidence["counterparty_name"] = 1.0

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: [{
                "transaction_id": "tx:environment-company",
                "semantic_judgement": "strong",
                "reason": "企业名称包含环保",
                "used_fields": ["counterparty_name"],
            }],
        )

        self.assertEqual(observation["value"]["reason"], "ai_response_invalid")

    def test_accepts_direct_classification_with_explicit_project_remark(self):
        row = Transaction(
            datetime(2026, 1, 2),
            income=Decimal("3500"),
            transaction_id="tx:project-material",
            source_file_id="source:bank",
            counterparty_name="石泉县房屋建设有限责任公司",
            remark="环境治理项目材料费",
        )
        row.field_confidence.update({
            "counterparty_name": 1.0,
            "remark": 1.0,
        })

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: [{
                "transaction_id": "tx:project-material",
                "semantic_judgement": "strong",
                "reason": "备注明确为环境治理项目材料费",
                "used_fields": ["counterparty_name", "remark"],
            }],
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["ai_candidates"][0]["classification"],
            "directly_related",
        )
        self.assertEqual(
            observation["value"]["ai_candidates"][0]["evidence_strength"],
            "strong",
        )

    def test_accepts_generic_company_as_structured_weak_hint(self):
        row = Transaction(
            datetime(2026, 1, 2),
            income=Decimal("786"),
            transaction_id="tx:trade-company",
            source_file_id="source:bank",
            counterparty_name="黔西南州宇辉贸易有限公司",
            remark="货款",
        )
        row.field_confidence.update({
            "counterparty_name": 1.0,
            "remark": 1.0,
        })

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: [{
                "transaction_id": "tx:trade-company",
                "semantic_judgement": "weak",
                "reason": "贸易公司和货款仅作为弱提示，缺少具体产品或用途",
                "used_fields": ["counterparty_name", "remark"],
            }],
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["ai_candidates"][0]["evidence_strength"],
            "weak",
        )

    def test_specific_product_takes_priority_over_generic_goods_payment(self):
        row = Transaction(
            datetime(2026, 1, 2),
            income=Decimal("25000"),
            transaction_id="tx:building-materials",
            source_file_id="source:bank",
            counterparty_name="江山市杰成建材有限公司",
            remark="货款",
        )
        row.field_confidence.update({
            "counterparty_name": 1.0,
            "remark": 1.0,
        })
        captured = {}

        observation = build_ai_business_observation(
            [row],
            cao_case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_available": True,
            },
            evaluator=lambda payload: (
                captured.update(payload)
                or [{
                    "transaction_id": "tx:building-materials",
                    "semantic_judgement": "medium",
                    "reason": "建材是具体产品类别，货款不削弱该语义",
                    "used_fields": ["counterparty_name", "remark"],
                }]
            ),
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(captured["prompt_version"], AI_PROMPT_VERSION)
        self.assertEqual(AI_PROMPT_VERSION, "business-relevance-mvp-v11")
        self.assertTrue(
            any(
                "货款不得覆盖或削弱" in instruction
                for instruction in captured["instructions"]
            )
        )
        self.assertTrue(
            any(
                "园林景观设计属于具体相关产品或服务" in instruction
                for instruction in captured["instructions"]
            )
        )
        self.assertTrue(
            any(
                "泛化用途而没有具体课题" in instruction
                for instruction in captured["instructions"]
            )
        )
        self.assertEqual(
            observation["value"]["ai_candidates"][0]["evidence_strength"],
            "medium",
        )

    def test_aggregates_multiple_item_failures_without_adopting_partial_round(self):
        rows = [
            business_tx("tx:invalid-class", purpose="五金采购"),
            business_tx(
                "tx:name-only",
                counterparty_name="示例建材有限公司",
            ),
            business_tx("tx:valid", purpose="环境治理项目材料费"),
        ]

        observation = build_ai_business_observation(
            rows,
            case_context(),
            ai_config={
                "enabled": True,
                "data_authorized": True,
                "retention_policy_confirmed": True,
                "allow_business_names": True,
                "provider": "test-provider",
                "model": "test-model",
                "api_key_available": True,
            },
            evaluator=lambda payload: [
                {
                    "transaction_id": "tx:invalid-class",
                    "semantic_judgement": "相关",
                    "reason": "非法分类",
                    "used_fields": ["purpose"],
                },
                {
                    "transaction_id": "tx:name-only",
                    "semantic_judgement": "strong",
                    "reason": "只使用企业名称",
                    "used_fields": ["counterparty_name"],
                },
                {
                    "transaction_id": "tx:valid",
                    "semantic_judgement": "strong",
                    "reason": "备注明确为环境治理项目材料费",
                    "used_fields": ["purpose"],
                },
            ],
        )

        value = observation["value"]
        self.assertFalse(value["available"])
        self.assertEqual(value["reason"], "ai_response_invalid")
        self.assertEqual(value["ai_candidates"], [])
        self.assertEqual(len(value["provisional_ai_candidates"]), 1)
        self.assertEqual(value["validation_failure_summary"]["total"], 2)
        self.assertEqual(
            value["validation_failure_summary"]["counts"],
            {
                "semantic_judgement_invalid": 1,
                "maximum_allowed_strength_exceeded": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
