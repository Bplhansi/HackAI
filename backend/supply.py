"""Supply and reminder maths. Pure Python, no database, no AI.

Everything here is deterministic so it is easy to test.
"""
from datetime import date, timedelta

OPEN_STATUSES = ("pending", "snoozed")


def estimate_end_date(collection_date: date, quantity: int, daily_quantity: float) -> date:
    """Date the supply is estimated to run out.

    Example: 60 tablets, 1 a day, collected 1 Nov -> 60 whole days -> 31 Dec.
    A new collection REPLACES the old supply (leftovers are not carried over).
    """
    if quantity <= 0 or daily_quantity <= 0:
        raise ValueError("Quantity and daily quantity must be positive")
    days_of_supply = int(quantity // daily_quantity)  # whole days only
    return collection_date + timedelta(days=days_of_supply)


def reminder_dates(end_date: date, today: date) -> list[tuple[str, date]]:
    """The first two reminders: 14 and 7 days before the end date.

    Dates that are already in the past are skipped. If BOTH are in the past
    (supply ends very soon, or already ended) we create one reminder for today,
    so the user is still told.
    """
    candidates = [
        ("14_day", end_date - timedelta(days=14)),
        ("7_day", end_date - timedelta(days=7)),
    ]
    future = [(kind, d) for kind, d in candidates if d >= today]
    if not future:
        future = [("7_day", today)]
    return future


def days_left(end_date: date, today: date) -> int:
    """Days until the supply is estimated to run out (negative = already past)."""
    return (end_date - today).days


def is_due(reminder: dict, today: date) -> bool:
    """Should this reminder be shown to the user today?"""
    if reminder["status"] == "pending":
        return date.fromisoformat(reminder["remind_on"]) <= today
    if reminder["status"] == "snoozed":
        return date.fromisoformat(reminder["snoozed_until"]) <= today
    return False


def next_repeat_date(
    end_date: date,
    med_reminders: list[dict],
    today: date,
    repeat_every_days: int,
    max_repeats: int,
) -> date | None:
    """When should the next 'repeat' reminder be created? None = don't create one.

    Rules (this is what keeps notifications under control):
    - Only once we are inside the final 7 days of supply.
    - Never while another reminder for this medication is still open
      (pending or snoozed), so there is never more than one at a time.
    - After the user acknowledges one, the next comes `repeat_every_days` later.
    - Stops after `max_repeats` repeat reminders (no endless nagging).
    - Updating the medication cancels everything and starts again.
    """
    if today < end_date - timedelta(days=7):
        return None
    if any(r["status"] in OPEN_STATUSES for r in med_reminders):
        return None
    if sum(1 for r in med_reminders if r["kind"] == "repeat") >= max_repeats:
        return None

    acknowledged = [r["acknowledged_at"] for r in med_reminders
                    if r["status"] == "acknowledged" and r.get("acknowledged_at")]
    if not acknowledged:
        return today
    last_ack = date.fromisoformat(max(acknowledged))
    return last_ack + timedelta(days=repeat_every_days)