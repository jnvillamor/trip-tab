"""Reversing a settlement undoes a payment by recording its mirror image: the money flows
back the other way, the original is stamped as reversed, and both rows are saved.

Reversal is a two-step domain operation — `Settlement.create_reversal` builds the mirror and
`original.mark_reversed()` stamps the source — and nothing in the entity forces the second
step. This use case is the only caller that gets it right, so these tests are what keeps it
that way; `TestKnownGaps` pins what the domain still allows a careless caller to do.
"""

from __future__ import annotations

import pytest

from application.dto.settlement_dto import SettlementView
from application.exceptions import NotAuthorizedError, NotFoundError
from application.use_cases.settlements.reverse_settlement import (
  ReverseSettlementInput,
  ReverseSettlementUseCase,
)
from domain.entities.settlement import InvalidSettlementError, Settlement
from domain.value_objects.ids import GroupId, SettlementId, UserId
from tests.builders import id_for, make_group, make_settlement, money
from tests.fakes import InMemoryGroupRepository, InMemorySettlementRepository


@pytest.fixture
def original(group_id: GroupId, alice: UserId, bob: UserId) -> Settlement:
  """Alice paid bob 50.00 — the settlement every test here reverses."""
  return make_settlement(
    id=id_for(SettlementId, "original"),
    group_id=group_id,
    from_user=alice,
    to_user=bob,
    amount=money(5_000),
  )


@pytest.fixture
def groups(
  alice: UserId, bob: UserId, carol: UserId, group_id: GroupId
) -> InMemoryGroupRepository:
  """Alice created the group; bob and carol joined. Dave is an outsider."""
  return InMemoryGroupRepository(
    [make_group(id=group_id, name="Palawan Trip", created_by=alice, members=[bob, carol])]
  )


@pytest.fixture
def settlements(original: Settlement) -> InMemorySettlementRepository:
  return InMemorySettlementRepository([original])


@pytest.fixture
def use_case(
  groups: InMemoryGroupRepository, settlements: InMemorySettlementRepository
) -> ReverseSettlementUseCase:
  return ReverseSettlementUseCase(groups, settlements)


@pytest.fixture
def a_reversal(group_id: GroupId, original: Settlement, alice: UserId):
  """The simplest valid input: alice, who paid, asks to undo it."""

  def build(**overrides) -> ReverseSettlementInput:
    fields = {
      "group_id": str(group_id),
      "settlement_id": str(original.id),
      "requested_by": str(alice),
    }
    return ReverseSettlementInput(**{**fields, **overrides})

  return build


class TestReversing:
  def test_returns_the_reversal_not_the_original(self, use_case, a_reversal, original):
    view = use_case.execute(a_reversal())

    assert isinstance(view, SettlementView)
    assert view.id != str(original.id)
    assert view.reverses == str(original.id)

  def test_the_money_flows_back_the_other_way(
    self, use_case, a_reversal, alice: UserId, bob: UserId
  ):
    """The original was alice paying bob, so the reversal is bob paying alice."""
    view = use_case.execute(a_reversal())

    assert (view.from_user, view.to_user) == (str(bob), str(alice))

  def test_the_reversal_is_for_the_same_amount(self, use_case, a_reversal):
    view = use_case.execute(a_reversal())

    assert view.amount_cents == 5_000

  def test_the_reversal_belongs_to_the_same_group(self, use_case, a_reversal, group_id: GroupId):
    assert use_case.execute(a_reversal()).group_id == str(group_id)

  def test_the_reversal_is_not_itself_reversed(self, use_case, a_reversal):
    assert use_case.execute(a_reversal()).reversed_at is None

  def test_either_party_may_reverse_it(self, use_case, a_reversal, bob: UserId):
    """Bob was paid rather than paying, but the settlement is just as much his to undo."""
    view = use_case.execute(a_reversal(requested_by=str(bob)))

    assert view.reverses is not None


class TestPersistence:
  def test_stamps_the_original_as_reversed(
    self, use_case, a_reversal, settlements, group_id: GroupId, original: Settlement
  ):
    """The stamp is what stops the settlement being reversed a second time, so it has to
    reach the repository — not just the in-memory entity the use case happened to hold."""
    use_case.execute(a_reversal())

    stored = settlements.get_by_id(group_id, original.id)
    assert stored.reversed_at is not None

  def test_saves_both_the_original_and_the_reversal(
    self, use_case, a_reversal, settlements, original: Settlement
  ):
    use_case.execute(a_reversal())

    saved_ids = [str(settlement.id) for settlement in settlements.saved]
    assert str(original.id) in saved_ids
    assert len(saved_ids) == 2

  def test_the_stored_reversal_points_back_at_the_original(
    self, use_case, a_reversal, settlements, group_id: GroupId, original: Settlement
  ):
    view = use_case.execute(a_reversal())

    stored = settlements.get_by_id(group_id, SettlementId(view.id))
    assert stored.reverses == original.id
    assert stored.is_reversal() is True


