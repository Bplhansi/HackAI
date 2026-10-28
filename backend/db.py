"""Database access for medAssist AI.

Two database implementations:
- SupabaseDB: persistent storage with per-request authentication and RLS.
- InMemoryDB: temporary storage for local development and tests.

IMPORTANT:
SupabaseDB uses a separate authenticated client for each request.
Never use a service_role or secret key for normal user database access.
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
        return None

    def for_user(self, token: str):
        raise ValueError("Authenticated database access requires Supabase")

    # --- medications ---

    def list_medications(self, user_id):
        return [
            dict(m)
            for m in self.medications
            if m["user_id"] == user_id
        ]

    def get_medication(self, user_id, med_id):
        for m in self.medications:
            if m["id"] == med_id and m["user_id"] == user_id:
                return dict(m)
        return None

    def insert_medication(self, user_id, data):
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "created_at": _now(),
            **data,
        }
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

        self.medications = [
            m for m in self.medications
            if not (
                m["id"] == med_id
                and m["user_id"] == user_id
            )
        ]

        self.reminders = [
            r for r in self.reminders
            if not (
                r["medication_id"] == med_id
                and r["user_id"] == user_id
            )
        ]

        return len(self.medications) < before

    # --- reminders ---

    def list_reminders(self, user_id):
        return [
            dict(r)
            for r in self.reminders
            if r["user_id"] == user_id
        ]

    def get_reminder(self, user_id, reminder_id):
        for r in self.reminders:
            if (
                r["id"] == reminder_id
                and r["user_id"] == user_id
            ):
                return dict(r)
        return None

    def insert_reminder(self, user_id, med_id, kind, remind_on: date):
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "medication_id": med_id,
            "remind_on": remind_on.isoformat(),
            "kind": kind,
            "status": "pending",
            "snoozed_until": None,
            "acknowledged_at": None,
            "created_at": _now(),
        }

        self.reminders.append(row)
        return dict(row)

    def update_reminder(self, user_id, reminder_id, data):
        for r in self.reminders:
            if (
                r["id"] == reminder_id
                and r["user_id"] == user_id
            ):
                r.update(data)
                return dict(r)
        return None

    def cancel_open_reminders(self, user_id, med_id):
        for r in self.reminders:
            if (
                r["user_id"] == user_id
                and r["medication_id"] == med_id
                and r["status"] in OPEN_STATUSES
            ):
                r["status"] = "cancelled"


class SupabaseDB:
    name = "supabase"

    def __init__(self, url: str, key: str):
        from supabase import create_client

        self.url = url
        self.key = key

        # This client is used ONLY to verify login tokens.
        # It is never used for medication/reminder queries.
        self.auth_client = create_client(url, key)

    def verify_token(self, token: str) -> str | None:
        """Verify a login token with Supabase Auth."""
        try:
            result = self.auth_client.auth.get_user(token)

            if result and result.user:
                return str(result.user.id)

            return None

        except Exception:
            return None

    def for_user(self, token: str):
        """Create an isolated database connection for one request.

        The request's JWT is sent to Supabase PostgREST,
        allowing Row Level Security to enforce auth.uid().
        """
        from supabase import create_client

        user_id = self.verify_token(token)

        if not user_id:
            raise ValueError("Invalid or expired login token")

        client = create_client(self.url, self.key)

        # Authenticate THIS client's database requests only.
        # Never modify a globally shared PostgREST client.
        client.postgrest.auth(token)

        return AuthenticatedSupabaseDB(client, user_id)


class AuthenticatedSupabaseDB:
    """Database operations for one authenticated user/request."""

    name = "supabase"

    def __init__(self, client, user_id: str):
        self.client = client
        self.user_id = user_id

    def _check_user(self, user_id):
        """Reject attempts to use this connection for another user."""
        if str(user_id) != self.user_id:
            raise ValueError("Database user mismatch")

    # --- medications ---

    def list_medications(self, user_id):
        self._check_user(user_id)

        res = (
            self.client.table("medications")
            .select("*")
            .eq("user_id", self.user_id)
            .execute()
        )

        return res.data

    def get_medication(self, user_id, med_id):
        self._check_user(user_id)

        res = (
            self.client.table("medications")
            .select("*")
            .eq("id", med_id)
            .eq("user_id", self.user_id)
            .execute()
        )

        return res.data[0] if res.data else None

    def insert_medication(self, user_id, data):
        self._check_user(user_id)

        # The verified user ID always wins.
        # Never accept user_id from medication data.
        row = {
            **data,
            "user_id": self.user_id,
        }

        res = (
            self.client.table("medications")
            .insert(row)
            .execute()
        )

        return res.data[0]

    def update_medication(self, user_id, med_id, data):
        self._check_user(user_id)

        # Prevent changing row ownership.
        changes = {
            key: value
            for key, value in data.items()
            if key not in ("user_id", "id")
        }

        res = (
            self.client.table("medications")
            .update(changes)
            .eq("id", med_id)
            .eq("user_id", self.user_id)
            .execute()
        )

        return res.data[0] if res.data else None

    def delete_medication(self, user_id, med_id):
        self._check_user(user_id)

        # Reminders should be deleted by the database's
        # ON DELETE CASCADE foreign key.
        res = (
            self.client.table("medications")
            .delete()
            .eq("id", med_id)
            .eq("user_id", self.user_id)
            .execute()
        )

        return bool(res.data)

    # --- reminders ---

    def list_reminders(self, user_id):
        self._check_user(user_id)

        res = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", self.user_id)
            .execute()
        )

        return res.data

    def get_reminder(self, user_id, reminder_id):
        self._check_user(user_id)

        res = (
            self.client.table("reminders")
            .select("*")
            .eq("id", reminder_id)
            .eq("user_id", self.user_id)
            .execute()
        )

        return res.data[0] if res.data else None

    def insert_reminder(self, user_id, med_id, kind, remind_on: date):
        self._check_user(user_id)

        res = (
            self.client.table("reminders")
            .insert({
                "user_id": self.user_id,
                "medication_id": med_id,
                "remind_on": remind_on.isoformat(),
                "kind": kind,
                "status": "pending",
            })
            .execute()
        )

        return res.data[0]

    def update_reminder(self, user_id, reminder_id, data):
        self._check_user(user_id)

        changes = {
            key: value
            for key, value in data.items()
            if key not in (
                "user_id",
                "id",
                "medication_id",
            )
        }

        res = (
            self.client.table("reminders")
            .update(changes)
            .eq("id", reminder_id)
            .eq("user_id", self.user_id)
            .execute()
        )

        return res.data[0] if res.data else None

    def cancel_open_reminders(self, user_id, med_id):
        self._check_user(user_id)

        (
            self.client.table("reminders")
            .update({"status": "cancelled"})
            .eq("user_id", self.user_id)
            .eq("medication_id", med_id)
            .in_("status", list(OPEN_STATUSES))
            .execute()
        )


def get_database():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if url and key:
        if not key.startswith(("sb_publishable_", "eyJ")):
            raise RuntimeError(
                "SUPABASE_KEY must be a publishable or legacy anon key. "
                "Do not use a service_role or secret key."
            )

        return SupabaseDB(url, key)

    print(
        "WARNING: SUPABASE_URL / SUPABASE_KEY not set. "
        "Using in-memory storage (data is lost on restart)."
    )

    return InMemoryDB()