from __future__ import annotations

"""
Centralized every DynamoDB key used in the project.

Item map:
  User                  PK=USER#<id>            SK=METADATA
  Group metadata        PK=GROUP#<id>           SK=METADATA
  Group membership      PK=GROUP#<id>           SK=MEMBER#<user_id>       GSI1PK=USER#<user_id> GSI1SK=GROUP#<id> 
  Expense               PK=GROUP#<id>           SK=EXPENSE#<expense_id>   GSI1PK=USER#<paid_by> GSI1SK=EXPENSE#<expense_id>
  Settlement            PK=GROUP#<id>           SK=SETTLEMENT#<id>        
"""

METADATA_SK = "METADATA"

def user_pk(user_id: str) -> str:
  return f"USER#{user_id}"

def group_pk(group_id: str) -> str:
  return f"GROUP#{group_id}"

def member_sk(user_id: str) -> str:
  return f"MEMBER#{user_id}"

MEMBER_SK_PREFIX = "MEMBER#"

def expense_sk(expense_id: str) -> str:
  return f"EXPENSE#{expense_id}"

EXPENSE_SK_PREFIX = "EXPENSE#"

def settlement_sk(settlement_id: str) -> str:
  return f"SETTLEMENT#{settlement_id}"

SETTLEMENT_SK_PREFIX = "SETTLEMENT#"

def gsi1pk_user(user_id: str) -> str:
  return f"USER#{user_id}"

def gsi1sk_group(group_id: str) -> str:
  return f"GROUP#{group_id}"

GSI1PK_GROUP_PREFIX = "GROUP#"

def gsi1sk_expense(expense_id: str) -> str:
  return f"EXPENSE#{expense_id}"

GS1SK_EXPENSE_PREFIX = "EXPENSE#"

# Entities Keys
ENTITY_ENUM = {
  "Expense": "Expense",
  "Group": "Group",
  "GroupMembership": "GroupMembership",
  "Settlement": "Settlement",
  "User": "User",
}