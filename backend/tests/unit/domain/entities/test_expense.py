from __future__ import annotations

import pytest

from domain.entities.expense import Expense, InvalidExpenseError
from domain.events.base import DomainEvent
from domain.events.expense_events import ExpenseCreated, ExpenseDeleted, ExpenseEdited
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


def only_event(expense: Expense) -> DomainEvent:
  """The single event the expense is holding — fails loudly if it recorded more or fewer.

  Every assertion about an event goes through here, so a method that starts emitting a
  second event cannot slip past a test that only looked at the first one.
  """
  events = expense.pull_events()
  assert len(events) == 1, f"expected exactly one event, got {[type(e).__name__ for e in events]}"
  return events[0]


def evolved(expense: Expense) -> Expense:
  """Rebuilds an expense from its own state, the way a repository rehydrates a stored row."""
  return Expense(
    id=expense.id,
    group_id=expense.group_id,
    description=expense.description,
    total=expense.total,
    paid_by=expense.paid_by,
    splits=list(expense.splits),
    created_at=expense.created_at,
    deleted=expense.deleted,
  )


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

  def test_stores_the_description_trimmed(self, alice):
    """Read models report the stored value verbatim, so the padding is removed on the way in."""
    assert make_expense(description="  Dinner  ", paid_by=alice).description == "Dinner"

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

  def test_an_edit_rejected_for_a_missing_strategy_changes_nothing(self, alice, bob):
    """The edit is computed into locals before anything is written, so a description
    supplied alongside a rejected total change is discarded with it."""
    expense = make_expense(
      paid_by=alice, participants=[alice, bob], total=money(10_000), description="Dinner"
    )

    with pytest.raises(InvalidExpenseError, match="strategy must be provided"):
      expense.edit(description="Late dinner", total=money(20_000))

    assert expense.description == "Dinner"
    assert expense.total == money(10_000)
    assert owed_cents(expense) == {alice: 5_000, bob: 5_000}

  def test_an_edit_rejected_by_the_strategy_changes_nothing(self, alice, bob):
    """The strategy runs against a candidate total, so a strategy that raises cannot leave
    the new total behind on an expense whose splits still add up to the old one."""
    expense = make_expense(
      paid_by=alice, participants=[alice, bob], total=money(10_000), description="Dinner"
    )

    with pytest.raises(InvalidSplitStrategyError):
      expense.edit(
        description="Late dinner",
        total=money(20_000),
        strategy=ExactSplitStrategy({alice: money(1_000), bob: money(1_000)}),
      )

    assert expense.description == "Dinner"
    assert expense.total == money(10_000)
    assert owed_cents(expense) == {alice: 5_000, bob: 5_000}

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


class TestCreateFactoryEvents:
  def test_creating_records_it(self, alice, bob, group_id: GroupId):
    expense = Expense.create(
      id=ExpenseId.new(),
      group_id=group_id,
      description="Boat rental",
      total=money(10_000),
      paid_by=alice,
      split_strategy=ExactSplitStrategy({alice: money(6_000), bob: money(4_000)}),
      participants=[alice, bob],
    )

    assert isinstance(only_event(expense), ExpenseCreated)

  def test_the_created_event_carries_the_whole_expense(self, alice, bob, group_id: GroupId):
    expense_id = id_for(ExpenseId, "boat-rental")

    expense = Expense.create(
      id=expense_id,
      group_id=group_id,
      description="Boat rental",
      total=money(10_000),
      paid_by=alice,
      split_strategy=ExactSplitStrategy({alice: money(6_000), bob: money(4_000)}),
      participants=[alice, bob],
    )

    event = only_event(expense)
    assert (event.group_id, event.expense_id) == (group_id, expense_id)
    assert (event.created_by, event.amount, event.description) == (
      alice, money(10_000), "Boat rental",
    )

  def test_the_created_event_credits_the_payer(self, alice, bob, group_id: GroupId):
    """`created_by` is taken from `paid_by` — the two are the same person today, and a
    notification saying the wrong member added the expense is worse than none."""
    expense = Expense.create(
      id=ExpenseId.new(),
      group_id=group_id,
      description="Boat rental",
      total=money(10_000),
      paid_by=bob,
      split_strategy=ExactSplitStrategy({alice: money(6_000), bob: money(4_000)}),
      participants=[alice, bob],
    )

    assert only_event(expense).created_by == bob

  def test_the_created_event_carries_the_trimmed_description(self, alice, group_id: GroupId):
    """Subscribers build their view from the event, not the entity — a description trimmed
    on the way in but published raw makes the two disagree about the same expense."""
    expense = Expense.create(
      id=ExpenseId.new(),
      group_id=group_id,
      description="  Boat rental  ",
      total=money(10_000),
      paid_by=alice,
      split_strategy=ExactSplitStrategy({alice: money(10_000)}),
      participants=[alice],
    )

    assert only_event(expense).description == expense.description

  def test_a_strategy_that_does_not_balance_records_nothing(self, alice, bob, group_id: GroupId):
    """The strategy runs before the expense exists, so there is nothing to publish."""
    with pytest.raises(InvalidSplitStrategyError):
      Expense.create(
        id=ExpenseId.new(),
        group_id=group_id,
        description="Boat rental",
        total=money(10_000),
        paid_by=alice,
        split_strategy=ExactSplitStrategy({alice: money(6_000), bob: money(3_000)}),
        participants=[alice, bob],
      )

  def test_a_blank_description_records_nothing(self, alice, group_id: GroupId):
    with pytest.raises(InvalidExpenseError):
      Expense.create(
        id=ExpenseId.new(),
        group_id=group_id,
        description="   ",
        total=money(10_000),
        paid_by=alice,
        split_strategy=ExactSplitStrategy({alice: money(10_000)}),
        participants=[alice],
      )


