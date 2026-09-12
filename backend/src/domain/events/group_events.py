from __future__ import annotations

from dataclasses import dataclass

from domain.events.base import DomainEvent
from domain.value_objects.ids import GroupId, UserId

@dataclass(frozen=True)
class GroupCreated(DomainEvent):
  group_id: GroupId
  created_by: UserId
  name: str

@dataclass(frozen=True)
class MemberAdded(DomainEvent):
  group_id: GroupId
  member_id: UserId

@dataclass(frozen=True)
class MemberRemoved(DomainEvent):
  group_id: GroupId
  member_id: UserId

@dataclass(frozen=True)
class GroupDeleted(DomainEvent):
  group_id: GroupId

@dataclass(frozen=True)
class GroupClosed(DomainEvent):
  group_id: GroupId

@dataclass(frozen=True)
class GroupReopened(DomainEvent):
  group_id: GroupId