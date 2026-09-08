from __future__ import annotations

import pytest

from application.exceptions import NotFoundError
from application.use_cases.group.add_group_member import (
  AddGroupMemberInput,
  AddGroupMemberUseCase,
)
from domain.entities.group import GroupMembershipError
from domain.value_objects.ids import GroupId
from tests.builders import id_for, make_group
from tests.fakes import InMemoryGroupRepository


@pytest.fixture
def group(alice, group_id: GroupId):
  return make_group(id=group_id, name="Palawan Trip", created_by=alice)


@pytest.fixture
def repository(group) -> InMemoryGroupRepository:
  return InMemoryGroupRepository([group])


@pytest.fixture
def use_case(repository: InMemoryGroupRepository) -> AddGroupMemberUseCase:
  return AddGroupMemberUseCase(repository)


class TestSuccess:
  def test_returns_a_view_including_the_new_member(self, use_case, group_id, alice, bob):
    view = use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert [member.user_id for member in view.members] == [str(alice), str(bob)]

  def test_the_view_still_describes_the_same_group(self, use_case, group_id, alice, bob):
    view = use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert view.id == str(group_id)
    assert view.name == "Palawan Trip"
    assert view.created_by == str(alice)

  def test_persists_the_new_member(self, use_case, repository, group_id, alice, bob):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    stored = repository.get_by_id(group_id)
    assert stored is not None
    assert stored.member_ids() == [alice, bob]

  def test_saves_exactly_once(self, use_case, repository, group_id, bob):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert len(repository.saved) == 1

  def test_stamps_the_new_member_with_a_join_time(self, use_case, group_id, bob):
    view = use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert view.members[-1].joined_at is not None

  def test_members_accumulate_across_calls(self, use_case, group_id, alice, bob, carol):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))
    view = use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(carol)))

    assert [member.user_id for member in view.members] == [str(alice), str(bob), str(carol)]


class TestFailure:
  def test_unknown_group_is_reported_as_not_found(self, use_case, bob):
    with pytest.raises(NotFoundError, match="not found"):
      use_case.execute(AddGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob)))

  def test_unknown_group_writes_nothing(self, use_case, repository, bob):
    with pytest.raises(NotFoundError):
      use_case.execute(AddGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob)))

    assert repository.saved == []

  def test_adding_an_existing_member_is_rejected(self, use_case, group_id, alice):
    with pytest.raises(GroupMembershipError, match="already a member"):
      use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(alice)))

  def test_a_rejected_add_leaves_the_stored_group_untouched(
    self, use_case, repository, group_id, alice
  ):
    with pytest.raises(GroupMembershipError):
      use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(alice)))

    assert repository.saved == []
    assert repository.get_by_id(group_id).member_ids() == [alice]

  def test_a_failed_second_add_does_not_undo_the_first(
    self, use_case, repository, group_id, alice, bob
  ):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    with pytest.raises(GroupMembershipError):
      use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert repository.get_by_id(group_id).member_ids() == [alice, bob]
    assert len(repository.saved) == 1


class TestUntrustedInput:
  """Both ids arrive as raw strings, as they would from an HTTP request."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "no-such-group", "not-a-uuid"], ids=["empty", "blank", "slug", "words"]
  )
  def test_a_group_id_that_is_not_a_uuid_is_rejected(self, use_case, bob, malformed: str):
    with pytest.raises(ValueError, match="GroupId must be"):
      use_case.execute(AddGroupMemberInput(group_id=malformed, user_id=str(bob)))

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "bob", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_user_id_that_is_not_a_uuid_is_rejected(self, use_case, group_id, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=malformed))

  def test_a_malformed_id_writes_nothing(self, use_case, repository, bob):
    with pytest.raises(ValueError):
      use_case.execute(AddGroupMemberInput(group_id="not-a-uuid", user_id=str(bob)))

    assert repository.saved == []


class TestInput:
  def test_the_input_is_immutable(self, group_id, bob):
    input_data = AddGroupMemberInput(group_id=str(group_id), user_id=str(bob))

    with pytest.raises(Exception):
      input_data.user_id = "someone-else"