class TestEditEvents:
  def test_editing_the_description_records_it(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit(description="Late dinner")

    event = only_event(expense)
    assert isinstance(event, ExpenseEdited)
    assert (event.group_id, event.expense_id) == (expense.group_id, expense.id)

  def test_the_edited_event_carries_the_state_after_the_edit(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit(
      description="Late dinner",
      total=money(20_000),
      strategy=ExactSplitStrategy({alice: money(12_000), bob: money(8_000)}),
    )

    event = only_event(expense)
    assert (event.new_amount, event.new_description) == (money(20_000), "Late dinner")

  def test_the_edited_event_repeats_the_unchanged_amount(self, alice, bob):
    """A description-only edit still publishes the amount, so a subscriber never has to
    guess whether an absent field means unchanged or zero."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit(description="Late dinner")

    assert only_event(expense).new_amount == money(10_000)

  def test_the_edited_event_carries_the_trimmed_description(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit(description="  Late dinner  ")

    assert only_event(expense).new_description == expense.description

  def test_an_edit_rejected_for_a_missing_strategy_records_nothing(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    with pytest.raises(InvalidExpenseError):
      expense.edit(total=money(20_000))

    assert expense.pull_events() == []

  def test_an_edit_rejected_by_the_strategy_records_nothing(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    with pytest.raises(InvalidSplitStrategyError):
      expense.edit(
        total=money(20_000),
        strategy=ExactSplitStrategy({alice: money(1_000), bob: money(1_000)}),
      )

    assert expense.pull_events() == []

  def test_each_edit_records_its_own_event(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit(description="Late dinner")
    expense.edit(description="Very late dinner")

    events = expense.pull_events()
    assert [type(event) for event in events] == [ExpenseEdited, ExpenseEdited]
    assert [event.new_description for event in events] == ["Late dinner", "Very late dinner"]

  def test_a_no_op_edit_records_nothing(self, alice, bob):
    """`edit()` with no arguments changes nothing, so there is nothing to announce — a
    subscriber must never tell the group an expense changed when it did not."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    expense.edit()

    assert expense.pull_events() == []

  def test_an_edit_that_sets_the_same_values_records_nothing(self, alice, bob):
    """The check is on the resulting state, not on which arguments were passed: re-sending
    the values an expense already holds is still a no-op."""
    expense = make_expense(
      paid_by=alice, participants=[alice, bob], total=money(10_000), description="Dinner"
    )

    expense.edit(
      description="Dinner",
      total=money(10_000),
      strategy=ExactSplitStrategy({alice: money(5_000), bob: money(5_000)}),
    )

    assert expense.pull_events() == []

  def test_an_edit_that_changes_only_the_splits_still_records(self, alice, bob):
    """Same total and description, different shares — the people who owe money changed,
    which is exactly what a subscriber needs to hear about."""
    expense = make_expense(
      paid_by=alice, participants=[alice, bob], total=money(10_000), description="Dinner"
    )

    expense.edit(
      total=money(10_000),
      strategy=ExactSplitStrategy({alice: money(7_000), bob: money(3_000)}),
    )

    assert isinstance(only_event(expense), ExpenseEdited)
    assert owed_cents(expense) == {alice: 7_000, bob: 3_000}


class TestDeletionEvents:
  def test_deleting_records_it(self, alice, group_id: GroupId):
    expense = make_expense(group_id=group_id, paid_by=alice)

    expense.mark_deleted()

    event = only_event(expense)
    assert isinstance(event, ExpenseDeleted)
    assert (event.group_id, event.expense_id) == (group_id, expense.id)

  def test_deleting_twice_records_one_event(self, alice):
    """The flag and the event stream are both idempotent, so a retried delete cannot push a
    second "expense removed" notification for the same expense."""
    expense = make_expense(paid_by=alice)

    expense.mark_deleted()
    expense.mark_deleted()

    assert expense.deleted is True
    assert [type(event) for event in expense.pull_events()] == [ExpenseDeleted]

  def test_deleting_an_already_deleted_expense_records_nothing(self, alice):
    """A repository rehydrates a deleted expense with `deleted=True`; deleting it again
    must stay silent rather than re-announcing a removal that already happened."""
    expense = make_expense(paid_by=alice, deleted=True)

    expense.mark_deleted()

    assert expense.pull_events() == []

  def test_a_deleted_expense_can_still_record_an_edit(self, alice, bob):
    """Nothing guards `edit` against a deleted expense, so the events keep flowing."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
    expense.mark_deleted()
    expense.pull_events()

    expense.edit(description="Late dinner")

    assert isinstance(only_event(expense), ExpenseEdited)


class TestEventBookkeeping:
  def test_an_expense_that_has_done_nothing_holds_no_events(self, alice):
    assert make_expense(paid_by=alice).pull_events() == []

  def test_events_come_back_in_the_order_they_happened(self, alice, bob, group_id: GroupId):
    expense = Expense.create(
      id=ExpenseId.new(),
      group_id=group_id,
      description="Boat rental",
      total=money(10_000),
      paid_by=alice,
      split_strategy=ExactSplitStrategy({alice: money(6_000), bob: money(4_000)}),
      participants=[alice, bob],
    )

    expense.edit(description="Boat rental (half day)")
    expense.mark_deleted()

    assert [type(event) for event in expense.pull_events()] == [
      ExpenseCreated, ExpenseEdited, ExpenseDeleted
    ]

  def test_pulling_clears_what_was_pulled(self, alice, bob):
    """Whoever pulls is responsible for publishing; leaving the events behind means the
    next pull publishes them a second time."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
    expense.edit(description="Late dinner")

    expense.pull_events()

    assert expense.pull_events() == []

  def test_only_the_events_since_the_last_pull_come_back(self, alice, bob):
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
    expense.edit(description="Late dinner")
    expense.pull_events()

    expense.mark_deleted()

    assert [type(event) for event in expense.pull_events()] == [ExpenseDeleted]

  def test_two_expenses_do_not_share_events(self, alice, bob):
    """`_pending_events` is created lazily per instance — a list shared across expenses
    would publish one expense's edit under another expense's id."""
    first = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
    second = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    first.edit(description="Late dinner")

    assert len(first.pull_events()) == 1
    assert second.pull_events() == []


class TestReconstruction:
  """`__post_init__` runs on every construction, including when a repository rebuilds a
  stored expense, so the events must not be re-emitted by a round trip."""

  def test_rebuilding_an_expense_records_nothing(self, alice, bob):
    """Only `Expense.create` announces a new expense. The constructor is also how a
    repository rehydrates a stored one, so recording there would re-announce every expense
    the moment it was read back."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    assert evolved(expense).pull_events() == []

  def test_a_rebuilt_expense_still_records_what_happens_next(self, alice, bob):
    """Rehydrating must leave the bookkeeping usable, not just empty."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))

    rebuilt = evolved(expense)
    rebuilt.edit(description="Late dinner")

    assert isinstance(only_event(rebuilt), ExpenseEdited)

  def test_events_do_not_travel_with_the_state_into_a_rebuild(self, alice, bob):
    """The events belong to the instance that recorded them, not to the stored state."""
    expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
    expense.edit(description="Late dinner")

    rebuilt = evolved(expense)

    assert rebuilt.pull_events() == []
    assert len(expense.pull_events()) == 1

  def test_a_deleted_expense_stays_deleted_when_rebuilt(self, alice):
    expense = make_expense(paid_by=alice)
    expense.mark_deleted()

    assert evolved(expense).deleted is True
