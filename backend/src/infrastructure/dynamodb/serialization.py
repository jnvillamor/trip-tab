from __future__ import annotations

from datetime import datetime, timezone

def to_iso(dt: datetime) -> str:
  return dt.astimezone(timezone.utc).isoformat()

def from_iso(value: str) -> datetime:
  return datetime.fromisoformat(value)