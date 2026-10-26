from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from db import InMemoryDB

TODAY = date.today()


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    """A new empty database for every test."""
    database = InMemoryDB()
    monkeypatch.setattr(main, "db", database)
    return database


@pytest.fixture
def client():
    return TestClient(main.app)


def add_body(**overrides):
    body = {"medication_name": "ExampleMed", "quantity_collected": 60,
            "collection_date": TODAY.isoformat(), "daily_quantity": 1}
    body.update(overrides)
    return body


def set_ai(monkeypatch, result=None, error=None):
    async def fake(**kwargs):
        if error:
            raise error
        return result
    monkeypatch.setattr(main, "interpret_medication_message", fake)


# ---------- confirm-add ----------
def test_confirm_add_saves_and_creates_two_reminders(client):
    r = client.post("/medications/confirm-add", json=add_body())
    assert r.status_code == 201
    data = r.json()
    assert data["success"] is True
    assert data["medication"]["estimated_end_date"] == (TODAY + timedelta(days=60)).isoformat()
    assert [x["kind"] for x in data["reminders"]] == ["14_day", "7_day"]
    assert len(client.get("/medications").json()["medications"]) == 1


@pytest.mark.parametrize("bad", [
    {"quantity_collected": 0},
    {"quantity_collected": -3},
    {"daily_quantity": 0},
    {"medication_name": "   "},
    {"collection_date": (TODAY + timedelta(days=10)).isoformat()},
    {"collection_date": (TODAY - timedelta(days=800)).isoformat()},
    {"collection_date": "not-a-date"},
])
def test_confirm_add_rejects_invalid_input(client, bad):
    assert client.post("/medications/confirm-add", json=add_body(**bad)).status_code == 422
    assert client.get("/medications").json()["medications"] == []


def test_confirm_add_duplicate_name_is_409(client):
    client.post("/medications/confirm-add", json=add_body())
    assert client.post("/medications/confirm-add",
                       json=add_body(medication_name="examplemed")).status_code == 409


