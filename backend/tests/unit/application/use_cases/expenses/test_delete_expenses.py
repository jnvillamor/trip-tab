"""Deleting an expense is a soft delete: the record stays in the store with `deleted` flipped,
so history and any audit of past balances survive. The use case only has to find the expense
inside its group, prove the caller is the one who paid, and flip the flag.

It takes no group repository, so unlike create and edit it never asks who belongs to the
group — being the payer is the whole authorization story. `TestKnownGaps` pins behavior that
is currently accepted but probably should not be.
"""

from __future__ import annotations

import pytest

from application.exceptions import NotAuthorizedError, NotFoundError
from application.use_cases.expenses.delete_expenses import (
  DeleteExpenseInput,
  DeleteExpenseUseCase,
)
from domain.events.expense_events import ExpenseDeleted
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from tests.builders import id_for, make_expense, money
from tests.fakes import InMemoryEventPublisher, InMemoryExpenseRepository


@pytest.fixture
def expense_id() -> ExpenseId:
  return id_for(ExpenseId, "dinner")


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
  expenses: InMemoryExpenseRepository, publisher: InMemoryEventPublisher
) -> DeleteExpenseUseCase:
  return DeleteExpenseUseCase(expenses, publisher)


@pytest.fixture
def a_delete(group_id: GroupId, expense_id: ExpenseId, alice: UserId):
  """The only valid input: alice deleting the expense she paid for."""

  def build(**overrides) -> DeleteExpenseInput:
    fields = {
      "group_id": str(group_id),
      "expense_id": str(expense_id),
      "requested_by": str(alice),
    }
    return DeleteExpenseInput(**{**fields, **overrides})

  return build


