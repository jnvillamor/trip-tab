from __future__ import annotations

from dataclasses import dataclass

from application.exceptions import NotFoundError
from domain.events.publisher import EventPublisher
from domain.repositories.expense_repository import ExpenseRepository
from domain.value_objects.ids import ExpenseId, GroupId, UserId

@dataclass(frozen=True)
class DeleteExpenseInput:
  group_id: str
  expense_id: str
  requested_by: str

class DeleteExpenseUseCase:
  def __init__(self, expense_repository: ExpenseRepository, event_publisher: EventPublisher):
    self._expenses = expense_repository
    self._publisher = event_publisher

  def execute(self, input_data: DeleteExpenseInput) -> None:
    group_id = GroupId(input_data.group_id)
    expense_id = ExpenseId(input_data.expense_id)
    requested_by = UserId(input_data.requested_by)

    expense = self._expenses.get_by_id(group_id, expense_id)
    if not expense:
      raise NotFoundError(f"Expense with ID {input_data.expense_id} not found in group {input_data.group_id}.")

    # Check if the user is authorized to delete the expense
    if expense.paid_by != requested_by:
      raise NotFoundError(f"User {input_data.requested_by} is not authorized to delete this expense.")

    expense.mark_deleted()
    self._expenses.save(expense)
    self._publisher.publish(expense.pull_events())