from __future__ import annotations

from abc import ABC, abstractmethod

from domain.events.base import DomainEvent

class EventSubscriber(ABC):
  """Port for anything that reacts to a domain event.

  One subscriber per delivery channel — an in-app bell today, email later — so a new
  channel is a new class registered with the publisher, not a change to any use case.
  """

  @abstractmethod
  def handle(self, event: DomainEvent) -> None:
    """Reacts to one event. Subscribers that do not care about an event type ignore it."""
    ...
