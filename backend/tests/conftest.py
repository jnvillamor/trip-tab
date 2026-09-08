"""Shared fixtures for the whole suite.

Ids are readable literals rather than uuids so an assertion failure names the person
it is talking about.
"""

from __future__ import annotations

import pytest

from domain.value_objects.ids import GroupId, UserId
from tests.builders import CURRENCY


@pytest.fixture
def currency() -> str:
  return CURRENCY


@pytest.fixture
def alice() -> UserId:
  return UserId("alice")


@pytest.fixture
def bob() -> UserId:
  return UserId("bob")


@pytest.fixture
def carol() -> UserId:
  return UserId("carol")


@pytest.fixture
def dave() -> UserId:
  return UserId("dave")


@pytest.fixture
def group_id() -> GroupId:
  return GroupId("palawan-trip")
