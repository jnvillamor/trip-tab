from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.exceptions import DomainError
from domain.value_objects.ids import GroupId, SettlementId, UserId
from domain.value_objects.money import Money 

class InvalidSettlementError(DomainError):
  """Raised for invalid settlement operations."""

@dataclass
class Settlement:
  """Records a payment from one user to another within a group."""

  id: SettlementId
  group_id: GroupId
  from_user: UserId
  to_user: UserId
  amount: Money
  settled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

  def __post_init__(self) -> None:
    if self.from_user == self.to_user:
      raise InvalidSettlementError("A user cannot settle a balance with themselves.")
    if not self.amount.is_positive():
      raise InvalidSettlementError("Settlement amount must be positive.")