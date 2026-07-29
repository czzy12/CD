"""PyQt6 verification workbench for the schema 1.16 vertical slice."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        self.setMinimumHeight(132)
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
        layout.addWidget(self.eyebrow)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

    def set_summary(
        self,
        case_name: str,
        period_start: str,
        period_end: str,
        status: str,
    ) -> None:
        self.title.setText(case_name)
        period = "覆盖期间不可用"
        if period_start or period_end:
            period = f"{str(period_start)[:10] or '未知'} → {str(period_end)[:10] or '未知'}"
        self.subtitle.setText(f"核查日期：当前任务 · {period} · {status}")


class MetricCard(HardShadowCard):
    def __init__(
        self,
        label: str,
        value: str = "0",
        accent: str = BriefTheme.SURFACE,
        parent: QWidget | None = None,
    ):
        super().__init__(accent, parent)
        self.setMinimumSize(QSize(145, 105))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 20, 18)
        layout.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("briefMetricValue")
        self.caption_label = QLabel(label)
        self.caption_label.setObjectName("briefMetricLabel")
        self.caption_label.setWordWrap(True)
        layout.addWidget(self.value_label)
        layout.addWidget(self.caption_label)
        layout.addStretch(1)

    def set_value(self, value: object) -> None:
        text = str(value)
        self.value_label.setProperty("compact", len(text) > 10)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)
        self.value_label.setText(text)
        self.value_label.setToolTip(text)


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


class ReviewItemCard(ObservationCard):
    pass


class EmptyStateCard(ObservationCard):
    def __init__(self, text: str):
        super().__init__("当前状态", text)


class ResultListModel(QAbstractTableModel):
    """Paged view over a standard result; stores no Transaction objects."""

    MANUAL_HEADERS = ("状态", "人工核实事项", "触发原因", "证据数", "交易ID")
    SENSITIVE_HEADERS = (
        "状态",
        "命中词",
        "日期",
        "方向",
        "金额",
        "交易对手",
        "来源文件",
        "交易ID",
    )

    def __init__(self, kind: str, page_size: int = 50, parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self.page_size = page_size
        self.page = 0
        self._result: Mapping[str, object] | None = None
        self._row_indices: range = range(0)

    @property
    def headers(self) -> tuple[str, ...]:
        return self.MANUAL_HEADERS if self.kind == "manual" else self.SENSITIVE_HEADERS

    def _rows(self) -> list[object]:
        if self._result is None:
            return []
        if self.kind == "manual":
            return manual_verification_questions(self._result)
        return sensitive_transaction_candidates(self._result)

    def set_result(self, result: Mapping[str, object] | None) -> None:
        self.beginResetModel()
        self._result = result
        self.page = 0
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
                short_transaction_id(evidence_ids[0]) if evidence_ids else "无直接交易证据",
            )
        else:
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
                short_transaction_id(item.get("transaction_id")),
            )
        value = values[index.column()]
        return str(value) if role == Qt.ItemDataRole.DisplayRole else str(value)

    def page_count(self) -> int:
        count = len(self._row_indices)
        return max(1, (count + self.page_size - 1) // self.page_size)

    def total_count(self) -> int:
        return len(self._row_indices)

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
    def __init__(self, parent: QWidget | None = None):
        super().__init__(BriefTheme.SURFACE, parent)
        self.setMinimumWidth(360)
        self.setMaximumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 24, 22)
        layout.setSpacing(10)
        header = SectionHeader("E", "交易证据详情")
        self.status = StatusBadge("等待左侧选择", "muted")
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
        layout.addWidget(header)
        layout.addWidget(self.status, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details, 1)

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
        self.status.set_status("引用完整" if complete else "需复核", "mint" if complete else "red")
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
        lines = [
            f"交易ID：{short_transaction_id(transaction_id)}",
            f"日期：{str(transaction.get('transaction_time') or '')[:19]}",
            f"方向：{direction}",
            f"金额：{amount}",
            *text_fields,
            "",
            f"来源文件：{Path(str(transaction.get('source_file') or '')).name}",
            f"页码：{transaction.get('page_no')}",
            f"行号：{transaction.get('row_no')}",
            f"证据定位：{transaction.get('evidence_locator') or '不可用'}",
            f"引用状态：{reference_text}",
            f"整体完整性：{'完整' if integrity.get('complete') else '存在缺失、重复或悬空/歧义'}",
        ]
        if raw_values:
            lines.extend(["", "原始字段（已脱敏）：", *raw_values])
        self.details.setPlainText("\n".join(lines))

    def show_unavailable(self, message: str) -> None:
        self.status.set_status("无直接交易证据", "red")
        self.details.setPlainText(message)


class VerificationWorkspace(QWidget):
    selectCaseRequested = pyqtSignal()
    loadResultRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    legacyRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: Mapping[str, object] | None = None
        self._source_errors: list[str] = []
        self.setObjectName("briefWorkspace")
        self.setFont(QFont("Microsoft YaHei UI", 10))
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(18)

        navigation = QFrame()
        navigation.setObjectName("briefNavigation")
        navigation.setFixedWidth(220)
        nav_layout = QVBoxLayout(navigation)
        nav_layout.setContentsMargins(14, 16, 14, 16)
        nav_layout.setSpacing(8)
        brand = QLabel("BANKFLOW\nBRIEF")
        brand.setObjectName("briefBrand")
        nav_layout.addWidget(brand)
        nav_layout.addSpacing(10)
        self.navigation_buttons: list[FilterButton] = []
        for index, title in enumerate(
            (
                "01  概览",
                "02  人工核实",
                "03  敏感交易",
                "04  经营关联 · 后续",
                "05  下定购车 · 后续",
                "06  交易对手 · 后续",
                "07  资金观察 · 后续",
                "08  余额结息 · 后续",
                "09  申报对照 · 后续",
                "10  证据总表 · 后续",
            )
        ):
            button = FilterButton(title)
            if index >= 3:
                button.setEnabled(False)
            else:
                button.clicked.connect(lambda checked, page=index: self.set_page(page))
            self.navigation_buttons.append(button)
            nav_layout.addWidget(button)
        self.navigation_buttons[0].setChecked(True)
        nav_layout.addStretch(1)
        self.legacy_button = QPushButton("返回原流水工具")
        self.legacy_button.clicked.connect(self.legacyRequested)
        nav_layout.addWidget(self.legacy_button)
        root.addWidget(navigation)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(14)
        action_row = QHBoxLayout()
        self.select_case_button = QPushButton("选择案例目录")
        self.select_case_button.setObjectName("briefPrimaryButton")
        self.load_result_button = QPushButton("打开标准结果JSON")
        self.load_result_button.setToolTip(
            "打开以前保存的schema 1.16 JSON，跳过PDF重新解析并直接查看结果。"
        )
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        self.select_case_button.clicked.connect(self.selectCaseRequested)
        self.load_result_button.clicked.connect(self.loadResultRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        action_row.addWidget(self.select_case_button)
        action_row.addWidget(self.load_result_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        center_layout.addLayout(action_row)
        self.header = BriefPageHeader()
        center_layout.addWidget(self.header)

        self.progress = QProgressBar()
        self.progress.setObjectName("briefProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_label = QLabel("等待选择案例或加载schema 1.16标准结果。")
        self.progress_label.setObjectName("briefProgressLabel")
        center_layout.addWidget(self.progress)
        center_layout.addWidget(self.progress_label)

        self.pages = QStackedWidget()
        self.overview_page = self._build_overview_page()
        self.manual_page, self.manual_table = self._build_table_page(
            "02",
            "人工核实事项",
            "问题只用于人工确认，不预设客户陈述虚假或形成准入结论。",
            "manual",
        )
        self.sensitive_page, self.sensitive_table = self._build_table_page(
            "03",
            "敏感交易候选",
            "候选只表示可靠文字字段命中，不表示真实事件、异常或风险。",
            "sensitive",
        )
        self.pages.addWidget(self.overview_page)
        self.pages.addWidget(self.manual_page)
        self.pages.addWidget(self.sensitive_page)
        center_layout.addWidget(self.pages, 1)
        root.addWidget(center, 1)

        self.evidence_panel = EvidencePanel()
        self.manual_table.transactionSelected.connect(self.show_evidence)
        self.sensitive_table.transactionSelected.connect(self.show_evidence)
        self.manual_table.selectionUnavailable.connect(
            self.evidence_panel.show_unavailable
        )
        self.sensitive_table.selectionUnavailable.connect(
            self.evidence_panel.show_unavailable
        )
        root.addWidget(self.evidence_panel)
        self.setStyleSheet(brief_stylesheet())

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(SectionHeader("01", "By the Numbers"))
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        definitions = (
            ("source_count", "资料来源", BriefTheme.ORANGE),
            ("transaction_count", "交易笔数", BriefTheme.SURFACE),
            ("income_sum", "收入合计", BriefTheme.MINT),
            ("expense_sum", "支出合计", BriefTheme.RED),
            ("manual_question_count", "人工核实", BriefTheme.YELLOW),
            ("sensitive_candidate_count", "敏感候选", BriefTheme.ORANGE),
        )
        self.metrics: dict[str, MetricCard] = {}
        for key, label, accent in definitions:
            card = MetricCard(label, "0", accent)
            self.metrics[key] = card
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        layout.addWidget(SectionHeader("02", "The One Idea · 最需人工关注"))
        self.attention_card = ReviewItemCard(
            "等待标准结果",
            "生成或加载结果后，这里只展示最需要人工核实的事项，不形成风险结论。",
        )
        layout.addWidget(self.attention_card)
        layout.addWidget(SectionHeader("03", "来源处理与可用性"))
        self.source_status = QPlainTextEdit()
        self.source_status.setReadOnly(True)
        self.source_status.setMaximumHeight(140)
        self.source_status.setPlainText("尚未处理来源文件。")
        layout.addWidget(self.source_status)
        layout.addStretch(1)
        return page

    def _build_table_page(
        self,
        number: str,
        title: str,
        note: str,
        kind: str,
    ) -> tuple[QWidget, PagedTable]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(SectionHeader(number, title))
        note_label = QLabel(note)
        note_label.setObjectName("briefPageNote")
        note_label.setWordWrap(True)
        layout.addWidget(note_label)
        table = PagedTable(kind)
        layout.addWidget(table, 1)
        return page, table

    def set_page(self, index: int) -> None:
        if not 0 <= index < self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.navigation_buttons[:3]):
            button.setChecked(button_index == index)

    def set_busy(self, case_name: str, total_sources: int) -> None:
        self._result = None
        self._source_errors = []
        self.select_case_button.setEnabled(False)
        self.load_result_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setValue(0)
        self.progress_label.setText(f"准备处理 {total_sources} 个来源文件…")
        self.header.set_summary(case_name, "", "", "正在生成标准结果")
        self.source_status.setPlainText("任务已启动，等待来源处理状态。")
        self.manual_table.set_result(None)
        self.sensitive_table.set_result(None)

    def set_progress(self, completed: int, total: int, message: str) -> None:
        value = int(completed * 100 / total) if total else 0
        self.progress.setValue(max(0, min(100, value)))
        self.progress_label.setText(message)

    def add_source_error(self, source_file: str, message: str) -> None:
        self._source_errors.append(f"{Path(source_file).name}：{message}")
        self.source_status.setPlainText("\n".join(self._source_errors))

    def set_cancel_pending(self) -> None:
        self.progress_label.setText("正在取消，等待当前来源处理结束…")
        self.cancel_button.setEnabled(False)

    def set_cancelled(self) -> None:
        self._set_idle_buttons()
        self.progress_label.setText("任务已取消；未完成来源未作为完整案件结果展示。")

    def set_result(
        self,
        result: Mapping[str, object],
        case_name: str = "",
        source_messages: list[str] | None = None,
    ) -> None:
        validated = validate_standard_result(result)
        self._result = validated
        summary = result_summary(validated, case_name)
        status = "证据完整" if summary["evidence_complete"] else "证据需复核"
        self.header.set_summary(
            str(summary["case_name"]),
            str(summary["period_start"]),
            str(summary["period_end"]),
            status,
        )
        for key, card in self.metrics.items():
            value = summary.get(key, 0)
            if key in {"income_sum", "expense_sum"}:
                value = _money(value)
            card.set_value(value)
        questions = manual_verification_questions(validated)
        if questions and isinstance(questions[0], Mapping):
            self.attention_card.title_label.setText(
                "需关注（仅供参考）"
                if questions[0].get("attention_hint_only")
                else "待人工核实"
            )
            self.attention_card.text_label.setText(
                redact_sensitive_text(questions[0].get("question_text", ""))
            )
        else:
            self.attention_card.title_label.setText("暂无人工核实事项")
            self.attention_card.text_label.setText(
                "仅表示当前确定性观察没有生成问题，不代表不存在其他需核实事项。"
            )
        self.manual_table.set_result(validated)
        self.sensitive_table.set_result(validated)
        self.progress.setValue(100)
        self.progress_label.setText(
            f"schema {summary['schema_version']} 已就绪；点击列表行查看交易证据。"
        )
        messages = list(source_messages or [])
        if self._source_errors:
            messages.extend(self._source_errors)
        if not messages:
            messages = [
                f"{item.get('source_file', '')}：已纳入，{item.get('transaction_count', 0)} 笔"
                for item in validated.get("source_files", [])
                if isinstance(item, Mapping)
            ]
        self.source_status.setPlainText("\n".join(messages) or "来源状态不可用。")
        self._set_idle_buttons()

    def show_result_error(self, message: str) -> None:
        self._set_idle_buttons()
        self.progress.setValue(0)
        self.progress_label.setText(message)
        self.header.set_summary("标准结果不可用", "", "", "版本或结构不兼容")

    def _set_idle_buttons(self) -> None:
        self.select_case_button.setEnabled(True)
        self.load_result_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def show_evidence(self, transaction_id: str) -> None:
        if self._result is None:
            return
        self.evidence_panel.show_transaction(self._result, transaction_id)


def brief_stylesheet() -> str:
    return f"""
    QWidget#briefWorkspace {{
        background: {BriefTheme.BG};
        color: {BriefTheme.INK};
        font-family: "Microsoft YaHei UI";
    }}
    QFrame#briefNavigation {{
        background: {BriefTheme.INK};
        border: {BriefTheme.BORDER}px solid {BriefTheme.INK};
    }}
    QLabel#briefBrand {{
        color: {BriefTheme.SURFACE};
        font-size: 25px;
        font-weight: 900;
        letter-spacing: 1px;
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
    QLabel#briefSubtitle, QLabel#briefProgressLabel, QLabel#briefPageNote {{
        color: {BriefTheme.MUTED};
        font-size: 13px;
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
    QLabel#briefCardTitle {{
        color: {BriefTheme.INK};
        font-size: 16px;
        font-weight: 900;
    }}
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
    QLabel#briefStatusBadge[tone="red"] {{ background: {BriefTheme.RED}; }}
    """