class TestDeleting:
  def test_marks_the_expense_deleted(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    use_case.execute(a_delete())

    assert expenses.get_by_id(group_id, expense_id).deleted is True

  def test_returns_nothing(self, use_case, a_delete):
    """A delete has no read model to hand back."""
    assert use_case.execute(a_delete()) is None

  def test_saves_the_expense_once(self, use_case, expenses, a_delete):
    use_case.execute(a_delete())

    assert len(expenses.saved) == 1

  def test_the_saved_expense_is_the_one_asked_for(
    self, use_case, expenses, a_delete, expense_id: ExpenseId
  ):
    use_case.execute(a_delete())

    assert [expense.id for expense in expenses.saved] == [expense_id]


class TestSoftDelete:
  def test_the_record_is_kept_not_removed(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    use_case.execute(a_delete())

    assert expenses.get_by_id(group_id, expense_id) is not None

  def test_nothing_but_the_flag_changes(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    before = expenses.get_by_id(group_id, expense_id)

    use_case.execute(a_delete())
    after = expenses.get_by_id(group_id, expense_id)

    assert after.id == before.id
    assert after.group_id == before.group_id
    assert after.description == before.description
    assert after.total == before.total
    assert after.paid_by == before.paid_by
    assert after.created_at == before.created_at
    assert after.splits == before.splits

  def test_the_splits_are_left_intact(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId, alice, bob
  ):
    """Balances are recomputed from splits, so a delete must not erase them — a reader
    that ignores `deleted` would still see the old numbers."""
    use_case.execute(a_delete())

    stored = expenses.get_by_id(group_id, expense_id)
    assert {split.user_id: split.owed.amount_cents for split in stored.splits} == {
      alice: 5_000,
      bob: 5_000,
    }


class TestAuthorization:
  def test_the_payer_may_delete_the_expense(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    use_case.execute(a_delete())

    assert expenses.get_by_id(group_id, expense_id).deleted is True

  def test_a_participant_who_did_not_pay_may_not_delete_it(self, use_case, a_delete, bob: UserId):
    """Owing a share of the expense does not grant the right to remove it."""
    with pytest.raises(NotFoundError, match="is not authorized"):
      use_case.execute(a_delete(requested_by=str(bob)))

  def test_someone_outside_the_expense_may_not_delete_it(self, use_case, a_delete, dave: UserId):
    with pytest.raises(NotFoundError, match="is not authorized"):
      use_case.execute(a_delete(requested_by=str(dave)))

  def test_an_unauthorized_caller_writes_nothing(self, use_case, expenses, a_delete, bob: UserId):
    with pytest.raises(NotFoundError):
      use_case.execute(a_delete(requested_by=str(bob)))

    assert expenses.saved == []

  def test_an_unauthorized_caller_leaves_the_expense_alive(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId, bob: UserId
  ):
    with pytest.raises(NotFoundError):
      use_case.execute(a_delete(requested_by=str(bob)))

    assert expenses.get_by_id(group_id, expense_id).deleted is False


class TestMissingRecords:
  def test_an_unknown_expense_is_reported_as_not_found(self, use_case, a_delete):
    with pytest.raises(NotFoundError, match="not found in group"):
      use_case.execute(a_delete(expense_id=str(id_for(ExpenseId, "no-such-expense"))))

  def test_an_expense_belonging_to_another_group_is_not_found(self, use_case, a_delete):
    """The lookup is scoped by group, so a real expense id under the wrong group misses."""
    with pytest.raises(NotFoundError, match="not found in group"):
      use_case.execute(a_delete(group_id=str(id_for(GroupId, "boracay-trip"))))

  def test_an_expense_in_another_group_is_left_alone(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    with pytest.raises(NotFoundError):
      use_case.execute(a_delete(group_id=str(id_for(GroupId, "boracay-trip"))))

    assert expenses.get_by_id(group_id, expense_id).deleted is False

  def test_a_missing_record_writes_nothing(self, use_case, expenses, a_delete):
    with pytest.raises(NotFoundError):
      use_case.execute(a_delete(expense_id=str(id_for(ExpenseId, "no-such-expense"))))

    assert expenses.saved == []


class TestUntrustedInput:
  """Every field arrives as raw request data, so the ids are parsed before anything is read."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, a_delete, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(a_delete(group_id=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "dinner", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_an_expense_id_that_is_not_a_uuid_is_rejected(self, use_case, a_delete, malformed: str):
    with pytest.raises(ValueError, match="ExpenseId must be"):
      use_case.execute(a_delete(expense_id=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "alice", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_caller_id_that_is_not_a_uuid_is_rejected(self, use_case, a_delete, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(a_delete(requested_by=malformed))

  def test_malformed_input_writes_nothing(self, use_case, expenses, a_delete):
    with pytest.raises(ValueError):
      use_case.execute(a_delete(group_id="not-a-uuid"))

    assert expenses.saved == []

  def test_the_ids_are_parsed_before_the_expense_is_read(self, use_case, expenses, a_delete):
    """A malformed caller id fails without the store ever being queried."""
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(a_delete(requested_by="alice"))

    assert expenses.saved == []


class TestInput:
  def test_the_input_is_immutable(self, a_delete):
    input_data = a_delete()

    with pytest.raises(Exception):
      input_data.requested_by = str(id_for(UserId, "bob"))


class TestEvents:
  """A delete takes the expense out of every balance, so whatever recomputes them has to hear
  about it — the entity records the event, but only `execute` gets it to a subscriber."""

  def test_publishes_that_the_expense_was_deleted(self, use_case, publisher, a_delete):
    use_case.execute(a_delete())

    assert publisher.types() == ["ExpenseDeleted"]

  def test_the_published_event_names_the_expense_and_its_group(
    self, use_case, publisher, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    use_case.execute(a_delete())

    event = publisher.published[0]
    assert isinstance(event, ExpenseDeleted)
    assert (event.group_id, event.expense_id) == (group_id, expense_id)

  def test_publishes_once_per_call(self, use_case, publisher, a_delete):
    """One `publish` per operation, so a subscriber sees one batch rather than a trickle."""
    use_case.execute(a_delete())

    assert len(publisher.batches) == 1
    assert len(publisher.batches[0]) == 1

  def test_publishes_after_the_write(self, expense_id, group_id, alice, bob, a_delete):
    """A subscriber that reads the expense back must already find it flagged, so the save has
    to land first."""
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
          total=money(10_000),
          paid_by=alice,
          participants=[alice, bob],
        )
      ]
    )
    use_case = DeleteExpenseUseCase(noting_expenses, NotingPublisher())

    use_case.execute(a_delete())

    assert timeline == ["save", "publish"]

  def test_the_expense_keeps_no_events_after_publishing(
    self, use_case, expenses, a_delete, group_id: GroupId, expense_id: ExpenseId
  ):
    """`pull_events` drains the aggregate, so nothing can be published a second time."""
    use_case.execute(a_delete())

    assert expenses.get_by_id(group_id, expense_id).pull_events() == []


class TestNothingIsPublishedOnFailure:
  def test_a_second_delete_publishes_nothing(self, use_case, publisher, a_delete):
    """`mark_deleted` returns early when the flag is already set, so the redundant write —
    see `TestKnownGaps` — announces nothing."""
    use_case.execute(a_delete())
    use_case.execute(a_delete())

    assert publisher.types() == ["ExpenseDeleted"]
    assert publisher.batches[1] == []

  def test_an_unauthorized_caller_publishes_nothing(self, use_case, publisher, a_delete, bob):
    with pytest.raises(NotFoundError):
      use_case.execute(a_delete(requested_by=str(bob)))

    assert publisher.published == []
    assert publisher.batches == []

  def test_an_unknown_expense_publishes_nothing(self, use_case, publisher, a_delete):
    with pytest.raises(NotFoundError):
      use_case.execute(a_delete(expense_id=str(id_for(ExpenseId, "no-such-expense"))))

    assert publisher.published == []

  def test_a_malformed_id_publishes_nothing(self, use_case, publisher, a_delete):
    with pytest.raises(ValueError):
      use_case.execute(a_delete(group_id="not-a-uuid"))

    assert publisher.published == []


class TestKnownGaps:
  """Behavior the use case currently allows that is worth a second look.

  Each test asserts what happens *today*; fixing the gap should break it on purpose.
  """

  def test_an_unauthorized_caller_gets_a_not_found_error(self, use_case, a_delete, bob: UserId):
    """GAP: the message says "is not authorized" but the type is `NotFoundError`, while
    `create` and `edit` both raise `NotAuthorizedError` for the same kind of refusal. A
    caller matching on the exception type sees this as a missing expense."""
    with pytest.raises(NotFoundError, match="is not authorized"):
      use_case.execute(a_delete(requested_by=str(bob)))

    with pytest.raises(Exception) as caught:
      use_case.execute(a_delete(requested_by=str(bob)))
    assert not isinstance(caught.value, NotAuthorizedError)

  def test_deleting_an_already_deleted_expense_succeeds(
    self, expense_id: ExpenseId, group_id: GroupId, alice: UserId, bob: UserId, a_delete
  ):
    """GAP: `Expense.mark_deleted` has no guard — unlike `Group.close`, which refuses to
    close a closed group — so a repeat delete is accepted rather than reported."""
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
    use_case = DeleteExpenseUseCase(expenses, InMemoryEventPublisher())

    assert use_case.execute(a_delete()) is None
    assert len(expenses.saved) == 1

  def test_deleting_twice_writes_twice(self, use_case, expenses, a_delete):
    """GAP: same cause — the second call is a redundant write, not a no-op."""
    use_case.execute(a_delete())
    use_case.execute(a_delete())

    assert len(expenses.saved) == 2

  def test_a_deleted_expense_is_still_returned_by_group_queries(
    self, use_case, expenses, a_delete, group_id: GroupId
  ):
    """GAP: `deleted` is a flag nobody filters on yet, so every reader has to remember to
    skip these itself or the expense keeps counting toward balances."""
    use_case.execute(a_delete())

    assert len(expenses.get_for_group(group_id)) == 1

  def test_a_deleted_expense_is_still_returned_by_user_queries(
    self, use_case, expenses, a_delete, alice: UserId
  ):
    """GAP: same cause, on the payer's own view of what they are owed."""
    use_case.execute(a_delete())

    assert len(expenses.get_by_user(alice)) == 1
