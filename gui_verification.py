"""PyQt6 verification workbench for the schema 1.16 vertical slice."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from bankflow_v2.standard_result_view import (
    StandardResultError,
    evidence_transaction,
    manual_verification_questions,
    mask_account,
    observation_by_type,
    redact_sensitive_text,
    result_summary,
    sensitive_transaction_candidates,
    short_transaction_id,
    validate_standard_result,
)


class BriefTheme:
    BG = "#F3EDDF"
    SURFACE = "#FFF9EC"
    SURFACE_STRONG = "#FFF2CF"
    INK = "#171713"
    MUTED = "#6D685D"
    ORANGE = "#FF7A1A"
    MINT = "#16B88A"
    RED = "#E64A3B"
    YELLOW = "#F4C84A"
    BORDER = 2
    SHADOW = 5
    SPACING_XS = 8
    SPACING_SM = 12
    SPACING_MD = 16
    SPACING_LG = 24


def _money(value: object) -> str:
    try:
        return f"{Decimal(str(value or '0')):,.2f}"
    except (InvalidOperation, ValueError):
        return str(value or "0.00")


def _money_compact(value: object) -> tuple[str, str]:
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        text = str(value or "0.00")
        return text, text
    full = f"{amount:,.2f} 元"
    if abs(amount) >= Decimal("10000"):
        compact = f"{amount / Decimal('10000'):.2f}万"
    else:
        compact = f"{amount:,.2f}"
    return compact, full


_BUSINESS_REASON_LABELS = {
    "ai_data_authorization_missing": (
        "AI 未启用：本次分析未获得 GUI 明确授权，未调用模型"
    ),
    "ai_retention_policy_unconfirmed": "AI 留存策略未确认，未调用模型",
    "ai_provider_configuration_missing": "AI 提供方配置缺失",
    "ai_api_key_missing": "AI 密钥缺失",
    "ai_input_candidates_unavailable": "没有可供 AI 判断的可靠文字候选",
    "ai_provider_unavailable": "AI 服务不可用",
    "ai_provider_failed": "AI 服务调用失败",
    "ai_response_invalid": "AI 返回未通过证据校验",
    "case_business_context_unavailable": "缺少案件经营上下文",
    "business_context_confirmation_required": "经营上下文待人工确认",
}
_BUSINESS_CLASSIFICATION_LABELS = {
    "directly_related": "直接关联",
    "possibly_related": "可能关联",
    "no_relation_evidence": "未发现关联依据",
    "undetermined": "无法判断",
}
_BUSINESS_STRENGTH_LABELS = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "none": "无",
}


def _business_reason_label(reason: object) -> str:
    code = str(reason or "")
    return _BUSINESS_REASON_LABELS.get(code, code or "原始状态未提供")


BUSINESS_FILTER_LABELS = {
    "positive": "正向候选",
    "manual": "待人工判断",
    "excluded": "已排除 / 无关联",
    "all": "全部结果",
}


def _business_rows(
    result: Mapping[str, object],
    view_filter: str = "positive",
) -> list[dict[str, object]]:
    observation = observation_by_type(result, "ai_business_relevance_candidates")
    value = observation.get("value")
    if not isinstance(value, Mapping):
        return []
    rows: list[dict[str, object]] = []
    deterministic = value.get("deterministic_candidates", [])
    ai_candidates = value.get("ai_candidates", [])
    excluded = value.get("deterministic_non_business_candidates", [])

    if view_filter in {"positive", "all"} and isinstance(deterministic, list):
        rows.extend(
            {"source": "确定性文字/名称候选", "candidate": candidate}
            for candidate in deterministic
            if isinstance(candidate, Mapping)
        )
    if isinstance(ai_candidates, list):
        for candidate in ai_candidates:
            if not isinstance(candidate, Mapping):
                continue
            classification = str(candidate.get("classification") or "")
            strength = str(candidate.get("evidence_strength") or "")
            is_positive = strength in {"strong", "medium", "weak"}
            is_manual = classification == "undetermined"
            is_excluded = (
                strength == "none"
                or classification == "no_relation_evidence"
            ) and not is_manual
            if (
                view_filter == "all"
                or (view_filter == "positive" and is_positive)
                or (view_filter == "manual" and is_manual)
                or (view_filter == "excluded" and is_excluded)
            ):
                rows.append({"source": "AI 观察", "candidate": candidate})
    if view_filter in {"excluded", "all"} and isinstance(excluded, list):
        rows.extend(
            {"source": "确定性排除", "candidate": candidate}
            for candidate in excluded
            if isinstance(candidate, Mapping)
        )
    return rows


def _business_status_text(result: Mapping[str, object] | None) -> str:
    if result is None:
        return "等待标准结果。"
    observation = observation_by_type(result, "ai_business_relevance_candidates")
    value = observation.get("value")
    if not isinstance(value, Mapping):
        return "标准结果未包含经营关联观察。"
    deterministic = value.get("deterministic_candidates", [])
    ai_candidates = value.get("ai_candidates", [])
    excluded = value.get("deterministic_non_business_candidates", [])
    counts = (
        len(deterministic) if isinstance(deterministic, list) else 0,
        len(ai_candidates) if isinstance(ai_candidates, list) else 0,
        len(excluded) if isinstance(excluded, list) else 0,
    )
    summary = (
        f"确定性文字/企业名称候选 {counts[0]} 项 · AI 观察 {counts[1]} 项 · "
        f"确定性排除 {counts[2]} 项。"
    )
    if bool(value.get("available")):
        return f"{summary}\nAI 观察可用；所有结论仍需结合交易证据人工核实。"
    reason = _business_reason_label(value.get("reason"))
    confirmation = value.get("business_context_confirmation")
    prompt = (
        str(confirmation.get("prompt") or "")
        if isinstance(confirmation, Mapping)
        else ""
    )
    detail = f"AI 观察不可用：{reason}。已有确定性结果仍单独展示。"
    return f"{summary}\n{detail}" + (f"\n{redact_sensitive_text(prompt)}" if prompt else "")


def _direction_and_amount(transaction: Mapping[str, object]) -> tuple[str, str]:
    try:
        income = Decimal(str(transaction.get("income") or "0"))
        expense = Decimal(str(transaction.get("expense") or "0"))
    except InvalidOperation:
        return "未知", ""
    if income > 0:
        return "收入", _money(income)
    if expense > 0:
        return "支出", _money(expense)
    return "中性", "0.00"


def _indicator_by_type(
    result: Mapping[str, object],
    indicator_type: str,
) -> Mapping[str, object]:
    body = result.get("result", {})
    indicators = body.get("indicators", []) if isinstance(body, Mapping) else []
    for indicator in indicators if isinstance(indicators, list) else []:
        if (
            isinstance(indicator, Mapping)
            and indicator.get("indicator_type") == indicator_type
        ):
            return indicator
    return {}


def _percentage(value: object, digits: int = 1) -> str:
    if value in (None, ""):
        return "不可用"
    try:
        return f"{Decimal(str(value)) * 100:.{digits}f}%"
    except (InvalidOperation, ValueError):
        return "不可用"


def _sensitive_term_summary(
    candidates: object,
) -> str:
    counts: dict[str, int] = {}
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, Mapping):
            continue
        for term in {
            str(value)
            for value in candidate.get("matched_terms", [])
            if str(value)
        }:
            counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    rendered = [f"{term}{count}" for term, count in ranked[:3]]
    if len(ranked) > 3:
        rendered.append(f"其他受控词组{len(ranked) - 3}类")
    return "｜".join(rendered) or "当前无候选"


def _change_label(value: object) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "不可用"
    if amount > 0:
        return "上升"
    if amount < 0:
        return "下降"
    return "基本持平"


class HardShadowCard(QFrame):
    """Square editorial card with a painted hard shadow."""

    def __init__(self, accent: str = BriefTheme.SURFACE, parent: QWidget | None = None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        lift = 0 if self._hovered else 2
        shadow = BriefTheme.SHADOW + (2 if self._hovered else 0)
        body = QRect(
            lift,
            lift,
            max(0, self.width() - shadow - lift),
            max(0, self.height() - shadow - lift),
        )
        shadow_rect = body.translated(shadow, shadow)
        painter.fillRect(shadow_rect, QColor(BriefTheme.INK))
        painter.fillRect(body, self._accent)
        painter.setPen(QPen(QColor(BriefTheme.INK), BriefTheme.BORDER))
        painter.drawRect(body.adjusted(1, 1, -1, -1))
        super().paintEvent(event)


class BriefPageHeader(HardShadowCard):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(BriefTheme.SURFACE_STRONG, parent)
        self.setMinimumHeight(154)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 26, 22)
        layout.setSpacing(5)
        self.eyebrow = QLabel("// 流水核查工作台 · SCHEMA 1.16")
        self.eyebrow.setObjectName("briefEyebrow")
        self.title = QLabel("请选择客户资料目录")
        self.title.setObjectName("briefTitle")
        self.subtitle = QLabel("后台生成或直接加载标准结果后，可查看人工核实与敏感交易证据。")
        self.subtitle.setObjectName("briefSubtitle")
        self.subtitle.setWordWrap(True)
        self.facts = QLabel("资料期间、来源和交易笔数将在案件完成后显示。")
        self.facts.setObjectName("briefHeaderFacts")
        self.facts.setWordWrap(True)
        layout.addWidget(self.eyebrow)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.facts)

    def set_summary(
        self,
        case_name: str,
        period_start: str,
        period_end: str,
        status: str,
        source_count: object | None = None,
        transaction_count: object | None = None,
    ) -> None:
        self.title.setText(case_name)
        period = "覆盖期间不可用"
        if period_start or period_end:
            period = f"{str(period_start)[:10] or '未知'} → {str(period_end)[:10] or '未知'}"
        self.subtitle.setText(f"资料覆盖期间：{period}")
        facts = [f"分析状态：{status}"]
        if source_count is not None:
            facts.append(f"资料来源：{source_count} 个")
        if transaction_count is not None:
            facts.append(f"交易笔数：{transaction_count} 笔")
        self.facts.setText(" · ".join(facts))


class SummaryMetric(QFrame):
    def __init__(
        self,
        label: str,
        value: str = "0",
        tone: str = "plain",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("briefKeyMetricCell")
        self.setProperty("tone", tone)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(3)
        self.caption_label = QLabel(label)
        self.caption_label.setObjectName("briefMetricLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("briefMetricValue")
        self.value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.caption_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: object) -> None:
        text = str(value)
        self.value_label.setProperty("compact", len(text) > 10)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)
        self.value_label.setText(text)
        self.value_label.setToolTip(text)


class KeyMetricsPanel(HardShadowCard):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(BriefTheme.SURFACE, parent)
        self.setMinimumHeight(176)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 18, 18)
        outer.setSpacing(0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        outer.addLayout(self.grid)
        definitions = (
            ("source_count", "资料来源", "orange"),
            ("transaction_count", "交易笔数", "plain"),
            ("income_sum", "收入合计", "mint"),
            ("expense_sum", "支出合计", "strong"),
            ("manual_question_count", "人工核实", "yellow"),
            ("sensitive_candidate_count", "敏感候选", "orange"),
        )
        self.metrics: dict[str, SummaryMetric] = {
            key: SummaryMetric(label, "0", tone)
            for key, label, tone in definitions
        }
        self._columns = 0
        self._reflow(3)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        columns = 2 if width < 620 else 6 if width >= 1320 else 3
        self._reflow(columns)

    def _reflow(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for cell in self.metrics.values():
            self.grid.removeWidget(cell)
        for index, cell in enumerate(self.metrics.values()):
            self.grid.addWidget(cell, index // columns, index % columns)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)


KeyMetricCell = SummaryMetric


class SectionHeader(QWidget):
    def __init__(self, number: str, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 6)
        number_label = QLabel(f"// {number}")
        number_label.setObjectName("briefSectionNumber")
        title_label = QLabel(title)
        title_label.setObjectName("briefSectionTitle")
        layout.addWidget(number_label)
        layout.addWidget(title_label)
        layout.addStretch(1)


class FilterButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setObjectName("briefFilterButton")
        self.setMinimumHeight(42)


class StatusBadge(QLabel):
    def __init__(self, text: str = "不可用", tone: str = "muted"):
        super().__init__(text)
        self.setObjectName("briefStatusBadge")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_status(self, text: str, tone: str) -> None:
        self.setText(text)
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class AnalysisModuleCard(HardShadowCard):
    clicked = pyqtSignal(str)

    def __init__(
        self,
        module_key: str,
        title: str,
        parent: QWidget | None = None,
    ):
        super().__init__(BriefTheme.SURFACE, parent)
        self.module_key = module_key
        self.setMinimumHeight(148)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 22, 18)
        layout.setSpacing(5)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("briefCardTitle")
        self.primary_label = QLabel("不可用")
        self.primary_label.setObjectName("briefModuleValue")
        self.summary_label = QLabel("等待标准结果。")
        self.summary_label.setObjectName("briefCardText")
        self.summary_label.setWordWrap(True)
        self.status_label = QLabel("不可用")
        self.status_label.setObjectName("briefModuleStatus")
        self.status_label.setWordWrap(True)
        self.open_button = QPushButton("查看概要 →")
        self.open_button.clicked.connect(lambda: self.clicked.emit(self.module_key))
        layout.addWidget(self.title_label)
        layout.addWidget(self.primary_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight)

    def set_summary(
        self,
        primary: str,
        summary: str,
        status_text: str,
        tone: str = "muted",
    ) -> None:
        self.primary_label.setText(primary)
        self.summary_label.setText(summary)
        self.status_label.setText(status_text)
        self.status_label.setProperty("tone", tone)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class KeyFindingCard(HardShadowCard):
    clicked = pyqtSignal(str)
    secondaryClicked = pyqtSignal(str)

    def __init__(
        self,
        section_key: str,
        title: str,
        parent: QWidget | None = None,
    ):
        super().__init__(BriefTheme.SURFACE, parent)
        self.section_key = section_key
        self.setMinimumHeight(292)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 24, 22)
        layout.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("briefCardTitle")
        self.body_label = QLabel("等待标准结果。")
        self.body_label.setObjectName("briefCombinedCardText")
        self.body_label.setWordWrap(True)
        self.body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.status_label = QLabel("不可用")
        self.status_label.setObjectName("briefModuleStatus")
        self.status_label.setWordWrap(True)
        actions = QHBoxLayout()
        self.secondary_button = QPushButton("补充经营信息")
        self.secondary_button.clicked.connect(
            lambda: self.secondaryClicked.emit(self.section_key)
        )
        self.secondary_button.hide()
        self.open_button = QPushButton("查看概要 →")
        self.open_button.clicked.connect(
            lambda: self.clicked.emit(self.section_key)
        )
        actions.addWidget(self.secondary_button)
        actions.addStretch(1)
        actions.addWidget(self.open_button)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addLayout(actions)

    def set_content(
        self,
        body: str,
        status_text: str,
        tone: str = "muted",
        *,
        show_secondary: bool = False,
    ) -> None:
        self.body_label.setText(body)
        self.status_label.setText(status_text)
        self.status_label.setProperty("tone", tone)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.secondary_button.setVisible(show_secondary)


CombinedOverviewCard = KeyFindingCard


class CandidateCategoryButton(QPushButton):
    def __init__(
        self,
        text: str,
        category: str,
        parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self.category = category
        self.setObjectName("briefCandidateCategoryButton")


class AttentionItemCard(HardShadowCard):
    openRequested = pyqtSignal(str)

    def __init__(
        self,
        fact: str,
        verification: str,
        module_key: str,
        module_title: str,
        question_count: int,
        evidence_count: int,
        availability: str,
        parent: QWidget | None = None,
    ):
        super().__init__(BriefTheme.SURFACE, parent)
        self.module_key = module_key
        self.setMinimumHeight(154)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 22, 18)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.module_badge = StatusBadge(
            f"{module_title} · {question_count} 项待核实",
            "orange",
        )
        availability_tone = (
            "mint"
            if availability == "数据可用"
            else "orange" if availability == "部分数据可用" else "muted"
        )
        self.availability_badge = StatusBadge(
            availability,
            availability_tone,
        )
        top.addWidget(self.module_badge)
        top.addWidget(self.availability_badge)
        top.addStretch(1)
        self.fact_label = QLabel(f"客观触发事实：{fact}")
        self.fact_label.setObjectName("briefCardText")
        self.fact_label.setWordWrap(True)
        self.verification_label = QLabel(f"建议核实内容：{verification}")
        self.verification_label.setObjectName("briefCardText")
        self.verification_label.setWordWrap(True)
        bottom = QHBoxLayout()
        self.evidence_label = QLabel(f"对应证据：{evidence_count} 笔")
        self.evidence_label.setObjectName("briefPageNote")
        self.open_button = QPushButton("进入人工核实 →")
        self.open_button.clicked.connect(
            lambda: self.openRequested.emit("manual")
        )
        bottom.addWidget(self.evidence_label)
        bottom.addStretch(1)
        bottom.addWidget(self.open_button)
        layout.addLayout(top)
        layout.addWidget(self.fact_label)
        layout.addWidget(self.verification_label)
        layout.addLayout(bottom)


class EvidenceSummaryPanel(HardShadowCard):
    openRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(BriefTheme.SURFACE_STRONG, parent)
        self.setMinimumHeight(112)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 24, 20)
        layout.setSpacing(18)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        self.status_label = QLabel("证据待核验")
        self.status_label.setObjectName("briefCardTitle")
        self.detail_label = QLabel("等待标准结果。")
        self.detail_label.setObjectName("briefCardText")
        self.detail_label.setWordWrap(True)
        copy.addWidget(self.status_label)
        copy.addWidget(self.detail_label)
        layout.addLayout(copy, 1)
        self.open_button = QPushButton("打开证据中心 →")
        self.open_button.clicked.connect(self.openRequested)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_evidence(
        self,
        complete: bool,
        indexed_transactions: object,
        resolved_links: object,
        unresolved_links: object,
        ambiguous_links: object,
    ) -> None:
        self.status_label.setText("证据完整" if complete else "证据需复核")
        self.detail_label.setText(
            f"{indexed_transactions} 笔交易已建立唯一索引 · "
            f"{resolved_links} 条有效证据引用 · "
            f"{unresolved_links} 条悬空引用 · "
            f"{ambiguous_links} 条歧义引用"
        )


class ObservationCard(HardShadowCard):
    def __init__(self, title: str, text: str, parent: QWidget | None = None):
        super().__init__(BriefTheme.SURFACE, parent)
        self.setMinimumHeight(98)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 22, 18)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("briefCardTitle")
        self.text_label = QLabel(text)
        self.text_label.setObjectName("briefCardText")
        self.text_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.text_label)


class EmptyStateCard(ObservationCard):
    def __init__(self, text: str):
        super().__init__("当前状态", text)


class ResultListModel(QAbstractTableModel):
    """Paged view over a standard result; stores no Transaction objects."""

    MANUAL_HEADERS = ("状态", "人工核实事项", "触发原因", "证据数")
    SENSITIVE_HEADERS = (
        "状态",
        "命中词",
        "日期",
        "方向",
        "金额",
        "交易对手",
        "来源文件",
    )
    BUSINESS_HEADERS = (
        "判断来源",
        "关联分类",
        "证据强度",
        "日期",
        "方向",
        "金额",
        "交易对手",
        "判断依据",
    )

    def __init__(self, kind: str, page_size: int = 50, parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self.page_size = page_size
        self.page = 0
        self.view_filter = "positive" if kind == "business" else "all"
        self._result: Mapping[str, object] | None = None
        self._row_indices: range = range(0)
        self._business_transactions: dict[str, Mapping[str, object]] = {}

    @property
    def headers(self) -> tuple[str, ...]:
        if self.kind == "manual":
            return self.MANUAL_HEADERS
        if self.kind == "business":
            return self.BUSINESS_HEADERS
        return self.SENSITIVE_HEADERS

    def _rows(self) -> list[object]:
        if self._result is None:
            return []
        if self.kind == "manual":
            return manual_verification_questions(self._result)
        if self.kind == "business":
            return _business_rows(self._result, self.view_filter)
        return sensitive_transaction_candidates(self._result)

    def set_view_filter(self, view_filter: str) -> None:
        if self.kind != "business":
            return
        resolved = (
            view_filter
            if view_filter in BUSINESS_FILTER_LABELS
            else "positive"
        )
        if resolved == self.view_filter:
            return
        self.beginResetModel()
        self.view_filter = resolved
        self.page = 0
        self._row_indices = range(len(self._rows()))
        self.endResetModel()

    def set_result(self, result: Mapping[str, object] | None) -> None:
        self.beginResetModel()
        self._result = result
        self.page = 0
        self._business_transactions.clear()
        self._row_indices = range(len(self._rows()))
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        start = self.page * self.page_size
        return max(0, min(self.page_size, len(self._row_indices) - start))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def _absolute_row(self, row: int) -> int:
        return self.page * self.page_size + row

    def item_at(self, row: int) -> Mapping[str, object]:
        rows = self._rows()
        absolute_row = self._absolute_row(row)
        if 0 <= absolute_row < len(rows) and isinstance(rows[absolute_row], Mapping):
            return rows[absolute_row]
        return {}

    def transaction_id_at(self, row: int) -> str:
        item = self.item_at(row)
        if self.kind == "manual":
            values = item.get("evidence_transaction_ids", [])
            return str(values[0]) if isinstance(values, list) and values else ""
        if self.kind == "business":
            candidate = item.get("candidate")
            return (
                str(candidate.get("transaction_id") or "")
                if isinstance(candidate, Mapping)
                else ""
            )
        return str(item.get("transaction_id") or "")

    def data(self, index: QModelIndex, role: int = 0):
        if not index.isValid() or role not in {
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.TextAlignmentRole,
        }:
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        item = self.item_at(index.row())
        if self.kind == "manual":
            evidence_ids = item.get("evidence_transaction_ids", [])
            values = (
                "需关注" if item.get("attention_hint_only") else "待核实",
                redact_sensitive_text(item.get("question_text", "")),
                redact_sensitive_text(item.get("trigger_reason", "")),
                len(evidence_ids) if isinstance(evidence_ids, list) else 0,
            )
        elif self.kind == "sensitive":
            context = item.get("transaction_context", {})
            context = context if isinstance(context, Mapping) else {}
            fields = context.get("reliable_standard_fields", {})
            fields = fields if isinstance(fields, Mapping) else {}
            direction = str(context.get("direction") or "")
            amount = (
                context.get("income")
                if direction == "income"
                else context.get("expense")
            )
            counterparty = (
                fields.get("counterparty_name")
                or fields.get("merchant_name")
                or fields.get("counterparty_account")
                or ""
            )
            if counterparty == fields.get("counterparty_account"):
                counterparty = mask_account(counterparty)
            values = (
                "候选命中",
                "、".join(str(value) for value in item.get("matched_terms", [])),
                str(context.get("transaction_time") or "")[:19],
                {"income": "收入", "expense": "支出", "neutral": "中性"}.get(
                    direction,
                    direction,
                ),
                _money(amount),
                redact_sensitive_text(counterparty),
                Path(str(context.get("source_file") or "")).name,
            )
        else:
            candidate = item.get("candidate")
            candidate = candidate if isinstance(candidate, Mapping) else {}
            transaction: Mapping[str, object] = {}
            transaction_id = str(candidate.get("transaction_id") or "")
            if self._result is not None and transaction_id:
                transaction = self._business_transactions.get(transaction_id, {})
                if not transaction:
                    try:
                        evidence = evidence_transaction(self._result, transaction_id)
                        original = evidence.get("transaction")
                        if isinstance(original, Mapping):
                            transaction = original
                            self._business_transactions[transaction_id] = original
                    except StandardResultError:
                        transaction = {}
            direction, amount = _direction_and_amount(transaction)
            counterparty = (
                transaction.get("counterparty_name")
                or transaction.get("merchant_name")
                or transaction.get("counterparty_account")
                or ""
            )
            if counterparty == transaction.get("counterparty_account"):
                counterparty = mask_account(counterparty)
            values = (
                item.get("source", ""),
                _BUSINESS_CLASSIFICATION_LABELS.get(
                    str(candidate.get("classification") or ""),
                    str(candidate.get("classification") or ""),
                ),
                _BUSINESS_STRENGTH_LABELS.get(
                    str(candidate.get("evidence_strength") or ""),
                    str(candidate.get("evidence_strength") or "—"),
                ),
                str(transaction.get("transaction_time") or "")[:19],
                direction,
                amount,
                redact_sensitive_text(counterparty),
                redact_sensitive_text(candidate.get("reason", "")),
            )
        value = values[index.column()]
        return str(value) if role == Qt.ItemDataRole.DisplayRole else str(value)

    def page_count(self) -> int:
        count = len(self._row_indices)
        return max(1, (count + self.page_size - 1) // self.page_size)

    def total_count(self) -> int:
        return len(self._row_indices)

    def transaction_ids(self) -> list[str]:
        current_page = self.page
        values: list[str] = []
        for absolute_row in self._row_indices:
            self.page = absolute_row // self.page_size
            relative_row = absolute_row % self.page_size
            transaction_id = self.transaction_id_at(relative_row)
            if transaction_id:
                values.append(transaction_id)
        self.page = current_page
        return values

    def set_page(self, page: int) -> None:
        page = max(0, min(page, self.page_count() - 1))
        if page == self.page:
            return
        self.beginResetModel()
        self.page = page
        self.endResetModel()


class PagedTable(QWidget):
    transactionSelected = pyqtSignal(str)
    selectionUnavailable = pyqtSignal(str)

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.model = ResultListModel(kind, parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.clicked.connect(self._clicked)
        layout.addWidget(self.table, 1)
        footer = QHBoxLayout()
        self.previous_button = QPushButton("← 上一页")
        self.next_button = QPushButton("下一页 →")
        self.page_label = QLabel("第 1 / 1 页 · 0 条")
        self.previous_button.clicked.connect(lambda: self._move_page(-1))
        self.next_button.clicked.connect(lambda: self._move_page(1))
        footer.addWidget(self.previous_button)
        footer.addWidget(self.page_label)
        footer.addStretch(1)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)
        self._refresh_footer()

    def set_result(self, result: Mapping[str, object] | None) -> None:
        self.model.set_result(result)
        self._refresh_footer()

    def set_view_filter(self, view_filter: str) -> None:
        self.model.set_view_filter(view_filter)
        self._refresh_footer()

    def _move_page(self, delta: int) -> None:
        self.model.set_page(self.model.page + delta)
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        count = self.model.page_count()
        self.page_label.setText(
            f"第 {self.model.page + 1} / {count} 页 · {self.model.total_count()} 条"
        )
        self.previous_button.setEnabled(self.model.page > 0)
        self.next_button.setEnabled(self.model.page + 1 < count)

    def _clicked(self, index: QModelIndex) -> None:
        transaction_id = self.model.transaction_id_at(index.row())
        if transaction_id:
            self.transactionSelected.emit(transaction_id)
            return
        self.selectionUnavailable.emit(
            "该事项没有直接关联的交易ID，无法展开单笔交易证据；"
            "请查看该行的触发原因，或选择其他带交易ID的事项。"
        )


class EvidencePanel(HardShadowCard):
    closeRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(BriefTheme.SURFACE, parent)
        self.setMinimumWidth(360)
        self._result: Mapping[str, object] | None = None
        self._transaction_ids: list[str] = []
        self._current_index = -1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 24, 22)
        layout.setSpacing(10)
        header_row = QHBoxLayout()
        header_row.addWidget(SectionHeader("E", "交易证据详情"), 1)
        self.previous_button = QPushButton("← 上一条")
        self.next_button = QPushButton("下一条 →")
        self.close_button = QPushButton("关闭")
        self.previous_button.clicked.connect(lambda: self._move(-1))
        self.next_button.clicked.connect(lambda: self._move(1))
        self.close_button.clicked.connect(self.closeRequested)
        header_row.addWidget(self.close_button)
        navigation_row = QHBoxLayout()
        navigation_row.addWidget(self.previous_button)
        navigation_row.addWidget(self.next_button)
        navigation_row.addStretch(1)
        self.status = StatusBadge("等待左侧选择", "muted")
        self.expand_button = QPushButton("展开完整证据")
        self.expand_button.setEnabled(False)
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(self._toggle_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("briefEvidenceText")
        self.details.setPlainText(
            "此处是证据详情输出区，不是候选列表。\n\n"
            "1. 先选择案例目录或打开标准结果JSON；\n"
            "2. 进入左侧“人工核实”或“敏感交易”；\n"
            "3. 点击带交易ID的表格行。\n\n"
            "随后将在此显示原交易、来源文件及页/行证据。"
        )
        layout.addLayout(header_row)
        layout.addLayout(navigation_row)
        layout.addWidget(self.status, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.expand_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details, 1)
        self._compact_text = self.details.toPlainText()
        self._full_text = self._compact_text
        self._refresh_navigation()

    def set_context(
        self,
        result: Mapping[str, object],
        transaction_ids: list[str],
        transaction_id: str,
    ) -> None:
        self._result = result
        self._transaction_ids = list(
            dict.fromkeys(value for value in transaction_ids if value)
        )
        if transaction_id not in self._transaction_ids:
            self._transaction_ids.append(transaction_id)
        self._current_index = self._transaction_ids.index(transaction_id)
        self.show_transaction(result, transaction_id)
        self._refresh_navigation()

    def _move(self, delta: int) -> None:
        target = self._current_index + delta
        if self._result is None or not 0 <= target < len(self._transaction_ids):
            return
        self._current_index = target
        self.show_transaction(self._result, self._transaction_ids[target])
        self._refresh_navigation()

    def _refresh_navigation(self) -> None:
        self.previous_button.setEnabled(self._current_index > 0)
        self.next_button.setEnabled(
            0 <= self._current_index < len(self._transaction_ids) - 1
        )

    def show_transaction(
        self,
        result: Mapping[str, object],
        transaction_id: str,
    ) -> None:
        try:
            resolved = evidence_transaction(result, transaction_id)
        except StandardResultError as exc:
            self.status.set_status("不可用", "red")
            self.details.setPlainText(str(exc))
            return
        transaction = resolved["transaction"]
        standard = transaction.get("standard_fields", {})
        standard = standard if isinstance(standard, Mapping) else {}
        original = transaction.get("original", {})
        original = original if isinstance(original, Mapping) else {}
        direction, amount = _direction_and_amount(transaction)
        references = resolved.get("references", [])
        integrity = resolved.get("integrity", {})
        reference_statuses = {
            str(reference.get("status"))
            for reference in references
            if isinstance(reference, Mapping)
        }
        complete = bool(integrity.get("complete")) and reference_statuses <= {"resolved"}
        self.status.set_status(
            "引用完整" if complete else "需复核",
            "mint" if complete else "orange",
        )
        text_fields = []
        for label, field_name in (
            ("交易对手", "counterparty_name"),
            ("摘要", "summary"),
            ("备注", "remark"),
            ("用途", "purpose"),
            ("商品说明", "product_description"),
            ("商户", "merchant_name"),
            ("商户类别", "merchant_category"),
        ):
            value = standard.get(field_name)
            if value:
                text_fields.append(f"{label}：{redact_sensitive_text(value)}")
        account = standard.get("counterparty_account")
        if account:
            text_fields.append(f"对手账号：{mask_account(account)}")
        raw_values = []
        if original.get("raw_text"):
            raw_values.append(redact_sensitive_text(original["raw_text"]))
        if isinstance(original.get("raw_fields"), list):
            raw_values.extend(
                redact_sensitive_text(value)
                for value in original["raw_fields"]
                if str(value or "").strip()
            )
        reference_text = "、".join(sorted(reference_statuses)) or "未登记消费者引用"
        compact_lines = [
            f"日期：{str(transaction.get('transaction_time') or '')[:19]}",
            f"方向：{direction}",
            f"金额：{amount}",
            *text_fields,
            f"来源文件：{Path(str(transaction.get('source_file') or '')).name}",
            f"页码：{transaction.get('page_no')}",
            f"行号：{transaction.get('row_no')}",
        ]
        full_lines = [
            *compact_lines,
            "",
            "完整证据信息：",
            f"交易ID：{short_transaction_id(transaction_id)}",
            f"证据定位：{transaction.get('evidence_locator') or '不可用'}",
            f"引用状态：{reference_text}",
            f"整体完整性：{'完整' if integrity.get('complete') else '存在缺失、重复或悬空/歧义'}",
        ]
        if raw_values:
            full_lines.extend(["", "原始字段（已脱敏）：", *raw_values])
        self._compact_text = "\n".join(compact_lines)
        self._full_text = "\n".join(full_lines)
        self.expand_button.setEnabled(True)
        self.expand_button.setChecked(False)
        self._toggle_details(False)

    def show_unavailable(self, message: str) -> None:
        self.status.set_status("无直接交易证据", "muted")
        self.expand_button.setChecked(False)
        self.expand_button.setEnabled(False)
        self.details.setPlainText(message)

    def _toggle_details(self, expanded: bool) -> None:
        self.expand_button.setText(
            "收起完整证据" if expanded else "展开完整证据"
        )
        self.details.setPlainText(
            self._full_text if expanded else self._compact_text
        )


class WelcomePage(QWidget):
    newCaseRequested = pyqtSignal()
    openCaseRequested = pyqtSignal()
    importResultRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(20)
        eyebrow = QLabel("// BANKFLOW VERIFICATION · SCHEMA 1.16")
        eyebrow.setObjectName("briefEyebrow")
        title = QLabel("流水核查工作台")
        title.setObjectName("briefHeroTitle")
        subtitle = QLabel(
            "新建核查、继续已有案件，或直接导入标准结果。未加载案件时不展示空白分析页面。"
        )
        subtitle.setObjectName("briefSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        cards = QGridLayout()
        cards.setHorizontalSpacing(18)
        cards.setVerticalSpacing(18)
        self.new_case_button = self._action_card(
            cards,
            0,
            "01",
            "新建流水核查",
            "选择客户资料目录，解析现有来源并生成 schema 1.16 标准结果。",
            "选择客户资料目录",
            BriefTheme.ORANGE,
            self.newCaseRequested,
        )
        self.open_case_button = self._action_card(
            cards,
            1,
            "02",
            "打开已有案件",
            "优先读取案件目录中的已有标准结果，避免重复解析。",
            "打开已有案件",
            BriefTheme.MINT,
            self.openCaseRequested,
        )
        self.import_result_button = self._action_card(
            cards,
            2,
            "03",
            "导入标准结果",
            "打开已有 schema 1.16 JSON，直接进入案件概览。",
            "导入标准结果",
            BriefTheme.YELLOW,
            self.importResultRequested,
        )
        layout.addLayout(cards)
        layout.addSpacing(8)
        recent = HardShadowCard(BriefTheme.SURFACE)
        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(16, 12, 22, 18)
        recent_title = QLabel("最近处理案件")
        recent_title.setObjectName("briefCardTitle")
        self.recent_label = QLabel("暂无最近案件。导入或完成一个案件后会显示在这里。")
        self.recent_label.setObjectName("briefCardText")
        self.recent_label.setWordWrap(True)
        recent_layout.addWidget(recent_title)
        recent_layout.addWidget(self.recent_label)
        layout.addWidget(recent)
        layout.addStretch(1)

    def _action_card(
        self,
        grid: QGridLayout,
        column: int,
        number: str,
        title: str,
        description: str,
        button_text: str,
        accent: str,
        signal,
    ) -> QPushButton:
        card = HardShadowCard(accent)
        card.setMinimumHeight(235)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 24, 22)
        number_label = QLabel(f"// {number}")
        number_label.setObjectName("briefEyebrow")
        title_label = QLabel(title)
        title_label.setObjectName("briefActionTitle")
        description_label = QLabel(description)
        description_label.setObjectName("briefCardText")
        description_label.setWordWrap(True)
        button = QPushButton(button_text)
        button.clicked.connect(signal)
        card_layout.addWidget(number_label)
        card_layout.addWidget(title_label)
        card_layout.addWidget(description_label)
        card_layout.addStretch(1)
        card_layout.addWidget(button)
        grid.addWidget(card, 0, column)
        return button

    def set_recent_cases(self, names: list[str]) -> None:
        self.recent_label.setText(
            "\n".join(f"• {name}" for name in names[:5])
            if names
            else "暂无最近案件。导入或完成一个案件后会显示在这里。"
        )


class CasePreparationPage(QWidget):
    confirmed = pyqtSignal(object)
    skipped = pyqtSignal()
    backRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._context: Mapping[str, object] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(14)
        layout.addWidget(SectionHeader("PREPARE", "分析前确认"))
        title = QLabel("确认经营上下文")
        title.setObjectName("briefHeroTitle")
        note = QLabel(
            "工作单位名称只作为文字线索，不能据此推断实际主营。"
            "请核对已提取内容；客户原始资料不会被修改。"
        )
        note.setObjectName("briefPageNote")
        note.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(note)

        self.extracted_card = HardShadowCard(BriefTheme.SURFACE)
        self.extracted_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        extracted_layout = QGridLayout(self.extracted_card)
        extracted_layout.setContentsMargins(18, 16, 24, 22)
        extracted_layout.setHorizontalSpacing(18)
        extracted_layout.setVerticalSpacing(10)
        extracted_layout.setColumnStretch(1, 1)
        self.work_unit = QLabel("未提取")
        self.work_content = QLabel("未提取")
        self.context_status = QLabel("待扫描")
        self.case_name = QLabel("未命名案例")
        self.missing_information = QLabel("待扫描")
        for row, (label, widget) in enumerate(
            (
                ("案例名称", self.case_name),
                ("工作单位", self.work_unit),
                ("明确工作内容", self.work_content),
                ("经营上下文状态", self.context_status),
                ("当前缺少信息", self.missing_information),
            )
        ):
            key = QLabel(label)
            key.setObjectName("briefMetricLabel")
            widget.setWordWrap(True)
            extracted_layout.addWidget(key, row, 0)
            extracted_layout.addWidget(widget, row, 1)
        self.source_text = QPlainTextEdit()
        self.source_text.setReadOnly(True)
        self.source_text.setMinimumHeight(180)
        source_row = 5
        extracted_layout.addWidget(QLabel("提取原文与来源"), source_row, 0)
        extracted_layout.addWidget(self.source_text, source_row, 1)
        extracted_layout.setRowStretch(source_row, 1)

        self.form_card = HardShadowCard(BriefTheme.SURFACE)
        self.form_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        form_layout = QGridLayout(self.form_card)
        form_layout.setContentsMargins(18, 16, 24, 22)
        form_layout.setHorizontalSpacing(18)
        form_layout.setVerticalSpacing(10)
        form_layout.setColumnStretch(1, 1)
        self.primary_business = QLineEdit()
        self.products_services = QLineEdit()
        self.confirmation_note = QLineEdit()
        self.confirmed_by = QLineEdit()
        self.primary_business.setPlaceholderText(
            "资料不足时必填，例如：食品销售"
        )
        self.products_services.setPlaceholderText("选填，例如：预包装食品、餐饮服务")
        self.confirmation_note.setPlaceholderText("选填，记录确认依据或补充说明")
        self.confirmed_by.setPlaceholderText("人工补充经营内容时必填")
        fields = (
            ("实际主要经营内容", self.primary_business),
            ("主要产品或服务", self.products_services),
            ("补充说明", self.confirmation_note),
            ("确认人（必填）", self.confirmed_by),
        )
        for row, (label, editor) in enumerate(fields):
            form_layout.addWidget(QLabel(label), row, 0)
            form_layout.addWidget(editor, row, 1)
        self.ai_enabled = QCheckBox("启用 AI 经营语义辅助")
        self.ai_enabled.setChecked(False)
        form_layout.addWidget(self.ai_enabled, len(fields), 0, 1, 2)
        self.ai_key_label = QLabel("DeepSeek API Key（仅本次运行）")
        self.ai_api_key = QLineEdit()
        self.ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key.setPlaceholderText(
            "启动环境未配置Key时在此输入；不会保存到案件或结果"
        )
        form_layout.addWidget(self.ai_key_label, len(fields) + 1, 0)
        form_layout.addWidget(self.ai_api_key, len(fields) + 1, 1)
        self.ai_scope = QLabel(
            "勾选并确认后，才允许提交：已确认经营内容、主要产品或服务，"
            "以及交易中的可靠摘要、备注、用途、商品说明、商户类别和必要的"
            "企业/商户名称。API Key只保留在本次进程内，不写入案件文件、"
            "标准结果或日志。默认关闭；不会因环境变量自动调用。"
        )
        self.ai_scope.setObjectName("briefPageNote")
        self.ai_scope.setWordWrap(True)
        self.ai_scope.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.ai_scope.setMinimumHeight(110)
        self.ai_scope.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.MinimumExpanding,
        )
        form_layout.addWidget(self.ai_scope, len(fields) + 2, 0, 1, 2)
        form_layout.setRowStretch(len(fields) + 2, 1)
        self.ai_enabled.toggled.connect(self._toggle_ai_inputs)
        self._toggle_ai_inputs(False)

        self.preparation_panels_layout = QHBoxLayout()
        self.preparation_panels_layout.setSpacing(16)
        self.preparation_panels_layout.addWidget(self.extracted_card, 1)
        self.preparation_panels_layout.addWidget(self.form_card, 1)
        layout.addLayout(self.preparation_panels_layout, 1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("briefError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        actions = QHBoxLayout()
        self.back_button = QPushButton("返回选择资料目录")
        self.skip_button = QPushButton("暂不补充，继续分析")
        self.confirm_button = QPushButton("确认并开始分析")
        self.back_button.clicked.connect(self.backRequested)
        self.skip_button.clicked.connect(self.skipped)
        self.confirm_button.clicked.connect(self._confirm)
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.skip_button)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)

    def set_context(
        self,
        context: Mapping[str, object],
        manual_record: Mapping[str, object] | None = None,
        *,
        reanalysis: bool = False,
    ) -> None:
        self._context = context
        record = manual_record if isinstance(manual_record, Mapping) else {}
        original_info = record.get("original_extracted_information")
        original_info = (
            original_info if isinstance(original_info, Mapping) else {}
        )
        search = context.get("search_context")
        search = search if isinstance(search, Mapping) else {}
        business = context.get("business_context")
        business = business if isinstance(business, Mapping) else {}
        self.case_name.setText(
            str(context.get("case_id") or record.get("case_id") or "未命名案例")
        )
        work_units = search.get("work_units", [])
        if not work_units:
            work_units = original_info.get("work_units", [])
        descriptions = business.get("declared_work_descriptions", [])
        if not descriptions:
            original_business = original_info.get("business_context")
            original_business = (
                original_business
                if isinstance(original_business, Mapping)
                else {}
            )
            descriptions = original_business.get(
                "declared_work_descriptions",
                [],
            )
        self.work_unit.setText(
            "；".join(str(value) for value in work_units)
            if isinstance(work_units, list) and work_units
            else "未提取"
        )
        self.work_content.setText(
            "；".join(str(value) for value in descriptions)
            if isinstance(descriptions, list) and descriptions
            else "未提取明确工作内容"
        )
        reason = str(business.get("confirmation_reason") or "")
        status_labels = {
            "company_name_only": "只有工作单位名称，需补充实际经营内容",
            "work_description_missing": "未提取工作单位或明确工作内容",
            "multiple_declared_work_descriptions": "存在多个工作描述，需人工确认",
            "company_description_conflict": "单位名称与工作描述可能冲突，需人工确认",
        }
        self.context_status.setText(
            "可使用已提取的明确工作内容"
            if business.get("ai_business_relevance_eligible")
            else status_labels.get(reason, "经营上下文待确认")
        )
        if business.get("ai_business_relevance_eligible"):
            missing_text = "无必填缺口；请核对已提取的明确工作内容"
        elif reason == "work_description_missing":
            missing_text = (
                "实际主要经营内容（必填）；工作单位和主要产品或服务如有请补充"
            )
        else:
            missing_text = (
                "实际主要经营内容（必填）；主要产品或服务建议补充"
            )
        self.missing_information.setText(missing_text)
        evidence = business.get("declared_work_evidence", [])
        if not evidence:
            original_business = original_info.get("business_context")
            if isinstance(original_business, Mapping):
                evidence = original_business.get(
                    "declared_work_evidence",
                    [],
                )
        source_lines = []
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, Mapping):
                    continue
                source_lines.append(
                    f"{item.get('source_ref') or '未知来源'} · "
                    f"{item.get('source_field') or '工作描述'}\n"
                    f"{item.get('source_excerpt') or item.get('value') or ''}"
                )
        if not source_lines and work_units:
            fields = context.get("fields")
            fields = fields if isinstance(fields, Mapping) else {}
            for item in fields.get("work_unit", []):
                if isinstance(item, Mapping):
                    source_lines.append(
                        f"{item.get('source_ref') or '未知来源'} · 工作单位\n"
                        f"{item.get('source_excerpt') or item.get('value') or ''}"
                    )
        self.source_text.setPlainText(
            "\n\n".join(source_lines) if source_lines else "未找到可展示的原始文字。"
        )
        confirmation = record.get("manual_confirmation")
        confirmation = confirmation if isinstance(confirmation, Mapping) else {}
        if confirmation.get("confirmation_status") == "confirmed":
            self.context_status.setText(
                "已恢复案件工作区中的人工经营确认，可修改后重新确认"
            )
            self.missing_information.setText(
                "无必填缺口（已恢复人工确认）"
            )
        self.primary_business.setText(
            str(confirmation.get("confirmed_primary_business") or "")
        )
        self.products_services.setText(
            str(confirmation.get("confirmed_products_or_services") or "")
        )
        self.confirmation_note.setText(
            str(confirmation.get("confirmation_note") or "")
        )
        self.confirmed_by.setText(str(record.get("confirmed_by") or ""))
        self.ai_enabled.setChecked(
            bool(
                record.get(
                    "enable_ai_business_analysis",
                    record.get("ai_business_assistance_enabled"),
                )
            )
        )
        self.ai_api_key.clear()
        self.confirm_button.setText(
            "应用并重新分析经营关联"
            if reanalysis
            else "确认并开始分析"
        )
        self.skip_button.setVisible(not reanalysis)
        self._clear_validation()

    def _confirm(self) -> None:
        self._clear_validation()
        business = self._context.get("business_context")
        business = business if isinstance(business, Mapping) else {}
        primary = self.primary_business.text().strip()
        if not business.get("ai_business_relevance_eligible") and not primary:
            self.error_label.setText(
                "无法开始分析：当前资料不足，请填写“实际主要经营内容”；"
                "或者选择“暂不补充，继续分析”。"
            )
            self.error_label.show()
            self._mark_invalid(self.primary_business)
            return
        if primary and not self.confirmed_by.text().strip():
            self.error_label.setText(
                "无法开始分析：人工补充经营内容时必须填写确认人。"
            )
            self.error_label.show()
            self._mark_invalid(self.confirmed_by)
            return
        self.confirmed.emit(
            {
                "confirmed_primary_business": primary,
                "confirmed_products_or_services": (
                    self.products_services.text().strip()
                ),
                "confirmation_note": self.confirmation_note.text().strip(),
                "confirmation_status": "confirmed" if primary else "unconfirmed",
                "confirmed_by": self.confirmed_by.text().strip(),
                "enable_ai_business_analysis": self.ai_enabled.isChecked(),
                "ai_api_key": self.ai_api_key.text(),
            }
        )

    def _toggle_ai_inputs(self, enabled: bool) -> None:
        self.ai_key_label.setVisible(enabled)
        self.ai_api_key.setVisible(enabled)
        self.ai_scope.setVisible(enabled)
        if not enabled:
            self.ai_api_key.clear()

    def _clear_validation(self) -> None:
        self.error_label.clear()
        self.error_label.hide()
        for editor in (self.primary_business, self.confirmed_by):
            editor.setProperty("invalid", False)
            editor.style().unpolish(editor)
            editor.style().polish(editor)

    def _mark_invalid(self, editor: QLineEdit) -> None:
        editor.setProperty("invalid", True)
        editor.style().unpolish(editor)
        editor.style().polish(editor)
        editor.setFocus()


class ProcessingPage(QWidget):
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(14)
        self.header = BriefPageHeader()
        layout.addWidget(self.header)
        layout.addWidget(SectionHeader("TASK", "任务处理"))
        info = HardShadowCard(BriefTheme.SURFACE)
        info_layout = QGridLayout(info)
        info_layout.setContentsMargins(18, 16, 24, 22)
        self.current_file = QLabel("等待开始")
        self.file_count = QLabel("0 / 0")
        self.stage = QLabel("准备任务")
        for row, (label, widget) in enumerate(
            (
                ("当前处理文件", self.current_file),
                ("已处理文件数", self.file_count),
                ("当前处理阶段", self.stage),
            )
        ):
            key = QLabel(label)
            key.setObjectName("briefMetricLabel")
            widget.setObjectName("briefCardTitle")
            info_layout.addWidget(key, row, 0)
            info_layout.addWidget(widget, row, 1)
        layout.addWidget(info)
        self.progress = QProgressBar()
        self.progress.setObjectName("briefProgress")
        self.progress.setRange(0, 100)
        self.progress_label = QLabel("等待任务。")
        self.progress_label.setObjectName("briefProgressLabel")
        layout.addWidget(self.progress)
        layout.addWidget(self.progress_label)
        error_title = QLabel("错误或不可用来源")
        error_title.setObjectName("briefSectionTitle")
        self.source_status = QPlainTextEdit()
        self.source_status.setReadOnly(True)
        self.source_status.setPlainText("暂无。")
        layout.addWidget(error_title)
        layout.addWidget(self.source_status, 1)
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.cancel_button = QPushButton("协作取消")
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.cancel_button.hide()
        action_row.addWidget(self.cancel_button)
        layout.addLayout(action_row)
        self._total = 0

    def start(self, case_name: str, total_sources: int) -> None:
        self._total = total_sources
        self.header.set_summary(case_name, "", "", "正在处理")
        self.current_file.setText("正在准备来源")
        self.file_count.setText(f"0 / {total_sources}")
        self.stage.setText("准备解析")
        self.progress.setValue(0)
        self.progress_label.setText(f"准备处理 {total_sources} 个来源文件…")
        self.source_status.setPlainText("暂无错误或不可用来源。")
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()

    def set_progress(self, completed: int, total: int, message: str) -> None:
        self._total = total
        self.progress.setValue(int(completed * 100 / total) if total else 0)
        self.file_count.setText(f"{completed} / {total}")
        self.progress_label.setText(message)
        self.stage.setText(
            "生成标准结果" if "标准结果" in message else "解析与证据附加"
        )
        if "正在解析 " in message:
            self.current_file.setText(message.split("正在解析 ", 1)[1])
        elif "已处理 " in message:
            self.current_file.setText(message.split("已处理 ", 1)[1])

    def add_source_error(self, source_file: str, message: str) -> None:
        existing = self.source_status.toPlainText()
        line = f"{Path(source_file).name}：{message}"
        self.source_status.setPlainText(
            line if existing == "暂无错误或不可用来源。" else f"{existing}\n{line}"
        )

    def set_cancel_pending(self) -> None:
        self.stage.setText("正在取消")
        self.progress_label.setText("正在取消，等待当前来源处理结束…")
        self.cancel_button.setEnabled(False)

    def stop(self, message: str) -> None:
        self.progress_label.setText(message)
        self.cancel_button.hide()


class ModuleSummaryHeader(QWidget):
    backRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top_row = QHBoxLayout()
        self.back_button = QPushButton("返回案件概览")
        self.back_button.clicked.connect(self.backRequested)
        self.breadcrumb_label = QLabel("当前案件 > 概览")
        self.breadcrumb_label.setObjectName("briefBreadcrumb")
        top_row.addWidget(self.back_button)
        top_row.addWidget(self.breadcrumb_label)
        top_row.addStretch(1)
        self.title = QLabel("模块分析概要")
        self.title.setObjectName("briefHeroTitle")
        self.note = QLabel("先选择候选分类，再进入交易明细。")
        self.note.setObjectName("briefPageNote")
        self.note.setWordWrap(True)
        layout.addLayout(top_row)
        layout.addWidget(self.title)
        layout.addWidget(self.note)

    def set_content(self, breadcrumb: str, title: str, note: str) -> None:
        self.breadcrumb_label.setText(breadcrumb)
        self.title.setText(title)
        self.note.setText(note)


class ModuleSummaryPage(QScrollArea):
    backRequested = pyqtSignal()
    categoryRequested = pyqtSignal(str, str)
    businessPreparationRequested = pyqtSignal()

    SECTION_TITLES = {
        "overview": "概览",
        "verification_declaration": "核实与申报概要",
        "purchase_business": "购车与经营概要",
        "funds_balance": "资金与余额概要",
        "counterparty": "主要交易关系概要",
        "evidence_center": "证据中心",
    }
    SECTION_MODULES = {
        "overview": (),
        "verification_declaration": ("manual", "sensitive", "declaration"),
        "purchase_business": ("purchase", "business"),
        "funds_balance": ("funds", "balance"),
        "counterparty": ("counterparty",),
        "evidence_center": ("evidence",),
    }
    MODULE_TITLES = {
        "manual": "人工核实",
        "sensitive": "敏感交易",
        "business": "经营关联",
        "purchase": "下定购车",
        "counterparty": "交易对手",
        "funds": "资金观察",
        "balance": "余额与月度",
        "declaration": "申报对照",
        "evidence": "证据中心",
    }
    CATEGORY_CHOICES = {
        "manual": (("查看待核实事项", "all"),),
        "sensitive": (("查看敏感候选", "all"),),
        "business": (
            ("正向候选", "positive"),
            ("待人工判断", "manual"),
            ("已排除 / 无关联", "excluded"),
            ("全部结果", "all"),
        ),
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._summaries: dict[str, tuple[str, str]] = {}
        self.choice_buttons: dict[tuple[str, str], QPushButton] = {}
        self.business_prepare_button: QPushButton | None = None
        self.container = QWidget()
        self.setWidget(self.container)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(12)
        self.summary_header = ModuleSummaryHeader()
        self.summary_header.backRequested.connect(self.backRequested.emit)
        self.back_button = self.summary_header.back_button
        self.breadcrumb_label = self.summary_header.breadcrumb_label
        self.title = self.summary_header.title
        self.note = self.summary_header.note
        layout.addWidget(self.summary_header)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)
        layout.addWidget(self.cards_container)
        layout.addStretch(1)

    def set_module_summaries(
        self,
        summaries: Mapping[str, tuple[str, str]],
    ) -> None:
        self._summaries = dict(summaries)

    def set_section(
        self,
        section_key: str,
        focus_module: str = "",
    ) -> None:
        resolved = (
            section_key
            if section_key in self.SECTION_TITLES
            else "overview"
        )
        section_title = self.SECTION_TITLES[resolved]
        breadcrumb = f"当前案件 > {section_title}"
        if focus_module in self.MODULE_TITLES:
            breadcrumb += f" > {self.MODULE_TITLES[focus_module]}"
        self.summary_header.set_content(
            breadcrumb,
            section_title,
            "先查看模块概要，再主动选择候选分类进入交易明细。",
        )
        modules = list(self.SECTION_MODULES[resolved])
        if focus_module in modules:
            modules = [focus_module]
        self._clear_cards()
        if not modules:
            self.summary_header.set_content(
                breadcrumb,
                section_title,
                "请从案件概览的组合卡片进入对应模块概要。",
            )
            return
        for module_key in modules:
            self.cards_layout.addWidget(self._module_card(module_key))

    def _module_card(self, module_key: str) -> QWidget:
        card = HardShadowCard(BriefTheme.SURFACE)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 24, 22)
        layout.setSpacing(8)
        title = QLabel(self.MODULE_TITLES[module_key])
        title.setObjectName("briefCardTitle")
        summary, status = self._summaries.get(
            module_key,
            ("等待标准结果。", "不可用"),
        )
        summary_label = QLabel(summary)
        summary_label.setObjectName("briefCardText")
        summary_label.setWordWrap(True)
        status_label = QLabel(status)
        status_label.setObjectName("briefPageNote")
        status_label.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(summary_label)
        layout.addWidget(status_label)
        if module_key == "business":
            prepare_button = QPushButton("补充经营信息")
            prepare_button.clicked.connect(
                self.businessPreparationRequested
            )
            self.business_prepare_button = prepare_button
            layout.addWidget(
                prepare_button,
                0,
                Qt.AlignmentFlag.AlignLeft,
            )
        choices = self.CATEGORY_CHOICES.get(module_key, ())
        if not choices:
            disabled = QPushButton("后续接入")
            disabled.setEnabled(False)
            layout.addWidget(disabled, 0, Qt.AlignmentFlag.AlignLeft)
            return card
        choices_row = QHBoxLayout()
        for label, category in choices:
            button = CandidateCategoryButton(label, category)
            button.clicked.connect(
                lambda checked=False, key=module_key, value=category:
                self.categoryRequested.emit(key, value)
            )
            self.choice_buttons[(module_key, category)] = button
            choices_row.addWidget(button)
        choices_row.addStretch(1)
        layout.addLayout(choices_row)
        return card

    def _clear_cards(self) -> None:
        self.choice_buttons.clear()
        self.business_prepare_button = None
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class TransactionListPanel(QWidget):
    backRequested = pyqtSignal()
    businessPreparationRequested = pyqtSignal()
    transactionSelected = pyqtSignal(str, object)
    selectionUnavailable = pyqtSignal(str)

    MODULE_TITLES = {
        "manual": "人工核实",
        "sensitive": "敏感交易",
        "business": "经营关联",
        "purchase": "下定购车",
        "counterparty": "交易对手",
        "funds": "资金观察",
        "balance": "余额与月度",
        "declaration": "申报对照",
        "evidence": "证据中心",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: Mapping[str, object] | None = None
        self._module_key = "manual"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        breadcrumb = QHBoxLayout()
        self.back_button = QPushButton("返回模块概要")
        self.back_button.clicked.connect(self.backRequested)
        self.breadcrumb_label = QLabel("当前案件 > 概览 > 人工核实")
        self.breadcrumb_label.setObjectName("briefBreadcrumb")
        breadcrumb.addWidget(self.back_button)
        breadcrumb.addWidget(self.breadcrumb_label)
        breadcrumb.addStretch(1)
        layout.addLayout(breadcrumb)
        self.title = QLabel("人工核实")
        self.title.setObjectName("briefHeroTitle")
        self.summary = QLabel("等待标准结果。")
        self.summary.setObjectName("briefPageNote")
        self.summary.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        self.business_notice = QLabel("等待标准结果。")
        self.business_notice.setObjectName("briefPageNote")
        self.business_notice.setWordWrap(True)
        self.business_notice.hide()
        layout.addWidget(self.business_notice)
        self.business_prepare_button = QPushButton("补充经营信息")
        self.business_prepare_button.clicked.connect(
            self.businessPreparationRequested
        )
        self.business_prepare_button.hide()
        layout.addWidget(self.business_prepare_button)
        self.tables = QStackedWidget()
        self.manual_table = PagedTable("manual")
        self.sensitive_table = PagedTable("sensitive")
        self.business_table = PagedTable("business")
        self.generic_table = QTableView()
        self.generic_table.setModel(ResultListModel("manual", parent=self.generic_table))
        self.generic_table.setEnabled(False)
        self.tables.addWidget(self.manual_table)
        self.tables.addWidget(self.sensitive_table)
        self.tables.addWidget(self.business_table)
        self.tables.addWidget(self.generic_table)
        layout.addWidget(self.tables, 1)
        for table in (self.manual_table, self.sensitive_table, self.business_table):
            table.transactionSelected.connect(
                lambda transaction_id, source=table: self.transactionSelected.emit(
                    transaction_id,
                    source,
                )
            )
            table.selectionUnavailable.connect(self.selectionUnavailable)

    def set_result(self, result: Mapping[str, object] | None) -> None:
        self._result = result
        self.manual_table.set_result(result)
        self.sensitive_table.set_result(result)
        self.business_table.set_result(result)
        self.business_notice.setText(_business_status_text(result))

    def set_module(
        self,
        module_key: str,
        summary: str,
        *,
        view_filter: str = "positive",
        breadcrumb: str = "",
    ) -> None:
        self._module_key = module_key
        title = self.MODULE_TITLES[module_key]
        self.breadcrumb_label.setText(
            breadcrumb or f"当前案件 > {title}"
        )
        resolved_filter = (
            view_filter
            if view_filter in BUSINESS_FILTER_LABELS
            else "positive"
        )
        self.title.setText(
            f"{title} · {BUSINESS_FILTER_LABELS[resolved_filter]}"
            if module_key == "business"
            else title
        )
        self.summary.setText(summary)
        self.business_notice.setVisible(module_key == "business")
        self.business_prepare_button.setVisible(module_key == "business")
        if module_key == "manual":
            self.tables.setCurrentWidget(self.manual_table)
        elif module_key == "sensitive":
            self.tables.setCurrentWidget(self.sensitive_table)
        elif module_key == "business":
            self.business_table.set_view_filter(resolved_filter)
            self.tables.setCurrentWidget(self.business_table)
        else:
            self.tables.setCurrentWidget(self.generic_table)


class ModuleDetailPage(TransactionListPanel):
    """Compatibility name for older imports; new workspace uses TransactionListPanel."""


class CaseDashboardPage(QScrollArea):
    moduleRequested = pyqtSignal(str)
    attentionRequested = pyqtSignal()
    businessPreparationRequested = pyqtSignal()

    CARD_DEFINITIONS = (
        ("verification_declaration", "核实与申报"),
        ("purchase_business", "购车与经营"),
        ("funds_balance", "资金与余额"),
        ("counterparty", "主要交易关系"),
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        include_case_header: bool = True,
    ):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.setWidget(self.container)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)
        self.header = BriefPageHeader()
        self.header_meta = QWidget()
        header_meta = QHBoxLayout(self.header_meta)
        header_meta.setContentsMargins(0, 0, 0, 0)
        self.completed_badge = StatusBadge("已完成", "mint")
        self.schema_badge = StatusBadge("schema 1.16", "mint")
        self.evidence_badge = StatusBadge("证据待核验", "muted")
        header_meta.addWidget(self.completed_badge)
        header_meta.addWidget(self.schema_badge)
        header_meta.addWidget(self.evidence_badge)
        header_meta.addStretch(1)
        if include_case_header:
            layout.addWidget(self.header)
            layout.addWidget(self.header_meta)
        self.breadcrumb_label = QLabel("当前案件 > 概览")
        self.breadcrumb_label.setObjectName("briefBreadcrumb")
        layout.addWidget(self.breadcrumb_label)
        layout.addWidget(SectionHeader("DATA", "关键数据"))
        self.key_metrics_panel = KeyMetricsPanel()
        self.metrics = self.key_metrics_panel.metrics
        layout.addWidget(self.key_metrics_panel)
        layout.addWidget(SectionHeader("OVERVIEW", "案件整体画像"))
        self.module_cards: dict[str, KeyFindingCard] = {}
        self.module_grid = QGridLayout()
        self.module_grid.setSpacing(14)
        for key, title in self.CARD_DEFINITIONS:
            card = KeyFindingCard(key, title)
            card.clicked.connect(self.moduleRequested)
            card.secondaryClicked.connect(
                lambda _key: self.businessPreparationRequested.emit()
            )
            self.module_cards[key] = card
        layout.addLayout(self.module_grid)
        layout.addWidget(SectionHeader("FOCUS", "需关注事项（人工核实待办）"))
        self.attention_container = QWidget()
        self.attention_layout = QVBoxLayout(self.attention_container)
        self.attention_layout.setContentsMargins(0, 0, 0, 0)
        self.attention_layout.setSpacing(8)
        self.attention_cards: list[AttentionItemCard] = []
        layout.addWidget(self.attention_container)
        layout.addWidget(SectionHeader("EVIDENCE", "证据完整性"))
        self.evidence_summary = EvidenceSummaryPanel()
        self.evidence_summary.openRequested.connect(
            lambda: self.moduleRequested.emit("evidence")
        )
        layout.addWidget(self.evidence_summary)
        layout.addWidget(SectionHeader("LATER", "后续分析能力"))
        future = QFrame()
        future.setObjectName("briefFutureCapabilities")
        future_layout = QHBoxLayout(future)
        future_layout.setContentsMargins(14, 10, 14, 10)
        future_layout.setSpacing(12)
        self.life_status = StatusBadge("生活轨迹：当前未分析", "muted")
        self.vehicle_status = StatusBadge("用车信息：当前未分析", "muted")
        future_layout.addWidget(self.life_status)
        future_layout.addWidget(self.vehicle_status)
        future_layout.addStretch(1)
        layout.addWidget(future)
        layout.addStretch(1)
        self._columns = 0
        self.module_summaries: dict[str, tuple[str, str]] = {}
        self._reflow(2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow(1 if self.viewport().width() < 860 else 2)

    def _reflow(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        cards = list(self.module_cards.values())
        for card in cards:
            self.module_grid.removeWidget(card)
        for index, card in enumerate(cards):
            self.module_grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.module_grid.setColumnStretch(column, 1)

    def set_result(
        self,
        result: Mapping[str, object],
        case_name: str,
        case_context: Mapping[str, object] | None = None,
        manual_context: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        summary = result_summary(result, case_name)
        status = "证据完整" if summary["evidence_complete"] else "证据需复核"
        self.header.set_summary(
            str(summary["case_name"]),
            str(summary["period_start"]),
            str(summary["period_end"]),
            "已完成",
            summary["source_count"],
            summary["transaction_count"],
        )
        self.header.eyebrow.setText(
            f"// 案件整体画像 · 核查日期 {date.today().isoformat()}"
        )
        self.completed_badge.set_status("已完成", "mint")
        self.schema_badge.set_status(f"schema {summary['schema_version']}", "mint")
        self.evidence_badge.set_status(
            status,
            "mint" if summary["evidence_complete"] else "orange",
        )
        for key, card in self.metrics.items():
            value = summary.get(key, 0)
            if key in {"income_sum", "expense_sum"}:
                compact, full = _money_compact(value)
                card.set_value(compact)
                card.value_label.setToolTip(full)
            else:
                card.set_value(value)
        self._set_attention(result)
        self._set_module_summaries(
            result,
            summary,
            case_context=case_context,
            manual_context=manual_context,
        )
        return summary

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_attention(self, result: Mapping[str, object]) -> None:
        self._clear_layout(self.attention_layout)
        self.attention_cards.clear()
        questions = manual_verification_questions(result)
        if not questions:
            card = EmptyStateCard(
                "当前确定性观察未生成核实事项，不代表不存在其他需核实内容。"
            )
            self.attention_layout.addWidget(card)
            return
        module_mapping = {
            "declaration_flow_cross_checks": ("declaration", "核实与申报"),
            "sensitive_transaction_context_candidates": (
                "sensitive",
                "核实与申报",
            ),
            "top_counterparties": ("counterparty", "主要交易关系"),
            "large_inflow_balance_paths": ("funds", "资金与余额"),
            "ai_business_relevance_candidates": (
                "business",
                "购车与经营",
            ),
            "purchase_prepayment_funding_candidates": (
                "purchase",
                "购车与经营",
            ),
        }
        groups: dict[str, dict[str, object]] = {}
        for item in questions:
            if not isinstance(item, Mapping):
                continue
            observation_type = str(
                item.get("trigger_observation_type") or ""
            )
            module_key, module_title = module_mapping.get(
                observation_type,
                ("manual", "人工核实"),
            )
            group = groups.setdefault(
                module_key,
                {
                    "module_title": module_title,
                    "question_types": set(),
                    "facts": [],
                    "verifications": [],
                    "evidence_ids": set(),
                    "availability": [],
                },
            )
            question_type = str(
                item.get("question_type")
                or item.get("question_id")
                or "verification_item"
            )
            question_types = group["question_types"]
            if not isinstance(question_types, set):
                continue
            is_new_type = question_type not in question_types
            question_types.add(question_type)
            observation = observation_by_type(result, observation_type)
            value = observation.get("value")
            if isinstance(value, Mapping):
                group["availability"].append(bool(value.get("available")))
            else:
                group["availability"].append(None)
            evidence_ids = item.get("evidence_transaction_ids", [])
            if isinstance(evidence_ids, list):
                group["evidence_ids"].update(
                    str(value)
                    for value in evidence_ids
                    if str(value)
                )
            if not is_new_type:
                continue
            group["facts"].append(
                redact_sensitive_text(
                    item.get("trigger_reason")
                    or "确定性观察触发人工核实"
                )
            )
            group["verifications"].append(
                redact_sensitive_text(
                    item.get("question_text")
                    or "请结合原始资料人工核实。"
                )
            )

        def render_items(values: object) -> str:
            rows = list(values) if isinstance(values, list) else []
            rendered = "\n".join(f"• {value}" for value in rows[:3])
            if len(rows) > 3:
                rendered += f"\n• 另有 {len(rows) - 3} 项，请进入人工核实查看"
            return rendered or "• 请进入人工核实查看"

        for module_key, group in list(groups.items())[:5]:
            availability_values = group["availability"]
            available_count = sum(
                value is True for value in availability_values
            )
            unavailable_count = sum(
                value is False for value in availability_values
            )
            if available_count and unavailable_count:
                availability = "部分数据可用"
            elif available_count:
                availability = "数据可用"
            elif unavailable_count:
                availability = "数据不可用"
            else:
                availability = "数据状态未提供"
            question_types = group["question_types"]
            evidence_ids = group["evidence_ids"]
            card = AttentionItemCard(
                render_items(group["facts"]),
                render_items(group["verifications"]),
                module_key,
                str(group["module_title"]),
                len(question_types),
                len(evidence_ids),
                availability,
            )
            card.openRequested.connect(
                lambda _route: self.attentionRequested.emit()
            )
            self.attention_cards.append(card)
            self.attention_layout.addWidget(card)

    def _observation_value(
        self,
        result: Mapping[str, object],
        observation_type: str,
    ) -> Mapping[str, object]:
        observation = observation_by_type(result, observation_type)
        value = observation.get("value")
        return value if isinstance(value, Mapping) else {}

    def _set_module_summaries(
        self,
        result: Mapping[str, object],
        summary: Mapping[str, object],
        *,
        case_context: Mapping[str, object] | None = None,
        manual_context: Mapping[str, object] | None = None,
    ) -> None:
        manual_count = int(summary.get("manual_question_count", 0))
        sensitive_count = int(summary.get("sensitive_candidate_count", 0))
        questions = manual_verification_questions(result)
        focus = [
            redact_sensitive_text(item.get("question_text", "待人工核实"))
            for item in questions[:2]
            if isinstance(item, Mapping)
        ]
        sensitive = self._observation_value(
            result,
            "sensitive_transaction_context_candidates",
        )
        sensitive_rows = sensitive.get("candidates", [])
        category_text = _sensitive_term_summary(sensitive_rows)
        declaration = self._observation_value(
            result,
            "declaration_flow_cross_checks",
        )
        checks = declaration.get("items", [])
        declaration_counts = {
            "direct_match": 0,
            "candidate_match": 0,
            "no_evidence_in_reliable_fields": 0,
            "unavailable": 0,
        }
        for item in checks if isinstance(checks, list) else []:
            if isinstance(item, Mapping) and item.get("status") in declaration_counts:
                declaration_counts[str(item["status"])] += 1
        check_status_labels = {
            "direct_match": "直接命中",
            "candidate_match": "候选命中",
            "no_evidence_in_reliable_fields": "可靠字段内未发现",
            "unavailable": "不可用",
        }
        checks_by_type = {
            str(item.get("check_type")): item
            for item in checks if isinstance(checks, list)
            and isinstance(item, Mapping)
        }
        work_unit_check = checks_by_type.get("work_unit", {})
        business_check = checks_by_type.get("declared_industry", {})
        work_unit_status = check_status_labels.get(
            str(work_unit_check.get("status") or ""),
            "未提供申报项",
        )
        business_check_status = check_status_labels.get(
            str(business_check.get("status") or ""),
            "未提供申报项",
        )
        verification_body = (
            f"待人工核实：{manual_count} 项\n"
            f"具体核实内容请查看下方人工核实待办。\n\n"
            f"敏感候选：{sensitive_count} 项\n{category_text}\n\n"
            "申报对照：\n"
            f"直接命中 {declaration_counts['direct_match']}｜"
            f"候选 {declaration_counts['candidate_match']}｜"
            f"未发现 {declaration_counts['no_evidence_in_reliable_fields']}｜"
            f"不可用 {declaration_counts['unavailable']}"
        )
        declaration_reason = str(declaration.get("reason") or "")
        self.module_cards["verification_declaration"].set_content(
            verification_body,
            (
                "数据可用；候选与未发现状态均需人工结合证据核实"
                if declaration.get("available")
                else f"申报对照不可用：{declaration_reason or '标准结果未提供'}"
            ),
            "orange" if manual_count or sensitive_count else "mint",
        )

        business = self._observation_value(result, "ai_business_relevance_candidates")
        deterministic = business.get("deterministic_candidates", [])
        ai_candidates = business.get("ai_candidates", [])
        deterministic_count = len(deterministic)
        positive_ai = [
            item
            for item in ai_candidates if isinstance(ai_candidates, list)
            and isinstance(item, Mapping)
            and str(item.get("evidence_strength") or "")
            in {"strong", "medium", "weak"}
        ]
        undetermined_ai = [
            item
            for item in ai_candidates if isinstance(ai_candidates, list)
            and isinstance(item, Mapping)
            and item.get("classification") == "undetermined"
        ]
        ai_count = len(positive_ai)
        business_reason = str(business.get("reason") or "")
        business_available = bool(business.get("available"))
        confirmation = business.get("business_context_confirmation")
        confirmation_required = bool(
            isinstance(confirmation, Mapping)
            and confirmation.get("required")
        )
        purchase = self._observation_value(
            result,
            "purchase_prepayment_funding_candidates",
        )
        purchase_rows = purchase.get("purchase_candidates", [])
        purchase_count = len(purchase_rows) if isinstance(purchase_rows, list) else 0
        lead_purchase = (
            purchase_rows[0]
            if isinstance(purchase_rows, list)
            and purchase_rows
            and isinstance(purchase_rows[0], Mapping)
            else {}
        )
        purchase_detail = (
            f"{_money(lead_purchase.get('expense'))} 元｜"
            f"{str(lead_purchase.get('transaction_time') or '')[:10]}"
            if lead_purchase
            else "可靠字段内未发现明确下定支出"
        )
        extracted_business = (
            case_context.get("business_context", {})
            if isinstance(case_context, Mapping)
            else {}
        )
        manual_confirmation = (
            manual_context.get("manual_confirmation", {})
            if isinstance(manual_context, Mapping)
            else {}
        )
        if (
            isinstance(manual_confirmation, Mapping)
            and manual_confirmation.get("confirmation_status") == "confirmed"
        ):
            context_text = "已人工确认"
            business_content = str(
                manual_confirmation.get("confirmed_primary_business") or ""
            )
        elif (
            isinstance(extracted_business, Mapping)
            and extracted_business.get("declared_work_description")
        ):
            context_text = "已从系统资料提取"
            business_content = str(
                extracted_business.get("declared_work_description") or ""
            )
        else:
            context_text = "待人工补充" if confirmation_required else "状态已确认"
            business_content = ""
        purchase_business_body = (
            f"下定候选：{purchase_count} 笔\n{purchase_detail}\n\n"
            f"工作单位对照：{work_unit_status}\n"
            f"经营内容对照：{business_check_status}\n\n"
            f"经营上下文：{context_text}\n"
            + (
                f"经营内容：{redact_sensitive_text(business_content)}\n"
                if business_content
                else ""
            )
            + f"确定性文字/企业名称候选：{deterministic_count} 笔\n"
            f"AI 正向候选：{ai_count} 笔\n"
            f"待人工判断：{len(undetermined_ai)} 笔\n"
            f"AI：{'已启用并产生观察' if business_available else '未启用或不可用'}"
        )
        self.module_cards["purchase_business"].set_content(
            purchase_business_body,
            (
                "需补充实际主要经营内容和主要产品/服务；"
                "经营上下文待确认，未执行完整行业语义判断"
                if confirmation_required
                else (
                    "下定及此前收入仅为时间金额并列，不表示资金来源；"
                    f"{_business_reason_label(business_reason)}"
                    if not business_available
                    else "下定及此前收入仅为时间金额并列，不表示资金来源"
                )
            ),
            "orange" if confirmation_required or purchase_count else "mint",
            show_secondary=confirmation_required,
        )

        counterparties = self._observation_value(result, "top_counterparties")
        income_top = counterparties.get("income", [])
        expense_top = counterparties.get("expense", [])
        def counterparty_lines(rows: object) -> str:
            rendered = []
            for index, item in enumerate(
                rows[:3] if isinstance(rows, list) else [],
                start=1,
            ):
                if not isinstance(item, Mapping):
                    continue
                identity = (
                    mask_account(item.get("identity_value", ""))
                    if item.get("identity_field") == "counterparty_account"
                    else redact_sensitive_text(item.get("identity_value", ""))
                )
                rendered.append(
                    f"{index}. {identity} {_percentage(item.get('direction_amount_share'), 0)}"
                )
            return "\n".join(rendered) or "暂无可靠可识别对手"

        income_summary = counterparties.get("income_summary", {})
        expense_summary = counterparties.get("expense_summary", {})
        income_coverage = (
            income_summary.get("amount_coverage_rate")
            if isinstance(income_summary, Mapping)
            else None
        )
        expense_coverage = (
            expense_summary.get("amount_coverage_rate")
            if isinstance(expense_summary, Mapping)
            else None
        )
        all_top = [
            item
            for rows in (income_top, expense_top)
            for item in (rows if isinstance(rows, list) else [])
            if isinstance(item, Mapping)
        ]
        months = sorted(
            {
                str(month)
                for item in all_top
                for month in item.get("months", [])
            }
        )
        max_share = max(
            (
                Decimal(str(item.get("direction_amount_share") or "0"))
                for item in all_top
            ),
            default=Decimal("0"),
        )
        occurrences = self._observation_value(
            result,
            "cross_source_counterparty_occurrences",
        )
        occurrence_rows = occurrences.get("counterparties", [])
        relationship_body = (
            "收入主要对手：\n"
            f"{counterparty_lines(income_top)}\n\n"
            "支出主要对手：\n"
            f"{counterparty_lines(expense_top)}\n\n"
            f"可识别覆盖：收入 {_percentage(income_coverage)}｜"
            f"支出 {_percentage(expense_coverage)}\n"
            f"主要对手覆盖月份：{months[0] + ' 至 ' + months[-1] if months else '不可用'}\n"
            f"跨来源同名候选："
            f"{len(occurrence_rows) if isinstance(occurrence_rows, list) else 0} 项"
        )
        self.module_cards["counterparty"].set_content(
            relationship_body,
            (
                f"集中程度未自动定性；当前最高单一对手金额占比"
                f"{_percentage(max_share, 0)}。排名不表示对手关系"
                if all_top
                else "集中程度不可用：没有可靠可识别对手"
            ),
            "mint" if counterparties.get("available") else "muted",
        )

        large = self._observation_value(result, "large_transaction_candidates")
        large_rows = large.get("candidates", [])
        large_count = len(large_rows) if isinstance(large_rows, list) else 0
        large_income_count = sum(
            Decimal(str(item.get("income") or "0")) > 0
            for item in large_rows if isinstance(large_rows, list)
            and isinstance(item, Mapping)
        )
        large_expense_count = sum(
            Decimal(str(item.get("expense") or "0")) > 0
            for item in large_rows if isinstance(large_rows, list)
            and isinstance(item, Mapping)
        )
        proximity_counts: dict[int, int] = {}
        body = result.get("result", {})
        indicators = body.get("indicators", []) if isinstance(body, Mapping) else []
        for indicator in indicators if isinstance(indicators, list) else []:
            if (
                isinstance(indicator, Mapping)
                and indicator.get("indicator_type") == "fund_time_proximity"
            ):
                parameters = indicator.get("parameters", {})
                value = indicator.get("value", {})
                if isinstance(parameters, Mapping) and isinstance(value, Mapping):
                    proximity_counts[int(parameters.get("window_days", 0))] = int(
                        value.get("time_proximity_pair_count", 0)
                    )
        paths = self._observation_value(result, "large_inflow_balance_paths")
        path_rows = paths.get("candidates", [])
        low_retention = sum(
            any(
                isinstance(window, Mapping)
                and window.get("low_retained_balance_increment")
                for window in item.get("windows", [])
            )
            for item in path_rows if isinstance(path_rows, list)
            and isinstance(item, Mapping)
        )
        balance = self._observation_value(
            result,
            "end_of_day_balance_and_interest",
        )
        sources = balance.get("sources", [])
        balance_sources = [
            source
            for source in sources if isinstance(sources, list)
            and isinstance(source, Mapping)
            and source.get("balance_available")
        ]
        latest_balance = "不可用"
        latest_balance_date = "不可用"
        latest_candidates: list[tuple[str, object]] = []
        interest_records: list[Mapping[str, object]] = []
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, Mapping):
                continue
            stats = source.get("balance_statistics", {})
            ids = source.get("balance_snapshot_transaction_ids", [])
            if isinstance(stats, Mapping) and ids:
                transaction = evidence_transaction(result, str(ids[-1]))
                transaction_record = (
                    transaction.get("transaction", {})
                    if isinstance(transaction, Mapping)
                    else {}
                )
                if isinstance(transaction_record, Mapping):
                    latest_candidates.append(
                        (
                            str(transaction_record.get("transaction_time") or ""),
                            stats.get("closing"),
                        )
                    )
            interest_records.extend(
                item
                for item in source.get("interest_records", [])
                if isinstance(item, Mapping)
            )
        if latest_candidates:
            latest_date_value, latest_amount = max(latest_candidates)
            latest_balance = _money_compact(latest_amount)[0]
            latest_balance_date = latest_date_value[:10]
        recent_interest = max(
            (str(item.get("transaction_time") or "") for item in interest_records),
            default="",
        )
        cashflow = _indicator_by_type(result, "cashflow_scale_and_recent_change")
        cashflow_value = cashflow.get("value", {})
        comparison = (
            cashflow_value.get("recent_comparison", {})
            if isinstance(cashflow_value, Mapping)
            else {}
        )
        recent_change = (
            f"收入{_change_label(comparison.get('income_change'))}、"
            f"支出{_change_label(comparison.get('expense_change'))}"
            if isinstance(comparison, Mapping) and comparison.get("available")
            else "不足连续六个日历月，无法比较最近三个月"
        )
        funds_body = (
            f"最近可靠日末余额：{latest_balance}\n"
            f"余额日期：{latest_balance_date}｜余额字段："
            f"{'可用' if balance_sources else '不可用'}\n"
            f"结息记录：{len(interest_records)} 笔"
            + (f"｜最近 {recent_interest[:10]}" if recent_interest else "")
            + f"\n\n大额收入：{large_income_count} 笔｜大额支出：{large_expense_count} 笔\n"
            f"1/3/7日资金观察：{proximity_counts.get(1, 0)}/"
            f"{proximity_counts.get(3, 0)}/{proximity_counts.get(7, 0)} 组\n"
            f"低留存候选：{low_retention} 项\n\n"
            f"最近三个月：{recent_change}"
        )
        self.module_cards["funds_balance"].set_content(
            funds_body,
            (
                "时间并列不表示资金来源；不判断实际停留时长；"
                "日末余额不是日均余额；结息不能反推本金或偿债能力"
            ),
            "orange" if low_retention or max(proximity_counts.values(), default=0) else "mint",
        )

        self.module_summaries = {
            "manual": (
                f"待人工核实 {manual_count} 项；"
                + ("重点：" + "；".join(focus) if focus else "当前无确定性核实事项"),
                "仅供人工核实",
            ),
            "sensitive": (
                f"敏感候选 {sensitive_count} 项；{category_text}",
                "候选命中不代表风险",
            ),
            "declaration": (
                "直接命中 {direct_match}｜候选 {candidate_match}｜"
                "未发现 {no_evidence_in_reliable_fields}｜不可用 {unavailable}".format(
                    **declaration_counts
                ),
                "未发现或不可用不等于申报不真实",
            ),
            "purchase": (
                f"下定候选 {purchase_count} 笔；{purchase_detail}",
                "只展示可靠字段候选，不作购车归因",
            ),
            "business": (
                f"确定性候选 {deterministic_count}｜AI正向 {ai_count}｜"
                f"待人工判断 {len(undetermined_ai)}",
                (
                    "经营上下文待确认，未执行完整行业语义判断"
                    if confirmation_required
                    else _business_reason_label(business_reason)
                    if not business_available
                    else "AI观察可用，仍需结合交易证据人工核实"
                ),
            ),
            "funds": (
                f"大额收入 {large_income_count}｜大额支出 {large_expense_count}；"
                f"1/3/7日并列 {proximity_counts.get(1, 0)}/"
                f"{proximity_counts.get(3, 0)}/{proximity_counts.get(7, 0)}",
                "时间并列不表示资金来源",
            ),
            "balance": (
                f"最近可靠日末余额 {latest_balance}（{latest_balance_date}）；"
                f"结息 {len(interest_records)} 笔；{recent_change}",
                "日末余额不是日均余额；结息不能反推本金或偿债能力",
            ),
            "counterparty": (
                f"收入覆盖 {_percentage(income_coverage)}｜"
                f"支出覆盖 {_percentage(expense_coverage)}；"
                f"跨来源同名候选 "
                f"{len(occurrence_rows) if isinstance(occurrence_rows, list) else 0}",
                "排名只表示可靠字段金额汇总，不表示对手关系",
            ),
        }
        result_body = result.get("result", {})
        evidence = (
            result_body.get("evidence", {})
            if isinstance(result_body, Mapping)
            else {}
        )
        coverage = evidence.get("coverage", {}) if isinstance(evidence, Mapping) else {}
        self.evidence_summary.set_evidence(
            bool(summary.get("evidence_complete")),
            coverage.get("indexed_transaction_count", 0),
            coverage.get("resolved_evidence_link_count", 0),
            coverage.get("unresolved_evidence_link_count", 0),
            coverage.get("ambiguous_evidence_link_count", 0),
        )


class VerificationWorkspace(QWidget):
    selectCaseRequested = pyqtSignal()
    openCaseRequested = pyqtSignal()
    loadResultRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    legacyRequested = pyqtSignal()
    preparationConfirmed = pyqtSignal(object)
    preparationSkipped = pyqtSignal()
    preparationBackRequested = pyqtSignal()
    businessPreparationRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: Mapping[str, object] | None = None
        self._source_errors: list[str] = []
        self._recent_cases: list[str] = []
        self._active_section = "overview"
        self._active_module = "manual"
        self.setObjectName("briefWorkspace")
        self.setFont(QFont("Microsoft YaHei UI", 10))
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        navigation = QFrame()
        navigation.setObjectName("briefTopNavigation")
        nav_layout = QHBoxLayout(navigation)
        nav_layout.setContentsMargins(14, 10, 14, 10)
        nav_layout.setSpacing(8)
        brand = QLabel("BANKFLOW BRIEF")
        brand.setObjectName("briefBrand")
        nav_layout.addWidget(brand)
        nav_layout.addSpacing(20)
        self.navigation_buttons: list[FilterButton] = []
        self.navigation_by_route: dict[str, FilterButton] = {}

        def add_navigation_button(route: str, title: str) -> None:
            button = FilterButton(title)
            button.setProperty("route", route)
            button.clicked.connect(
                lambda checked, selected_route=route: self.navigate(selected_route)
            )
            self.navigation_buttons.append(button)
            self.navigation_by_route[route] = button
            nav_layout.addWidget(button)

        add_navigation_button("home", "首页")
        add_navigation_button("case", "当前案件")
        add_navigation_button("history", "历史案件")
        add_navigation_button("settings", "设置")
        self.navigation_by_route["home"].setChecked(True)
        self.navigation_by_route["case"].setEnabled(False)
        self.navigation_by_route["dashboard"] = self.navigation_by_route["case"]
        self.navigation_by_route["analysis"] = self.navigation_by_route["case"]
        nav_layout.addStretch(1)
        self.legacy_button = QPushButton("返回原流水工具")
        self.legacy_button.clicked.connect(self.legacyRequested)
        nav_layout.addWidget(self.legacy_button)
        root.addWidget(navigation)

        self.main_pages = QStackedWidget()
        self.welcome_page = WelcomePage()
        self.processing_page = ProcessingPage()
        self.preparation_page = CasePreparationPage()
        self.dashboard_page = CaseDashboardPage(include_case_header=False)
        self.module_summary_page = ModuleSummaryPage()
        self.transaction_list_panel = TransactionListPanel()
        self.module_detail_page = self.transaction_list_panel
        self.current_case_page = QWidget()
        case_layout = QVBoxLayout(self.current_case_page)
        case_layout.setContentsMargins(0, 0, 0, 0)
        case_layout.setSpacing(10)
        case_layout.addWidget(self.dashboard_page.header)
        case_layout.addWidget(self.dashboard_page.header_meta)
        self.case_content_pages = QStackedWidget()
        for page in (
            self.dashboard_page,
            self.module_summary_page,
            self.transaction_list_panel,
        ):
            self.case_content_pages.addWidget(page)
        case_layout.addWidget(self.case_content_pages, 1)
        self.history_page = self._simple_page(
            "历史案件",
            "最近处理案件显示在首页；已有 schema 1.16 结果可直接导入。",
        )
        self.settings_page = self._simple_page(
            "设置",
            "AI经营语义辅助默认关闭；只有在分析前确认页明确勾选并确认后"
            "才允许装载提供方配置。本页不展示或保存任何模型密钥。",
        )
        for page in (
            self.welcome_page,
            self.preparation_page,
            self.processing_page,
            self.current_case_page,
            self.history_page,
            self.settings_page,
        ):
            self.main_pages.addWidget(page)
        self.evidence_panel = EvidencePanel()
        self.evidence_panel.hide()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.main_pages)
        self.splitter.addWidget(self.evidence_panel)
        self.splitter.setCollapsible(1, True)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([1000, 0])
        root.addWidget(self.splitter, 1)

        self.welcome_page.newCaseRequested.connect(self.selectCaseRequested)
        self.welcome_page.openCaseRequested.connect(self.openCaseRequested)
        self.welcome_page.importResultRequested.connect(self.loadResultRequested)
        self.processing_page.cancelRequested.connect(self.cancelRequested)
        self.preparation_page.confirmed.connect(self.preparationConfirmed)
        self.preparation_page.skipped.connect(self.preparationSkipped)
        self.preparation_page.backRequested.connect(
            self.preparationBackRequested
        )
        self.dashboard_page.moduleRequested.connect(
            self.show_module_summary_for_module
        )
        self.dashboard_page.attentionRequested.connect(
            lambda: self.open_transaction_list("manual", "all")
        )
        self.dashboard_page.businessPreparationRequested.connect(
            self.businessPreparationRequested
        )
        self.module_summary_page.backRequested.connect(
            lambda: self.show_case_section("overview")
        )
        self.module_summary_page.categoryRequested.connect(
            self.open_transaction_list
        )
        self.module_summary_page.businessPreparationRequested.connect(
            self.businessPreparationRequested
        )
        self.transaction_list_panel.backRequested.connect(
            self._return_to_module_summary
        )
        self.transaction_list_panel.businessPreparationRequested.connect(
            self.businessPreparationRequested
        )
        self.transaction_list_panel.transactionSelected.connect(
            self._show_evidence_from_table
        )
        self.transaction_list_panel.selectionUnavailable.connect(
            self._show_unavailable_evidence
        )
        self.evidence_panel.closeRequested.connect(self.close_evidence)

        self.select_case_button = self.welcome_page.new_case_button
        self.load_result_button = self.welcome_page.import_result_button
        self.cancel_button = self.processing_page.cancel_button
        self.progress = self.processing_page.progress
        self.progress_label = self.processing_page.progress_label
        self.header = self.dashboard_page.header
        self.metrics = self.dashboard_page.metrics
        self.manual_table = self.transaction_list_panel.manual_table
        self.sensitive_table = self.transaction_list_panel.sensitive_table
        self.business_table = self.transaction_list_panel.business_table
        self.source_status = self.processing_page.source_status
        self.setStyleSheet(brief_stylesheet())

    def show_case_preparation(
        self,
        context: Mapping[str, object],
        manual_record: Mapping[str, object] | None = None,
        *,
        reanalysis: bool = False,
    ) -> None:
        self.preparation_page.set_context(
            context,
            manual_record,
            reanalysis=reanalysis,
        )
        self.main_pages.setCurrentWidget(self.preparation_page)
        self.close_evidence()

    def _simple_page(self, title: str, text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 28, 30, 28)
        heading = QLabel(title)
        heading.setObjectName("briefHeroTitle")
        note = QLabel(text)
        note.setObjectName("briefPageNote")
        note.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def set_page(self, index: int) -> None:
        routes = ("dashboard", "manual", "sensitive")
        if 0 <= index < len(routes):
            self.navigate(routes[index])

    def navigate(self, route: str) -> None:
        effective_route = "case" if route in {"dashboard", "analysis"} else route
        if effective_route == "home":
            self.main_pages.setCurrentWidget(self.welcome_page)
            self.close_evidence()
        elif effective_route == "case":
            if self._result is None:
                return
            self.main_pages.setCurrentWidget(self.current_case_page)
            self.show_case_section("overview")
            self.close_evidence()
        elif effective_route in {"manual", "sensitive", "evidence"}:
            if self._result is None:
                return
            self.show_module_summary_for_module(effective_route)
        elif effective_route == "history":
            self.main_pages.setCurrentWidget(self.history_page)
            self.close_evidence()
        elif effective_route == "settings":
            self.main_pages.setCurrentWidget(self.settings_page)
            self.close_evidence()
        for button in self.navigation_buttons:
            button.setChecked(str(button.property("route")) == effective_route)

    def show_case_section(self, section_key: str) -> None:
        if self._result is None:
            return
        resolved = (
            section_key
            if section_key in ModuleSummaryPage.SECTION_TITLES
            else "overview"
        )
        self._active_section = resolved
        self.main_pages.setCurrentWidget(self.current_case_page)
        if resolved == "overview":
            self.case_content_pages.setCurrentWidget(self.dashboard_page)
        else:
            self.module_summary_page.set_section(resolved)
            self.case_content_pages.setCurrentWidget(self.module_summary_page)
        self._set_top_route("case")
        self.close_evidence()

    def show_module_summary_for_module(self, module_key: str) -> None:
        if self._result is None:
            return
        section = self._section_for_module(module_key)
        self._active_section = section
        self._active_module = module_key
        self.main_pages.setCurrentWidget(self.current_case_page)
        self.module_summary_page.set_section(section, module_key)
        self.case_content_pages.setCurrentWidget(self.module_summary_page)
        self._set_top_route("case")
        self.close_evidence()

    def open_transaction_list(
        self,
        module_key: str,
        view_filter: str = "all",
    ) -> None:
        if (
            self._result is None
            or module_key
            not in {"manual", "sensitive", "business"}
        ):
            return
        self._active_module = module_key
        section = self._section_for_module(module_key)
        self._active_section = section
        summary_text, status_text = self.dashboard_page.module_summaries.get(
            module_key,
            ("等待标准结果。", "不可用"),
        )
        summary = f"{summary_text}\n{status_text}"
        section_title = ModuleSummaryPage.SECTION_TITLES[section]
        module_title = TransactionListPanel.MODULE_TITLES[module_key]
        filter_suffix = (
            f" > {BUSINESS_FILTER_LABELS.get(view_filter, '正向候选')}"
            if module_key == "business"
            else ""
        )
        self.transaction_list_panel.set_module(
            module_key,
            summary,
            view_filter=view_filter,
            breadcrumb=(
                f"当前案件 > {section_title} > {module_title}{filter_suffix}"
            ),
        )
        self.main_pages.setCurrentWidget(self.current_case_page)
        self.case_content_pages.setCurrentWidget(self.transaction_list_panel)
        self._set_top_route("case")
        self.close_evidence()

    def _return_to_module_summary(self) -> None:
        self.show_module_summary_for_module(self._active_module)

    def _section_for_module(self, module_key: str) -> str:
        mapping = {
            "verification_declaration": "verification_declaration",
            "manual": "verification_declaration",
            "sensitive": "verification_declaration",
            "declaration": "verification_declaration",
            "purchase_business": "purchase_business",
            "purchase": "purchase_business",
            "business": "purchase_business",
            "funds": "funds_balance",
            "balance": "funds_balance",
            "funds_balance": "funds_balance",
            "counterparty": "counterparty",
            "evidence": "evidence_center",
        }
        return mapping.get(module_key, "overview")

    def _set_top_route(self, route: str) -> None:
        for button in self.navigation_buttons:
            button.setChecked(str(button.property("route")) == route)

    def set_busy(self, case_name: str, total_sources: int) -> None:
        self._result = None
        self._source_errors = []
        self.processing_page.start(case_name, total_sources)
        self.transaction_list_panel.set_result(None)
        self.navigation_by_route["case"].setEnabled(False)
        self.main_pages.setCurrentWidget(self.processing_page)
        self.close_evidence()

    def set_progress(self, completed: int, total: int, message: str) -> None:
        self.processing_page.set_progress(completed, total, message)

    def add_source_error(self, source_file: str, message: str) -> None:
        self._source_errors.append(f"{Path(source_file).name}：{message}")
        self.processing_page.add_source_error(source_file, message)

    def set_cancel_pending(self) -> None:
        self.processing_page.set_cancel_pending()

    def set_cancelled(self) -> None:
        self.processing_page.stop(
            "任务已取消；未完成来源未作为完整案件结果展示。"
        )

    def set_result(
        self,
        result: Mapping[str, object],
        case_name: str = "",
        source_messages: list[str] | None = None,
        case_context: Mapping[str, object] | None = None,
        manual_context: Mapping[str, object] | None = None,
    ) -> None:
        validated = validate_standard_result(result)
        self._result = validated
        summary = self.dashboard_page.set_result(
            validated,
            case_name,
            case_context=case_context,
            manual_context=manual_context,
        )
        self.transaction_list_panel.set_result(validated)
        module_summaries = dict(self.dashboard_page.module_summaries)
        module_summaries["evidence"] = (
            self.dashboard_page.evidence_summary.detail_label.text(),
            self.dashboard_page.evidence_summary.status_label.text(),
        )
        self.module_summary_page.set_module_summaries(module_summaries)
        self.progress.setValue(100)
        self.processing_page.stop(
            f"schema {summary['schema_version']} 已就绪。"
        )
        resolved_name = str(summary["case_name"])
        self._recent_cases = [
            resolved_name,
            *(name for name in self._recent_cases if name != resolved_name),
        ][:5]
        self.welcome_page.set_recent_cases(self._recent_cases)
        self.navigation_by_route["case"].setEnabled(True)
        self.main_pages.setCurrentWidget(self.current_case_page)
        self.show_case_section("overview")
        self.close_evidence()

    def show_result_error(self, message: str) -> None:
        self.processing_page.stop(message)
        self.progress.setValue(0)
        self.main_pages.setCurrentWidget(self.processing_page)

    def show_evidence(self, transaction_id: str) -> None:
        if self._result is None:
            return
        self.evidence_panel.set_context(self._result, [transaction_id], transaction_id)
        self._open_evidence_panel()

    def open_module(self, module_key: str) -> None:
        self.show_module_summary_for_module(module_key)

    def _show_evidence_from_table(
        self,
        transaction_id: str,
        source_table: object,
    ) -> None:
        if self._result is None or not isinstance(source_table, PagedTable):
            return
        self.evidence_panel.set_context(
            self._result,
            source_table.model.transaction_ids(),
            transaction_id,
        )
        self._open_evidence_panel()

    def _show_unavailable_evidence(self, message: str) -> None:
        self.evidence_panel.show_unavailable(message)
        self._open_evidence_panel()

    def _open_evidence_panel(self) -> None:
        self.evidence_panel.show()
        width = max(360, min(480, self.width() // 3))
        self.splitter.setSizes([max(600, self.width() - width), width])

    def close_evidence(self) -> None:
        self.evidence_panel.hide()
        self.splitter.setSizes([max(1, self.width()), 0])


def brief_stylesheet() -> str:
    return f"""
    QWidget#briefWorkspace {{
        background: {BriefTheme.BG};
        color: {BriefTheme.INK};
        font-family: "Microsoft YaHei UI";
    }}
    QFrame#briefTopNavigation {{
        background: {BriefTheme.INK};
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
    }}
    QLabel#briefBrand {{
        color: {BriefTheme.SURFACE};
        font-size: 25px;
        font-weight: 900;
        letter-spacing: 1px;
    }}
    QLabel#briefNavigationGroup {{
        margin-top: 8px;
        padding: 5px 4px 2px 4px;
        color: {BriefTheme.MINT};
        font-size: 12px;
        font-weight: 900;
    }}
    QLabel#briefEyebrow, QLabel#briefSectionNumber {{
        color: {BriefTheme.ORANGE};
        font-size: 12px;
        font-weight: 900;
    }}
    QLabel#briefTitle {{
        color: {BriefTheme.INK};
        font-size: 30px;
        font-weight: 900;
    }}
    QLabel#briefHeroTitle {{
        color: {BriefTheme.INK};
        font-size: 36px;
        font-weight: 900;
    }}
    QLabel#briefActionTitle {{
        color: {BriefTheme.INK};
        font-size: 22px;
        font-weight: 900;
    }}
    QLabel#briefBreadcrumb {{
        color: {BriefTheme.MUTED};
        font-size: 13px;
        font-weight: 800;
    }}
    QLabel#briefSubtitle, QLabel#briefProgressLabel, QLabel#briefPageNote {{
        color: {BriefTheme.MUTED};
        font-size: 13px;
    }}
    QLabel#briefHeaderFacts {{
        color: {BriefTheme.INK};
        font-size: 13px;
        font-weight: 800;
    }}
    QLabel#briefError {{
        padding: 7px 10px;
        color: {BriefTheme.RED};
        background: #FFE0D9;
        border-left: 5px solid {BriefTheme.RED};
        font-size: 13px;
        font-weight: 900;
    }}
    QLineEdit[invalid="true"] {{
        border: 2px solid {BriefTheme.RED};
        background: #FFF1ED;
    }}
    QLabel#briefSectionTitle {{
        color: {BriefTheme.INK};
        font-size: 22px;
        font-weight: 900;
    }}
    QLabel#briefMetricValue {{
        color: {BriefTheme.INK};
        font-size: 23px;
        font-weight: 900;
    }}
    QLabel#briefMetricValue[compact="true"] {{
        font-size: 17px;
    }}
    QLabel#briefMetricLabel, QLabel#briefCardText {{
        color: {BriefTheme.INK};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#briefCombinedCardText {{
        color: {BriefTheme.INK};
        font-size: 13px;
        font-weight: 650;
        line-height: 1.35;
    }}
    QFrame#briefFutureCapabilities {{
        background: {BriefTheme.SURFACE_STRONG};
        border: 1px solid {BriefTheme.INK};
    }}
    QFrame#briefKeyMetricCell {{
        background: #F7EBCF;
        border: 0;
    }}
    QFrame#briefKeyMetricCell[tone="mint"] {{ background: #D9F2E8; }}
    QFrame#briefKeyMetricCell[tone="orange"] {{ background: #FFE0C7; }}
    QFrame#briefKeyMetricCell[tone="yellow"] {{ background: #FFF0B8; }}
    QFrame#briefKeyMetricCell[tone="strong"] {{ background: {BriefTheme.SURFACE_STRONG}; }}
    QLabel#briefAnalysisGroup {{
        margin-top: 4px;
        color: {BriefTheme.MUTED};
        font-size: 13px;
        font-weight: 900;
    }}
    QLabel#briefCardTitle {{
        color: {BriefTheme.INK};
        font-size: 16px;
        font-weight: 900;
    }}
    QLabel#briefModuleValue {{
        color: {BriefTheme.INK};
        font-size: 28px;
        font-weight: 900;
    }}
    QLabel#briefModuleStatus {{
        padding: 4px 7px;
        color: {BriefTheme.INK};
        background: #D8D1C3;
        border: 1px solid {BriefTheme.INK};
        font-size: 11px;
        font-weight: 800;
    }}
    QLabel#briefModuleStatus[tone="mint"] {{ background: {BriefTheme.MINT}; }}
    QLabel#briefModuleStatus[tone="orange"] {{ background: {BriefTheme.ORANGE}; }}
    QPushButton {{
        min-height: 36px;
        padding: 0 14px;
        color: {BriefTheme.INK};
        background: {BriefTheme.SURFACE};
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
        border-radius: 2px;
        font-weight: 800;
    }}
    QPushButton:hover {{
        background: {BriefTheme.SURFACE_STRONG};
    }}
    QPushButton:pressed {{
        padding-top: 2px;
        padding-left: 16px;
        background: {BriefTheme.YELLOW};
    }}
    QPushButton:disabled {{
        color: #8F8A80;
        background: #D8D1C3;
        border-color: #8F8A80;
    }}
    QPushButton#briefPrimaryButton {{
        background: {BriefTheme.ORANGE};
        color: {BriefTheme.INK};
    }}
    QPushButton#briefAttentionButton {{
        min-height: 46px;
        text-align: left;
        background: {BriefTheme.SURFACE};
        border-left: 8px solid {BriefTheme.ORANGE};
    }}
    QPushButton#briefCandidateCategoryButton {{
        background: {BriefTheme.SURFACE_STRONG};
        border-left: 6px solid {BriefTheme.MINT};
    }}
    QPushButton#briefFilterButton {{
        text-align: left;
        color: {BriefTheme.SURFACE};
        background: {BriefTheme.INK};
        border-color: {BriefTheme.SURFACE};
    }}
    QPushButton#briefFilterButton:checked {{
        color: {BriefTheme.INK};
        background: {BriefTheme.MINT};
        border-color: {BriefTheme.INK};
    }}
    QPushButton#briefFilterButton[nested="true"] {{
        margin-left: 12px;
    }}
    QPushButton#briefFilterButton:disabled {{
        color: #8C887F;
        border-color: #67635B;
        background: {BriefTheme.INK};
    }}
    QProgressBar#briefProgress {{
        min-height: 16px;
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
        border-radius: 0;
        background: {BriefTheme.SURFACE};
        text-align: center;
        color: {BriefTheme.INK};
    }}
    QProgressBar#briefProgress::chunk {{
        background: {BriefTheme.MINT};
    }}
    QTableView {{
        background: {BriefTheme.SURFACE};
        alternate-background-color: #F7EBCF;
        color: {BriefTheme.INK};
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
        gridline-color: {BriefTheme.INK};
        selection-background-color: {BriefTheme.YELLOW};
        selection-color: {BriefTheme.INK};
    }}
    QHeaderView::section {{
        background: {BriefTheme.INK};
        color: {BriefTheme.SURFACE};
        border: 0;
        border-right: 1px solid {BriefTheme.SURFACE};
        padding: 8px;
        font-weight: 900;
    }}
    QPlainTextEdit {{
        background: {BriefTheme.SURFACE};
        color: {BriefTheme.INK};
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
        border-radius: 0;
        padding: 8px;
        selection-background-color: {BriefTheme.YELLOW};
    }}
    QLabel#briefStatusBadge {{
        min-width: 88px;
        padding: 5px 9px;
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
        color: {BriefTheme.INK};
        background: #D8D1C3;
        font-weight: 900;
    }}
    QLabel#briefStatusBadge[tone="mint"] {{ background: {BriefTheme.MINT}; }}
    QLabel#briefStatusBadge[tone="orange"] {{ background: {BriefTheme.ORANGE}; }}
    QLabel#briefStatusBadge[tone="red"] {{ background: {BriefTheme.RED}; }}
    """
