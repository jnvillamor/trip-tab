"""Creating an expense turns raw request data into a split ledger entry: ids are parsed,
every party must belong to the group, and the split strategy named in the input decides who
owes what. These tests pin that wiring and the guards around it.
"""

from __future__ import annotations

import pytest

from application.dto.expense_dto import ExpenseView
from application.exceptions import NotAuthorizedError, NotFoundError
from application.use_cases.expenses.create_expense import (
  CreateExpenseInput,
  CreateExpenseUseCase,
)
from domain.entities.expense import InvalidExpenseError
from domain.events.expense_events import ExpenseCreated
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import InvalidSplitStrategyError
from tests.builders import CURRENCY, id_for, make_group
from tests.fakes import (
  InMemoryEventPublisher,
  InMemoryExpenseRepository,
  InMemoryGroupRepository,
)


@pytest.fixture
def groups(
  alice: UserId, bob: UserId, carol: UserId, group_id: GroupId
) -> InMemoryGroupRepository:
  return InMemoryGroupRepository(
    [make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob, carol])]
  )


@pytest.fixture
def expenses() -> InMemoryExpenseRepository:
  return InMemoryExpenseRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
  return InMemoryEventPublisher()


@pytest.fixture
def use_case(
  groups: InMemoryGroupRepository,
  expenses: InMemoryExpenseRepository,
  publisher: InMemoryEventPublisher,
) -> CreateExpenseUseCase:
  return CreateExpenseUseCase(groups, expenses, publisher)


@pytest.fixture
def an_equal_split(group_id: GroupId, alice: UserId, bob: UserId):
  """The simplest valid input: dinner paid by alice, split equally with bob."""

  def build(**overrides) -> CreateExpenseInput:
    fields = {
      "group_id": str(group_id),
      "description": "Dinner",
      "total_cents": 10_000,
      "currency": CURRENCY,
      "paid_by": str(alice),
      "participants_ids": [str(alice), str(bob)],
      "split_type": "equal",
    }
    return CreateExpenseInput(**{**fields, **overrides})

  return build


def owed_by(view: ExpenseView) -> dict[str, int]:
  """The split lines keyed by user id."""
  return {split.user_id: split.amount_cents for split in view.splits}


class TestEqualSplit:
  def test_divides_the_total_between_the_participants(
    self, use_case, an_equal_split, alice: UserId, bob: UserId
  ):
    view = use_case.execute(an_equal_split())

    assert owed_by(view) == {str(alice): 5_000, str(bob): 5_000}

  def test_leftover_cents_go_to_the_earliest_participants(
    self, use_case, an_equal_split, alice: UserId, bob: UserId, carol: UserId
  ):
    view = use_case.execute(
      an_equal_split(
        total_cents=10_001, participants_ids=[str(alice), str(bob), str(carol)]
      )
    )

    assert owed_by(view) == {str(alice): 3_334, str(bob): 3_334, str(carol): 3_333}
    assert sum(owed_by(view).values()) == 10_001

  def test_the_payer_need_not_share_the_cost(
    self, use_case, an_equal_split, alice: UserId, bob: UserId, carol: UserId
  ):
    view = use_case.execute(
      an_equal_split(paid_by=str(alice), participants_ids=[str(bob), str(carol)])
    )

    assert owed_by(view) == {str(bob): 5_000, str(carol): 5_000}
    assert view.paid_by == str(alice)


