"""Pydantic models: every request from the browser is validated here.

The AI's output is NOT trusted either. The user confirms in the form, and the
confirm routes re-validate with these models before anything is saved.
"""
from datetime import date, timedelta

from pydantic import BaseModel, Field, field_validator

MAX_QUANTITY = 10000  # tablets in one collection
MAX_DAILY = 50  # tablets per day


def _check_collection_date(value: date) -> date:
    today = date.today()
    # +1 day of tolerance so users in a time zone ahead of the server aren't rejected
    if value > today + timedelta(days=1):
        raise ValueError("Collection date cannot be in the future")
    if value < today - timedelta(days=366):
        raise ValueError("Collection date is more than a year ago")
    return value


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    # Earlier chat turns, e.g. [{"role": "user", "content": "..."}]
    conversation_context: list[dict] = Field(default_factory=list, max_length=20)


class ConfirmAdd(BaseModel):
    medication_name: str = Field(min_length=1, max_length=100)
    quantity_collected: int = Field(gt=0, le=MAX_QUANTITY)
    collection_date: date
    daily_quantity: float = Field(gt=0, le=MAX_DAILY)

    @field_validator("medication_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Medication name cannot be empty")
        return v

    @field_validator("collection_date")
    @classmethod
    def check_date(cls, v: date) -> date:
        return _check_collection_date(v)


class ConfirmUpdate(BaseModel):
    medication_id: str = Field(min_length=1, max_length=64)
    quantity_collected: int = Field(gt=0, le=MAX_QUANTITY)
    collection_date: date
    # Optional: leave out to keep the saved daily quantity
    daily_quantity: float | None = Field(default=None, gt=0, le=MAX_DAILY)

    @field_validator("collection_date")
    @classmethod
    def check_date(cls, v: date) -> date:
        return _check_collection_date(v)


class SnoozeRequest(BaseModel):
    days: int = Field(default=1, ge=1, le=7)
