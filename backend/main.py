"""medAssist AI backend (FastAPI).

Flow:  React -> /chat (AI proposes, nothing saved)
       React shows a confirmation form
       React -> /medications/confirm-add or /confirm-update (the ONLY routes that save)

The AI never touches the database and never does maths. Python does both.
"""
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

import supply  # noqa: E402
from db import get_database  # noqa: E402
from models import ArchiveRequest, ChatRequest, ConfirmAdd, ConfirmUpdate, SnoozeRequest  # noqa: E402

# ---------- settings (all from environment variables) ----------
REPEAT_EVERY_DAYS = int(os.getenv("REPEAT_EVERY_DAYS", "3"))
MAX_REPEAT_REMINDERS = int(os.getenv("MAX_REPEAT_REMINDERS", "5"))
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
DEMO_USER_ID = os.getenv("DEMO_USER_ID", "00000000-0000-0000-0000-000000000001")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]

# ---------- AI module (written by Person 2) ----------
AI_MODE = "stub"
if os.getenv("USE_STUB_AI", "false").lower() != "true":
    try:
        from ai_agent import interpret_medication_message

        AI_MODE = "nemotron"
    except ImportError as err:
        print(f"WARNING: could not import ai_agent ({err}). Using the stub AI.")
if AI_MODE == "stub":
    from ai_stub import interpret_medication_message

ALLOWED_ACTIONS = {"add_medication", "update_medication_supply",
                   "ask_clarification", "general_response"}

db = get_database()

app = FastAPI(title="medAssist AI backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- who is the user? ----------
def get_current_user(authorization: str | None = Header(default=None)) -> str:
    """Returns the user's id. Never trust an id sent in the request body."""
    if authorization and authorization.lower().startswith("bearer "):
        user_id = db.verify_token(authorization[7:])
        if user_id:
            return user_id
        raise HTTPException(401, "Invalid or expired login")
    if DEMO_MODE:
        return DEMO_USER_ID  # one shared demo user (see README)
    raise HTTPException(401, "Please log in")


# ---------- helpers ----------
def _med_view(med: dict, today: date) -> dict:
    """A medication row plus days_left, for the frontend cards."""
    end = date.fromisoformat(med["estimated_end_date"])
    out = {k: v for k, v in med.items() if k != "user_id"}
    out["details"] = med.get("details") or {}
    out["archived"] = bool(med.get("archived"))
    out["days_left"] = supply.days_left(end, today)
    return out


def _create_reminders(user_id: str, med_id: str, end: date, today: date) -> list[dict]:
    return [db.insert_reminder(user_id, med_id, kind, d)
            for kind, d in supply.reminder_dates(end, today)]


def _clean_ai_result(result, owned_meds: list[dict]) -> dict:
    """Don't trust the AI output just because it is JSON."""
    if not isinstance(result, dict) or result.get("action") not in ALLOWED_ACTIONS:
        return {"action": "general_response", "parameters": {}, "missing_fields": [],
                "requires_confirmation": False,
                "message": "Sorry, I didn't understand that. Could you rephrase?"}

    if result["action"] == "update_medication_supply":
        med_id = (result.get("parameters") or {}).get("medication_id")
        if med_id not in {m["id"] for m in owned_meds}:
            names = ", ".join(m["name"] for m in owned_meds) or "none saved yet"
            return {"action": "ask_clarification", "parameters": {},
                    "missing_fields": ["medication_id"], "requires_confirmation": False,
                    "message": f"Which medication do you mean? Saved medications: {names}."}
    return result


# ---------- routes ----------
@app.get("/health")
def health():
    return {"status": "ok", "ai": AI_MODE, "database": db.name}


@app.post("/chat")
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user)):
    """Ask the AI to interpret a message. Saves NOTHING."""
    # Only this user's medications, and not the ones moved to Medication History.
    meds = [m for m in db.list_medications(user_id) if not m.get("archived")]
    # Give the AI only what it needs (no user_id).
    ai_meds = [{k: m[k] for k in ("id", "name", "daily_quantity", "quantity_collected",
                                  "collection_date", "estimated_end_date")} for m in meds]
    try:
        result = await interpret_medication_message(
            user_message=req.message,
            current_date=date.today().isoformat(),
            medications=ai_meds,
            conversation_context=req.conversation_context,
        )
    except Exception as err:
        # Log the error type only: messages may contain medication details.
        print(f"AI call failed: {type(err).__name__}")
        raise HTTPException(503, "The AI assistant is unavailable right now. "
                                 "Please try again in a moment.")
    return _clean_ai_result(result, ai_meds)


@app.get("/medications")
def list_medications(user_id: str = Depends(get_current_user)):
    today = date.today()
    return {"medications": [_med_view(m, today) for m in db.list_medications(user_id)]}


