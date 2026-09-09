"""Turning net balances into payments is a greedy pairing: the largest creditor is matched with
the largest debtor and the smaller of the two amounts moves between them, repeatedly, until both
sides are empty. Because each round settles `min(credit, owed)`, at least one person is cleared
every time — which is what bounds the result at n-1 payments.

The service is a pure function over a zero-sum map of balances, so these tests lean on the
properties that must hold for any input (money is conserved, debtors only ever pay, creditors
only ever receive) as much as on worked examples.
"""

from __future__ import annotations

import random

import pytest

from domain.services.settlement_suggester import SettlementSuggester, SuggestedPayment
from domain.value_objects.ids import UserId
from domain.value_objects.money import Money
from tests.builders import CURRENCY, id_for, money


def suggest(debts: dict[UserId, Money]) -> list[SuggestedPayment]:
  return SettlementSuggester.suggest_payments(debts)


def as_tuples(payments: list[SuggestedPayment]) -> list[tuple[UserId, UserId, int]]:
  """Payments as (payer, payee, cents), which is what the assertions care about."""
  return [(p.from_user, p.to_user, p.amount.amount_cents) for p in payments]


def net_movement(payments: list[SuggestedPayment], user_id: UserId) -> int:
  """What the payments move for one person: received minus paid.

  For a settled-up plan this equals that person's original balance.
  """
  received = sum(p.amount.amount_cents for p in payments if p.to_user == user_id)
  paid = sum(p.amount.amount_cents for p in payments if p.from_user == user_id)
  return received - paid


@pytest.fixture
def erin() -> UserId:
  return id_for(UserId, "erin")


