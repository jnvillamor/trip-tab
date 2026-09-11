from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain.entities.expense import Expense
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money
from infrastructure.dynamodb.expense_repository import DynamoDBExpenseRepository
from tests.builders import make_expense, money


@pytest.fixture
def repository(table) -> DynamoDBExpenseRepository:
  return DynamoDBExpenseRepository(table=table)


def at(days_ago: int) -> datetime:
  """A fixed, ordered timestamp — `days_ago` counts backwards from a stable now."""
  return datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)


class TestSave:
  def test_writes_the_expense_at_the_documented_key(self, repository, table, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice, description="Dinner")

    repository.save(expense)

    # Spelled out rather than built from `keys`, so changing the physical key format
    # has to break a test instead of silently orphaning every row already stored.
    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"EXPENSE#{expense.id}"})["Item"]
    assert (item["id"], item["group_id"], item["description"]) == (
      str(expense.id), str(group_id), "Dinner",
    )

  def test_stores_the_total_and_currency(self, repository, table, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice, total=money(12_345))

    repository.save(expense)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"EXPENSE#{expense.id}"})["Item"]
    assert int(item["total_cents"]) == 12_345
    assert item["currency"] == "PHP"

  def test_stores_a_line_per_split(self, repository, table, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, paid_by=alice, participants=[alice, bob], total=money(10_000)
    )

    repository.save(expense)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"EXPENSE#{expense.id}"})["Item"]
    assert sorted((s["user_id"], int(s["owed"])) for s in item["splits"]) == sorted(
      [(str(alice), 5_000), (str(bob), 5_000)]
    )

  def test_indexes_the_expense_under_the_payer(self, repository, table, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice)

    repository.save(expense)

    item = table.get_item(Key={"PK": f"GROUP#{group_id}", "SK": f"EXPENSE#{expense.id}"})["Item"]
    # Per the item map: an expense is indexed by who paid, and its GSI1 sort key
    # carries the EXPENSE# prefix that `get_by_user` filters on.
    assert (item["GSI1PK"], item["GSI1SK"]) == (f"USER#{alice}", f"EXPENSE#{expense.id}")

  def test_resaving_updates_the_one_row(self, repository, table, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice, description="Dinner")
    repository.save(expense)

    expense.edit(description="Late dinner")
    repository.save(expense)

    assert table.scan()["Count"] == 1
    assert repository.get_by_id(group_id, expense.id).description == "Late dinner"


class TestGetById:
  def test_returns_none_when_the_expense_was_never_saved(self, repository, group_id):
    assert repository.get_by_id(group_id, ExpenseId.new()) is None

  def test_returns_none_when_the_expense_belongs_to_another_group(self, repository, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice)
    repository.save(expense)

    assert repository.get_by_id(GroupId.new(), expense.id) is None

  def test_restores_every_field(self, repository, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id,
      paid_by=alice,
      participants=[alice, bob],
      total=money(10_000),
      description="Dinner",
      created_at=at(1),
    )
    repository.save(expense)

    found = repository.get_by_id(group_id, expense.id)

    assert isinstance(found, Expense)
    assert (found.id, found.group_id, found.description) == (expense.id, group_id, "Dinner")
    assert (found.paid_by, found.created_at, found.deleted) == (alice, at(1), False)

  def test_restores_money_as_integer_cents(self, repository, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice, total=money(12_345))
    repository.save(expense)

    found = repository.get_by_id(group_id, expense.id)

    # DynamoDB hands numbers back as Decimal; Money rejects anything but int.
    assert found.total == Money(12_345, "PHP")
    assert isinstance(found.total.amount_cents, int)

  def test_restores_the_splits(self, repository, alice, bob, group_id):
    expense = make_expense(
      group_id=group_id, paid_by=alice, participants=[alice, bob], total=money(10_001)
    )
    repository.save(expense)

    found = repository.get_by_id(group_id, expense.id)

    assert sorted((str(s.user_id), s.owed.amount_cents) for s in found.splits) == sorted(
      (str(s.user_id), s.owed.amount_cents) for s in expense.splits
    )

  def test_restores_a_deleted_expense_as_deleted(self, repository, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice)
    expense.mark_deleted()
    repository.save(expense)

    assert repository.get_by_id(group_id, expense.id).deleted is True


