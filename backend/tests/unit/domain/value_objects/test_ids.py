from __future__ import annotations

import uuid

import pytest

from domain.value_objects.ids import ExpenseId, GroupId, SettlementId, UserId

ID_TYPES = [UserId, GroupId, ExpenseId, SettlementId]


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
class TestIdentifiers:
  def test_new_generates_a_uuid4(self, id_type):
    generated = id_type.new()
    assert uuid.UUID(generated.value).version == 4

  def test_new_is_unique(self, id_type):
    assert id_type.new() != id_type.new()

  def test_compares_by_value(self, id_type):
    assert id_type("abc") == id_type("abc")
    assert id_type("abc") != id_type("xyz")

  def test_is_hashable_so_it_can_key_a_dict(self, id_type):
    assert {id_type("abc"): 1}[id_type("abc")] == 1

  def test_is_frozen(self, id_type):
    with pytest.raises(Exception):
      id_type("abc").value = "xyz"

  def test_str_is_the_raw_value(self, id_type):
    assert str(id_type("abc")) == "abc"


def test_different_id_types_never_compare_equal():
  assert UserId("abc") != GroupId("abc")
