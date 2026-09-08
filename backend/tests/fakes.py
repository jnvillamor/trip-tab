"""In-memory stand-ins for the domain repository ports.

Each fake snapshots on write and on read, so a use case that mutates an entity but
forgets to call `save` leaves the store untouched — and the test notices.
"""

from __future__ import annotations

import copy

from domain.entities.group import Group
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import GroupId, UserId


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
