from __future__ import annotations

import pytest

from domain.services.balance_engine import BalanceEngine
from domain.value_objects.money import CurrencyMismatchError, Money
from tests.builders import make_expense, make_settlement, money

class TestNetBalance:
  def test_the_payer_is_owed_what_the_others_consumed(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob]
    )

    balances = BalanceEngine.compute_net_balance([expense], [])

    assert balances == {alice: money(5_000), bob: money(-5_000)}

  def test_net_balances_always_add_up_to_zero(self, alice, bob, carol, group_id):
    expenses = [
      make_expense(group_id=group_id, total=money(9_000), paid_by=alice,
                   participants=[alice, bob, carol]),
      make_expense(group_id=group_id, total=money(3_000), paid_by=bob,
                   participants=[bob, carol]),
    ]

    balances = BalanceEngine.compute_net_balance(expenses, [])

    assert sum(amount.amount_cents for amount in balances.values()) == 0

  def test_a_settled_up_group_reports_no_balances(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob]
    )
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    assert BalanceEngine.compute_net_balance([expense], [settlement]) == {}

  def test_settlements_apply_even_when_the_group_has_no_expenses(self, alice, bob, group_id):
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    balances = BalanceEngine.compute_net_balance([], [settlement])

    assert balances == {bob: money(5_000), alice: money(-5_000)}

  def test_a_settlement_counts_once_however_many_expenses_there_are(self, alice, bob, group_id):
    expenses = [
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice,
                   participants=[alice, bob]),
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice,
                   participants=[alice, bob]),
    ]
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    balances = BalanceEngine.compute_net_balance(expenses, [settlement])

    # Bob consumed 5,000 of each expense and has paid 5,000 of it back.
    assert balances == {alice: money(5_000), bob: money(-5_000)}

  def test_deleted_expenses_are_ignored(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice,
      participants=[alice, bob], deleted=True,
    )

    assert BalanceEngine.compute_net_balance([expense], []) == {}

  def test_an_expense_the_payer_covered_alone_leaves_everyone_square(self, alice, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice]
    )

    assert BalanceEngine.compute_net_balance([expense], []) == {}

  def test_empty_input_produces_no_balances(self):
    assert BalanceEngine.compute_net_balance([], []) == {}

  def test_mixing_currencies_is_rejected(self, alice, bob, group_id):
    expenses = [
      make_expense(group_id=group_id, total=Money(10_000, "PHP"), paid_by=alice,
                   participants=[alice, bob]),
      make_expense(group_id=group_id, total=Money(10_000, "USD"), paid_by=alice,
                   participants=[alice, bob]),
    ]

    with pytest.raises(CurrencyMismatchError, match="mixed currencies"):
      BalanceEngine.compute_net_balance(expenses, [])


class TestPairwiseBalance:
  def test_a_participant_owes_the_payer_their_share(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob]
    )

    pairwise = BalanceEngine.compute_pairwise_balance([expense], [])

    assert pairwise == {(bob, alice): money(5_000)}

  def test_each_debtor_is_tracked_separately(self, alice, bob, carol, group_id):
    expense = make_expense(
      group_id=group_id, total=money(9_000), paid_by=alice, participants=[alice, bob, carol]
    )

    pairwise = BalanceEngine.compute_pairwise_balance([expense], [])

    assert pairwise == {(bob, alice): money(3_000), (carol, alice): money(3_000)}

  def test_debts_in_both_directions_are_netted_into_one_entry(self, alice, bob, group_id):
    expenses = [
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice,
                   participants=[alice, bob]),
      make_expense(group_id=group_id, total=money(4_000), paid_by=bob,
                   participants=[alice, bob]),
    ]

    pairwise = BalanceEngine.compute_pairwise_balance(expenses, [])

    assert pairwise == {(bob, alice): money(3_000)}

  def test_a_pair_that_cancels_out_is_omitted(self, alice, bob, group_id):
    expenses = [
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice,
                   participants=[alice, bob]),
      make_expense(group_id=group_id, total=money(10_000), paid_by=bob,
                   participants=[alice, bob]),
    ]

    assert BalanceEngine.compute_pairwise_balance(expenses, []) == {}

  def test_deleted_expenses_are_ignored(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice,
      participants=[alice, bob], deleted=True,
    )

    assert BalanceEngine.compute_pairwise_balance([expense], []) == {}

  def test_an_expense_the_payer_covered_alone_produces_no_debt(self, alice, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice]
    )

    assert BalanceEngine.compute_pairwise_balance([expense], []) == {}

  def test_empty_input_produces_no_balances(self):
    assert BalanceEngine.compute_pairwise_balance([], []) == {}

  def test_mixing_currencies_is_rejected(self, alice, bob, group_id):
    expenses = [
      make_expense(group_id=group_id, total=Money(10_000, "PHP"), paid_by=alice,
                   participants=[alice, bob]),
      make_expense(group_id=group_id, total=Money(10_000, "USD"), paid_by=alice,
                   participants=[alice, bob]),
    ]

    with pytest.raises(CurrencyMismatchError, match="mixed currencies"):
      BalanceEngine.compute_pairwise_balance(expenses, [])

  def test_a_settlement_clears_the_debt_it_pays_off(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob]
    )
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    assert BalanceEngine.compute_pairwise_balance([expense], [settlement]) == {}

  def test_a_partial_settlement_reduces_the_debt(self, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob]
    )
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(2_000)
    )

    pairwise = BalanceEngine.compute_pairwise_balance([expense], [settlement])

    assert pairwise == {(bob, alice): money(3_000)}

  def test_a_settlement_counts_once_however_many_expenses_there_are(self, alice, bob, group_id):
    expenses = [
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice,
                   participants=[alice, bob]),
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice,
                   participants=[alice, bob]),
    ]
    settlement = make_settlement(
      group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000)
    )

    pairwise = BalanceEngine.compute_pairwise_balance(expenses, [settlement])

    assert pairwise == {(bob, alice): money(5_000)}
