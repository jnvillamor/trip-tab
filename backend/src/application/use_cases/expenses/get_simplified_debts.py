from __future__ import annotations

from dataclasses import dataclass

from application.dto.balance_dto import SuggestedPaymentView
from application.exceptions import NotFoundError
from domain.repositories.expense_repository import ExpenseRepository
from domain.repositories.settlement_repository import SettlementRepository
from domain.services.balance_engine import BalanceEngine
from domain.services.settlement_suggester import SettlementSuggester
from domain.value_objects.ids import GroupId

@dataclass(frozen=True)
class GetSimplifiedDebtsInput:
  group_id: str

class GetSimplifiedDebtsUseCase:
  def __init__(
    self,
    expense_repository: ExpenseRepository,
    settlement_repository: SettlementRepository,
  ):
    self._expenses = expense_repository
    self._settlements = settlement_repository

  def execute(self, input_data: GetSimplifiedDebtsInput) -> list[SuggestedPaymentView]:
    group_id = GroupId(input_data.group_id)
    group_expenses = self._expenses.get_for_group(group_id)
    group_settlements = self._settlements.get_for_group(group_id)

    net = BalanceEngine.compute_net_balance(group_expenses, group_settlements)
    suggestions = SettlementSuggester.suggest_payments(net)

    return [SuggestedPaymentView.from_domain(suggestion) for suggestion in suggestions]