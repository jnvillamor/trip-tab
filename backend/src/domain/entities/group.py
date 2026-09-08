from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.exceptions import DomainError
from domain.value_objects.ids import GroupId, UserId

class GroupMembershipError(DomainError):
  """Raised for invalid membership operations in a group."""

@dataclass(frozen=True)
class GroupMember:
  user_id: UserId
  joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class Group:
  id: GroupId
  name: str
  created_by: UserId
  members: list[GroupMember] = field(default_factory=list)
  closed_at: datetime | None = None

  def __post_init__(self) -> None:
    if not self.name.strip():
      raise ValueError("Group name cannot be empty")
    if not any(member.user_id == self.created_by for member in self.members):
      self.members.append(GroupMember(user_id=self.created_by))

  @classmethod
  def create(cls, id: GroupId, name: str, created_by: UserId) -> Group:
    group = cls(id=id, name=name, created_by=created_by)
    return group

  def has_member(self, user_id: UserId) -> bool:
    return any(member.user_id == user_id for member in self.members)

  def add_member(self, user_id: UserId) -> None:
    if self.has_member(user_id):
      raise GroupMembershipError(f"User {user_id} is already a member of the group.")
    self.members.append(GroupMember(user_id=user_id))

  def remove_member(self, user_id: UserId, *, has_zero_balance: bool) -> None:
    """`has_zero_balance` indiccates whether the user has any unsettled balances in the group."""
    if not self.has_member(user_id):
      raise GroupMembershipError(f"User {user_id} is not a memeber of {self.id}:{self.name}")
    if not has_zero_balance:
      raise GroupMembershipError(f"User {user_id} has unsettled balances in the group.")
    self.members = [member for member in self.members if member.user_id != user_id]

  def member_ids(self) -> list[UserId]:
    return [member.user_id for member in self.members]

  @property
  def is_closed(self) -> bool: 
    return self.closed_at is not None

  def close(self) -> None:
    if self.is_closed:
      raise DomainError(f"Group {self.id}:{self.name} is already closed.")
    self.closed_at = datetime.now(timezone.utc)

  def reopen(self) -> None:
    if not self.is_closed:
      raise DomainError(f"Group {self.id}:{self.name} is not closed.")
    self.closed_at = None
  
