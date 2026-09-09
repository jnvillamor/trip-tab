from __future__ import annotations

from dataclasses import dataclass

from application.exceptions import NotAuthorizedError, NotFoundError
from application.dto.settlement_dto import SettlementView
from domain.entities.settlement import Settlement
from domain.repositories.group_repository import GroupRepository
from domain.repositories.settlement_repository import SettlementRepository
from domain.value_objects.ids import GroupId, SettlementId, UserId

@dataclass(frozen=True)
class ReverseSettlementInput:
  group_id: str
  settlement_id: str
  requested_by: str

class ReverseSettlementUseCase:
  def __init__(self, group_repository: GroupRepository, settlement_repository: SettlementRepository):
    self._groups = group_repository
    self._settlements = settlement_repository

  def execute(self, input_data: ReverseSettlementInput) -> SettlementView:
    group_id = GroupId(input_data.group_id)
    group = self._groups.get_by_id(group_id)
    if group is None:
      raise NotFoundError(f"Group with ID {input_data.group_id} not found.")

    settlement_id = SettlementId(input_data.settlement_id)
    original = self._settlements.get_by_id(group_id, settlement_id)
    if original is None:
      raise NotFoundError(f"Settlement with ID {input_data.settlement_id} not found in group {input_data.group_id}.")

    requested_by = UserId(input_data.requested_by)
    if not group.has_member(requested_by):
      raise NotAuthorizedError(f"User {input_data.requested_by} is not a member of group {input_data.group_id}.")
    if not original.involves(requested_by):
      raise NotAuthorizedError(f"User {input_data.requested_by} is not involved in settlement {input_data.settlement_id}.")

    reversal = Settlement.create_reversal(
      original=original,
      id=SettlementId.new(),
    )
    original.mark_reversed()

    self._settlements.save(original)
    self._settlements.save(reversal)

    return SettlementView.from_entity(reversal)
