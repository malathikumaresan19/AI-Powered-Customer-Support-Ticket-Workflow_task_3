from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal

Priority = Literal["low", "normal", "high", "urgent"]
TicketState = Literal["needs_information", "open", "escalated"]


@dataclass(slots=True)
class Customer:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    account_id: str | None = None


@dataclass(slots=True)
class Product:
    name: str | None = None
    sku: str | None = None
    order_id: str | None = None


@dataclass(slots=True)
class Conversation:
    id: str
    text: str
    created_at: datetime
    customer: Customer = field(default_factory=Customer)
    product: Product = field(default_factory=Product)
    attachments: list[str] = field(default_factory=list)
    source: str = "chat"


@dataclass(slots=True)
class SLAConfig:
    allowed_minutes: dict[Priority, int] = field(default_factory=lambda: {
        "low": 2880,
        "normal": 1440,
        "high": 480,
        "urgent": 120,
    })
    warning_percent: int = 75


@dataclass(slots=True)
class BusinessCalendar:
    timezone: str = "UTC"
    workday_start: time = time(9, 0)
    workday_end: time = time(17, 0)
    workdays: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4})
    holidays: set[date] = field(default_factory=set)

    def is_working_time(self, moment: datetime) -> bool:
        return (
            moment.weekday() in self.workdays
            and moment.date() not in self.holidays
            and self.workday_start <= moment.time() < self.workday_end
        )

    def business_minutes_between(self, start: datetime, end: datetime) -> int:
        if end <= start:
            return 0
        cursor = start
        total = 0
        while cursor.date() <= end.date():
            if cursor.weekday() in self.workdays and cursor.date() not in self.holidays:
                day_start = datetime.combine(cursor.date(), self.workday_start, cursor.tzinfo)
                day_end = datetime.combine(cursor.date(), self.workday_end, cursor.tzinfo)
                left = max(start, day_start)
                right = min(end, day_end)
                if right > left:
                    total += int((right - left).total_seconds() // 60)
            cursor = datetime.combine(cursor.date() + timedelta(days=1), time.min, cursor.tzinfo)
        return total

    def add_business_minutes(self, start: datetime, minutes: int) -> datetime:
        if minutes <= 0:
            return start
        cursor = start
        remaining = minutes
        while remaining:
            if not self.is_working_time(cursor):
                cursor = self._next_open(cursor)
            day_end = datetime.combine(cursor.date(), self.workday_end, cursor.tzinfo)
            available = int((day_end - cursor).total_seconds() // 60)
            if remaining <= available:
                return cursor + timedelta(minutes=remaining)
            remaining -= available
            cursor = self._next_open(datetime.combine(cursor.date() + timedelta(days=1), time.min, cursor.tzinfo))
        return cursor

    def _next_open(self, moment: datetime) -> datetime:
        cursor = moment
        for _ in range(370):
            if cursor.weekday() in self.workdays and cursor.date() not in self.holidays:
                opening = datetime.combine(cursor.date(), self.workday_start, cursor.tzinfo)
                closing = datetime.combine(cursor.date(), self.workday_end, cursor.tzinfo)
                if cursor < opening:
                    return opening
                if opening <= cursor < closing:
                    return cursor
            cursor = datetime.combine(cursor.date() + timedelta(days=1), time.min, cursor.tzinfo)
        raise RuntimeError("No working day found within one year")


@dataclass(slots=True)
class Team:
    name: str
    skills: set[str]
    available: bool = True
    active_tickets: int = 0
    business_hours_only: bool = True


@dataclass(slots=True)
class WorkflowConfig:
    calendar: BusinessCalendar = field(default_factory=BusinessCalendar)
    sla: SLAConfig = field(default_factory=SLAConfig)
    teams: list[Team] = field(default_factory=list)
    required_fields: tuple[str, ...] = ("customer.name", "customer.email", "product.order_id", "issue")


@dataclass(slots=True)
class Ticket:
    id: str
    conversation_id: str
    customer: Customer
    product: Product
    issue: str | None
    evidence: list[str]
    contact_details: dict[str, str]
    severity: int
    sentiment: float
    waiting_minutes: int
    customer_impact: int
    priority: Priority
    state: TicketState
    missing_information: list[str]
    requested_information: list[str]
    team: str | None
    sla_started_at: datetime
    sla_due_at: datetime
    warning_at: datetime
    breached: bool = False
    duplicate_of: str | None = None
    related_ticket_ids: list[str] = field(default_factory=list)
    handoff_summary: str = ""
