from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.settlement import InvalidSettlementError, Settlement
from domain.events.base import DomainEvent
from domain.events.settlement_events import SettlementRecorded, SettlementReversed
from domain.value_objects.ids import SettlementId
from tests.builders import id_for, make_settlement, money


def only_event(settlement: Settlement) -> DomainEvent:
  """The single event the settlement is holding — fails loudly if it recorded more or fewer.

  Every assertion about an event goes through here, so a method that starts emitting a
  second event cannot slip past a test that only looked at the first one.
  """
  events = settlement.pull_events()
  assert len(events) == 1, f"expected exactly one event, got {[type(e).__name__ for e in events]}"
  return events[0]


def evolved(settlement: Settlement) -> Settlement:
  """Rebuilds a settlement from its own state, the way a repository rehydrates a stored row."""
  return Settlement(
    id=settlement.id,
    group_id=settlement.group_id,
    from_user=settlement.from_user,
    to_user=settlement.to_user,
    amount=settlement.amount,
    settled_at=settlement.settled_at,
    reverses=settlement.reverses,
    reversed_at=settlement.reversed_at,
  )


class TestCreation:
  def test_records_the_payment_direction_and_amount(self, alice, bob, group_id):
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    assert (settlement.from_user, settlement.to_user) == (bob, alice)
    assert settlement.amount == money(5_000)
    assert settlement.group_id == group_id

  def test_defaults_to_an_unreversed_original_with_a_timestamp(self, alice, bob):
    settlement = make_settlement(from_user=bob, to_user=alice)

    assert settlement.reverses is None
    assert settlement.reversed_at is None
    assert settlement.settled_at.tzinfo is not None

  def test_rejects_a_user_settling_with_themselves(self, alice):
    with pytest.raises(InvalidSettlementError, match="settle a balance with themselves"):
      make_settlement(from_user=alice, to_user=alice)

  @pytest.mark.parametrize("cents", [0, -100])
  def test_rejects_a_non_positive_amount(self, cents: int, alice, bob):
    with pytest.raises(InvalidSettlementError, match="amount must be positive"):
      make_settlement(from_user=bob, to_user=alice, amount=money(cents))


class TestParticipants:
  def test_involves_both_sides(self, alice, bob):
    settlement = make_settlement(from_user=bob, to_user=alice)

    assert settlement.involves(alice)
    assert settlement.involves(bob)

  def test_does_not_involve_a_bystander(self, alice, bob, carol):
    assert make_settlement(from_user=bob, to_user=alice).involves(carol) is False

  def test_counter_party_flips_the_side(self, alice, bob):
    settlement = make_settlement(from_user=bob, to_user=alice)

    assert settlement.counter_party(bob) == alice
    assert settlement.counter_party(alice) == bob


