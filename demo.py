"""Demo mode: clearly-labelled SAMPLE data so the app works with no API key and no network.
These are fictional programmes for UI demonstration only - not real scholarships."""
from __future__ import annotations
from datetime import date, timedelta
from schemas import CandidateProfile, GapReport, GapItem, ScholarshipRecord

def demo_profile(level="PhD", countries=None):
    return CandidateProfile(
        name="Sample Candidate", highest_degree="MS Electrical Engineering", field_of_study="Computer Vision",
        research_interests=["computer vision", "deep learning", "image processing"],
        skills=["Python", "PyTorch", "OpenCV"], target_level=level, countries=countries or ["Germany", "United Kingdom"],
        keywords=["computer vision", "deep learning", "image processing", f"{level} scholarship", "fully funded"])

def demo_records():
    t = date.today()
    def rec(name, prov, country, days, status, fit, gaps, reasons, ver="verified", verified=True, roll=False):
        return ScholarshipRecord(
            scholarship_name=name + " (SAMPLE)", provider=prov, country=country, level="PhD",
            deadline=None if roll or days is None else (t + timedelta(days=days)).isoformat(),
            deadline_status="rolling" if roll else status, deadline_verified=verified, verification_status=ver,
            deadline_source="https://example.edu/sample-source", official_link="https://example.edu/" + name.lower().replace(" ", "-"),
            requirements="CV, SOP, Research proposal, IELTS, 2 referees", funding="Tuition + monthly stipend (sample)",
            confidence="medium", fit_score=fit, top_gaps=gaps, fit_reasons=reasons)
    return [
        rec("Demo Vision Fellowship", "Sample University A", "Germany", 9, "upcoming", 82, ["IELTS not confirmed"], ["PhD level matches", "Computer vision matches"]),
        rec("Demo AI Research Scholarship", "Sample Institute B", "United Kingdom", 33, "upcoming", 71, ["Research proposal required"], ["Degree matches", "Country preference matches"]),
        rec("Demo Open Call Programme", "Sample Foundation C", "Canada", None, "rolling", 58, ["Publication requirement unclear"], ["Field is related"], roll=True),
        rec("Demo Closed Programme", "Sample University D", "Japan", -12, "expired", 64, [], []),
        rec("Demo Unverified Listing", "Unknown", "Australia", None, "unknown", 40, ["Deadline could not be verified"], ["Keyword match only"], ver="unverified", verified=False),
    ]

def demo_gap():
    return GapReport(
        strengths=["Relevant MS degree and computer-vision focus", "Python / PyTorch skills match typical requirements"],
        gaps=["English test score not confirmed", "Publication record not evidenced in the CV"],
        recommendations=["Book IELTS/TOEFL and confirm each programme's minimum", "Draft a 2-page research proposal", "Request two recommendation letters early"],
        per_item=[GapItem(url="", fit_score=0)])
