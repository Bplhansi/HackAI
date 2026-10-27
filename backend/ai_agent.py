"""AI module (Person 2): turns a chat message into a proposed action using
NVIDIA Nemotron on Nebius Token Factory.

main.py calls interpret_medication_message(...) and gets back a dict in the
shape described in API.md. This module only INTERPRETS messages. It never saves
anything and never does supply maths. The backend does both.

Checking a model reply happens in two steps:
  1. AIResult checks the SHAPE (valid JSON, known action, right types). If that
     fails we ask the model once more, then give up with a friendly message.
  2. _apply_rules checks the VALUES (sensible numbers, real dates, an id we
     actually supplied). Bad or missing values turn into "ask_clarification".

Try it from the backend/ folder:
    python ai_agent.py "I collected 60 tablets of ExampleMed today, one a day"
"""
import asyncio
import os
import re
import sys
import time
from datetime import date, timedelta
from typing import Literal

import openai
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models import MAX_DAILY, MAX_QUANTITY

load_dotenv()

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
TIMEOUT_SECONDS = 20
MAX_TOKENS = 600
MAX_CONTEXT_TURNS = 6
MAX_DAYS_AGO = 366

# Switch off Nemotron's reasoning: we want a fast, direct JSON answer.
NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

SAFE_DOSE_MESSAGE = (
    "I can't give advice about changing, skipping or stopping a dose. "
    "Please speak to your pharmacist or GP, or call NHS 111 if you need help now."
)
FALLBACK_MESSAGE = (
    "Sorry, I didn't quite understand that. Could you rephrase it? For example: "
    '"I collected 60 tablets of ExampleMed today, one a day."'
)

# First safety layer: obvious dose-change questions never reach the model.
DOSE_CHANGE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bdouble\b.{0,15}\bdose\b",
        r"\bdouble up\b",
        r"\bskip\b.{0,15}\b(dose|tablet|pill)s?\b",
        r"\bstop taking\b",
        r"\btake (more|extra|less|fewer)\b(?! than)",
        r"\b(increase|decrease|reduce|lower|raise|change)\b.{0,15}\b(dose|dosage)\b",
    ]
]


# ---------- the shape we accept from the model ----------
class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_name: str | None = None
    quantity_collected: int | None = None
    collection_date: date | None = None
    daily_quantity: float | None = None
    medication_id: str | None = None


class AIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["add_medication", "update_medication_supply",
                    "ask_clarification", "general_response"]
    parameters: Parameters = Field(default_factory=Parameters)
    missing_fields: list[str] = Field(default_factory=list)
    message: str = Field(min_length=1, max_length=800)


REQUIRED = {
    "add_medication": ["medication_name", "quantity_collected", "collection_date", "daily_quantity"],
    "update_medication_supply": ["medication_id", "quantity_collected", "collection_date"],
}

QUESTIONS = {
    "medication_name": "the name of the medication",
    "quantity_collected": "how many tablets you collected",
    "collection_date": "the date you collected it",
    "daily_quantity": "how many tablets you take each day",
    "medication_id": "which of your saved medications this is for",
}


