"""Editing an expense is a partial update: only the fields present in the input change, and
the ones left as `None` keep whatever the stored expense already had. The use case has to
find the expense inside its group, prove the editor belongs to that group, vet any new
participants, and re-run a split strategy whenever the money or the people move.

These tests pin that wiring. `TestKnownGaps` at the bottom pins behavior that is currently
*accepted* but probably should not be — it is there so a future fix breaks a test on purpose.
"""

from __future__ import annotations

import pytest

from application.dto.expense_dto import ExpenseView
from application.exceptions import NotAuthorizedError, NotFoundError
from application.use_cases.expenses.edit_expense import (
  EditExpenseInput,
  EditExpenseUseCase,
)
from domain.entities.expense import InvalidExpenseError
from domain.events.expense_events import ExpenseEdited
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.split_strategy import InvalidSplitStrategyError
from tests.builders import CURRENCY, id_for, make_expense, make_group, money
from tests.fakes import (
  InMemoryEventPublisher,
  InMemoryExpenseRepository,
  InMemoryGroupRepository,
)


@pytest.fixture
def expense_id() -> ExpenseId:
  return id_for(ExpenseId, "dinner")


@pytest.fixture
def groups(
  alice: UserId, bob: UserId, carol: UserId, group_id: GroupId
) -> InMemoryGroupRepository:
  """Alice created the group; bob and carol joined. Dave is an outsider."""
  return InMemoryGroupRepository(
    [make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob, carol])]
  )


@pytest.fixture
def expenses(
  expense_id: ExpenseId, group_id: GroupId, alice: UserId, bob: UserId
) -> InMemoryExpenseRepository:
  """One stored expense: 100.00 dinner paid by alice, split equally with bob."""
  return InMemoryExpenseRepository(
    [
      make_expense(
        id=expense_id,
        group_id=group_id,
        description="Dinner",
        total=money(10_000),
        paid_by=alice,
        participants=[alice, bob],
      )
    ]
  )


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
  return InMemoryEventPublisher()


@pytest.fixture
def use_case(
  expenses: InMemoryExpenseRepository,
  groups: InMemoryGroupRepository,
  publisher: InMemoryEventPublisher,
) -> EditExpenseUseCase:
  return EditExpenseUseCase(expenses, groups, publisher)


@pytest.fixture
def an_edit(group_id: GroupId, expense_id: ExpenseId, alice: UserId):
  """The smallest valid input: alice touching her own group's expense, changing nothing."""

  def build(**overrides) -> EditExpenseInput:
    fields = {
      "group_id": str(group_id),
      "expense_id": str(expense_id),
      "requested_by": str(alice),
    }
    return EditExpenseInput(**{**fields, **overrides})

  return build


def owed_by(view: ExpenseView) -> dict[str, int]:
  """The split lines keyed by user id."""
  return {split.user_id: split.amount_cents for split in view.splits}


class TestPartialUpdate:
  def test_renames_the_expense(self, use_case, an_edit):
    view = use_case.execute(an_edit(description="Late dinner"))

    assert view.description == "Late dinner"

  def test_a_rename_leaves_the_money_alone(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    view = use_case.execute(an_edit(description="Late dinner"))

    assert view.total_cents == 10_000
    assert owed_by(view) == {str(alice): 5_000, str(bob): 5_000}

  def test_an_edit_that_sets_nothing_keeps_every_field(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    view = use_case.execute(an_edit())

    assert view.description == "Dinner"
    assert view.total_cents == 10_000
    assert owed_by(view) == {str(alice): 5_000, str(bob): 5_000}

  @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "blank"])
  def test_a_blank_description_is_rejected(self, use_case, expenses, an_edit, blank: str):
    """An edit cannot erase the description any more than `create` can omit it."""
    with pytest.raises(InvalidExpenseError, match="description cannot be empty"):
      use_case.execute(an_edit(description=blank))

    assert expenses.saved == []

  def test_a_renamed_description_is_stored_trimmed(self, use_case, expenses, an_edit):
    view = use_case.execute(an_edit(description="  Late dinner  "))

    assert view.description == "Late dinner"
    assert expenses.saved[-1].description == "Late dinner"

  def test_the_identity_of_the_expense_survives_an_edit(
    self, use_case, an_edit, expense_id: ExpenseId, group_id: GroupId, alice: UserId
  ):
    """An edit is an update, not a replacement: id, group and payer are not editable."""
    view = use_case.execute(an_edit(description="Late dinner"))

    assert view.id == str(expense_id)
    assert view.group_id == str(group_id)
    assert view.paid_by == str(alice)

  def test_the_creation_time_is_not_bumped(self, use_case, expenses, an_edit, group_id):
    original = expenses.get_for_group(group_id)[0].created_at

    use_case.execute(an_edit(description="Late dinner"))

    assert expenses.saved[-1].created_at == original


