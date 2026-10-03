from datetime import date, timedelta
import crew, tools, demo
from schemas import ScholarshipRecord, CandidateProfile, RawResult

def test_llm_deadline_without_evidence_is_dropped_and_not_verified():
    rec = ScholarshipRecord(scholarship_name="X", official_link="https://nowhere.example/x", deadline="2099-01-01",
                            deadline_verified=True, verification_status="verified")   # LLM tries to spoof
    out = crew._post_verify([rec], [], CandidateProfile(keywords=["ai"]), "PhD")
    assert out[0].deadline is None and out[0].deadline_verified is False and out[0].verification_status == "unverified"

def test_evidence_deadline_is_verified_and_expired_removed():
    fut = (date.today() + timedelta(days=20)).strftime("%d %B %Y"); past = (date.today() - timedelta(days=20)).strftime("%d %B %Y")
    raw = [RawResult(url="https://a.edu/p", page_text=f"Application deadline: {fut}."), RawResult(url="https://b.edu/p", page_text=f"Application deadline: {past}.")]
    recs = [ScholarshipRecord(scholarship_name="A", official_link="https://a.edu/p"), ScholarshipRecord(scholarship_name="B", official_link="https://b.edu/p")]
    out = crew._post_verify(recs, raw, CandidateProfile(keywords=["ai"]), "PhD")
    assert [r.scholarship_name for r in out] == ["A"] and out[0].deadline_verified is True and out[0].days_remaining in (19, 20)

def test_duplicates_removed_by_url_and_name():
    recs = [ScholarshipRecord(scholarship_name="Test Award", official_link="https://a.edu/x"),
            ScholarshipRecord(scholarship_name="Test Award", official_link="https://other.edu/y"),
            ScholarshipRecord(scholarship_name="Another", official_link="https://www.a.edu/x/")]
    out = crew._post_verify(recs, [], CandidateProfile(keywords=[]), "PhD")
    assert [r.scholarship_name for r in out] == ["Test Award"]

def test_search_budget_cap(monkeypatch):
    class FakeDDGS:
        def text(self, q, max_results=10): return [{"href": "https://u.edu/" + q, "title": "t", "body": "b"}]
    monkeypatch.setattr(tools, "DDGS", FakeDDGS)
    b = tools.SearchBudget(2)
    b.run("a"); b.run("b")
    assert b.run("c") == "SEARCH LIMIT REACHED" and len(b.queries) == 2

def test_budgets_do_not_share_results(monkeypatch):
    class FakeDDGS:
        def text(self, q, max_results=10): return [{"href": "https://u.edu/" + q, "title": "t", "body": "b"}]
    monkeypatch.setattr(tools, "DDGS", FakeDDGS)
    b1, b2 = tools.SearchBudget(3), tools.SearchBudget(3)
    b1.run("one"); b2.run("two")
    assert [r["query"] for r in b1.results] == ["one"] and [r["query"] for r in b2.results] == ["two"]

def test_evidence_snippet_is_bounded():
    page = "intro " * 50 + " IELTS 6.5 required. " + "filler " * 800 + " Application deadline: 1 Dec 2030. " + "tail " * 300
    assert len(tools.evidence_snippet(page, 800)) <= 800

def test_demo_records_split_correctly():
    import pandas as pd, tracker
    df = tracker.apply_state(tracker.records_to_df(demo.demo_records()))
    current, verify, expired = tracker.split_by_freshness(df)
    assert len(current) == 3 and len(expired) == 1 and len(verify) == 1
