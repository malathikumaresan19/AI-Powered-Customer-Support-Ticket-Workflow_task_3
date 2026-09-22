# Support Ticket Workflow

A dependency-light Python workflow that turns unresolved conversations into structured support tickets.

## Features

- Extracts customer, order, product, issue, evidence, and contact details from supplied structured fields and message text.
- Requests missing mandatory information before routing.
- Scores priority from severity, sentiment, waiting time, customer impact, and live SLA rules.
- Calculates SLA time using configurable working hours, weekends, and holidays.
- Emits a warning at the configured percentage and escalates breached tickets.
- Routes by skill match, availability, workload, and business hours.
- Detects duplicate requests, groups related issues, separates unrelated issues, and masks sensitive handoff details.

## Run

```powershell
python -m pytest
python -m support_workflow.cli examples/conversation.json
```

The workflow is a library first. Import `TicketWorkflow` and replace `WorkflowConfig` at runtime to change SLA rules, calendar settings, or teams without restarting the process.
