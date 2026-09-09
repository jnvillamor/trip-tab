from __future__ import annotations 

from dataclasses import dataclass

from application.dto.expense_dto import ExpenseView
from application.exceptions import NotFoundError, NotAuthorizedError
from application.support.split_strategy_builder import build_split_strategy
from domain.repositories.expense_repository import ExpenseRepository
from domain.repositories.group_repository import GroupRepository
from domain.value_objects.ids import ExpenseId, GroupId, UserId
from domain.value_objects.money import Money

@dataclass(frozen=True)
class EditExpenseInput:
  group_id: str
  expense_id: str
  requested_by: str
  description: str | None = None
  total_cents: str | None = None
  currency: str | None = None
  participant_ids: list[str] | None = None
  split_type: str | None = None
  exact_amounts_cents: dict[str, int] | None = None
  percentages: dict[str, float] | None = None

class EditExpenseUseCase:
  def __init__(self, expense_repository: ExpenseRepository, group_repository: GroupRepository):
    self._expenses = expense_repository
    self._groups = group_repository

  def execute(self, input_data: EditExpenseInput) -> ExpenseView:
    group_id = GroupId(input_data.group_id)
    expense = self._expenses.get_by_id(GroupId(input_data.group_id), ExpenseId(input_data.expense_id))
    if not expense:
      raise NotFoundError(f"Expense with ID {input_data.expense_id} not found in group {input_data.group_id}.")

    group = self._groups.get_by_id(group_id)
    if group is None:
      raise NotFoundError(f"Group with ID {input_data.group_id} not found.")

    requested_by = UserId(input_data.requested_by)
    if not group.has_member(requested_by):
      raise NotAuthorizedError(f"User {input_data.requested_by} is not a member of group {input_data.group_id}.")

    total = (
      Money(input_data.total_cents, input_data.currency or expense.total.currency)
      if input_data.total_cents is not None
      else None
    )

    participants = (
      [UserId(pid) for pid in input_data.participant_ids]
      if input_data.participant_ids is not None
      else None
    )

    # Check if all participant belong to the group
    if participants is not None:
      for participant in participants:
        if not group.has_member(participant):
          raise NotAuthorizedError(f"User {participant} is not a member of group {input_data.group_id}.")

    strategy=None
    if input_data.split_type:
      strategy = build_split_strategy(
        split_type=input_data.split_type,
        currency=(total or expense.total).currency,
        exact_amounts_cents=input_data.exact_amounts_cents,
        percentages=input_data.percentages,
      )

    expense.edit(
      description=input_data.description,
      total=total,
      participants=participants,
      strategy=strategy,
    )
    self._expenses.save(expense)
    return ExpenseView.from_entity(expense)