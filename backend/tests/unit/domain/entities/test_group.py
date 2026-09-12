from __future__ import annotations

import pytest

from domain.entities.group import Group, GroupMember, GroupMembershipError
from domain.events.base import DomainEvent
from domain.events.group_events import (
  GroupClosed,
  GroupCreated,
  GroupReopened,
  MemberAdded,
  MemberRemoved,
)
from domain.exceptions import DomainError
from domain.value_objects.ids import GroupId, UserId
from tests.builders import make_group


def only_event(group: Group) -> DomainEvent:
  """The single event the group is holding — fails loudly if it recorded more or fewer.

  Every assertion about an event goes through here, so a method that starts emitting a
  second event cannot slip past a test that only looked at the first one.
  """
  events = group.pull_events()
  assert len(events) == 1, f"expected exactly one event, got {[type(e).__name__ for e in events]}"
  return events[0]


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

  def test_records_that_the_group_was_created(self, alice: UserId):
    group = Group.create(id=GroupId.new(), name="Palawan Trip", created_by=alice)

    assert isinstance(only_event(group), GroupCreated)

  def test_the_created_event_carries_the_whole_group(self, alice: UserId):
    group_id = GroupId.new()

    group = Group.create(id=group_id, name="Palawan Trip", created_by=alice)

    event = only_event(group)
    assert (event.group_id, event.created_by, event.name) == (group_id, alice, "Palawan Trip")

  def test_the_created_event_carries_the_trimmed_name(self, alice: UserId):
    """Subscribers build read models from the event, not from the entity — a name that was
    trimmed on the way in but published raw makes the two disagree about the same group."""
    group = Group.create(id=GroupId.new(), name="  Palawan Trip  ", created_by=alice)

    assert only_event(group).name == group.name

  def test_seeding_the_creator_does_not_also_record_a_member_added(self, alice: UserId):
    """The creator joins as part of creation; a second event would double-count them."""
    group = Group.create(id=GroupId.new(), name="Palawan Trip", created_by=alice)

    assert [type(event) for event in group.pull_events()] == [GroupCreated]

  def test_a_rejected_name_records_nothing(self, alice: UserId):
    """The group is never constructed, so there is nothing to publish."""
    with pytest.raises(ValueError):
      Group.create(id=GroupId.new(), name="  ", created_by=alice)


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


class TestMembershipEvents:
  def test_adding_a_member_records_it(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice)

    group.add_member(bob)

    event = only_event(group)
    assert isinstance(event, MemberAdded)
    assert (event.group_id, event.member_id) == (group.id, bob)

  def test_a_rejected_duplicate_records_nothing(self, alice: UserId, bob: UserId):
    """The guard runs before the event, so a rejected join cannot announce itself."""
    group = make_group(created_by=alice, members=[bob])

    with pytest.raises(GroupMembershipError):
      group.add_member(bob)

    assert group.pull_events() == []

  def test_removing_a_member_records_it(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])

    group.remove_member(bob, has_zero_balance=True)

    event = only_event(group)
    assert isinstance(event, MemberRemoved)
    assert (event.group_id, event.member_id) == (group.id, bob)

  def test_removing_an_outsider_records_nothing(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice)

    with pytest.raises(GroupMembershipError):
      group.remove_member(bob, has_zero_balance=True)

    assert group.pull_events() == []

  def test_a_removal_blocked_by_an_unsettled_balance_records_nothing(
    self, alice: UserId, bob: UserId
  ):
    """The member is still in the group, so publishing a removal would tell every
    subscriber they left while the entity still lists them."""
    group = make_group(created_by=alice, members=[bob])

    with pytest.raises(GroupMembershipError):
      group.remove_member(bob, has_zero_balance=False)

    assert group.pull_events() == []

  def test_rejoining_records_a_second_addition(self, alice: UserId, bob: UserId):
    group = make_group(created_by=alice, members=[bob])
    group.remove_member(bob, has_zero_balance=True)

    group.add_member(bob)

    assert [type(event) for event in group.pull_events()] == [MemberRemoved, MemberAdded]