class TestGetForGroup:
  def test_returns_nothing_for_a_group_with_no_expenses(self, repository, group_id):
    assert repository.get_for_group(group_id) == []

  def test_returns_every_expense_in_the_group(self, repository, alice, group_id):
    first = make_expense(group_id=group_id, paid_by=alice, created_at=at(2))
    second = make_expense(group_id=group_id, paid_by=alice, created_at=at(1))
    repository.save(first)
    repository.save(second)

    found = repository.get_for_group(group_id)

    assert {expense.id for expense in found} == {first.id, second.id}

  def test_excludes_another_groups_expenses(self, repository, alice, group_id):
    mine = make_expense(group_id=group_id, paid_by=alice)
    theirs = make_expense(group_id=GroupId.new(), paid_by=alice)
    repository.save(mine)
    repository.save(theirs)

    assert [expense.id for expense in repository.get_for_group(group_id)] == [mine.id]

  def test_ignores_non_expense_rows_in_the_same_partition(self, repository, table, alice, group_id):
    repository.save(make_expense(group_id=group_id, paid_by=alice))
    table.put_item(Item={"PK": f"GROUP#{group_id}", "SK": "METADATA", "name": "Palawan Trip"})
    table.put_item(Item={"PK": f"GROUP#{group_id}", "SK": f"MEMBER#{alice}", "user_id": str(alice)})

    assert len(repository.get_for_group(group_id)) == 1

  def test_returns_the_newest_first(self, repository, alice, group_id):
    oldest = make_expense(group_id=group_id, paid_by=alice, created_at=at(3))
    newest = make_expense(group_id=group_id, paid_by=alice, created_at=at(1))
    middle = make_expense(group_id=group_id, paid_by=alice, created_at=at(2))
    for expense in (oldest, newest, middle):
      repository.save(expense)

    found = repository.get_for_group(group_id)

    assert [expense.id for expense in found] == [newest.id, middle.id, oldest.id]

  def test_since_drops_anything_older(self, repository, alice, group_id):
    old = make_expense(group_id=group_id, paid_by=alice, created_at=at(5))
    recent = make_expense(group_id=group_id, paid_by=alice, created_at=at(1))
    repository.save(old)
    repository.save(recent)

    found = repository.get_for_group(group_id, since=at(2))

    assert [expense.id for expense in found] == [recent.id]

  def test_since_keeps_an_expense_created_exactly_then(self, repository, alice, group_id):
    expense = make_expense(group_id=group_id, paid_by=alice, created_at=at(2))
    repository.save(expense)

    assert [found.id for found in repository.get_for_group(group_id, since=at(2))] == [expense.id]


class TestGetByUser:
  def test_returns_nothing_for_a_user_who_paid_for_nothing(self, repository, alice):
    assert repository.get_by_user(alice) == []

  def test_returns_the_expenses_the_user_paid(self, repository, alice, bob, group_id):
    hers = make_expense(group_id=group_id, paid_by=alice, created_at=at(1))
    his = make_expense(group_id=group_id, paid_by=bob, created_at=at(2))
    repository.save(hers)
    repository.save(his)

    assert [expense.id for expense in repository.get_by_user(alice)] == [hers.id]

  def test_spans_every_group_the_user_paid_in(self, repository, alice, group_id):
    here = make_expense(group_id=group_id, paid_by=alice, created_at=at(1))
    elsewhere = make_expense(group_id=GroupId.new(), paid_by=alice, created_at=at(2))
    repository.save(here)
    repository.save(elsewhere)

    assert {expense.id for expense in repository.get_by_user(alice)} == {here.id, elsewhere.id}

  def test_returns_the_newest_first(self, repository, alice, group_id):
    older = make_expense(group_id=group_id, paid_by=alice, created_at=at(3))
    newer = make_expense(group_id=group_id, paid_by=alice, created_at=at(1))
    repository.save(older)
    repository.save(newer)

    assert [expense.id for expense in repository.get_by_user(alice)] == [newer.id, older.id]
