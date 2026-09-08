from __future__ import annotations

import pytest

from domain.entities.expense import Expense, InvalidExpenseError
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import (
  ExactSplitStrategy,
  InvalidSplitStrategyError,
  SplitLine,
)
from tests.builders import id_for, make_expense, money


def owed_cents(expense: Expense) -> dict[UserId, int]:
  return {line.user_id: line.owed.amount_cents for line in expense.splits}


class TestCreation:
  def test_records_the_payer_the_total_and_the_splits(self, alice, bob, group_id: GroupId):
    expense = make_expense(
      group_id=group_id,
      description="Dinner",
      total=money(10_000),
      paid_by=alice,
      participants=[alice, bob],
    )

    assert expense.group_id == group_id
    assert expense.paid_by == alice
    assert expense.total == money(10_000)
    assert owed_cents(expense) == {alice: 5_000, bob: 5_000}

  def test_defaults_to_not_deleted_with_a_timezone_aware_timestamp(self, alice):
    expense = make_expense(paid_by=alice)

    assert expense.deleted is False
    assert expense.created_at.tzinfo is not None

  @pytest.mark.parametrize("blank", ["", "   "])
  def test_rejects_a_blank_description(self, blank: str, alice):
    with pytest.raises(InvalidExpenseError, match="description cannot be empty"):
      make_expense(description=blank, paid_by=alice)

  @pytest.mark.parametrize("cents", [0, -100])
  def test_rejects_a_non_positive_total(self, cents: int, alice):
    with pytest.raises(InvalidExpenseError, match="total must be positive"):
      make_expense(total=money(cents), paid_by=alice, splits=[SplitLine(alice, money(cents))])

  def test_rejects_splits_that_do_not_add_up_to_the_total(self, alice, bob):
    with pytest.raises(InvalidExpenseError, match="does not match total"):
      make_expense(
        total=money(10_000),
        paid_by=alice,
        splits=[SplitLine(alice, money(5_000)), SplitLine(bob, money(4_999))],
      )

  def test_rejects_splits_denominated_in_another_currency(self, alice):
    with pytest.raises(Exception):
      make_expense(
        total=Money(10_000, "PHP"),
        paid_by=alice,
        splits=[SplitLine(alice, Money(10_000, "USD"))],
      )

  def test_the_payer_may_also_be_a_participant(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    assert expense.owed_by(alice) == money(5_000)


class TestCreateFactory:
  def test_delegates_the_split_to_the_strategy(self, alice, bob, group_id: GroupId):
    strategy = ExactSplitStrategy({alice: money(6_000), bob: money(4_000)})

    expense = Expense.create(
      id=id_for(ExpenseId, "boat-rental"),
      group_id=group_id,
      description="Boat rental",
      total=money(10_000),
      paid_by=alice,
      split_strategy=strategy,
      participants=[alice, bob],
    )

    assert owed_cents(expense) == {alice: 6_000, bob: 4_000}
    assert expense.id == id_for(ExpenseId, "boat-rental")
    assert expense.deleted is False

  def test_a_strategy_that_does_not_balance_is_rejected(self, alice, bob, group_id: GroupId):
    strategy = ExactSplitStrategy({alice: money(6_000), bob: money(3_000)})

    with pytest.raises(InvalidSplitStrategyError, match="does not match the specified total"):
      Expense.create(
        id=ExpenseId.new(),
        group_id=group_id,
        description="Boat rental",
        total=money(10_000),
        paid_by=alice,
        split_strategy=strategy,
        participants=[alice, bob],
      )


class TestEdit:
  def test_changing_only_the_description_leaves_the_splits_alone(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
    original_splits = list(expense.splits)

    expense.edit(description="Late dinner")

    assert expense.description == "Late dinner"
    assert expense.splits == original_splits

  def test_changing_the_total_recomputes_the_splits(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit(
      total=money(20_000),
      strategy=ExactSplitStrategy({alice: money(12_000), bob: money(8_000)}),
    )

    assert expense.total == money(20_000)
    assert owed_cents(expense) == {alice: 12_000, bob: 8_000}

  def test_changing_the_participants_recomputes_the_splits(self, alice, bob, carol):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(9_000))

    expense.edit(
      participants=[alice, bob, carol],
      strategy=ExactSplitStrategy(
        {alice: money(3_000), bob: money(3_000), carol: money(3_000)}
      ),
    )

    assert owed_cents(expense) == {alice: 3_000, bob: 3_000, carol: 3_000}

  def test_changing_the_total_without_a_strategy_is_rejected(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    with pytest.raises(InvalidExpenseError, match="strategy must be provided"):
      expense.edit(total=money(20_000))

  def test_changing_the_participants_without_a_strategy_is_rejected(self, alice, bob, carol):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    with pytest.raises(InvalidExpenseError, match="strategy must be provided"):
      expense.edit(participants=[alice, bob, carol])

  def test_a_strategy_that_does_not_balance_is_rejected(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    with pytest.raises(InvalidSplitStrategyError):
      expense.edit(
        total=money(20_000),
        strategy=ExactSplitStrategy({alice: money(1_000), bob: money(1_000)}),
      )

  def test_a_no_op_edit_leaves_the_expense_untouched(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit()

    assert expense.description == "Dinner"
    assert owed_cents(expense) == {alice: 5_000, bob: 5_000}


class TestDeletion:
  def test_mark_deleted_flags_the_expense_without_dropping_it(self, alice):
    expense = make_expense(paid_by=alice)

    expense.mark_deleted()

    assert expense.deleted is True
    assert expense.splits

  def test_marking_twice_is_idempotent(self, alice):
    expense = make_expense(paid_by=alice)

    expense.mark_deleted()
    expense.mark_deleted()

    assert expense.deleted is True


class TestOwedBy:
  def test_returns_the_participants_share(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    assert expense.owed_by(bob) == money(5_000)

  def test_a_non_participant_owes_zero_in_the_expense_currency(self, alice, bob, carol):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=Money(10_000, "USD"))

    assert expense.owed_by(carol) == Money(0, "USD")
