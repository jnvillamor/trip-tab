from __future__ import annotations

from dataclasses import dataclass

from application.dto.expense_dto import ExpenseView
from application.exceptions import NotFoundError, NotAuthorizedError
from application.support.split_strategy_builder import build_split_strategy 
from domain.entities.expense import Expense
from domain.repositories.expense_repository import ExpenseRepository
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import GroupId, UserId, ExpenseId
from domain.value_objects.money import Money
from domain.value_objects.split_strategy import SplitType

@dataclass(frozen=True)
class CreateExpenseInput:
  group_id: str
  description: str
  total_cents: int
  paid_by: str
  participants_ids: list[str]
  split_type: str # "equal", "exact", "percentage"
  exact_amounts_cents: dict[str, int] | None = None
  percentages: dict[str, float] | None = None
  
class CreateExpenseUseCase:
  def __init__(
    self,
    group_repository: GroupRepository,
    expense_repository: ExpenseRepository,
  ):
    self._groups = group_repository
    self._expenses = expense_repository

  def execute(self, input_data: CreateExpenseInput) -> ExpenseView:
    group_id = GroupId(input_data.group_id)
    group = self._groups.get_by_id(group_id)
    if not group:
      raise NotFoundError(f"Group with ID {group_id} not found.")

    paid_by = UserId(input_data.paid_by)
    participants = [UserId(user_id) for user_id in input_data.participants_ids]

    # Check if all participants, including the payer, are members of the group
    for participant in { paid_by, *participants }:
      if not group.has_member(participant):
        raise NotAuthorizedError(f"User {participant} is not a member of the group {group_id}.")

    total = Money(amount_cents=input_data.total_cents, currency="PHP")
    strategy = build_split_strategy(
      split_type=input_data.split_type,
      currency=total.currency,
      exact_amounts_cents=input_data.exact_amounts_cents,
      percentages=input_data.percentages,
    )

    expense = Expense.create(
      id=ExpenseId.new(),
      group_id=group_id,
      description=input_data.description,
      total=total,
      paid_by=paid_by,
      participants=participants,
      split_strategy=strategy
    )
    self._expenses.save(expense)
    return ExpenseView.from_entity(expense)