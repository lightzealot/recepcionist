# n8n integration

Every message the AI takes can POST to n8n:

```json
{ "message": {"caller_name", "callback_number", "message",
  "business_name", "timestamp"},
  "context": {"call_id", "transcript_json_path", ...} }
```

## Setup

1. In n8n: Workflows → Import from File →
   `n8n/receptionist-messages.json`.
2. Activate the workflow and copy the **Production** webhook URL.
3. In the worker `.env`:
   `N8N_WEBHOOK_URL=<production URL>` and
   `N8N_WEBHOOK_TOKEN=<a long secret>`.
4. In `config/businesses/<slug>.yaml`, uncomment the `webhook`
   channel under `messages:`.
5. Restart the worker, call in, leave a message, watch it arrive in n8n.

## Extend

After the `Normalize message` node attach whatever you need:
Google Calendar (create event / check availability), Gmail or Slack
(notify the team), Sheets/CRM (log the lead). Starting from the
normalized fields keeps later nodes simple.
