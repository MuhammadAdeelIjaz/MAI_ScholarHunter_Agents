"""Pydantic models for ScholarHunter Agents V2."""
from __future__ import annotations
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_NULLS = {"", "null", "none", "n/a", "na", "unknown", "not stated", "not specified", "nil", "tbd"}

def clean_str(v: Any) -> Optional[str]:
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in _NULLS else s

def to_list(v: Any) -> List[str]:
    if v is None: return []
    if isinstance(v, str):
        return [p.strip() for p in v.replace(";", ",").split(",") if p.strip() and p.strip().lower() not in _NULLS]
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip() and str(x).strip().lower() not in _NULLS]
    return [str(v).strip()]

class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")

class CandidateProfile(_Base):
    name: Optional[str] = None
    highest_degree: Optional[str] = None
    field_of_study: Optional[str] = None
    institution: Optional[str] = None
    gpa: Optional[str] = None
    english_test: Optional[str] = None
    publications: Optional[str] = None
    research_experience: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    research_interests: List[str] = Field(default_factory=list)
    target_domain: Optional[str] = None
    target_level: Optional[str] = None
    countries: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)

    @field_validator("name", "highest_degree", "field_of_study", "institution", "gpa", "english_test", "publications", "target_domain", "target_level", mode="before")
    @classmethod
    def _opt_str(cls, v): return clean_str(v)

    @field_validator("research_experience", "skills", "research_interests", "countries", "keywords", mode="before")
    @classmethod
    def _lists(cls, v): return to_list(v)

class RawResult(_Base):
    title: str = ""
    url: str
    snippet: str = ""
    query: str = ""
    page_text: str = ""
    trust: int = 1
    deadline: Optional[str] = None
    deadline_status: str = "unknown"
    days_remaining: Optional[int] = None

class ScholarshipRecord(_Base):
    id: Optional[int] = None
    country: str = "Unknown"
    scholarship_name: str
    provider: str = "Unknown"
    level: str = ""
    deadline: Optional[str] = None
    deadline_type: str = "unknown"
    deadline_status: str = "unknown"
    days_remaining: Optional[int] = None
    is_expired: bool = False
    requirements: str = ""
    funding: str = ""
    official_link: str = ""
    application_link: str = ""
    deadline_source: str = ""
    source_type: str = "web"
    verification_status: str = "unverified"
    deadline_verified: bool = False
    confidence: str = "low"
    fit_score: int = 0
    fit_level: str = "Low"
    top_gaps: List[str] = Field(default_factory=list)
    fit_reasons: List[str] = Field(default_factory=list)
    status: str = "Not Started"
    notes: str = ""

    @field_validator("deadline", mode="before")
    @classmethod
    def _deadline(cls, v): return clean_str(v)

    @field_validator("country", "provider", mode="before")
    @classmethod
    def _unknown_default(cls, v): return clean_str(v) or "Unknown"

    @field_validator("level", "funding", "official_link", "application_link", "deadline_source", "deadline_type", "deadline_status", "source_type", "verification_status", "notes", mode="before")
    @classmethod
    def _text(cls, v): return clean_str(v) or ""

    @field_validator("requirements", mode="before")
    @classmethod
    def _reqs(cls, v): return ", ".join(to_list(v))

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        s = (clean_str(v) or "low").lower()
        return s if s in {"high", "medium", "low"} else "low"

    @field_validator("fit_score", mode="before")
    @classmethod
    def _fit(cls, v):
        try: return max(0, min(100, int(float(v))))
        except Exception: return 0

    @field_validator("top_gaps", "fit_reasons", mode="before")
    @classmethod
    def _lists2(cls, v): return to_list(v)

    @model_validator(mode="after")
    def _consistency(self):
        if not self.deadline and self.deadline_status != "rolling":
            self.deadline_status = "unknown"
            self.deadline_verified = False
        self.fit_level = "High" if self.fit_score >= 70 else "Medium" if self.fit_score >= 45 else "Low"
        return self

class GapItem(_Base):
    url: str = ""
    fit_score: int = 0
    top_gaps: List[str] = Field(default_factory=list)
    fit_reasons: List[str] = Field(default_factory=list)

    @field_validator("fit_score", mode="before")
    @classmethod
    def _fit(cls, v):
        try: return max(0, min(100, int(float(v))))
        except Exception: return 0

    @field_validator("top_gaps", "fit_reasons", mode="before")
    @classmethod
    def _list_fields(cls, v): return to_list(v)[:5]

class GapReport(_Base):
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    per_item: List[GapItem] = Field(default_factory=list)

    @field_validator("strengths", "gaps", "recommendations", mode="before")
    @classmethod
    def _lists(cls, v): return to_list(v)
