from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

@dataclass(frozen=True)
class DomainEvent:
  """Base class for domain events."""
  event_id: str = field(default_factory=lambda: str(uuid.uuid4()), kw_only=True)
  occured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc), kw_only=True)

class AggregateRoot:
  """Mixin providing pending-event bookkeeping for aggregate roots."""

  def record_event(self, event: DomainEvent) -> None:
    """Records a domain event to be published later."""
    if not hasattr(self, "_pending_events"):
      self._pending_events = []
    self._pending_events.append(event)

  def pull_events(self) -> list[DomainEvent]:
    """Returns and clears the list of pendign events."""
    events = getattr(self, "_pending_events", [])
    self._pending_events = []
    return events