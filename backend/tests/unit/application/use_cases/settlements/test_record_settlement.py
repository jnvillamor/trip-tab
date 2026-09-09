"""Recording a settlement writes down that one member paid another back: ids are parsed,
both parties must belong to the group, and the domain refuses the two nonsense cases — paying
yourself, and paying a non-positive amount.

A settlement is a bare fact, not a calculation: the use case never looks at what anyone
actually owes, so nothing here consults expenses or balances. `TestKnownGaps` pins the
consequences of that, and the misspelled view field.
"""

from __future__ import annotations

import pytest

from application.dto.settlement_dto import SettlementView
from application.exceptions import NotAuthorizedError, NotFoundError
from application.use_cases.settlements.record_settlement import (
  RecordSettlementInput,
  RecordSettlementUseCase,
)
from domain.entities.settlement import InvalidSettlementError
from domain.value_objects.ids import GroupId, UserId
from tests.builders import CURRENCY, id_for, make_group, money
from tests.fakes import InMemoryGroupRepository, InMemorySettlementRepository


@pytest.fixture
def groups(
  alice: UserId, bob: UserId, carol: UserId, group_id: GroupId
) -> InMemoryGroupRepository:
  """Alice created the group; bob and carol joined. Dave is an outsider."""
  return InMemoryGroupRepository(
    [make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob, carol])]
  )


@pytest.fixture
def settlements() -> InMemorySettlementRepository:
  return InMemorySettlementRepository()


@pytest.fixture
def use_case(
  groups: InMemoryGroupRepository, settlements: InMemorySettlementRepository
) -> RecordSettlementUseCase:
  return RecordSettlementUseCase(groups, settlements)


@pytest.fixture
def a_settlement(group_id: GroupId, alice: UserId, bob: UserId):
  """The simplest valid input: alice pays bob 50.00."""

  def build(**overrides) -> RecordSettlementInput:
    fields = {
      "group_id": str(group_id),
      "from_user": str(alice),
      "to_user": str(bob),
      "amount_cents": 5_000,
    }
    return RecordSettlementInput(**{**fields, **overrides})

  return build


class TestRecording:
  def test_records_the_payment_between_the_two_members(
    self, use_case, a_settlement, alice: UserId, bob: UserId
  ):
    view = use_case.execute(a_settlement())

    assert view.from_user == str(alice)
    assert view.to_user == str(bob)
    assert view.amount_cents == 5_000

  def test_the_direction_of_the_payment_is_kept(
    self, use_case, a_settlement, alice: UserId, bob: UserId
  ):
    """`from_user` paid, `to_user` was paid — reversing them is a different settlement."""
    view = use_case.execute(a_settlement(from_user=str(bob), to_user=str(alice)))

    assert view.from_user == str(bob)
    assert view.to_user == str(alice)

  def test_any_two_members_can_settle_up(
    self, use_case, a_settlement, bob: UserId, carol: UserId
  ):
    """Settling is not the group creator's privilege."""
    view = use_case.execute(a_settlement(from_user=str(bob), to_user=str(carol)))

    assert view.from_user == str(bob)
    assert view.to_user == str(carol)

  def test_a_fresh_settlement_is_not_a_reversal(self, use_case, a_settlement):
    view = use_case.execute(a_settlement())

    assert view.reverses is None
    assert view.reversed_at is None

  def test_the_settlement_is_stamped_with_the_time_it_happened(self, use_case, a_settlement):
    view = use_case.execute(a_settlement())

    assert view.settlted_at is not None
    assert view.settlted_at.tzinfo is not None


class TestCurrency:
  def test_the_domain_default_currency_is_used_when_the_input_names_none(
    self, use_case, a_settlement
  ):
    view = use_case.execute(a_settlement())

    assert view.currency == CURRENCY

  def test_an_explicit_currency_is_honored(self, use_case, a_settlement):
    view = use_case.execute(a_settlement(currency="USD"))

    assert view.currency == "USD"

  @pytest.mark.parametrize(
    "malformed", ["US", "PHPX", "peso", "1 2"], ids=["short", "long", "word", "digits"]
  )
  def test_a_currency_that_is_not_a_three_letter_code_is_rejected(
    self, use_case, a_settlement, malformed: str
  ):
    with pytest.raises(ValueError, match="Currency must be a 3-letter ISO code"):
      use_case.execute(a_settlement(currency=malformed))

  @pytest.mark.parametrize("absent", ["", "   "], ids=["empty", "blank"])
  def test_an_empty_currency_falls_back_to_the_domain_default(
    self, use_case, a_settlement, absent: str
  ):
    """Nothing, or whitespace, reads as "not provided" rather than as a bad code."""
    view = use_case.execute(a_settlement(currency=absent))

    assert view.currency == CURRENCY

  def test_a_rejected_currency_writes_nothing(self, use_case, settlements, a_settlement):
    with pytest.raises(ValueError):
      use_case.execute(a_settlement(currency="US"))

    assert settlements.saved == []


