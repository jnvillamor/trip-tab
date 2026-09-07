from __future__ import annotations

from collections import defaultdict

from domain.entities.expense import Expense
from domain.entities.settlement import Settlement
from domain.value_objects.ids import UserId
from domain.value_objects.money import CurrencyMismatchError, Money

class BalanceEngine:
  """ Pure domain service: derives balance from expense and settlment data."""

  @staticmethod
  def _resolve_currency(expenses: list[Expense], settlements: list[Settlement]) -> str:
    currencies = { expense.total.currency for expense in expenses if not expense.deleted } | { settlement.amount.currency for settlement in settlements }
    if len(currencies) > 1:
      raise CurrencyMismatchError(
        f"Cannot compute balances across mixed currencies: { sorted(currencies) }."
      )

    return next(iter(currencies), "USD")

  @staticmethod
  def compute_net_balance(expenses: list[Expense], settlements: list[Settlement]) -> dict[UserId, Money]:
    """ Computes the net balance of each user given a list of expenses and settlements. """
    currency = BalanceEngine._resolve_currency(expenses, settlements)
    net_cents = dict[UserId, int] = defaultdict(int)

    for expense in expenses:
      if expense.deleted:
        continue

      for split in expense.splits:
        if split.user_id == expense.paid_by:
          continue

        net_cents[split.user_id] -= split.owed.amount_cents
        net_cents[expense.paid_by] += split.owed.amount_cents

      for settlement in settlements:
        net_cents[settlement.from_user] += settlement.amount.amount_cents
        net_cents[settlement.to_user] -= settlement.amount.amount_cents

    return {uid: Money(cents, currency) for uid, cents in net_cents.items() if cents != 0}

  @staticmethod
  def compute_pairwise_balance(
    expenses: list[Expense], settlements: list[Settlement]
  ) -> dict[tuple[UserId, UserId], Money]:
    """ Computes the pairwise balance between users given a list of expenses and settlements. """
    currency = BalanceEngine._resolve_currency(expenses, settlements)
    owed_cents: dict[tuple[UserId, UserId], int] = defaultdict(int)

    for expense in expenses:
      if expense.deleted:
        continue

      for split in expense.splits:
        if split.user_id == expense.paid_by:
          continue

        owed_cents[(split.user_id, expense.paid_by)] += split.owed.amount_cents

    for settlement in settlements:
      owed_cents[(settlement.to_user, settlement.from_user)] -= settlement.amount.amount_cents

    result: dict[tuple[UserId, UserId], Money] = {}
    seen_pairs: set[frozenset[UserId]] = set()

    for (user_a, user_b) in list(owed_cents.keys()):
      pair_key = frozenset({user_a, user_b})
      if pair_key in seen_pairs:
        continue 

      seen_pairs.add(pair_key)

      a_owes_b = owed_cents.get((user_a, user_b), 0)
      b_owes_a = owed_cents.get((user_b, user_a), 0)
      net_cents = a_owes_b - b_owes_a

      if net_cents > 0:
        result[(user_a, user_b)] = Money(net_cents, currency)
      elif net_cents < 0:
        result[(user_b, user_a)] = Money(-net_cents, currency)
        # net_cetns == 0 means no one owes anything, so we don't add it to the result

    return result
