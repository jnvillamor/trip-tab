from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.events.base import AggregateRoot
from domain.events.expense_events import (
  ExpenseCreated,
  ExpenseDeleted,
  ExpenseEdited
)
from domain.exceptions import DomainError
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import SplitLine, SplitStrategy

class InvalidExpenseError(DomainError):
  """Raised for invalid expense operations."""

@dataclass
class Expense(AggregateRoot):
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
    self.description = self._normalize_description(self.description)
    if not self.total.is_positive():
      raise InvalidExpenseError("Expense total must be positive")
    self._validate_splits_sum_to_total(self.total, self.splits)

  @staticmethod
  def _normalize_description(description: str) -> str:
    """Descriptions are stored trimmed, so a stored value always matches what is displayed."""
    trimmed = description.strip()
    if not trimmed:
      raise InvalidExpenseError("Expense description cannot be empty")
    return trimmed

  @staticmethod
  def _validate_splits_sum_to_total(total: Money, splits: list[SplitLine]) -> None:
    """Takes the values to check, so `edit` can validate a candidate before committing it."""
    computed = Money.sum([split.owed for split in splits], total.currency)
    if computed != total:
      raise InvalidExpenseError(
        f"Sum of splits {computed.amount_cents} does not match total {total.amount_cents}"
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
    expense = cls(
      id=id,
      group_id=group_id,
      description=description,
      total=total,
      paid_by=paid_by,
      splits=splits
    )
    expense.record_event(ExpenseCreated(
      group_id=group_id,
      expense_id=expense.id,
      created_by=expense.paid_by,
      amount=expense.total,
      description=expense.description
    ))
    return expense

  def edit(
      self,
      *,
      description: str | None = None,
      total: Money | None = None,
      participants: list[UserId] | None = None,
      strategy: SplitStrategy | None = None
  ) -> None:
    """Applies the whole edit or none of it, and records an event only if something moved."""
    new_description = self.description
    if description is not None:
      new_description = self._normalize_description(description)

    new_total = self.total
    new_splits = self.splits
    if total is not None or participants is not None:
      if strategy is None:
        raise InvalidExpenseError("A split strategy must be provided when changing total or participants.")
      new_total = total or self.total
      new_participants = participants or [split.user_id for split in self.splits]
      new_splits = strategy.split(new_total, new_participants)

    self._validate_splits_sum_to_total(new_total, new_splits)

    if (new_description, new_total, new_splits) == (self.description, self.total, self.splits):
      return

    self.description = new_description
    self.total = new_total
    self.splits = new_splits
    self.record_event(ExpenseEdited(
      group_id=self.group_id,
      expense_id=self.id,
      new_amount=self.total,
      new_description=self.description
    ))

  def mark_deleted(self) -> None:
    if self.deleted:
      return
    self.deleted = True
    self.record_event(ExpenseDeleted(
      group_id=self.group_id,
      expense_id=self.id
    ))

  def owed_by(self, user_id: UserId) -> Money:
    """Return the amount owed by a specific user for this expense."""
    for split in self.splits:
      if split.user_id == user_id:
        return split.owed
    return Money(0, self.total.currency)