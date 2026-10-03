"""Deterministic deadline, tracker and persistence logic."""
from __future__ import annotations
import json, os, re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional
import pandas as pd
from schemas import ScholarshipRecord

STATUSES = ["Not Started", "Preparing", "Ready to Apply", "Applied", "Submitted", "Rejected", "Accepted"]
STATE_PATH = Path(__file__).parent / "data" / "tracker_state.json"
# File persistence is OFF by default: on Streamlit Cloud the file would be shared by every visitor.
# Enable only for single-user local runs:  SCHOLARHUNTER_PERSIST=1
PERSIST = os.getenv("SCHOLARHUNTER_PERSIST", "0") == "1"
COLUMNS = ["id","country","scholarship_name","provider","level","deadline","deadline_status","days_remaining","urgency","verification_status","deadline_verified","deadline_source","requirements","funding","official_link","application_link","confidence","fit_score","fit_level","status","notes"]
_FORMATS = ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%m/%d/%Y","%d %B %Y","%d %b %Y","%B %d, %Y","%b %d, %Y","%B %d %Y","%b %d %Y")

def parse_deadline(value) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)): return None
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    s = str(value).strip()
    if not s or s.lower() in {"null","none","n/a","unknown","rolling","tbd","open"}: return None
    iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", s)
    if iso: s = iso.group(0)
    for fmt in _FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
            return d if 2000 <= d.year <= 2100 else None
        except ValueError: pass
    try:
        from dateutil import parser as dparser
        d = dparser.parse(s, fuzzy=False, dayfirst=False).date()
        return d if 2000 <= d.year <= 2100 else None
    except Exception: return None

def classify_deadline(deadline, today: Optional[date]=None, rolling: bool=False):
    if rolling: return "rolling", None, False
    d = parse_deadline(deadline)
    if d is None: return "unknown", None, False
    days = (d - (today or date.today())).days
    return ("expired" if days < 0 else "upcoming"), days, days < 0

def urgency(days, deadline_status="unknown"):
    if deadline_status == "expired": return "Expired"
    if deadline_status == "rolling": return "Rolling"
    if days is None or pd.isna(days): return "Needs Verification"
    if days <= 14: return "Critical"
    if days <= 45: return "Soon"
    return "Upcoming"

def records_to_df(records: Iterable[ScholarshipRecord]) -> pd.DataFrame:
    rows=[]
    for r in records:
        d=r.model_dump(); d["top_gaps"]="; ".join(r.top_gaps); d["fit_reasons"]="; ".join(r.fit_reasons); rows.append(d)
    df=pd.DataFrame(rows)
    if df.empty: return pd.DataFrame(columns=COLUMNS+["top_gaps","fit_reasons"])
    df["id"]=range(1,len(df)+1)
    for c in COLUMNS+["top_gaps","fit_reasons"]:
        if c not in df.columns: df[c]=None
    return recompute(df)

def recompute(df):
    df=df.copy()
    if df.empty: return df
    for i,row in df.iterrows():
        rolling=str(row.get("deadline_status") or "").lower()=="rolling"
        st,days,expired=classify_deadline(row.get("deadline"), rolling=rolling)
        df.at[i,"deadline_status"]=st; df.at[i,"days_remaining"]=days; df.at[i,"is_expired"]=expired; df.at[i,"urgency"]=urgency(days,st)
        if expired: df.at[i,"verification_status"]="expired"
    if "deadline_verified" not in df.columns: df["deadline_verified"]=False
    df["deadline_verified"]=df["deadline_verified"].fillna(False).astype(bool)
    df["days_remaining"]=pd.array(df["days_remaining"],dtype="Int64")
    df["status"]=df["status"].where(df["status"].isin(STATUSES),"Not Started")
    df["notes"]=df["notes"].fillna("")
    df["fit_score"]=pd.to_numeric(df["fit_score"],errors="coerce").fillna(0).astype(int).clip(0,100)
    df["fit_level"]=df["fit_score"].apply(lambda s:"High" if s>=70 else "Medium" if s>=45 else "Low")
    return df

def split_by_freshness(df):
    if df is None or df.empty:
        empty=pd.DataFrame(columns=df.columns if df is not None else COLUMNS); return empty,empty.copy(),empty.copy()
    d=recompute(df)
    expired=d[d["deadline_status"]=="expired"].copy()
    verified=d["deadline_verified"].fillna(False).astype(bool) if "deadline_verified" in d.columns else pd.Series(False,index=d.index)
    # A deadline counts as "current" ONLY if it was found in fetched source text (never LLM-only).
    current=d[d["deadline_status"].isin(["upcoming","rolling"])&verified].copy()
    needs=d[~d.index.isin(current.index)&~d.index.isin(expired.index)].copy()
    return current.reset_index(drop=True),needs.reset_index(drop=True),expired.reset_index(drop=True)

def status_counts(df):
    if df is None or df.empty: return dict(total=0,applied=0,preparing=0,not_started=0,critical=0,soon=0,verify=0)
    d=recompute(df); d=d[d["deadline_status"]!="expired"]; open_=d[~d["status"].isin(["Applied","Submitted","Rejected","Accepted"])]
    return dict(total=len(d),applied=int(d["status"].isin(["Applied","Submitted"]).sum()),preparing=int(d["status"].isin(["Preparing","Ready to Apply"]).sum()),not_started=int((d["status"]=="Not Started").sum()),critical=int((open_["urgency"]=="Critical").sum()),soon=int((open_["urgency"]=="Soon").sum()),verify=int((open_["urgency"]=="Needs Verification").sum()))

def urgent_list(df):
    if df is None or df.empty: return pd.DataFrame(columns=COLUMNS)
    d=recompute(df); m=d[(~d["status"].isin(["Applied","Submitted","Rejected","Accepted"]))&(d["urgency"].isin(["Critical","Soon"]))]
    return m.sort_values("days_remaining")

def plain_summary(df):
    c=status_counts(df); lines=[f"- {c['applied']} applied/submitted, {c['preparing']} preparing, {c['not_started']} not started."]
    for _,r in urgent_list(df).head(5).iterrows(): lines.append(f"- {r['scholarship_name']}: {int(r['days_remaining'])} days left ({r['urgency']}).")
    if c["verify"]: lines.append(f"- {c['verify']} opportunity/opportunities need deadline verification.")
    return "\n".join(lines)

def _key(row): return (str(row.get("official_link") or "") or str(row.get("scholarship_name") or "")).strip().lower().rstrip("/")
def load_state():
    if not PERSIST: return {}
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {}
def save_state(df):
    if not PERSIST: return
    try:
        STATE_PATH.parent.mkdir(parents=True,exist_ok=True); state={}
        for _,r in df.iterrows(): state[_key(r)]={"status":r.get("status","Not Started"),"notes":r.get("notes","") or "","deadline":r.get("deadline")}
        STATE_PATH.write_text(json.dumps(state,indent=2,default=str),encoding="utf-8")
    except Exception: pass
def apply_state(df):
    state=load_state()
    if df.empty or not state: return recompute(df)
    df=df.copy()
    for i,r in df.iterrows():
        s=state.get(_key(r))
        if s:
            df.at[i,"status"]=s.get("status",r.get("status","Not Started")); df.at[i,"notes"]=s.get("notes","")
            if s.get("deadline") and not r.get("deadline"): df.at[i,"deadline"]=s["deadline"]
    return recompute(df)
