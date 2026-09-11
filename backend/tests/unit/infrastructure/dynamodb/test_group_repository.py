from __future__ import annotations

import pytest

from domain.entities.group import Group
from domain.value_objects.ids import GroupId, UserId
from infrastructure.dynamodb.group_repository import DynamoDBGroupRepository
from tests.builders import make_group


@pytest.fixture
def repository(table) -> DynamoDBGroupRepository:
  return DynamoDBGroupRepository(table=table)


def rows(table, group_id: GroupId) -> list[dict]:
  """Every raw item stored under a group's partition, sorted by sort key."""
  from boto3.dynamodb.conditions import Key

  items = table.query(KeyConditionExpression=Key("PK").eq(f"GROUP#{group_id}"))["Items"]
  return sorted(items, key=lambda item: item["SK"])


class TestSave:
  def test_writes_the_group_at_the_documented_key(self, repository, table, alice: UserId):
    group = make_group(created_by=alice, name="Palawan Trip")

    repository.save(group)

    # Spelled out rather than built from `keys`, so changing the physical key format
    # has to break a test instead of silently orphaning every row already stored.
    item = table.get_item(Key={"PK": f"GROUP#{group.id}", "SK": "METADATA"})["Item"]
    assert (item["id"], item["name"], item["created_by"]) == (
      str(group.id), "Palawan Trip", str(alice),
    )

  def test_writes_one_membership_row_per_member(self, repository, table, alice, bob):
    group = make_group(created_by=alice, members=[bob])

    repository.save(group)

    assert [item["SK"] for item in rows(table, group.id)] == (
      sorted([f"MEMBER#{alice}", f"MEMBER#{bob}"]) + ["METADATA"]
    )

  def test_membership_rows_carry_the_gsi1_attributes(self, repository, table, alice: UserId):
    group = make_group(created_by=alice)

    repository.save(group)

    member = table.get_item(Key={"PK": f"GROUP#{group.id}", "SK": f"MEMBER#{alice}"})["Item"]
    # Attribute names are case-sensitive and must match the index key schema exactly,
    # or the row is simply absent from GSI1 and `get_for_user` goes blind.
    assert (member["GSI1PK"], member["GSI1SK"]) == (f"USER#{alice}", f"GROUP#{group.id}")

  def test_adding_a_member_adds_its_row(self, repository, table, alice, bob):
    group = make_group(created_by=alice)
    repository.save(group)

    group.add_member(bob)
    repository.save(group)

    assert [item["SK"] for item in rows(table, group.id)] == (
      sorted([f"MEMBER#{alice}", f"MEMBER#{bob}"]) + ["METADATA"]
    )

  def test_removing_a_member_deletes_its_row(self, repository, table, alice, bob):
    group = make_group(created_by=alice, members=[bob])
    repository.save(group)

    group.remove_member(bob, has_zero_balance=True)
    repository.save(group)

    assert [item["SK"] for item in rows(table, group.id)] == [f"MEMBER#{alice}", "METADATA"]

  def test_resaving_updates_the_one_metadata_row(self, repository, table, alice: UserId):
    group = make_group(created_by=alice, name="Palawan")
    repository.save(group)

    group.name = "Palawan Trip"
    repository.save(group)

    metadata = [item for item in rows(table, group.id) if item["SK"] == "METADATA"]
    assert len(metadata) == 1
    assert metadata[0]["name"] == "Palawan Trip"


class TestGetById:
  def test_returns_none_when_the_group_was_never_saved(self, repository):
    assert repository.get_by_id(GroupId.new()) is None

  def test_returns_the_saved_group(self, repository, alice: UserId):
    group = make_group(created_by=alice, name="Palawan Trip")
    repository.save(group)

    found = repository.get_by_id(group.id)

    assert isinstance(found, Group)
    assert (found.id, found.name, found.created_by) == (group.id, "Palawan Trip", alice)

  def test_restores_every_member(self, repository, alice, bob, carol):
    group = make_group(created_by=alice, members=[bob, carol])
    repository.save(group)

    found = repository.get_by_id(group.id)

    assert sorted(str(uid) for uid in found.member_ids()) == sorted(
      str(uid) for uid in (alice, bob, carol)
    )

  def test_restores_the_join_time(self, repository, alice: UserId):
    group = make_group(created_by=alice)
    joined_at = group.members[0].joined_at
    repository.save(group)

    found = repository.get_by_id(group.id)

    assert found.members[0].joined_at == joined_at

  def test_an_open_group_comes_back_open(self, repository, alice: UserId):
    group = make_group(created_by=alice)
    repository.save(group)

    found = repository.get_by_id(group.id)

    assert found.closed_at is None
    assert found.is_closed is False

  def test_a_closed_group_keeps_its_closing_time(self, repository, alice: UserId):
    group = make_group(created_by=alice)
    group.close()
    repository.save(group)

    found = repository.get_by_id(group.id)

    assert found.closed_at == group.closed_at

  def test_ignores_another_groups_rows(self, repository, alice, bob):
    wanted = make_group(created_by=alice, name="Palawan Trip")
    other = make_group(created_by=bob, name="Baguio Trip")
    repository.save(wanted)
    repository.save(other)

    found = repository.get_by_id(wanted.id)

    assert found.name == "Palawan Trip"
    assert found.member_ids() == [alice]


class TestGetForUser:
  def test_returns_nothing_for_a_user_in_no_groups(self, repository, alice: UserId):
    assert repository.get_for_user(alice) == []

  def test_returns_the_groups_the_user_belongs_to(self, repository, alice, bob):
    mine = make_group(created_by=alice, name="Palawan Trip")
    shared = make_group(created_by=bob, members=[alice], name="Baguio Trip")
    theirs = make_group(created_by=bob, name="Sagada Trip")
    for group in (mine, shared, theirs):
      repository.save(group)

    found = repository.get_for_user(alice)

    assert sorted(group.name for group in found) == ["Baguio Trip", "Palawan Trip"]

  def test_stops_returning_a_group_the_user_left(self, repository, alice, bob):
    group = make_group(created_by=bob, members=[alice])
    repository.save(group)

    group.remove_member(alice, has_zero_balance=True)
    repository.save(group)

    assert repository.get_for_user(alice) == []


class TestDelete:
  def test_removes_the_group_and_all_its_rows(self, repository, table, alice, bob):
    group = make_group(created_by=alice, members=[bob])
    repository.save(group)

    repository.delete(group.id)

    assert rows(table, group.id) == []
    assert repository.get_by_id(group.id) is None

  def test_leaves_other_groups_alone(self, repository, table, alice, bob):
    doomed = make_group(created_by=alice)
    survivor = make_group(created_by=bob, name="Baguio Trip")
    repository.save(doomed)
    repository.save(survivor)

    repository.delete(doomed.id)

    assert repository.get_by_id(survivor.id).name == "Baguio Trip"

  def test_deleting_a_group_that_was_never_saved_is_a_no_op(self, repository):
    repository.delete(GroupId.new())
