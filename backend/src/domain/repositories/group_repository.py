from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.group import Group
from domain.value_objects.ids import GroupId, UserId

class GroupRepository(ABC):
  """Port for persisting and retrieving Group entities."""

  @abstractmethod
  def get_by_id(self, group_id: GroupId) -> Group | None:
    ...

  @abstractmethod
  def save(self, group: Group) -> None:
    ...

  @abstractmethod
  def get_for_user(self, user_id: UserId) -> list[Group]:
    """Retrieve all groups that a user is a member of."""
    ...
    
  @abstractmethod
  def delete(self, group_id: GroupId) -> None:
    ...