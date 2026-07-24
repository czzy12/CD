"""Small helpers for PDFs whose transaction columns have stable x-coordinates."""

from __future__ import annotations

from collections.abc import Callable


def extract_coordinate_rows(
    page,
    headers: list[str],
    is_first_cell: Callable[[str], bool],
    column_positions: dict[str, float] | None = None,
) -> list[dict[str, str]]:
    """Return rows only when the page exposes every declared header explicitly.

    A new row begins only at a value in the first header's x-column.  This keeps
    wrapped cell text with its original column instead of guessing from text lines.
    """
    words = sorted(page.extract_words(use_text_flow=True, keep_blank_chars=False), key=lambda word: (word["top"], word["x0"]))
    positions: dict[str, float] = {}
    header_bottom = -1.0
    for word in words:
        text = str(word["text"]).strip()
        if text in headers:
            positions[text] = float(word["x0"])
            header_bottom = max(header_bottom, float(word["top"]))

    if len(positions) == len(headers):
        if column_positions is not None:
            column_positions.clear()
            column_positions.update(positions)
    elif column_positions is not None and len(column_positions) == len(headers):
        positions = dict(column_positions)
        header_bottom = -1.0
    else:
        return []

    ordered = sorted(headers, key=positions.__getitem__)
    bounds = [
        (positions[ordered[index]] + positions[ordered[index + 1]]) / 2
        for index in range(len(ordered) - 1)
    ]

    first_boundary = bounds[0] if bounds else float("inf")
    data_words = [word for word in words if float(word["top"]) > header_bottom]
    starts = [
        word
        for word in data_words
        if float(word["x0"]) < first_boundary and is_first_cell(str(word["text"]).strip())
    ]
    if starts:
        first_row_top = min(float(word["top"]) for word in starts)
        last_row_top = max(float(word["top"]) for word in starts)
        # Some bilingual layouts print the English header lower than the Chinese
        # header.  Keep wrapped cells slightly above their row date, but not that
        # secondary header.
        data_words = [
            word
            for word in data_words
            if first_row_top - 12 <= float(word["top"]) <= last_row_top + 18
        ]
    groups: list[list[dict]] = [[] for _start in starts]
    for word in data_words:
        if not starts:
            break
        row_index = min(
            range(len(starts)),
            key=lambda index: abs(float(word["top"]) - float(starts[index]["top"])),
        )
        groups[row_index].append(word)

    rows: list[dict[str, str]] = []
    for group in groups:
        values = {header: [] for header in ordered}
        for word in group:
            x0 = float(word["x0"])
            column = next((index for index, boundary in enumerate(bounds) if x0 < boundary), len(ordered) - 1)
            values[ordered[column]].append(str(word["text"]).strip())
        rows.append({header: " ".join(values[header]).strip() for header in headers})
    return rows
