from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from domain.value_objects.ids import UserId
from domain.value_objects.money import Money

CurrencyCode = Annotated[str, AfterValidator(str.upper)]
"""An upper-cased ISO currency code."""


class _View(BaseModel):
  """Base for read models: immutable and strict about unknown fields.

  Deliberately does not trim strings: a view reports what the domain holds, so whitespace
  that got stored is a bug to surface, not one to hide.
  """

  model_config = ConfigDict(frozen=True, extra="forbid")


class BalanceView(_View):
  user_id: str
  amount_cents: int
  currency: CurrencyCode


class PairwiseBalanceView(_View):
  debtor: str
  creditor: str
  amount_cents: int
  currency: CurrencyCode


class GroupBalancesView(_View):
  net: list[BalanceView]
  pairwise: list[PairwiseBalanceView]

  @classmethod
  def from_domain(
    cls,
    net_balances: dict[UserId, Money],
    pairwise_balances: dict[tuple[UserId, UserId], Money],
  ) -> "GroupBalancesView":
    return cls(
      net=[
        BalanceView(user_id=str(uid), amount_cents=amount.amount_cents, currency=amount.currency)
        for uid, amount in net_balances.items()
      ],
      pairwise=[
        PairwiseBalanceView(
          debtor=str(debtor),
          creditor=str(creditor),
          amount_cents=amount.amount_cents,
          currency=amount.currency,
        )
        for (debtor, creditor), amount in pairwise_balances.items()
      ],
    )