class TestTheAmount:
  @pytest.mark.parametrize("amount", [1, 5_000, 1_000_000], ids=["one-cent", "fifty", "ten-k"])
  def test_any_positive_amount_is_recorded(self, use_case, a_settlement, amount: int):
    view = use_case.execute(a_settlement(amount_cents=amount))

    assert view.amount_cents == amount

  @pytest.mark.parametrize("amount", [0, -1, -5_000], ids=["zero", "negative-cent", "negative"])
  def test_a_non_positive_amount_is_rejected(self, use_case, a_settlement, amount: int):
    """Paying back nothing, or a negative sum, is not a settlement."""
    with pytest.raises(InvalidSettlementError, match="amount must be positive"):
      use_case.execute(a_settlement(amount_cents=amount))

  def test_a_rejected_amount_writes_nothing(self, use_case, settlements, a_settlement):
    with pytest.raises(InvalidSettlementError):
      use_case.execute(a_settlement(amount_cents=0))

    assert settlements.saved == []


class TestSelfSettlement:
  def test_a_member_cannot_settle_with_themselves(self, use_case, a_settlement, alice: UserId):
    with pytest.raises(InvalidSettlementError, match="cannot settle a balance with themselves"):
      use_case.execute(a_settlement(from_user=str(alice), to_user=str(alice)))

  def test_a_self_settlement_writes_nothing(
    self, use_case, settlements, a_settlement, alice: UserId
  ):
    with pytest.raises(InvalidSettlementError):
      use_case.execute(a_settlement(from_user=str(alice), to_user=str(alice)))

    assert settlements.saved == []


class TestMembership:
  def test_a_payer_outside_the_group_is_refused(self, use_case, a_settlement, dave: UserId):
    with pytest.raises(NotAuthorizedError, match=str(dave)):
      use_case.execute(a_settlement(from_user=str(dave)))

  def test_a_payee_outside_the_group_is_refused(self, use_case, a_settlement, dave: UserId):
    with pytest.raises(NotAuthorizedError, match=str(dave)):
      use_case.execute(a_settlement(to_user=str(dave)))

  def test_the_payer_is_checked_before_the_payee(
    self, use_case, a_settlement, dave: UserId
  ):
    """Both are outsiders, but the loop reports `from_user` first."""
    erin = id_for(UserId, "erin")

    with pytest.raises(NotAuthorizedError, match=str(dave)):
      use_case.execute(a_settlement(from_user=str(dave), to_user=str(erin)))

  def test_membership_is_checked_before_the_self_settlement_rule(
    self, use_case, a_settlement, dave: UserId
  ):
    """An outsider paying themselves is refused for not belonging, not for the self-payment."""
    with pytest.raises(NotAuthorizedError, match=str(dave)):
      use_case.execute(a_settlement(from_user=str(dave), to_user=str(dave)))

  def test_an_outsider_writes_nothing(self, use_case, settlements, a_settlement, dave: UserId):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(a_settlement(from_user=str(dave)))

    assert settlements.saved == []


class TestMissingGroup:
  def test_an_unknown_group_is_reported_as_not_found(self, use_case, a_settlement):
    with pytest.raises(NotFoundError, match="not found"):
      use_case.execute(a_settlement(group_id=str(id_for(GroupId, "no-such-group"))))

  def test_the_group_is_looked_up_before_the_members_are_checked(
    self, settlements, a_settlement, dave: UserId
  ):
    """With no group there is nobody to be a member of, so the miss is reported as not found."""
    use_case = RecordSettlementUseCase(InMemoryGroupRepository([]), settlements)

    with pytest.raises(NotFoundError, match="not found"):
      use_case.execute(a_settlement(from_user=str(dave)))

  def test_an_unknown_group_writes_nothing(self, use_case, settlements, a_settlement):
    with pytest.raises(NotFoundError):
      use_case.execute(a_settlement(group_id=str(id_for(GroupId, "no-such-group"))))

    assert settlements.saved == []


class TestPersistence:
  def test_saves_the_settlement_once(self, use_case, settlements, a_settlement):
    use_case.execute(a_settlement())

    assert len(settlements.saved) == 1

  def test_the_saved_settlement_is_the_one_returned(
    self, use_case, settlements, a_settlement, group_id: GroupId
  ):
    view = use_case.execute(a_settlement())

    stored = settlements.get_for_group(group_id)
    assert [str(settlement.id) for settlement in stored] == [view.id]

  def test_the_stored_settlement_carries_the_amount(
    self, use_case, settlements, a_settlement, group_id: GroupId
  ):
    use_case.execute(a_settlement())

    assert settlements.get_for_group(group_id)[0].amount == money(5_000)

  def test_each_settlement_gets_its_own_id(self, use_case, a_settlement):
    first = use_case.execute(a_settlement())
    second = use_case.execute(a_settlement())

    assert first.id != second.id

  def test_settlements_accumulate_in_the_group(
    self, use_case, settlements, a_settlement, group_id: GroupId
  ):
    use_case.execute(a_settlement())
    use_case.execute(a_settlement(amount_cents=2_500))

    assert len(settlements.get_for_group(group_id)) == 2

  def test_a_settlement_is_scoped_to_its_group(
    self, use_case, settlements, a_settlement, group_id: GroupId
  ):
    use_case.execute(a_settlement())

    assert settlements.get_for_group(id_for(GroupId, "boracay-trip")) == []

  def test_recording_a_settlement_does_not_touch_the_group(
    self, use_case, groups, a_settlement
  ):
    use_case.execute(a_settlement())

    assert groups.saved == []


