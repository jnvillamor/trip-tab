from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.exceptions import DomainError
from domain.value_objects.ids import ExpenseId, GroupId, UserId

class InvalidExpenseError(DomainError):
  """Raised for invalid expense operations."""