from __future__ import annotations

from dataclasses import dataclass
from application.dto.settlement_dto import SettlementView 
from application.exceptions import NotAuthorizedError, NotFoundError
from domain.entities.settlement import Settlement
from domain.events.publisher import EventPublisher
from domain.repositories.group_repository import GroupRepository
from domain.repositories.settlement_repository import SettlementRepository
from domain.value_objects.ids import GroupId, SettlementId, UserId
from domain.value_objects.money import DEFAULT_CURRENCY, Money

@dataclass(frozen=True)
class RecordSettlementInput:
  group_id: str
  from_user: str
  to_user: str
  amount_cents: int
  currency: str = DEFAULT_CURRENCY

class RecordSettlementUseCase:
  def __init__(
    self,
    group_repository: GroupRepository,
    settlement_repository: SettlementRepository,
    event_publisher: EventPublisher,
  ):
    self._groups = group_repository
    self._settlements = settlement_repository
    self._publisher = event_publisher

  def execute(self, input_data: RecordSettlementInput) -> SettlementView:
    group_id = GroupId(input_data.group_id)
    group = self._groups.get_by_id(group_id)
    if group is None:
      raise NotFoundError(f"Group with ID {input_data.group_id} not found.")

    from_user = UserId(input_data.from_user)
    to_user = UserId(input_data.to_user)

    for user in (from_user, to_user):
      if not group.has_member(user):
        raise NotAuthorizedError(f"User {user} is not a member of group {input_data.group_id}.")

    amount = Money(input_data.amount_cents, (input_data.currency or "").strip() or DEFAULT_CURRENCY)
    settlement = Settlement.create(
      id=SettlementId.new(),
      group_id=group_id,
      from_user=from_user,
      to_user=to_user,
      amount=amount,
    )
    self._settlements.save(settlement)
    self._publisher.publish(settlement.pull_events())
    return SettlementView.from_entity(settlement)