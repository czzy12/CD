"""Local Markdown rendering for a guarded AI sample acceptance run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from decimal import Decimal

from .models import Transaction


CLASSIFICATION_LABELS = {
    "directly_related": "直接相关",
    "possibly_related": "可能相关",
    "no_relation_evidence": "未发现关联依据",
    "undetermined": "无法判断",
}


def _cell(value: object) -> str:
    return str(value or "").replace("|", "／").replace("\r", " ").replace("\n", " ")


def _amount(transaction: Transaction) -> tuple[str, Decimal]:
    if transaction.income > 0:
        return "收入", transaction.income
    if transaction.expense > 0:
        return "支出", transaction.expense
    return "中性", Decimal("0.00")


def render_ai_sample_markdown(
    *,
    case_name: str,
    provider: str,
    model: str,
    eligible_count: int,
    sampled_transactions: list[Transaction],
    observation: Mapping[str, object],
) -> str:
    value = observation.get("value", {})
    if not isinstance(value, Mapping):
        value = {}
    candidates = value.get("ai_candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    counts = Counter(
        str(candidate.get("classification", ""))
        for candidate in candidates
        if isinstance(candidate, Mapping)
    )
    strength_counts = Counter(
        str(candidate.get("evidence_strength", ""))
        for candidate in candidates
        if isinstance(candidate, Mapping)
    )
    transaction_by_id = {
        transaction.transaction_id: transaction
        for transaction in sampled_transactions
    }

    lines = [
        f"# {case_name} AI经营关联小批量验收",
        "",
        "## 运行摘要",
        "",
        f"- 提供方：{_cell(provider)}",
        f"- 模型：{_cell(model)}",
        f"- 可送入AI的唯一语义候选总数：{eligible_count}",
        f"- 本次均匀抽样：{len(sampled_transactions)}",
        f"- 有效模型结果：{len(candidates)}",
        f"- 运行状态：{'成功' if value.get('available') else '未采用'}",
        f"- 未采用原因：{_cell(value.get('reason')) or '无'}",
        "",
        "## 抽样来源",
        "",
    ]
    source_counts = Counter(
        (transaction.bank, transaction.source_file)
        for transaction in sampled_transactions
    )
    for (bank, source_file), count in sorted(source_counts.items()):
        lines.append(
            f"- {_cell(bank)} / {_cell(source_file)}：{count}笔"
        )
    lines.extend(
        [
            "",
        "## 分类汇总",
        "",
        ]
    )
    for classification in (
        "directly_related",
        "possibly_related",
        "no_relation_evidence",
        "undetermined",
    ):
        lines.append(
            f"- {CLASSIFICATION_LABELS[classification]}：{counts[classification]}"
        )
    lines.extend(
        [
            f"- 强证据：{strength_counts['strong']}",
            f"- 中等候选：{strength_counts['medium']}",
            f"- 弱提示：{strength_counts['weak']}",
            "",
            "## 逐笔结果",
            "",
            "| 日期 | 方向 | 金额 | 使用字段及原文 | AI分类 | 证据强度 | 理由 | 证据定位 |",
            "| --- | --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        transaction = transaction_by_id.get(str(candidate.get("transaction_id", "")))
        if transaction is None:
            continue
        direction, amount = _amount(transaction)
        used_fields = candidate.get("used_fields", [])
        if not isinstance(used_fields, list):
            used_fields = []
        field_text = "；".join(
            f"{field_name}={_cell(getattr(transaction, str(field_name), ''))}"
            for field_name in used_fields
        )
        classification = str(candidate.get("classification", ""))
        lines.append(
            "| "
            + " | ".join(
                [
                    transaction.transaction_time.strftime("%Y-%m-%d"),
                    direction,
                    f"{amount:.2f}",
                    field_text,
                    CLASSIFICATION_LABELS.get(classification, classification),
                    _cell(candidate.get("evidence_strength")),
                    _cell(candidate.get("reason")),
                    _cell(transaction.evidence_locator),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 使用边界",
            "",
            "- 本次只抽取一个小批次，不代表完整流水的行业关联分布。",
            "- AI结果仅为人工复核候选，不表示真实经营、欺诈、包装、准入或拒绝结论。",
            "- 输入不含身份证、电话、账号、本地路径或PDF页面；疑似个人交易对手名称不发送。",
            "- 任一请求失败、超时、格式不合格、虚构字段或漏项时，本批模型结果整体不采用。",
        ]
    )
    return "\n".join(lines)
