from __future__ import annotations

import pytest

from domain.value_objects.ids import UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import (
  EqualSplitStrategy,
  ExactSplitStrategy,
  InvalidSplitStrategyError,
  PercentageSplitStrategy,
  SplitLine,
  SplitStrategy,
  SplitType,
)
from tests.builders import money


def owed_cents(lines: list[SplitLine]) -> dict[UserId, int]:
  return {line.user_id: line.owed.amount_cents for line in lines}


class TestSplitType:
  @pytest.mark.parametrize(
    ("raw", "expected"),
    [("equal", SplitType.EQUAL), ("exact", SplitType.EXACT), ("percentage", SplitType.PERCENTAGE)],
  )
  def test_parses_from_its_wire_value(self, raw: str, expected: SplitType):
    assert SplitType(raw) is expected

  def test_unknown_value_is_rejected(self):
    with pytest.raises(ValueError):
      SplitType("weighted")

  def test_str_is_the_wire_value(self):
    assert str(SplitType.EQUAL) == "equal"

  def test_is_a_str_so_it_serializes_transparently(self):
    assert SplitType.EXACT == "exact"


class TestSplitLine:
  def test_compares_by_value(self, alice: UserId):
    assert SplitLine(alice, money(100)) == SplitLine(alice, money(100))

  def test_is_frozen(self, alice: UserId):
    with pytest.raises(Exception):
      SplitLine(alice, money(100)).owed = money(200)


class TestExactSplitStrategy:
  def test_hands_each_participant_their_stated_amount(self, alice, bob):
    strategy = ExactSplitStrategy({alice: money(7_000), bob: money(3_000)})

    lines = strategy.split(money(10_000), [alice, bob])

    assert owed_cents(lines) == {alice: 7_000, bob: 3_000}

  def test_keeps_the_participant_order(self, alice, bob, carol):
    amounts = {alice: money(100), bob: money(100), carol: money(100)}
    strategy = ExactSplitStrategy(amounts)

    lines = strategy.split(money(300), [carol, alice, bob])

    assert [line.user_id for line in lines] == [carol, alice, bob]

  def test_a_single_participant_owes_everything(self, alice):
    lines = ExactSplitStrategy({alice: money(10_000)}).split(money(10_000), [alice])

    assert owed_cents(lines) == {alice: 10_000}

  def test_rejects_a_participant_with_no_stated_amount(self, alice, bob, carol):
    strategy = ExactSplitStrategy({alice: money(5_000), bob: money(5_000)})

    with pytest.raises(InvalidSplitStrategyError, match="Participants do not match"):
      strategy.split(money(10_000), [alice, bob, carol])

  def test_rejects_an_amount_for_a_non_participant(self, alice, bob, carol):
    strategy = ExactSplitStrategy({alice: money(5_000), bob: money(4_000), carol: money(1_000)})

    with pytest.raises(InvalidSplitStrategyError, match="Participants do not match"):
      strategy.split(money(10_000), [alice, bob])

  @pytest.mark.parametrize("total_cents", [9_999, 10_001])
  def test_rejects_amounts_that_do_not_add_up_to_the_total(self, alice, bob, total_cents: int):
    strategy = ExactSplitStrategy({alice: money(5_000), bob: money(5_000)})

    with pytest.raises(InvalidSplitStrategyError, match="does not match the specified total"):
      strategy.split(money(total_cents), [alice, bob])


