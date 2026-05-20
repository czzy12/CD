from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


ZERO = Decimal("0.00")


@dataclass
class Transaction:
    transaction_time: datetime
    income: Decimal = ZERO
    expense: Decimal = ZERO
    balance: Decimal | None = None
    bank: str = ""
    page_no: int = 0
    row_no: int = 0
    raw_time: str = ""
    raw_amount: str = ""
    raw_balance: str = ""
    raw_text: str = ""
    raw_fields: list[str] = field(default_factory=list)
    raw_headers: list[str] = field(default_factory=list)
    status: str = "ok"
    issues: list[str] = field(default_factory=list)

    @property
    def amount(self) -> Decimal:
        return self.income - self.expense
