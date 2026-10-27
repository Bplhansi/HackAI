"""Tests for ai_agent.py. They never call Nemotron: the model is replaced by a fake
that returns a fixed reply, so we can check how our code handles good and bad replies.
"""
import asyncio
import json

import pytest

import ai_agent

TODAY = "2026-03-10"
MED = {"id": "med-a", "name": "ExampleMed", "daily_quantity": 1,
       "quantity_collected": 60, "collection_date": "2026-03-01"}


def reply(action="add_medication", message="Please confirm these details.", **params):
    base = {"medication_name": None, "quantity_collected": None, "collection_date": None,
            "daily_quantity": None, "medication_id": None}
    return json.dumps({"action": action, "parameters": {**base, **params},
                       "missing_fields": [], "message": message})


@pytest.fixture
def fake_model(monkeypatch):
    """Replace the real API call. Set fake_model.replies to what the 'model' says."""
    calls = []

    async def fake_call(client, model, messages):
        calls.append(messages)
        return fake_model.replies[len(calls) - 1]

    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(ai_agent, "_call_model", fake_call)
    fake_model.calls = calls
    return fake_model


def run(message, medications=(), context=()):
    return asyncio.run(ai_agent.interpret_medication_message(
        user_message=message, current_date=TODAY,
        medications=list(medications), conversation_context=list(context)))


def test_valid_add_needs_confirmation(fake_model):
    fake_model.replies = [reply(medication_name="ExampleMed", quantity_collected=60,
                                collection_date=TODAY, daily_quantity=1)]
    result = run("I collected 60 ExampleMed today, one a day")
    assert result["action"] == "add_medication"
    assert result["requires_confirmation"] is True
    assert result["parameters"]["collection_date"] == TODAY


def test_missing_name_becomes_clarification(fake_model):
    fake_model.replies = [reply(quantity_collected=30, collection_date=TODAY, daily_quantity=2)]
    result = run("I picked up 30 tablets, two a day")
    assert result["action"] == "ask_clarification"
    assert result["missing_fields"] == ["medication_name"]
    assert result["requires_confirmation"] is False


def test_future_date_and_silly_quantity_are_rejected(fake_model):
    fake_model.replies = [reply(medication_name="ExampleMed", quantity_collected=999999,
                                collection_date="2026-04-01", daily_quantity=1)]
    result = run("weird message")
    assert result["action"] == "ask_clarification"
    assert set(result["missing_fields"]) == {"quantity_collected", "collection_date"}


def test_invented_medication_id_is_not_trusted(fake_model):
    fake_model.replies = [reply("update_medication_supply", medication_id="made-up",
                                quantity_collected=60, collection_date=TODAY)]
    result = run("I collected more", medications=[MED])
    assert result["action"] == "ask_clarification"
    assert result["parameters"]["medication_id"] is None


def test_real_medication_id_is_kept(fake_model):
    fake_model.replies = [reply("update_medication_supply", medication_id="med-a",
                                quantity_collected=60, collection_date=TODAY)]
    result = run("another 60 today", medications=[MED])
    assert result["action"] == "update_medication_supply"
    assert result["parameters"]["medication_id"] == "med-a"


def test_bad_json_is_retried_once_then_falls_back(fake_model):
    fake_model.replies = ["not json", '{"action": "dance"}']
    result = run("hello")
    assert len(fake_model.calls) == 2
    assert result["action"] == "general_response"
    assert result["message"] == ai_agent.FALLBACK_MESSAGE


def test_dose_question_never_reaches_the_model(fake_model):
    fake_model.replies = []
    result = run("Should I double my dose today?")
    assert fake_model.calls == []
    assert result["message"] == ai_agent.SAFE_DOSE_MESSAGE


def test_general_response_drops_please_confirm(fake_model):
    fake_model.replies = [reply("general_response", message="Hi there! Please confirm these details.")]
    assert run("hi")["message"] == "Hi there!"


def test_context_has_date_table_and_saved_ids():
    from datetime import date
    block = ai_agent._context_block(date(2026, 3, 10), [MED])
    assert "Monday 2026-03-09 (yesterday)" in block
    assert 'id "med-a", ExampleMed' in block