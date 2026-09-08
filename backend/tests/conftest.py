"""Shared fixtures for the whole suite.

Ids validate as UUIDs, so they cannot be readable literals. `id_for` derives a stable
uuid5 from a label instead: `alice` is the same id in every test and every run, so a
failure can still be traced back to a name.
"""

from __future__ import annotations

import pytest

from domain.value_objects.ids import GroupId, UserId
from tests.builders import CURRENCY, id_for


@pytest.fixture
def currency() -> str:
  return CURRENCY


@pytest.fixture
def alice() -> UserId:
  return id_for(UserId, "alice")


@pytest.fixture
def bob() -> UserId:
  return id_for(UserId, "bob")


@pytest.fixture
def carol() -> UserId:
  return id_for(UserId, "carol")


@pytest.fixture
def dave() -> UserId:
  return id_for(UserId, "dave")


@pytest.fixture
def group_id() -> GroupId:
  return id_for(GroupId, "palawan-trip")
