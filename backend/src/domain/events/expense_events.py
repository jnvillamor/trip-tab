from __future__ import annotations

from dataclasses import dataclass

from domain.events.base import DomainEvent
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money

@dataclass(frozen=True)
class ExpenseCreated(DomainEvent):
  group_id: GroupId
  expense_id: ExpenseId
  created_by: UserId
  amount: Money
  description: str

@dataclass(frozen=True)
class ExpenseEdited(DomainEvent):
  group_id: GroupId
  expense_id: ExpenseId
  new_amount: Money 
  new_description: str

@dataclass(frozen=True)
class ExpenseDeleted(DomainEvent):
  group_id: GroupId
  expense_id: ExpenseId