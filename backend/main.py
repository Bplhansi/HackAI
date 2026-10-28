"""medAssist AI backend (FastAPI).

Flow:
React -> /chat (AI proposes, nothing saved)
React shows a confirmation form
React -> /medications/confirm-add or /confirm-update

Each request uses its own authenticated Supabase database client.
"""

import os
from datetime import date, timedelta

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

import supply
from db import get_database
from models import (
    ArchiveRequest,
    ChatRequest,
    ConfirmAdd,
    ConfirmUpdate,
    SnoozeRequest,
)

# ---------- settings ----------

REPEAT_EVERY_DAYS = int(os.getenv("REPEAT_EVERY_DAYS", "3"))
MAX_REPEAT_REMINDERS = int(os.getenv("MAX_REPEAT_REMINDERS", "5"))

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    if origin.strip()
]

# ---------- AI module ----------

AI_MODE = "stub"

if os.getenv("USE_STUB_AI", "false").lower() != "true":
    try:
        from ai_agent import interpret_medication_message
        AI_MODE = "nemotron"
    except ImportError as err:
        print(
            f"WARNING: could not import ai_agent ({err}). "
            "Using the stub AI."
        )

if AI_MODE == "stub":
    from ai_stub import interpret_medication_message

ALLOWED_ACTIONS = {
    "add_medication",
    "update_medication_supply",
    "ask_clarification",
    "general_response",
}

# ---------- database ----------

db = get_database()

# Refuse to start a deployed backend without Supabase.
if os.getenv("RENDER") and db.name != "supabase":
    raise RuntimeError(
        "Supabase must be configured before deploying medAssist AI."
    )

# ---------- app ----------

app = FastAPI(title="medAssist AI backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- authentication ----------

def get_user_db(
    authorization: str | None = Header(default=None),
):
    """Return this request's authenticated database and user ID."""

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Please log in",
        )

    scheme, separator, token = authorization.partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Please log in",
        )

    token = token.strip()

    try:
        user_db = db.for_user(token)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired login",
        )
    except Exception as err:
        print(f"Authentication error: {type(err).__name__}")
        raise HTTPException(
            status_code=503,
            detail="Authentication is temporarily unavailable",
        )

    return user_db, user_db.user_id


# ---------- helpers ----------

def _med_view(med: dict, today: date) -> dict:
    """Return a medication with its calculated days remaining."""

    end = date.fromisoformat(med["estimated_end_date"])

    out = {
        key: value
        for key, value in med.items()
        if key != "user_id"
    }

    out["details"] = med.get("details") or {}
    out["archived"] = bool(med.get("archived"))
    out["days_left"] = supply.days_left(end, today)

    return out


def _create_reminders(
    user_db,
    user_id: str,
    med_id: str,
    end: date,
    today: date,
) -> list[dict]:

    return [
        user_db.insert_reminder(user_id, med_id, kind, reminder_date)
        for kind, reminder_date in supply.reminder_dates(end, today)
    ]


def _clean_ai_result(
    result,
    owned_meds: list[dict],
) -> dict:

    if (
        not isinstance(result, dict)
        or result.get("action") not in ALLOWED_ACTIONS
    ):
        return {
            "action": "general_response",
            "parameters": {},
            "missing_fields": [],
            "requires_confirmation": False,
            "message": (
                "Sorry, I didn't understand that. "
                "Could you rephrase?"
            ),
        }

    if result["action"] == "update_medication_supply":
        med_id = (
            result.get("parameters") or {}
        ).get("medication_id")

        if med_id not in {med["id"] for med in owned_meds}:
            names = (
                ", ".join(med["name"] for med in owned_meds)
                or "none saved yet"
            )

            return {
                "action": "ask_clarification",
                "parameters": {},
                "missing_fields": ["medication_id"],
                "requires_confirmation": False,
                "message": (
                    f"Which medication do you mean? "
                    f"Saved medications: {names}."
                ),
            }

    return result


# ---------- health ----------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "ai": AI_MODE,
        "database": db.name,
    }