class TestExactSplit:
  def test_uses_the_amounts_given(self, use_case, an_equal_split, alice: UserId, bob: UserId):
    view = use_case.execute(
      an_equal_split(
        split_type="exact",
        exact_amounts_cents={str(alice): 7_000, str(bob): 3_000},
      )
    )

    assert owed_by(view) == {str(alice): 7_000, str(bob): 3_000}

  def test_amounts_that_miss_the_total_are_rejected(
    self, use_case, expenses, an_equal_split, alice: UserId, bob: UserId
  ):
    with pytest.raises(InvalidSplitStrategyError, match="does not match the specified total"):
      use_case.execute(
        an_equal_split(
          split_type="exact",
          exact_amounts_cents={str(alice): 7_000, str(bob): 2_000},
        )
      )

    assert expenses.saved == []

  def test_amounts_for_the_wrong_people_are_rejected(
    self, use_case, an_equal_split, alice: UserId, bob: UserId, carol: UserId
  ):
    with pytest.raises(InvalidSplitStrategyError, match="do not match the specified amounts"):
      use_case.execute(
        an_equal_split(
          split_type="exact",
          exact_amounts_cents={str(alice): 5_000, str(carol): 5_000},
        )
      )

  def test_an_exact_split_without_amounts_is_rejected(self, use_case, an_equal_split):
    with pytest.raises(ValueError, match="exact_amounts_cents is required"):
      use_case.execute(an_equal_split(split_type="exact"))


class TestPercentageSplit:
  def test_applies_the_percentages(self, use_case, an_equal_split, alice: UserId, bob: UserId):
    view = use_case.execute(
      an_equal_split(
        split_type="percentage",
        percentages={str(alice): 70.0, str(bob): 30.0},
      )
    )

    assert owed_by(view) == {str(alice): 7_000, str(bob): 3_000}

  def test_fractional_cents_still_add_up_to_the_total(
    self, use_case, an_equal_split, alice: UserId, bob: UserId, carol: UserId
  ):
    view = use_case.execute(
      an_equal_split(
        total_cents=1_000,
        participants_ids=[str(alice), str(bob), str(carol)],
        split_type="percentage",
        percentages={str(alice): 33.33, str(bob): 33.33, str(carol): 33.34},
      )
    )

    assert sum(owed_by(view).values()) == 1_000

  def test_percentages_that_miss_a_hundred_are_rejected(
    self, use_case, expenses, an_equal_split, alice: UserId, bob: UserId
  ):
    with pytest.raises(InvalidSplitStrategyError, match="must sum to 100"):
      use_case.execute(
        an_equal_split(
          split_type="percentage",
          percentages={str(alice): 60.0, str(bob): 30.0},
        )
      )

    assert expenses.saved == []

  def test_percentages_for_the_wrong_people_are_rejected(
    self, use_case, an_equal_split, alice: UserId, carol: UserId
  ):
    with pytest.raises(InvalidSplitStrategyError, match="do not match the specified percentages"):
      use_case.execute(
        an_equal_split(
          split_type="percentage",
          percentages={str(alice): 50.0, str(carol): 50.0},
        )
      )

  def test_a_percentage_split_without_percentages_is_rejected(self, use_case, an_equal_split):
    with pytest.raises(ValueError, match="percentages is required"):
      use_case.execute(an_equal_split(split_type="percentage"))


class TestSplitType:
  @pytest.mark.parametrize("unknown", ["", "even", "EQUAL", "half"])
  def test_an_unknown_split_type_is_rejected(self, use_case, an_equal_split, unknown: str):
    with pytest.raises(ValueError, match="Unknown split_type"):
      use_case.execute(an_equal_split(split_type=unknown))

  def test_an_unknown_split_type_writes_nothing(self, use_case, expenses, an_equal_split):
    with pytest.raises(ValueError):
      use_case.execute(an_equal_split(split_type="even"))

    assert expenses.saved == []


class TestTheView:
  def test_describes_the_expense_it_created(
    self, use_case, an_equal_split, group_id: GroupId, alice: UserId
  ):
    view = use_case.execute(an_equal_split())

    assert view.group_id == str(group_id)
    assert view.description == "Dinner"
    assert view.total_cents == 10_000
    assert view.paid_by == str(alice)
    assert view.deleted is False
    assert view.created_at is not None

  def test_the_expense_and_its_splits_share_one_currency(self, use_case, an_equal_split):
    """A split is a share of the total, so it can never be denominated differently."""
    view = use_case.execute(an_equal_split(currency="USD"))

    assert view.currency == "USD"
    assert {split.currency for split in view.splits} == {"USD"}

  def test_is_immutable(self, use_case, an_equal_split):
    view = use_case.execute(an_equal_split())

    with pytest.raises(Exception):
      view.description = "Renamed"


