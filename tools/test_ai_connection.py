"""Test the configured AI provider with synthetic, non-customer data."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.deepseek_adapter import (
    DeepSeekProviderError,
    load_deepseek_runtime,
    load_deepseek_settings,
)


def main() -> int:
    settings = load_deepseek_settings()
    _, evaluator = load_deepseek_runtime()
    print(f"provider=deepseek")
    print(f"model={settings.model}")
    print(f"base_url={settings.base_url}")
    print(f"enabled={settings.enabled}")
    print(f"data_authorized={settings.data_authorized}")
    print(f"retention_confirmed={settings.retention_policy_confirmed}")
    print(f"api_key_available={bool(settings.api_key)}")
    if evaluator is None:
        print("connection=not_attempted")
        print("reason=configuration_or_authorization_incomplete")
        return 2

    payload = {
        "prompt_version": "connection-test-v1",
        "business_context": {
            "declared_industries": ["环保工程"],
            "declared_work_units": ["示例环保工程有限公司"],
        },
        "allowed_classifications": [
            "directly_related",
            "possibly_related",
            "no_relation_evidence",
            "undetermined",
        ],
        "instructions": [
            "仅处理虚构示例数据。",
            "证据不足时使用 undetermined。",
        ],
        "transactions": [
            {
                "transaction_id": "connection:test",
                "transaction_month": "2026-01",
                "direction": "expense",
                "amount": "1000.00",
                "fields": {"purpose": "环保设备采购"},
            }
        ],
    }
    try:
        response = evaluator(payload)
    except DeepSeekProviderError:
        print("connection=failed")
        print("reason=provider_request_or_response_invalid")
        return 1
    except Exception:
        print("connection=failed")
        print("reason=unexpected_provider_failure")
        return 1

    if (
        not isinstance(response, list)
        or len(response) != 1
        or response[0].get("transaction_id") != "connection:test"
    ):
        print("connection=failed")
        print("reason=response_contract_invalid")
        return 1
    print("connection=ok")
    print("synthetic_result_received=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
