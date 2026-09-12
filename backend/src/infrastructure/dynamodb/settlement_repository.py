from __future__ import annotations 

from boto3.dynamodb.conditions import Key

from domain.entities.settlement import Settlement
from domain.repositories.settlement_repository import SettlementRepository
from domain.value_objects.ids import GroupId, SettlementId, UserId
from domain.value_objects.money import Money
from infrastructure.dynamodb.keys import (
  ENTITY_ENUM,
  SETTLEMENT_SK_PREFIX,
  group_pk,
  settlement_sk,
)
from infrastructure.dynamodb.serialization import from_iso, to_iso, from_decimal, to_decimal
from infrastructure.dynamodb.table import get_table

class DynamoDBSettlementRepository(SettlementRepository):
  def __init__(self, table=None):
    self._table = table if table is not None else get_table()

  def get_by_id(self, group_id: GroupId, settlement_id: SettlementId) -> Settlement | None:
    response = self._table.get_item(
      Key={
        "PK": group_pk(str(group_id)),
        "SK": settlement_sk(str(settlement_id))
      }
    )
    item = response.get("Item")
    return self._to_entity(item) if item else None

  def save(self, settlement: Settlement) -> None:
    self._table.put_item(
      Item={
        "PK": group_pk(str(settlement.group_id)),
        "SK": settlement_sk(str(settlement.id)),
        "EntityType": ENTITY_ENUM["Settlement"],
        "id": str(settlement.id),
        "group_id": str(settlement.group_id),
        "from_user": str(settlement.from_user),
        "to_user": str(settlement.to_user),
        "amount_cents": to_decimal(settlement.amount.amount_cents),
        "currency": settlement.amount.currency,
        "settled_at": to_iso(settlement.settled_at) if settlement.settled_at is not None else None,
        "reverses": str(settlement.reverses) if settlement.reverses is not None else None,
        "reversed_at": to_iso(settlement.reversed_at) if settlement.reversed_at is not None else None,
      }
    )

  def get_for_group(self, group_id: GroupId) -> list[Settlement]:
    """Returns all settlements for a group, newest first."""
    response = self._table.query(
      KeyConditionExpression=Key("PK").eq(group_pk(str(group_id)))
      & Key("SK").begins_with(SETTLEMENT_SK_PREFIX),
    )
    settlements = [self._to_entity(item) for item in response.get("Items", [])]
    return sorted(settlements, key=lambda s: s.settled_at, reverse=True)

  def _to_entity(self, item: dict) -> Settlement:
    return Settlement(
      id=SettlementId(item["id"]),
      group_id=GroupId(item["group_id"]),
      from_user=UserId(item["from_user"]),
      to_user=UserId(item["to_user"]),
      amount=Money(amount_cents=from_decimal(item["amount_cents"]), currency=item["currency"]),
      settled_at=from_iso(item["settled_at"]),
      reverses=SettlementId(item["reverses"]) if item.get("reverses") is not None else None,
      reversed_at=from_iso(item["reversed_at"]) if item.get("reversed_at") is not None else None
    )