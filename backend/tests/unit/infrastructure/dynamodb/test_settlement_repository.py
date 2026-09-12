from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain.entities.settlement import Settlement
from domain.value_objects.ids import GroupId, SettlementId
from domain.value_objects.money import Money
from infrastructure.dynamodb.settlement_repository import DynamoDBSettlementRepository
from tests.builders import make_settlement, money


@pytest.fixture
def repository(table) -> DynamoDBSettlementRepository:
  return DynamoDBSettlementRepository(table=table)


def at(days_ago: int) -> datetime:
  """A fixed, ordered timestamp — `days_ago` counts backwards from a stable now."""
  return datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)


class TestSave:
  def test_writes_the_settlement_at_the_documented_key(self, repository, table, alice, bob, group_id):
    settlement = make_settlement(group_id=group_id, from_user=alice, to_user=bob)

    repository.save(settlement)

    # Spelled out rather than built from `keys`, so changing the physical key format
    # has to break a test instead of silently orphaning every row already stored.
    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"SETTLEMENT#{settlement.id}"})["Item"]
    assert (item["id"], item["group_id"]) == (str(settlement.id), str(group_id))
    assert (item["from_user"], item["to_user"]) == (str(alice), str(bob))

  def test_tags_the_row_with_its_entity_type(self, repository, table, alice, bob, group_id):
    settlement = make_settlement(group_id=group_id, from_user=alice, to_user=bob)

    repository.save(settlement)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"SETTLEMENT#{settlement.id}"})["Item"]
    assert item["EntityType"] == "Settlement"

  def test_stores_the_amount_and_currency(self, repository, table, alice, bob, group_id):
    settlement = make_settlement(
      group_id=group_id, from_user=alice, to_user=bob, amount=money(12_345)
    )

    repository.save(settlement)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"SETTLEMENT#{settlement.id}"})["Item"]
    assert int(item["amount_cents"]) == 12_345
    assert item["currency"] == "PHP"

  def test_leaves_the_reversal_fields_empty_for_a_plain_settlement(
    self, repository, table, alice, bob, group_id
  ):
    settlement = make_settlement(group_id=group_id, from_user=alice, to_user=bob)

    repository.save(settlement)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"SETTLEMENT#{settlement.id}"})["Item"]
    assert item["reverses"] is None
    assert item["reversed_at"] is None

  def test_stores_which_settlement_a_reversal_undoes(self, repository, table, alice, bob, group_id):
    original = make_settlement(group_id=group_id, from_user=alice, to_user=bob)
    reversal = Settlement.create_reversal(SettlementId.new(), original)

    repository.save(reversal)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"SETTLEMENT#{reversal.id}"})["Item"]
    assert item["reverses"] == str(original.id)

  def test_resaving_updates_the_one_row(self, repository, table, alice, bob, group_id):
    settlement = make_settlement(group_id=group_id, from_user=alice, to_user=bob)
    repository.save(settlement)

    settlement.mark_reversed()
    repository.save(settlement)

    assert table.scan()["Count"] == 1
    assert repository.get_by_id(group_id, settlement.id).reversed_at is not None


