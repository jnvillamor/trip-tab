from __future__ import annotations

from domain.entities.user import User
from domain.repositories.user_repository import UserRepository
from domain.value_objects.ids import UserId
from infrastructure.dynamodb.keys import ENTITY_ENUM, METADATA_SK, user_pk
from infrastructure.dynamodb.table import get_table

class DynamoDBUserRepository(UserRepository):
  def __init__(self, table=None):
    self._table = table if table is not None else get_table()

  def get_by_id(self, user_id: UserId) -> User | None:
    response = self._table.get_item(Key={"PK": user_pk(str(user_id)), "SK": METADATA_SK})
    item = response.get("Item")
    return self._to_entity(item) if item else None

  def save(self, user: User) -> None:
    self._table.put_item(Item={
      "PK": user_pk(str(user.id)),
      "SK": METADATA_SK,
      "EntityType": ENTITY_ENUM["User"],
      "id": str(user.id),
      "name": user.name,
      "email": user.email
    })

  @staticmethod
  def _to_entity(item: dict) -> User:
    return User(
      id=UserId(item["id"]),
      name=item["name"],
      email=item["email"]
    )