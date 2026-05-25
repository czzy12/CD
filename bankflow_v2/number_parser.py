import re
from decimal import Decimal, InvalidOperation
from itertools import combinations


CENT = Decimal("0.01")
MONEY_RE = re.compile(r"[+-]?\d[\d,]*\.\d{2}")


def _compact_text(raw: str | None) -> str:
    if raw is None:
        return ""
    return str(raw).replace("\n", "").replace(" ", "")


def _money_matches(raw: str | None) -> list[str]:
    text = _compact_text(raw)
    normalized = re.sub(r"[^0-9,+.\-]", "", text)
    matches: list[str] = []
    seen: set[str] = set()
    for source in (text, normalized):
        for match in MONEY_RE.findall(source):
            if match not in seen:
                matches.append(match)
                seen.add(match)
    return matches


def money_to_decimal(text: str | None) -> Decimal | None:
    if not text:
        return None
    try:
        return Decimal(str(text).replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def extract_signed_amount(raw: str | None) -> Decimal | None:
    """Extract the rightmost signed/decimal amount from noisy PDF text."""
    signed = [match for match in _money_matches(raw) if match.startswith(("+", "-"))]
    if signed:
        return money_to_decimal(signed[-1])

    unsigned = [match for match in _money_matches(raw) if not match.startswith(("+", "-"))]
    if unsigned:
        return money_to_decimal(unsigned[-1])

    return None


def amount_candidates(raw: str | None) -> list[Decimal]:
    """Return plausible signed amounts from noisy PDF text."""
    matches = [match for match in _money_matches(raw) if match.startswith(("+", "-"))]
    text = _compact_text(raw)
    for match in re.findall(r"[+-][\d,]*\d\.\d{3}", text):
        sign = match[0]
        clean = match[1:].replace(",", "")
        int_part, frac = clean.split(".", 1)
        matches.append(f"{sign}{int_part}.{frac[:2]}")
        matches.append(f"{sign}{int_part}.{frac[0]}{frac[2]}")
    values: list[Decimal] = []
    seen: set[Decimal] = set()

    for match in matches:
        sign = match[0]
        body = match[1:]
        clean = match[1:].replace(",", "")
        int_part, frac = clean.split(".", 1)

        candidate_texts = []
        if "," in body:
            int_with_commas, raw_frac = body.split(".", 1)
            comma_parts = int_with_commas.split(",")
            if len(comma_parts[-1]) > 3:
                prefix = "".join(comma_parts[:-1])
                for drop_index in range(len(comma_parts[-1])):
                    fixed_int = prefix + comma_parts[-1][:drop_index] + comma_parts[-1][drop_index + 1 :]
                    if fixed_int:
                        candidate_texts.append(f"{sign}{fixed_int}.{raw_frac}")

        for start in range(len(int_part)):
            candidate_texts.append(f"{sign}{int_part[start:]}.{frac}")

        # PDF garbage can be inserted between real digits. For small retail
        # amounts, trying one removed digit catches cases like -6828.00 -> -88.00.
        if len(int_part) <= 5:
            for drop in range(len(int_part)):
                reduced = int_part[:drop] + int_part[drop + 1 :]
                if reduced:
                    candidate_texts.append(f"{sign}{reduced}.{frac}")

        for candidate_text in candidate_texts:
            value = money_to_decimal(candidate_text)
            if value is not None and abs(value) >= CENT and value not in seen:
                values.append(value)
                seen.add(value)

    if values:
        return values

    amount = extract_signed_amount(raw)
    return [amount] if amount is not None else []


def balance_candidates(raw: str | None) -> list[Decimal]:
    """
    Return plausible balances from a noisy cell.

    ICBC PDFs often prefix or interleave balances with random digits, for example
    "5\n4\n1,627.28" should allow 541627.28, 41627.28 and 1627.28,
    while "BC37A0,244.26" should allow 370244.26, 70244.26 and 244.26.
    The sequential resolver later picks the candidate that matches
    previous balance + transaction amount.
    """
    matches = _money_matches(raw)
    text = _compact_text(raw)
    normalized = re.sub(r"[^0-9,+.\-]", "", text)
    for source in (text, normalized):
        for match in re.findall(r"[+-]?\d[\d,]*\.\d{3}", source):
            clean = match.replace(",", "")
            if clean.startswith(("+", "-")):
                clean = clean[1:]
            int_part, frac = clean.split(".", 1)
            matches.append(f"{int_part}.{frac[:2]}")
            matches.append(f"{int_part}.{frac[0]}{frac[2]}")

    values: list[Decimal] = []
    seen: set[Decimal] = set()

    for match in matches:
        clean = match.replace(",", "")
        if clean.startswith(("+", "-")):
            clean = clean[1:]
        int_part, frac = clean.split(".", 1)
        candidate_texts: list[str] = []

        for start in range(len(int_part)):
            candidate_texts.append(f"{int_part[start:]}.{frac}")

        if len(int_part) <= 9:
            for drop_count in (1, 2):
                for indexes in combinations(range(len(int_part)), drop_count):
                    reduced = "".join(char for idx, char in enumerate(int_part) if idx not in indexes)
                    if reduced:
                        candidate_texts.append(f"{reduced}.{frac}")

        for candidate_text in candidate_texts:
            value = money_to_decimal(candidate_text)
            if value is not None and value >= Decimal("0.00") and value not in seen:
                values.append(value)
                seen.add(value)

    return values


def _cents_text(value: Decimal) -> str:
    return f"{value.quantize(CENT):.2f}".replace(".", "").replace("-", "")


def _candidate_is_suffix(expected: Decimal, candidate: Decimal) -> bool:
    expected_text = _cents_text(expected)
    candidate_text = _cents_text(candidate)
    return expected_text.endswith(candidate_text) and expected_text != candidate_text


def _is_subsequence(needle: str, haystack: str) -> bool:
    position = 0
    for char in haystack:
        if position < len(needle) and needle[position] == char:
            position += 1
    return position == len(needle)


def _amount_supported_by_raw(amount: Decimal, raw: str | None) -> bool:
    text = _compact_text(raw)
    if amount > 0 and "+" not in text:
        return False
    if amount < 0 and "-" not in text:
        return False
    raw_digits = re.sub(r"\D", "", text)
    amount_digits = _cents_text(amount)
    return bool(raw_digits) and _is_subsequence(amount_digits, raw_digits)


def choose_balance(
    raw: str | None,
    previous_balance: Decimal | None,
    amount: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    candidates = balance_candidates(raw)
    if not candidates:
        return None, "余额无法解析"

    if previous_balance is not None and amount is not None:
        expected = (previous_balance + amount).quantize(CENT)
        for candidate in candidates:
            if candidate == expected:
                return candidate, None
        for candidate in candidates:
            if _candidate_is_suffix(expected, candidate):
                return expected, None
        closest = min(candidates, key=lambda value: abs(value - expected))
        return closest, f"余额不连续: 期望 {expected}, 解析 {closest}"

    return candidates[0], None


def choose_amount_and_balance(
    amount_raw: str | None,
    balance_raw: str | None,
    previous_balance: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, list[str]]:
    amounts = amount_candidates(amount_raw)
    balances = balance_candidates(balance_raw)
    issues: list[str] = []

    if not amounts:
        issues.append("金额无法解析")
    if not balances:
        issues.append("余额无法解析")

    if previous_balance is not None and amounts and balances:
        prefer_amount = "," in _compact_text(amount_raw)
        matches: list[tuple[int, int, Decimal, Decimal]] = []
        suffix_matches: list[tuple[int, int, Decimal, Decimal]] = []
        for amount_index, amount in enumerate(amounts):
            expected = (previous_balance + amount).quantize(CENT)
            for balance_index, balance in enumerate(balances):
                if balance == expected:
                    matches.append((balance_index, amount_index, amount, balance))
            for balance_index, balance in enumerate(balances):
                if _candidate_is_suffix(expected, balance):
                    suffix_matches.append((balance_index, amount_index, amount, expected))
        if matches:
            _, _, amount, balance = min(
                matches,
                key=lambda item: (item[1], item[0]) if prefer_amount else (item[0], item[1]),
            )
            return amount, balance, issues
        if suffix_matches:
            _, _, amount, balance = min(
                suffix_matches,
                key=lambda item: (item[1], item[0]) if prefer_amount else (item[0], item[1]),
            )
            return amount, balance, issues

        for balance in balances[:4]:
            required_amount = (balance - previous_balance).quantize(CENT)
            if required_amount != 0 and _amount_supported_by_raw(required_amount, amount_raw):
                return required_amount, balance, issues

        best = min(
            ((amount, balance) for amount in amounts for balance in balances),
            key=lambda pair: abs((previous_balance + pair[0]).quantize(CENT) - pair[1]),
        )
        expected = (previous_balance + best[0]).quantize(CENT)
        issues.append(f"余额不连续: 期望 {expected}, 解析 {best[1]}")
        return best[0], best[1], issues

    amount = amounts[0] if amounts else None
    balance = balances[0] if balances else None
    return amount, balance, issues


def resolve_amount_balance_sequence(
    raw_rows: list[tuple[str | None, str | None]],
    beam_size: int = 40,
) -> list[tuple[Decimal | None, Decimal | None, list[str]]]:
    """Resolve a statement's noisy amount/balance cells with lookahead.

    Greedy row-by-row resolution can lock onto a locally continuous but wrong
    small suffix when ICBC watermark digits pollute both amount and balance
    cells. A bounded beam keeps several plausible balance paths alive and lets
    later rows choose the globally most continuous sequence.
    """
    if not raw_rows:
        return []

    parsed = [(amount_candidates(amount_raw), balance_candidates(balance_raw)) for amount_raw, balance_raw in raw_rows]
    beams: list[tuple[Decimal, Decimal | None, list[tuple[Decimal | None, Decimal | None]]]] = [
        (Decimal("0.00"), None, [])
    ]

    for row_index, ((amount_raw, balance_raw), (amounts, balances)) in enumerate(zip(raw_rows, parsed)):
        next_beams: list[tuple[Decimal, Decimal | None, list[tuple[Decimal | None, Decimal | None]]]] = []
        for cost, previous_balance, path in beams:
            for option_cost, amount, balance in _sequence_options(
                amount_raw,
                balance_raw,
                amounts,
                balances,
                previous_balance,
                row_index == 0,
            ):
                next_beams.append((cost + option_cost, balance, path + [(amount, balance)]))

        beams = sorted(next_beams, key=lambda item: item[0])[:beam_size]

    best_path = min(beams, key=lambda item: item[0])[2] if beams else []
    results: list[tuple[Decimal | None, Decimal | None, list[str]]] = []
    previous_balance: Decimal | None = None
    for amount, balance in best_path:
        issues: list[str] = []
        if amount is None:
            issues.append("金额无法解析")
        if balance is None:
            issues.append("余额无法解析")
        if previous_balance is not None and amount is not None and balance is not None:
            expected = (previous_balance + amount).quantize(CENT)
            if expected != balance.quantize(CENT):
                issues.append(f"余额不连续: 期望 {expected}, 解析 {balance}")
        results.append((amount, balance, issues))
        if balance is not None:
            previous_balance = balance
    return results


def _sequence_options(
    amount_raw: str | None,
    balance_raw: str | None,
    amounts: list[Decimal],
    balances: list[Decimal],
    previous_balance: Decimal | None,
    is_first_row: bool,
) -> list[tuple[Decimal, Decimal | None, Decimal | None]]:
    if not amounts or not balances:
        return [(Decimal("5000.00"), amounts[0] if amounts else None, balances[0] if balances else None)]

    options: list[tuple[Decimal, Decimal, Decimal]] = []
    seen: set[tuple[Decimal, Decimal]] = set()

    def add(cost: Decimal, amount: Decimal, balance: Decimal) -> None:
        key = (amount, balance)
        if key not in seen:
            options.append((cost, amount, balance))
            seen.add(key)

    amount_rank = {value: index for index, value in enumerate(amounts)}
    balance_rank = {value: index for index, value in enumerate(balances)}

    if previous_balance is None or is_first_row:
        for amount in amounts[:4]:
            for balance in balances[:8]:
                add(_candidate_cost(amount_rank, balance_rank, amount, balance), amount, balance)
        return sorted(options, key=lambda item: item[0])[:20]

    for amount in amounts[:40]:
        expected = (previous_balance + amount).quantize(CENT)
        for balance in balances:
            if balance == expected:
                add(_candidate_cost(amount_rank, balance_rank, amount, balance), amount, balance)
        for balance in balances:
            if _candidate_is_suffix(expected, balance):
                add(_candidate_cost(amount_rank, balance_rank, amount, balance) + Decimal("0.05"), amount, expected)

    for balance in balances[:40]:
        required_amount = (balance - previous_balance).quantize(CENT)
        if required_amount != 0 and _amount_supported_by_raw(required_amount, amount_raw):
            add(
                Decimal("0.10") + Decimal(balance_rank.get(balance, 99)) / Decimal("1000"),
                required_amount,
                balance,
            )

    if options:
        return sorted(options, key=lambda item: item[0])[:25]

    fallback: list[tuple[Decimal, Decimal, Decimal]] = []
    for amount in amounts[:12]:
        expected = (previous_balance + amount).quantize(CENT)
        for balance in balances[:20]:
            gap = abs(expected - balance)
            fallback.append((
                Decimal("1000.00") + min(gap, Decimal("1000.00")) + _candidate_cost(amount_rank, balance_rank, amount, balance),
                amount,
                balance,
            ))
    return sorted(fallback, key=lambda item: item[0])[:10]


def _candidate_cost(
    amount_rank: dict[Decimal, int],
    balance_rank: dict[Decimal, int],
    amount: Decimal,
    balance: Decimal,
) -> Decimal:
    return Decimal(amount_rank.get(amount, 99)) / Decimal("1000") + Decimal(balance_rank.get(balance, 99)) / Decimal("10000")
