import unittest

from bankflow_v2.case_context import (
    SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION,
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)


class CaseContextTests(unittest.TestCase):
    def test_stops_system_copy_at_manual_analysis_boundary(self):
        context = build_case_context(
            "任如冰",
            [{
                "source_ref": "任如冰.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "姓名:任如冰\n"
                    "工作单位全称：汇诚名烟名酒\n"
                    "下定人及试驾情况：本人微信下定，已试驾\n"
                    "本人分析：\n"
                    "工作单位全称：不应读取\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["customer_names"], ["任如冰"])
        self.assertEqual(context["search_context"]["work_units"], ["汇诚名烟名酒"])
        self.assertEqual(
            context["fields"]["purchase_declaration"][0]["source_role"],
            SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION,
        )
        self.assertNotIn("不应读取", str(context))

    def test_stops_when_manual_analysis_is_on_same_line_as_heading(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "示例.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：示例\n"
                    "个人分析：客户可能从事烟酒经营\n"
                    "主营业务：烟酒经营\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["customer_names"], ["示例"])
        self.assertEqual(context["search_context"]["declared_industries"], [])
        self.assertNotIn("客户可能从事烟酒经营", str(context))

    def test_stops_at_company_opinion_without_analysis_heading(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "示例.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：示例\n"
                    "公司意见：建议进一步核查其家具销售情况\n"
                    "主营业务：家具销售\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["customer_names"], ["示例"])
        self.assertEqual(context["search_context"]["declared_industries"], [])
        self.assertNotIn("建议进一步核查", str(context))

    def test_stops_at_generic_opinion_section(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "示例.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：示例\n"
                    "意见：疑似从事家具销售\n"
                    "主营业务：家具销售\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["customer_names"], ["示例"])
        self.assertEqual(context["search_context"]["declared_industries"], [])
        self.assertNotIn("疑似从事家具销售", str(context))

    def test_does_not_consume_unknown_labeled_field_as_previous_value(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "示例.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "职务：\n"
                    "生活轨迹：仅为人工分析内容\n"
                    "工作单位全称：示例公司\n"
                ),
            }],
        )

        self.assertNotIn("job_title", context["fields"])
        self.assertNotIn("仅为人工分析内容", str(context))
        self.assertEqual(context["search_context"]["work_units"], ["示例公司"])

    def test_normalizes_practice_customer_work_unit_labels(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "示例.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "工作单位名称：示例销售公司\n"
                    "工作单位地址（精确到门牌号）：示例路1号\n"
                ),
            }],
        )

        self.assertEqual(
            context["search_context"]["work_units"],
            ["示例销售公司"],
        )
        self.assertEqual(
            context["search_context"]["work_locations"],
            ["示例路1号"],
        )

    def test_normalizes_repeated_credit_section_name_without_losing_excerpt(self):
        context = build_case_context(
            "韩鹏飞",
            [{
                "source_ref": "韩鹏飞.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名:韩鹏飞（新疆国物能源产业发展有限公司）\n"
                    "#征信\n"
                    "姓名：韩鹏飞，总负债0，月289\n"
                    "个人分析：\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["customer_names"], ["韩鹏飞"])
        self.assertIn("总负债0", context["fields"]["customer_name"][1]["source_excerpt"])

    def test_reads_alternating_system_page_copy_and_keeps_manager_description_unverified(self):
        context = build_case_context(
            "曹国民",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：\n曹国民\n"
                    "购买车型：\n问界M9 增程Ultra 六座\n"
                    "工作单位全称：\n河南省润恒环保工程有限公司\n"
                    "家庭住址：\n郑州市二七区秀水湾\n"
                    "工作介绍及收入情况（是否和流水匹配）：\n"
                    "客户主要是做建筑材料批发投资的，还有其他生意，信用卡用于日常消费\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["customer_names"], ["曹国民"])
        self.assertEqual(
            context["search_context"]["work_units"],
            ["河南省润恒环保工程有限公司"],
        )
        self.assertEqual(
            context["fields"]["manager_work_income_description"][0]["source_role"],
            SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION,
        )
        self.assertEqual(
            context["fields"]["manager_work_income_description"][0]["verification_status"],
            "unverified",
        )
        self.assertEqual(
            context["search_context"]["declared_industries"],
            ["建筑材料批发投资"],
        )
        self.assertEqual(
            context["fields"]["declared_industry"][0]["source_role"],
            SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION,
        )
        self.assertEqual(
            context["fields"]["declared_industry"][0]["verification_status"],
            "unverified",
        )
        self.assertNotIn("其他生意", context["search_context"]["declared_industries"])
        self.assertNotIn("信用卡", context["search_context"]["declared_industries"])
        self.assertEqual(
            context["business_context"]["declared_work_description"],
            "建筑材料批发投资",
        )
        self.assertTrue(
            context["business_context"]["ai_business_relevance_eligible"]
        )

    def test_does_not_turn_non_work_manager_notes_into_industry_context(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：示例\n"
                    "工作介绍及收入情况（是否和流水匹配）：\n"
                    "信用卡消费是日常消费，微信体现居住地\n"
                ),
            }],
        )

        self.assertEqual(context["search_context"]["declared_industries"], [])

    def test_builds_traceable_declared_work_context(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：示例\n"
                    "工作单位全称：示例商贸有限公司\n"
                    "工作介绍及收入情况（是否和流水匹配）：建筑材料批发\n"
                ),
            }],
        )

        business = context["business_context"]
        self.assertEqual(
            business["declared_work_description"],
            "建筑材料批发",
        )
        self.assertEqual(
            business["declared_work_source"],
            "工作介绍及收入情况（是否和流水匹配）",
        )
        self.assertEqual(
            business["declared_work_source_ref"],
            "客户资料.txt",
        )
        self.assertEqual(
            business["declared_work_status"],
            "declared_unverified",
        )
        self.assertEqual(business["company_name"], "示例商贸有限公司")
        self.assertTrue(business["ai_business_relevance_eligible"])
        self.assertEqual(
            business["eligibility_reason"],
            "explicit_declared_work_description",
        )

    def test_company_name_only_requires_business_confirmation(self):
        context = build_case_context(
            "李娟",
            [{
                "source_ref": "李娟.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "客户姓名：李娟\n"
                    "工作单位全称：新疆汇品建安商贸有限公司\n"
                    "工作介绍及收入情况（是否和流水匹配）：是\n"
                ),
            }],
        )

        business = context["business_context"]
        self.assertEqual(business["declared_work_description"], "")
        self.assertEqual(
            business["company_name"],
            "新疆汇品建安商贸有限公司",
        )
        self.assertFalse(business["ai_business_relevance_eligible"])
        self.assertEqual(
            business["eligibility_reason"],
            "business_context_confirmation_required",
        )
        self.assertEqual(
            business["confirmation_reason"],
            "company_name_only",
        )
        self.assertEqual(business["confirmation_status"], "unconfirmed")

    def test_manual_confirmation_is_separate_and_has_priority(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "工作单位全称：示例科技有限公司\n"
                    "工作介绍及收入情况（是否和流水匹配）：做生意\n"
                ),
            }],
            business_confirmation={
                "confirmed_primary_business": "货物运输",
                "confirmed_products_or_services": "普通货物道路运输",
                "confirmation_note": "客户现场确认",
                "confirmation_status": "confirmed",
            },
        )

        business = context["business_context"]
        self.assertEqual(business["declared_work_description"], "")
        self.assertEqual(
            business["confirmed_primary_business"],
            "货物运输",
        )
        self.assertEqual(
            business["confirmed_products_or_services"],
            "普通货物道路运输",
        )
        self.assertEqual(
            business["effective_primary_business"],
            "货物运输",
        )
        self.assertTrue(business["ai_business_relevance_eligible"])
        self.assertEqual(
            business["eligibility_reason"],
            "confirmed_primary_business",
        )

    def test_confirmed_status_requires_primary_business(self):
        with self.assertRaisesRegex(
            ValueError,
            "confirmed_primary_business",
        ):
            build_case_context(
                "示例",
                [{
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：示例商贸有限公司",
                }],
                business_confirmation={
                    "confirmation_status": "confirmed",
                },
            )

    def test_multiple_declared_work_descriptions_require_confirmation(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "主营业务：烟酒经营\n"
                    "工作介绍及收入情况（是否和流水匹配）：货物运输\n"
                ),
            }],
        )

        business = context["business_context"]
        self.assertFalse(business["ai_business_relevance_eligible"])
        self.assertEqual(
            business["confirmation_reason"],
            "multiple_declared_work_descriptions",
        )
        self.assertCountEqual(
            business["declared_work_descriptions"],
            ["烟酒经营", "货物运输"],
        )

    def test_clear_company_and_work_description_conflict_requires_confirmation(self):
        context = build_case_context(
            "示例",
            [{
                "source_ref": "客户资料.txt",
                "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                "text": (
                    "工作单位全称：示例环保工程有限公司\n"
                    "工作介绍及收入情况（是否和流水匹配）：烟酒经营\n"
                ),
            }],
        )

        business = context["business_context"]
        self.assertFalse(business["ai_business_relevance_eligible"])
        self.assertEqual(
            business["confirmation_reason"],
            "company_description_conflict",
        )

    def test_keeps_risk_report_as_reported_narrative_not_confirmed_fields(self):
        context = build_case_context(
            "曹国民",
            [{
                "source_ref": "调查报告.txt",
                "source_role": SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
                "text": "微信流水（已验真）并分析：支付宝下定，郑州轨迹，建议推进",
            }],
        )

        self.assertEqual(context["fields"], {})
        self.assertEqual(context["narratives"][0]["source_role"], SOURCE_ROLE_RISK_INVESTIGATION_REPORT)
        self.assertEqual(context["narratives"][0]["verification_status"], "reported")

    def test_requires_explicit_source_role(self):
        with self.assertRaisesRegex(ValueError, "source_role"):
            build_case_context(
                "case",
                [{"source_ref": "资料.txt", "source_role": "unknown", "text": "姓名：甲"}],
            )


if __name__ == "__main__":
    unittest.main()
