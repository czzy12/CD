import json
import tempfile
import unittest
from pathlib import Path

from bankflow_v2.ai_business_observation import build_classification_constraints
from bankflow_v2.deepseek_adapter import (
    DeepSeekEvaluator,
    DeepSeekProviderError,
    DeepSeekSettings,
    load_deepseek_runtime,
    load_deepseek_settings,
)


def payload(count: int) -> dict[str, object]:
    return {
        "task_type": "business_relevance",
        "prompt_version": "test-v1",
        "business_context": {"declared_industries": ["装修"]},
        "allowed_classifications": [
            "directly_related",
            "possibly_related",
            "no_relation_evidence",
            "undetermined",
        ],
        "allowed_model_judgements": [
            "strong",
            "medium",
            "weak",
            "none",
            "undetermined",
        ],
        "transactions": [
            {
                "transaction_id": f"tx:{index}",
                "fields": {"purpose": f"材料采购{index}"},
                "classification_constraints": build_classification_constraints(
                    {"purpose": f"材料采购{index}"}
                ),
            }
            for index in range(count)
        ],
    }


def provider_response(transaction_ids: list[str]) -> bytes:
    results = [
        {
            "transaction_id": transaction_id,
            "semantic_judgement": "medium",
            "reason": "用途字段需要人工复核",
            "used_fields": ["purpose"],
        }
        for transaction_id in transaction_ids
    ]
    content = json.dumps({"results": results}, ensure_ascii=False)
    return json.dumps(
        {"choices": [{"message": {"content": content}}]},
        ensure_ascii=False,
    ).encode("utf-8")