def test_confirm_add_database_failure_does_not_report_success(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(main.db, "insert_medication", boom)
    r = client.post("/medications/confirm-add", json=add_body())
    assert r.status_code == 500
    assert "success" not in r.json()


# ---------- confirm-update ----------
def test_confirm_update_recalculates_and_replaces_reminders(client, fresh_db):
    added = client.post("/medications/confirm-add", json=add_body()).json()
    med_id = added["medication"]["id"]
    r = client.post("/medications/confirm-update", json={
        "medication_id": med_id, "quantity_collected": 30,
        "collection_date": TODAY.isoformat()})
    assert r.status_code == 200
    assert r.json()["medication"]["estimated_end_date"] == (
        TODAY + timedelta(days=30)).isoformat()
    statuses = [x["status"] for x in fresh_db.reminders]
    assert statuses.count("cancelled") == 2  # the two old ones
    assert statuses.count("pending") == len(r.json()["reminders"])


def test_confirm_update_unknown_medication_is_404(client):
    r = client.post("/medications/confirm-update", json={
        "medication_id": "does-not-exist", "quantity_collected": 30,
        "collection_date": TODAY.isoformat()})
    assert r.status_code == 404


def test_user_cannot_update_or_see_another_users_medication(client):
    med_id = client.post("/medications/confirm-add", json=add_body()).json()["medication"]["id"]
    main.app.dependency_overrides[main.get_current_user] = lambda: "someone-else"
    try:
        r = client.post("/medications/confirm-update", json={
            "medication_id": med_id, "quantity_collected": 30,
            "collection_date": TODAY.isoformat()})
        assert r.status_code == 404
        assert client.get("/medications").json()["medications"] == []
        assert client.delete(f"/medications/{med_id}").status_code == 404
    finally:
        main.app.dependency_overrides.clear()


# ---------- chat ----------
def test_chat_returns_ai_result_and_saves_nothing(client, monkeypatch):
    ai_result = {"action": "add_medication", "parameters": {"medication_name": "ExampleMed"},
                 "missing_fields": [], "requires_confirmation": True, "message": "Confirm?"}
    set_ai(monkeypatch, ai_result)
    r = client.post("/chat", json={"message": "I collected 60 tablets of ExampleMed"})
    assert r.status_code == 200
    assert r.json() == ai_result
    assert client.get("/medications").json()["medications"] == []


def test_chat_ai_unavailable_gives_503(client, monkeypatch):
    set_ai(monkeypatch, error=RuntimeError("Nebius down"))
    assert client.post("/chat", json={"message": "hi"}).status_code == 503


def test_chat_unsupported_action_is_replaced(client, monkeypatch):
    set_ai(monkeypatch, {"action": "delete_everything", "parameters": {}})
    assert client.post("/chat", json={"message": "hi"}).json()["action"] == "general_response"


def test_chat_non_dict_result_is_replaced(client, monkeypatch):
    set_ai(monkeypatch, "just a string")
    assert client.post("/chat", json={"message": "hi"}).json()["action"] == "general_response"


def test_chat_update_with_invented_medication_id_becomes_clarification(client, monkeypatch):
    client.post("/medications/confirm-add", json=add_body())
    set_ai(monkeypatch, {"action": "update_medication_supply",
                         "parameters": {"medication_id": "made-up-id"}})
    data = client.post("/chat", json={"message": "collected more"}).json()
    assert data["action"] == "ask_clarification"
    assert "ExampleMed" in data["message"]


def test_chat_passes_only_this_users_medications_to_ai(client, monkeypatch):
    client.post("/medications/confirm-add", json=add_body())
    seen = {}

    async def spy(**kwargs):
        seen.update(kwargs)
        return {"action": "general_response", "parameters": {}, "message": "ok"}
    monkeypatch.setattr(main, "interpret_medication_message", spy)

    client.post("/chat", json={"message": "hi"})
    assert [m["name"] for m in seen["medications"]] == ["ExampleMed"]
    assert "user_id" not in seen["medications"][0]
    assert seen["current_date"] == TODAY.isoformat()


def test_chat_rejects_empty_message(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422


# ---------- reminders ----------
def _add_ending_in(client, days):
    """Add a medication whose supply ends `days` days from today."""
    return client.post("/medications/confirm-add", json=add_body(
        quantity_collected=days, collection_date=TODAY.isoformat())).json()


def test_no_reminders_due_for_a_fresh_long_supply(client):
    client.post("/medications/confirm-add", json=add_body())
    assert client.get("/reminders").json()["reminders"] == []


def test_reminder_due_when_supply_nearly_over(client):
    _add_ending_in(client, 5)
    due = client.get("/reminders").json()["reminders"]
    assert len(due) == 1
    assert due[0]["medication_name"] == "ExampleMed"
    assert due[0]["days_left"] == 5


def test_acknowledge_removes_it_from_due_list(client):
    _add_ending_in(client, 5)
    rid = client.get("/reminders").json()["reminders"][0]["id"]
    assert client.post(f"/reminders/{rid}/acknowledge").status_code == 200
    assert client.get("/reminders").json()["reminders"] == []


def test_snooze_hides_reminder_until_later(client):
    _add_ending_in(client, 5)
    rid = client.get("/reminders").json()["reminders"][0]["id"]
    r = client.post(f"/reminders/{rid}/snooze", json={"days": 2})
    assert r.json()["reminder"]["snoozed_until"] == (TODAY + timedelta(days=2)).isoformat()
    assert client.get("/reminders").json()["reminders"] == []


def test_snooze_defaults_to_one_day_and_rejects_silly_values(client):
    _add_ending_in(client, 5)
    rid = client.get("/reminders").json()["reminders"][0]["id"]
    assert client.post(f"/reminders/{rid}/snooze", json={"days": 365}).status_code == 422
    r = client.post(f"/reminders/{rid}/snooze")
    assert r.json()["reminder"]["snoozed_until"] == (TODAY + timedelta(days=1)).isoformat()


def test_repeat_reminder_is_created_later_not_immediately(client, fresh_db):
    _add_ending_in(client, 5)
    rid = client.get("/reminders").json()["reminders"][0]["id"]
    client.post(f"/reminders/{rid}/acknowledge")
    # acknowledged today -> next repeat is 3 days away, so nothing is due now
    assert client.get("/reminders").json()["reminders"] == []
    repeats = [r for r in fresh_db.reminders if r["kind"] == "repeat"]
    assert len(repeats) == 1
    assert repeats[0]["remind_on"] == (TODAY + timedelta(days=main.REPEAT_EVERY_DAYS)).isoformat()
    # asking again must not create a second one
    client.get("/reminders")
    assert len([r for r in fresh_db.reminders if r["kind"] == "repeat"]) == 1


def test_cannot_acknowledge_cancelled_or_unknown_reminder(client):
    assert client.post("/reminders/nope/acknowledge").status_code == 404
    med = _add_ending_in(client, 5)["medication"]
    old_id = client.get("/reminders").json()["reminders"][0]["id"]
    client.post("/medications/confirm-update", json={
        "medication_id": med["id"], "quantity_collected": 60,
        "collection_date": TODAY.isoformat()})
    assert client.post(f"/reminders/{old_id}/acknowledge").status_code == 409


def test_delete_medication_removes_its_reminders(client, fresh_db):
    med = _add_ending_in(client, 5)["medication"]
    assert client.delete(f"/medications/{med['id']}").status_code == 200
    assert client.get("/medications").json()["medications"] == []
    assert fresh_db.reminders == []


# ---------- misc ----------
def test_health(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["database"] == "memory"
    assert data["ai"] in ("stub", "nemotron")


def test_login_token_required_when_demo_mode_off(client, monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", False)
    assert client.get("/medications").status_code == 401
    assert client.get("/medications",
                      headers={"Authorization": "Bearer junk"}).status_code == 401
