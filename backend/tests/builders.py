"""Object mothers for domain tests.

Every builder returns a valid entity by default and takes keyword overrides, so a
test only has to spell out the one field it actually cares about.
"""

from __future__ import annotations

from datetime import datetime, timezone

from domain.entities.expense import Expense
from domain.entities.group import Group, GroupMember
from domain.entities.settlement import Settlement
from domain.entities.user import User
from domain.value_objects.ids import ExpenseId, GroupId, SettlementId, UserId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import SplitLine

CURRENCY = "PHP"
"""Currency used by every builder unless a test overrides it."""


def money(cents: int, currency: str = CURRENCY) -> Money:
  """Shorthand for `Money(cents, CURRENCY)`."""
  return Money(cents, currency)


def split_evenly(total: Money, participants: list[UserId]) -> list[SplitLine]:
  """Even split with the leftover cents handed to the earliest participants."""
  if not participants:
    raise ValueError("split_evenly needs at least one participant")

  base, remainder = divmod(total.amount_cents, len(participants))
  return [
    SplitLine(user_id=uid, owed=Money(base + (1 if i < remainder else 0), total.currency))
    for i, uid in enumerate(participants)
  ]


def make_user(
  *,
  id: UserId | None = None,
  name: str = "Alice",
  email: str = "alice@example.com",
) -> User:
  return User(id=id or UserId.new(), name=name, email=email)


def make_group(
  *,
  id: GroupId | None = None,
  name: str = "Palawan Trip",
  created_by: UserId | None = None,
  members: list[UserId] | None = None,
) -> Group:
  """The creator is always a member; `members` lists any *extra* members."""
  creator = created_by or UserId.new()
  member_ids = [creator, *(members or [])]
  return Group(
    id=id or GroupId.new(),
    name=name,
    created_by=creator,
    members=[GroupMember(user_id=uid) for uid in member_ids],
  )


def make_expense(
  *,
  id: ExpenseId | None = None,
  group_id: GroupId | None = None,
  description: str = "Dinner",
  total: Money | None = None,
  paid_by: UserId | None = None,
  participants: list[UserId] | None = None,
  splits: list[SplitLine] | None = None,
  created_at: datetime | None = None,
  deleted: bool = False,
) -> Expense:
  """Builds an expense whose splits already sum to the total.

  Pass `splits` to control them exactly, or `participants` to have the total split
  evenly between them.
  """
  amount = total if total is not None else money(10_000)
  payer = paid_by or UserId.new()
  lines = splits if splits is not None else split_evenly(amount, participants or [payer])

  return Expense(
    id=id or ExpenseId.new(),
    group_id=group_id or GroupId.new(),
    description=description,
    total=amount,
    paid_by=payer,
    splits=lines,
    created_at=created_at or datetime.now(timezone.utc),
    deleted=deleted,
  )


def make_settlement(
  *,
  id: SettlementId | None = None,
  group_id: GroupId | None = None,
  from_user: UserId | None = None,
  to_user: UserId | None = None,
  amount: Money | None = None,
  settled_at: datetime | None = None,
  reverses: SettlementId | None = None,
  reversed_at: datetime | None = None,
) -> Settlement:
  return Settlement(
    id=id or SettlementId.new(),
    group_id=group_id or GroupId.new(),
    from_user=from_user or UserId.new(),
    to_user=to_user or UserId.new(),
    amount=amount if amount is not None else money(5_000),
    settled_at=settled_at or datetime.now(timezone.utc),
    reverses=reverses,
    reversed_at=reversed_at,
  )
