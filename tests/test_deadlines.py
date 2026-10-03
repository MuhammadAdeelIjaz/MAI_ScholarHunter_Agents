from datetime import date
import tracker, tools

def test_upcoming_deadline():
    status, days, expired = tracker.classify_deadline("2026-10-20", today=date(2026,10,3))
    assert (status, days, expired) == ("upcoming",17,False)

def test_expired_deadline():
    status, days, expired = tracker.classify_deadline("2026-09-30", today=date(2026,10,3))
    assert (status, days, expired) == ("expired",-3,True)

def test_extract_deadline_near_keyword():
    deadline, status, days, verified = tools.extract_deadline("Applications are open. The application deadline is 15 October 2026. Apply online.", today=date(2026,10,3))
    assert (deadline,status,days,verified) == ("2026-10-15","upcoming",12,True)

def test_rolling():
    deadline, status, days, verified = tools.extract_deadline("Applications accepted year-round on a rolling admission basis.")
    assert deadline is None and status == "rolling" and days is None and verified is True

def test_missing_deadline_not_invented():
    deadline, status, days, verified = tools.extract_deadline("This programme offers full funding to PhD students.")
    assert deadline is None and status == "unknown" and days is None and verified is False


def test_ordinal_and_multiple_dates_pick_earliest_upcoming():
    text = "Early deadline: 1st November 2026. Final application deadline: December 15th, 2026."
    deadline, status, days, verified = tools.extract_deadline(text, today=date(2026,10,3))
    assert deadline == "2026-11-01" and status == "upcoming" and verified is True

def test_only_past_dates_is_expired():
    deadline, status, days, verified = tools.extract_deadline("Application deadline: 5 March 2025.", today=date(2026,10,3))
    assert status == "expired" and deadline == "2025-03-05"

def test_yearless_date_is_never_verified():
    deadline, status, days, verified = tools.extract_deadline("Applications close 15 October.", today=date(2026,10,3))
    assert deadline == "2026-10-15" and verified is False
