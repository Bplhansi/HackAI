from datetime import date, timedelta

import pytest

import supply

TODAY = date(2026, 11, 1)


def test_end_date_60_tablets_one_a_day():
    assert supply.estimate_end_date(date(2026, 11, 1), 60, 1) == date(2026, 12, 31)


def test_end_date_two_a_day():
    assert supply.estimate_end_date(date(2026, 11, 1), 60, 2) == date(2026, 12, 1)


def test_end_date_uses_whole_days_only():
    # 30 tablets at 4/day = 7.5 days -> 7 whole days
    assert supply.estimate_end_date(date(2026, 11, 1), 30, 4) == date(2026, 11, 8)


@pytest.mark.parametrize("qty,daily", [(0, 1), (-5, 1), (60, 0), (60, -1)])
def test_end_date_rejects_bad_numbers(qty, daily):
    with pytest.raises(ValueError):
        supply.estimate_end_date(date(2026, 11, 1), qty, daily)


def test_reminder_dates_normal():
    end = TODAY + timedelta(days=60)
    assert supply.reminder_dates(end, TODAY) == [
        ("14_day", end - timedelta(days=14)),
        ("7_day", end - timedelta(days=7)),
    ]


def test_reminder_dates_skips_past_dates():
    end = TODAY + timedelta(days=10)  # 14-day date is in the past, 7-day is not
    assert supply.reminder_dates(end, TODAY) == [("7_day", end - timedelta(days=7))]


def test_reminder_dates_all_past_gives_one_reminder_today():
    end = TODAY + timedelta(days=3)
    assert supply.reminder_dates(end, TODAY) == [("7_day", TODAY)]
    assert supply.reminder_dates(TODAY - timedelta(days=5), TODAY) == [("7_day", TODAY)]


def test_days_left():
    assert supply.days_left(TODAY + timedelta(days=5), TODAY) == 5
    assert supply.days_left(TODAY - timedelta(days=2), TODAY) == -2


def _rem(status, kind="7_day", remind_on=TODAY, snoozed_until=None, ack=None):
    return {"status": status, "kind": kind, "remind_on": remind_on.isoformat(),
            "snoozed_until": snoozed_until.isoformat() if snoozed_until else None,
            "acknowledged_at": ack.isoformat() if ack else None}


def test_is_due():
    assert supply.is_due(_rem("pending", remind_on=TODAY), TODAY)
    assert not supply.is_due(_rem("pending", remind_on=TODAY + timedelta(days=1)), TODAY)
    assert supply.is_due(_rem("snoozed", snoozed_until=TODAY), TODAY)
    assert not supply.is_due(_rem("snoozed", snoozed_until=TODAY + timedelta(days=2)), TODAY)
    assert not supply.is_due(_rem("acknowledged"), TODAY)
    assert not supply.is_due(_rem("cancelled"), TODAY)


def test_repeat_not_before_final_week():
    end = TODAY + timedelta(days=20)
    assert supply.next_repeat_date(end, [_rem("acknowledged", ack=TODAY)], TODAY, 3, 5) is None


def test_repeat_not_while_a_reminder_is_open():
    end = TODAY + timedelta(days=3)
    assert supply.next_repeat_date(end, [_rem("pending")], TODAY, 3, 5) is None
    assert supply.next_repeat_date(
        end, [_rem("snoozed", snoozed_until=TODAY + timedelta(days=1))], TODAY, 3, 5) is None


def test_repeat_comes_after_interval_following_acknowledge():
    end = TODAY + timedelta(days=3)
    reminders = [_rem("acknowledged", ack=TODAY)]
    assert supply.next_repeat_date(end, reminders, TODAY, 3, 5) == TODAY + timedelta(days=3)


def test_repeat_stops_after_maximum():
    end = TODAY - timedelta(days=30)
    reminders = [_rem("acknowledged", kind="repeat", ack=TODAY - timedelta(days=i))
                 for i in range(5)]
    assert supply.next_repeat_date(end, reminders, TODAY, 3, 5) is None