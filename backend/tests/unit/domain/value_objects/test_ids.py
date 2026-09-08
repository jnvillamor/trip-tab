from __future__ import annotations

import uuid

import pytest

from domain.value_objects.ids import ExpenseId, GroupId, SettlementId, UserId

ID_TYPES = [UserId, GroupId, ExpenseId, SettlementId]

CANONICAL = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
OTHER = "9f8e7d6c-5b4a-4392-8271-0e02b2c3d479"


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
class TestIdentifiers:
  def test_new_generates_a_uuid4(self, id_type):
    generated = id_type.new()

    assert uuid.UUID(generated.value).version == 4

  def test_new_is_unique(self, id_type):
    assert id_type.new() != id_type.new()

  def test_accepts_a_canonical_uuid_string(self, id_type):
    assert id_type(CANONICAL).value == CANONICAL

  def test_compares_by_value(self, id_type):
    assert id_type(CANONICAL) == id_type(CANONICAL)
    assert id_type(CANONICAL) != id_type(OTHER)

  def test_is_hashable_so_it_can_key_a_dict(self, id_type):
    assert {id_type(CANONICAL): 1}[id_type(CANONICAL)] == 1

  def test_is_frozen(self, id_type):
    with pytest.raises(Exception):
      id_type(CANONICAL).value = OTHER

  def test_str_is_the_raw_value(self, id_type):
    assert str(id_type(CANONICAL)) == CANONICAL


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
class TestValidation:
  @pytest.mark.parametrize(
    "malformed",
    ["", "   ", "abc", "not-a-uuid", CANONICAL[:-1], CANONICAL + "extra"],
    ids=["empty", "blank", "short", "words", "truncated", "overlong"],
  )
  def test_rejects_a_value_that_is_not_a_uuid(self, id_type, malformed: str):
    with pytest.raises(ValueError, match="must be a valid UUID string"):
      id_type(malformed)

  @pytest.mark.parametrize(
    "not_a_string",
    [None, 123, 4.5, b"f47ac10b-58cc-4372-a567-0e02b2c3d479", uuid.UUID(CANONICAL)],
    ids=["none", "int", "float", "bytes", "uuid-object"],
  )
  def test_rejects_a_value_that_is_not_a_string(self, id_type, not_a_string):
    with pytest.raises(ValueError, match="must be a string"):
      id_type(not_a_string)

  def test_rejects_being_wrapped_around_another_id(self, id_type):
    """`UserId(UserId(...))` used to nest silently, so every later lookup missed."""
    already_an_id = id_type(CANONICAL)

    with pytest.raises(ValueError, match="must be a string"):
      id_type(already_an_id)

  def test_the_error_names_the_type_that_was_rejected(self, id_type):
    with pytest.raises(ValueError, match=id_type.__name__):
      id_type("not-a-uuid")

  def test_a_generated_id_survives_a_round_trip(self, id_type):
    generated = id_type.new()

    assert id_type(str(generated)) == generated


def test_different_id_types_never_compare_equal():
  assert UserId(CANONICAL) != GroupId(CANONICAL)


class TestNonCanonicalSpellings:
  """`uuid.UUID()` parses these, so validation lets them through — but the raw string is
  stored as given, so two spellings of the same UUID are two different ids."""

  @pytest.mark.parametrize(
    "spelling",
    [CANONICAL.upper(), CANONICAL.replace("-", ""), "{%s}" % CANONICAL, "urn:uuid:%s" % CANONICAL],
    ids=["uppercase", "no-hyphens", "braced", "urn"],
  )
  def test_is_accepted(self, spelling: str):
    assert UserId(spelling).value == spelling

  @pytest.mark.parametrize(
    "spelling",
    [CANONICAL.upper(), CANONICAL.replace("-", ""), "{%s}" % CANONICAL, "urn:uuid:%s" % CANONICAL],
    ids=["uppercase", "no-hyphens", "braced", "urn"],
  )
  def test_does_not_equal_the_canonical_form(self, spelling: str):
    assert UserId(spelling) != UserId(CANONICAL)
