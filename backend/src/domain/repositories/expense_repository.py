from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from domain.entities.expense import Expense
from domain.value_objects.ids import ExpenseId, GroupId, UserId

class ExpenseRepository(ABC):
  """Port for persisting and retrieving Expense entities."""

  @abstractmethod
  def get_by_id(self, group_id: GroupId, expense_id: ExpenseId) -> Expense | None:
    ...

  @abstractmethod
  def save(self, expense: Expense) -> None:
    ...

  @abstractmethod
  def get_for_group(self, group_id: GroupId, *, since: datetime | None = None) -> list[Expense]:
    """Retrieve all expenses for a group, optionally filtered by a timestamp."""
    ...

  @abstractmethod
  def get_by_user(self, user_id: UserId) -> list[Expense]:
    """Retrieve all expenses that a user is involved in, either as payer or participant."""
    ...