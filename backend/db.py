"""Database access. All Supabase calls live in this one file.

Two versions with the same methods:
- SupabaseDB: the real one (used when SUPABASE_URL and SUPABASE_KEY are set).
- InMemoryDB: stores things in Python lists. Used for tests and for running
  locally before Supabase is set up. Data is lost when the server restarts.

Every method takes user_id and filters by it, so one user can never read or
change another user's rows.
"""
import os
import uuid
from datetime import date, datetime, timezone

from supply import OPEN_STATUSES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryDB:
    name = "memory"

    def __init__(self):
        self.medications: list[dict] = []
        self.reminders: list[dict] = []

    def verify_token(self, token: str) -> str | None:
        return None  # no real accounts in memory mode

    # --- medications ---
    def list_medications(self, user_id):
        return [dict(m) for m in self.medications if m["user_id"] == user_id]

    def get_medication(self, user_id, med_id):
        for m in self.medications:
            if m["id"] == med_id and m["user_id"] == user_id:
                return dict(m)
        return None

    def insert_medication(self, user_id, data):
        row = {"id": str(uuid.uuid4()), "user_id": user_id, "created_at": _now(), **data}
        self.medications.append(row)
        return dict(row)

    def update_medication(self, user_id, med_id, data):
        for m in self.medications:
            if m["id"] == med_id and m["user_id"] == user_id:
                m.update(data)
                return dict(m)
        return None

    def delete_medication(self, user_id, med_id):
        before = len(self.medications)
        self.medications = [m for m in self.medications
                            if not (m["id"] == med_id and m["user_id"] == user_id)]
        self.reminders = [r for r in self.reminders if r["medication_id"] != med_id]
        return len(self.medications) < before

    # --- reminders ---
    def list_reminders(self, user_id):
        return [dict(r) for r in self.reminders if r["user_id"] == user_id]

    def get_reminder(self, user_id, reminder_id):
        for r in self.reminders:
            if r["id"] == reminder_id and r["user_id"] == user_id:
                return dict(r)
        return None

    def insert_reminder(self, user_id, med_id, kind, remind_on: date):
        row = {
            "id": str(uuid.uuid4()), "user_id": user_id, "medication_id": med_id,
            "remind_on": remind_on.isoformat(), "kind": kind, "status": "pending",
            "snoozed_until": None, "acknowledged_at": None, "created_at": _now(),
        }
        self.reminders.append(row)
        return dict(row)

    def update_reminder(self, user_id, reminder_id, data):
        for r in self.reminders:
            if r["id"] == reminder_id and r["user_id"] == user_id:
                r.update(data)
                return dict(r)
        return None

    def cancel_open_reminders(self, user_id, med_id):
        for r in self.reminders:
            if (r["user_id"] == user_id and r["medication_id"] == med_id
                    and r["status"] in OPEN_STATUSES):
                r["status"] = "cancelled"


class SupabaseDB:
    name = "supabase"

    def __init__(self, url: str, key: str):
        from supabase import create_client  # imported here so memory mode needs no package

        self.client = create_client(url, key)

    def verify_token(self, token: str) -> str | None:
        """Ask Supabase Auth who this login token belongs to."""
        try:
            result = self.client.auth.get_user(token)
            return result.user.id if result and result.user else None
        except Exception:
            return None

    # --- medications ---
    def list_medications(self, user_id):
        res = self.client.table("medications").select("*").eq("user_id", user_id).execute()
        return res.data

    def get_medication(self, user_id, med_id):
        res = (self.client.table("medications").select("*")
               .eq("id", med_id).eq("user_id", user_id).execute())
        return res.data[0] if res.data else None

    def insert_medication(self, user_id, data):
        res = self.client.table("medications").insert({"user_id": user_id, **data}).execute()
        return res.data[0]

    def update_medication(self, user_id, med_id, data):
        res = (self.client.table("medications").update(data)
               .eq("id", med_id).eq("user_id", user_id).execute())
        return res.data[0] if res.data else None

    def delete_medication(self, user_id, med_id):
        # reminders are removed automatically (on delete cascade in schema.sql)
        res = (self.client.table("medications").delete()
               .eq("id", med_id).eq("user_id", user_id).execute())
        return bool(res.data)

    # --- reminders ---
    def list_reminders(self, user_id):
        res = self.client.table("reminders").select("*").eq("user_id", user_id).execute()
        return res.data

    def get_reminder(self, user_id, reminder_id):
        res = (self.client.table("reminders").select("*")
               .eq("id", reminder_id).eq("user_id", user_id).execute())
        return res.data[0] if res.data else None

    def insert_reminder(self, user_id, med_id, kind, remind_on: date):
        res = self.client.table("reminders").insert({
            "user_id": user_id, "medication_id": med_id,
            "remind_on": remind_on.isoformat(), "kind": kind, "status": "pending",
        }).execute()
        return res.data[0]

    def update_reminder(self, user_id, reminder_id, data):
        res = (self.client.table("reminders").update(data)
               .eq("id", reminder_id).eq("user_id", user_id).execute())
        return res.data[0] if res.data else None

    def cancel_open_reminders(self, user_id, med_id):
        (self.client.table("reminders").update({"status": "cancelled"})
         .eq("user_id", user_id).eq("medication_id", med_id)
         .in_("status", list(OPEN_STATUSES)).execute())


def get_database():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if url and key:
        return SupabaseDB(url, key)
    print("WARNING: SUPABASE_URL / SUPABASE_KEY not set. Using in-memory storage "
          "(data is lost on restart).")
    return InMemoryDB()