class TestCurrency:
  """`currency` is a required input field, but an empty one falls back to the domain default."""

  def test_an_explicit_currency_is_honored(self, use_case, an_equal_split):
    view = use_case.execute(an_equal_split(currency="USD"))

    assert view.currency == "USD"

  def test_an_empty_currency_falls_back_to_the_domain_default(self, use_case, an_equal_split):
    view = use_case.execute(an_equal_split(currency=""))

    assert view.currency == CURRENCY

  def test_a_whitespace_only_currency_falls_back_to_the_domain_default(
    self, use_case, an_equal_split
  ):
    """Whitespace is not a currency code, so it counts as absent rather than as three
    characters that happen to pass a length check."""
    view = use_case.execute(an_equal_split(currency="   "))

    assert view.currency == CURRENCY

  def test_a_currency_that_is_not_letters_is_rejected(self, use_case, an_equal_split):
    with pytest.raises(ValueError, match="Currency must be a 3-letter ISO code"):
      use_case.execute(an_equal_split(currency="1 2"))

  def test_a_missing_currency_falls_back_to_the_domain_default(self, use_case, an_equal_split):
    """`currency` is annotated `str`, but `None` is what an omitted request field looks like."""
    view = use_case.execute(an_equal_split(currency=None))

    assert view.currency == CURRENCY

  @pytest.mark.parametrize("malformed", ["US", "PHPX", "peso"], ids=["short", "long", "word"])
  def test_a_currency_that_is_not_a_three_letter_code_is_rejected(
    self, use_case, an_equal_split, malformed: str
  ):
    with pytest.raises(ValueError, match="Currency must be a 3-letter ISO code"):
      use_case.execute(an_equal_split(currency=malformed))

  def test_a_rejected_currency_writes_nothing(self, use_case, expenses, an_equal_split):
    with pytest.raises(ValueError):
      use_case.execute(an_equal_split(currency="US"))

    assert expenses.saved == []

  def test_the_currency_is_required(self, group_id: GroupId, alice: UserId, bob: UserId):
    """It has no default, so a caller cannot forget to say what they spent."""
    with pytest.raises(TypeError, match="currency"):
      CreateExpenseInput(
        group_id=str(group_id),
        description="Dinner",
        total_cents=10_000,
        paid_by=str(alice),
        participants_ids=[str(alice), str(bob)],
        split_type="equal",
      )


class TestPersistence:
  def test_saves_the_expense_once(self, use_case, expenses, an_equal_split):
    use_case.execute(an_equal_split())

    assert len(expenses.saved) == 1

  def test_the_saved_expense_is_the_one_returned(
    self, use_case, expenses, an_equal_split, group_id: GroupId
  ):
    view = use_case.execute(an_equal_split())

    stored = expenses.get_for_group(group_id)
    assert [str(expense.id) for expense in stored] == [view.id]

  def test_each_expense_gets_its_own_id(self, use_case, an_equal_split):
    first = use_case.execute(an_equal_split())
    second = use_case.execute(an_equal_split())

    assert first.id != second.id

  def test_expenses_accumulate_in_the_group(
    self, use_case, expenses, an_equal_split, group_id: GroupId
  ):
    use_case.execute(an_equal_split())
    use_case.execute(an_equal_split(description="Breakfast"))

    assert len(expenses.get_for_group(group_id)) == 2

  def test_creating_an_expense_does_not_touch_the_group(self, use_case, groups, an_equal_split):
    use_case.execute(an_equal_split())

    assert groups.saved == []


