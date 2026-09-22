from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from .models import Conversation, Customer, Product, Priority, Team, Ticket, WorkflowConfig


class TicketWorkflow:
    def __init__(self, config: WorkflowConfig | None = None) -> None:
        self.config = config or WorkflowConfig()
        self.tickets: list[Ticket] = []
        self._sequence = 0

    def create_ticket(self, conversation: Conversation, now: datetime | None = None) -> Ticket:
        now = now or conversation.created_at
        customer, product, issue, evidence, contact = self.extract(conversation)
        missing = self._missing(customer, product, issue)
        waiting = self.config.calendar.business_minutes_between(conversation.created_at, now)
        severity = self._severity(conversation.text)
        sentiment = self._sentiment(conversation.text)
        impact = self._impact(conversation.text)
        priority = self.calculate_priority(severity, sentiment, waiting, impact)
        duplicate = self._find_duplicate(customer, product, issue)
        related, unrelated = self._related_tickets(customer, product, issue)
        self._sequence += 1
        ticket_id = f"T-{self._sequence:05d}"
        allowed = self.config.sla.allowed_minutes[priority]
        sla_start = max(conversation.created_at, self.config.calendar._next_open(conversation.created_at))
        ticket = Ticket(
            id=ticket_id,
            conversation_id=conversation.id,
            customer=customer,
            product=product,
            issue=issue,
            evidence=evidence,
            contact_details=contact,
            severity=severity,
            sentiment=sentiment,
            waiting_minutes=waiting,
            customer_impact=impact,
            priority=priority,
            state="needs_information" if missing else "open",
            missing_information=missing,
            requested_information=[self._request_for(field) for field in missing],
            team=None,
            sla_started_at=sla_start,
            sla_due_at=self.config.calendar.add_business_minutes(sla_start, allowed),
            warning_at=self.config.calendar.add_business_minutes(sla_start, allowed * self.config.sla.warning_percent // 100),
            duplicate_of=duplicate,
            related_ticket_ids=related,
            handoff_summary=self._handoff(customer, product, issue, evidence, contact),
        )
        if not missing and not duplicate:
            ticket.team = self.route(ticket, now)
        self.tickets.append(ticket)
        return ticket

    def update_config(self, config: WorkflowConfig) -> None:
        self.config = config
        for ticket in self.tickets:
            if ticket.breached:
                continue
            allowed = self.config.sla.allowed_minutes[ticket.priority]
            ticket.sla_due_at = self.config.calendar.add_business_minutes(ticket.sla_started_at, allowed)
            ticket.warning_at = self.config.calendar.add_business_minutes(
                ticket.sla_started_at, allowed * self.config.sla.warning_percent // 100
            )

    def refresh(self, now: datetime) -> list[Ticket]:
        for ticket in self.tickets:
            if ticket.state == "needs_information":
                continue
            if now >= ticket.sla_due_at:
                ticket.breached = True
                ticket.state = "escalated"
            elif now >= ticket.warning_at:
                ticket.state = "open"
        return self.tickets

    def extract(self, conversation: Conversation) -> tuple[Customer, Product, str | None, list[str], dict[str, str]]:
        text = conversation.text
        customer = replace(conversation.customer)
        product = replace(conversation.product)
        email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        order = re.search(r"\b(?:order|ord)[\s:#-]*([A-Z0-9-]{4,})\b", text, re.I)
        sku = re.search(r"\b(?:sku|product)[\s:#-]*([A-Z0-9-]{3,})\b", text, re.I)
        if not customer.email and email:
            customer.email = email.group(0).rstrip(".,;:)")
        if not product.order_id and order:
            product.order_id = order.group(1)
        if not product.sku and sku:
            product.sku = sku.group(1)
        if not customer.name:
            name = re.search(r"(?:my name is|this is)\s+([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?)", text, re.I)
            if name:
                customer.name = name.group(1)
        issue = self._issue(text)
        evidence = list(conversation.attachments)
        evidence.extend(re.findall(r"(?:attached|see|screenshot|tracking)[^.!?]{0,100}", text, re.I))
        contact = {key: value for key, value in {"email": customer.email, "phone": customer.phone}.items() if value}
        return customer, product, issue, evidence, contact

    def calculate_priority(self, severity: int, sentiment: float, waiting_minutes: int, impact: int) -> Priority:
        score = severity * 3 + max(0, -sentiment) * 2 + min(waiting_minutes / 240, 4) + impact * 2
        if score >= 18:
            return "urgent"
        if score >= 11:
            return "high"
        if score >= 6:
            return "normal"
        return "low"

    def route(self, ticket: Ticket, now: datetime) -> str | None:
        issue_text = (ticket.issue or "").lower()
        required_skills = {"billing" if any(word in issue_text for word in ("charge", "refund", "payment")) else "technical" if any(word in issue_text for word in ("broken", "error", "login", "not work")) else "orders"}
        candidates: list[tuple[int, Team]] = []
        for team in self.config.teams:
            if not team.available or (team.business_hours_only and not self.config.calendar.is_working_time(now)):
                continue
            match = len(required_skills & {skill.lower() for skill in team.skills})
            if match:
                candidates.append((match, team))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (-item[0], item[1].active_tickets, item[1].name))[1].name

    def _missing(self, customer: Customer, product: Product, issue: str | None) -> list[str]:
        values = {"customer.name": customer.name, "customer.email": customer.email, "product.order_id": product.order_id, "issue": issue}
        return [field for field in self.config.required_fields if not values.get(field)]

    def _issue(self, text: str) -> str | None:
        cleaned = re.sub(r"\s+", " ", text).strip()
        match = re.search(r"(?:issue|problem|help|because|but)[: ]+(.+)", cleaned, re.I)
        issue = match.group(1) if match else cleaned
        issue = re.sub(r"\b(?:order|ord)[\s:#-]*[A-Z0-9-]{4,}\b", "", issue, flags=re.I)
        issue = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", issue)
        issue = re.sub(r"\b(?:email|phone|contact)\b", "", issue, flags=re.I)
        return issue.strip(" .!? ,")[:240] or None

    def _severity(self, text: str) -> int:
        lowered = text.lower()
        if any(word in lowered for word in ("security", "fraud", "outage", "charged twice", "cannot access")):
            return 5
        if any(word in lowered for word in ("broken", "failed", "late", "wrong")):
            return 3
        return 1

    def _sentiment(self, text: str) -> float:
        lowered = text.lower()
        negative = sum(lowered.count(word) for word in ("angry", "furious", "terrible", "frustrated", "unacceptable", "disappointed"))
        positive = sum(lowered.count(word) for word in ("thanks", "great", "happy"))
        return max(-1.0, min(1.0, (positive - negative) / 3))

    def _impact(self, text: str) -> int:
        lowered = text.lower()
        return 3 if any(word in lowered for word in ("all users", "business stopped", "whole team", "outage")) else 2 if any(word in lowered for word in ("subscription", "cannot work", "urgent")) else 1

    def _find_duplicate(self, customer: Customer, product: Product, issue: str | None) -> str | None:
        fingerprint = self._fingerprint(customer, product, issue)
        current_tokens = self._issue_tokens(customer, issue)
        for ticket in self.tickets:
            if self._fingerprint(ticket.customer, ticket.product, ticket.issue) == fingerprint:
                return ticket.id
            if customer.email and customer.email == ticket.customer.email and product.order_id == ticket.product.order_id:
                previous_tokens = self._issue_tokens(ticket.customer, ticket.issue)
                overlap = len(current_tokens & previous_tokens) / max(1, min(len(current_tokens), len(previous_tokens)))
                if overlap >= 0.8:
                    return ticket.id
        return None

    def _issue_tokens(self, customer: Customer, issue: str | None) -> set[str]:
        tokens = set(re.findall(r"[a-z0-9]+", (issue or "").lower()))
        if customer.name:
            tokens -= set(re.findall(r"[a-z0-9]+", customer.name.lower()))
        return tokens - {"the", "a", "an", "and", "to", "for"}

    def _related_tickets(self, customer: Customer, product: Product, issue: str | None) -> tuple[list[str], list[str]]:
        related, unrelated = [], []
        tokens = set(re.findall(r"[a-z0-9]+", (issue or "").lower()))
        for ticket in self.tickets:
            old = set(re.findall(r"[a-z0-9]+", (ticket.issue or "").lower()))
            if customer.email and customer.email == ticket.customer.email and tokens & old:
                related.append(ticket.id)
            elif product.order_id and product.order_id == ticket.product.order_id and tokens & old:
                related.append(ticket.id)
            elif customer.email == ticket.customer.email:
                unrelated.append(ticket.id)
        return related, unrelated

    def _fingerprint(self, customer: Customer, product: Product, issue: str | None) -> str:
        normalized_issue = re.sub(r"\W+", " ", issue or "").lower().strip()
        if customer.name:
            normalized_issue = normalized_issue.replace(customer.name.lower(), "")
        normalized_issue = re.sub(r"\b(?:email|phone|contact|my|name|is)\b", "", normalized_issue)
        raw = "|".join(((customer.email or "").lower().strip(), (product.order_id or "").lower().strip(), re.sub(r"\s+", " ", normalized_issue).strip()))
        return sha256(raw.encode()).hexdigest()

    def _request_for(self, field: str) -> str:
        return {"customer.name": "Please provide your full name.", "customer.email": "Please provide the best email address for updates.", "product.order_id": "Please provide the order number.", "issue": "Please describe the issue and expected outcome."}.get(field, f"Please provide {field}.")

    def _handoff(self, customer: Customer, product: Product, issue: str | None, evidence: list[str], contact: dict[str, str]) -> str:
        masked = {key: self._mask(value) for key, value in contact.items()}
        return f"Customer: {customer.name or 'unknown'} ({masked.get('email', 'no email')}); order: {product.order_id or 'unknown'}; issue: {issue or 'unknown'}; evidence: {len(evidence)} item(s)."

    def _mask(self, value: str) -> str:
        if "@" in value:
            name, domain = value.split("@", 1)
            return f"{name[:1]}***@{domain}"
        return f"***{value[-4:]}"
