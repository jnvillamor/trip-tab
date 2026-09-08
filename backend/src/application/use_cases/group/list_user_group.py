from __future__ import annotations

from dataclasses import dataclass

from application.dto.group_dto import GroupView
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import UserId 

@dataclass(frozen=True)
class ListUserGroupsInput:
  user_id: str

class ListUserGroupsUseCase:
  def __init__(self, group_repository: GroupRepository):
    self._groups = group_repository

  def execute(self, input_data: ListUserGroupsInput) -> list[GroupView]:
    user_id = UserId(input_data.user_id)
    groups = self._groups.get_for_user(user_id)
    return [GroupView.from_entity(group) for group in groups]