class TestReversal:
  def test_an_original_is_not_a_reversal(self, alice, bob):
    assert make_settlement(from_user=bob, to_user=alice).is_reversal() is False

  def test_create_reversal_swaps_the_direction_and_keeps_the_amount(self, alice, bob, group_id):
    original = make_settlement(
      id=id_for(SettlementId, "original"), group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    reversal = Settlement.create_reversal(id_for(SettlementId, "reversal"), original)

    assert (reversal.from_user, reversal.to_user) == (alice, bob)
    assert reversal.amount == money(5_000)
    assert reversal.group_id == group_id
    assert reversal.reverses == id_for(SettlementId, "original")
    assert reversal.is_reversal() is True

  def test_mark_reversed_stamps_the_original(self, alice, bob):
    original = make_settlement(from_user=bob, to_user=alice)

    original.mark_reversed()

    assert original.reversed_at is not None

  def test_marking_the_same_settlement_reversed_twice_is_rejected(self, alice, bob):
    original = make_settlement(from_user=bob, to_user=alice)
    original.mark_reversed()

    with pytest.raises(InvalidSettlementError, match="already been reversed"):
      original.mark_reversed()

  def test_an_already_reversed_settlement_cannot_be_reversed_again(self, alice, bob):
    original = make_settlement(
      from_user=bob, to_user=alice, reversed_at=datetime.now(timezone.utc)
    )

    with pytest.raises(InvalidSettlementError, match="already been reversed"):
      Settlement.create_reversal(SettlementId.new(), original)

  def test_a_reversal_cannot_itself_be_reversed(self, alice, bob):
    original = make_settlement(id=id_for(SettlementId, "original"), from_user=bob, to_user=alice)
    reversal = Settlement.create_reversal(id_for(SettlementId, "reversal"), original)

    with pytest.raises(InvalidSettlementError, match="cannot be reversed again"):
      Settlement.create_reversal(id_for(SettlementId, "second-reversal"), reversal)


class TestCreateFactoryEvents:
  def test_recording_a_settlement_records_it(self, alice, bob, group_id):
    settlement = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )

    assert isinstance(only_event(settlement), SettlementRecorded)

  def test_the_recorded_event_carries_the_whole_settlement(self, alice, bob, group_id):
    settlement_id = id_for(SettlementId, "dinner-payback")

    settlement = Settlement.create(
      id=settlement_id,
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )

    event = only_event(settlement)
    assert (event.settlement_id, event.group_id) == (settlement_id, group_id)
    assert (event.from_user, event.to_user, event.amount) == (bob, alice, money(5_000))

  def test_the_recorded_event_keeps_the_direction_of_the_payment(self, alice, bob, group_id):
    """Who paid whom is the whole content of the notification — swapping the two would tell
    the wrong person they had been paid back."""
    settlement = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )

    event = only_event(settlement)
    assert (event.from_user, event.to_user) == (settlement.from_user, settlement.to_user)

  def test_a_settlement_with_oneself_records_nothing(self, alice, group_id):
    """The settlement is never constructed, so there is nothing to publish."""
    with pytest.raises(InvalidSettlementError, match="settle a balance with themselves"):
      Settlement.create(
        id=SettlementId.new(),
        group_id=group_id,
        from_user=alice,
        to_user=alice,
        amount=money(5_000),
      )

  @pytest.mark.parametrize("cents", [0, -100])
  def test_a_non_positive_amount_records_nothing(self, cents: int, alice, bob, group_id):
    with pytest.raises(InvalidSettlementError, match="amount must be positive"):
      Settlement.create(
        id=SettlementId.new(),
        group_id=group_id,
        from_user=bob,
        to_user=alice,
        amount=money(cents),
      )


class TestReversalEvents:
  def test_reversing_records_it_on_the_reversal(self, alice, bob, group_id):
    original = make_settlement(group_id=group_id, from_user=bob, to_user=alice)

    reversal = Settlement.create_reversal(SettlementId.new(), original)

    assert isinstance(only_event(reversal), SettlementReversed)

  def test_the_reversed_event_names_the_original_and_the_reversal(self, alice, bob, group_id):
    """`settlement_id` is the settlement being undone and `reversal_id` is the one undoing
    it. Swapping them would tell subscribers the brand new reversal had been reversed."""
    original = make_settlement(
      id=id_for(SettlementId, "original"), group_id=group_id, from_user=bob, to_user=alice
    )
    reversal_id = id_for(SettlementId, "reversal")

    reversal = Settlement.create_reversal(reversal_id, original)

    event = only_event(reversal)
    assert event.settlement_id == id_for(SettlementId, "original")
    assert event.reversal_id == reversal_id
    assert event.group_id == group_id

  def test_the_original_records_nothing_when_it_is_reversed(self, alice, bob):
    """One business fact, one event. The reversal carries it, so a publisher that pulls from
    both aggregates does not announce the same reversal twice."""
    original = make_settlement(from_user=bob, to_user=alice)

    Settlement.create_reversal(SettlementId.new(), original)

    assert original.pull_events() == []

  def test_mark_reversed_records_nothing(self, alice, bob):
    """Stamping the original is bookkeeping for a fact `create_reversal` already announced."""
    original = make_settlement(from_user=bob, to_user=alice)

    original.mark_reversed()

    assert original.reversed_at is not None
    assert original.pull_events() == []

  def test_the_full_reversal_flow_produces_exactly_one_event(self, alice, bob, group_id):
    """Mirrors `ReverseSettlementUseCase`: build the reversal, then stamp the original."""
    original = make_settlement(group_id=group_id, from_user=bob, to_user=alice)

    reversal = Settlement.create_reversal(SettlementId.new(), original)
    original.mark_reversed()

    assert original.pull_events() == []
    assert [type(event) for event in reversal.pull_events()] == [SettlementReversed]

  def test_reversing_an_already_reversed_settlement_records_nothing(self, alice, bob):
    original = make_settlement(
      from_user=bob, to_user=alice, reversed_at=datetime.now(timezone.utc)
    )

    with pytest.raises(InvalidSettlementError, match="already been reversed"):
      Settlement.create_reversal(SettlementId.new(), original)

    assert original.pull_events() == []

  def test_reversing_a_reversal_records_nothing_extra(self, alice, bob):
    """The guard runs before the second reversal exists, so the first one's event is the
    only thing left to pull."""
    original = make_settlement(id=id_for(SettlementId, "original"), from_user=bob, to_user=alice)
    reversal = Settlement.create_reversal(id_for(SettlementId, "reversal"), original)
    reversal.pull_events()

    with pytest.raises(InvalidSettlementError, match="cannot be reversed again"):
      Settlement.create_reversal(id_for(SettlementId, "second-reversal"), reversal)

    assert reversal.pull_events() == []

  def test_marking_reversed_twice_records_nothing(self, alice, bob):
    original = make_settlement(from_user=bob, to_user=alice)
    original.mark_reversed()

    with pytest.raises(InvalidSettlementError, match="already been reversed"):
      original.mark_reversed()

    assert original.pull_events() == []


