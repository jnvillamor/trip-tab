"""Removal is gated on the group's ledger: the use case derives the member's balance from
the group's expenses and settlements and lets the entity decide. These tests pin the gate,
the read/write behavior around it, and what happens when the ledger says no.
"""

from __future__ import annotations

import pytest

from application.exceptions import NotFoundError
from application.use_cases.group.remove_group_member import (
  RemoveGroupMemberInput,
  RemoveGroupMemberUseCase,
)
from domain.entities.group import GroupMembershipError
from domain.events.group_events import MemberRemoved
from domain.value_objects.ids import GroupId, UserId
from domain.value_objects.money import CurrencyMismatchError, Money
from domain.value_objects.split_strategy import SplitLine
from tests.builders import id_for, make_expense, make_group, make_settlement, money, split_evenly
from tests.fakes import (
  InMemoryEventPublisher,
  InMemoryExpenseRepository,
  InMemoryGroupRepository,
  InMemorySettlementRepository,
)


@pytest.fixture
def groups(alice: UserId, bob: UserId, group_id: GroupId) -> InMemoryGroupRepository:
  return InMemoryGroupRepository(
    [make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob])]
  )


@pytest.fixture
def expenses() -> InMemoryExpenseRepository:
  return InMemoryExpenseRepository()


@pytest.fixture
def settlements() -> InMemorySettlementRepository:
  return InMemorySettlementRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
  return InMemoryEventPublisher()


@pytest.fixture
def use_case(
  groups: InMemoryGroupRepository,
  expenses: InMemoryExpenseRepository,
  settlements: InMemorySettlementRepository,
  publisher: InMemoryEventPublisher,
) -> RemoveGroupMemberUseCase:
  return RemoveGroupMemberUseCase(groups, expenses, settlements, publisher)


def owes(*, group_id: GroupId, debtor: UserId, creditor: UserId, cents: int = 5_000):
  """An expense the creditor paid and only the debtor owes, so the balance is unambiguous."""
  total = money(cents)
  return make_expense(
    group_id=group_id,
    total=total,
    paid_by=creditor,
    splits=[SplitLine(user_id=debtor, owed=total)],
  )


class TestSettledMember:
  def test_removes_a_member_with_no_activity(
    self, use_case, group_id: GroupId, alice: UserId, bob: UserId
  ):
    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert [member.user_id for member in view.members] == [str(alice)]

  def test_persists_the_removal(self, use_case, groups, group_id: GroupId, alice, bob: UserId):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    stored = groups.get_by_id(group_id)
    assert stored is not None
    assert stored.member_ids() == [alice]

  def test_saves_exactly_once(self, use_case, groups, group_id: GroupId, bob: UserId):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert len(groups.saved) == 1

  def test_the_view_still_describes_the_same_group(
    self, use_case, group_id: GroupId, alice: UserId, bob: UserId
  ):
    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert view.id == str(group_id)
    assert view.name == "Palawan Trip"
    assert view.created_by == str(alice)

  def test_removes_a_member_who_has_settled_up(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))
    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000))
    )

    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert [member.user_id for member in view.members] == [str(alice)]

  def test_removes_a_member_whose_only_expense_was_deleted(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expense = owes(group_id=group_id, debtor=bob, creditor=alice)
    expense.mark_deleted()
    expenses.save(expense)

    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert [member.user_id for member in view.members] == [str(alice)]

  def test_the_creator_can_be_removed_when_settled(
    self, use_case, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """The entity applies no special rule to the creator, and neither does the use case."""
    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(alice)))

    assert [member.user_id for member in view.members] == [str(bob)]


