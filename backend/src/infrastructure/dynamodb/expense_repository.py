from __future__ import annotations

from boto3.dynamodb.conditions import Key

from domain.entities.expense import Expense, SplitLine
from domain.repositories.expense_repository import ExpenseRepository
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money
from infrastructure.dynamodb.keys import (
  ENTITY_ENUM,
  EXPENSE_SK_PREFIX,
  group_pk,
  gsi1pk_user,
  gsi1sk_expense,
  expense_sk,
)
from infrastructure.dynamodb.serialization import from_decimal, from_iso, to_decimal, to_iso
from infrastructure.dynamodb.table import get_table

class DynamoDBExpenseRepository(ExpenseRepository):
  def __init__(self, table=None):
    self._table = table if table is not None else get_table()

  def get_by_id(self, group_id: GroupId, expense_id: ExpenseId) -> Expense | None:
    response = self._table.get_item(
      Key={
        "PK": group_pk(str(group_id)),
        "SK": expense_sk(str(expense_id)),
      }
    )
    item = response.get("Item")
    return self._to_entity(item) if item is not None else None

  def save(self, expense: Expense) -> None:
    group_id = str(expense.group_id)
    self._table.put_item(
      Item={
        "PK": group_pk(group_id),
        "SK": expense_sk(str(expense.id)),
        "EntityType": ENTITY_ENUM["Expense"],
        "id": str(expense.id),
        "group_id": group_id,
        "description": expense.description,
        "total_cents": to_decimal(expense.total.amount_cents),
        "currency": expense.total.currency,
        "paid_by": str(expense.paid_by),
        "splits": [
          {
            "user_id": str(split.user_id),
            "owed_cents": to_decimal(split.owed.amount_cents),
          } for split in expense.splits
        ],
        "created_at": to_iso(expense.created_at),
        "deleted": expense.deleted,
        "GSI1PK": gsi1pk_user(str(expense.paid_by)),
        "GSI1SK": gsi1sk_expense(str(expense.id)),
      }
    )

  def get_for_group(self, group_id: GroupId, *, since=None):
    """Returns all expenses for a group, optionally filtered by a since timestamp."""
    response = self._table.query(
      KeyConditionExpression=Key("PK").eq(group_pk(str(group_id))) 
      & Key("SK").begins_with(EXPENSE_SK_PREFIX),
    )
    items = response.get("Items", [])
    expenses = [self._to_entity(item) for item in items]
    if since is not None:
      expenses = [expense for expense in expenses if expense.created_at >= since]
    return sorted(expenses, key=lambda e: e.created_at, reverse=True) 

  def get_by_user(self, user_id: UserId):
    """Returns all expenses this user paid"""
    response = self._table.query(
      IndexName="GSI1",
      KeyConditionExpression=Key("GSI1PK").eq(gsi1pk_user(str(user_id)))
      & Key("GSI1SK").begins_with(EXPENSE_SK_PREFIX),
    )
    expenses = [self._to_entity(item) for item in response.get("Items", [])]
    return sorted(expenses, key=lambda e: e.created_at, reverse=True)

  def _to_entity(self, item: dict) -> Expense:
    currency = item["currency"]
    return Expense(
      id=ExpenseId(item["id"]),
      group_id=GroupId(item["group_id"]),
      description=item["description"],
      total=Money(from_decimal(item["total_cents"]), currency),
      paid_by=UserId(item["paid_by"]),
      splits=[
        SplitLine(
          user_id=UserId(split["user_id"]),
          owed=Money(from_decimal(split["owed_cents"]), currency)
        )
        for split in item["splits"]
      ],
      created_at=from_iso(item["created_at"]),
      deleted=item.get("deleted", False)
    )