class TestMembership:
  def test_a_participant_outside_the_group_is_refused(
    self, use_case, an_equal_split, alice: UserId, dave: UserId
  ):
    with pytest.raises(NotAuthorizedError, match="is not a member of the group"):
      use_case.execute(an_equal_split(participants_ids=[str(alice), str(dave)]))

  def test_a_payer_outside_the_group_is_refused(
    self, use_case, an_equal_split, alice: UserId, bob: UserId, dave: UserId
  ):
    with pytest.raises(NotAuthorizedError, match=str(dave)):
      use_case.execute(
        an_equal_split(paid_by=str(dave), participants_ids=[str(alice), str(bob)])
      )

  def test_an_outsider_writes_nothing(self, use_case, expenses, an_equal_split, alice, dave):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(an_equal_split(participants_ids=[str(alice), str(dave)]))

    assert expenses.saved == []


class TestMissingGroup:
  def test_an_unknown_group_is_reported_as_not_found(self, use_case, an_equal_split):
    with pytest.raises(NotFoundError, match="not found"):
      use_case.execute(an_equal_split(group_id=str(id_for(GroupId, "unknown-group"))))

  def test_an_unknown_group_writes_nothing(self, use_case, expenses, an_equal_split):
    with pytest.raises(NotFoundError):
      use_case.execute(an_equal_split(group_id=str(id_for(GroupId, "unknown-group"))))

    assert expenses.saved == []


class TestInvalidExpense:
  @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "blank"])
  def test_a_blank_description_is_rejected(self, use_case, an_equal_split, blank: str):
    with pytest.raises(InvalidExpenseError, match="description cannot be empty"):
      use_case.execute(an_equal_split(description=blank))

  @pytest.mark.parametrize("amount", [0, -1, -10_000], ids=["zero", "negative-cent", "negative"])
  def test_a_non_positive_total_is_rejected(self, use_case, an_equal_split, amount: int):
    with pytest.raises(InvalidExpenseError, match="total must be positive"):
      use_case.execute(an_equal_split(total_cents=amount))

  def test_an_expense_with_no_participants_is_rejected(self, use_case, an_equal_split):
    with pytest.raises(InvalidSplitStrategyError, match="No participants"):
      use_case.execute(an_equal_split(participants_ids=[]))

  def test_a_rejected_expense_writes_nothing(self, use_case, expenses, an_equal_split):
    with pytest.raises(InvalidExpenseError):
      use_case.execute(an_equal_split(description=""))

    assert expenses.saved == []


