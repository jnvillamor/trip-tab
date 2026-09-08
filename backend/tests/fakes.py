"""In-memory stand-ins for the domain repository ports.

Each fake snapshots on write and on read, so a use case that mutates an entity but
forgets to call `save` leaves the store untouched — and the test notices.
"""

from __future__ import annotations

import copy
from datetime import datetime

from domain.entities.expense import Expense
from domain.entities.group import Group
from domain.entities.settlement import Settlement
from domain.repositories.expense_repository import ExpenseRepository
from domain.repositories.group_repository import GroupRepository
from domain.repositories.settlement_repository import SettlementRepository
from domain.value_objects.ids import ExpenseId, GroupId, SettlementId, UserId


class InMemoryGroupRepository(GroupRepository):
  def __init__(self, groups: list[Group] | None = None):
    self._groups: dict[GroupId, Group] = {}
    for group in groups or []:
      self._groups[group.id] = copy.deepcopy(group)

    self.saved: list[Group] = []
    """Every group handed to `save`, in order, for asserting the write actually happened."""

    self.deleted: list[GroupId] = []

  def get_by_id(self, group_id: GroupId) -> Group | None:
    stored = self._groups.get(group_id)
    return copy.deepcopy(stored) if stored is not None else None

  def save(self, group: Group) -> None:
    self._groups[group.id] = copy.deepcopy(group)
    self.saved.append(copy.deepcopy(group))

  def get_for_user(self, user_id: UserId) -> list[Group]:
    return [copy.deepcopy(g) for g in self._groups.values() if g.has_member(user_id)]

  def delete(self, group_id: GroupId) -> None:
    self._groups.pop(group_id, None)
    self.deleted.append(group_id)


class InMemoryExpenseRepository(ExpenseRepository):
  def __init__(self, expenses: list[Expense] | None = None):
    self._expenses: dict[ExpenseId, Expense] = {}
    for expense in expenses or []:
      self._expenses[expense.id] = copy.deepcopy(expense)

    self.saved: list[Expense] = []
    """Every expense handed to `save`, in order, for asserting the write actually happened."""

    self.queried_groups: list[GroupId] = []
    """Every group id passed to `get_for_group`, in order, so reads can be asserted too."""

  def get_by_id(self, group_id: GroupId, expense_id: ExpenseId) -> Expense | None:
    stored = self._expenses.get(expense_id)
    if stored is None or stored.group_id != group_id:
      return None
    return copy.deepcopy(stored)

  def save(self, expense: Expense) -> None:
    self._expenses[expense.id] = copy.deepcopy(expense)
    self.saved.append(copy.deepcopy(expense))

  def get_for_group(self, group_id: GroupId, *, since: datetime | None = None) -> list[Expense]:
    self.queried_groups.append(group_id)
    return [
      copy.deepcopy(expense)
      for expense in self._expenses.values()
      if expense.group_id == group_id and (since is None or expense.created_at >= since)
    ]

  def get_by_user(self, user_id: UserId) -> list[Expense]:
    return [
      copy.deepcopy(expense)
      for expense in self._expenses.values()
      if expense.paid_by == user_id
      or any(split.user_id == user_id for split in expense.splits)
    ]


class InMemorySettlementRepository(SettlementRepository):
  def __init__(self, settlements: list[Settlement] | None = None):
    self._settlements: dict[SettlementId, Settlement] = {}
    for settlement in settlements or []:
      self._settlements[settlement.id] = copy.deepcopy(settlement)

    self.saved: list[Settlement] = []
    """Every settlement handed to `save`, in order."""

    self.queried_groups: list[GroupId] = []
    """Every group id passed to `get_for_group`, in order."""

  def get_by_id(self, group_id: GroupId, settlement_id: SettlementId) -> Settlement | None:
    stored = self._settlements.get(settlement_id)
    if stored is None or stored.group_id != group_id:
      return None
    return copy.deepcopy(stored)

  def save(self, settlement: Settlement) -> None:
    self._settlements[settlement.id] = copy.deepcopy(settlement)
    self.saved.append(copy.deepcopy(settlement))

  def get_for_group(self, group_id: GroupId) -> list[Settlement]:
    self.queried_groups.append(group_id)
    return [
      copy.deepcopy(settlement)
      for settlement in self._settlements.values()
      if settlement.group_id == group_id
    ]