class TestRefusals:
  def test_refuses_to_reverse_the_same_settlement_twice(self, use_case, a_reversal):
    """The second attempt reads the stamped original back, so the domain guard fires."""
    use_case.execute(a_reversal())

    with pytest.raises(InvalidSettlementError, match="already been reversed"):
      use_case.execute(a_reversal())

  def test_a_second_attempt_writes_nothing(self, use_case, a_reversal, settlements):
    use_case.execute(a_reversal())
    saved_before = len(settlements.saved)

    with pytest.raises(InvalidSettlementError):
      use_case.execute(a_reversal())

    assert len(settlements.saved) == saved_before

  def test_refuses_to_reverse_a_reversal(self, use_case, a_reversal, settlements, group_id):
    """Undoing an undo is an ordinary new settlement, not a second reversal."""
    reversal = use_case.execute(a_reversal())

    with pytest.raises(InvalidSettlementError, match="cannot be reversed again"):
      use_case.execute(a_reversal(settlement_id=reversal.id))

  def test_refuses_an_unknown_group(self, use_case, a_reversal):
    with pytest.raises(NotFoundError, match="Group with ID"):
      use_case.execute(a_reversal(group_id=str(GroupId.new())))

  def test_refuses_an_unknown_settlement(self, use_case, a_reversal):
    with pytest.raises(NotFoundError, match="Settlement with ID"):
      use_case.execute(a_reversal(settlement_id=str(SettlementId.new())))

  def test_refuses_a_settlement_from_another_group(
    self, use_case, a_reversal, settlements, alice: UserId, bob: UserId
  ):
    """The lookup is scoped by group, so a valid id from elsewhere is simply not found."""
    elsewhere = make_settlement(group_id=GroupId.new(), from_user=alice, to_user=bob)
    settlements.save(elsewhere)

    with pytest.raises(NotFoundError, match="Settlement with ID"):
      use_case.execute(a_reversal(settlement_id=str(elsewhere.id)))

  def test_refuses_someone_outside_the_group(self, use_case, a_reversal, dave: UserId):
    with pytest.raises(NotAuthorizedError, match="is not a member of group"):
      use_case.execute(a_reversal(requested_by=str(dave)))

  def test_refuses_a_member_who_was_not_party_to_the_payment(
    self, use_case, a_reversal, carol: UserId
  ):
    """Carol is in the group, but the money was between alice and bob."""
    with pytest.raises(NotAuthorizedError, match="is not involved in settlement"):
      use_case.execute(a_reversal(requested_by=str(carol)))

  def test_a_refused_reversal_writes_nothing(self, use_case, a_reversal, settlements, carol):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(a_reversal(requested_by=str(carol)))

    assert settlements.saved == []

  def test_a_refused_reversal_leaves_the_original_unstamped(
    self, use_case, a_reversal, settlements, carol, group_id: GroupId, original: Settlement
  ):
    with pytest.raises(NotAuthorizedError):
      use_case.execute(a_reversal(requested_by=str(carol)))

    assert settlements.get_by_id(group_id, original.id).reversed_at is None

  @pytest.mark.parametrize("field", ["group_id", "settlement_id", "requested_by"])
  def test_rejects_an_id_that_is_not_a_uuid(self, use_case, a_reversal, field: str):
    with pytest.raises(ValueError, match="valid UUID string"):
      use_case.execute(a_reversal(**{field: "not-a-uuid"}))


class TestKnownGaps:
  """What the domain still allows a caller other than this use case to do.

  `Settlement.create_reversal` checks `original.reversed_at` but never sets it — stamping is
  a separate call. Each test here asserts what happens *today*; moving the stamp into
  `create_reversal` should break them on purpose.
  """

  def test_the_entity_lets_one_settlement_be_reversed_twice(self, original: Settlement):
    """GAP: two reversals of the same payment, because nothing stamped the original in
    between. Only the use case remembering `mark_reversed` prevents this."""
    first = Settlement.create_reversal(SettlementId.new(), original)
    second = Settlement.create_reversal(SettlementId.new(), original)

    assert first.reverses == original.id
    assert second.reverses == original.id
    assert original.reversed_at is None

  def test_creating_a_reversal_does_not_stamp_the_original(self, original: Settlement):
    """GAP: same cause, stated directly — the factory has no effect on its source."""
    Settlement.create_reversal(SettlementId.new(), original)

    assert original.reversed_at is None