class TestUnsettledMember:
  def test_a_debtor_cannot_be_removed(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))

    with pytest.raises(GroupMembershipError, match="unsettled balances"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

  def test_a_creditor_cannot_be_removed_either(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """Being owed money is just as unsettled as owing it."""
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))

    with pytest.raises(GroupMembershipError, match="unsettled balances"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(alice)))

  def test_a_partial_settlement_is_not_enough(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))
    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(2_000))
    )

    with pytest.raises(GroupMembershipError, match="unsettled balances"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

  def test_a_rejected_removal_leaves_the_stored_group_untouched(
    self, use_case, groups, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))

    with pytest.raises(GroupMembershipError):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert groups.saved == []
    assert groups.get_by_id(group_id).member_ids() == [alice, bob]

  def test_removal_succeeds_once_the_debt_is_settled(
    self, use_case, expenses, settlements, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))

    with pytest.raises(GroupMembershipError):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    settlements.save(
      make_settlement(group_id=group_id, from_user=bob, to_user=alice, amount=money(5_000))
    )
    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert [member.user_id for member in view.members] == [str(alice)]


class TestNonMember:
  def test_removing_someone_who_never_joined_is_rejected(
    self, use_case, group_id: GroupId, carol: UserId
  ):
    with pytest.raises(GroupMembershipError, match="not a memeber"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(carol)))

  def test_membership_is_checked_before_the_balance(
    self, use_case, expenses, group_id: GroupId, alice: UserId, carol: UserId
  ):
    """An outsider with a debt in the ledger is turned away as an outsider, not as a debtor."""
    expenses.save(owes(group_id=group_id, debtor=carol, creditor=alice))

    with pytest.raises(GroupMembershipError, match="not a memeber"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(carol)))

  def test_the_second_removal_of_the_same_member_is_rejected(
    self, use_case, groups, group_id: GroupId, alice: UserId, bob: UserId
  ):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    with pytest.raises(GroupMembershipError, match="not a memeber"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert len(groups.saved) == 1
    assert groups.get_by_id(group_id).member_ids() == [alice]


class TestMissingGroup:
  def test_an_unknown_group_is_reported_as_not_found(self, use_case, bob: UserId):
    with pytest.raises(NotFoundError, match="not found"):
      use_case.execute(
        RemoveGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob))
      )

  def test_an_unknown_group_never_reads_the_ledger(self, use_case, expenses, settlements, bob):
    with pytest.raises(NotFoundError):
      use_case.execute(
        RemoveGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob))
      )

    assert expenses.queried_groups == []
    assert settlements.queried_groups == []

  def test_an_unknown_group_writes_nothing(self, use_case, groups, bob: UserId):
    with pytest.raises(NotFoundError):
      use_case.execute(
        RemoveGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob))
      )

    assert groups.saved == []


class TestLedgerScoping:
  def test_the_ledger_is_read_for_the_group_being_changed(
    self, use_case, expenses, settlements, group_id: GroupId, bob: UserId
  ):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert expenses.queried_groups == [group_id]
    assert settlements.queried_groups == [group_id]

  def test_a_debt_in_another_group_does_not_block_removal(
    self, use_case, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    expenses.save(
      owes(group_id=id_for(GroupId, "other-group"), debtor=bob, creditor=alice)
    )

    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert [member.user_id for member in view.members] == [str(alice)]


class TestBrokenLedger:
  def test_a_mixed_currency_ledger_blocks_removal(
    self, use_case, groups, expenses, group_id: GroupId, alice: UserId, bob: UserId
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
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert groups.saved == []


class TestNetOnlyGate:
  def test_a_ring_of_debts_that_nets_to_zero_lets_a_member_leave(
    self, use_case, groups, expenses, group_id: GroupId, alice: UserId, bob: UserId, carol: UserId
  ):
    """The gate reads `compute_net_balance` only. In a ring — bob owes alice, carol owes bob,
    alice owes carol — every net balance is zero while three pairwise debts of 5,000 remain,
    so alice is allowed to leave still owing carol.
    """
    groups.save(make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob, carol]))
    groups.saved.clear()
    for debtor, creditor in ((bob, alice), (carol, bob), (alice, carol)):
      expenses.save(owes(group_id=group_id, debtor=debtor, creditor=creditor))

    view = use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(alice)))

    assert [member.user_id for member in view.members] == [str(bob), str(carol)]