class TestSettlingUp:
  def test_one_debtor_pays_one_creditor(self, alice: UserId, carol: UserId):
    payments = suggest({alice: money(5_000), carol: money(-5_000)})

    assert as_tuples(payments) == [(carol, alice, 5_000)]

  def test_the_only_creditor_collects_from_every_debtor(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    payments = suggest(
      {alice: money(9_000), bob: money(-3_000), carol: money(-3_000), dave: money(-3_000)}
    )

    assert as_tuples(payments) == [
      (bob, alice, 3_000),
      (carol, alice, 3_000),
      (dave, alice, 3_000),
    ]

  def test_the_only_debtor_pays_every_creditor(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    payments = suggest(
      {alice: money(3_000), bob: money(3_000), carol: money(3_000), dave: money(-9_000)}
    )

    assert as_tuples(payments) == [
      (dave, alice, 3_000),
      (dave, bob, 3_000),
      (dave, carol, 3_000),
    ]

  def test_a_single_cent_still_gets_a_payment(self, alice: UserId, carol: UserId):
    payments = suggest({alice: money(1), carol: money(-1)})

    assert as_tuples(payments) == [(carol, alice, 1)]


class TestTheGreedyPairing:
  def test_the_largest_debtor_pays_the_largest_creditor_first(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    """alice is owed most and carol owes most, so they are matched before anyone else."""
    payments = suggest(
      {alice: money(7_000), bob: money(2_000), carol: money(-6_000), dave: money(-3_000)}
    )

    assert as_tuples(payments)[0] == (carol, alice, 6_000)

  def test_a_partly_settled_creditor_returns_to_the_queue_for_the_rest(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    """carol clears only 6000 of alice's 7000, so alice comes back for the last 1000."""
    payments = suggest(
      {alice: money(7_000), bob: money(2_000), carol: money(-6_000), dave: money(-3_000)}
    )

    assert as_tuples(payments) == [
      (carol, alice, 6_000),
      (dave, bob, 2_000),
      (dave, alice, 1_000),
    ]

  def test_a_partly_settled_debtor_returns_to_the_queue_for_the_rest(
    self, alice: UserId, bob: UserId, carol: UserId
  ):
    """carol owes 8000 but alice is only owed 5000, so carol still owes bob afterwards."""
    payments = suggest({alice: money(5_000), bob: money(3_000), carol: money(-8_000)})

    assert as_tuples(payments) == [(carol, alice, 5_000), (carol, bob, 3_000)]

  def test_every_payment_clears_at_least_one_of_the_two_parties(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    """`min(credit, owed)` is what guarantees progress: someone always leaves the heaps.

    Replaying the plan makes it checkable — after each payment, either the payer owes
    nothing more or the payee is owed nothing more.
    """
    debts = {alice: money(7_000), bob: money(2_000), carol: money(-6_000), dave: money(-3_000)}
    outstanding = {uid: amount.amount_cents for uid, amount in debts.items()}

    for payment in suggest(debts):
      outstanding[payment.from_user] += payment.amount.amount_cents
      outstanding[payment.to_user] -= payment.amount.amount_cents

      assert 0 in (outstanding[payment.from_user], outstanding[payment.to_user]), (
        f"neither party was cleared by {payment}"
      )

    assert set(outstanding.values()) == {0}, "everyone should end at zero"


class TestTies:
  def test_equal_amounts_on_both_sides_are_paired_off(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    """Ties must not blow up: `UserId` has no ordering, so the heap relies on the
    insertion counter pushed alongside each entry."""
    payments = suggest(
      {alice: money(5_000), bob: money(5_000), carol: money(-5_000), dave: money(-5_000)}
    )

    assert as_tuples(payments) == [(carol, alice, 5_000), (dave, bob, 5_000)]

  def test_the_same_input_always_gives_the_same_plan(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    debts = {alice: money(5_000), bob: money(5_000), carol: money(-5_000), dave: money(-5_000)}

    assert as_tuples(suggest(debts)) == as_tuples(suggest(debts))


class TestMoneyIsConserved:
  """The plan has to move exactly each person's balance — no more, no less."""

  def test_each_person_nets_exactly_their_balance(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId, erin: UserId
  ):
    debts = {
      alice: money(10_000),
      bob: money(4_500),
      carol: money(-2_500),
      dave: money(-7_000),
      erin: money(-5_000),
    }

    payments = suggest(debts)

    assert {uid: net_movement(payments, uid) for uid in debts} == {
      uid: amount.amount_cents for uid, amount in debts.items()
    }

  def test_the_payments_sum_to_the_total_debt(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    payments = suggest(
      {alice: money(7_000), bob: money(2_000), carol: money(-6_000), dave: money(-3_000)}
    )

    assert sum(p.amount.amount_cents for p in payments) == 9_000

  def test_a_debtor_never_receives_and_a_creditor_never_pays(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    debts = {alice: money(7_000), bob: money(2_000), carol: money(-6_000), dave: money(-3_000)}

    payments = suggest(debts)

    assert all(debts[p.from_user].is_negative() for p in payments)
    assert all(debts[p.to_user].is_positive() for p in payments)

  def test_no_payment_is_zero_or_negative(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    payments = suggest(
      {alice: money(7_000), bob: money(2_000), carol: money(-6_000), dave: money(-3_000)}
    )

    assert all(p.amount.is_positive() for p in payments)


class TestHowManyPayments:
  def test_never_more_than_one_payment_short_of_the_headcount(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId, erin: UserId
  ):
    """Each round removes at least one person, and the last removes two."""
    debts = {
      alice: money(10_000),
      bob: money(4_500),
      carol: money(-2_500),
      dave: money(-7_000),
      erin: money(-5_000),
    }

    assert len(suggest(debts)) <= len(debts) - 1

  def test_a_perfectly_matched_group_needs_only_one_payment_each(
    self, alice: UserId, bob: UserId, carol: UserId, dave: UserId
  ):
    """Two pairs that happen to match exactly settle in two payments, not three."""
    payments = suggest(
      {alice: money(5_000), bob: money(5_000), carol: money(-5_000), dave: money(-5_000)}
    )

    assert len(payments) == 2


class TestZeroBalances:
  def test_nothing_to_settle_produces_no_payments(self):
    assert suggest({}) == []

  def test_a_group_that_is_already_square_produces_no_payments(
    self, alice: UserId, carol: UserId
  ):
    assert suggest({alice: money(0), carol: money(0)}) == []

  def test_people_at_zero_are_left_out_of_the_plan(
    self, alice: UserId, bob: UserId, carol: UserId
  ):
    """bob owes nothing and is owed nothing, so he neither pays nor receives."""
    payments = suggest({alice: money(5_000), bob: money(0), carol: money(-5_000)})

    assert as_tuples(payments) == [(carol, alice, 5_000)]
    assert net_movement(payments, bob) == 0


class TestCurrency:
  def test_the_payments_are_denominated_in_the_currency_of_the_debts(
    self, alice: UserId, carol: UserId
  ):
    payments = suggest({alice: money(5_000, "USD"), carol: money(-5_000, "USD")})

    assert [p.amount.currency for p in payments] == ["USD"]

  def test_the_domain_default_currency_is_used_by_default(self, alice: UserId, carol: UserId):
    payments = suggest({alice: money(5_000), carol: money(-5_000)})

    assert [p.amount.currency for p in payments] == [CURRENCY]

  def test_mixed_currencies_are_refused(self, alice: UserId, carol: UserId):
    """Balances in different currencies cannot be netted, so there is nothing to suggest."""
    with pytest.raises(ValueError, match="must be in the same currency"):
      suggest({alice: money(100, "USD"), carol: money(-100, "PHP")})

  def test_a_zero_balance_in_another_currency_is_ignored(
    self, alice: UserId, carol: UserId, dave: UserId
  ):
    """The currency check skips zero amounts, so a stray zero cannot poison the set."""
    payments = suggest({alice: money(100), carol: money(-100), dave: money(0, "USD")})

    assert as_tuples(payments) == [(carol, alice, 100)]


class TestUnbalancedInput:
  """Balances must sum to zero. `BalanceEngine` guarantees it; the guard proves it."""

  def test_more_credit_than_debt_is_refused(self, alice: UserId, carol: UserId):
    with pytest.raises(ValueError, match=r"credits \(500\) and total debts \(200\)"):
      suggest({alice: money(500), carol: money(-200)})

  def test_more_debt_than_credit_is_refused(self, alice: UserId, carol: UserId):
    with pytest.raises(ValueError, match=r"credits \(200\) and total debts \(500\)"):
      suggest({alice: money(200), carol: money(-500)})

  def test_a_creditor_with_nobody_owing_is_refused(self, alice: UserId):
    """Without the guard this returned an empty plan and silently dropped the credit."""
    with pytest.raises(ValueError, match="do not balance out"):
      suggest({alice: money(100)})

  def test_a_debtor_with_nobody_owed_is_refused(self, carol: UserId):
    with pytest.raises(ValueError, match="do not balance out"):
      suggest({carol: money(-100)})

  def test_the_currency_check_runs_before_the_balance_check(
    self, alice: UserId, carol: UserId
  ):
    """Mixed currencies are reported as such, even though the totals also disagree."""
    with pytest.raises(ValueError, match="must be in the same currency"):
      suggest({alice: money(500, "USD"), carol: money(-200, "PHP")})


class TestAcrossManyShapes:
  """A seeded sweep, because the invariants matter more here than any single example."""

  @staticmethod
  def _zero_sum_debts(rng: random.Random, people: list[UserId]) -> dict[UserId, Money]:
    cents = [rng.randint(-9_000, 9_000) for _ in people]
    cents[-1] = -sum(cents[:-1])
    return {uid: money(c) for uid, c in zip(people, cents) if c != 0}

  def test_the_invariants_hold_for_every_shape(self):
    rng = random.Random(7)
    people = [id_for(UserId, f"person-{i}") for i in range(8)]
    checked = 0

    for _ in range(200):
      debts = self._zero_sum_debts(rng, people[: rng.randint(2, 8)])
      if not debts:
        continue
      checked += 1

      payments = suggest(debts)

      assert all(
        net_movement(payments, uid) == amount.amount_cents for uid, amount in debts.items()
      ), f"money not conserved for {debts}"
      assert all(p.amount.is_positive() for p in payments)
      assert all(debts[p.from_user].is_negative() for p in payments)
      assert all(debts[p.to_user].is_positive() for p in payments)
      assert len(payments) <= len(debts) - 1

    assert checked > 150, "the sweep should exercise a healthy number of shapes"


class TestSuggestedPayment:
  def test_is_immutable(self, alice: UserId, carol: UserId):
    payment = suggest({alice: money(5_000), carol: money(-5_000)})[0]

    with pytest.raises(Exception):
      payment.amount = money(1)

  def test_carries_the_two_parties_and_the_amount(self, alice: UserId, carol: UserId):
    payment = suggest({alice: money(5_000), carol: money(-5_000)})[0]

    assert payment == SuggestedPayment(from_user=carol, to_user=alice, amount=money(5_000))
