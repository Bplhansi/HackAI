# medAssist AI backend: API and integration guide

Base URL: `http://localhost:8000` locally, your Render/Railway URL when deployed.
All routes return JSON. Errors look like `{"detail": "message"}`.

**Login:** in demo mode (`DEMO_MODE=true`) no login is needed. With Supabase Auth,
send `Authorization: Bearer <supabase access token>` on every request.

## The flow

1. User types a message -> `POST /chat` -> AI proposes an action. **Nothing is saved.**
2. Frontend shows a confirmation form pre-filled from `parameters`.
3. User confirms -> `POST /medications/confirm-add` or `/confirm-update`.
4. Only when that returns `"success": true` does the frontend say "saved".

## For Person 1 (frontend)

| Route | Body | Returns |
|---|---|---|
| `GET /health` | | `{status, ai, database}` (`ai` must say `nemotron` in the real demo) |
| `POST /chat` | `{"message": "...", "conversation_context": [{"role":"user","content":"..."}]}` | the AI result (below) |
| `GET /medications` | | `{"medications": [{id, name, quantity_collected, collection_date, daily_quantity, estimated_end_date, days_left, details, archived}]}` (includes archived ones) |
| `POST /medications/confirm-add` | `{medication_name, quantity_collected, collection_date, daily_quantity, details?}` | 201 `{success, medication, reminders, message}` |
| `POST /medications/confirm-update` | `{medication_id, quantity_collected, collection_date, daily_quantity?, details?}` | `{success, medication, reminders, message}` |
| `POST /medications/{id}/archive` | `{"archived": true or false, "details"?: {...}}` | `{success, medication}`: moves it to or from Medication History |
| `DELETE /medications/{id}` | | `{success: true}` |
| `GET /reminders` | | `{"reminders": [{id, medication_id, medication_name, kind, status, remind_on, snoozed_until, estimated_end_date, days_left}]}`: only reminders due today |
| `POST /reminders/{id}/acknowledge` | | `{success, reminder}` |
| `POST /reminders/{id}/snooze` | optional `{"days": 1-7}` (default 1) | `{success, reminder}` |

`collection_date` is `"YYYY-MM-DD"`. `details` is any small JSON object the frontend
wants kept with the medication (schedule, dose times, collection history), up to 20 KB.
The backend stores it and gives it back, but never uses it for maths: `daily_quantity`
must already be the average per day. Archived medications get no reminders and are
not shown to the AI; recording a new collection (`confirm-update`) restores them. Call `GET /reminders` when the page loads and
every few minutes. It also creates repeat reminders, so no separate scheduler is needed.

Status codes to handle: `422` invalid input (show the message), `404` not found,
`409` duplicate name (tell the user to update instead) or inactive reminder,
`503` AI unavailable (offer the manual form), `500` save failed (nothing was saved).

### AI result from `POST /chat`

```json
{
  "action": "add_medication",
  "parameters": {"medication_name": "ExampleMed", "quantity_collected": 60,
                 "collection_date": "2026-10-25", "daily_quantity": 1, "medication_id": null},
  "missing_fields": [],
  "requires_confirmation": true,
  "message": "Please confirm these medication details before I save them."
}
```

`action` is always one of `add_medication`, `update_medication_supply`,
`ask_clarification`, `general_response`. Show `message` in the chat.
For `add_medication` open the confirm-add form; for `update_medication_supply`
open the confirm-update form using `parameters.medication_id`.
The user can edit every field before confirming.

## For Person 2 (AI)

The backend does this in `main.py`:

```python
from ai_agent import interpret_medication_message   # falls back to ai_stub.py if missing

result = await interpret_medication_message(
    user_message=req.message,
    current_date=date.today().isoformat(),     # "YYYY-MM-DD"
    medications=ai_meds,                       # this user's saved medications
    conversation_context=req.conversation_context,
)
```

- It is called with **keyword arguments** and must be `async` and return a **dict**.
- Each item in `medications` is
  `{id, name, daily_quantity, quantity_collected, collection_date, estimated_end_date}`.
  `id` is the value to return as `parameters.medication_id`. Never invent one.
- If the function raises, the backend returns 503 and the frontend shows an error.
- The backend double-checks the result: unknown actions become `general_response`, and
  an `update_medication_supply` whose `medication_id` isn't one of the user's own
  becomes `ask_clarification`.
- To switch from the stub to the real module, just have `ai_agent.py` in `backend/`
  and make sure `USE_STUB_AI` is not `true`. `GET /health` shows which is active.

## Reminder rules

- First reminders: 14 and 7 days before the estimated end date (dates already in the
  past are skipped; if both are past, one reminder is created for today).
- After the final 7 days begin, a `repeat` reminder appears. It is never created
  while another reminder for that medication is still pending or snoozed.
  After the user acknowledges, the next comes `REPEAT_EVERY_DAYS` later (default 3),
  and at most `MAX_REPEAT_REMINDERS` (default 5) are made.
- `confirm-update` cancels the old open reminders and creates new ones.
- A new collection **replaces** the old supply and counts from its collection date.
  Leftover tablets are not carried over.