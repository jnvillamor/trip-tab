from __future__ import annotations

import pytest

from application.exceptions import NotFoundError
from application.use_cases.group.add_group_member import (
  AddGroupMemberInput,
  AddGroupMemberUseCase,
)
from domain.entities.group import GroupMembershipError
from domain.events.group_events import MemberAdded
from domain.value_objects.ids import GroupId, UserId
from tests.builders import id_for, make_group
from tests.fakes import InMemoryEventPublisher, InMemoryGroupRepository


@pytest.fixture
def group(alice, group_id: GroupId):
  return make_group(id=group_id, name="Palawan Trip", created_by=alice)


@pytest.fixture
def repository(group) -> InMemoryGroupRepository:
  return InMemoryGroupRepository([group])


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
  return InMemoryEventPublisher()


@pytest.fixture
def use_case(
  repository: InMemoryGroupRepository, publisher: InMemoryEventPublisher
) -> AddGroupMemberUseCase:
  return AddGroupMemberUseCase(repository, publisher)


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


class TestEvents:
  """Adding a member is what a notification is built from, so the use case has to hand the
  event on — the entity records it, but only `execute` gets it to a subscriber."""

  def test_publishes_that_the_member_was_added(self, use_case, publisher, group_id, bob):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert publisher.types() == ["MemberAdded"]

  def test_the_published_event_names_the_group_and_the_member(
    self, use_case, publisher, group_id, bob
  ):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    event = publisher.published[0]
    assert isinstance(event, MemberAdded)
    assert (event.group_id, event.member_id) == (group_id, bob)

  def test_publishes_once_per_call(self, use_case, publisher, group_id, bob):
    """One `publish` per operation, so a subscriber sees one batch rather than a trickle."""
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert len(publisher.batches) == 1
    assert len(publisher.batches[0]) == 1

  def test_publishes_after_the_write(self, repository, publisher, group_id, bob):
    """A subscriber that reads the group back must find the new member already there, so the
    save has to land first."""
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

    noting_repository = NotingRepository(
      [make_group(id=group_id, name="Palawan Trip", created_by=id_for(UserId, "alice"))]
    )
    use_case = AddGroupMemberUseCase(noting_repository, NotingPublisher())

    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert timeline == ["save", "publish"]

  def test_each_call_publishes_only_its_own_event(
    self, use_case, publisher, group_id, bob, carol
  ):
    """A second add must not re-announce the first — the entity is drained by `pull_events`
    and a rebuilt group starts clean."""
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(carol)))

    assert [len(batch) for batch in publisher.batches] == [1, 1]
    assert [event.member_id for event in publisher.published] == [bob, carol]

  def test_the_group_keeps_no_events_after_publishing(self, use_case, repository, group_id, bob):
    """`pull_events` drains the aggregate, so nothing can be published a second time."""
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert repository.get_by_id(group_id).pull_events() == []


class TestNothingIsPublishedOnFailure:
  def test_an_unknown_group_publishes_nothing(self, use_case, publisher, bob):
    with pytest.raises(NotFoundError):
      use_case.execute(
        AddGroupMemberInput(group_id=str(id_for(GroupId, "unknown-group")), user_id=str(bob))
      )

    assert publisher.published == []
    assert publisher.batches == []

  def test_a_duplicate_member_publishes_nothing(self, use_case, publisher, group_id, alice):
    """The entity raises before recording, and the use case never reaches `publish`."""
    with pytest.raises(GroupMembershipError):
      use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(alice)))

    assert publisher.published == []

  def test_a_malformed_id_publishes_nothing(self, use_case, publisher, bob):
    with pytest.raises(ValueError):
      use_case.execute(AddGroupMemberInput(group_id="not-a-uuid", user_id=str(bob)))

    assert publisher.published == []

  def test_a_failed_second_add_does_not_republish_the_first(
    self, use_case, publisher, group_id, bob
  ):
    use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    with pytest.raises(GroupMembershipError):
      use_case.execute(AddGroupMemberInput(group_id=str(group_id), user_id=str(bob)))

    assert publisher.types() == ["MemberAdded"]


class TestInput:
  def test_the_input_is_immutable(self, group_id, bob):
    input_data = AddGroupMemberInput(group_id=str(group_id), user_id=str(bob))

    with pytest.raises(Exception):
      input_data.user_id = "someone-else"
