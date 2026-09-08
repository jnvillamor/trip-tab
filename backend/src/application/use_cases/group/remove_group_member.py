from __future__ import annotations

from dataclasses import dataclass

from application.dto.group_dto import GroupView
from application.exceptions import NotFoundError
from domain.entities.group import Group
from domain.repositories.expense_repository import ExpenseRepository
from domain.repositories.group_repository import GroupRepository
from domain.repositories.settlement_repository import SettlementRepository
from domain.services.balance_engine import BalanceEngine
from domain.value_objects.ids import GroupId, UserId

@dataclass(frozen=True)
class RemoveGroupMemberInput:
  group_id: str
  user_id: str

class RemoveGroupMemberUseCase:
  """Only remove a member if they have no balances in the group. If they do, raise an error and ask them to settle first."""

  def __init__(
    self,
    group_repository: GroupRepository,
    expense_repository: ExpenseRepository,
    settlement_repository: SettlementRepository,
  ):
    self._groups = group_repository
    self._expenses = expense_repository
    self._settlements = settlement_repository

  def execute(self, input_data: RemoveGroupMemberInput) -> GroupView:
    group_id = GroupId(input_data.group_id)
    user_id = UserId(input_data.user_id)

    group = self._groups.get_by_id(group_id)
    if group is None:
      raise NotFoundError(f"Group with ID {group_id} not found.")

    group_expenses = self._expenses.get_for_group(group_id)
    group_settlements = self._settlements.get_for_group(group_id)
    net_balances = BalanceEngine.compute_net_balance(group_expenses, group_settlements)

    # Check if the user has any non-zero balance in the group
    # BalanceEngine omits users with zero balances, so if the user is not in the net_balances, they have no balance
    has_zero_balance = user_id not in net_balances

    group.remove_member(user_id, has_zero_balance=has_zero_balance)
    self._groups.save(group)
    return GroupView.from_entity(group)