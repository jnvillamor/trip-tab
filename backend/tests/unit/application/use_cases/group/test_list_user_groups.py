"""Listing is a pure read: whatever the repository reports for the user, mapped to views.
These tests pin the id parsing, the membership scoping, and the shape of each view.
"""

from __future__ import annotations

import pytest

from application.dto.group_dto import GroupView
from application.use_cases.group.list_user_groups import (
  ListUserGroupsInput,
  ListUserGroupsUseCase,
)
from domain.value_objects.ids import GroupId, UserId
from tests.builders import id_for, make_group
from tests.fakes import InMemoryGroupRepository


@pytest.fixture
def repository() -> InMemoryGroupRepository:
  return InMemoryGroupRepository()


@pytest.fixture
def use_case(repository: InMemoryGroupRepository) -> ListUserGroupsUseCase:
  return ListUserGroupsUseCase(repository)


def names_of(views: list[GroupView]) -> set[str]:
  """Group names as a set: the repository port promises no particular ordering."""
  return {view.name for view in views}


class TestListing:
  def test_a_user_in_no_groups_gets_an_empty_list(self, use_case, alice: UserId):
    assert use_case.execute(ListUserGroupsInput(user_id=str(alice))) == []

  def test_lists_a_group_the_user_created(self, use_case, repository, alice: UserId):
    repository.save(make_group(name="Palawan Trip", created_by=alice))

    views = use_case.execute(ListUserGroupsInput(user_id=str(alice)))

    assert names_of(views) == {"Palawan Trip"}

  def test_lists_a_group_the_user_only_joined(self, use_case, repository, alice, bob: UserId):
    repository.save(make_group(name="Palawan Trip", created_by=alice, members=[bob]))

    views = use_case.execute(ListUserGroupsInput(user_id=str(bob)))

    assert names_of(views) == {"Palawan Trip"}

  def test_lists_every_group_the_user_belongs_to(self, use_case, repository, alice, bob: UserId):
    repository.save(make_group(name="Palawan Trip", created_by=alice))
    repository.save(make_group(name="Baguio Trip", created_by=bob, members=[alice]))

    views = use_case.execute(ListUserGroupsInput(user_id=str(alice)))

    assert names_of(views) == {"Palawan Trip", "Baguio Trip"}

  def test_groups_the_user_is_not_in_are_left_out(self, use_case, repository, alice, bob: UserId):
    repository.save(make_group(name="Palawan Trip", created_by=alice))
    repository.save(make_group(name="Someone Elses Trip", created_by=bob))

    views = use_case.execute(ListUserGroupsInput(user_id=str(alice)))

    assert names_of(views) == {"Palawan Trip"}

  def test_a_member_who_left_no_longer_sees_the_group(
    self, use_case, repository, alice, bob: UserId
  ):
    group = make_group(name="Palawan Trip", created_by=alice, members=[bob])
    group.remove_member(bob, has_zero_balance=True)
    repository.save(group)

    assert use_case.execute(ListUserGroupsInput(user_id=str(bob))) == []

  def test_a_closed_group_is_still_listed(self, use_case, repository, alice: UserId):
    """`GroupView` carries no closed state, so a caller cannot tell it apart from an open one."""
    group = make_group(name="Palawan Trip", created_by=alice)
    group.close()
    repository.save(group)

    views = use_case.execute(ListUserGroupsInput(user_id=str(alice)))

    assert names_of(views) == {"Palawan Trip"}


class TestTheView:
  def test_describes_the_group_it_came_from(self, use_case, repository, alice, group_id: GroupId):
    repository.save(make_group(id=group_id, name="Palawan Trip", created_by=alice))

    view = use_case.execute(ListUserGroupsInput(user_id=str(alice)))[0]

    assert view.id == str(group_id)
    assert view.name == "Palawan Trip"
    assert view.created_by == str(alice)

  def test_lists_the_members_in_the_groups_own_order(
    self, use_case, repository, alice, bob, carol: UserId
  ):
    repository.save(make_group(created_by=alice, members=[bob, carol]))

    view = use_case.execute(ListUserGroupsInput(user_id=str(alice)))[0]

    assert [member.user_id for member in view.members] == [str(alice), str(bob), str(carol)]

  def test_carries_each_members_join_time(self, use_case, repository, alice, bob: UserId):
    repository.save(make_group(created_by=alice, members=[bob]))

    view = use_case.execute(ListUserGroupsInput(user_id=str(alice)))[0]

    assert all(member.joined_at is not None for member in view.members)

  def test_is_immutable(self, use_case, repository, alice: UserId):
    repository.save(make_group(created_by=alice))

    view = use_case.execute(ListUserGroupsInput(user_id=str(alice)))[0]

    with pytest.raises(Exception):
      view.name = "Renamed"


class TestReadOnly:
  def test_listing_writes_nothing(self, use_case, repository, alice, bob: UserId):
    repository.save(make_group(created_by=alice, members=[bob]))
    repository.saved.clear()

    use_case.execute(ListUserGroupsInput(user_id=str(alice)))

    assert repository.saved == []
    assert repository.deleted == []

  def test_reads_with_the_parsed_user_id(self, use_case, repository, alice: UserId):
    use_case.execute(ListUserGroupsInput(user_id=str(alice)))

    assert repository.queried_users == [alice]


class TestUntrustedInput:
  """The user id arrives as a raw string, as it would from an HTTP request."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "alice", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_user_id_that_is_not_a_uuid_is_rejected(self, use_case, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(ListUserGroupsInput(user_id=malformed))

  def test_a_malformed_id_reads_nothing(self, use_case, repository):
    with pytest.raises(ValueError):
      use_case.execute(ListUserGroupsInput(user_id="not-a-uuid"))

    assert repository.queried_users == []

  def test_an_unknown_but_valid_id_is_not_an_error(self, use_case, repository, alice: UserId):
    repository.save(make_group(created_by=alice))

    assert use_case.execute(ListUserGroupsInput(user_id=str(id_for(UserId, "nobody")))) == []


class TestInput:
  def test_the_input_is_immutable(self, alice: UserId):
    input_data = ListUserGroupsInput(user_id=str(alice))

    with pytest.raises(Exception):
      input_data.user_id = "someone-else"