# ---------- chat ----------

@app.post("/chat")
async def chat(
    req: ChatRequest,
    context=Depends(get_user_db),
):
    """Ask the AI to interpret a message. Saves nothing."""

    user_db, user_id = context

    meds = [
        med
        for med in user_db.list_medications(user_id)
        if not med.get("archived")
    ]

    ai_meds = [
        {
            key: med[key]
            for key in (
                "id",
                "name",
                "daily_quantity",
                "quantity_collected",
                "collection_date",
                "estimated_end_date",
            )
        }
        for med in meds
    ]

    try:
        result = await interpret_medication_message(
            user_message=req.message,
            current_date=date.today().isoformat(),
            medications=ai_meds,
            conversation_context=req.conversation_context,
        )

    except Exception as err:
        print(f"AI call failed: {type(err).__name__}")

        raise HTTPException(
            status_code=503,
            detail=(
                "The AI assistant is unavailable right now. "
                "Please try again in a moment."
            ),
        )

    return _clean_ai_result(result, ai_meds)


# ---------- medications ----------

@app.get("/medications")
def list_medications(
    context=Depends(get_user_db),
):
    user_db, user_id = context
    today = date.today()

    medications = user_db.list_medications(user_id)

    return {
        "medications": [
            _med_view(med, today)
            for med in medications
        ]
    }


@app.post("/medications/confirm-add", status_code=201)
def confirm_add(
    body: ConfirmAdd,
    context=Depends(get_user_db),
):
    user_db, user_id = context
    today = date.today()

    existing = {
        med["name"].lower()
        for med in user_db.list_medications(user_id)
        if not med.get("archived")
    }

    if body.medication_name.lower() in existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{body.medication_name} is already being tracked. "
                "Update it with the new collection instead."
            ),
        )

    end = supply.estimate_end_date(
        body.collection_date,
        body.quantity_collected,
        body.daily_quantity,
    )

    try:
        med = user_db.insert_medication(
            user_id,
            {
                "name": body.medication_name,
                "quantity_collected": body.quantity_collected,
                "collection_date": body.collection_date.isoformat(),
                "daily_quantity": body.daily_quantity,
                "estimated_end_date": end.isoformat(),
                "details": body.details or {},
                "archived": False,
            },
        )

        reminders = _create_reminders(
            user_db,
            user_id,
            med["id"],
            end,
            today,
        )

    except Exception as err:
        print(f"Database error: {type(err).__name__}")

        raise HTTPException(
            status_code=500,
            detail="Could not complete the save. Please try again.",
        )

    return {
        "success": True,
        "medication": _med_view(med, today),
        "reminders": reminders,
        "message": (
            f"Saved. Estimated supply end date: {end.isoformat()}."
        ),
    }


@app.post("/medications/confirm-update")
def confirm_update(
    body: ConfirmUpdate,
    context=Depends(get_user_db),
):
    user_db, user_id = context
    today = date.today()

    med = user_db.get_medication(
        user_id,
        body.medication_id,
    )

    if not med:
        raise HTTPException(
            status_code=404,
            detail="Medication not found",
        )

    daily = body.daily_quantity or float(
        med["daily_quantity"]
    )

    end = supply.estimate_end_date(
        body.collection_date,
        body.quantity_collected,
        daily,
    )

    changes = {
        "quantity_collected": body.quantity_collected,
        "collection_date": body.collection_date.isoformat(),
        "daily_quantity": daily,
        "estimated_end_date": end.isoformat(),
        "archived": False,
    }

    if body.details is not None:
        changes["details"] = body.details

    try:
        updated = user_db.update_medication(
            user_id,
            med["id"],
            changes,
        )

        if not updated:
            raise HTTPException(
                status_code=404,
                detail="Medication not found",
            )

        user_db.cancel_open_reminders(
            user_id,
            med["id"],
        )

        reminders = _create_reminders(
            user_db,
            user_id,
            med["id"],
            end,
            today,
        )

    except HTTPException:
        raise

    except Exception as err:
        print(f"Database error: {type(err).__name__}")

        raise HTTPException(
            status_code=500,
            detail="Could not complete the update. Please try again.",
        )

    return {
        "success": True,
        "medication": _med_view(updated, today),
        "reminders": reminders,
        "message": (
            "Updated. New estimated supply end date: "
            f"{end.isoformat()}."
        ),
    }


