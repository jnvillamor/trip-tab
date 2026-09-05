from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainError

DEFAULT_CURRENCY = "PHP"

class CurrencyMismatchError(DomainError):
  """Raised when two Money objects with different currencies are used in an operation."""

@dataclass(frozen=True)
class Money:
  amount_cent: int
  currency: str = DEFAULT_CURRENCY

  def __post_init__(self) -> None:
    if not isinstance(self.amount_cent, int):
      raise ValueError("Money amount must be an integer representing cents")
    if len(self.currency) != 3:
      raise ValueError("Currency must be a 3-letter ISO code")

  @classmethod
  def from_major_units(cls, amount: float, currency: str = DEFAULT_CURRENCY) -> "Money":
    """Create a Money object from major currency units (e.g., dollars, euros)."""
    return cls(round(amount * 100), currency)

  @property
  def major_units(self) -> float:
    """Return the amount in major currency units (e.g., dollars, euros)."""
    return self.amount_cent / 100.0

  def _check_currency(self, other: "Money") -> None:
    if self.currency != other.currency:
      raise CurrencyMismatchError(f"Currency mismatch: {self.currency} vs {other.currency}")

  def __add__(self, other: "Money") -> "Money":
    self._check_currency(other)
    return Money(self.amount_cent + other.amount_cent, self.currency)

  def __sub__(self, other: "Money") -> "Money":
    self._check_currency(other)
    return Money(self.amount_cent - other.amount_cent, self.currency)

  def __neg__(self) -> "Money":
    return Money(-self.amount_cent, self.currency)

  def __lt__(self, other: "Money") -> bool:
    self._check_currency(other)
    return self.amount_cent < other.amount_cent

  def __le__(self, other: "Money") -> bool:
    self._check_currency(other)
    return self.amount_cent <= other.amount_cent

  def is_zero(self) -> bool:
    return self.amount_cent == 0

  def is_positive(self) -> bool:
    return self.amount_cent > 0

  def is_negative(self) -> bool:
    return self.amount_cent < 0

  def __str__(self) -> str:
    return f"{self.major_units:.2f} {self.currency}"

  @staticmethod
  def sum(amounts: list["Money"], currency: str = DEFAULT_CURRENCY) -> "Money":
    total = Money(0, currency)
    for amount in amounts:
      total += amount
    return total
