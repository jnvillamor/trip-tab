"""Simplified debts are derived, never stored: the use case reads a group's ledger, hands it to
the `BalanceEngine`, feeds the net balances to the `SettlementSuggester`, and maps the result to
views. Three moving parts, no writes.

These tests pin that wiring — what gets read, how the group scopes it, how the domain result is
mapped — not the netting or the pairing arithmetic, which have their own tests.
"""

from __future__ import annotations

import pytest

from application.dto.balance_dto import SuggestedPaymentView
from application.use_cases.expenses.get_simplified_debts import (
  GetSimplifiedDebtsInput,
  GetSimplifiedDebtsUseCase,
)
from domain.value_objects.ids import GroupId, UserId
from domain.value_objects.money import CurrencyMismatchError
from tests.builders import CURRENCY, id_for, make_expense, make_settlement, money
from tests.fakes import InMemoryExpenseRepository, InMemorySettlementRepository


@pytest.fixture
def expenses() -> InMemoryExpenseRepository:
  return InMemoryExpenseRepository()


@pytest.fixture
def settlements() -> InMemorySettlementRepository:
  return InMemorySettlementRepository()


@pytest.fixture
def use_case(
  expenses: InMemoryExpenseRepository, settlements: InMemorySettlementRepository
) -> GetSimplifiedDebtsUseCase:
  return GetSimplifiedDebtsUseCase(expenses, settlements)


@pytest.fixture
def a_request(group_id: GroupId):
  def build(**overrides) -> GetSimplifiedDebtsInput:
    return GetSimplifiedDebtsInput(**{"group_id": str(group_id), **overrides})

  return build


@pytest.fixture
def dinner(group_id: GroupId, alice: UserId, bob: UserId, carol: UserId):
  """90.00 paid by alice, split three ways — so bob and carol each owe her 30.00."""
  return make_expense(
    group_id=group_id,
    description="Dinner",
    total=money(9_000),
    paid_by=alice,
    participants=[alice, bob, carol],
  )


def payments_of(views: list[SuggestedPaymentView]) -> dict[tuple[str, str], int]:
  """The suggested payments keyed by `(payer, payee)`, so a test does not depend on order."""
  return {(view.from_user, view.to_user): view.amount_cents for view in views}


class TestEmptyLedger:
  def test_a_group_with_no_activity_owes_nothing(self, use_case, a_request):
    assert use_case.execute(a_request()) == []

  def test_a_group_whose_only_expense_was_deleted_owes_nothing(
    self, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """Deleted expenses are skipped by the engine, so they cannot produce a payment."""
    expenses = InMemoryExpenseRepository(
      [
        make_expense(
          group_id=group_id,
          total=money(6_000),
          paid_by=alice,
          participants=[alice, bob],
          deleted=True,
        )
      ]
    )

    assert GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request()) == []


class TestSuggestingPayments:
  def test_each_debtor_is_told_to_pay_the_person_who_paid(
    self, expenses, settlements, a_request, dinner, alice: UserId, bob: UserId, carol: UserId
  ):
    expenses.save(dinner)

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert payments_of(views) == {
      (str(bob), str(alice)): 3_000,
      (str(carol), str(alice)): 3_000,
    }

  def test_a_debt_between_two_people_is_one_payment(
    self, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses = InMemoryExpenseRepository(
      [make_expense(group_id=group_id, total=money(6_000), paid_by=alice, participants=[alice, bob])]
    )

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert payments_of(views) == {(str(bob), str(alice)): 3_000}

  def test_debts_that_cancel_out_produce_no_payments(
    self, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """Each paid for the other in equal measure, so there is nothing left to move."""
    expenses = InMemoryExpenseRepository(
      [
        make_expense(group_id=group_id, total=money(6_000), paid_by=alice, participants=[alice, bob]),
        make_expense(group_id=group_id, total=money(6_000), paid_by=bob, participants=[alice, bob]),
      ]
    )

    assert GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request()) == []

  def test_the_payments_never_outnumber_the_people_involved(
    self, expenses, settlements, a_request, dinner
  ):
    """The suggester's n-1 bound survives the trip through the use case."""
    expenses.save(dinner)

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert len(views) <= 2


class TestSettlementsAreTakenIntoAccount:
  def test_a_settled_debt_disappears_from_the_suggestions(
    self, expenses, a_request, dinner, group_id: GroupId, alice: UserId, bob: UserId, carol: UserId
  ):
    expenses.save(dinner)
    settlements = InMemorySettlementRepository(
      [make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(3_000))]
    )

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert payments_of(views) == {(str(carol), str(alice)): 3_000}

  def test_a_fully_settled_group_owes_nothing(
    self, expenses, a_request, dinner, group_id: GroupId, alice: UserId, bob: UserId, carol: UserId
  ):
    expenses.save(dinner)
    settlements = InMemorySettlementRepository(
      [
        make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(3_000)),
        make_settlement(group_id=group_id, from_user=carol, to_user=alice, amount=money(3_000)),
      ]
    )

    assert GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request()) == []

  def test_overpaying_turns_the_payer_into_a_creditor(
    self, expenses, a_request, dinner, group_id: GroupId, alice: UserId, bob: UserId, carol: UserId
  ):
    """bob owed 3000 and paid 5000, so the extra 2000 is now owed back to him."""
    expenses.save(dinner)
    settlements = InMemorySettlementRepository(
      [make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000))]
    )

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert payments_of(views) == {
      (str(carol), str(bob)): 2_000,
      (str(carol), str(alice)): 1_000,
    }