@app.post("/medications/{med_id}/archive")
def archive_medication(
    med_id: str,
    body: ArchiveRequest,
    context=Depends(get_user_db),
):
    user_db, user_id = context

    changes = {
        "archived": body.archived,
    }

    if body.details is not None:
        changes["details"] = body.details

    updated = user_db.update_medication(
        user_id,
        med_id,
        changes,
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Medication not found",
        )

    user_db.cancel_open_reminders(
        user_id,
        med_id,
    )

    return {
        "success": True,
        "medication": _med_view(
            updated,
            date.today(),
        ),
    }


@app.delete("/medications/{med_id}")
def delete_medication(
    med_id: str,
    context=Depends(get_user_db),
):
    user_db, user_id = context

    if not user_db.delete_medication(user_id, med_id):
        raise HTTPException(
            status_code=404,
            detail="Medication not found",
        )

    return {"success": True}


# ---------- reminders ----------

@app.get("/reminders")
def get_reminders(
    context=Depends(get_user_db),
):
    user_db, user_id = context
    today = date.today()

    meds = {
        med["id"]: med
        for med in user_db.list_medications(user_id)
        if not med.get("archived")
    }

    reminders = user_db.list_reminders(user_id)

    for med in meds.values():
        mine = [
            reminder
            for reminder in reminders
            if reminder["medication_id"] == med["id"]
        ]

        when = supply.next_repeat_date(
            date.fromisoformat(
                med["estimated_end_date"]
            ),
            mine,
            today,
            REPEAT_EVERY_DAYS,
            MAX_REPEAT_REMINDERS,
        )

        if when:
            reminders.append(
                user_db.insert_reminder(
                    user_id,
                    med["id"],
                    "repeat",
                    when,
                )
            )

    due = []

    for reminder in reminders:
        med = meds.get(reminder["medication_id"])

        if med and supply.is_due(reminder, today):
            view = {
                key: value
                for key, value in reminder.items()
                if key != "user_id"
            }

            view["medication_name"] = med["name"]
            view["estimated_end_date"] = (
                med["estimated_end_date"]
            )

            view["days_left"] = supply.days_left(
                date.fromisoformat(
                    med["estimated_end_date"]
                ),
                today,
            )

            due.append(view)

    return {"reminders": due}


@app.post("/reminders/{reminder_id}/acknowledge")
def acknowledge_reminder(
    reminder_id: str,
    context=Depends(get_user_db),
):
    user_db, user_id = context

    reminder = user_db.get_reminder(
        user_id,
        reminder_id,
    )

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found",
        )

    if reminder["status"] == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="This reminder is no longer active",
        )

    updated = user_db.update_reminder(
        user_id,
        reminder_id,
        {
            "status": "acknowledged",
            "acknowledged_at": (
                date.today().isoformat()
            ),
        },
    )

    return {
        "success": True,
        "reminder": updated,
    }


@app.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(
    reminder_id: str,
    body: SnoozeRequest | None = None,
    context=Depends(get_user_db),
):
    user_db, user_id = context
    days = body.days if body else 1

    reminder = user_db.get_reminder(
        user_id,
        reminder_id,
    )

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found",
        )

    if reminder["status"] in (
        "cancelled",
        "acknowledged",
    ):
        raise HTTPException(
            status_code=409,
            detail="This reminder is no longer active",
        )

    updated = user_db.update_reminder(
        user_id,
        reminder_id,
        {
            "status": "snoozed",
            "snoozed_until": (
                date.today() + timedelta(days=days)
            ).isoformat(),
        },
    )

    return {
        "success": True,
        "reminder": updated,
    }