class TestGetById:
  def test_returns_none_when_the_settlement_was_never_saved(self, repository, group_id):
    assert repository.get_by_id(group_id, SettlementId.new()) is None

  def test_returns_none_when_the_settlement_belongs_to_another_group(
    self, repository, alice, bob, group_id
  ):
    settlement = make_settlement(group_id=group_id, from_user=alice, to_user=bob)
    repository.save(settlement)

    assert repository.get_by_id(GroupId.new(), settlement.id) is None

  def test_restores_every_field(self, repository, alice, bob, group_id):
    settlement = make_settlement(
      group_id=group_id, from_user=alice, to_user=bob, amount=money(7_500), settled_at=at(1)
    )
    repository.save(settlement)

    found = repository.get_by_id(group_id, settlement.id)

    assert isinstance(found, Settlement)
    assert (found.id, found.group_id) == (settlement.id, group_id)
    assert (found.from_user, found.to_user) == (alice, bob)
    assert (found.settled_at, found.reverses, found.reversed_at) == (at(1), None, None)

  def test_restores_money_as_integer_cents(self, repository, alice, bob, group_id):
    settlement = make_settlement(
      group_id=group_id, from_user=alice, to_user=bob, amount=money(12_345)
    )
    repository.save(settlement)

    found = repository.get_by_id(group_id, settlement.id)

    # DynamoDB hands numbers back as Decimal; Money rejects anything but int.
    assert found.amount == Money(12_345, "PHP")
    assert isinstance(found.amount.amount_cents, int)

  def test_restores_a_reversal_as_a_reversal(self, repository, alice, bob, group_id):
    original = make_settlement(group_id=group_id, from_user=alice, to_user=bob)
    reversal = Settlement.create_reversal(SettlementId.new(), original)
    repository.save(reversal)

    found = repository.get_by_id(group_id, reversal.id)

    assert found.is_reversal() is True
    assert found.reverses == original.id
    # A reversal points the other way: bob pays alice back.
    assert (found.from_user, found.to_user) == (bob, alice)

  def test_restores_a_reversed_settlement_as_reversed(self, repository, alice, bob, group_id):
    settlement = make_settlement(
      group_id=group_id, from_user=alice, to_user=bob, reversed_at=at(1)
    )
    repository.save(settlement)

    assert repository.get_by_id(group_id, settlement.id).reversed_at == at(1)


class TestGetForGroup:
  def test_returns_nothing_for_a_group_with_no_settlements(self, repository, group_id):
    assert repository.get_for_group(group_id) == []

  def test_returns_every_settlement_in_the_group(self, repository, alice, bob, group_id):
    first = make_settlement(group_id=group_id, from_user=alice, to_user=bob, settled_at=at(2))
    second = make_settlement(group_id=group_id, from_user=bob, to_user=alice, settled_at=at(1))
    repository.save(first)
    repository.save(second)

    found = repository.get_for_group(group_id)

    assert {settlement.id for settlement in found} == {first.id, second.id}

  def test_excludes_another_groups_settlements(self, repository, alice, bob, group_id):
    mine = make_settlement(group_id=group_id, from_user=alice, to_user=bob)
    theirs = make_settlement(group_id=GroupId.new(), from_user=alice, to_user=bob)
    repository.save(mine)
    repository.save(theirs)

    assert [settlement.id for settlement in repository.get_for_group(group_id)] == [mine.id]

  def test_ignores_non_settlement_rows_in_the_same_partition(
    self, repository, table, alice, bob, group_id
  ):
    repository.save(make_settlement(group_id=group_id, from_user=alice, to_user=bob))
    table.put_item(Item={"PK": f"GROUP#{group_id}", "SK": "METADATA", "name": "Palawan Trip"})
    table.put_item(Item={"PK": f"GROUP#{group_id}", "SK": f"MEMBER#{alice}", "user_id": str(alice)})
    table.put_item(Item={"PK": f"GROUP#{group_id}", "SK": "EXPENSE#1", "description": "Dinner"})

    assert len(repository.get_for_group(group_id)) == 1

  def test_returns_the_newest_first(self, repository, alice, bob, group_id):
    oldest = make_settlement(group_id=group_id, from_user=alice, to_user=bob, settled_at=at(3))
    newest = make_settlement(group_id=group_id, from_user=alice, to_user=bob, settled_at=at(1))
    middle = make_settlement(group_id=group_id, from_user=alice, to_user=bob, settled_at=at(2))
    for settlement in (oldest, newest, middle):
      repository.save(settlement)

    found = repository.get_for_group(group_id)

    assert [settlement.id for settlement in found] == [newest.id, middle.id, oldest.id]

  def test_includes_reversals_alongside_what_they_reverse(self, repository, alice, bob, group_id):
    original = make_settlement(group_id=group_id, from_user=alice, to_user=bob, settled_at=at(2))
    reversal = Settlement.create_reversal(SettlementId.new(), original)
    repository.save(original)
    repository.save(reversal)

    found = repository.get_for_group(group_id)

    assert {settlement.id for settlement in found} == {original.id, reversal.id}
