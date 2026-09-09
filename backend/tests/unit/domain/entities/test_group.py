from __future__ import annotations

import pytest

from domain.entities.group import Group, GroupMember, GroupMembershipError
from domain.exceptions import DomainError
from domain.value_objects.ids import GroupId, UserId
from tests.builders import make_group


class TestCreation:
  def test_the_creator_is_a_member(self, alice: UserId):
    group = make_group(created_by=alice)

    assert group.has_member(alice)

  def test_a_creator_missing_from_the_member_list_is_added(self, alice: UserId, bob: UserId):
    group = Group(
      id=GroupId.new(),
      name="Palawan Trip",
      created_by=alice,
      members=[GroupMember(user_id=bob)],
    )

    assert group.member_ids() == [bob, alice]

  def test_a_group_built_with_no_members_gets_the_creator(self, alice: UserId):
    group = Group(id=GroupId.new(), name="Palawan Trip", created_by=alice, members=[])

    assert group.member_ids() == [alice]

  @pytest.mark.parametrize("blank", ["", "   "])
  def test_rejects_a_blank_name(self, blank: str, alice: UserId):
    with pytest.raises(ValueError, match="name cannot be empty"):
      make_group(name=blank, created_by=alice)

  def test_stores_the_name_trimmed(self, alice: UserId):
    """Read models report the stored value verbatim, so the padding is removed on the way in."""
    assert make_group(name="  Palawan Trip  ", created_by=alice).name == "Palawan Trip"


class TestCreateFactory:
  def test_the_creator_is_seeded_as_the_first_member(self, alice: UserId):
    group = Group.create(id=GroupId.new(), name="Palawan Trip", created_by=alice)

    assert group.member_ids() == [alice]

  def test_the_creator_is_stamped_with_a_join_time(self, alice: UserId):
    group = Group.create(id=GroupId.new(), name="Palawan Trip", created_by=alice)

    assert group.members[0].joined_at is not None

  def test_keeps_the_supplied_id_and_name(self, alice: UserId):
    group_id = GroupId.new()

    group = Group.create(id=group_id, name="Palawan Trip", created_by=alice)

    assert (group.id, group.name, group.created_by) == (group_id, "Palawan Trip", alice)

  @pytest.mark.parametrize("blank", ["", "   "])
  def test_rejects_a_blank_name(self, blank: str, alice: UserId):
    with pytest.raises(ValueError, match="name cannot be empty"):
      Group.create(id=GroupId.new(), name=blank, created_by=alice)


class TestMembership:
  def test_has_member_is_false_for_an_outsider(self, alice: UserId, bob: UserId):
    assert make_group(created_by=alice).has_member(bob) is False

  def test_add_member(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice)

    group.add_member(bob)

    assert group.member_ids() == [alice, bob]

  def test_adding_the_same_member_twice_is_rejected(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    with pytest.raises(GroupMembershipError, match="already a member"):
      group.add_member(bob)

    assert group.member_ids() == [alice, bob]

  def test_added_members_are_stamped_with_a_join_time(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice)

    group.add_member(bob)

    assert group.members[-1].joined_at is not None

  def test_member_ids_preserves_insertion_order(self, alice, bob, carol):
    group = make_group(created_by=alice, members=[bob, carol])

    assert group.member_ids() == [alice, bob, carol]


class TestRemoveMember:
  def test_removes_a_settled_up_member(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    group.remove_member(bob, has_zero_balance=True)

    assert group.member_ids() == [alice]

  def test_refuses_to_remove_a_member_who_still_owes_or_is_owed(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    with pytest.raises(GroupMembershipError, match="unsettled balances"):
      group.remove_member(bob, has_zero_balance=False)

    assert group.has_member(bob)

  def test_refuses_to_remove_someone_who_is_not_a_member(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice)

    with pytest.raises(GroupMembershipError, match="not a memeber"):
      group.remove_member(bob, has_zero_balance=True)

  def test_the_creator_can_be_removed_once_settled(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    group.remove_member(alice, has_zero_balance=True)

    assert group.member_ids() == [bob]


class TestClosing:
  def test_a_new_group_is_open(self, alice: UserId):
    group = make_group(created_by=alice)

    assert group.is_closed is False
    assert group.closed_at is None

  def test_close_stamps_an_aware_utc_time(self, alice: UserId):
    group = make_group(created_by=alice)

    group.close()

    assert group.is_closed is True
    assert group.closed_at is not None
    assert group.closed_at.tzinfo is not None

  def test_closing_a_closed_group_is_rejected(self, alice: UserId):
    group = make_group(created_by=alice)
    group.close()
    closed_at = group.closed_at

    with pytest.raises(DomainError, match="already closed"):
      group.close()

    assert group.closed_at == closed_at

  def test_reopen_clears_the_closed_stamp(self, alice: UserId):
    group = make_group(created_by=alice)
    group.close()

    group.reopen()

    assert group.is_closed is False
    assert group.closed_at is None

  def test_reopening_an_open_group_is_rejected(self, alice: UserId):
    group = make_group(created_by=alice)

    with pytest.raises(DomainError, match="is not closed"):
      group.reopen()

  def test_a_reopened_group_can_be_closed_again(self, alice: UserId):
    group = make_group(created_by=alice)
    group.close()
    group.reopen()

    group.close()

    assert group.is_closed is True

  def test_closing_leaves_the_members_alone(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    group.close()

    assert group.member_ids() == [alice, bob]


class TestReconstruction:
  """`__post_init__` runs on every construction, including when a repository rebuilds a
  stored group, so any state the entity can reach has to survive a round trip."""

  def test_a_group_survives_being_rebuilt_from_its_own_state(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    rebuilt = Group(
      id=group.id, name=group.name, created_by=group.created_by, members=list(group.members)
    )

    assert rebuilt.member_ids() == [alice, bob]

  def test_a_group_survives_a_rebuild_after_a_member_leaves(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])
    group.remove_member(bob, has_zero_balance=True)

    rebuilt = Group(
      id=group.id, name=group.name, created_by=group.created_by, members=list(group.members)
    )

    assert rebuilt.member_ids() == [alice]

  def test_a_creator_who_left_is_put_back_by_a_rebuild(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])
    group.remove_member(alice, has_zero_balance=True)

    rebuilt = Group(
      id=group.id, name=group.name, created_by=group.created_by, members=list(group.members)
    )

    assert rebuilt.member_ids() == [bob, alice]

  def test_a_closed_group_stays_closed_when_rebuilt(self, alice: UserId):
    group = make_group(created_by=alice)
    group.close()

    rebuilt = Group(
      id=group.id,
      name=group.name,
      created_by=group.created_by,
      members=list(group.members),
      closed_at=group.closed_at,
    )

    assert rebuilt.is_closed is True
    assert rebuilt.closed_at == group.closed_at

