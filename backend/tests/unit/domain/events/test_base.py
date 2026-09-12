from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from domain.events.base import AggregateRoot, DomainEvent


@dataclass(frozen=True)
class ExpenseRecorded(DomainEvent):
  """A stand-in event.

  It declares a field with no default *positionally*, which only compiles because the
  base class marks `event_id` and `occured_at` as `kw_only` — a plain default would
  push them ahead of this one and raise at class-definition time.
  """

  expense_id: str
  description: str = "Dinner"


@dataclass(frozen=True)
class GroupRenamed(DomainEvent):
  group_id: str


class Group(AggregateRoot):
  """The mixin's intended host: an aggregate that records as it changes."""

  def __init__(self, group_id: str) -> None:
    self.group_id = group_id

  def rename(self) -> None:
    self.record_event(GroupRenamed(group_id=self.group_id))


@dataclass
class DataclassAggregate(AggregateRoot):
  """The entities in this project are dataclasses, so the mixin has to work on one."""

  name: str = "Palawan Trip"
  tags: list[str] = field(default_factory=list)


class TestDomainEventIdentity:
  def test_generates_an_event_id_without_being_asked(self):
    assert ExpenseRecorded(expense_id="e1").event_id

  def test_the_generated_id_is_a_uuid(self):
    event = ExpenseRecorded(expense_id="e1")

    # Stored as a string so it serializes straight to JSON, but it has to parse back.
    assert str(uuid.UUID(event.event_id)) == event.event_id

  def test_every_event_gets_its_own_id(self):
    ids = {ExpenseRecorded(expense_id="e1").event_id for _ in range(100)}

    # A shared mutable default would hand every event the same id and make
    # deduplication downstream collapse unrelated events into one.
    assert len(ids) == 100

  def test_an_explicit_id_is_kept(self):
    assert ExpenseRecorded(expense_id="e1", event_id="fixed").event_id == "fixed"


class TestDomainEventTimestamp:
  def test_stamps_the_time_it_was_created(self):
    before = datetime.now(timezone.utc)
    event = ExpenseRecorded(expense_id="e1")
    after = datetime.now(timezone.utc)

    assert before <= event.occured_at <= after

  def test_the_timestamp_is_timezone_aware_utc(self):
    """A naive timestamp cannot be compared against an aware one — it raises — and every
    other timestamp in the domain (`Expense.created_at`, `Settlement.settled_at`) is aware."""
    occured_at = ExpenseRecorded(expense_id="e1").occured_at

    assert occured_at.tzinfo is not None
    assert occured_at.utcoffset() == timezone.utc.utcoffset(None)

  def test_an_explicit_timestamp_is_kept(self):
    stamped = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    assert ExpenseRecorded(expense_id="e1", occured_at=stamped).occured_at == stamped


class TestDomainEventValueSemantics:
  def test_is_frozen(self):
    """Events are a record of what already happened; rewriting one rewrites history."""
    event = ExpenseRecorded(expense_id="e1")

    with pytest.raises(Exception):
      event.expense_id = "e2"  # type: ignore[misc]

  def test_is_hashable(self):
    event = ExpenseRecorded(expense_id="e1")

    assert len({event, event}) == 1

  def test_two_events_with_the_same_fields_are_equal(self):
    stamped = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    first = ExpenseRecorded(expense_id="e1", event_id="fixed", occured_at=stamped)
    second = ExpenseRecorded(expense_id="e1", event_id="fixed", occured_at=stamped)

    assert first == second

  def test_two_events_of_the_same_kind_differ_by_their_generated_id(self):
    stamped = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    first = ExpenseRecorded(expense_id="e1", occured_at=stamped)
    second = ExpenseRecorded(expense_id="e1", occured_at=stamped)

    assert first != second

  def test_different_event_types_are_never_equal(self):
    stamped = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    expense = ExpenseRecorded(expense_id="shared", event_id="fixed", occured_at=stamped)
    group = GroupRenamed(group_id="shared", event_id="fixed", occured_at=stamped)

    assert expense != group

  def test_the_base_event_can_be_built_on_its_own(self):
    """Nothing forces a payload, so `DomainEvent()` has to stand up by itself."""
    event = DomainEvent()

    assert event.event_id and event.occured_at


class TestPullEvents:
  def test_a_fresh_aggregate_has_nothing_pending(self):
    """`_pending_events` is created lazily, so `pull_events` runs before it exists."""
    assert Group("g1").pull_events() == []

  def test_returns_what_was_recorded(self):
    group = Group("g1")

    group.rename()

    assert [type(event) for event in group.pull_events()] == [GroupRenamed]

  def test_keeps_the_order_events_were_recorded_in(self):
    aggregate = AggregateRoot()
    first = GroupRenamed(group_id="first")
    second = GroupRenamed(group_id="second")
    third = GroupRenamed(group_id="third")

    for event in (first, second, third):
      aggregate.record_event(event)

    assert aggregate.pull_events() == [first, second, third]

  def test_hands_back_the_same_event_object(self):
    aggregate = AggregateRoot()
    event = GroupRenamed(group_id="g1")
    aggregate.record_event(event)

    assert aggregate.pull_events()[0] is event

  def test_records_the_same_event_twice_if_asked_twice(self):
    """Deduplication is the publisher's job; the aggregate records what it is told."""
    aggregate = AggregateRoot()
    event = GroupRenamed(group_id="g1")

    aggregate.record_event(event)
    aggregate.record_event(event)

    assert aggregate.pull_events() == [event, event]


class TestPullEventsClears:
  def test_a_second_pull_comes_back_empty(self):
    """Pulling is what hands events to the publisher — leaving them behind publishes twice."""
    group = Group("g1")
    group.rename()

    group.pull_events()

    assert group.pull_events() == []

  def test_events_recorded_after_a_pull_are_returned_by_the_next_one(self):
    group = Group("g1")
    group.rename()
    group.pull_events()

    group.rename()

    assert len(group.pull_events()) == 1

  def test_mutating_the_returned_list_does_not_refill_the_aggregate(self):
    group = Group("g1")
    group.rename()

    pulled = group.pull_events()
    pulled.append(GroupRenamed(group_id="smuggled"))

    assert group.pull_events() == []


class TestEventsAreNotSharedBetweenAggregates:
  def test_each_aggregate_keeps_its_own_events(self):
    first = Group("g1")
    second = Group("g2")

    first.rename()

    assert len(first.pull_events()) == 1
    assert second.pull_events() == []

  def test_pulling_from_one_aggregate_leaves_another_alone(self):
    first = Group("g1")
    second = Group("g2")
    first.rename()
    second.rename()

    first.pull_events()

    assert len(second.pull_events()) == 1


class TestMixesIntoADataclass:
  def test_a_dataclass_aggregate_can_record_and_pull(self):
    aggregate = DataclassAggregate()
    event = GroupRenamed(group_id="g1")

    aggregate.record_event(event)

    assert aggregate.pull_events() == [event]

  def test_the_mixin_adds_no_dataclass_field(self):
    """`_pending_events` is set in `record_event`, not declared — so it must not leak into
    `__init__`, `__eq__`, or `repr`, where it would make two equal aggregates compare unequal."""
    first = DataclassAggregate(name="Palawan Trip")
    second = DataclassAggregate(name="Palawan Trip")
    first.record_event(GroupRenamed(group_id="g1"))

    assert first == second
    assert "_pending_events" not in repr(first)
