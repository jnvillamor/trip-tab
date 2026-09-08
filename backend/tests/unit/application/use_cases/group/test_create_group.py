from __future__ import annotations

import uuid

import pytest

from application.use_cases.group.create_group import CreateGroupInput, CreateGroupUseCase
from domain.value_objects.ids import GroupId
from tests.fakes import InMemoryGroupRepository

@pytest.fixture
def repository() -> InMemoryGroupRepository:
  return InMemoryGroupRepository()


@pytest.fixture
def use_case(repository: InMemoryGroupRepository) -> CreateGroupUseCase:
  return CreateGroupUseCase(repository)


class TestSuccess:
  def test_returns_a_view_of_the_new_group(self, use_case, alice):
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert view.name == "Palawan Trip"
    assert view.created_by == str(alice)

  def test_the_creator_is_the_only_member(self, use_case, alice):
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert [member.user_id for member in view.members] == [str(alice)]

  def test_stamps_the_creator_with_a_join_time(self, use_case, alice):
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert view.members[0].joined_at is not None

  def test_assigns_a_generated_id(self, use_case, alice):
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert uuid.UUID(view.id).version == 4

  def test_each_group_gets_its_own_id(self, use_case, alice):
    first = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))
    second = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert first.id != second.id

  def test_persists_the_group_under_the_id_it_reports(self, use_case, repository, alice):
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    stored = repository.get_by_id(GroupId(view.id))
    assert stored is not None
    assert stored.name == "Palawan Trip"
    assert stored.member_ids() == [alice]

  def test_saves_exactly_once(self, use_case, repository, alice):
    use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert len(repository.saved) == 1

  def test_the_creator_can_look_the_group_up(self, use_case, repository, alice):
    use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert [group.name for group in repository.get_for_user(alice)] == ["Palawan Trip"]


class TestFailure:
  @pytest.mark.parametrize("blank", ["", "   "])
  def test_a_blank_name_is_rejected(self, use_case, alice, blank: str):
    with pytest.raises(ValueError, match="name cannot be empty"):
      use_case.execute(CreateGroupInput(name=blank, created_by=str(alice)))

  @pytest.mark.parametrize("blank", ["", "   "])
  def test_a_blank_name_writes_nothing(self, use_case, repository, alice, blank: str):
    with pytest.raises(ValueError):
      use_case.execute(CreateGroupInput(name=blank, created_by=str(alice)))

    assert repository.saved == []


class TestUntrustedInput:
  """`created_by` arrives as a raw string, as it would from an HTTP body, so the use case
  is where a malformed id has to be caught."""

  @pytest.mark.parametrize(
    "malformed", ["", "   ", "alice", "not-a-uuid"], ids=["empty", "blank", "name", "words"]
  )
  def test_a_created_by_that_is_not_a_uuid_is_rejected(self, use_case, malformed: str):
    with pytest.raises(ValueError, match="UserId must be"):
      use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=malformed))

  def test_a_malformed_created_by_writes_nothing(self, use_case, repository):
    with pytest.raises(ValueError):
      use_case.execute(CreateGroupInput(name="Palawan Trip", created_by="not-a-uuid"))

    assert repository.saved == []


class TestInput:
  def test_the_input_is_immutable(self, alice):
    input_data = CreateGroupInput(name="Palawan Trip", created_by=str(alice))

    with pytest.raises(Exception):
      input_data.name = "Boracay Trip"
