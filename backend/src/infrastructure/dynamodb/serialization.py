from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

def to_decimal(value: int) -> Decimal:
  return Decimal(value)

def from_decimal(value: Decimal) -> int:
  return int(value)

def to_iso(dt: datetime) -> str:
  return dt.astimezone(timezone.utc).isoformat()

def from_iso(value: str) -> datetime:
  return datetime.fromisoformat(value)