from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.exceptions import DomainError
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import SplitLine, SplitStrategy

class InvalidExpenseError(DomainError):
  """Raised for invalid expense operations."""

@dataclass
class Expense:
  """Paid by one user, owed by a set of participants according to a split strategy."""

  id: ExpenseId
  group_id: GroupId
  description: str
  total: Money
  paid_by: UserId
  splits: list[SplitLine]
  created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
  deleted: bool = False

  def __post_init__(self) -> None:
    if not self.description.strip():
      raise InvalidExpenseError("Expense description cannot be empty")
    if not self.total.is_positive():
      raise InvalidExpenseError("Expense total must be positive")
    self._validate_splits_sum_to_total()

  def _validate_splits_sum_to_total(self) -> None:
    computed = Money.sum([split.owed for split in self.splits], self.total.currency)
    if computed != self.total:
      raise InvalidExpenseError(
        f"Sum of splits {computed.amount_cent} does not match total {self.total.amount_cent}"
      )


  @classmethod
  def create(
    cls,
    id: ExpenseId,
    group_id: GroupId,
    description: str,
    total: Money,
    paid_by: UserId,
    split_strategy: SplitStrategy,
    participants: list[UserId],
  ) -> "Expense":
    """Factory that runs the split strategy to generate the SplitLines for the expense."""
    splits = split_strategy.split(total, participants)
    return cls(
      id=id,
      group_id=group_id,
      description=description,
      total=total,
      paid_by=paid_by,
      splits=splits
    )

  def edit(
      self,
      *,
      description: str | None = None,
      total: Money | None = None,
      participants: list[UserId] | None = None,
      strategy: SplitStrategy | None = None
  ) -> None:
    if description is not None:
      self.description = description

    if total is not None or participants is not None:
      if strategy is None:
        raise InvalidExpenseError("A split strategy must be provided when changing total or participants.")
      new_total = total or self.total
      new_participants = participants or [split.user_id for split in self.splits]
      self.total = new_total
      self.splits = strategy.split(new_total, new_participants)

    self._validate_splits_sum_to_total()

  def mark_deleted(self) -> None:
    self.deleted = True

  def owed_by(self, user_id: UserId) -> Money:
    """Return the amount owed by a specific user for this expense."""
    for split in self.splits:
      if split.user_id == user_id:
        return split.owed
    return Money(0, self.total.currency)