class TestTheView:
  def test_describes_the_settlement_it_recorded(
    self, use_case, a_settlement, group_id: GroupId, alice: UserId, bob: UserId
  ):
    view = use_case.execute(a_settlement())

    assert isinstance(view, SettlementView)
    assert view.group_id == str(group_id)
    assert view.from_user == str(alice)
    assert view.to_user == str(bob)
    assert view.amount_cents == 5_000
    assert view.currency == CURRENCY
    assert view.reverses is None
    assert view.reversed_at is None
    assert view.settlted_at is not None

  def test_the_view_id_matches_the_stored_entity(
    self, use_case, settlements, a_settlement, group_id: GroupId
  ):
    view = use_case.execute(a_settlement())

    assert view.id == str(settlements.get_for_group(group_id)[0].id)

  def test_is_immutable(self, use_case, a_settlement):
    view = use_case.execute(a_settlement())

    with pytest.raises(Exception):
      view.amount_cents = 1


class TestUntrustedInput:
  """Every field arrives as raw request data, so the guards belong to the use case."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, a_settlement, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(a_settlement(group_id=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "alice", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_payer_id_that_is_not_a_uuid_is_rejected(self, use_case, a_settlement, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(a_settlement(from_user=malformed))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "bob", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_payee_id_that_is_not_a_uuid_is_rejected(self, use_case, a_settlement, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(a_settlement(to_user=malformed))

  def test_an_amount_that_is_not_an_integer_is_rejected(self, use_case, a_settlement):
    with pytest.raises(ValueError, match="Money amount must be an integer"):
      use_case.execute(a_settlement(amount_cents="5000"))

  def test_malformed_input_writes_nothing(self, use_case, settlements, a_settlement):
    with pytest.raises(ValueError):
      use_case.execute(a_settlement(group_id="not-a-uuid"))

    assert settlements.saved == []


class TestInput:
  def test_the_currency_defaults_to_the_domain_default(self, a_settlement):
    assert a_settlement().currency == CURRENCY

  def test_the_input_is_immutable(self, a_settlement):
    input_data = a_settlement()

    with pytest.raises(Exception):
      input_data.amount_cents = 1


class TestKnownGaps:
  """Behavior the use case currently allows that is worth a second look.

  Each test asserts what happens *today*; fixing the gap should break it on purpose.
  """

  def test_the_view_misspells_the_settled_at_field(self, use_case, a_settlement):
    """GAP: `SettlementView.settlted_at` is a typo for `settled_at`. It is a public field
    name, so anything serializing this view ships the misspelling to clients."""
    view = use_case.execute(a_settlement())

    assert view.settlted_at is not None
    assert not hasattr(view, "settled_at")

  def test_a_settlement_can_be_recorded_when_nothing_is_owed(
    self, use_case, settlements, a_settlement
  ):
    """GAP: the use case takes no expense or balance repository, so it cannot tell a real
    repayment from a payment between two members who owe each other nothing."""
    use_case.execute(a_settlement())

    assert len(settlements.saved) == 1

  def test_the_same_payment_can_be_recorded_twice(self, use_case, settlements, a_settlement):
    """GAP: nothing detects a duplicate, so a double-submitted request settles twice."""
    use_case.execute(a_settlement())
    use_case.execute(a_settlement())

    assert len(settlements.saved) == 2
    assert {settlement.amount for settlement in settlements.saved} == {money(5_000)}

  def test_a_settlement_may_use_a_currency_the_group_never_spent_in(
    self, use_case, a_settlement
  ):
    """GAP: the currency is taken from the request and never reconciled with the group's
    expenses, so a PHP balance can be settled with a USD payment."""
    view = use_case.execute(a_settlement(currency="USD"))

    assert view.currency == "USD"

  def test_a_closed_group_still_accepts_settlements(
    self, settlements, a_settlement, group_id: GroupId, alice: UserId, bob: UserId
  ):
    """GAP: `Group.is_closed` is never consulted, so a wrapped-up trip keeps taking payments.

    Arguably correct — a closed group may still need settling up — but it is unchecked
    rather than decided."""
    group = make_group(id=group_id, created_by=alice, members=[bob])
    group.close()
    use_case = RecordSettlementUseCase(InMemoryGroupRepository([group]), settlements)

    view = use_case.execute(a_settlement())

    assert view.amount_cents == 5_000