class TestEventBookkeeping:
  def test_a_settlement_that_has_done_nothing_holds_no_events(self, alice, bob):
    assert make_settlement(from_user=bob, to_user=alice).pull_events() == []

  def test_pulling_clears_what_was_pulled(self, alice, bob, group_id):
    """Whoever pulls is responsible for publishing; leaving the events behind means the
    next pull publishes them a second time."""
    settlement = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )

    settlement.pull_events()

    assert settlement.pull_events() == []

  def test_two_settlements_do_not_share_events(self, alice, bob, group_id):
    """`_pending_events` is created lazily per instance — a list shared across settlements
    would publish one payment under another settlement's id."""
    first = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )
    second = make_settlement(from_user=bob, to_user=alice)

    assert len(first.pull_events()) == 1
    assert second.pull_events() == []

  def test_a_reversal_does_not_inherit_the_originals_pending_events(self, alice, bob, group_id):
    """The original may still be holding its own `SettlementRecorded` when it is reversed."""
    original = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )

    reversal = Settlement.create_reversal(SettlementId.new(), original)

    assert [type(event) for event in original.pull_events()] == [SettlementRecorded]
    assert [type(event) for event in reversal.pull_events()] == [SettlementReversed]


class TestReconstruction:
  """`__post_init__` runs on every construction, including when a repository rebuilds a
  stored settlement, so the events must not be re-emitted by a round trip."""

  def test_rebuilding_a_settlement_records_nothing(self, alice, bob, group_id):
    """Only the factories announce anything. The constructor is also how a repository
    rehydrates a stored settlement, so recording there would re-announce every payment the
    moment it was read back."""
    settlement = make_settlement(group_id=group_id, from_user=bob, to_user=alice)

    assert evolved(settlement).pull_events() == []

  def test_rebuilding_a_reversal_records_nothing(self, alice, bob, group_id):
    original = make_settlement(group_id=group_id, from_user=bob, to_user=alice)
    reversal = Settlement.create_reversal(SettlementId.new(), original)

    rebuilt = evolved(reversal)

    assert rebuilt.is_reversal() is True
    assert rebuilt.pull_events() == []

  def test_events_do_not_travel_with_the_state_into_a_rebuild(self, alice, bob, group_id):
    """The events belong to the instance that recorded them, not to the stored state."""
    settlement = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=bob,
      to_user=alice,
      amount=money(5_000),
    )

    rebuilt = evolved(settlement)

    assert rebuilt.pull_events() == []
    assert len(settlement.pull_events()) == 1

  def test_a_rebuilt_settlement_still_records_what_happens_next(self, alice, bob, group_id):
    """Rehydrating must leave the bookkeeping usable, not just empty."""
    original = make_settlement(group_id=group_id, from_user=bob, to_user=alice)

    rebuilt = evolved(original)
    reversal = Settlement.create_reversal(SettlementId.new(), rebuilt)

    assert isinstance(only_event(reversal), SettlementReversed)
