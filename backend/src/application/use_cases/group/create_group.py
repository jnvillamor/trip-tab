from __future__ import annotations

from dataclasses import dataclass

from application.dto.group_dto import GroupView
from domain.events.publisher import EventPublisher
from domain.entities.group import Group
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import GroupId, UserId

@dataclass(frozen=True)
class CreateGroupInput:
  name: str
  created_by: str

class CreateGroupUseCase:
  def __init__(self, group_repository: GroupRepository, event_publisher: EventPublisher):
    self._groups = group_repository
    self._publisher = event_publisher

  def execute(self, input_data: CreateGroupInput) -> GroupView:
    group = Group.create(id=GroupId.new(), name=input_data.name, created_by=UserId(input_data.created_by))
    self._groups.save(group)
    self._publisher.publish(group.pull_events())
    return GroupView.from_entity(group)