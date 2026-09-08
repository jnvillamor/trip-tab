from __future__ import annotations

import pytest

from domain.entities.group import Group, GroupMember, GroupMembershipError
from domain.value_objects.ids import GroupId, UserId
from tests.builders import make_group


class TestCreation:
  def test_the_creator_is_a_member(self, alice: UserId):
    group = make_group(created_by=alice)

    assert group.has_member(alice)

  def test_rejects_a_group_whose_creator_is_not_a_member(self, alice: UserId, bob: UserId):
    with pytest.raises(GroupMembershipError, match="creator must be a member"):
      Group(
        id=GroupId.new(),
        name="Palawan Trip",
        created_by=alice,
        members=[GroupMember(user_id=bob)],
      )

  def test_rejects_a_group_with_no_members(self, alice: UserId):
    with pytest.raises(GroupMembershipError, match="creator must be a member"):
      Group(id=GroupId.new(), name="Palawan Trip", created_by=alice, members=[])

  @pytest.mark.parametrize("blank", ["", "   "])
  def test_rejects_a_blank_name(self, blank: str, alice: UserId):
    with pytest.raises(ValueError, match="name cannot be empty"):
      make_group(name=blank, created_by=alice)


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