class DeepSeekAdapterTests(unittest.TestCase):
    def test_loads_explicit_environment_without_exposing_key_in_repr(self):
        settings = load_deepseek_settings(
            {
                "BANKFLOW_AI_API_KEY": "secret-key",
                "BANKFLOW_AI_ENABLED": "true",
                "BANKFLOW_AI_DATA_AUTHORIZED": "1",
                "BANKFLOW_AI_RETENTION_CONFIRMED": "yes",
                "BANKFLOW_AI_ALLOW_BUSINESS_NAMES": "on",
                "BANKFLOW_AI_TIMEOUT_SECONDS": "12.5",
                "BANKFLOW_AI_BATCH_SIZE": "20",
            }
        )

        self.assertTrue(settings.enabled)
        self.assertTrue(settings.data_authorized)
        self.assertTrue(settings.retention_policy_confirmed)
        self.assertTrue(settings.allow_business_names)
        self.assertEqual(settings.timeout_seconds, 12.5)
        self.assertEqual(settings.batch_size, 20)
        self.assertNotIn("secret-key", repr(settings))

    def test_builds_official_compatible_json_request_and_batches(self):
        calls = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            ids = [
                item["transaction_id"]
                for item in user_payload["transactions"]
            ]
            calls.append((url, request, dict(headers), timeout, ids))
            return provider_response(ids)

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(
                api_key="secret-key",
                enabled=True,
                data_authorized=True,
                retention_policy_confirmed=True,
                batch_size=2,
                timeout_seconds=15,
            ),
            transport,
        )

        result = evaluator(payload(3))

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(calls[0][1]["model"], "deepseek-v4-flash")
        self.assertEqual(
            calls[0][1]["response_format"],
            {"type": "json_object"},
        )
        self.assertEqual(calls[0][1]["thinking"], {"type": "disabled"})
        self.assertEqual(calls[0][3], 15)
        self.assertEqual([item["transaction_id"] for item in result["results"]], [
            "tx:0",
            "tx:1",
            "tx:2",
        ])

    def test_sends_per_transaction_direct_classification_constraint(self):
        captured = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            captured.extend(user_payload["transactions"])
            response = json.loads(
                provider_response(
                    [
                        item["transaction_id"]
                        for item in user_payload["transactions"]
                    ]
                ).decode("utf-8")
            )
            content = json.loads(response["choices"][0]["message"]["content"])
            content["results"][0]["used_fields"] = ["counterparty_name"]
            response["choices"][0]["message"]["content"] = json.dumps(
                content,
                ensure_ascii=False,
            )
            return json.dumps(response, ensure_ascii=False).encode("utf-8")

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key"),
            transport,
        )
        constrained_payload = payload(2)
        constrained_payload["transactions"][0]["fields"] = {
            "counterparty_name": "王先生生鲜超市",
        }
        constrained_payload["transactions"][0][
            "classification_constraints"
        ] = build_classification_constraints(
            constrained_payload["transactions"][0]["fields"]
        )
        constrained_payload["transactions"][1]["fields"] = {
            "purpose": "材料采购",
        }
        constrained_payload["transactions"][1][
            "classification_constraints"
        ] = build_classification_constraints(
            constrained_payload["transactions"][1]["fields"]
        )

        evaluator(constrained_payload)

        self.assertEqual(
            captured[0]["classification_constraints"],
            {
                "directly_related_allowed": False,
                "directly_related_evidence_fields": [],
                "maximum_allowed_strength": "none",
                "deterministic_non_business_category": "convenience_store",
            },
        )
        self.assertEqual(
            captured[1]["classification_constraints"],
            {
                "directly_related_allowed": True,
                "directly_related_evidence_fields": ["purpose"],
                "maximum_allowed_strength": "strong",
                "deterministic_non_business_category": "",
            },
        )

    def test_classifies_duplicate_semantic_fields_once_and_expands_results(self):
        calls = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            ids = [
                item["transaction_id"]
                for item in user_payload["transactions"]
            ]
            calls.append(ids)
            return provider_response(ids)

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key"),
            transport,
        )
        duplicated = payload(2)
        duplicated["transactions"][1]["fields"] = dict(
            duplicated["transactions"][0]["fields"]
        )
        duplicated["transactions"][1]["classification_constraints"] = dict(
            duplicated["transactions"][0]["classification_constraints"]
        )

        result = evaluator(duplicated)

        self.assertEqual(calls, [["tx:0"]])
        self.assertEqual(
            [item["transaction_id"] for item in result["results"]],
            ["tx:0", "tx:1"],
        )

    def test_reuses_signature_when_only_generic_summaries_differ(self):
        calls = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            ids = [
                item["transaction_id"]
                for item in user_payload["transactions"]
            ]
            calls.append(ids)
            return provider_response(ids)

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key"),
            transport,
        )
        duplicated = payload(2)
        duplicated["transactions"][0]["fields"] = {
            "purpose": "材料采购",
            "summary": "转账",
        }
        duplicated["transactions"][0][
            "classification_constraints"
        ] = build_classification_constraints(
            duplicated["transactions"][0]["fields"]
        )
        duplicated["transactions"][1]["fields"] = {
            "purpose": "材料采购",
            "summary": "跨行汇款",
        }
        duplicated["transactions"][1][
            "classification_constraints"
        ] = build_classification_constraints(
            duplicated["transactions"][1]["fields"]
        )

        result = evaluator(duplicated)

        self.assertEqual(calls, [["tx:0"]])
        self.assertEqual(
            [item["transaction_id"] for item in result["results"]],
            ["tx:0", "tx:1"],
        )

    def test_full_case_reuses_337_signatures_in_seven_batches(self):
        calls = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            ids = [
                item["transaction_id"]
                for item in user_payload["transactions"]
            ]
            calls.append(ids)
            return provider_response(ids)

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key", batch_size=50),
            transport,
        )
        full_payload = payload(1180)
        for index, item in enumerate(full_payload["transactions"]):
            item["fields"] = {"purpose": f"材料采购{index % 337}"}
            item["classification_constraints"] = build_classification_constraints(
                item["fields"]
            )

        result = evaluator(full_payload)

        self.assertEqual(len(calls), 7)
        self.assertEqual(sum(len(batch) for batch in calls), 337)
        self.assertEqual(len(result["results"]), 1180)
        self.assertEqual(
            {item["transaction_id"] for item in result["results"]},
            {f"tx:{index}" for index in range(1180)},
        )

    def test_rejects_non_json_provider_content(self):
        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key"),
            lambda url, body, headers, timeout: json.dumps(
                {"choices": [{"message": {"content": "not-json"}}]}
            ).encode("utf-8"),
        )

        result = evaluator(payload(1))

        self.assertEqual(result["results"], [])
        self.assertEqual(
            result["validation_failures"][0]["reason"],
            "provider_json_invalid",
        )

    def test_collects_invalid_items_and_continues_later_batches(self):
        calls = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            ids = [
                item["transaction_id"]
                for item in user_payload["transactions"]
            ]
            calls.append(ids)
            response = json.loads(provider_response(ids).decode("utf-8"))
            if len(calls) == 2:
                content = json.loads(
                    response["choices"][0]["message"]["content"]
                )
                content["results"][0]["semantic_judgement"] = "相关"
                response["choices"][0]["message"]["content"] = json.dumps(
                    content,
                    ensure_ascii=False,
                )
            return json.dumps(response, ensure_ascii=False).encode("utf-8")

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key", batch_size=2),
            transport,
        )

        result = evaluator(payload(5))

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(result["results"]), 4)
        self.assertEqual(len(result["validation_failures"]), 1)
        self.assertEqual(
            result["validation_failures"][0]["location"],
            "batch_2:item_1",
        )
        self.assertEqual(
            result["validation_failures"][0]["reason"],
            "semantic_judgement_invalid",
        )

    def test_caches_raw_response_and_replays_without_provider_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = []

            def transport(url, body, headers, timeout):
                request = json.loads(body.decode("utf-8"))
                user_payload = json.loads(request["messages"][1]["content"])
                ids = [
                    item["transaction_id"]
                    for item in user_payload["transactions"]
                ]
                calls.append(ids)
                return provider_response(ids)

            settings = DeepSeekSettings(
                api_key="secret-key",
                model="test-model",
            )
            first = DeepSeekEvaluator(
                settings,
                transport,
                cache_dir=temp_dir,
            )(payload(2))
            second = DeepSeekEvaluator(
                settings,
                lambda *_args: self.fail("provider should not be called"),
                cache_dir=temp_dir,
                replay_only=True,
            )(payload(2))
            changed_ids = payload(2)
            changed_ids["transactions"][0]["transaction_id"] = "tx:new-0"
            changed_ids["transactions"][1]["transaction_id"] = "tx:new-1"
            replayed_with_new_ids = DeepSeekEvaluator(
                settings,
                lambda *_args: self.fail("provider should not be called"),
                cache_dir=temp_dir,
                replay_only=True,
            )(changed_ids)

            self.assertEqual(calls, [["tx:0", "tx:1"]])
            self.assertEqual(len(first["results"]), 2)
            self.assertEqual(len(second["results"]), 2)
            self.assertEqual(second["cache_hit_count"], 2)
            self.assertEqual(second["cache_miss_count"], 0)
            self.assertEqual(second["cache_replay_mismatch_count"], 0)
            self.assertEqual(second["provider_call_count"], 0)
            self.assertEqual(
                [
                    item["transaction_id"]
                    for item in replayed_with_new_ids["results"]
                ],
                ["tx:new-0", "tx:new-1"],
            )
            cache_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(temp_dir).rglob("*.json")
            )
            self.assertNotIn("secret-key", cache_text)
            self.assertIn("raw_response", cache_text)
            self.assertIn('"task_type": "business_relevance"', cache_text)

    def test_prompt_change_invalidates_signature_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = []

            def transport(url, body, headers, timeout):
                request = json.loads(body.decode("utf-8"))
                user_payload = json.loads(request["messages"][1]["content"])
                ids = [
                    item["transaction_id"]
                    for item in user_payload["transactions"]
                ]
                calls.append(ids)
                return provider_response(ids)

            evaluator = DeepSeekEvaluator(
                DeepSeekSettings(api_key="secret-key", model="test-model"),
                transport,
                cache_dir=temp_dir,
            )
            first_payload = payload(1)
            evaluator(first_payload)
            changed = payload(1)
            changed["prompt_version"] = "test-v2"
            evaluator(changed)

            self.assertEqual(calls, [["tx:0"], ["tx:0"]])

    def test_task_type_change_invalidates_signature_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = []

            def transport(url, body, headers, timeout):
                request = json.loads(body.decode("utf-8"))
                user_payload = json.loads(request["messages"][1]["content"])
                ids = [
                    item["transaction_id"]
                    for item in user_payload["transactions"]
                ]
                calls.append(ids)
                return provider_response(ids)

            evaluator = DeepSeekEvaluator(
                DeepSeekSettings(api_key="secret-key", model="test-model"),
                transport,
                cache_dir=temp_dir,
            )
            evaluator(payload(1))
            changed = payload(1)
            changed["task_type"] = "life_trajectory"
            evaluator(changed)

            self.assertEqual(calls, [["tx:0"], ["tx:0"]])

    def test_replay_only_reports_cache_miss_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = DeepSeekEvaluator(
                DeepSeekSettings(api_key="", model="test-model"),
                lambda *_args: self.fail("provider should not be called"),
                cache_dir=temp_dir,
                replay_only=True,
            )(payload(1))

            self.assertEqual(result["results"], [])
            self.assertEqual(
                result["validation_failures"][0]["reason"],
                "cache_miss",
            )
            self.assertEqual(result["cache_hit_count"], 0)
            self.assertEqual(result["cache_miss_count"], 1)
            self.assertEqual(result["provider_call_count"], 0)

    def test_provider_system_error_still_stops_remaining_batches(self):
        calls = []

        def transport(url, body, headers, timeout):
            request = json.loads(body.decode("utf-8"))
            user_payload = json.loads(request["messages"][1]["content"])
            ids = [
                item["transaction_id"]
                for item in user_payload["transactions"]
            ]
            calls.append(ids)
            if len(calls) == 2:
                raise DeepSeekProviderError("authentication failed")
            return provider_response(ids)

        evaluator = DeepSeekEvaluator(
            DeepSeekSettings(api_key="secret-key", batch_size=2),
            transport,
        )

        with self.assertRaises(DeepSeekProviderError):
            evaluator(payload(5))
        self.assertEqual(len(calls), 2)

    def test_runtime_does_not_create_evaluator_without_key(self):
        config, evaluator = load_deepseek_runtime(
            {
                "BANKFLOW_AI_ENABLED": "true",
                "BANKFLOW_AI_DATA_AUTHORIZED": "true",
                "BANKFLOW_AI_RETENTION_CONFIRMED": "true",
            }
        )

        self.assertIsNone(evaluator)
        self.assertFalse(config["api_key_available"])

    def test_runtime_stays_disabled_by_default(self):
        config, evaluator = load_deepseek_runtime({})

        self.assertFalse(config["enabled"])
        self.assertFalse(config["data_authorized"])
        self.assertIsNone(evaluator)


if __name__ == "__main__":
    unittest.main()
