from __future__ import annotations

import pytest

from domain.entities.user import User
from domain.value_objects.ids import UserId
from infrastructure.dynamodb.user_repository import DynamoDBUserRepository
from tests.builders import make_user


@pytest.fixture
def repository(table) -> DynamoDBUserRepository:
  return DynamoDBUserRepository(table=table)


class TestSave:
  def test_writes_the_user_at_the_documented_key(self, repository, table, alice: UserId):
    repository.save(make_user(id=alice))

    # Spelled out rather than built from `keys`, so changing the physical key format
    # has to break a test instead of silently orphaning every row already stored.
    item = table.get_item(Key={"PK": f"USER#{alice}", "SK": "METADATA"})["Item"]
    assert item["id"] == str(alice)

  def test_stores_the_name_and_email(self, repository, table, alice: UserId):
    repository.save(make_user(id=alice, name="Alice Reyes", email="alice@example.com"))

    item = table.get_item(Key={"PK": f"USER#{alice}", "SK": "METADATA"})["Item"]
    assert (item["name"], item["email"]) == ("Alice Reyes", "alice@example.com")

  def test_saving_the_same_user_twice_updates_the_one_row(self, repository, table, alice: UserId):
    repository.save(make_user(id=alice, name="Alice"))
    repository.save(make_user(id=alice, name="Alice Reyes"))

    # The constant METADATA sort key is what makes this an upsert rather than a
    # second row: one user can only ever have one profile item.
    assert table.scan()["Count"] == 1
    assert repository.get_by_id(alice).name == "Alice Reyes"

  def test_keeps_users_in_separate_rows(self, repository, table, alice: UserId, bob: UserId):
    repository.save(make_user(id=alice, name="Alice"))
    repository.save(make_user(id=bob, name="Bob"))

    assert table.scan()["Count"] == 2
    assert repository.get_by_id(alice).name == "Alice"
    assert repository.get_by_id(bob).name == "Bob"


class TestGetById:
  def test_returns_the_saved_user(self, repository, alice: UserId):
    repository.save(make_user(id=alice, name="Alice Reyes", email="alice@example.com"))

    found = repository.get_by_id(alice)

    assert (found.id, found.name, found.email) == (alice, "Alice Reyes", "alice@example.com")

  def test_rebuilds_a_user_entity(self, repository, alice: UserId):
    repository.save(make_user(id=alice))

    found = repository.get_by_id(alice)

    assert isinstance(found, User)
    assert isinstance(found.id, UserId)

  def test_returns_none_when_the_user_was_never_saved(self, repository, alice: UserId):
    assert repository.get_by_id(alice) is None

  def test_returns_none_when_only_another_user_was_saved(self, repository, alice: UserId, bob: UserId):
    repository.save(make_user(id=bob))

    assert repository.get_by_id(alice) is None

  def test_ignores_rows_that_share_the_partition_but_not_the_sort_key(
    self, repository, table, alice: UserId
  ):
    # A future non-profile row under USER#<id> must not be mistaken for the profile.
    table.put_item(Item={"PK": f"USER#{alice}", "SK": "PREFERENCES", "theme": "dark"})

    assert repository.get_by_id(alice) is None


class TestRoundTrip:
  @pytest.mark.parametrize(
    "name, email",
    [
      ("Alice Reyes", "alice@example.com"),
      ("Ámelie O'Brien-Reyes", "amelie+trips@example.co.uk"),
      ("李雷", "lilei@example.cn"),
    ],
  )
  def test_survives_a_save_and_a_read(self, repository, alice: UserId, name: str, email: str):
    repository.save(make_user(id=alice, name=name, email=email))

    found = repository.get_by_id(alice)

    assert (found.name, found.email) == (name, email)
