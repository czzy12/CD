import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.case_context import (
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.models import Transaction
from bankflow_v2.mvp_report import (
    build_declaration_flow_cross_check,
    render_mvp_markdown,
)
from bankflow_v2.result_export import build_bankflow_result


def transaction(
    transaction_id: str,
    *,
    counterparty_name: str,
    expense: str = "10",
) -> Transaction:
    row = Transaction(
        datetime(2026, 1, 9, 10),
        expense=Decimal(expense),
        transaction_id=transaction_id,
        source_file_id="source:wechat",
        source_file="wechat.pdf",
        evidence_locator="page=3;row=2",
        counterparty_name=counterparty_name,
    )
    row.field_confidence["counterparty_name"] = 1.0
    return row


def context() -> dict[str, object]:
    return build_case_context(
        "测试客户",
        [{
            "source_ref": "客户资料.txt",
            "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
            "text": (
                "客户姓名：测试客户\n"
                "工作单位全称：甲装修工程有限公司\n"
                "家庭住址：河南省郑州市二七区\n"
                "购买车型：问界M9\n"
                "下定人及试驾情况：本人微信下定\n"
            ),
        }],
    )


class MvpReportTests(unittest.TestCase):
    def test_cross_check_distinguishes_direct_candidate_and_no_evidence(self):
        rows = [
            transaction("tx:unit", counterparty_name="甲装修工程有限公司"),
            transaction("tx:purchase", counterparty_name="重庆问界汽车销售有限公司", expense="10000"),
        ]
        case = context()
        result = build_bankflow_result(rows, case_context=case)
        cross_check = build_declaration_flow_cross_check(
            rows,
            case,
            result["result"]["observations"],
        )
        items = {item["check_type"]: item for item in cross_check["value"]["items"]}

        self.assertEqual(items["work_unit"]["status"], "direct_match")
        self.assertEqual(items["purchase"]["status"], "candidate_match")
        self.assertEqual(items["residence_location"]["status"], "no_evidence_in_reliable_fields")
        self.assertIn("tx:unit", items["work_unit"]["evidence_transaction_ids"])

    def test_markdown_contains_boundaries_and_evidence(self):
        rows = [
            transaction("tx:unit", counterparty_name="甲装修工程有限公司"),
            transaction("tx:purchase", counterparty_name="重庆问界汽车销售有限公司", expense="10000"),
        ]
        case = context()
        result = build_bankflow_result(rows, case_context=case)
        markdown = render_mvp_markdown(result, case)

        self.assertIn("# 流水核查 MVP 验收报告：测试客户", markdown)
        self.assertIn("申报与流水对照", markdown)
        self.assertIn("tx:purchase", markdown)
        self.assertIn("counterparty_name=重庆问界汽车销售有限公司", markdown)
        self.assertIn("expense", markdown)
        self.assertIn("不输出欺诈、包装、资金来源、实际控制、通过或拒绝结论", markdown)

    def test_markdown_distinguishes_no_keyword_hit_from_unavailable_fields(self):
        case = context()
        reliable_unrelated = transaction(
            "tx:unrelated",
            counterparty_name="普通百货商店",
        )
        no_hit_result = build_bankflow_result(
            [reliable_unrelated],
            case_context={
                "case_id": "无动态购车词",
                "search_context": {},
            },
        )
        no_hit_markdown = render_mvp_markdown(
            no_hit_result,
            {"case_id": "无动态购车词"},
        )

        unavailable = transaction(
            "tx:unavailable",
            counterparty_name="普通百货商店",
        )
        unavailable.field_confidence.clear()
        unavailable_result = build_bankflow_result(
            [unavailable],
            case_context={"case_id": "字段不可用", "search_context": {}},
        )
        unavailable_markdown = render_mvp_markdown(
            unavailable_result,
            {"case_id": "字段不可用"},
        )

        self.assertIn("可靠标准文字字段内未发现受控关键词", no_hit_markdown)
        self.assertIn("没有可用于关键词搜索的可靠标准文字字段", unavailable_markdown)

    def test_markdown_counterparty_table_has_coverage_and_evidence(self):
        row = transaction(
            "tx:counterparty",
            counterparty_name="甲公司",
            expense="100",
        )
        case = {"case_id": "对手测试", "search_context": {}}
        markdown = render_mvp_markdown(
            build_bankflow_result([row], case_context=case),
            case,
        )

        self.assertIn("可识别对手金额覆盖", markdown)
        self.assertIn("占可识别金额", markdown)
        self.assertIn("证据交易ID", markdown)
        self.assertIn("tx:counterparty", markdown)
        self.assertIn("没有收入交易", markdown)


if __name__ == "__main__":
    unittest.main()