@app.post("/medications/confirm-add", status_code=201)
def confirm_add(body: ConfirmAdd, user_id: str = Depends(get_current_user)):
    today = date.today()
    existing = {m["name"].lower() for m in db.list_medications(user_id) if not m.get("archived")}
    if body.medication_name.lower() in existing:
        raise HTTPException(409, f"{body.medication_name} is already being tracked. "
                                 "Update it with the new collection instead.")
    end = supply.estimate_end_date(body.collection_date, body.quantity_collected,
                                   body.daily_quantity)
    try:
        med = db.insert_medication(user_id, {
            "name": body.medication_name,
            "quantity_collected": body.quantity_collected,
            "collection_date": body.collection_date.isoformat(),
            "daily_quantity": body.daily_quantity,
            "estimated_end_date": end.isoformat(),
            "details": body.details or {},
            "archived": False,
        })
        reminders = _create_reminders(user_id, med["id"], end, today)
    except Exception as err:
        print(f"Database error: {type(err).__name__}")
        raise HTTPException(500, "Could not save. Nothing has been confirmed.")
    # We only get here after the database write worked.
    return {"success": True, "medication": _med_view(med, today), "reminders": reminders,
            "message": f"Saved. Estimated supply end date: {end.isoformat()}."}


@app.post("/medications/confirm-update")
def confirm_update(body: ConfirmUpdate, user_id: str = Depends(get_current_user)):
    today = date.today()
    med = db.get_medication(user_id, body.medication_id)  # checks ownership
    if not med:
        raise HTTPException(404, "Medication not found")
    daily = body.daily_quantity or float(med["daily_quantity"])
    end = supply.estimate_end_date(body.collection_date, body.quantity_collected, daily)
    changes = {
        "quantity_collected": body.quantity_collected,
        "collection_date": body.collection_date.isoformat(),
        "daily_quantity": daily,
        "estimated_end_date": end.isoformat(),
        "archived": False,  # a new collection brings a restored medication back
    }
    if body.details is not None:
        changes["details"] = body.details
    try:
        updated = db.update_medication(user_id, med["id"], changes)
        if not updated:
            raise HTTPException(404, "Medication not found")
        db.cancel_open_reminders(user_id, med["id"])  # old reminders are now wrong
        reminders = _create_reminders(user_id, med["id"], end, today)
    except HTTPException:
        raise
    except Exception as err:
        print(f"Database error: {type(err).__name__}")
        raise HTTPException(500, "Could not save. Nothing has been confirmed.")
    return {"success": True, "medication": _med_view(updated, today), "reminders": reminders,
            "message": f"Updated. New estimated supply end date: {end.isoformat()}."}


@app.post("/medications/{med_id}/archive")
def archive_medication(med_id: str, body: ArchiveRequest,
                       user_id: str = Depends(get_current_user)):
    """Move a medication to (or back from) Medication History. Nothing is deleted."""
    changes = {"archived": body.archived}
    if body.details is not None:
        changes["details"] = body.details
    updated = db.update_medication(user_id, med_id, changes)  # checks ownership
    if not updated:
        raise HTTPException(404, "Medication not found")
    # Archived medications get no reminders. Restored ones get new reminders
    # when the user records their next collection (confirm-update).
    db.cancel_open_reminders(user_id, med_id)
    return {"success": True, "medication": _med_view(updated, date.today())}


@app.delete("/medications/{med_id}")
def delete_medication(med_id: str, user_id: str = Depends(get_current_user)):
    if not db.delete_medication(user_id, med_id):
        raise HTTPException(404, "Medication not found")
    return {"success": True}


@app.get("/reminders")
def get_reminders(user_id: str = Depends(get_current_user)):
    """Reminders that are due today. Also creates the next 'repeat' reminder if needed
    (so we don't need a separate scheduler)."""
    today = date.today()
    meds = {m["id"]: m for m in db.list_medications(user_id) if not m.get("archived")}
    reminders = db.list_reminders(user_id)

    for med in meds.values():
        mine = [r for r in reminders if r["medication_id"] == med["id"]]
        when = supply.next_repeat_date(
            date.fromisoformat(med["estimated_end_date"]), mine, today,
            REPEAT_EVERY_DAYS, MAX_REPEAT_REMINDERS)
        if when:
            reminders.append(db.insert_reminder(user_id, med["id"], "repeat", when))

    due = []
    for r in reminders:
        med = meds.get(r["medication_id"])
        if med and supply.is_due(r, today):
            view = {k: v for k, v in r.items() if k != "user_id"}
            view["medication_name"] = med["name"]
            view["estimated_end_date"] = med["estimated_end_date"]
            view["days_left"] = supply.days_left(
                date.fromisoformat(med["estimated_end_date"]), today)
            due.append(view)
    return {"reminders": due}


@app.post("/reminders/{reminder_id}/acknowledge")
def acknowledge_reminder(reminder_id: str, user_id: str = Depends(get_current_user)):
    reminder = db.get_reminder(user_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    if reminder["status"] == "cancelled":
        raise HTTPException(409, "This reminder is no longer active")
    updated = db.update_reminder(user_id, reminder_id, {
        "status": "acknowledged", "acknowledged_at": date.today().isoformat()})
    return {"success": True, "reminder": updated}


@app.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(reminder_id: str, body: SnoozeRequest | None = None,
                    user_id: str = Depends(get_current_user)):
    days = body.days if body else 1
    reminder = db.get_reminder(user_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    if reminder["status"] in ("cancelled", "acknowledged"):
        raise HTTPException(409, "This reminder is no longer active")
    updated = db.update_reminder(user_id, reminder_id, {
        "status": "snoozed",
        "snoozed_until": (date.today() + timedelta(days=days)).isoformat()})
    return {"success": True, "reminder": updated}