import pandas as pd
import tracker

def _df(rows):
    return pd.DataFrame(rows)

def test_split_freshness_requires_verified_deadline():
    df = _df([
        {"id":1,"scholarship_name":"A","deadline":"2099-01-01","deadline_status":"upcoming","deadline_verified":True,"status":"Not Started","fit_score":50,"notes":""},
        {"id":2,"scholarship_name":"B","deadline":"2001-01-01","deadline_status":"expired","deadline_verified":True,"status":"Not Started","fit_score":50,"notes":""},
        {"id":3,"scholarship_name":"C","deadline":None,"deadline_status":"unknown","deadline_verified":False,"status":"Not Started","fit_score":50,"notes":""},
        {"id":4,"scholarship_name":"D","deadline":"2099-06-01","deadline_status":"upcoming","deadline_verified":False,"status":"Not Started","fit_score":50,"notes":""},
        {"id":5,"scholarship_name":"E","deadline":None,"deadline_status":"rolling","deadline_verified":True,"status":"Not Started","fit_score":50,"notes":""},
    ])
    current, verify, expired = tracker.split_by_freshness(df)
    assert sorted(current["scholarship_name"]) == ["A", "E"]      # D (LLM-only date) must NOT be current
    assert expired["scholarship_name"].tolist() == ["B"]
    assert sorted(verify["scholarship_name"]) == ["C", "D"]

def test_counts_exclude_expired():
    df = _df([
        {"id":1,"scholarship_name":"A","deadline":"2099-01-01","deadline_status":"upcoming","deadline_verified":True,"status":"Applied","fit_score":50,"notes":""},
        {"id":2,"scholarship_name":"B","deadline":"2001-01-01","deadline_status":"expired","deadline_verified":True,"status":"Not Started","fit_score":50,"notes":""},
    ])
    c = tracker.status_counts(df)
    assert c["total"] == 1 and c["applied"] == 1
