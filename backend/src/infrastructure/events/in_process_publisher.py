from __future__ import annotations

import logging

from domain.events.base import DomainEvent
from domain.events.publisher import EventPublisher
from domain.events.subscriber import EventSubscriber

logger = logging.getLogger(__name__)

class InProcessEventPublisher(EventPublisher):
  """Fans each event out to every subscriber, in the caller's thread."""

  def __init__(self, subscribers: list[EventSubscriber] | None = None):
    self._subscribers: list[EventSubscriber] = list(subscribers or [])

  def subscribe(self, subscriber: EventSubscriber) -> None:
    self._subscribers.append(subscriber)

  def publish(self, events: list[DomainEvent]) -> None:
    for event in events:
      for subscriber in self._subscribers:
        self._deliver(subscriber, event)

  def _deliver(self, subscriber: EventSubscriber, event: DomainEvent) -> None:
    """A failing subscriber is logged and skipped."""
    try:
      subscriber.handle(event)
    except Exception:
      logger.exception(
        "subscriber %s failed handling %s (event_id=%s)",
        type(subscriber).__name__,
        type(event).__name__,
        event.event_id,
      )
