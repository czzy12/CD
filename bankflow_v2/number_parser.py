import re
from decimal import Decimal, InvalidOperation


MONEY_RE = re.compile(r"[+-]?\d[\d,]*\.\d{2}")


def money_to_decimal(text: str | None) -> Decimal | None:
    if not text:
        return None
    try:
        return Decimal(str(text).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def extract_signed_amount(raw: str | None) -> Decimal | None:
    """Extract the rightmost signed/decimal amount from noisy PDF text."""
    if raw is None:
        return None
    text = str(raw).replace("\n", "").replace("，", ",").replace(" ", "")

    signed = re.findall(r"[+-]\d[\d,]*\.\d{2}", text)
    if signed:
        return money_to_decimal(signed[-1])

    unsigned = re.findall(r"\d[\d,]*\.\d{2}", text)
    if unsigned:
        return money_to_decimal(unsigned[-1])

    return None


def amount_candidates(raw: str | None) -> list[Decimal]:
    """Return plausible signed amounts from noisy PDF text."""
    if raw is None:
        return []

    text = str(raw).replace("\n", "").replace("，", ",").replace(" ", "")
    matches = re.findall(r"[+-][\d,]*\d\.\d{2}", text)
    values: list[Decimal] = []
    seen: set[Decimal] = set()

    for match in matches:
        sign = match[0]
        clean = match[1:].replace(",", "")
        int_part, frac = clean.split(".", 1)

        candidate_texts = []
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
            if value is not None and abs(value) >= Decimal("0.01") and value not in seen:
                values.append(value)
                seen.add(value)

    if values:
        return values

    amount = extract_signed_amount(raw)
    return [amount] if amount is not None else []


def balance_candidates(raw: str | None) -> list[Decimal]:
    """
    Return plausible balances from a noisy cell.

    ICBC PDFs often prefix balances with random digits, for example
    "5\n4\n1,627.28" should allow 541627.28, 41627.28 and 1627.28.
    The sequential resolver later picks the candidate that matches
    previous balance + transaction amount.
    """
    if raw is None:
        return []

    text = str(raw).replace("\n", "").replace("，", ",").replace(" ", "")
    matches = MONEY_RE.findall(text)
    values: list[Decimal] = []
    seen: set[Decimal] = set()

    for match in matches:
        clean = match.replace(",", "")
        if clean.startswith(("+", "-")):
            clean = clean[1:]
        int_part, frac = clean.split(".", 1)

        for start in range(len(int_part)):
            candidate_text = f"{int_part[start:]}.{frac}"
            value = money_to_decimal(candidate_text)
            if value is not None and value >= Decimal("0.01") and value not in seen:
                values.append(value)
                seen.add(value)

    return values


def choose_balance(
    raw: str | None,
    previous_balance: Decimal | None,
    amount: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    candidates = balance_candidates(raw)
    if not candidates:
        return None, "余额无法解析"

    if previous_balance is not None and amount is not None:
        expected = (previous_balance + amount).quantize(Decimal("0.01"))
        for candidate in candidates:
            if candidate == expected:
                return candidate, None
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
        for amount in amounts:
            expected = (previous_balance + amount).quantize(Decimal("0.01"))
            for balance in balances:
                if balance == expected:
                    return amount, balance, issues

        best = min(
            ((amount, balance) for amount in amounts for balance in balances),
            key=lambda pair: abs((previous_balance + pair[0]).quantize(Decimal("0.01")) - pair[1]),
        )
        expected = (previous_balance + best[0]).quantize(Decimal("0.01"))
        issues.append(f"余额不连续: 期望 {expected}, 解析 {best[1]}")
        return best[0], best[1], issues

    amount = amounts[0] if amounts else None
    balance = balances[0] if balances else None
    return amount, balance, issues
