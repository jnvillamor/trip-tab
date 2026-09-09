from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict

from domain.entities.expense import Expense

class _View(BaseModel):
  """Base for read models: immutable and strict about unknown fields.

  Deliberately does not trim strings: a view reports what the domain holds, so whitespace
  that got stored is a bug to surface, not one to hide.
  """

  model_config = ConfigDict(frozen=True, extra="forbid")

class SplitLineView(_View):
  user_id: str
  amount_cents: int
  currency: str

class ExpenseView(_View):
  id: str
  group_id: str
  description: str
  total_cents: int
  currency: str
  paid_by: str
  splits: list[SplitLineView]
  created_at: datetime
  deleted: bool

  @classmethod
  def from_entity(cls, expense: "Expense") -> "ExpenseView":
    return cls(
      id=str(expense.id),
      group_id=str(expense.group_id),
      description=expense.description,
      total_cents=expense.total.amount_cents,
      currency=expense.total.currency,
      paid_by=str(expense.paid_by),
      splits=[
        SplitLineView(
          user_id=str(split.user_id),
          amount_cents=split.owed.amount_cents,
          currency=split.owed.currency,
        )
        for split in expense.splits
      ],
      created_at=expense.created_at,
      deleted=expense.deleted,
    )