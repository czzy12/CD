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
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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


class AnalysisModuleCard(HardShadowCard):
    clicked = pyqtSignal(str)

    def __init__(
        self,
        module_key: str,
        number: str,
        title: str,
        parent: QWidget | None = None,
    ):
        super().__init__(BriefTheme.SURFACE, parent)
        self.module_key = module_key
        self.setMinimumHeight(170)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 22, 20)
        layout.setSpacing(6)
        eyebrow = QLabel(f"// {number} · ANALYSIS")
        eyebrow.setObjectName("briefEyebrow")
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
        self.open_button = QPushButton("查看详情 →")
        self.open_button.clicked.connect(lambda: self.clicked.emit(self.module_key))
        layout.addWidget(eyebrow)
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
    settingsRequested = pyqtSignal()

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
        settings_row = QHBoxLayout()
        settings_row.addStretch(1)
        self.settings_button = QPushButton("设置")
        self.settings_button.clicked.connect(self.settingsRequested)
        settings_row.addWidget(self.settings_button)
        layout.addLayout(settings_row)
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


class ModuleDetailPage(QWidget):
    backRequested = pyqtSignal()
    transactionSelected = pyqtSignal(str, object)
    selectionUnavailable = pyqtSignal(str)

    MODULE_TITLES = {
        "manual": ("01", "人工核实"),
        "sensitive": ("02", "敏感交易"),
        "business": ("03", "经营关联"),
        "purchase": ("04", "下定购车"),
        "counterparty": ("05", "交易对手"),
        "funds": ("06", "资金观察"),
        "balance": ("07", "余额与月度"),
        "declaration": ("08", "申报对照"),
        "evidence": ("09", "证据总表"),
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: Mapping[str, object] | None = None
        self._module_key = "manual"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        breadcrumb = QHBoxLayout()
        self.back_button = QPushButton("案件概览")
        self.back_button.clicked.connect(self.backRequested)
        self.breadcrumb_label = QLabel("案件概览 > 人工核实")
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
        self.tables = QStackedWidget()
        self.manual_table = PagedTable("manual")
        self.sensitive_table = PagedTable("sensitive")
        self.generic_table = QTableView()
        self.generic_table.setModel(ResultListModel("manual", parent=self.generic_table))
        self.generic_table.setEnabled(False)
        self.tables.addWidget(self.manual_table)
        self.tables.addWidget(self.sensitive_table)
        self.tables.addWidget(self.generic_table)
        layout.addWidget(self.tables, 1)
        for table in (self.manual_table, self.sensitive_table):
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

    def set_module(self, module_key: str, summary: str) -> None:
        self._module_key = module_key
        number, title = self.MODULE_TITLES[module_key]
        self.breadcrumb_label.setText(f"案件概览 > {title}")
        self.title.setText(f"{number} · {title}")
        self.summary.setText(summary)
        if module_key == "manual":
            self.tables.setCurrentWidget(self.manual_table)
        elif module_key == "sensitive":
            self.tables.setCurrentWidget(self.sensitive_table)
        else:
            self.tables.setCurrentWidget(self.generic_table)


class CaseDashboardPage(QScrollArea):
    moduleRequested = pyqtSignal(str)

    MODULES = (
        ("manual", "01", "人工核实"),
        ("sensitive", "02", "敏感交易"),
        ("business", "03", "经营关联"),
        ("purchase", "04", "下定购车"),
        ("counterparty", "05", "交易对手"),
        ("funds", "06", "资金观察"),
        ("balance", "07", "余额与月度"),
        ("declaration", "08", "申报对照"),
        ("evidence", "09", "证据总表"),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.setWidget(self.container)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)
        self.header = BriefPageHeader()
        layout.addWidget(self.header)
        header_meta = QHBoxLayout()
        self.completed_badge = StatusBadge("已完成", "mint")
        self.schema_badge = StatusBadge("schema 1.16", "mint")
        self.evidence_badge = StatusBadge("证据待核验", "muted")
        header_meta.addWidget(self.completed_badge)
        header_meta.addWidget(self.schema_badge)
        header_meta.addWidget(self.evidence_badge)
        header_meta.addStretch(1)
        layout.addLayout(header_meta)
        layout.addWidget(SectionHeader("DATA", "关键数据"))
        self.metric_grid = QGridLayout()
        self.metric_grid.setSpacing(10)
        definitions = (
            ("source_count", "资料来源", BriefTheme.ORANGE),
            ("transaction_count", "交易笔数", BriefTheme.SURFACE),
            ("income_sum", "收入合计", BriefTheme.MINT),
            ("expense_sum", "支出合计", BriefTheme.SURFACE_STRONG),
            ("manual_question_count", "人工核实", BriefTheme.YELLOW),
            ("sensitive_candidate_count", "敏感候选", BriefTheme.ORANGE),
        )
        self.metrics: dict[str, MetricCard] = {}
        for key, label, accent in definitions:
            self.metrics[key] = MetricCard(label, "0", accent)
        layout.addLayout(self.metric_grid)
        layout.addWidget(SectionHeader("FOCUS", "最需人工关注"))
        self.attention_container = QWidget()
        self.attention_layout = QVBoxLayout(self.attention_container)
        self.attention_layout.setContentsMargins(0, 0, 0, 0)
        self.attention_layout.setSpacing(8)
        layout.addWidget(self.attention_container)
        layout.addWidget(SectionHeader("MODULES", "分析模块"))
        self.module_grid = QGridLayout()
        self.module_grid.setSpacing(14)
        self.module_cards: dict[str, AnalysisModuleCard] = {}
        for key, number, title in self.MODULES:
            card = AnalysisModuleCard(key, number, title)
            card.clicked.connect(self.moduleRequested)
            self.module_cards[key] = card
        layout.addLayout(self.module_grid)
        layout.addStretch(1)
        self._columns = 0
        self._reflow(3)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow(2 if self.viewport().width() < 930 else 3)

    def _reflow(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for card in self.metrics.values():
            self.metric_grid.removeWidget(card)
        for index, card in enumerate(self.metrics.values()):
            self.metric_grid.addWidget(card, index // columns, index % columns)
        for card in self.module_cards.values():
            self.module_grid.removeWidget(card)
        for index, card in enumerate(self.module_cards.values()):
            self.module_grid.addWidget(card, index // columns, index % columns)

    def set_result(
        self,
        result: Mapping[str, object],
        case_name: str,
    ) -> dict[str, object]:
        summary = result_summary(result, case_name)
        status = "证据完整" if summary["evidence_complete"] else "证据需复核"
        self.header.set_summary(
            str(summary["case_name"]),
            str(summary["period_start"]),
            str(summary["period_end"]),
            status,
        )
        self.header.eyebrow.setText(
            f"// 核查日期 {date.today().isoformat()} · {summary['source_count']} 个来源"
        )
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
        self._set_module_summaries(result, summary)
        return summary

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_attention(self, result: Mapping[str, object]) -> None:
        self._clear_layout(self.attention_layout)
        questions = manual_verification_questions(result)
        if not questions:
            card = EmptyStateCard(
                "当前确定性观察未生成核实事项，不代表不存在其他需核实内容。"
            )
            self.attention_layout.addWidget(card)
            return
        for item in questions[:3]:
            if not isinstance(item, Mapping):
                continue
            button = QPushButton(
                redact_sensitive_text(item.get("question_text", "待人工核实"))
            )
            button.setObjectName("briefAttentionButton")
            button.setToolTip(redact_sensitive_text(item.get("trigger_reason", "")))
            button.clicked.connect(lambda: self.moduleRequested.emit("manual"))
            self.attention_layout.addWidget(button)

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
    ) -> None:
        manual_count = int(summary.get("manual_question_count", 0))
        sensitive_count = int(summary.get("sensitive_candidate_count", 0))
        self.module_cards["manual"].set_summary(
            str(manual_count),
            "待人工确认的问题与确定性触发依据。",
            f"候选命中 {manual_count} · 可点击复核",
            "orange" if manual_count else "mint",
        )
        self.module_cards["sensitive"].set_summary(
            str(sensitive_count),
            "可靠文字字段中的敏感词组候选。",
            f"候选命中 {sensitive_count} · 不代表风险",
            "orange" if sensitive_count else "mint",
        )
        business = self._observation_value(result, "ai_business_relevance_candidates")
        deterministic = business.get("deterministic_candidates", [])
        ai_candidates = business.get("ai_candidates", [])
        business_count = len(deterministic) + len(ai_candidates)
        business_reason = str(business.get("reason") or "")
        business_available = bool(business.get("available"))
        self.module_cards["business"].set_summary(
            str(business_count) if business_available else "不可用",
            "只展示 schema 既有经营观察；不会在 GUI 中恢复模型调用。",
            (
                f"直接/候选命中 {business_count}"
                if business_available
                else f"不可用 · {business_reason or '原始状态未提供'}"
            ),
            "mint" if business_available else "muted",
        )
        purchase = self._observation_value(
            result,
            "purchase_prepayment_funding_candidates",
        )
        purchase_rows = purchase.get("purchase_candidates", [])
        purchase_count = len(purchase_rows) if isinstance(purchase_rows, list) else 0
        self.module_cards["purchase"].set_summary(
            str(purchase_count),
            "下定、定金、购车款及此前收入的非归因候选。",
            (
                f"候选命中 {purchase_count}"
                if purchase_count
                else "可靠字段内未发现"
            ),
            "orange" if purchase_count else "mint",
        )
        counterparties = self._observation_value(result, "top_counterparties")
        income_top = counterparties.get("income", [])
        expense_top = counterparties.get("expense", [])
        counterparty_count = (
            len(income_top) + len(expense_top)
            if isinstance(income_top, list) and isinstance(expense_top, list)
            else 0
        )
        self.module_cards["counterparty"].set_summary(
            str(counterparty_count),
            "收入与支出主要交易对手摘要。",
            "可用" if counterparties else "不可用",
            "mint" if counterparties else "muted",
        )
        large = self._observation_value(result, "large_transaction_candidates")
        large_rows = large.get("candidates", [])
        large_count = len(large_rows) if isinstance(large_rows, list) else 0
        self.module_cards["funds"].set_summary(
            str(large_count),
            "大额交易与既有 1/3/7 日资金观察。",
            "可用" if large else "不可用",
            "mint" if large else "muted",
        )
        balance = self._observation_value(
            result,
            "end_of_day_balance_and_interest",
        )
        self.module_cards["balance"].set_summary(
            "可用" if balance else "不可用",
            "日末余额、结息与月度变化摘要。",
            "可用" if balance else "不可用",
            "mint" if balance else "muted",
        )
        declaration = self._observation_value(
            result,
            "declaration_flow_cross_checks",
        )
        checks = declaration.get("items", [])
        check_count = len(checks) if isinstance(checks, list) else 0
        self.module_cards["declaration"].set_summary(
            str(check_count),
            "申报信息与可靠流水字段的四状态对照。",
            "可用" if declaration else "不可用",
            "mint" if declaration else "muted",
        )
        result_body = result.get("result", {})
        evidence = (
            result_body.get("evidence", {})
            if isinstance(result_body, Mapping)
            else {}
        )
        coverage = evidence.get("coverage", {}) if isinstance(evidence, Mapping) else {}
        indexed = coverage.get("indexed_transaction_count", 0)
        self.module_cards["evidence"].set_summary(
            str(indexed or summary.get("transaction_count", 0)),
            "交易索引、来源页行与消费者引用完整性。",
            "可用" if evidence else "不可用",
            "mint" if summary.get("evidence_complete") else "orange",
        )


class VerificationWorkspace(QWidget):
    selectCaseRequested = pyqtSignal()
    openCaseRequested = pyqtSignal()
    loadResultRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    legacyRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: Mapping[str, object] | None = None
        self._source_errors: list[str] = []
        self._recent_cases: list[str] = []
        self._active_module = "manual"
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
        for route, title in (
            ("home", "首页"),
            ("dashboard", "当前案件  ·  案件概览"),
            ("manual", "当前案件  ·  人工核实"),
            ("analysis", "当前案件  ·  分析结果"),
            ("evidence", "当前案件  ·  证据中心"),
            ("history", "历史案件"),
            ("settings", "设置"),
        ):
            button = FilterButton(title)
            button.setProperty("route", route)
            button.clicked.connect(
                lambda checked, selected_route=route: self.navigate(selected_route)
            )
            self.navigation_buttons.append(button)
            nav_layout.addWidget(button)
        self.navigation_buttons[0].setChecked(True)
        for button in self.navigation_buttons[1:5]:
            button.setEnabled(False)
        nav_layout.addStretch(1)
        self.legacy_button = QPushButton("返回原流水工具")
        self.legacy_button.clicked.connect(self.legacyRequested)
        nav_layout.addWidget(self.legacy_button)
        root.addWidget(navigation)

        self.main_pages = QStackedWidget()
        self.welcome_page = WelcomePage()
        self.processing_page = ProcessingPage()
        self.dashboard_page = CaseDashboardPage()
        self.module_detail_page = ModuleDetailPage()
        self.history_page = self._simple_page(
            "历史案件",
            "最近处理案件显示在首页；已有 schema 1.16 结果可直接导入。",
        )
        self.settings_page = self._simple_page(
            "设置",
            "基础解析固定禁用外部模型；本页不展示或保存任何模型密钥。",
        )
        for page in (
            self.welcome_page,
            self.processing_page,
            self.dashboard_page,
            self.module_detail_page,
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
        self.welcome_page.settingsRequested.connect(self.settingsRequested)
        self.processing_page.cancelRequested.connect(self.cancelRequested)
        self.dashboard_page.moduleRequested.connect(self.open_module)
        self.module_detail_page.backRequested.connect(
            lambda: self.navigate("dashboard")
        )
        self.module_detail_page.transactionSelected.connect(
            self._show_evidence_from_table
        )
        self.module_detail_page.selectionUnavailable.connect(
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
        self.manual_table = self.module_detail_page.manual_table
        self.sensitive_table = self.module_detail_page.sensitive_table
        self.source_status = self.processing_page.source_status
        self.setStyleSheet(brief_stylesheet())

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
        if route == "home":
            self.main_pages.setCurrentWidget(self.welcome_page)
            self.close_evidence()
        elif route in {"dashboard", "analysis"}:
            if self._result is None:
                return
            self.main_pages.setCurrentWidget(self.dashboard_page)
            self.close_evidence()
        elif route in {"manual", "sensitive", "evidence"}:
            if self._result is None:
                return
            self.open_module(route)
        elif route == "history":
            self.main_pages.setCurrentWidget(self.history_page)
            self.close_evidence()
        elif route == "settings":
            self.main_pages.setCurrentWidget(self.settings_page)
            self.close_evidence()
        for button in self.navigation_buttons:
            button.setChecked(str(button.property("route")) == route)

    def set_busy(self, case_name: str, total_sources: int) -> None:
        self._result = None
        self._source_errors = []
        self.processing_page.start(case_name, total_sources)
        self.module_detail_page.set_result(None)
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
    ) -> None:
        validated = validate_standard_result(result)
        self._result = validated
        summary = self.dashboard_page.set_result(validated, case_name)
        self.module_detail_page.set_result(validated)
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
        for button in self.navigation_buttons[1:5]:
            button.setEnabled(True)
        self.main_pages.setCurrentWidget(self.dashboard_page)
        self.close_evidence()
        for button in self.navigation_buttons:
            button.setChecked(str(button.property("route")) == "dashboard")

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
        if self._result is None:
            return
        if module_key not in ModuleDetailPage.MODULE_TITLES:
            module_key = "manual"
        card = self.dashboard_page.module_cards[module_key]
        summary = f"{card.summary_label.text()}\n{card.status_label.text()}"
        self._active_module = module_key
        self.module_detail_page.set_module(module_key, summary)
        self.main_pages.setCurrentWidget(self.module_detail_page)
        self.close_evidence()

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
    QLabel#briefStatusBadge[tone="orange"] {{ background: {BriefTheme.ORANGE}; }}
    QLabel#briefStatusBadge[tone="red"] {{ background: {BriefTheme.RED}; }}
    """