class TestLifecycleEvents:
  def test_closing_records_it(self, alice: UserId):
    group = make_group(created_by=alice)

    group.close()

    event = only_event(group)
    assert isinstance(event, GroupClosed)
    assert event.group_id == group.id

  def test_closing_a_closed_group_records_nothing(self, alice: UserId):
    group = make_group(created_by=alice)
    group.close()
    group.pull_events()

    with pytest.raises(DomainError):
      group.close()

    assert group.pull_events() == []

  def test_reopening_records_it(self, alice: UserId):
    group = make_group(created_by=alice)
    group.close()
    group.pull_events()

    group.reopen()

    event = only_event(group)
    assert isinstance(event, GroupReopened)
    assert event.group_id == group.id

  def test_reopening_an_open_group_records_nothing(self, alice: UserId):
    group = make_group(created_by=alice)

    with pytest.raises(DomainError):
      group.reopen()

    assert group.pull_events() == []

  def test_a_close_reopen_close_cycle_records_each_step(self, alice: UserId):
    group = make_group(created_by=alice)

    group.close()
    group.reopen()
    group.close()

    assert [type(event) for event in group.pull_events()] == [
      GroupClosed, GroupReopened, GroupClosed
    ]


class TestEventBookkeeping:
  def test_a_group_that_has_done_nothing_holds_no_events(self, alice: UserId):
    assert make_group(created_by=alice).pull_events() == []

  def test_events_come_back_in_the_order_they_happened(self, alice, bob, carol):
    group = Group.create(id=GroupId.new(), name="Palawan Trip", created_by=alice)

    group.add_member(bob)
    group.add_member(carol)
    group.remove_member(bob, has_zero_balance=True)
    group.close()

    assert [type(event) for event in group.pull_events()] == [
      GroupCreated, MemberAdded, MemberAdded, MemberRemoved, GroupClosed
    ]

  def test_pulling_clears_what_was_pulled(self, alice: UserId, bob: UserId):
    """Whoever pulls is responsible for publishing; leaving the events behind means the
    next pull publishes them a second time."""
    group = make_group(created_by=alice)
    group.add_member(bob)

    group.pull_events()

    assert group.pull_events() == []

  def test_only_the_events_since_the_last_pull_come_back(self, alice, bob, carol):
    group = make_group(created_by=alice)
    group.add_member(bob)
    group.pull_events()

    group.add_member(carol)

    assert [event.member_id for event in group.pull_events()] == [carol]

  def test_two_groups_do_not_share_events(self, alice: UserId, bob: UserId):
    """`_pending_events` is created lazily per instance — a list shared across groups would
    publish one group's membership changes under another group's id."""
    first = make_group(created_by=alice)
    second = make_group(created_by=alice)

    first.add_member(bob)

    assert len(first.pull_events()) == 1
    assert second.pull_events() == []


class TestReconstruction:
  """`__post_init__` runs on every construction, including when a repository rebuilds a
  stored group, so any state the entity can reach has to survive a round trip."""

  def test_rebuilding_a_group_records_nothing(self, alice: UserId, bob: UserId):
    """Only `Group.create` announces a new group. The constructor is also how a repository
    rehydrates a stored one, so recording there would re-announce an existing group — and
    seeding an absent creator would publish a join that already happened long ago."""
    rebuilt = Group(
      id=GroupId.new(),
      name="Palawan Trip",
      created_by=alice,
      members=[GroupMember(user_id=bob)],
    )

    assert rebuilt.pull_events() == []

  def test_a_rebuilt_group_still_records_what_happens_next(self, alice: UserId, bob: UserId):
    """Rehydrating must leave the bookkeeping usable, not just empty."""
    group = make_group(created_by=alice)
    rebuilt = Group(
      id=group.id, name=group.name, created_by=group.created_by, members=list(group.members)
    )

    rebuilt.add_member(bob)

    assert isinstance(only_event(rebuilt), MemberAdded)

  def test_events_do_not_travel_with_the_state_into_a_rebuild(self, alice: UserId, bob: UserId):
    """The events belong to the instance that recorded them, not to the stored state."""
    group = make_group(created_by=alice)
    group.add_member(bob)

    rebuilt = Group(
      id=group.id, name=group.name, created_by=group.created_by, members=list(group.members)
    )

    assert rebuilt.pull_events() == []
    assert len(group.pull_events()) == 1

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

