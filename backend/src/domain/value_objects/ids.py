from __future__ import annotations 

import uuid
from dataclasses import dataclass

def _new_uuid() -> str:
  return str(uuid.uuid4())

@dataclass(frozen=True)
class UserId:
  value: str

  @classmethod
  def new(cls) -> "UserId":
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value


@dataclass(frozen=True)
class GroupId:
  value: str

  @classmethod
  def new(cls) -> "GroupId": 
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value


@dataclass(frozen=True)
class ExpenseId:
  value: str

  @classmethod
  def new(cls) -> "ExpenseId":
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value

@dataclass(frozen=True)
class SettlementId:
  value: str

  @classmethod
  def new(cls) -> "SettlementId":
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value