# ---------- the prompt ----------
SYSTEM_PROMPT = """\
You are the assistant inside medAssist AI, a website that helps people on repeat prescriptions log the medication they COLLECT, so the app can estimate when their supply will run out and remind them in time.

You are not a medical adviser. You are not connected to NHS records, GPs or pharmacies. You never save anything: the app saves only after the user presses Confirm.

Reply with exactly ONE JSON object and nothing else:
{
  "action": "add_medication" | "update_medication_supply" | "ask_clarification" | "general_response",
  "parameters": {
    "medication_name": string or null,
    "quantity_collected": whole number of tablets or null,
    "collection_date": "YYYY-MM-DD" or null,
    "daily_quantity": tablets taken per day or null,
    "medication_id": an id copied from SAVED MEDICATIONS, or null
  },
  "missing_fields": [names of parameters you still need],
  "message": "short, friendly text shown to the user"
}

CHOOSING THE ACTION:
- add_medication: the user collected a medication that is NOT in SAVED MEDICATIONS. Needs medication_name, quantity_collected, collection_date and daily_quantity.
- update_medication_supply: the user collected more of, or corrects the last collection of, a medication that IS in SAVED MEDICATIONS. Copy its medication_id. If exactly one medication is saved and the user does not name a different one ("my repeat", "my tablets", "another 60"), it is that one. Needs medication_id, quantity_collected and collection_date. Leave daily_quantity null unless the user states it.
- ask_clarification: something required is missing or unclear, or more than one saved medication could match. Fill in what you know, list what is missing in missing_fields, and ask one short question.
- general_response: greetings, questions about medAssist AI, unsupported requests and safety refusals.

RULES:
1. Dates: look them up in RECENT DATES. "last Monday" or "on Monday" is the Monday listed there (never today). If no date is given or implied, set collection_date to null and ask. Never use a future date.
2. Never invent names, quantities or ids. Only use a medication_id from SAVED MEDICATIONS.
3. Quantities are tablets or capsules. If the user gives packs, boxes or millilitres, ask how many tablets.
4. daily_quantity is the average per day: "one a day" = 1, "twice a day" = 2, "half a tablet daily" = 0.5, "two tablets twice a day" = 4, "one a week" = 0.142857. As-needed (PRN), tapering or unclear schedules are not supported: use general_response and suggest adding it with the form instead.
5. SAFETY: never recommend changing, doubling, skipping, stopping or starting a dose. Never comment on symptoms or side effects. Ordering a prescription is NOT a collection. For any medical question use general_response and suggest their pharmacist, GP or NHS 111.
6. Never say anything was saved. For add_medication and update_medication_supply end the message with "Please confirm these details." Never write that for the other actions.
7. Do not calculate run-out dates; the app does that.
8. Keep message under 60 words, plain and kind.

EXAMPLES (example date, not the real one):

Context: CURRENT DATE: 2026-03-10 (Tuesday). SAVED MEDICATIONS: none.
User: I collected 60 tablets of ExampleMed today. I take one a day.
{"action": "add_medication", "parameters": {"medication_name": "ExampleMed", "quantity_collected": 60, "collection_date": "2026-03-10", "daily_quantity": 1, "medication_id": null}, "missing_fields": [], "message": "Got it: 60 tablets of ExampleMed collected today, 1 a day. Please confirm these details."}

Context: CURRENT DATE: 2026-03-10 (Tuesday). SAVED MEDICATIONS: none.
User: I picked up 30 tablets yesterday, two a day.
{"action": "ask_clarification", "parameters": {"medication_name": null, "quantity_collected": 30, "collection_date": "2026-03-09", "daily_quantity": 2, "medication_id": null}, "missing_fields": ["medication_name"], "message": "Thanks! Which medication did you collect?"}

Context: CURRENT DATE: 2026-03-10 (Tuesday). SAVED MEDICATIONS: id "med-a", ExampleMed.
User: I've picked up another 60 tablets today.
{"action": "update_medication_supply", "parameters": {"medication_name": "ExampleMed", "quantity_collected": 60, "collection_date": "2026-03-10", "daily_quantity": null, "medication_id": "med-a"}, "missing_fields": [], "message": "Another 60 tablets of ExampleMed collected today. Please confirm these details."}

Context: CURRENT DATE: 2026-03-10 (Tuesday). SAVED MEDICATIONS: id "med-a", ExampleMed; id "med-b", DemoPril.
User: I collected more medication today.
{"action": "ask_clarification", "parameters": {"medication_name": null, "quantity_collected": null, "collection_date": "2026-03-10", "daily_quantity": null, "medication_id": null}, "missing_fields": ["medication_id", "quantity_collected"], "message": "Which medication did you collect, ExampleMed or DemoPril, and how many tablets?"}

Context: CURRENT DATE: 2026-03-10 (Tuesday). SAVED MEDICATIONS: id "med-a", ExampleMed, collected 2026-03-10 (60 tablets).
User: Actually, it was 30 tablets, not 60.
{"action": "update_medication_supply", "parameters": {"medication_name": "ExampleMed", "quantity_collected": 30, "collection_date": "2026-03-10", "daily_quantity": null, "medication_id": "med-a"}, "missing_fields": [], "message": "No problem, I'll change today's ExampleMed collection to 30 tablets. Please confirm these details."}

Context: CURRENT DATE: 2026-03-10 (Tuesday). SAVED MEDICATIONS: id "med-a", ExampleMed.
User: I missed yesterday's tablet, should I take two today?
{"action": "general_response", "parameters": {"medication_name": null, "quantity_collected": null, "collection_date": null, "daily_quantity": null, "medication_id": null}, "missing_fields": [], "message": "I'm sorry, I can't advise on doses. Please speak to your pharmacist or GP, or call NHS 111 if you need help now."}
"""