class TestChangingTheTotal:
  def test_a_new_total_is_re_split_between_the_participants(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    view = use_case.execute(an_edit(total_cents=20_000, split_type="equal"))

    assert view.total_cents == 20_000
    assert owed_by(view) == {str(alice): 10_000, str(bob): 10_000}

  def test_leftover_cents_go_to_the_earliest_participants(
    self, use_case, an_edit, alice: UserId, bob: UserId, carol: UserId
  ):
    view = use_case.execute(
      an_edit(
        total_cents=10_001,
        participant_ids=[str(alice), str(bob), str(carol)],
        split_type="equal",
      )
    )

    assert owed_by(view) == {str(alice): 3_334, str(bob): 3_334, str(carol): 3_333}
    assert sum(owed_by(view).values()) == 10_001

  def test_a_new_total_without_a_split_type_is_refused(self, use_case, an_edit):
    """The use case only builds a strategy when `split_type` is given, and the entity
    refuses to move money without one rather than guess how to re-split it."""
    with pytest.raises(InvalidExpenseError, match="split strategy must be provided"):
      use_case.execute(an_edit(total_cents=20_000))

  def test_a_refused_total_change_writes_nothing(self, use_case, expenses, an_edit):
    with pytest.raises(InvalidExpenseError):
      use_case.execute(an_edit(total_cents=20_000))

    assert expenses.saved == []


class TestChangingTheParticipants:
  def test_adding_a_participant_re_splits_the_unchanged_total(
    self, use_case, an_edit, alice: UserId, bob: UserId, carol: UserId
  ):
    view = use_case.execute(
      an_edit(participant_ids=[str(alice), str(bob), str(carol)], split_type="equal")
    )

    assert view.total_cents == 10_000
    assert owed_by(view) == {str(alice): 3_334, str(bob): 3_333, str(carol): 3_333}

  def test_dropping_a_participant_re_splits_the_unchanged_total(
    self, use_case, an_edit, alice: UserId
  ):
    view = use_case.execute(an_edit(participant_ids=[str(alice)], split_type="equal"))

    assert owed_by(view) == {str(alice): 10_000}

  def test_the_payer_can_be_dropped_from_the_split(
    self, use_case, an_edit, alice: UserId, bob: UserId, carol: UserId
  ):
    """Alice paid, so she can stop sharing the cost without ceasing to be the payer."""
    view = use_case.execute(
      an_edit(participant_ids=[str(bob), str(carol)], split_type="equal")
    )

    assert owed_by(view) == {str(bob): 5_000, str(carol): 5_000}
    assert view.paid_by == str(alice)

  def test_new_participants_without_a_split_type_are_refused(self, use_case, an_edit):
    with pytest.raises(InvalidExpenseError, match="split strategy must be provided"):
      use_case.execute(an_edit(participant_ids=[str(id_for(UserId, "alice"))]))


class TestChangingTheSplit:
  def test_an_exact_split_uses_the_amounts_given(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    view = use_case.execute(
      an_edit(
        total_cents=10_000,
        split_type="exact",
        exact_amounts_cents={str(alice): 7_000, str(bob): 3_000},
      )
    )

    assert owed_by(view) == {str(alice): 7_000, str(bob): 3_000}

  def test_a_percentage_split_applies_the_percentages(
    self, use_case, an_edit, alice: UserId, bob: UserId, carol: UserId
  ):
    view = use_case.execute(
      an_edit(
        participant_ids=[str(alice), str(bob), str(carol)],
        split_type="percentage",
        percentages={str(alice): 50.0, str(bob): 25.0, str(carol): 25.0},
      )
    )

    assert owed_by(view) == {str(alice): 5_000, str(bob): 2_500, str(carol): 2_500}

  def test_exact_amounts_that_miss_the_total_are_rejected(
    self, use_case, expenses, an_edit, alice: UserId, bob: UserId
  ):
    with pytest.raises(InvalidSplitStrategyError, match="does not match the specified total"):
      use_case.execute(
        an_edit(
          total_cents=10_000,
          split_type="exact",
          exact_amounts_cents={str(alice): 7_000, str(bob): 2_000},
        )
      )

    assert expenses.saved == []

  def test_percentages_that_miss_a_hundred_are_rejected(
    self, use_case, expenses, an_edit, alice: UserId, bob: UserId
  ):
    with pytest.raises(InvalidSplitStrategyError, match="must sum to 100"):
      use_case.execute(
        an_edit(split_type="percentage", percentages={str(alice): 60.0, str(bob): 30.0})
      )

    assert expenses.saved == []

  def test_an_exact_split_without_amounts_is_rejected(self, use_case, an_edit):
    with pytest.raises(ValueError, match="exact_amounts_cents is required"):
      use_case.execute(an_edit(total_cents=10_000, split_type="exact"))

  def test_a_percentage_split_without_percentages_is_rejected(self, use_case, an_edit):
    with pytest.raises(ValueError, match="percentages is required"):
      use_case.execute(an_edit(total_cents=10_000, split_type="percentage"))

  @pytest.mark.parametrize("unknown", ["even", "EQUAL", "half"])
  def test_an_unknown_split_type_is_rejected(self, use_case, expenses, an_edit, unknown: str):
    with pytest.raises(ValueError, match="Unknown split_type"):
      use_case.execute(an_edit(total_cents=20_000, split_type=unknown))

    assert expenses.saved == []

  def test_an_empty_split_type_reads_as_no_split_type_at_all(self, use_case, an_edit):
    """`split_type` is checked for truthiness, so `""` never reaches the strategy builder:
    it fails as a missing strategy rather than as an unknown one."""
    with pytest.raises(InvalidExpenseError, match="split strategy must be provided"):
      use_case.execute(an_edit(total_cents=20_000, split_type=""))


class TestCurrency:
  def test_the_stored_currency_is_kept_when_the_input_names_none(self, use_case, an_edit):
    view = use_case.execute(an_edit(total_cents=20_000, split_type="equal"))

    assert view.currency == CURRENCY
    assert {split.currency for split in view.splits} == {CURRENCY}

  def test_a_new_currency_is_applied_to_the_total_and_the_splits(self, use_case, an_edit):
    view = use_case.execute(an_edit(total_cents=20_000, currency="USD", split_type="equal"))

    assert view.currency == "USD"
    assert {split.currency for split in view.splits} == {"USD"}

  def test_exact_amounts_are_booked_in_the_new_currency(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    view = use_case.execute(
      an_edit(
        total_cents=10_000,
        currency="USD",
        split_type="exact",
        exact_amounts_cents={str(alice): 6_000, str(bob): 4_000},
      )
    )

    assert view.currency == "USD"
    assert owed_by(view) == {str(alice): 6_000, str(bob): 4_000}
    assert {split.currency for split in view.splits} == {"USD"}

  def test_a_currency_that_is_not_a_three_letter_code_is_rejected(self, use_case, an_edit):
    with pytest.raises(ValueError, match="Currency must be a 3-letter ISO code"):
      use_case.execute(an_edit(total_cents=20_000, currency="US", split_type="equal"))


class TestAuthorization:
  def test_any_member_may_edit_the_expense(self, use_case, an_edit, carol: UserId):
    """Editing is a group-level right, not the payer's alone."""
    view = use_case.execute(an_edit(requested_by=str(carol), description="Carol fixed this"))

    assert view.description == "Carol fixed this"

  def test_a_non_member_may_not_edit_the_expense(self, use_case, an_edit, dave: UserId):
    with pytest.raises(NotAuthorizedError, match=str(dave)):
      use_case.execute(an_edit(requested_by=str(dave), description="Late dinner"))

  def test_a_non_member_writes_nothing(self, use_case, expenses, an_edit, dave: UserId):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(an_edit(requested_by=str(dave), description="Late dinner"))

    assert expenses.saved == []

  def test_an_outsider_cannot_be_made_a_participant(
    self, use_case, an_edit, alice: UserId, dave: UserId
  ):
    with pytest.raises(NotAuthorizedError, match="is not a member of group"):
      use_case.execute(
        an_edit(participant_ids=[str(alice), str(dave)], split_type="equal")
      )

  def test_an_outsider_participant_writes_nothing(
    self, use_case, expenses, an_edit, alice: UserId, dave: UserId
  ):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(an_edit(participant_ids=[str(alice), str(dave)], split_type="equal"))

    assert expenses.saved == []


class TestMissingRecords:
  def test_an_unknown_expense_is_reported_as_not_found(self, use_case, an_edit):
    with pytest.raises(NotFoundError, match="Expense with ID"):
      use_case.execute(an_edit(expense_id=str(id_for(ExpenseId, "no-such-expense"))))

  def test_an_expense_belonging_to_another_group_is_not_found(
    self, use_case, an_edit, alice: UserId
  ):
    """The lookup is scoped by group, so a real expense id under the wrong group misses."""
    with pytest.raises(NotFoundError, match="Expense with ID"):
      use_case.execute(an_edit(group_id=str(id_for(GroupId, "boracay-trip"))))

  def test_an_unknown_group_is_reported_as_not_found(
    self, expenses, an_edit, expense_id: ExpenseId
  ):
    """Reachable only when the two stores disagree — the expense exists but its group is gone."""
    use_case = EditExpenseUseCase(expenses, InMemoryGroupRepository([]), InMemoryEventPublisher())

    with pytest.raises(NotFoundError, match="Group with ID"):
      use_case.execute(an_edit(description="Late dinner"))

  def test_a_missing_record_writes_nothing(self, use_case, expenses, an_edit):
    with pytest.raises(NotFoundError):
      use_case.execute(an_edit(expense_id=str(id_for(ExpenseId, "no-such-expense"))))

    assert expenses.saved == []


class TestPersistence:
  def test_saves_the_edited_expense_once(self, use_case, expenses, an_edit):
    use_case.execute(an_edit(description="Late dinner"))

    assert len(expenses.saved) == 1

  def test_the_change_is_readable_afterwards(self, use_case, expenses, an_edit, group_id):
    use_case.execute(an_edit(description="Late dinner"))

    assert [e.description for e in expenses.get_for_group(group_id)] == ["Late dinner"]

  def test_editing_does_not_create_a_second_expense(
    self, use_case, expenses, an_edit, group_id: GroupId
  ):
    use_case.execute(an_edit(description="Late dinner"))
    use_case.execute(an_edit(total_cents=20_000, split_type="equal"))

    assert len(expenses.get_for_group(group_id)) == 1

  def test_edits_accumulate_on_the_same_expense(
    self, use_case, expenses, an_edit, group_id: GroupId
  ):
    use_case.execute(an_edit(description="Late dinner"))
    use_case.execute(an_edit(total_cents=20_000, split_type="equal"))

    stored = expenses.get_for_group(group_id)[0]
    assert stored.description == "Late dinner"
    assert stored.total == money(20_000)

  def test_editing_an_expense_does_not_touch_the_group(self, use_case, groups, an_edit):
    use_case.execute(an_edit(description="Late dinner"))

    assert groups.saved == []


class TestTheView:
  def test_describes_the_expense_after_the_edit(
    self, use_case, an_edit, expense_id: ExpenseId, group_id: GroupId, alice: UserId
  ):
    view = use_case.execute(an_edit(description="Late dinner", total_cents=20_000, split_type="equal"))

    assert view.id == str(expense_id)
    assert view.group_id == str(group_id)
    assert view.description == "Late dinner"
    assert view.total_cents == 20_000
    assert view.paid_by == str(alice)
    assert view.deleted is False
    assert view.created_at is not None

  def test_the_splits_always_add_up_to_the_total(self, use_case, an_edit, alice, bob, carol):
    view = use_case.execute(
      an_edit(
        total_cents=1_000,
        participant_ids=[str(alice), str(bob), str(carol)],
        split_type="percentage",
        percentages={str(alice): 33.33, str(bob): 33.33, str(carol): 33.34},
      )
    )

    assert sum(owed_by(view).values()) == view.total_cents == 1_000

  def test_is_immutable(self, use_case, an_edit):
    view = use_case.execute(an_edit())

    with pytest.raises(Exception):
      view.description = "Renamed"


class TestUntrustedInput:
  """Every field arrives as raw request data, so the guards belong to the use case."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, an_edit, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(an_edit(group_id=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "dinner", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_an_expense_id_that_is_not_a_uuid_is_rejected(self, use_case, an_edit, malformed: str):
    with pytest.raises(ValueError, match="ExpenseId must be"):
      use_case.execute(an_edit(expense_id=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "alice", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_an_editor_id_that_is_not_a_uuid_is_rejected(self, use_case, an_edit, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(an_edit(requested_by=malformed))

  def test_a_participant_id_that_is_not_a_uuid_is_rejected(
    self, use_case, an_edit, alice: UserId
  ):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(an_edit(participant_ids=[str(alice), "bob"], split_type="equal"))

  def test_a_total_that_is_not_an_integer_is_rejected(self, use_case, an_edit):
    """`EditExpenseInput.total_cents` is annotated `str | None`, but `Money` only takes cents
    as an int — the annotation is wrong, not the guard."""
    with pytest.raises(ValueError, match="Money amount must be an integer"):
      use_case.execute(an_edit(total_cents="20000", split_type="equal"))

  def test_malformed_input_writes_nothing(self, use_case, expenses, an_edit):
    with pytest.raises(ValueError):
      use_case.execute(an_edit(group_id="not-a-uuid"))

    assert expenses.saved == []


class TestInput:
  def test_the_input_is_immutable(self, an_edit):
    input_data = an_edit(description="Late dinner")

    with pytest.raises(Exception):
      input_data.description = "Renamed"


class TestKnownGaps:
  """Edits that the use case currently lets through even though `create` refuses them.

  `Expense.edit` re-runs only `_validate_splits_sum_to_total`, never the `__post_init__`
  invariants, and it recomputes splits only when the total or the participants change.
  Each test here asserts what happens *today*; fixing the gap should break it on purpose.
  """

  def test_changing_only_the_split_type_does_not_re_split(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    """GAP: the strategy is built and then discarded, because neither the total nor the
    participants moved. "Split this exactly instead of equally" is silently a no-op."""
    view = use_case.execute(
      an_edit(split_type="exact", exact_amounts_cents={str(alice): 6_000, str(bob): 4_000})
    )

    assert owed_by(view) == {str(alice): 5_000, str(bob): 5_000}

  def test_exact_amounts_for_the_wrong_people_are_not_caught(
    self, use_case, an_edit, alice: UserId, bob: UserId, carol: UserId
  ):
    """GAP: same cause — the strategy never runs, so its participant check never fires."""
    view = use_case.execute(
      an_edit(split_type="exact", exact_amounts_cents={str(alice): 5_000, str(carol): 5_000})
    )

    assert owed_by(view) == {str(alice): 5_000, str(bob): 5_000}

  @pytest.mark.parametrize("amount", [0, -500], ids=["zero", "negative"])
  def test_a_non_positive_total_is_accepted(self, use_case, an_edit, amount: int):
    """GAP: `create` requires a positive total; `edit` never re-checks it."""
    view = use_case.execute(an_edit(total_cents=amount, split_type="equal"))

    assert view.total_cents == amount

  def test_an_empty_participant_list_is_silently_ignored(
    self, use_case, an_edit, alice: UserId, bob: UserId
  ):
    """GAP: `participants or [...]` treats `[]` as "not given" and keeps the old split,
    rather than rejecting an expense nobody owes."""
    view = use_case.execute(an_edit(participant_ids=[], split_type="equal"))

    assert owed_by(view) == {str(alice): 5_000, str(bob): 5_000}

  def test_a_currency_on_its_own_is_ignored(self, use_case, an_edit):
    """GAP: currency is only read while building a new total, so a currency-only edit
    silently does nothing instead of re-denominating the expense."""
    view = use_case.execute(an_edit(currency="USD"))

    assert view.currency == CURRENCY

  def test_a_deleted_expense_can_still_be_edited(
    self, expense_id: ExpenseId, group_id: GroupId, groups, alice: UserId, bob: UserId, an_edit
  ):
    """GAP: nothing checks `expense.deleted` before applying the edit."""
    expenses = InMemoryExpenseRepository(
      [
        make_expense(
          id=expense_id,
          group_id=group_id,
          total=money(10_000),
          paid_by=alice,
          participants=[alice, bob],
          deleted=True,
        )
      ]
    )
    use_case = EditExpenseUseCase(expenses, groups, InMemoryEventPublisher())

    view = use_case.execute(an_edit(description="Edited after deletion"))

    assert view.deleted is True
    assert view.description == "Edited after deletion"


class TestEvents:
  """An edit moves the money that was already split, so whatever recomputes balances has to
  hear about it — the entity records the event, but only `execute` gets it to a subscriber."""

  def test_publishes_that_the_expense_was_edited(self, use_case, publisher, an_edit):
    use_case.execute(an_edit(description="Late dinner"))

    assert publisher.types() == ["ExpenseEdited"]

  def test_the_published_event_carries_the_new_values(
    self, use_case, publisher, an_edit, group_id: GroupId, expense_id: ExpenseId, alice, bob
  ):
    use_case.execute(
      an_edit(description="Late dinner", total_cents=20_000, split_type="equal")
    )

    event = publisher.published[0]
    assert isinstance(event, ExpenseEdited)
    assert (event.group_id, event.expense_id) == (group_id, expense_id)
    assert event.new_amount == money(20_000)
    assert event.new_description == "Late dinner"

  def test_an_unchanged_field_is_reported_at_its_current_value(
    self, use_case, publisher, an_edit
  ):
    """The event is a snapshot, not a delta, so the description survives a total-only edit."""
    use_case.execute(an_edit(total_cents=20_000, split_type="equal"))

    assert publisher.published[0].new_description == "Dinner"

  def test_publishes_once_per_call(self, use_case, publisher, an_edit):
    """One `publish` per operation, so a subscriber sees one batch rather than a trickle."""
    use_case.execute(an_edit(description="Late dinner"))

    assert len(publisher.batches) == 1
    assert len(publisher.batches[0]) == 1

  def test_publishes_after_the_write(self, groups, expense_id, group_id, alice, bob, an_edit):
    """A subscriber that reads the expense back must already find the new values, so the save
    has to land first."""
    timeline: list[str] = []

    class NotingRepository(InMemoryExpenseRepository):
      def save(self, expense):
        timeline.append("save")
        super().save(expense)

    class NotingPublisher(InMemoryEventPublisher):
      def publish(self, events):
        if events:
          timeline.append("publish")
        super().publish(events)

    noting_expenses = NotingRepository(
      [
        make_expense(
          id=expense_id,
          group_id=group_id,
          description="Dinner",
          total=money(10_000),
          paid_by=alice,
          participants=[alice, bob],
        )
      ]
    )
    use_case = EditExpenseUseCase(noting_expenses, groups, NotingPublisher())

    use_case.execute(an_edit(description="Late dinner"))

    assert timeline == ["save", "publish"]

  def test_each_call_publishes_only_its_own_event(self, use_case, publisher, an_edit):
    """A second edit must not re-announce the first — `pull_events` drains the aggregate and
    a rebuilt expense starts clean."""
    use_case.execute(an_edit(description="Late dinner"))
    use_case.execute(an_edit(description="Very late dinner"))

    assert [len(batch) for batch in publisher.batches] == [1, 1]
    assert [event.new_description for event in publisher.published] == [
      "Late dinner",
      "Very late dinner",
    ]

  def test_the_expense_keeps_no_events_after_publishing(
    self, use_case, expenses, an_edit, group_id: GroupId, expense_id: ExpenseId
  ):
    """`pull_events` drains the aggregate, so nothing can be published a second time."""
    use_case.execute(an_edit(description="Late dinner"))

    assert expenses.get_by_id(group_id, expense_id).pull_events() == []


class TestNothingIsPublishedOnFailure:
  def test_an_edit_that_changes_nothing_publishes_nothing(self, use_case, publisher, an_edit):
    """`Expense.edit` returns early when the values match, so there is no event to hand on —
    even though the use case still saves."""
    use_case.execute(an_edit())

    assert publisher.published == []
    assert publisher.batches == [[]]

  def test_a_repeated_edit_publishes_only_the_first(self, use_case, publisher, an_edit):
    use_case.execute(an_edit(description="Late dinner"))
    use_case.execute(an_edit(description="Late dinner"))

    assert publisher.types() == ["ExpenseEdited"]

  def test_an_unknown_expense_publishes_nothing(self, use_case, publisher, an_edit):
    with pytest.raises(NotFoundError):
      use_case.execute(an_edit(expense_id=str(id_for(ExpenseId, "no-such-expense"))))

    assert publisher.published == []
    assert publisher.batches == []

  def test_a_non_member_editor_publishes_nothing(self, use_case, publisher, an_edit, dave):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(an_edit(requested_by=str(dave), description="Late dinner"))

    assert publisher.published == []

  def test_an_invalid_edit_publishes_nothing(self, use_case, publisher, an_edit):
    """A new total with no strategy is refused by the entity before anything is recorded."""
    with pytest.raises(InvalidExpenseError):
      use_case.execute(an_edit(total_cents=20_000))

    assert publisher.published == []

  def test_a_malformed_id_publishes_nothing(self, use_case, publisher, an_edit):
    with pytest.raises(ValueError):
      use_case.execute(an_edit(group_id="not-a-uuid"))

    assert publisher.published == []
