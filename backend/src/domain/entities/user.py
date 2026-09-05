from __future__ import annotations

from dataclasses import dataclass

from domain.value_objects.ids import UserId

@dataclass
class User:
  id: UserId
  name: str
  email: str

  def __post_init__(self) -> None:
    if not self.name.strip():
      raise ValueError("user name cannot be empty")
    if "@" not in self.email:
      raise ValueError(f"Invalid email: {self.email}")

  def rename(self, new_name: str) -> None:
    if not new_name.strip():
      raise ValueError("User name cannot be empty")
    self.name = new_name