def _context_block(today: date, medications: list[dict]) -> str:
    """Today's date, a lookup table of recent dates, and the user's saved medications."""
    lines = [f"CURRENT DATE: {today.isoformat()} ({today.strftime('%A')})",
             "RECENT DATES (look dates up here; do not calculate them):"]
    # Models are unreliable at counting back weekdays, so we give them the answers.
    for back in range(8):
        day = today - timedelta(days=back)
        label = {0: "today", 1: "yesterday"}.get(back, f"{back} days ago")
        lines.append(f"- {day.strftime('%A')} {day.isoformat()} ({label})")
    lines.append("SAVED MEDICATIONS:")
    if not medications:
        lines.append("none")
    for med in medications:
        line = f'- id "{med["id"]}", {med["name"]}, {med.get("daily_quantity")} a day'
        if med.get("collection_date"):
            line += f', collected {med["collection_date"]} ({med.get("quantity_collected")} tablets)'
        lines.append(line)
    return "\n".join(lines)


def _build_messages(user_message: str, today: date, medications: list[dict],
                    conversation: list[dict]) -> list[dict]:
    system = SYSTEM_PROMPT + "\nCONTEXT FOR THIS CONVERSATION:\n" + _context_block(today, medications)
    messages = [{"role": "system", "content": system}]
    for turn in conversation[-MAX_CONTEXT_TURNS:]:
        if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            messages.append({"role": turn["role"], "content": turn["content"][:1000]})
    messages.append({"role": "user", "content": user_message[:1000]})
    return messages


# ---------- checking the values ----------
def _ask_for(missing: list[str]) -> str:
    questions = [QUESTIONS[f] for f in missing if f in QUESTIONS]
    if not questions:
        return "Could you tell me a bit more?"
    if len(questions) == 1:
        return f"Could you tell me {questions[0]}?"
    return "Could you tell me " + ", ".join(questions[:-1]) + f" and {questions[-1]}?"


def _apply_rules(result: AIResult, today: date, medication_ids: set[str]) -> dict:
    """Replace out-of-range values with None, then decide what the user sees."""
    p = result.parameters.model_copy()
    if p.medication_name is not None:
        p.medication_name = p.medication_name.strip()[:100] or None
    if p.quantity_collected is not None and not 0 < p.quantity_collected <= MAX_QUANTITY:
        p.quantity_collected = None
    if p.daily_quantity is not None and not 0 < p.daily_quantity <= MAX_DAILY:
        p.daily_quantity = None
    if p.collection_date is not None and not (
            today - timedelta(days=MAX_DAYS_AGO) <= p.collection_date <= today):
        p.collection_date = None
    if p.medication_id is not None and p.medication_id not in medication_ids:
        p.medication_id = None  # the model invented or mistyped an id

    action, message = result.action, result.message
    missing = [f for f in result.missing_fields if f in QUESTIONS]
    if action in REQUIRED:
        missing = [f for f in REQUIRED[action] if getattr(p, f) is None]
        if missing:
            action, message = "ask_clarification", _ask_for(missing)
    else:
        message = re.sub(r"\s*Please confirm these details\.?", "", message).strip() or message

    return {
        "action": action,
        "parameters": p.model_dump(mode="json"),  # dates become "YYYY-MM-DD"
        "missing_fields": missing,
        "requires_confirmation": action in REQUIRED,  # set by code, never by the model
        "message": message,
    }


