from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict

from domain.entities.settlement import Settlement

class _View(BaseModel):
  """Base for read models: immutable and strict about unknown fields.

  Deliberately does not trim strings: a view reports what the domain holds, so whitespace
  that got stored is a bug to surface, not one to hide.
  """

  model_config = ConfigDict(frozen=True, extra="forbid")

class SettlementView(_View):
  id: str
  group_id: str
  from_user: str
  to_user: str
  amount_cents: int
  currency: str
  settlted_at: datetime
  reverses: str | None
  reversed_at: datetime | None

  @classmethod
  def from_entity(cls, settlement: "Settlement") -> "SettlementView":
    return cls(
      id=str(settlement.id),
      group_id=str(settlement.group_id),
      from_user=str(settlement.from_user),
      to_user=str(settlement.to_user),
      amount_cents=settlement.amount.amount_cents,
      currency=settlement.amount.currency,
      settlted_at=settlement.settled_at,
      reverses=str(settlement.reverses) if settlement.reverses else None,
      reversed_at=settlement.reversed_at,
    )