from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.exceptions import DomainError
from domain.value_objects.ids import UserId
from domain.value_objects.money import Money

class InvalidSplitStrategyError(DomainError):
  """Raised for invalid split strategy operations."""

@dataclass(frozen=True)
class SplitLine:
  """How much a single participant owes for one expense."""
  user_id: UserId
  owed: Money

class SplitStrategy(ABC):
  """Abstract base class for different split strategies."""

  @abstractmethod
  def split(self, total: Money, participants: list[UserId]) -> list[SplitLine]:
    ...

  @staticmethod
  def _largest_remainder_distribute(
    total_cents: int, raw_cents: dict[UserId, float], participants: list[UserId]
  ) -> dict[UserId, int]:
    """Distribute cents based on the largest remainder method."""

    floored = { uid: int(raw_cents[uid]) for uid in participants }
    remainder = total_cents - sum(floored.values())
    by_fraction_desc = sorted(
      participants, key=lambda uid: raw_cents[uid] - floored[uid], reverse=True
    )
    for uid in by_fraction_desc[:remainder]:
      floored[uid] += 1
    return floored

class EqualSplitStrategy(SplitStrategy):
  def __init__(self, amounts: dict[UserId, Money]):
    self._amounts = amounts

  def split(self, total: Money, participants: list[UserId]) -> list[SplitLine]:
    if set(self._amounts.keys()) != set(participants):
      raise InvalidSplitStrategyError("Participants do not match the specified amounts.")

    lines = [SplitLine(user_id=uid, owed=self._amounts[uid]) for uid in participants]
    computed_total = sum(line.owed.amount_cents for line in lines)

    if computed_total != total.amount_cents:
      raise InvalidSplitStrategyError(
        f"Computed total {computed_total} does not match the specified total {total.amount_cents}"
      )
    return lines

class ExactSplitStrategy(SplitStrategy):
  def __init__(self, amounts: dict[UserId, Money]):
    self._amounts = amounts

  def split(self, total: Money, participants: list[UserId]) -> list[SplitLine]:
    if set(self._amounts.keys()) != set(participants):
      raise InvalidSplitStrategyError("Participants do not match the specified amounts.")

    lines = [SplitLine(user_id, self._amounts[user_id]) for user_id in participants]
    computed_total = sum(line.owed.amount_cents for line in lines)
    if computed_total != total.amount_cents:
      raise InvalidSplitStrategyError(
        f"Computed total {computed_total} does not match the specified total {total.amount_cents}"
      )
    return lines

class PercentageSplitStrategy(SplitStrategy):
  """Split the total amount based on specified percentages for each participant."""

  def __init__(self, percentages: dict[UserId, float]):
    if not all(0 <= p <= 100 for p in percentages.values()):
      raise InvalidSplitStrategyError("Percentages must be between 0 and 100.")
    if abs(sum(percentages.values()) - 100) > 1e-6:
      raise InvalidSplitStrategyError("Percentages must sum to 100.")
    self._percentages = percentages

  def split(self, total: Money, participants: list[UserId]) -> list[SplitLine]:
    if set(self._percentages.keys()) != set(participants):
      raise InvalidSplitStrategyError("Participants do not match the specified percentages.")

    raw_cents = {
      uid: total.amount_cents * pct / 100.0 for uid, pct in self._percentages.items()
    }
    distributed_cents = self._largest_remainder_distribute(
      total.amount_cents, raw_cents, participants
    )

    return [SplitLine(user_id=uid, owed=Money(amount_cents=distributed_cents[uid], currency=total.currency)) for uid in participants]
