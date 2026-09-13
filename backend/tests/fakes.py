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
from domain.events.base import DomainEvent
from domain.events.publisher import EventPublisher
from domain.events.subscriber import EventSubscriber
from domain.repositories.expense_repository import ExpenseRepository
from domain.repositories.group_repository import GroupRepository
from domain.repositories.settlement_repository import SettlementRepository
from domain.value_objects.ids import ExpenseId, GroupId, SettlementId, UserId


def _stored(entity):
  """Snapshots an entity the way a repository round trip does.

  A real repository writes named fields, so pending events never survive a save and a
  rebuilt aggregate comes back with nothing recorded. A plain `deepcopy` would carry
  `_pending_events` along and hand the next caller events that were already published.
  """
  clone = copy.deepcopy(entity)
  if hasattr(clone, "_pending_events"):
    clone._pending_events = []
  return clone



class InMemoryGroupRepository(GroupRepository):
  def __init__(self, groups: list[Group] | None = None):
    self._groups: dict[GroupId, Group] = {}
    for group in groups or []:
      self._groups[group.id] = _stored(group)

    self.saved: list[Group] = []
    """Every group handed to `save`, in order, for asserting the write actually happened."""

    self.deleted: list[GroupId] = []

    self.queried_users: list[UserId] = []
    """Every user id passed to `get_for_user`, in order, so reads can be asserted too."""

  def get_by_id(self, group_id: GroupId) -> Group | None:
    stored = self._groups.get(group_id)
    return _stored(stored) if stored is not None else None

  def save(self, group: Group) -> None:
    self._groups[group.id] = _stored(group)
    self.saved.append(_stored(group))

  def get_for_user(self, user_id: UserId) -> list[Group]:
    self.queried_users.append(user_id)
    return [_stored(g) for g in self._groups.values() if g.has_member(user_id)]

  def delete(self, group_id: GroupId) -> None:
    self._groups.pop(group_id, None)
    self.deleted.append(group_id)


class InMemoryExpenseRepository(ExpenseRepository):
  def __init__(self, expenses: list[Expense] | None = None):
    self._expenses: dict[ExpenseId, Expense] = {}
    for expense in expenses or []:
      self._expenses[expense.id] = _stored(expense)

    self.saved: list[Expense] = []
    """Every expense handed to `save`, in order, for asserting the write actually happened."""

    self.queried_groups: list[GroupId] = []
    """Every group id passed to `get_for_group`, in order, so reads can be asserted too."""

  def get_by_id(self, group_id: GroupId, expense_id: ExpenseId) -> Expense | None:
    stored = self._expenses.get(expense_id)
    if stored is None or stored.group_id != group_id:
      return None
    return _stored(stored)

  def save(self, expense: Expense) -> None:
    self._expenses[expense.id] = _stored(expense)
    self.saved.append(_stored(expense))

  def get_for_group(self, group_id: GroupId, *, since: datetime | None = None) -> list[Expense]:
    self.queried_groups.append(group_id)
    return [
      _stored(expense)
      for expense in self._expenses.values()
      if expense.group_id == group_id and (since is None or expense.created_at >= since)
    ]

  def get_by_user(self, user_id: UserId) -> list[Expense]:
    return [
      _stored(expense)
      for expense in self._expenses.values()
      if expense.paid_by == user_id
      or any(split.user_id == user_id for split in expense.splits)
    ]


class InMemorySettlementRepository(SettlementRepository):
  def __init__(self, settlements: list[Settlement] | None = None):
    self._settlements: dict[SettlementId, Settlement] = {}
    for settlement in settlements or []:
      self._settlements[settlement.id] = _stored(settlement)

    self.saved: list[Settlement] = []
    """Every settlement handed to `save`, in order."""

    self.queried_groups: list[GroupId] = []
    """Every group id passed to `get_for_group`, in order."""

  def get_by_id(self, group_id: GroupId, settlement_id: SettlementId) -> Settlement | None:
    stored = self._settlements.get(settlement_id)
    if stored is None or stored.group_id != group_id:
      return None
    return _stored(stored)

  def save(self, settlement: Settlement) -> None:
    self._settlements[settlement.id] = _stored(settlement)
    self.saved.append(_stored(settlement))

  def get_for_group(self, group_id: GroupId) -> list[Settlement]:
    self.queried_groups.append(group_id)
    return [
      _stored(settlement)
      for settlement in self._settlements.values()
      if settlement.group_id == group_id
    ]


class RecordingSubscriber(EventSubscriber):
  """Records every event it is handed, for asserting what reached a channel."""

  def __init__(self, name: str = "recording"):
    self.name = name

    self.handled: list[DomainEvent] = []
    """Every event passed to `handle`, in order."""

  def handle(self, event: DomainEvent) -> None:
    self.handled.append(event)

  def types(self) -> list[str]:
    """The class names of what it handled, which is what most assertions compare."""
    return [type(event).__name__ for event in self.handled]


class ExplodingSubscriber(EventSubscriber):
  """Raises on every event, for asserting one bad channel cannot take out the others."""

  def __init__(self, error: Exception | None = None):
    self._error = error or RuntimeError("subscriber is down")

    self.handled: list[DomainEvent] = []
    """Every event it was asked to handle, recorded before it raises."""

  def handle(self, event: DomainEvent) -> None:
    self.handled.append(event)
    raise self._error


class InMemoryEventPublisher(EventPublisher):
  """Collects what a use case publishes instead of fanning it out.

  Use-case tests assert on `published` to check an operation announced what it should; the
  real fan-out is exercised in the `InProcessEventPublisher` tests.
  """

  def __init__(self):
    self.published: list[DomainEvent] = []
    """Every event handed to `publish`, flattened, in order."""

    self.batches: list[list[DomainEvent]] = []
    """Each `publish` call as its own list, so a test can assert one call per operation."""

  def publish(self, events: list[DomainEvent]) -> None:
    self.batches.append(list(events))
    self.published.extend(events)

  def types(self) -> list[str]:
    return [type(event).__name__ for event in self.published]
