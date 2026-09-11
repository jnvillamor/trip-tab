from __future__ import annotations

from boto3.dynamodb.conditions import Key

from domain.entities.group import Group, GroupMember
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import GroupId, UserId
from infrastructure.dynamodb.keys import (
  ENTITY_ENUM,
  GSI1PK_GROUP_PREFIX,
  MEMBER_SK_PREFIX,
  METADATA_SK,
  group_pk,
  gsi1pk_user,
  gsi1sk_group,
  member_sk
)
from infrastructure.dynamodb.serialization import from_iso, to_iso
from infrastructure.dynamodb.table import get_table

class DynamoDBGroupRepository(GroupRepository):
  def __init__(self, table=None):
    self._table = table if table is not None else get_table()

  def get_by_id(self, group_id: GroupId) -> Group | None:
    response = self._table.query(
      KeyConditionExpression=Key("PK").eq(f"{group_pk(str(group_id))}")
    )
    items = response.get("Items", [])
    metadata = next((item for item in items if item["SK"] == METADATA_SK), None)
    if metadata is None:
      return None

    members = [
      GroupMember(user_id=UserId(item["user_id"]), joined_at=from_iso(item["joined_at"]))
      for item in items
      if item["SK"].startswith(MEMBER_SK_PREFIX)
    ]

    return Group(
      id=GroupId(metadata["id"]),
      name=metadata["name"],
      created_by=UserId(metadata["created_by"]),
      members=members,
      closed_at=from_iso(metadata["closed_at"]) if metadata.get("closed_at") else None
    )

  def save(self, group: Group) -> None:
    group_id = str(group.id)

    metadata = {
      "PK": group_pk(group_id),
      "SK": METADATA_SK,
      "EntityType": ENTITY_ENUM["Group"],
      "id": group_id,
      "name": group.name,
      "created_by": str(group.created_by),
    }
    if group.closed_at is not None:
      metadata["closed_at"] = to_iso(group.closed_at)
    self._table.put_item(Item=metadata)

    # Save group members
    response = self._table.query(
      KeyConditionExpression=Key("PK").eq(f"{group_pk(group_id)}") & Key("SK").begins_with(MEMBER_SK_PREFIX)
    )
    existing_user_ids = {item["user_id"] for item in response.get("Items", [])}
    desired_members = {str(member.user_id): member for member in group.members}

    for user_id, member in desired_members.items():
      if user_id not in existing_user_ids:
        self._table.put_item(Item={
          "PK": group_pk(group_id),
          "SK": f"{member_sk(user_id)}",
          "EntityType": ENTITY_ENUM["GroupMembership"],
          "group_id": group_id,
          "user_id": user_id,
          "joined_at": to_iso(member.joined_at),
          "GSI1PK": gsi1pk_user(user_id),
          "GSI1SK": gsi1sk_group(group_id)
        })

    for stale_user_id in existing_user_ids - desired_members.keys():
      self._table.delete_item(Key={
        "PK": group_pk(group_id),
        "SK": member_sk(stale_user_id)
      })

  def get_for_user(self, user_id: UserId) -> list[Group]:
    response = self._table.query(
      IndexName="GSI1",
      KeyConditionExpression=Key("GSI1PK").eq(gsi1pk_user(str(user_id)))
      & Key("GSI1SK").begins_with(GSI1PK_GROUP_PREFIX)
    )
    group_ids = [item["group_id"] for item in response.get("Items", [])]
    groups = (self.get_by_id(GroupId(group_id)) for group_id in group_ids)
    return [group for group in groups if group is not None]

  def delete(self, group_id: GroupId) -> None:
    response = self._table.query(
      KeyConditionExpression=Key("PK").eq(group_pk(str(group_id)))
    )
    with self._table.batch_writer() as batch:
      for item in response.get("Items", []):
        batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})