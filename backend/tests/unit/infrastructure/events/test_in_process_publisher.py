from __future__ import annotations

import logging

import pytest

from domain.events.base import DomainEvent
from domain.events.publisher import EventPublisher
from domain.events.subscriber import EventSubscriber
from domain.value_objects.ids import GroupId, UserId
from domain.events.group_events import GroupClosed, MemberAdded
from infrastructure.events.in_process_publisher import InProcessEventPublisher
from tests.builders import id_for
from tests.fakes import ExplodingSubscriber, RecordingSubscriber


@pytest.fixture
def a_group() -> GroupId:
  return id_for(GroupId, "palawan-trip")


@pytest.fixture
def member_added(a_group: GroupId, alice: UserId) -> MemberAdded:
  return MemberAdded(group_id=a_group, member_id=alice)


@pytest.fixture
def group_closed(a_group: GroupId) -> GroupClosed:
  return GroupClosed(group_id=a_group)


class TestPortConformance:
  def test_it_is_an_event_publisher(self):
    """Use cases will depend on the port, so the adapter has to satisfy it."""
    assert isinstance(InProcessEventPublisher(), EventPublisher)

  def test_the_port_cannot_be_used_directly(self):
    with pytest.raises(TypeError, match="abstract"):
      EventPublisher()  # type: ignore[abstract]

  def test_the_subscriber_port_cannot_be_used_directly(self):
    with pytest.raises(TypeError, match="abstract"):
      EventSubscriber()  # type: ignore[abstract]


class TestFanOut:
  def test_delivers_an_event_to_the_only_subscriber(self, member_added):
    subscriber = RecordingSubscriber()

    InProcessEventPublisher([subscriber]).publish([member_added])

    assert subscriber.handled == [member_added]

  def test_delivers_every_event_to_every_subscriber(self, member_added, group_closed):
    bell = RecordingSubscriber("bell")
    email = RecordingSubscriber("email")

    InProcessEventPublisher([bell, email]).publish([member_added, group_closed])

    assert bell.handled == [member_added, group_closed]
    assert email.handled == [member_added, group_closed]

  def test_keeps_the_order_the_events_were_recorded_in(self, member_added, group_closed):
    """The list comes straight from `pull_events`, which is already in order."""
    subscriber = RecordingSubscriber()

    InProcessEventPublisher([subscriber]).publish([group_closed, member_added])

    assert subscriber.types() == ["GroupClosed", "MemberAdded"]

  def test_hands_over_the_same_event_object(self, member_added):
    """Subscribers read the event as recorded; nothing copies or rebuilds it in between."""
    subscriber = RecordingSubscriber()

    InProcessEventPublisher([subscriber]).publish([member_added])

    assert subscriber.handled[0] is member_added

  def test_finishes_one_event_everywhere_before_starting_the_next(
    self, member_added, group_closed
  ):
    """Event-major, not subscriber-major: each event reaches every channel before the next
    one starts, so two channels cannot drift apart when one is slow."""
    order: list[str] = []

    class Noting(EventSubscriber):
      def __init__(self, name: str):
        self._name = name

      def handle(self, event: DomainEvent) -> None:
        order.append(f"{self._name}:{type(event).__name__}")

    InProcessEventPublisher([Noting("bell"), Noting("email")]).publish(
      [member_added, group_closed]
    )

    assert order == [
      "bell:MemberAdded", "email:MemberAdded", "bell:GroupClosed", "email:GroupClosed",
    ]


class TestNothingToDo:
  def test_publishing_no_events_calls_nobody(self):
    subscriber = RecordingSubscriber()

    InProcessEventPublisher([subscriber]).publish([])

    assert subscriber.handled == []

  def test_publishing_with_no_subscribers_is_harmless(self, member_added):
    """The publisher is wired before any channel exists, so an empty roster must not raise."""
    InProcessEventPublisher().publish([member_added])

  def test_defaults_to_an_empty_roster(self, member_added):
    InProcessEventPublisher(None).publish([member_added])


class TestSubscribe:
  def test_a_late_subscriber_receives_what_comes_after_it(self, member_added, group_closed):
    publisher = InProcessEventPublisher()
    subscriber = RecordingSubscriber()

    publisher.publish([member_added])
    publisher.subscribe(subscriber)
    publisher.publish([group_closed])

    assert subscriber.types() == ["GroupClosed"]

  def test_subscribing_does_not_replace_the_existing_roster(self, member_added):
    bell = RecordingSubscriber("bell")
    email = RecordingSubscriber("email")
    publisher = InProcessEventPublisher([bell])

    publisher.subscribe(email)
    publisher.publish([member_added])

    assert bell.handled == [member_added]
    assert email.handled == [member_added]

  def test_the_roster_passed_in_is_copied(self, member_added):
    """Mutating the caller's list afterwards must not quietly add a channel."""
    roster: list[EventSubscriber] = []
    publisher = InProcessEventPublisher(roster)
    late = RecordingSubscriber()

    roster.append(late)
    publisher.publish([member_added])

    assert late.handled == []


class TestAFailingSubscriber:
  def test_does_not_reach_the_caller(self, member_added):
    """Publishing happens after the write committed, so raising here would fail an
    operation that actually succeeded."""
    InProcessEventPublisher([ExplodingSubscriber()]).publish([member_added])

  def test_does_not_stop_the_subscribers_after_it(self, member_added):
    broken = ExplodingSubscriber()
    working = RecordingSubscriber()

    InProcessEventPublisher([broken, working]).publish([member_added])

    assert working.handled == [member_added]

  def test_does_not_stop_the_remaining_events(self, member_added, group_closed):
    broken = ExplodingSubscriber()
    working = RecordingSubscriber()

    InProcessEventPublisher([broken, working]).publish([member_added, group_closed])

    assert working.types() == ["MemberAdded", "GroupClosed"]

  def test_keeps_failing_without_being_removed(self, member_added, group_closed):
    """One bad delivery says nothing about the next; the roster is wiring, not state."""
    broken = ExplodingSubscriber()

    InProcessEventPublisher([broken]).publish([member_added, group_closed])

    assert len(broken.handled) == 2

  def test_is_logged_with_enough_to_find_it(self, member_added, caplog):
    with caplog.at_level(logging.ERROR):
      InProcessEventPublisher([ExplodingSubscriber()]).publish([member_added])

    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert "ExplodingSubscriber" in record.getMessage()
    assert "MemberAdded" in record.getMessage()
    assert member_added.event_id in record.getMessage()

  def test_the_log_carries_the_traceback(self, member_added, caplog):
    """`logger.exception`, not `logger.error` — without the traceback the log says a channel
    broke but not where."""
    with caplog.at_level(logging.ERROR):
      InProcessEventPublisher([ExplodingSubscriber()]).publish([member_added])

    assert caplog.records[0].exc_info is not None

  def test_one_log_line_per_failed_delivery(self, member_added, group_closed, caplog):
    with caplog.at_level(logging.ERROR):
      InProcessEventPublisher([ExplodingSubscriber()]).publish([member_added, group_closed])

    assert len(caplog.records) == 2

  def test_a_working_subscriber_logs_nothing(self, member_added, caplog):
    with caplog.at_level(logging.ERROR):
      InProcessEventPublisher([RecordingSubscriber()]).publish([member_added])

    assert caplog.records == []
