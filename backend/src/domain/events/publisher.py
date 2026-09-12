from __future__ import annotations

from abc import ABC, abstractmethod

from domain.events.base import DomainEvent

class EventPublisher(ABC):
  """Port for handing recorded events on to whoever reacts to them.

  Use cases depend on this rather than on a subscriber list, so swapping in-process fan-out
  for an outbox or a stream consumer later touches the wiring and nothing else.
  """

  @abstractmethod
  def publish(self, events: list[DomainEvent]) -> None:
    """Publishes events in the order they were recorded. An empty list is a no-op."""
    ...
