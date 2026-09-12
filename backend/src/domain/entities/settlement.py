from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.events.base import AggregateRoot
from domain.events.settlement_events import SettlementRecorded, SettlementReversed
from domain.exceptions import DomainError
from domain.value_objects.ids import GroupId, SettlementId, UserId
from domain.value_objects.money import Money 

class InvalidSettlementError(DomainError):
  """Raised for invalid settlement operations."""

@dataclass
class Settlement(AggregateRoot):
  """Records a payment from one user to another within a group."""

  id: SettlementId
  group_id: GroupId
  from_user: UserId
  to_user: UserId
  amount: Money
  settled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
  reverses: SettlementId | None = None
  reversed_at: datetime | None = None

  def __post_init__(self) -> None:
    if self.from_user == self.to_user:
      raise InvalidSettlementError("A user cannot settle a balance with themselves.")
    if not self.amount.is_positive():
      raise InvalidSettlementError("Settlement amount must be positive.")

  def involves(self, user_id: UserId) -> bool:
    return user_id in (self.from_user, self.to_user)

  def counter_party(self, user_id: UserId) -> UserId:
    return self.to_user if user_id == self.from_user else self.from_user

  def is_reversal(self) -> bool:
    return self.reverses is not None

  def mark_reversed(self) -> None:
    if self.reversed_at is not None:
      raise InvalidSettlementError("Settlement has already been reversed.")
    self.reversed_at = datetime.now(timezone.utc)

  @classmethod
  def create(
    cls,
    id: SettlementId,
    group_id: GroupId,
    from_user: UserId,
    to_user: UserId,
    amount: Money,
  ) -> "Settlement":
    """Factory to create a new settlement."""
    settlement = cls(
      id=id,
      group_id=group_id,
      from_user=from_user,
      to_user=to_user,
      amount=amount
    )
    settlement.record_event(
      SettlementRecorded(
        settlement_id=settlement.id,
        group_id=settlement.group_id,
        from_user=settlement.from_user,
        to_user=settlement.to_user,
        amount=settlement.amount
      )
    )
    return settlement

  @classmethod
  def create_reversal(cls, id: SettlementId, original: "Settlement") -> "Settlement":
    """Factory to create a reversal settlement."""
    if original.reversed_at is not None:
      raise InvalidSettlementError(f"{original.id} has already been reversed.")
    if original.is_reversal():
      raise InvalidSettlementError(f"{original.id} is a reversal and cannot be reversed again.")
    
    reversal = cls(
      id=id,
      group_id=original.group_id,
      from_user=original.to_user,
      to_user=original.from_user,
      amount=original.amount,
      reverses=original.id
    )
    reversal.record_event(
      SettlementReversed(
        settlement_id=original.id,
        reversal_id=reversal.id,
        group_id=reversal.group_id
      )
    )
    return reversal
