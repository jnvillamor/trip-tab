from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.settlement import InvalidSettlementError, Settlement
from domain.value_objects.ids import SettlementId
from tests.builders import id_for, make_settlement, money


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
