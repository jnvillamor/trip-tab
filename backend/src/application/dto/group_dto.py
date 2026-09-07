from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from datetime import datetime

from domain.entities.group import Group


class _View(BaseModel):
  """Base for read models: immutable, strict about unknown fields, and trims string input."""

  model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class GroupMember(_View):
  user_id: str
  joined_at: datetime


class GroupView(_View):
  id: str
  name: str
  created_by: str
  members: list[GroupMember]

  @classmethod
  def from_entity(cls, group: Group) -> "GroupView":
    return cls(
      id=str(group.id),
      name=group.name,
      created_by=str(group.created_by),
      members=[
        GroupMember(user_id=str(member.user_id), joined_at=member.joined_at)
        for member in group.members
      ],
    )
