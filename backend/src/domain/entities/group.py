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

  def __post_init__(self) -> None:
    if not self.name.strip():
      raise ValueError("Group name cannot be empty")
    if not any(member.user_id == self.created_by for member in self.members):
      raise GroupMembershipError("The creator must be a member of the group.")

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
    