def _general(message: str) -> dict:
    return {"action": "general_response", "parameters": Parameters().model_dump(mode="json"),
            "missing_fields": [], "requires_confirmation": False, "message": message}


# ---------- calling Nemotron ----------
def _client() -> openai.AsyncOpenAI:
    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key or api_key == "your-key-here":
        raise RuntimeError("NEBIUS_API_KEY is not set")
    return openai.AsyncOpenAI(base_url=os.getenv("NEBIUS_BASE_URL") or DEFAULT_BASE_URL,
                              api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0)


def _response_format() -> dict:
    """Ask Token Factory to force the reply into our JSON schema."""
    return {"type": "json_schema",
            "json_schema": {"name": "ai_result", "schema": AIResult.model_json_schema(), "strict": True}}


def _extract_json(text: str) -> str:
    """Keep only the JSON object: drop any <think> block, ``` fences or chatter."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).split("</think>")[-1]
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text.strip()


async def _call_model(client: openai.AsyncOpenAI, model: str, messages: list[dict]) -> str:
    kwargs = dict(model=model, messages=messages, temperature=0.1,
                  max_tokens=MAX_TOKENS, extra_body=NO_THINKING)
    try:
        response = await client.chat.completions.create(**kwargs, response_format=_response_format())
    except openai.BadRequestError:
        # If strict JSON schema is rejected, plain JSON mode still works and Pydantic checks it.
        response = await client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    return response.choices[0].message.content or ""


async def interpret_medication_message(user_message: str, current_date: str,
                                       medications: list, conversation_context: list) -> dict:
    """Called by main.py. Raises on network/API errors (main.py turns that into a 503)."""
    if any(p.search(user_message) for p in DOSE_CHANGE_PATTERNS):
        print("ai action=general_response source=safety_guard")
        return _general(SAFE_DOSE_MESSAGE)

    today = date.fromisoformat(current_date)
    model = os.getenv("NEBIUS_MODEL") or DEFAULT_MODEL
    messages = _build_messages(user_message, today, medications, conversation_context)
    start = time.perf_counter()

    async with _client() as client:
        for attempt in (1, 2):
            raw = await _call_model(client, model, messages)
            try:
                result = AIResult.model_validate_json(_extract_json(raw))
            except ValidationError:
                # Tell the model what went wrong and let it try once more.
                messages = messages + [
                    {"role": "assistant", "content": raw[:2000]},
                    {"role": "user", "content": "That was not valid. Reply with one JSON object "
                                                "only, exactly matching the format."},
                ]
                continue
            safe = _apply_rules(result, today, {str(m["id"]) for m in medications})
            # Log only action, model and timing. Never medication details.
            ms = int((time.perf_counter() - start) * 1000)
            print(f"ai action={safe['action']} model={model} attempts={attempt} latency_ms={ms}")
            return safe

    print(f"ai fallback_after_retry model={model}")
    return _general(FALLBACK_MESSAGE)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: python ai_agent.py "your message"')
    demo_meds = [{"id": "11111111-1111-1111-1111-111111111111", "name": "ExampleMed",
                  "daily_quantity": 1, "quantity_collected": 60, "collection_date": "2026-10-01"}]
    print(asyncio.run(interpret_medication_message(
        user_message=sys.argv[1], current_date=date.today().isoformat(),
        medications=demo_meds if "--with-med" in sys.argv else [], conversation_context=[])))