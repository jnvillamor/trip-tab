from __future__ import annotations

from dataclasses import dataclass

from domain.events.base import DomainEvent
from domain.value_objects.ids import SettlementId, GroupId, UserId
from domain.value_objects.money import Money

@dataclass(frozen=True)
class SettlementRecorded(DomainEvent):
  settlement_id: SettlementId
  group_id: GroupId
  from_user: UserId
  to_user: UserId
  amount: Money

@dataclass(frozen=True)
class SettlementReversed(DomainEvent):
  settlement_id: SettlementId
  reversal_id: SettlementId
  group_id: GroupId