class TestUntrustedInput:
  """Both ids arrive as raw strings, as they would from an HTTP request."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, bob: UserId, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(RemoveGroupMemberInput(group_id=malformed, user_id=str(bob)))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "bob", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_user_id_that_is_not_a_uuid_is_rejected(
    self, use_case, group_id: GroupId, malformed: str
  ):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=malformed))

  def test_a_malformed_id_touches_nothing(self, use_case, groups, expenses, settlements, bob):
    with pytest.raises(ValueError):
      use_case.execute(RemoveGroupMemberInput(group_id="not-a-uuid", user_id=str(bob)))

    assert groups.saved == []
    assert expenses.queried_groups == []
    assert settlements.queried_groups == []


class TestEvents:
  """A departure has to reach whatever recomputes a group's roster, so the use case hands the
  recorded event on — the entity records it, but only `execute` gets it to a subscriber."""

  def test_publishes_that_the_member_was_removed(self, use_case, publisher, group_id, bob):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert publisher.types() == ["MemberRemoved"]

  def test_the_published_event_names_the_group_and_the_member(
    self, use_case, publisher, group_id: GroupId, bob: UserId
  ):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    event = publisher.published[0]
    assert isinstance(event, MemberRemoved)
    assert (event.group_id, event.member_id) == (group_id, bob)

  def test_publishes_once_per_call(self, use_case, publisher, group_id: GroupId, bob: UserId):
    """One `publish` per operation, so a subscriber sees one batch rather than a trickle."""
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert len(publisher.batches) == 1
    assert len(publisher.batches[0]) == 1

  def test_publishes_after_the_write(self, expenses, settlements, group_id, alice, bob):
    """A subscriber that reads the group back must already find the member gone, so the save
    has to land first."""
    timeline: list[str] = []

    class NotingRepository(InMemoryGroupRepository):
      def save(self, group):
        timeline.append("save")
        super().save(group)

    class NotingPublisher(InMemoryEventPublisher):
      def publish(self, events):
        if events:
          timeline.append("publish")
        super().publish(events)

    noting_groups = NotingRepository(
      [make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob])]
    )
    use_case = RemoveGroupMemberUseCase(
      noting_groups, expenses, settlements, NotingPublisher()
    )

    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert timeline == ["save", "publish"]

  def test_the_group_keeps_no_events_after_publishing(
    self, use_case, groups, group_id: GroupId, bob: UserId
  ):
    """`pull_events` drains the aggregate, so nothing can be published a second time."""
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert groups.get_by_id(group_id).pull_events() == []


class TestNothingIsPublishedOnFailure:
  def test_an_unsettled_member_publishes_nothing(
    self, use_case, publisher, expenses, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """The entity raises before recording, and the use case never reaches `publish`."""
    expenses.save(owes(group_id=group_id, debtor=bob, creditor=alice))

    with pytest.raises(GroupMembershipError):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert publisher.published == []
    assert publisher.batches == []

  def test_a_non_member_publishes_nothing(self, use_case, publisher, group_id, carol: UserId):
    with pytest.raises(GroupMembershipError):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(carol)))

    assert publisher.published == []

  def test_an_unknown_group_publishes_nothing(self, use_case, publisher, bob: UserId):
    with pytest.raises(NotFoundError):
      use_case.execute(
        RemoveGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob))
      )

    assert publisher.published == []

  def test_a_malformed_id_publishes_nothing(self, use_case, publisher, bob: UserId):
    with pytest.raises(ValueError):
      use_case.execute(RemoveGroupMemberInput(group_id="not-a-uuid", user_id=str(bob)))

    assert publisher.published == []

  def test_a_failed_second_removal_does_not_republish_the_first(
    self, use_case, publisher, group_id: GroupId, bob: UserId
  ):
    use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    with pytest.raises(GroupMembershipError):
      use_case.execute(RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert publisher.types() == ["MemberRemoved"]


class TestInput:
  def test_the_input_is_immutable(self, group_id: GroupId, bob: UserId):
    input_data = RemoveGroupMemberInput(group_id=str(group_id), user_id=str(bob))

    with pytest.raises(Exception):
      input_data.user_id = "someone-else"