class TestPercentageSplitStrategy:
  def test_applies_each_percentage_to_the_total(self, alice, bob):
    strategy = PercentageSplitStrategy({alice: 70.0, bob: 30.0})

    lines = strategy.split(money(10_000), [alice, bob])

    assert owed_cents(lines) == {alice: 7_000, bob: 3_000}

  def test_carries_the_totals_currency(self, alice):
    lines = PercentageSplitStrategy({alice: 100.0}).split(Money(500, "USD"), [alice])

    assert lines[0].owed == Money(500, "USD")

  def test_indivisible_totals_still_add_up_to_the_total(self, alice, bob, carol):
    """100 cents three ways: the largest-remainder pass must not lose or invent a cent."""
    strategy = PercentageSplitStrategy({alice: 33.34, bob: 33.33, carol: 33.33})

    lines = strategy.split(money(100), [alice, bob, carol])

    assert sum(line.owed.amount_cents for line in lines) == 100
    assert owed_cents(lines) == {alice: 34, bob: 33, carol: 33}

  def test_spare_cents_go_to_the_largest_remainders(self, alice, bob, carol):
    lines = PercentageSplitStrategy({alice: 50.0, bob: 25.0, carol: 25.0}).split(
      money(101), [alice, bob, carol]
    )

    assert sum(line.owed.amount_cents for line in lines) == 101
    assert owed_cents(lines)[alice] == 51

  def test_a_zero_percent_participant_owes_nothing(self, alice, bob):
    lines = PercentageSplitStrategy({alice: 100.0, bob: 0.0}).split(money(10_000), [alice, bob])

    assert owed_cents(lines) == {alice: 10_000, bob: 0}

  @pytest.mark.parametrize(
    "percentages",
    [{"alice": 60.0, "bob": 60.0}, {"alice": 10.0, "bob": 10.0}, {"alice": 99.9, "bob": 0.0}],
    ids=["over-100", "under-100", "just-short"],
  )
  def test_rejects_percentages_that_do_not_sum_to_100(self, percentages: dict[str, float]):
    with pytest.raises(InvalidSplitStrategyError, match="must sum to 100"):
      PercentageSplitStrategy({UserId(uid): pct for uid, pct in percentages.items()})

  @pytest.mark.parametrize("bad_pct", [-1.0, 101.0])
  def test_rejects_percentages_outside_0_to_100(self, alice, bob, bad_pct: float):
    with pytest.raises(InvalidSplitStrategyError, match="between 0 and 100"):
      PercentageSplitStrategy({alice: bad_pct, bob: 100.0 - bad_pct})

  def test_rejects_participants_that_do_not_match_the_percentages(self, alice, bob, carol):
    strategy = PercentageSplitStrategy({alice: 50.0, bob: 50.0})

    with pytest.raises(InvalidSplitStrategyError, match="Participants do not match"):
      strategy.split(money(10_000), [alice, carol])


class TestLargestRemainderDistribution:
  """The invariant every strategy leans on: cents in equals cents out."""

  @pytest.mark.parametrize("total_cents", [0, 1, 2, 7, 99, 100, 101, 1_000_003])
  @pytest.mark.parametrize("participant_count", [1, 2, 3, 7])
  def test_distributes_exactly_the_total(self, total_cents: int, participant_count: int):
    participants = [UserId(f"u{i}") for i in range(participant_count)]
    raw = {uid: total_cents / participant_count for uid in participants}

    distributed = SplitStrategy._largest_remainder_distribute(total_cents, raw, participants)

    assert sum(distributed.values()) == total_cents
    assert set(distributed) == set(participants)


class TestEqualSplitStrategy:
  """Constructed with no arguments: the builder only wires the strategy up, and the use
  case calls `split` once it knows the total and the participants."""

  def test_divides_the_total_between_the_participants(self, alice, bob):
    strategy = EqualSplitStrategy()

    lines = strategy.split(money(10_000), [alice, bob])

    assert owed_cents(lines) == {alice: 5_000, bob: 5_000}

  def test_a_single_participant_owes_everything(self, alice):
    lines = EqualSplitStrategy().split(money(10_000), [alice])

    assert owed_cents(lines) == {alice: 10_000}

  def test_indivisible_totals_still_add_up_to_the_total(self, alice, bob, carol):
    lines = EqualSplitStrategy().split(money(100), [alice, bob, carol])

    assert sum(line.owed.amount_cents for line in lines) == 100

  def test_shares_of_an_indivisible_total_differ_by_at_most_a_cent(self, alice, bob, carol):
    lines = EqualSplitStrategy().split(money(100), [alice, bob, carol])

    shares = [line.owed.amount_cents for line in lines]
    assert max(shares) - min(shares) <= 1

  def test_keeps_the_participant_order(self, alice, bob, carol):
    lines = EqualSplitStrategy().split(money(300), [carol, alice, bob])

    assert [line.user_id for line in lines] == [carol, alice, bob]

  def test_carries_the_totals_currency(self, alice, bob):
    lines = EqualSplitStrategy().split(Money(500, "USD"), [alice, bob])

    assert all(line.owed.currency == "USD" for line in lines)

  def test_one_instance_can_split_more_than_one_expense(self, alice, bob):
    """The builder hands the use case a single strategy; it holds no per-expense state."""
    strategy = EqualSplitStrategy()

    first = strategy.split(money(10_000), [alice, bob])
    second = strategy.split(money(6_000), [alice, bob])

    assert owed_cents(first) == {alice: 5_000, bob: 5_000}
    assert owed_cents(second) == {alice: 3_000, bob: 3_000}
