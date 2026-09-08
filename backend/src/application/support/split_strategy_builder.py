from __future__ import annotations

from domain.value_objects.ids import UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import (
  EqualSplitStrategy,
  ExactSplitStrategy,
  PercentageSplitStrategy,
  SplitStrategy,
  SplitType,
)

def build_split_strategy(
  split_type: SplitType | str,
  currency: str,
  *,
  exact_amounts_cents: dict[UserId, int] | None = None,
  percentages: dict[UserId, float] | None = None,
) -> SplitStrategy:
  """Build a SplitStrategy based on the provided parameters."""
  try:
    split_type = SplitType(split_type)
  except ValueError:
    raise ValueError(f"Unknown split_type: {split_type}") from None

  if split_type is SplitType.EQUAL:
    return EqualSplitStrategy()

  if split_type is SplitType.EXACT:
    if exact_amounts_cents is None:
      raise ValueError("exact_amounts_cents is required for exact split strategy.")
    return ExactSplitStrategy(
      {UserId(uid): Money(amount_cents=amount, currency=currency) for uid, amount in exact_amounts_cents.items()}
    )

  if split_type is SplitType.PERCENTAGE:
    if not percentages:
      raise ValueError("percentages is required for percentage split strategy.")
    return PercentageSplitStrategy({UserId(uid): pct for uid, pct in percentages.items()})

  raise ValueError(f"Unknown split_type: {split_type}")
