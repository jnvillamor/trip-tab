from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass

from domain.value_objects.ids import UserId
from domain.value_objects.money import DEFAULT_CURRENCY, Money

@dataclass(frozen=True)
class SuggestedPayment:
  from_user: UserId
  to_user: UserId
  amount: Money

class SettlementSuggester:
  """Suggests a set of payments that would settle all debts in a group."""

  @staticmethod
  def suggest_payments(debts: dict[UserId, Money]) -> list[SuggestedPayment]:
    currencies = { debt.currency for debt in debts.values() if not debt.is_zero()}
    if len(currencies) > 1:
      raise ValueError("All debts must be in the same currency to suggest payments.")
    currency = next(iter(currencies), DEFAULT_CURRENCY)

    tiebreak = itertools.count()
    creditors: list[tuple[int, int, UserId]] = []
    debtors: list[tuple[int, int, UserId]] = []

    for user_id, amount in debts.items():
      if amount.is_positive():
        heapq.heappush(creditors, (-amount.amount_cents, next(tiebreak), user_id))
      elif amount.is_negative():
        heapq.heappush(debtors, (amount.amount_cents, next(tiebreak), user_id))

    # Check whether the total debts and credits balance out
    total_credit = sum(-credit[0] for credit in creditors)
    total_debt = sum(-debt[0] for debt in debtors)
    if total_credit != total_debt:
      raise ValueError(
        f"Total credits ({total_credit}) and total debts ({total_debt}) do not balance out."
      )

    payments: list[SuggestedPayment] = []

    while creditors and debtors:
      neg_credit_amount, _, creditor = heapq.heappop(creditors)
      debt_amount, _, debtor = heapq.heappop(debtors)

      credit_amount = -neg_credit_amount
      owed_cents = -debt_amount

      settle_cents = min(credit_amount, owed_cents)
      payments.append(SuggestedPayment(debtor, creditor, Money(settle_cents, currency)))

      remaining_credit = credit_amount - settle_cents
      remaining_debt = owed_cents - settle_cents

      if remaining_credit > 0:
        heapq.heappush(creditors,  (-remaining_credit, next(tiebreak), creditor))
      if remaining_debt > 0:
        heapq.heappush(debtors, (-remaining_debt, next(tiebreak), debtor))

    return payments