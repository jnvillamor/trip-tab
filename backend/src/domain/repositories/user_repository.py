from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.user import User
from domain.value_objects.ids import UserId

class UserRepository(ABC):
  """Port for persisting and retrieving User entities."""

  @abstractmethod
  def get_by_id(self, user_id: UserId) -> User | None:
    ...

  @abstractmethod
  def save(self, user: User) -> None:
    ...