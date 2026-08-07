"""Read-only module catalogue and schema 1.16 presentation adapters."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Mapping

from bankflow_v2.standard_result_view import (
    manual_verification_questions,
    observation_by_type,
    redact_sensitive_text,
    sensitive_transaction_candidates,
)

from .contracts import (
    ApplicationError,
    FilterDefinitionDTO,
    FilterOptionDTO,
    ModuleDescriptorDTO,
    ModuleRegistryDTO,
    ModuleSummaryDTO,
    PagedModuleItemsDTO,
    ReviewItemDTO,
)
from .result_adapter import PURCHASE_BOUNDARY_NOTE, PurchaseResultAdapter


ALLOWED_PAGE_SIZES = {25, 50, 100}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _basename(value: object) -> str | None:
    name = Path(str(value or "")).name
    return name or None


def _transaction_fields(record: Mapping[str, object]) -> Mapping[str, object]:
    context = _mapping(record.get("transaction_context"))
    return _mapping(
        record.get("reliable_standard_fields")
        or context.get("reliable_standard_fields")
    )


def _original_transactions(result: Mapping[str, object]) -> list[object]:
    body = _mapping(result.get("result"))
    return _list(body.get("original_transactions"))


def _transaction_lookup(result: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    lookup: dict[str, Mapping[str, object]] = {}
    for transaction in _original_transactions(result):
        if isinstance(transaction, Mapping) and transaction.get("transaction_id"):
            lookup[str(transaction["transaction_id"])] = transaction
    return lookup


def _context_from_transaction(
    transaction: Mapping[str, object],
) -> Mapping[str, object]:
    income = str(transaction.get("income") or "0.00")
    expense = str(transaction.get("expense") or "0.00")
    direction = ""
    if income not in {"", "0", "0.0", "0.00", "None"}:
        direction = "income"
    elif expense not in {"", "0", "0.0", "0.00", "None"}:
        direction = "expense"
    return {
        "transaction_time": transaction.get("transaction_time"),
        "direction": direction,
        "income": income,
        "expense": expense,
        "source_file": transaction.get("source_file"),
        "reliable_standard_fields": dict(
            _mapping(transaction.get("standard_fields"))
        ),
    }


def _with_transaction_context(
    record: Mapping[str, object],
    lookup: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object]:
    enriched = dict(record)
    transaction = lookup.get(str(record.get("transaction_id") or ""))
    if transaction is None:
        return enriched
    context = _mapping(record.get("transaction_context"))
    merged = dict(context)
    for key, value in _context_from_transaction(transaction).items():
        merged.setdefault(key, value)
    enriched["transaction_context"] = merged
    return enriched


def _direction_amount(record: Mapping[str, object]) -> tuple[str | None, str | None]:
    context = _mapping(record.get("transaction_context"))
    direction = str(record.get("direction") or context.get("direction") or "")
    income = str(record.get("income") or context.get("income") or "0")
    expense = str(record.get("expense") or context.get("expense") or "0")
    if direction == "income" or income not in {"", "0", "0.0", "0.00", "None"}:
        return "收入", income
    if direction == "expense" or expense not in {"", "0", "0.0", "0.00", "None"}:
        return "支出", expense
    return None, None


def _common_item(
    record: Mapping[str, object],
    *,
    item_id: str,
    transaction_id: str | None,
    category: str | None,
    matched_text: str | None,
    interpretation: str | None,
    review_status: str | None,
    source_kind: str | None = None,
) -> ReviewItemDTO:
    context = _mapping(record.get("transaction_context"))
    fields = _transaction_fields(record)
    direction, amount = _direction_amount(record)
    counterparty = str(
        fields.get("counterparty_name")
        or fields.get("merchant_name")
        or record.get("counterparty_name")
        or ""
    ) or None
    summary = str(fields.get("summary") or fields.get("purpose") or fields.get("remark") or "") or None
    source_name = _basename(
        record.get("source_file") or context.get("source_file")
    )
    date = str(record.get("transaction_time") or context.get("transaction_time") or "")[:19] or None
    return ReviewItemDTO(
        item_id=item_id,
        transaction_id=transaction_id,
        date=date,
        direction=direction,
        amount=amount,
        primary_text=redact_sensitive_text(counterparty or summary or matched_text or "未提供交易摘要"),
        secondary_text=redact_sensitive_text(summary) if summary else None,
        counterparty=redact_sensitive_text(counterparty) if counterparty else None,
        matched_text=redact_sensitive_text(matched_text) if matched_text else None,
        interpretation=redact_sensitive_text(interpretation) if interpretation else None,
        category=category,
        review_status=review_status,
        source_name=source_name,
        evidence_available=bool(transaction_id),
        source_kind=source_kind,
    )


def _options(items: list[ReviewItemDTO], field: str) -> list[FilterOptionDTO]:
    values = sorted({str(getattr(item, field) or "") for item in items if getattr(item, field)})
    return [FilterOptionDTO(value, value) for value in values]


def _filters(items: list[ReviewItemDTO]) -> list[FilterDefinitionDTO]:
    definitions = [
        FilterDefinitionDTO("status", "状态", "select", _options(items, "review_status")),
        FilterDefinitionDTO("category", "分类", "select", _options(items, "category")),
        FilterDefinitionDTO("source", "来源", "select", _options(items, "source_name")),
        FilterDefinitionDTO("keyword", "关键词", "text"),
    ]
    if any(item.source_kind for item in items):
        source_kind_options = []
        if any(item.source_kind == "deterministic" for item in items):
            source_kind_options.append(
                FilterOptionDTO("deterministic", "确定性")
            )
        if any(item.source_kind == "ai" for item in items):
            source_kind_options.append(FilterOptionDTO("ai", "AI"))
        definitions.insert(
            1,
            FilterDefinitionDTO(
                "source_kind",
                "来源类型",
                "select",
                source_kind_options,
            ),
        )
    if any(item.date for item in items):
        definitions.extend([
            FilterDefinitionDTO("date_from", "开始日期", "date"),
            FilterDefinitionDTO("date_to", "结束日期", "date"),
        ])
    return definitions


class ModuleAdapter:
    module_id = ""
    title = ""
    icon = "circle"
    display_kind = "transaction_list"
    description = ""
    boundary_note = ""
    forced_availability: str | None = None
    evidence_supported = True

    def __init__(self, result: Mapping[str, object], case_name: str) -> None:
        self.result = result
        self.case_name = case_name
        self.items = self.build_items()

    def build_items(self) -> list[ReviewItemDTO]:
        return []

    @property
    def availability(self) -> str:
        if self.forced_availability:
            return self.forced_availability
        return "available" if self.items else "empty"

    @property
    def review_count(self) -> int:
        return sum(item.review_status == "review" for item in self.items)

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            if item.category:
                counts[item.category] = counts.get(item.category, 0) + 1
        return counts

    def source_count(self) -> int:
        return len({item.source_name for item in self.items if item.source_name})

    def descriptor(self) -> ModuleDescriptorDTO:
        return ModuleDescriptorDTO(
            self.module_id, self.title, self.icon, self.availability,
            self.display_kind, len(self.items), self.review_count,
            "需复核" if self.review_count else ("可查看" if self.availability == "available" else ""),
            self.description, _filters(self.items), self.evidence_supported,
        )

    def summary(self, case_session_id: str) -> ModuleSummaryDTO:
        return ModuleSummaryDTO(
            self.module_id, self.title, len(self.items), self.review_count,
            self.descriptor().status, self.description, self.boundary_note,
            self.category_counts(), self.source_count(), case_session_id,
        )

    def list_items(
        self,
        case_session_id: str,
        page: int,
        page_size: int,
        filters: Mapping[str, object],
        sort: str,
    ) -> PagedModuleItemsDTO:
        started = time.perf_counter()
        if not isinstance(page, int) or page < 1 or page_size not in ALLOWED_PAGE_SIZES:
            raise ApplicationError("INVALID_ARGUMENT")
        if sort not in {"default", "date_desc", "date_asc"}:
            raise ApplicationError("INVALID_ARGUMENT")
        supported = {definition.key for definition in _filters(self.items)}
        if any(key not in supported for key, value in filters.items() if value not in (None, "")):
            raise ApplicationError("INVALID_ARGUMENT")
        selected = list(self.items)
        for key, field in (
            ("status", "review_status"),
            ("source_kind", "source_kind"),
            ("category", "category"),
            ("source", "source_name"),
        ):
            value = str(filters.get(key) or "")
            if value:
                selected = [item for item in selected if getattr(item, field) == value]
        keyword = str(filters.get("keyword") or "").strip().casefold()
        if keyword:
            selected = [
                item for item in selected
                if keyword in " ".join(str(value or "") for value in (
                    item.primary_text, item.secondary_text, item.counterparty,
                    item.matched_text, item.interpretation, item.source_name,
                )).casefold()
            ]
        date_from = str(filters.get("date_from") or "")[:10]
        date_to = str(filters.get("date_to") or "")[:10]
        if date_from:
            selected = [item for item in selected if (item.date or "")[:10] >= date_from]
        if date_to:
            selected = [item for item in selected if (item.date or "")[:10] <= date_to]
        if sort != "default":
            selected.sort(key=lambda item: item.date or "", reverse=sort == "date_desc")
        start = (page - 1) * page_size
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        return PagedModuleItemsDTO(
            self.module_id, case_session_id, page, page_size, len(selected),
            max(1, math.ceil(len(selected) / page_size)),
            selected[start:start + page_size], _filters(self.items),
            {"query_elapsed_ms": elapsed, "sort": sort},
        )


class PurchaseModuleAdapter(ModuleAdapter):
    module_id = "purchase"
    title = "下定与购车"
    icon = "car-front"
    description = "展示标准结果中已有的下定、购车与下定前收入候选。"
    boundary_note = PURCHASE_BOUNDARY_NOTE

    def build_items(self) -> list[ReviewItemDTO]:
        adapter = PurchaseResultAdapter(self.result, self.case_name)
        page = adapter.list_transactions(page=1, page_size=100)
        rows = list(page.items)
        for number in range(2, page.total_pages + 1):
            rows.extend(adapter.list_transactions(number, 100).items)
        return [ReviewItemDTO(
            item_id=row.transaction_id, transaction_id=row.transaction_id,
            date=row.date, direction=row.direction, amount=row.amount,
            primary_text=redact_sensitive_text(row.counterparty),
            secondary_text=None, counterparty=redact_sensitive_text(row.counterparty),
            matched_text=redact_sensitive_text(row.matched_text),
            interpretation=row.interpretation, category=row.category,
            review_status=row.review_status, source_name=row.source_name,
            evidence_available=True,
        ) for row in rows]


class SensitiveModuleAdapter(ModuleAdapter):
    module_id = "sensitive"
    title = "敏感交易"
    icon = "shield-alert"
    description = "展示标准结果中已有的敏感文字上下文候选，仅表示文字共现。"
    boundary_note = "候选命中只表示文字共现，需结合交易实际性质和背景核实。"

    def build_items(self) -> list[ReviewItemDTO]:
        rows: list[ReviewItemDTO] = []
        for candidate in sensitive_transaction_candidates(self.result):
            if not isinstance(candidate, Mapping):
                continue
            transaction_id = str(candidate.get("transaction_id") or "") or None
            terms = sorted({str(value) for value in _list(candidate.get("matched_terms")) if value})
            rows.append(_common_item(
                candidate, item_id=transaction_id or f"sensitive-{len(rows)}",
                transaction_id=transaction_id, category="敏感文字",
                matched_text="、".join(terms) or None,
                interpretation="需结合交易背景人工核实", review_status="review",
            ))
        return rows


class FundsBalanceModuleAdapter(ModuleAdapter):
    module_id = "funds_balance"
    title = "资金与余额"
    icon = "landmark"
    description = "展示标准结果中已有的大额交易候选；不在展示层重算资金规则。"
    boundary_note = "大额和余额观察仅用于定位既有结果，不代表资金来源或用途结论。"

    def build_items(self) -> list[ReviewItemDTO]:
        observation = observation_by_type(self.result, "large_transaction_candidates")
        value = _mapping(observation.get("value"))
        rows: list[ReviewItemDTO] = []
        for candidate in _list(value.get("candidates")):
            if not isinstance(candidate, Mapping):
                continue
            transaction_id = str(candidate.get("transaction_id") or "") or None
            rows.append(_common_item(
                candidate, item_id=transaction_id or f"funds-{len(rows)}",
                transaction_id=transaction_id, category="大额交易",
                matched_text="大额交易候选", interpretation="来自 schema 1.16 既有观察",
                review_status="review",
            ))
        return rows


class DeclarationCompareModuleAdapter(ModuleAdapter):
    module_id = "declaration"
    title = "申报对照"
    icon = "clipboard-check"
    display_kind = "summary"
    description = "展示标准结果中已有的申报对照项。"
    evidence_supported = True

    def build_items(self) -> list[ReviewItemDTO]:
        observation = observation_by_type(self.result, "declaration_flow_cross_checks")
        value = _mapping(observation.get("value"))
        check_labels = {
            "work_unit": "工作单位",
            "declared_industry": "申报行业",
            "purchase_deposit_expense": "下定相关支出",
            "work_location": "工作地点",
            "residence_location": "居住地点",
            "vehicle_registration_location": "车辆上牌地点",
            "dealer_name": "经销商",
            "purchase_declaration": "下定描述",
        }
        status_labels = {
            "direct_match": "直接命中",
            "candidate_match": "候选命中",
            "no_evidence_in_reliable_fields": "可靠字段内未发现",
            "unavailable": "字段覆盖不足",
            "display_only": "仅展示",
        }
        rows: list[ReviewItemDTO] = []
        for key in ("items", "display_only_items"):
            for item in _list(value.get(key)):
                if not isinstance(item, Mapping):
                    continue
                ids = [
                    str(value)
                    for value in _list(item.get("evidence_transaction_ids"))
                    if value
                ]
                transaction_id = ids[0] if ids else None
                check_type = str(item.get("check_type") or "申报对照")
                status = str(item.get("status") or "unavailable")
                reason = str(item.get("reason") or "")
                status_label = status_labels.get(status, status)
                display_only = (
                    key == "display_only_items"
                    or str(item.get("handling"))
                    == "system_information_display_only"
                )
                declared = "、".join(
                    str(value)
                    for value in _list(item.get("declared_values"))
                    if str(value)
                )
                rows.append(ReviewItemDTO(
                    item_id=f"declaration-{check_type}-{len(rows)}",
                    transaction_id=transaction_id,
                    date=None,
                    direction=None,
                    amount=None,
                    primary_text=redact_sensitive_text(
                        declared or check_labels.get(check_type, check_type)
                    ),
                    secondary_text=redact_sensitive_text(
                        reason if reason else status_label
                    ),
                    counterparty=None,
                    matched_text=None,
                    interpretation=None,
                    category=check_labels.get(check_type, check_type),
                    review_status=(
                        "display_only"
                        if display_only
                        else (
                            "direct"
                            if status in {"direct_match", "candidate_match"}
                            else "review"
                        )
                    ),
                    source_name=None,
                    evidence_available=bool(transaction_id),
                ))
        return rows


class BusinessModuleAdapter(ModuleAdapter):
    module_id = "business"
    title = "经营痕迹"
    icon = "briefcase-business"
    description = "仅读取标准结果中已有的经营关联候选，不发起 AI 调用。"

    def build_items(self) -> list[ReviewItemDTO]:
        observation = observation_by_type(self.result, "ai_business_relevance_candidates")
        value = _mapping(observation.get("value"))
        lookup = _transaction_lookup(self.result)
        reason_labels = {
            "business_context_confirmation_required": (
                "经营上下文不足，需人工确认主要经营内容后重新构建上下文观察"
            ),
            "ai_data_authorization_missing": "AI 未授权（未加载运行时配置）",
            "ai_response_invalid": "AI 验收缓存未覆盖本案件，暂无可复用 AI 结果",
        }
        classification_labels = {
            "directly_related": "直接相关",
            "possibly_related": "可能相关",
            "no_relation_evidence": "无关联证据",
            "undetermined": "无法判断",
            "none": "无关联",
        }
        rows: list[ReviewItemDTO] = []
        for source_key, source_label in (("deterministic_candidates", "确定性候选"), ("ai_candidates", "既有 AI 观察")):
            source_kind = "deterministic" if source_key == "deterministic_candidates" else "ai"
            for candidate in _list(value.get(source_key)):
                if not isinstance(candidate, Mapping):
                    continue
                transaction_id = str(candidate.get("transaction_id") or "") or None
                classification = str(candidate.get("classification") or source_label)
                classification_cn = classification_labels.get(
                    classification,
                    classification if classification != source_label else source_label,
                )
                reason = str(candidate.get("reason") or "")
                interpretation = f"{source_label}：{classification_cn}"
                if reason:
                    interpretation = f"{interpretation}；{reason}"
                matched_text = classification_cn
                if source_kind == "deterministic":
                    anchors = [
                        str(anchor)
                        for anchor in _list(candidate.get("matched_anchors"))
                        if str(anchor)
                    ]
                    if anchors:
                        matched_text = f"命中：{'、'.join(anchors)}"
                rows.append(_common_item(
                    _with_transaction_context(candidate, lookup),
                    item_id=transaction_id or f"business-{len(rows)}",
                    transaction_id=transaction_id, category=classification_cn,
                    matched_text=matched_text,
                    interpretation=interpretation,
                    review_status="review",
                    source_kind=source_kind,
                ))
        if not bool(value.get("available")) and not rows:
            self.forced_availability = "unavailable"
            reason = str(value.get("reason") or "")
            self.boundary_note = (
                "AI 经营判断不可用："
                + reason_labels.get(reason, reason or "当前不可用")
                + "；确定性候选可继续查看。"
            )
        return rows


class ManualReviewModuleAdapter(ModuleAdapter):
    module_id = "manual_review"
    title = "人工核实"
    icon = "circle-help"
    display_kind = "summary"
    description = "展示标准结果中已有的人工核实问题。"

    def build_items(self) -> list[ReviewItemDTO]:
        rows: list[ReviewItemDTO] = []
        lookup = _transaction_lookup(self.result)
        attention_labels = {
            "transaction_structure_attention": "交易结构",
            "fund_flow_attention": "资金流向",
            "text_context_attention": "文字背景",
            "declaration_attention": "申报核实",
        }
        for question in manual_verification_questions(self.result):
            if not isinstance(question, Mapping):
                continue
            ids = [str(value) for value in _list(question.get("evidence_transaction_ids")) if value]
            transaction_id = ids[0] if ids else None
            context = (
                _context_from_transaction(lookup[transaction_id])
                if transaction_id and transaction_id in lookup
                else {}
            )
            direction = (
                "收入"
                if context.get("direction") == "income"
                else "支出"
                if context.get("direction") == "expense"
                else None
            )
            amount = (
                str(context.get("income"))
                if direction == "收入"
                else str(context.get("expense"))
                if direction == "支出"
                else None
            )
            rows.append(ReviewItemDTO(
                item_id=str(question.get("question_id") or f"question-{len(rows)}"),
                transaction_id=transaction_id,
                date=str(context.get("transaction_time") or "")[:19] or None,
                direction=direction,
                amount=amount,
                primary_text=redact_sensitive_text(
                    question.get("question_text") or "待人工核实"
                ),
                secondary_text=redact_sensitive_text(
                    question.get("trigger_reason") or ""
                ),
                counterparty=None,
                matched_text=(
                    f"涉及 {len(ids)} 笔证据" if ids else None
                ),
                interpretation=None,
                category=attention_labels.get(
                    str(question.get("attention_category") or ""),
                    "人工核实",
                ),
                review_status="review",
                source_name=_basename(context.get("source_file")),
                evidence_available=bool(transaction_id),
            ))
        return rows


class DisabledModuleAdapter(ModuleAdapter):
    display_kind = "disabled"
    forced_availability = "not_implemented"
    evidence_supported = False

    def __init__(self, module_id: str, title: str, icon: str) -> None:
        self.module_id, self.title, self.icon = module_id, title, icon
        self.description = "当前版本尚未实施"
        self.result, self.case_name, self.items = {}, "", []


class ModuleRegistry:
    def __init__(self, result: Mapping[str, object], case_name: str) -> None:
        self._adapters: dict[str, ModuleAdapter] = {}
        for adapter in (
            PurchaseModuleAdapter(result, case_name),
            SensitiveModuleAdapter(result, case_name),
            BusinessModuleAdapter(result, case_name),
            FundsBalanceModuleAdapter(result, case_name),
            DeclarationCompareModuleAdapter(result, case_name),
            ManualReviewModuleAdapter(result, case_name),
            DisabledModuleAdapter("vehicle_records", "用车记录", "car"),
            DisabledModuleAdapter("life_trajectory", "居住/工作轨迹", "map-pin"),
            DisabledModuleAdapter("consumption_level", "消费水平", "wallet-cards"),
        ):
            self._adapters[adapter.module_id] = adapter

    def catalogue(self, case_session_id: str) -> ModuleRegistryDTO:
        return ModuleRegistryDTO(case_session_id, [adapter.descriptor() for adapter in self._adapters.values()])

    def adapter(self, module_id: str) -> ModuleAdapter:
        adapter = self._adapters.get(module_id)
        if adapter is None:
            raise ApplicationError("INVALID_ARGUMENT")
        return adapter