class TestGroupScoping:
  def test_another_group_s_ledger_is_not_included(
    self, settlements, a_request, alice: UserId, bob: UserId
  ):
    other_group = id_for(GroupId, "boracay-trip")
    expenses = InMemoryExpenseRepository(
      [
        make_expense(
          group_id=other_group, total=money(6_000), paid_by=alice, participants=[alice, bob]
        )
      ]
    )

    assert GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request()) == []

  def test_both_ledgers_are_read_for_the_requested_group(
    self, use_case, expenses, settlements, a_request, group_id: GroupId
  ):
    use_case.execute(a_request())

    assert expenses.queried_groups == [group_id]
    assert settlements.queried_groups == [group_id]

  def test_an_unknown_group_reads_an_empty_ledger(
    self, use_case, expenses, settlements, a_request
  ):
    unknown = id_for(GroupId, "no-such-group")

    use_case.execute(a_request(group_id=str(unknown)))

    assert expenses.queried_groups == [unknown]
    assert settlements.queried_groups == [unknown]


class TestCurrency:
  def test_the_payments_are_denominated_in_the_ledger_s_currency(
    self, expenses, settlements, a_request, dinner
  ):
    expenses.save(dinner)

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert {view.currency for view in views} == {CURRENCY}

  def test_a_foreign_currency_ledger_is_reported_in_that_currency(
    self, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses = InMemoryExpenseRepository(
      [
        make_expense(
          group_id=group_id, total=money(6_000, "USD"), paid_by=alice, participants=[alice, bob]
        )
      ]
    )

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert [view.currency for view in views] == ["USD"]

  def test_the_currency_code_is_upper_cased_by_the_view(
    self, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """`SuggestedPaymentView.currency` is a `CurrencyCode`, which normalizes case — unlike
    `ExpenseView.currency`, which reports whatever the expense was booked in."""
    expenses = InMemoryExpenseRepository(
      [
        make_expense(
          group_id=group_id, total=money(6_000, "usd"), paid_by=alice, participants=[alice, bob]
        )
      ]
    )

    views = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert [view.currency for view in views] == ["USD"]

  def test_a_ledger_in_two_currencies_cannot_be_simplified(
    self, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """The engine refuses to net across currencies, so the request fails rather than guess."""
    expenses = InMemoryExpenseRepository(
      [
        make_expense(
          group_id=group_id, total=money(6_000, "USD"), paid_by=alice, participants=[alice, bob]
        ),
        make_expense(
          group_id=group_id, total=money(6_000, "PHP"), paid_by=bob, participants=[alice, bob]
        ),
      ]
    )

    with pytest.raises(CurrencyMismatchError, match="mixed currencies"):
      GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())


class TestReadOnly:
  def test_asking_for_debts_writes_nothing(
    self, expenses, settlements, a_request, dinner
  ):
    expenses.save(dinner)
    expenses.saved.clear()

    GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())

    assert expenses.saved == []
    assert settlements.saved == []

  def test_asking_twice_gives_the_same_answer(self, expenses, settlements, a_request, dinner):
    expenses.save(dinner)
    use_case = GetSimplifiedDebtsUseCase(expenses, settlements)

    assert payments_of(use_case.execute(a_request())) == payments_of(
      use_case.execute(a_request())
    )


class TestTheView:
  def test_describes_who_pays_whom_and_how_much(
    self, expenses, settlements, a_request, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(6_000), paid_by=alice, participants=[alice, bob])
    )

    view = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())[0]

    assert isinstance(view, SuggestedPaymentView)
    assert view.from_user == str(bob)
    assert view.to_user == str(alice)
    assert view.amount_cents == 3_000
    assert view.currency == CURRENCY

  def test_the_ids_are_plain_strings(
    self, expenses, settlements, a_request, dinner
  ):
    expenses.save(dinner)

    view = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())[0]

    assert isinstance(view.from_user, str)
    assert isinstance(view.to_user, str)

  def test_is_immutable(self, expenses, settlements, a_request, dinner):
    expenses.save(dinner)

    view = GetSimplifiedDebtsUseCase(expenses, settlements).execute(a_request())[0]

    with pytest.raises(Exception):
      view.amount_cents = 1


class TestUntrustedInput:
  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, a_request, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(a_request(group_id=malformed))

  def test_a_malformed_group_id_reads_nothing(self, use_case, expenses, settlements, a_request):
    """The id is parsed before either repository is touched."""
    with pytest.raises(ValueError):
      use_case.execute(a_request(group_id="not-a-uuid"))

    assert expenses.queried_groups == []
    assert settlements.queried_groups == []


class TestInput:
  def test_the_input_is_immutable(self, a_request):
    input_data = a_request()

    with pytest.raises(Exception):
      input_data.group_id = str(id_for(GroupId, "elsewhere"))


class TestKnownGaps:
  """Behavior worth a second look. Each test asserts what happens *today*; fixing the gap
  should break it on purpose.
  """

  def test_an_unknown_group_is_reported_as_settled_up(self, use_case, a_request):
    """GAP: the use case takes no group repository and never checks that the group exists, so
    a wrong or deleted group id is indistinguishable from a group that owes nothing.

    `NotFoundError` is imported in the module and never raised, which suggests the check was
    intended. Compare `get_group_balances`, which has the same hole.
    """
    views = use_case.execute(a_request(group_id=str(id_for(GroupId, "no-such-group"))))

    assert views == []
