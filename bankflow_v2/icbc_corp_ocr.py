from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国工商银行对公"
TITLE = "中国工商银行账户明细清单"
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
_OCR_INSTANCE: Any | None = None
TIME_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})(\d{2}:\d{2}:\d{2})")
MONEY_RE = re.compile(r"\d[\d,]*\.\d{2}")


def _create_ocr() -> Any:
    global _OCR_INSTANCE
    if _OCR_INSTANCE is not None:
        return _OCR_INSTANCE

    os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        import torch  # noqa: F401
    except Exception:
        pass

    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        raise RuntimeError("图片型工商银行账户明细清单需要本地 PaddleOCR") from exc

    try:
        _OCR_INSTANCE = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
        )
    except TypeError:
        _OCR_INSTANCE = PaddleOCR(use_angle_cls=False, lang="ch")
    return _OCR_INSTANCE


def _run_ocr(ocr: Any, image: Any) -> Any:
    if hasattr(ocr, "predict"):
        return ocr.predict(image)
    return ocr.ocr(image, cls=True)


def _ocr_texts(ocr: Any, image: Any) -> list[str]:
    texts: list[str] = []
    for page in _run_ocr(ocr, image) or []:
        if isinstance(page, dict) and "rec_texts" in page:
            texts.extend(str(text).strip() for text in page.get("rec_texts") or [] if text)
            continue
        for line in page or []:
            if len(line) >= 2 and line[1]:
                texts.append(str(line[1][0]).strip())
    return texts


def _crop_text(ocr: Any, image: Any, x1: int, y1: int, x2: int, y2: int, scale: int = 3) -> str:
    import cv2

    crop = image[y1 + 3 : y2 - 3, x1 + 3 : x2 - 3]
    if crop.size == 0:
        return ""
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return "".join(_ocr_texts(ocr, crop)).strip()


