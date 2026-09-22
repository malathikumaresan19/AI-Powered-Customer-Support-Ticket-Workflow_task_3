from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime

from .engine import TicketWorkflow
from .models import Conversation, Customer, Product


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: support-workflow <conversation.json>")
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
    conversation = Conversation(
        id=payload["id"],
        text=payload["text"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        customer=Customer(**payload.get("customer", {})),
        product=Product(**payload.get("product", {})),
        attachments=payload.get("attachments", []),
        source=payload.get("source", "chat"),
    )
    ticket = TicketWorkflow().create_ticket(conversation, now=datetime.now(conversation.created_at.tzinfo))
    print(json.dumps(asdict(ticket), default=str, indent=2))


if __name__ == "__main__":
    main()
