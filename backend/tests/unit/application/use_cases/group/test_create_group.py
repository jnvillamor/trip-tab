from __future__ import annotations

import uuid

import pytest

from application.use_cases.group.create_group import CreateGroupInput, CreateGroupUseCase
from domain.events.group_events import GroupCreated
from domain.value_objects.ids import GroupId
from tests.fakes import InMemoryEventPublisher, InMemoryGroupRepository


@pytest.fixture
def repository() -> InMemoryGroupRepository:
  return InMemoryGroupRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
  return InMemoryEventPublisher()


@pytest.fixture
def use_case(
  repository: InMemoryGroupRepository, publisher: InMemoryEventPublisher
) -> CreateGroupUseCase:
  return CreateGroupUseCase(repository, publisher)


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


class TestEvents:
  """A new group is what a workspace or a notification is built from, so the use case has to
  hand the event on — the entity records it, but only `execute` gets it to a subscriber."""

  def test_publishes_that_the_group_was_created(self, use_case, publisher, alice):
    use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert publisher.types() == ["GroupCreated"]

  def test_the_published_event_names_the_group_and_its_creator(self, use_case, publisher, alice):
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    event = publisher.published[0]
    assert isinstance(event, GroupCreated)
    assert (event.group_id, event.created_by, event.name) == (GroupId(view.id), alice, "Palawan Trip")

  def test_the_published_name_is_the_trimmed_one(self, use_case, publisher, alice):
    """The entity strips the name before recording, so a subscriber never sees the raw input."""
    use_case.execute(CreateGroupInput(name="  Palawan Trip  ", created_by=str(alice)))

    assert publisher.published[0].name == "Palawan Trip"

  def test_publishes_once_per_call(self, use_case, publisher, alice):
    """One `publish` per operation, so a subscriber sees one batch rather than a trickle."""
    use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert len(publisher.batches) == 1
    assert len(publisher.batches[0]) == 1

  def test_publishes_after_the_write(self, alice):
    """A subscriber that reads the group back must already find it stored, so the save has to
    land first."""
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

    use_case = CreateGroupUseCase(NotingRepository(), NotingPublisher())

    use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert timeline == ["save", "publish"]

  def test_each_call_publishes_only_its_own_event(self, use_case, publisher, alice):
    """A second create must not re-announce the first — each group carries its own events."""
    first = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))
    second = use_case.execute(CreateGroupInput(name="Boracay Trip", created_by=str(alice)))

    assert [len(batch) for batch in publisher.batches] == [1, 1]
    assert [event.group_id for event in publisher.published] == [
      GroupId(first.id),
      GroupId(second.id),
    ]

  def test_the_group_keeps_no_events_after_publishing(self, use_case, repository, alice):
    """`pull_events` drains the aggregate, so nothing can be published a second time."""
    view = use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    assert repository.get_by_id(GroupId(view.id)).pull_events() == []


class TestNothingIsPublishedOnFailure:
  @pytest.mark.parametrize("blank", ["", "   "])
  def test_a_blank_name_publishes_nothing(self, use_case, publisher, alice, blank: str):
    """The entity raises before recording, and the use case never reaches `publish`."""
    with pytest.raises(ValueError):
      use_case.execute(CreateGroupInput(name=blank, created_by=str(alice)))

    assert publisher.published == []
    assert publisher.batches == []

  def test_a_malformed_created_by_publishes_nothing(self, use_case, publisher):
    with pytest.raises(ValueError):
      use_case.execute(CreateGroupInput(name="Palawan Trip", created_by="not-a-uuid"))

    assert publisher.published == []
    assert publisher.batches == []

  def test_a_failed_create_does_not_republish_an_earlier_one(self, use_case, publisher, alice):
    use_case.execute(CreateGroupInput(name="Palawan Trip", created_by=str(alice)))

    with pytest.raises(ValueError):
      use_case.execute(CreateGroupInput(name="   ", created_by=str(alice)))

    assert publisher.types() == ["GroupCreated"]


class TestInput:
  def test_the_input_is_immutable(self, alice):
    input_data = CreateGroupInput(name="Palawan Trip", created_by=str(alice))

    with pytest.raises(Exception):
      input_data.name = "Boracay Trip"