def _prepare_recognition_crop(
    image: Any,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> Any | None:
    import cv2
    import numpy as np

    crop = image[y1 + 3 : y2 - 3, x1 + 3 : x2 - 3]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(gray < 180)
    if not len(xs):
        return None
    crop = crop[
        max(0, int(ys.min()) - 2) : min(crop.shape[0], int(ys.max()) + 3),
        max(0, int(xs.min()) - 2) : min(crop.shape[1], int(xs.max()) + 3),
    ]
    target_height = 32
    target_width = max(32, round(crop.shape[1] * target_height / crop.shape[0]))
    return cv2.resize(crop, (target_width, target_height), interpolation=cv2.INTER_CUBIC)


def _recognize_cells(ocr: Any, crops: list[Any | None]) -> list[tuple[str, float]]:
    results = [("", 1.0) for _ in crops]
    positions = [index for index, crop in enumerate(crops) if crop is not None]
    if not positions:
        return results

    images = [crops[index] for index in positions]
    pipeline = getattr(getattr(ocr, "paddlex_pipeline", None), "_pipeline", None)
    recognizer = getattr(pipeline, "text_rec_model", None)
    if recognizer is None:
        for index, crop in zip(positions, images):
            results[index] = ("".join(_ocr_texts(ocr, crop)), 0.0)
        return results

    recognized = list(recognizer.predict(images, batch_size=min(64, len(images))))
    for index, result in zip(positions, recognized):
        data = dict(result)
        results[index] = (
            str(data.get("rec_text") or "").strip(),
            float(data.get("rec_score") or 0.0),
        )
    return results


def _parse_time(text: str) -> datetime | None:
    compact = re.sub(r"\s+", "", text).replace("：", ":")
    match = TIME_RE.search(compact)
    if not match:
        return None
    try:
        return datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_money(text: str) -> Decimal | None:
    compact = re.sub(r"\s+", "", text)
    matches = MONEY_RE.findall(compact)
    if not matches:
        return None
    return money_to_decimal(max(matches, key=len))


def _horizontal_line_centers(image: Any) -> list[int]:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    counts = (gray < 80).sum(axis=1)
    candidates = [index for index, count in enumerate(counts) if count > image.shape[1] * 0.75]
    groups: list[list[int]] = []
    for value in candidates:
        if groups and value <= groups[-1][-1] + 1:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [round(sum(group) / len(group)) for group in groups]


def _table_edges(image: Any, line_y: int) -> tuple[int, int]:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    xs = [index for index, value in enumerate(gray[line_y]) if value < 80]
    if not xs:
        raise ValueError("未定位到工商银行账户明细表边界")
    return min(xs), max(xs)


def _header_value(ocr: Any, image: Any, rect: tuple[int, int, int, int], prefix: str) -> str:
    text = _crop_text(ocr, image, *rect, scale=2)
    if prefix in text:
        return text.split(prefix, 1)[1].lstrip("：:")
    return ""


def _render_pages(pdf_path: str) -> list[Any]:
    try:
        import cv2
        import numpy as np
        import pypdfium2 as pdfium
    except Exception as exc:
        raise RuntimeError("图片型工商银行账户明细清单缺少 PDF 渲染依赖") from exc

    document = pdfium.PdfDocument(pdf_path)
    pages: list[Any] = []
    for page in document:
        rgb = np.asarray(page.render(scale=2).to_pil())
        pages.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return pages


def _restore_printed_order(transactions: list[Transaction]) -> None:
    grouped: dict[object, list[Transaction]] = {}
    for tx in transactions:
        grouped.setdefault(tx.transaction_time.date(), []).append(tx)

    for items in grouped.values():
        if len(items) < 2:
            continue
        chronological = sorted(items, key=lambda tx: (tx.page_no, tx.row_no), reverse=True)
        previous_time: datetime | None = None
        for tx in chronological:
            if previous_time is not None and tx.transaction_time <= previous_time:
                tx.transaction_time = previous_time + timedelta(microseconds=1)
            previous_time = tx.transaction_time


def _repair_and_validate_balance_chain(transactions: list[Transaction]) -> None:
    for index in range(len(transactions) - 2, -1, -1):
        current = transactions[index]
        older = transactions[index + 1]
        if older.balance is None:
            continue
        expected = (older.balance + current.income - current.expense).quantize(CENT)
        if current.balance is None:
            if current.income == ZERO and current.expense == ZERO:
                current.issues.append("OCR余额缺失且金额无法用于重建")
                current.status = "review"
                continue
            current.balance = expected
            current.raw_balance = f"{expected:.2f}"
            current.ocr_balance_reconstructed = True
            continue
        actual = current.balance.quantize(CENT)
        if actual == expected:
            continue

        if index == 0:
            current.balance = expected
            current.raw_balance = f"{expected:.2f}"
            current.ocr_balance_reconstructed = True
            continue

        derived = (current.balance - older.balance).quantize(CENT)
        if derived == ZERO:
            current.issues.append(
                f"OCR余额链不一致: 上笔余额 {older.balance:.2f}, 当前余额 {current.balance:.2f}"
            )
            current.status = "review"
            continue

        current.income = derived if derived > ZERO else ZERO
        current.expense = -derived if derived < ZERO else ZERO
        current.raw_amount = f"OCR余额链校正:{abs(derived):.2f}"
        current.ocr_amount_reconstructed = True

    for tx in transactions:
        if tx.income == ZERO and tx.expense == ZERO:
            tx.issues.append("OCR转入和转出金额均为空")
            tx.status = "review"


def extract_icbc_corp_ocr(pdf_path: str) -> list[Transaction]:
    pages = _render_pages(pdf_path)
    if not pages:
        return []

    import cv2

    ocr = _create_ocr()
    first = pages[0]
    title_crop = cv2.resize(first[5:75, 500:1150], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if TITLE not in "".join(_ocr_texts(ocr, title_crop)):
        raise ValueError("图片型 PDF 未确认命中中国工商银行账户明细清单")

    account_no = _header_value(ocr, first, (90, 45, 650, 85), "账号")
    account_name = _header_value(ocr, first, (90, 75, 950, 112), "本方账号户名")
    account_no_match = re.search(r"\d{15,25}", account_no)
    account_no = account_no_match.group(0) if account_no_match else ""

    row_specs: list[dict[str, Any]] = []
    headers = ["交易时间", "转出金额", "转入金额", "余额"]
    for page_no, image in enumerate(pages, start=1):
        lines = _horizontal_line_centers(image)
        if len(lines) < 4:
            raise ValueError(f"第 {page_no} 页未定位到工商银行九列表格")
        left, right = _table_edges(image, lines[0])
        column_width = (right - left) / 9
        columns = {
            "time": (round(left + column_width), round(left + column_width * 2)),
            "expense": (round(left + column_width * 5), round(left + column_width * 6)),
            "income": (round(left + column_width * 6), round(left + column_width * 7)),
            "balance": (round(left + column_width * 7), round(left + column_width * 8)),
        }

        for row_no, (top, bottom) in enumerate(zip(lines, lines[1:]), start=1):
            row_specs.append(
                {
                    "page_no": page_no,
                    "row_no": row_no,
                    "image": image,
                    "top": top,
                    "bottom": bottom,
                    "columns": columns,
                }
            )

    time_crops = [
        _prepare_recognition_crop(
            spec["image"],
            spec["columns"]["time"][0],
            spec["top"],
            spec["columns"]["time"][1],
            spec["bottom"],
        )
        for spec in row_specs
    ]
    time_results = _recognize_cells(ocr, time_crops)
    valid_specs: list[dict[str, Any]] = []
    for spec, crop, (raw_time, score) in zip(row_specs, time_crops, time_results):
        tx_time = _parse_time(raw_time)
        if crop is not None and (tx_time is None or score < 0.85):
            left, right = spec["columns"]["time"]
            fallback = _crop_text(ocr, spec["image"], left, spec["top"], right, spec["bottom"])
            fallback_time = _parse_time(fallback)
            if fallback_time is not None:
                raw_time, tx_time = fallback, fallback_time
        if tx_time is not None:
            spec.update(raw_time=raw_time, tx_time=tx_time, time_score=score)
            valid_specs.append(spec)

    balance_crops = [
        _prepare_recognition_crop(
            spec["image"],
            spec["columns"]["balance"][0],
            spec["top"],
            spec["columns"]["balance"][1],
            spec["bottom"],
        )
        for spec in valid_specs
    ]
    balance_results = _recognize_cells(ocr, balance_crops)
    for spec, crop, (raw_balance, score) in zip(valid_specs, balance_crops, balance_results):
        if crop is not None and (_parse_money(raw_balance) is None or score < 0.85):
            left, right = spec["columns"]["balance"]
            raw_balance = _crop_text(
                ocr, spec["image"], left, spec["top"], right, spec["bottom"], scale=4
            )
        spec.update(raw_balance=raw_balance, balance_score=score, balance=_parse_money(raw_balance))

    amount_spec_indexes = {
        index
        for index, spec in enumerate(valid_specs)
        if index in (0, len(valid_specs) - 1)
        or spec["balance"] is None
        or spec["balance_score"] < 0.95
    }
    amount_cells = [
        (index, name)
        for index in sorted(amount_spec_indexes)
        for name in ("expense", "income")
    ]
    amount_crops = [
        _prepare_recognition_crop(
            valid_specs[index]["image"],
            valid_specs[index]["columns"][name][0],
            valid_specs[index]["top"],
            valid_specs[index]["columns"][name][1],
            valid_specs[index]["bottom"],
        )
        for index, name in amount_cells
    ]
    amount_results = _recognize_cells(ocr, amount_crops)
    amounts: dict[tuple[int, str], str] = {}
    for (spec_index, name), crop, (raw_value, score) in zip(
        amount_cells, amount_crops, amount_results
    ):
        spec = valid_specs[spec_index]
        if crop is not None and (_parse_money(raw_value) is None or score < 0.85):
            left, right = spec["columns"][name]
            raw_value = _crop_text(
                ocr, spec["image"], left, spec["top"], right, spec["bottom"]
            )
        amounts[(spec_index, name)] = raw_value

    transactions: list[Transaction] = []
    for spec_index, spec in enumerate(valid_specs):
        raw_expense = amounts.get((spec_index, "expense"), "")
        raw_income = amounts.get((spec_index, "income"), "")
        raw_balance = spec["raw_balance"]
        expense = _parse_money(raw_expense) or ZERO
        income = _parse_money(raw_income) or ZERO
        balance = _parse_money(raw_balance)
        issues: list[str] = []
        if income != ZERO and expense != ZERO:
            issues.append("OCR转入和转出金额同时存在")

        tx = Transaction(
            transaction_time=spec["tx_time"],
            income=income,
            expense=expense,
            balance=balance,
            bank=BANK_NAME,
            page_no=spec["page_no"],
            row_no=spec["row_no"],
            raw_time=spec["raw_time"],
            raw_amount=f"{raw_income}|{raw_expense}",
            raw_balance=raw_balance,
            raw_text=" | ".join((spec["raw_time"], raw_expense, raw_income, raw_balance)),
            raw_fields=[spec["raw_time"], raw_expense, raw_income, raw_balance],
            raw_headers=headers,
            status="ok" if not issues else "review",
            issues=issues,
        )
        tx.preserve_signed_columns = True
        tx.account_name = account_name
        tx.account_no = account_no
        tx.ocr_source = True
        transactions.append(tx)

    _repair_and_validate_balance_chain(transactions)
    _restore_printed_order(transactions)
    return transactions
