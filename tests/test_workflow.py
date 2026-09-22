from datetime import date, datetime, time, timezone

from support_workflow import BusinessCalendar, Conversation, Customer, Product, SLAConfig, Team, TicketWorkflow, WorkflowConfig


def moment(day=10, hour=10):
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


def make_config(**kwargs):
    config = WorkflowConfig(
        calendar=BusinessCalendar(workday_start=time(9), workday_end=time(17), holidays={date(2026, 9, 11)}),
        sla=SLAConfig(allowed_minutes={"low": 480, "normal": 240, "high": 120, "urgent": 60}),
        teams=[Team("Billing", {"billing"}, active_tickets=2), Team("Tech", {"technical"}, available=False)],
    )
    return config


def test_extracts_fields_and_requests_missing_information():
    workflow = TicketWorkflow(make_config())
    ticket = workflow.create_ticket(Conversation("c1", "My name is Ada Lovelace. Issue: refund is missing. Order ORD-42, email ada@example.com", moment()), moment())
    assert ticket.customer.name == "Ada Lovelace"
    assert ticket.product.order_id == "ORD-42"
    assert ticket.state == "open"
    assert ticket.team == "Billing"
    assert "***@example.com" in ticket.handoff_summary

    incomplete = workflow.create_ticket(Conversation("c2", "Issue: package is late", moment()), moment())
    assert incomplete.state == "needs_information"
    assert "customer.email" in incomplete.missing_information


def test_business_calendar_skips_weekend_and_holiday():
    calendar = make_config().calendar
    assert calendar.business_minutes_between(moment(10, 16), moment(14, 10)) == 120
    due = calendar.add_business_minutes(moment(10, 16), 120)
    assert due == moment(14, 10)


def test_warning_and_breach_use_live_sla_config():
    workflow = TicketWorkflow(make_config())
    ticket = workflow.create_ticket(Conversation("c1", "My name is Ada. Issue: urgent refund missing. Order ORD-42, email ada@example.com", moment()), moment())
    assert ticket.priority == "normal"
    assert ticket.warning_at == moment(10, 13)
    workflow.refresh(moment(10, 13))
    assert ticket.state == "open"
    workflow.refresh(moment(14, 10))
    assert ticket.state == "escalated" and ticket.breached


def test_duplicate_and_related_unrelated_requests():
    workflow = TicketWorkflow(make_config())
    first = workflow.create_ticket(Conversation("c1", "My name is Ada. Issue: refund missing. Order ORD-42, email ada@example.com", moment()), moment())
    duplicate = workflow.create_ticket(Conversation("c2", "Ada refund missing order ORD-42 ada@example.com", moment()), moment())
    related = workflow.create_ticket(Conversation("c3", "Ada Issue: refund status update order ORD-42 ada@example.com", moment()), moment())
    unrelated = workflow.create_ticket(Conversation("c4", "Ada Issue: login broken ada@example.com", moment()), moment())
    assert duplicate.duplicate_of == first.id
    assert first.id in related.related_ticket_ids
    assert unrelated.related_ticket_ids == []


def test_unavailable_team_and_after_hours_are_not_routed():
    config = make_config()
    workflow = TicketWorkflow(config)
    ticket = workflow.create_ticket(Conversation("c1", "My name is Ada. Issue: login broken. Order ORD-42, email ada@example.com", moment()), moment())
    assert ticket.team is None
    config.teams[1].available = True
    workflow.update_config(config)
    after_hours = workflow.create_ticket(Conversation("c2", "My name is Ada. Issue: login broken. Order ORD-43, email ada@example.com", moment(hour=20)), moment(hour=20))
    assert after_hours.team is None
