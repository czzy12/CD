import unittest
from datetime import datetime, timedelta
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
    def test_cross_check_separates_automatic_and_display_only_fields(self):
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
        display_only = {
            item["check_type"]: item
            for item in cross_check["value"]["display_only_items"]
        }

        self.assertEqual(items["work_unit"]["status"], "direct_match")
        self.assertEqual(
            items["purchase_deposit_expense"]["status"],
            "candidate_match",
        )
        self.assertNotIn("residence_location", items)
        self.assertEqual(
            display_only["residence_location"]["handling"],
            "system_information_display_only",
        )
        self.assertIn("客户资料.txt", display_only["residence_location"]["source_refs"])
        self.assertIn("tx:unit", items["work_unit"]["evidence_transaction_ids"])
        self.assertEqual(
            items["purchase_deposit_expense"]["evidence_transaction_ids"],
            ["tx:purchase"],
        )
        self.assertEqual(
            cross_check["parameters"]["automatic_comparison_scope"],
            [
                "work_unit",
                "declared_industry",
                "purchase_deposit_expense",
            ],
        )
        self.assertEqual(cross_check["parameters"]["purchase_direction"], "expense")
        self.assertIn(
            "declared_industry",
            cross_check["value"]["missing_automatic_fields"],
        )
        self.assertEqual(
            cross_check["value"]["searched_sources"][0][
                "observed_period_start"
            ],
            "2026-01-09T10:00:00",
        )

    def test_markdown_contains_boundaries_and_evidence(self):
        rows = [
            transaction("tx:unit", counterparty_name="甲装修工程有限公司"),
            transaction("tx:purchase", counterparty_name="重庆问界汽车销售有限公司", expense="10000"),
        ]
        case = context()
        result = build_bankflow_result(rows, case_context=case)
        markdown = render_mvp_markdown(result, case)
        question_observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "manual_verification_questions"
        )
        question_types = {
            question["question_type"]
            for question in question_observation["value"]["questions"]
        }

        self.assertIn("# 流水核查 MVP 验收报告：测试客户", markdown)
        self.assertIn("申报与流水对照", markdown)
        self.assertIn("系统信息（仅展示）", markdown)
        self.assertIn("自动对照搜索范围", markdown)
        self.assertIn("工作地点和住家地址留待后续生活轨迹模块共同对照", markdown)
        self.assertIn("下定定金支出", markdown)
        self.assertIn("人工核实事项与需关注提示", markdown)
        self.assertIn("只作参考，不是风险结论、评分或准入意见", markdown)
        self.assertIn("tx:purchase", markdown)
        self.assertIn("counterparty_name=重庆问界汽车销售有限公司", markdown)
        self.assertIn("expense", markdown)
        self.assertIn("不输出欺诈、包装、资金来源、实际控制、通过或拒绝结论", markdown)
        self.assertIn("purchase_deposit_expense", question_types)
        self.assertNotIn("work_location", question_types)
        self.assertNotIn("residence_location", question_types)
        self.assertTrue(
            all(
                question["reference_only"]
                for question in question_observation["value"]["questions"]
            )
        )

    def test_purchase_cross_check_only_accepts_expense_candidate(self):
        incoming = Transaction(
            datetime(2026, 1, 9, 10),
            income=Decimal("10000"),
            transaction_id="tx:incoming",
            source_file_id="source:wechat",
            source_file="wechat.pdf",
            evidence_locator="page=3;row=2",
            counterparty_name="重庆问界汽车销售有限公司",
        )
        incoming.field_confidence["counterparty_name"] = 1.0
        case = context()
        result = build_bankflow_result([incoming], case_context=case)
        cross_check = build_declaration_flow_cross_check(
            [incoming],
            case,
            result["result"]["observations"],
        )
        items = {
            item["check_type"]: item
            for item in cross_check["value"]["items"]
        }

        self.assertEqual(
            items["purchase_deposit_expense"]["status"],
            "no_evidence_in_reliable_fields",
        )
        self.assertEqual(
            items["purchase_deposit_expense"]["evidence_transaction_ids"],
            [],
        )
        question_observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "manual_verification_questions"
        )
        self.assertNotIn(
            "purchase_deposit_expense",
            {
                question["question_type"]
                for question in question_observation["value"]["questions"]
            },
        )

    def test_purchase_cross_check_rejects_unrelated_vehicle_payment(self):
        unrelated_purchase = transaction(
            "tx:unrelated-purchase",
            counterparty_name="其他汽车销售有限公司",
            expense="493000",
        )
        unrelated_purchase.purpose = "购车款"
        unrelated_purchase.field_confidence["purpose"] = 1.0
        case = context()
        result = build_bankflow_result([unrelated_purchase], case_context=case)
        cross_check = build_declaration_flow_cross_check(
            [unrelated_purchase],
            case,
            result["result"]["observations"],
        )
        items = {
            item["check_type"]: item
            for item in cross_check["value"]["items"]
        }

        self.assertEqual(
            items["purchase_deposit_expense"]["status"],
            "no_evidence_in_reliable_fields",
        )
        self.assertEqual(
            items["purchase_deposit_expense"]["evidence_transaction_ids"],
            [],
        )

    def test_declared_completed_purchase_without_flow_creates_question(self):
        case = build_case_context(
            "已下定测试",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：测试客户\n"
                    "购买车型：问界M9\n"
                    "下定人及试驾情况：本人已下定\n"
                ),
            }],
        )
        unrelated = transaction(
            "tx:ordinary",
            counterparty_name="普通便利店",
            expense="20",
        )
        result = build_bankflow_result([unrelated], case_context=case)
        question_observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "manual_verification_questions"
        )
        deposit_question = next(
            question
            for question in question_observation["value"]["questions"]
            if question["question_type"] == "purchase_deposit_expense"
        )

        self.assertEqual(deposit_question["evidence_transaction_ids"], [])
        self.assertEqual(deposit_question["source_file_ids"], ["source:wechat"])
        self.assertEqual(
            deposit_question["source_scope"],
            "all_declaration_search_sources",
        )
        self.assertIn("系统资料显示已下定", deposit_question["question_text"])
        self.assertFalse(deposit_question["attention_hint_only"])

    def test_display_only_locations_do_not_generate_questions(self):
        case = build_case_context(
            "仅地点展示测试",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：测试客户\n"
                    "工作单位详细地址：郑州市二七区示例路1号\n"
                    "家庭住址：郑州市金水区示例路2号\n"
                    "上牌地：郑州\n"
                ),
            }],
        )
        ordinary = transaction(
            "tx:ordinary-small",
            counterparty_name="普通便利店",
            expense="20",
        )
        result = build_bankflow_result([ordinary], case_context=case)
        question_observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "manual_verification_questions"
        )

        self.assertFalse(question_observation["value"]["available"])
        self.assertEqual(question_observation["value"]["questions"], [])
        self.assertTrue(
            question_observation["parameters"][
                "display_only_fields_do_not_trigger_questions"
            ]
        )

    def test_markdown_shows_large_transaction_and_balance_path_evidence(self):
        start = datetime(2026, 1, 10, 10)
        inflow = Transaction(
            start,
            income=Decimal("100000"),
            balance=Decimal("105000"),
            transaction_id="tx:large-inflow",
            source_file_id="source:bank",
            source_file="bank.pdf",
            evidence_locator="page=1;row=1",
            counterparty_name="甲公司",
        )
        inflow.field_confidence["counterparty_name"] = 1.0
        outflow = Transaction(
            start + timedelta(hours=2),
            expense=Decimal("95000"),
            balance=Decimal("10000"),
            transaction_id="tx:split-outflow",
            source_file_id="source:bank",
            source_file="bank.pdf",
            evidence_locator="page=1;row=2",
            purpose="货款",
        )
        outflow.field_confidence["purpose"] = 1.0
        case = {"case_id": "资金路径测试", "search_context": {}}

        result = build_bankflow_result([inflow, outflow], case_context=case)
        markdown = render_mvp_markdown(result, case)
        question_observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "manual_verification_questions"
        )
        low_retention_question = next(
            question
            for question in question_observation["value"]["questions"]
            if question["question_type"] == "large_inflow_short_term_outflow"
        )

        self.assertIn("大额交易清单", markdown)
        self.assertIn("请确认相关大额入账的性质及随后支出的实际用途", markdown)
        self.assertIn("需关注（仅供参考）", markdown)
        self.assertIn("tx:large-inflow", markdown)
        self.assertIn("1/3/7 日收入后支出时间共现", markdown)
        self.assertIn("| 1日 | 1 | 1 | 1 |", markdown)
        self.assertIn("大额入账后 1/3/7 日路径", markdown)
        self.assertIn("累计支出95000.00（95.00%）", markdown)
        self.assertIn("日末余额10000.00", markdown)
        self.assertIn("留存增量5.00%", markdown)
        self.assertIn("tx:split-outflow", markdown)
        self.assertIn("max(窗口日末余额-入账前余额, 0)÷入账额", markdown)
        self.assertIn("目标日无交易时沿用此前最近余额快照", markdown)
        self.assertIn("fund_source_attribution=false", markdown)
        self.assertIn("不计算或断言某笔资金实际停留时长", markdown)
        self.assertTrue(low_retention_question["attention_hint_only"])
        self.assertTrue(low_retention_question["reference_only"])
        self.assertFalse(
            question_observation["parameters"]["risk_or_admission_conclusion"]
        )

    def test_markdown_reports_missing_source_id_for_large_inflow_path(self):
        inflow = Transaction(
            datetime(2026, 1, 10, 10),
            income=Decimal("30000"),
            balance=Decimal("30000"),
            transaction_id="tx:missing-source",
            source_file_id="",
            source_file="bank.pdf",
            evidence_locator="page=1;row=1",
        )
        case = {"case_id": "来源缺失测试", "search_context": {}}

        markdown = render_mvp_markdown(
            build_bankflow_result([inflow], case_context=case),
            case,
        )

        self.assertIn("大额入账缺少可靠来源文件ID，不能构造同来源路径", markdown)

    def test_markdown_reports_partially_unavailable_large_inflow_paths(self):
        start = datetime(2026, 1, 10, 10)
        usable = Transaction(
            start,
            income=Decimal("30000"),
            balance=Decimal("30000"),
            transaction_id="tx:usable",
            source_file_id="source:bank",
            source_file="bank.pdf",
            evidence_locator="page=1;row=1",
        )
        unavailable = Transaction(
            start + timedelta(days=1),
            income=Decimal("40000"),
            balance=Decimal("40000"),
            transaction_id="tx:missing-source",
            source_file_id="",
            source_file="unknown.pdf",
            evidence_locator="page=1;row=1",
        )
        case = {"case_id": "部分来源缺失测试", "search_context": {}}

        markdown = render_mvp_markdown(
            build_bankflow_result(
                [usable, unavailable],
                case_context=case,
            ),
            case,
        )

        self.assertIn("3万元以上入账路径：1 笔", markdown)
        self.assertIn(
            "另有 1 笔达到3万元阈值的入账因缺少可靠来源文件ID未构造路径",
            markdown,
        )

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
        self.assertIn(
            "已搜索可靠标准文字字段，未发现敏感词组命中",
            no_hit_markdown,
        )
        self.assertIn(
            "没有可用于敏感词组搜索的可靠标准文字字段",
            unavailable_markdown,
        )

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

    def test_markdown_shows_monthly_change_balance_and_interest_details(self):
        rows = []
        for month in range(1, 7):
            row = Transaction(
                datetime(2026, month, 10, 9),
                income=Decimal(month * 100),
                expense=Decimal(month * 10),
                balance=Decimal(month * 1000),
                transaction_id=f"tx:month-{month}",
                source_file_id="source:bank",
                source_file="bank.pdf",
                evidence_locator=f"page={month};row=1",
            )
            rows.append(row)
        rows[2].summary = "结息"
        rows[2].field_confidence["summary"] = 1.0
        rows[5].summary = "利息"
        rows[5].field_confidence["summary"] = 1.0
        case = {"case_id": "余额结息测试", "search_context": {}}

        markdown = render_mvp_markdown(
            build_bankflow_result(rows, case_context=case),
            case,
        )

        self.assertIn("月度收入连续性与收支变化", markdown)
        self.assertIn("数据期月份：6；有收入月份：6", markdown)
        self.assertIn("月均收入 350.00 元，月均支出 35.00 元", markdown)
        self.assertIn("| 收入（2026-01至2026-03 对 2026-04至2026-06）", markdown)
        self.assertIn("| 600.00 | 1500.00 | 900.00 | 150.00% |", markdown)
        self.assertIn("日末余额与结息", markdown)
        self.assertIn("tx:month-3", markdown)
        self.assertIn("2026-Q1", markdown)
        self.assertIn("2026-Q2", markdown)
        self.assertIn("较上一列示季度变化", markdown)
        self.assertIn("不是日均余额", markdown)
        self.assertIn("不能据此反推平均存款本金", markdown)

    def test_markdown_shows_complete_sensitive_context_and_search_scope(self):
        first = Transaction(
            datetime(2026, 1, 2, 10),
            expense=Decimal("1000"),
            transaction_id="tx:sensitive-one",
            source_file_id="source:bank",
            source_file="bank.pdf",
            evidence_locator="page=1;row=1",
            purpose="信用卡套现还款",
            counterparty_name="甲金融服务公司",
        )
        first.field_confidence["purpose"] = 1.0
        first.field_confidence["counterparty_name"] = 1.0
        second = Transaction(
            datetime(2026, 2, 3, 11),
            expense=Decimal("200"),
            transaction_id="tx:sensitive-two",
            source_file_id="source:bank",
            source_file="bank.pdf",
            evidence_locator="page=2;row=1",
            summary="法院司法缴费",
        )
        second.field_confidence["summary"] = 1.0
        case = {"case_id": "敏感上下文测试", "search_context": {}}

        result = build_bankflow_result([first, second], case_context=case)
        markdown = render_mvp_markdown(result, case)
        question_observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "manual_verification_questions"
        )
        sensitive_questions = [
            question
            for question in question_observation["value"]["questions"]
            if question["question_type"] == "sensitive_transaction_context"
        ]

        self.assertIn("敏感交易关键词及上下文", markdown)
        self.assertIn("敏感词组候选：2 笔", markdown)
        self.assertIn("2026-01-02T10:00:00 至 2026-02-03T11:00:00", markdown)
        self.assertIn("2/2", markdown)
        self.assertIn("purpose=信用卡套现还款", markdown)
        self.assertIn("counterparty_name=甲金融服务公司", markdown)
        self.assertIn("summary=法院司法缴费", markdown)
        self.assertIn("tx:sensitive-one page=1;row=1", markdown)
        self.assertIn("tx:sensitive-two page=2;row=1", markdown)
        self.assertIn("不冒充原件声明期间", markdown)
        self.assertIn("不表示真实借贷、抵押、诉讼、医疗事实", markdown)
        self.assertEqual(len(sensitive_questions), 1)
        self.assertEqual(
            sensitive_questions[0]["evidence_transaction_ids"],
            ["tx:sensitive-one", "tx:sensitive-two"],
        )
        self.assertTrue(sensitive_questions[0]["attention_hint_only"])

    def test_markdown_masks_phone_embedded_in_sensitive_context(self):
        row = Transaction(
            datetime(2026, 1, 2, 10),
            expense=Decimal("100"),
            transaction_id="tx:phone",
            source_file_id="source:wechat",
            source_file="wechat.pdf",
            evidence_locator="page=1;row=1",
            counterparty_name="王律师℡1 3609990661",
        )
        row.field_confidence["counterparty_name"] = 1.0
        case = {"case_id": "敏感号码脱敏测试", "search_context": {}}

        markdown = render_mvp_markdown(
            build_bankflow_result([row], case_context=case),
            case,
        )

        self.assertIn("王律师℡手机号已隐藏", markdown)
        self.assertNotIn("1 3609990661", markdown)

    def test_markdown_summarizes_traceable_evidence_without_expanding_all_rows(self):
        row = transaction(
            "tx:traceable",
            counterparty_name="甲公司",
        )
        row.page_no = 3
        row.row_no = 2
        result = build_bankflow_result([row])

        markdown = render_mvp_markdown(
            result,
            {"case_id": "证据索引测试", "search_context": {}},
        )

        self.assertIn("## 9. 可追溯交易证据", markdown)
        self.assertIn("证据链状态：完整", markdown)
        self.assertIn("已建立唯一索引：1 笔", markdown)
        self.assertIn("结构化结果保留交易ID到 original_transactions 的索引", markdown)
        self.assertIn("## 10. 重要提示", markdown)


if __name__ == "__main__":
    unittest.main()