class TestUntrustedInput:
  """Every field arrives as raw request data, so the guards belong to the use case."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, an_equal_split, malformed):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(an_equal_split(group_id=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "alice", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_payer_id_that_is_not_a_uuid_is_rejected(self, use_case, an_equal_split, malformed):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(an_equal_split(paid_by=malformed))

  def test_a_participant_id_that_is_not_a_uuid_is_rejected(
    self, use_case, an_equal_split, alice: UserId
  ):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(an_equal_split(participants_ids=[str(alice), "bob"]))

  def test_a_total_that_is_not_an_integer_is_rejected(self, use_case, an_equal_split):
    with pytest.raises(ValueError, match="Money amount must be an integer"):
      use_case.execute(an_equal_split(total_cents="10000"))

  def test_malformed_input_writes_nothing(self, use_case, expenses, an_equal_split):
    with pytest.raises(ValueError):
      use_case.execute(an_equal_split(group_id="not-a-uuid"))

    assert expenses.saved == []


class TestInput:
  def test_the_input_is_immutable(self, an_equal_split):
    input_data = an_equal_split()

    with pytest.raises(Exception):
      input_data.description = "Renamed"


class TestKnownGaps:
  """Behavior the use case currently allows that is worth a second look.

  Each test asserts what happens *today*; fixing the gap should break it on purpose.
  """

  def test_a_currency_code_is_not_upper_cased(self, use_case, an_equal_split):
    """GAP: `balance_dto.CurrencyCode` upper-cases via `AfterValidator(str.upper)`, but
    `ExpenseView.currency` is a plain `str`. The same money reads as "usd" on an expense and
    "USD" on a balance, and `Money._check_currency` compares exactly."""
    view = use_case.execute(an_equal_split(currency="usd"))

    assert view.currency == "usd"


class TestEvents:
  """A new expense moves everyone's balance, so whatever recomputes or notifies has to hear
  about it — the entity records the event, but only `execute` gets it to a subscriber."""

  def test_publishes_that_the_expense_was_created(self, use_case, publisher, an_equal_split):
    use_case.execute(an_equal_split())

    assert publisher.types() == ["ExpenseCreated"]

  def test_the_published_event_describes_the_expense(
    self, use_case, publisher, an_equal_split, group_id: GroupId, alice: UserId
  ):
    view = use_case.execute(an_equal_split())

    event = publisher.published[0]
    assert isinstance(event, ExpenseCreated)
    assert event.group_id == group_id
    assert str(event.expense_id) == view.id
    assert event.created_by == alice
    assert event.amount == Money(10_000, CURRENCY)
    assert event.description == "Dinner"

  def test_the_event_credits_the_payer_not_the_caller(
    self, use_case, publisher, an_equal_split, bob: UserId
  ):
    """`created_by` is taken from `paid_by`, so the event names whoever footed the bill."""
    use_case.execute(an_equal_split(paid_by=str(bob)))

    assert publisher.published[0].created_by == bob

  def test_publishes_once_per_call(self, use_case, publisher, an_equal_split):
    """One `publish` per operation, so a subscriber sees one batch rather than a trickle."""
    use_case.execute(an_equal_split())

    assert len(publisher.batches) == 1
    assert len(publisher.batches[0]) == 1

  def test_publishes_after_the_write(self, groups, an_equal_split):
    """A subscriber that reads the ledger back must already find the expense there, so the
    save has to land first."""
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

    use_case = CreateExpenseUseCase(groups, NotingRepository(), NotingPublisher())

    use_case.execute(an_equal_split())

    assert timeline == ["save", "publish"]

  def test_each_call_publishes_only_its_own_event(self, use_case, publisher, an_equal_split):
    """A second expense must not re-announce the first — each aggregate carries its own."""
    first = use_case.execute(an_equal_split())
    second = use_case.execute(an_equal_split(description="Breakfast"))

    assert [len(batch) for batch in publisher.batches] == [1, 1]
    assert [str(event.expense_id) for event in publisher.published] == [first.id, second.id]

  def test_the_expense_keeps_no_events_after_publishing(
    self, use_case, expenses, an_equal_split, group_id: GroupId
  ):
    """`pull_events` drains the aggregate, so nothing can be published a second time."""
    view = use_case.execute(an_equal_split())

    stored = expenses.get_by_id(group_id, ExpenseId(view.id))
    assert stored.pull_events() == []


class TestNothingIsPublishedOnFailure:
  def test_an_unknown_group_publishes_nothing(self, use_case, publisher, an_equal_split):
    with pytest.raises(NotFoundError):
      use_case.execute(an_equal_split(group_id=str(id_for(GroupId, "no-such-group"))))

    assert publisher.published == []
    assert publisher.batches == []

  def test_a_non_member_publishes_nothing(self, use_case, publisher, an_equal_split, dave: UserId):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(an_equal_split(participants_ids=[str(dave)]))

    assert publisher.published == []

  def test_an_invalid_split_publishes_nothing(
    self, use_case, publisher, an_equal_split, alice: UserId, bob: UserId
  ):
    """The entity raises before recording, and the use case never reaches `publish`."""
    with pytest.raises((InvalidSplitStrategyError, InvalidExpenseError)):
      use_case.execute(
        an_equal_split(
          split_type="exact",
          exact_amounts_cents={str(alice): 1_000, str(bob): 1_000},
        )
      )

    assert publisher.published == []

  def test_a_malformed_id_publishes_nothing(self, use_case, publisher, an_equal_split):
    with pytest.raises(ValueError):
      use_case.execute(an_equal_split(group_id="not-a-uuid"))

    assert publisher.published == []

  def test_a_failed_create_does_not_republish_an_earlier_one(
    self, use_case, publisher, an_equal_split, dave: UserId
  ):
    use_case.execute(an_equal_split())

    with pytest.raises(NotAuthorizedError):
      use_case.execute(an_equal_split(participants_ids=[str(dave)]))

    assert publisher.types() == ["ExpenseCreated"]
