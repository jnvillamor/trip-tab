from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.settlement import Settlement
from domain.value_objects.ids import GroupId, SettlementId

class SettlementRepository(ABC):
  """Port for persisting and retrieving Settlement entities."""

  @abstractmethod
  def get_by_id(self, group_id: GroupId, settlement_id: SettlementId) -> Settlement | None:
    ...

  @abstractmethod
  def save(self, settlement: Settlement) -> None:
    ...

  @abstractmethod
  def get_for_group(self, group_id: GroupId) -> list[Settlement]:
    """Retrieve all settlements for a group."""
    ...