from __future__ import annotations

from dataclasses import dataclass

from application.dto.group_dto import GroupView
from application.exceptions import NotFoundError
from domain.entities.group import Group, GroupMembershipError
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import GroupId, UserId

@dataclass(frozen=True)
class AddGroupMemberInput:
  group_id: str
  user_id: str

class AddGroupMemberUseCase:
  def __init__(self, group_repository: GroupRepository):
    self._groups = group_repository

  def execute(self, input_data: AddGroupMemberInput) -> GroupView:
    group_id = GroupId(input_data.group_id)
    user_id = UserId(input_data.user_id)

    group = self._groups.get_by_id(group_id)
    if not group:
      raise NotFoundError(f"Group with ID {group_id} not found.")

    group.add_member(user_id)
    self._groups.save(group)
    return GroupView.from_entity(group)