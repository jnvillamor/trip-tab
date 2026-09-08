from __future__ import annotations

import pytest

from domain.value_objects.ids import UserId
from tests.builders import make_user


class TestCreation:
  def test_keeps_the_supplied_details(self, alice: UserId):
    user = make_user(id=alice, name="Alice Reyes", email="alice@example.com")

    assert (user.id, user.name, user.email) == (alice, "Alice Reyes", "alice@example.com")

  @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
  def test_rejects_a_blank_name(self, blank: str):
    with pytest.raises(ValueError, match="name cannot be empty"):
      make_user(name=blank)

  @pytest.mark.parametrize("bad_email", ["alice", "alice.example.com", ""])
  def test_rejects_an_address_without_an_at_sign(self, bad_email: str):
    with pytest.raises(ValueError, match="Invalid email"):
      make_user(email=bad_email)


class TestRename:
  def test_replaces_the_name(self):
    user = make_user(name="Alice")

    user.rename("Alice Reyes")

    assert user.name == "Alice Reyes"

  @pytest.mark.parametrize("blank", ["", "   "])
  def test_rejects_a_blank_name_and_leaves_the_old_one(self, blank: str):
    user = make_user(name="Alice")

    with pytest.raises(ValueError, match="name cannot be empty"):
      user.rename(blank)

    assert user.name == "Alice"
