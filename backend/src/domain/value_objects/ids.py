from __future__ import annotations 

import uuid
from dataclasses import dataclass

def _new_uuid() -> str:
  return str(uuid.uuid4())

def _validate_uuid(value: str, type_name: str) -> None: 
  """Validates that the provided value is a valid UUID string. Raises ValueError if not."""
  if not isinstance(value, str):
    raise ValueError(f"{type_name} must be a string, got {type(value).__name__}")
  try:
    uuid.UUID(value)
  except ValueError as e:
    raise ValueError(f"{type_name} must be a valid UUID string, got '{value!r}'") from e

@dataclass(frozen=True)
class UserId:
  value: str

  def __post_init__(self) -> None:
    _validate_uuid(self.value, "UserId")

  @classmethod
  def new(cls) -> "UserId":
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value


@dataclass(frozen=True)
class GroupId:
  value: str

  def __post_init__(self) -> None:
    _validate_uuid(self.value, "GroupId")

  @classmethod
  def new(cls) -> "GroupId": 
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value


@dataclass(frozen=True)
class ExpenseId:
  value: str

  def __post_init__(self) -> None:
    _validate_uuid(self.value, "ExpenseId")

  @classmethod
  def new(cls) -> "ExpenseId":
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value

@dataclass(frozen=True)
class SettlementId:
  value: str

  def __post_init__(self) -> None:
    _validate_uuid(self.value, "SettlementId")

  @classmethod
  def new(cls) -> "SettlementId":
    return cls(_new_uuid())

  def __str__(self) -> str:
    return self.value