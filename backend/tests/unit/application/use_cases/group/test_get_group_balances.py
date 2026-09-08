"""Balances are derived, never stored: the use case reads a group's ledger and hands the
`BalanceEngine`'s output to the caller as a view. These tests pin the wiring — id parsing,
what gets read, and how the domain result is mapped — not the arithmetic itself, which
belongs to the engine's own tests.
"""

from __future__ import annotations

import pytest

from application.dto.balance_dto import GroupBalancesView
from application.use_cases.group.get_group_balances import (
  GetGroupBalancesInput,
  GetGroupBalancesUseCase,
)
from domain.value_objects.ids import GroupId, UserId
from domain.value_objects.money import CurrencyMismatchError, Money
from tests.builders import id_for, make_expense, make_settlement, money, split_evenly
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
) -> GetGroupBalancesUseCase:
  return GetGroupBalancesUseCase(expenses, settlements)


def net_of(view: GroupBalancesView) -> dict[str, int]:
  """The net section keyed by user id, so a test does not depend on the engine's ordering."""
  return {balance.user_id: balance.amount_cents for balance in view.net}


def debts_of(view: GroupBalancesView) -> dict[tuple[str, str], int]:
  """The pairwise section keyed by `(debtor, creditor)`."""
  return {(debt.debtor, debt.creditor): debt.amount_cents for debt in view.pairwise}


class TestEmptyLedger:
  def test_a_group_with_no_activity_has_no_balances(self, use_case, group_id: GroupId):
    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert view.net == []
    assert view.pairwise == []

  def test_an_unknown_group_reads_as_an_empty_ledger(self, use_case):
    """No group repository is injected, so an id nobody has ever used is not an error."""
    unknown = id_for(GroupId, "unknown-group")

    view = use_case.execute(GetGroupBalancesInput(group_id=str(unknown)))

    assert view.net == []
    assert view.pairwise == []


class TestNetBalances:
  def test_a_single_expense_puts_the_payer_ahead(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert net_of(view) == {str(alice): 5_000, str(bob): -5_000}

  def test_the_ledger_currency_is_carried_into_the_view(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId, currency: str
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert {balance.currency for balance in view.net} == {currency}
    assert {debt.currency for debt in view.pairwise} == {currency}

  def test_balances_accumulate_across_expenses(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    for _ in range(2):
      expenses.save(
        make_expense(
          group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob]
        )
      )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert net_of(view) == {str(alice): 10_000, str(bob): -10_000}

  def test_a_deleted_expense_is_left_out(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(
        group_id=group_id,
        total=money(10_000),
        paid_by=alice,
        participants=[alice, bob],
        deleted=True,
      )
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert view.net == []
    assert view.pairwise == []

  def test_a_user_who_comes_out_even_is_omitted(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    for payer in (alice, bob):
      expenses.save(
        make_expense(
          group_id=group_id, total=money(10_000), paid_by=payer, participants=[alice, bob]
        )
      )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert view.net == []


class TestPairwiseBalances:
  def test_pairwise_names_the_debtor_and_the_creditor(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert debts_of(view) == {(str(bob), str(alice)): 5_000}

  def test_one_debt_per_pair(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId, carol: UserId
  ):
    expenses.save(
      make_expense(
        group_id=group_id, total=money(9_000), paid_by=alice, participants=[alice, bob, carol]
      )
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert debts_of(view) == {(str(bob), str(alice)): 3_000, (str(carol), str(alice)): 3_000}


class TestSettlements:
  def test_a_full_settlement_clears_the_ledger(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )
    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000))
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert view.net == []
    assert view.pairwise == []

  def test_a_partial_settlement_leaves_the_remainder(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )
    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(2_000))
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert net_of(view) == {str(alice): 3_000, str(bob): -3_000}
    assert debts_of(view) == {(str(bob), str(alice)): 3_000}

  def test_a_settlement_alone_creates_a_balance(
    self, use_case, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """Paying someone who is owed nothing leaves them owing the payer."""
    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000))
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert net_of(view) == {str(bob): 5_000, str(alice): -5_000}
    assert debts_of(view) == {(str(alice), str(bob)): 5_000}


class TestScoping:
  def test_another_groups_expenses_are_not_counted(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    other_group = id_for(GroupId, "other-group")
    expenses.save(
      make_expense(
        group_id=other_group, total=money(10_000), paid_by=alice, participants=[alice, bob]
      )
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert view.net == []
    assert view.pairwise == []

  def test_another_groups_settlements_are_not_counted(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )
    settlements.save(
      make_settlement(
        group_id=id_for(GroupId, "other-group"),
        from_user=bob,
        to_user=alice,
        amount=money(5_000),
      )
    )

    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert net_of(view) == {str(alice): 5_000, str(bob): -5_000}

  def test_both_repositories_are_read_with_the_parsed_group_id(
    self, use_case, expenses, settlements, group_id: GroupId
  ):
    use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert expenses.queried_groups == [group_id]
    assert settlements.queried_groups == [group_id]


class TestReadOnly:
  def test_reading_balances_writes_nothing(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      make_expense(group_id=group_id, total=money(10_000), paid_by=alice, participants=[alice, bob])
    )
    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(2_000))
    )
    expenses.saved.clear()
    settlements.saved.clear()

    use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    assert expenses.saved == []
    assert settlements.saved == []


class TestFailure:
  def test_a_ledger_mixing_currencies_is_rejected(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    for currency in ("PHP", "USD"):
      total = Money(10_000, currency)
      expenses.save(
        make_expense(
          group_id=group_id,
          total=total,
          paid_by=alice,
          splits=split_evenly(total, [alice, bob]),
        )
      )

    with pytest.raises(CurrencyMismatchError, match="mixed currencies"):
      use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))


class TestUntrustedInput:
  """The group id arrives as a raw string, as it would from an HTTP request."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(GetGroupBalancesInput(group_id=malformed))

  def test_a_malformed_id_reads_nothing(self, use_case, expenses, settlements):
    with pytest.raises(ValueError):
      use_case.execute(GetGroupBalancesInput(group_id="not-a-uuid"))

    assert expenses.queried_groups == []
    assert settlements.queried_groups == []


class TestOutput:
  def test_the_view_is_immutable(self, use_case, group_id: GroupId):
    view = use_case.execute(GetGroupBalancesInput(group_id=str(group_id)))

    with pytest.raises(Exception):
      view.net = []


class TestInput:
  def test_the_input_is_immutable(self, group_id: GroupId):
    input_data = GetGroupBalancesInput(group_id=str(group_id))

    with pytest.raises(Exception):
      input_data.group_id = "another-group"
