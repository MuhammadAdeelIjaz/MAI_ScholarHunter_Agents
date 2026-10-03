"""ScholarHunter Agents V2 - Streamlit UI (Discover -> Verify -> Understand -> Manage)."""
import os
import re
import sys
import time

# Some Streamlit Cloud images ship an old sqlite3 that chromadb (used by CrewAI) rejects.
# If pysqlite3-binary is installed, use it; otherwise silently continue with the system sqlite3.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except Exception:
    pass

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import crew as sh_crew
import demo
import export
import tracker
from tools import parse_cv

st.set_page_config(page_title="ScholarHunter Agents", page_icon="🎓", layout="wide")

COUNTRIES = ["United Kingdom", "United States", "Germany", "Canada", "Australia", "China", "Turkey", "Hungary",
             "Japan", "South Korea", "Sweden", "Netherlands", "France", "Italy", "Malaysia", "Norway", "Finland"]
MAX_LIVE_RUNS = 3          # per browser session - protects the shared free-tier Groq quota
STAGE_PAUSE_SECONDS = 4    # short pause between stages to stay under the free-tier tokens-per-minute limit

DEFAULT_STATE = {
    "profile": None, "queries": [], "all_df": None, "current_df": None, "verify_df": None, "expired_df": None,
    "work_df": None, "gap": None, "summary": "", "warnings": [], "run_id": 0, "mode_used": None,
    "live_runs": 0, "export_csv": None, "export_xlsx": None,
}
for _k, _v in DEFAULT_STATE.items():
    st.session_state.setdefault(_k, _v)


# ----------------------------------------------------------------------------- helpers
def get_api_key(user_key: str = "") -> str:
    """Order: key typed in the sidebar, Streamlit secrets, environment/.env. Never printed or logged."""
    if user_key and user_key.strip():
        return user_key.strip()
    try:
        if "GROQ_API_KEY" in st.secrets:
            return str(st.secrets["GROQ_API_KEY"]).strip().strip('"').strip("'")
    except Exception:
        pass
    return os.getenv("GROQ_API_KEY", "").strip()


def redact(message, key: str = "") -> str:
    message = str(message)
    if key:
        message = message.replace(key, "***")
    return re.sub(r"gsk_[A-Za-z0-9]+", "***", message)[:400]


def friendly_error(exc: Exception, key: str = "") -> str:
    low = str(exc).lower()
    if "429" in low or "rate limit" in low:
        return "The free Groq quota is temporarily used up. Wait about a minute, lower 'Max searches', or use Demo mode."
    if "401" in low or "invalid api key" in low or "authentication" in low:
        return "The Groq API key was rejected. Check GROQ_API_KEY in Secrets / .env."
    if "request too large" in low or "413" in low:
        return "The request was too large for the free-tier limit. Lower 'Max searches' and retry."
    return "The run stopped unexpectedly: " + redact(exc, key)


def persist_frames(df: pd.DataFrame) -> None:
    """Recompute every derived table once and cache export bytes, so downloads never need to rerun anything."""
    df = tracker.recompute(df)
    current, verify, expired = tracker.split_by_freshness(df)
    st.session_state.all_df = df
    st.session_state.work_df = df
    st.session_state.current_df = current
    st.session_state.verify_df = verify
    st.session_state.expired_df = expired
    st.session_state.summary = tracker.plain_summary(df)
    st.session_state.export_csv = export.to_csv_bytes(df)
    st.session_state.export_xlsx = export.to_excel_bytes(df, st.session_state.gap)


def store_results(profile, queries, records, gap, warnings, mode):
    df = tracker.apply_state(tracker.records_to_df(records))
    st.session_state.profile = profile
    st.session_state.queries = queries
    st.session_state.gap = gap
    st.session_state.warnings = [w for w in warnings if w]
    st.session_state.mode_used = mode
    st.session_state.run_id += 1
    persist_frames(df)


def run_demo(level, countries):
    store_results(demo.demo_profile(level, countries), ["(demo mode - no searches were run)"], demo.demo_records(),
                  demo.demo_gap(), ["DEMO MODE: all data below is fictional SAMPLE data for demonstration. Nothing was searched."], "demo")


def run_live(cv_file, interests, domain, level, countries, max_searches, api_key):
    if st.session_state.live_runs >= MAX_LIVE_RUNS:
        st.warning(f"Live-run limit reached ({MAX_LIVE_RUNS} per session) to protect the shared free quota. Use Demo mode, or reload the page later.")
        return
    cv_text = ""
    if cv_file is not None:
        try:
            cv_text = parse_cv(cv_file, cv_file.name)
        except Exception as exc:
            st.error(f"Could not read the CV: {redact(exc)}")
            return
    with st.status("Running ScholarHunter workflow...", expanded=True) as status:
        try:
            llm = sh_crew.get_llm(api_key)
            st.write("1/4 Profile Analyst (LLM)")
            profile = sh_crew.analyze_profile(cv_text, interests, domain, countries, level, llm)
            time.sleep(STAGE_PAUSE_SECONDS)
            st.write("2/4 Scholarship Scout (LLM plans searches; Python searches, fetches pages, extracts deadlines)")
            raw, queries, warn1 = sh_crew.scout_opportunities(profile, level, max_searches, llm)
            time.sleep(STAGE_PAUSE_SECONDS)
            st.write("3/4 Database + Verification + Gap Analysis (LLM structures; Python verifies dates)")
            records, gap, warn2 = sh_crew.build_database_and_gaps(profile, raw, level, llm)
            st.write("4/4 Tracker (deterministic)")
            st.session_state.live_runs += 1
            store_results(profile, queries, records, gap, [warn1, warn2], "live")
            status.update(label="Workflow complete", state="complete", expanded=False)
        except Exception as exc:
            status.update(label="Run failed", state="error")
            st.error(friendly_error(exc, api_key))


def tracker_table(df: pd.DataFrame, name: str) -> None:
    """Editable status/notes table. Edits are merged by row id, so rows with empty links can never collide."""
    show = ["id", "scholarship_name", "country", "provider", "deadline", "days_remaining", "urgency", "verification_status",
            "deadline_source", "fit_level", "official_link", "status", "notes"]
    cols = [c for c in show if c in df.columns]
    edited = st.data_editor(
        df[cols], hide_index=True, width="stretch", key=f"editor_{name}_{st.session_state.run_id}",
        disabled=[c for c in cols if c not in {"status", "notes"}],
        column_config={
            "id": None,
            "official_link": st.column_config.LinkColumn("Official source", display_text="Open"),
            "deadline_source": st.column_config.LinkColumn("Deadline found at", display_text="Source"),
            "status": st.column_config.SelectboxColumn("Status", options=tracker.STATUSES),
            "days_remaining": st.column_config.NumberColumn("Days left"),
        })
    master = st.session_state.work_df.copy()
    changed = False
    for _, row in pd.DataFrame(edited).iterrows():
        mask = master["id"] == row["id"]
        new_status = row["status"] if row["status"] in tracker.STATUSES else "Not Started"
        new_notes = row["notes"] if isinstance(row["notes"], str) else ""
        if mask.any() and (master.loc[mask, "status"].iloc[0] != new_status or master.loc[mask, "notes"].iloc[0] != new_notes):
            master.loc[mask, "status"] = new_status
            master.loc[mask, "notes"] = new_notes
            changed = True
    if changed:
        tracker.save_state(master)
        persist_frames(master)
        st.rerun()


# ----------------------------------------------------------------------------- sidebar
st.title("🎓 ScholarHunter Agents")
st.caption("Discover → Verify → Understand → Manage")

with st.sidebar:
    st.header("Candidate inputs")
    mode = st.radio("Mode", ["Live (uses Groq)", "Demo (sample data, no API)"], index=0)
    cv_file = st.file_uploader("Upload CV (PDF or TXT)", type=["pdf", "txt"], key="cv_uploader")
    interests = st.text_area("Research interests", height=90)
    domain = st.text_input("Target domain (optional)")
    level = st.selectbox("Level", ["MS", "PhD", "Postdoc"])
    selected = st.multiselect("Countries", COUNTRIES, default=["United Kingdom", "Germany", "Turkey"])
    custom = st.text_input("Other countries (comma-separated)")
    max_searches = st.slider("Max searches", 1, 5, 3, help="Fewer searches use fewer tokens (free tier: 8,000 tokens/minute).")
    user_key = st.text_input("Your own Groq key (optional)", type="password", help="Used only for this session; never stored or shown.")
    run_clicked = st.button("🚀 Run Agents", type="primary", width="stretch")

if run_clicked:
    countries = list(dict.fromkeys(selected + [c.strip() for c in custom.split(",") if c.strip()]))
    if mode.startswith("Demo"):
        run_demo(level, countries)
    else:
        key = get_api_key(user_key)
        if not key:
            st.error("GROQ_API_KEY not found. Add it in Streamlit Secrets or a local .env file, paste your own key in the sidebar, or switch to Demo mode.")
        elif not cv_file and not interests.strip():
            st.error("Upload a CV or enter research interests.")
        elif not countries:
            st.error("Select at least one country.")
        else:
            run_live(cv_file, interests, domain, level, countries, max_searches, key)

# ----------------------------------------------------------------------------- tabs
tab_profile, tab_current, tab_verify, tab_gap, tab_tracker, tab_export = st.tabs(
    ["Profile", "Current Opportunities", "Needs Verification", "Gap Analysis", "Tracker", "Export"])

with tab_profile:
    p = st.session_state.profile
    if p is None:
        st.info("Choose a mode, enter your profile and click Run Agents.")
    else:
        for w in st.session_state.warnings:
            st.warning(w)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Highest degree", p.highest_degree or "Not stated")
        c2.metric("Field", p.field_of_study or "Not stated")
        c3.metric("GPA", p.gpa or "Not stated")
        c4.metric("English test", p.english_test or "Not stated")
        st.markdown("**Research interests:** " + (", ".join(p.research_interests) or "Not stated"))
        st.markdown("**Skills:** " + (", ".join(p.skills) or "Not stated"))
        st.markdown("**Search keywords:** " + (", ".join(p.keywords) or "—"))
        st.markdown("**Target countries:** " + (", ".join(p.countries) or "—"))
        with st.expander("Search queries used (why these results were found)"):
            for q in st.session_state.queries:
                st.write("•", q)

with tab_current:
    current = st.session_state.current_df
    if current is None:
        st.info("Run the agents to see current opportunities.")
    else:
        st.subheader(f"Current opportunities ({len(current)})")
        st.caption("Only opportunities whose deadline was found in fetched source text (or explicitly rolling) and has not passed. "
                   "Always confirm on the official site before applying.")
        if current.empty:
            st.warning("No opportunity with a verified current deadline was found. See 'Needs Verification' or broaden the search.")
        else:
            tracker_table(current, "current")

with tab_verify:
    verify, expired = st.session_state.verify_df, st.session_state.expired_df
    if verify is None:
        st.info("Run the agents first.")
    else:
        st.subheader(f"Needs verification ({len(verify)})")
        st.caption("A current deadline could not be confirmed from a source page. Open the link and check the official site.")
        if verify.empty:
            st.success("No unverified items.")
        else:
            tracker_table(verify, "verify")
        with st.expander(f"Expired / historical ({0 if expired is None else len(expired)})"):
            if expired is not None and not expired.empty:
                st.dataframe(expired[[c for c in ["scholarship_name", "country", "deadline", "official_link"] if c in expired.columns]],
                             hide_index=True, width="stretch")
            else:
                st.write("No expired items in this result set.")

with tab_gap:
    gap, work = st.session_state.gap, st.session_state.work_df
    if gap is None or work is None:
        st.info("Run the agents first.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("✅ Strengths")
            for x in gap.strengths or ["Not enough evidence to list strengths."]:
                st.markdown(f"- {x}")
        with c2:
            st.subheader("⚠️ Gaps")
            for x in gap.gaps or ["No gap analysis available."]:
                st.markdown(f"- {x}")
        st.subheader("🎯 Recommended actions")
        for x in gap.recommendations or ["No recommendations available."]:
            st.markdown(f"- {x}")
        st.subheader("Per-opportunity fit")
        st.caption("Match scores are AI estimates, not predictions of success.")
        live = work[work["deadline_status"] != "expired"]
        for _, r in live.sort_values("fit_score", ascending=False).iterrows():
            with st.expander(f"{r['scholarship_name']} | {r['fit_level']} match"):
                st.write(f"AI-estimated match score: {int(r['fit_score'])}/100")
                if r.get("fit_reasons"):
                    st.write("Why:", r["fit_reasons"])
                if r.get("top_gaps"):
                    st.write("Top gaps:", r["top_gaps"])
                if r.get("requirements"):
                    st.write("Requirements found:", r["requirements"])

with tab_tracker:
    work = st.session_state.work_df
    if work is None or work.empty:
        st.info("Run the agents first.")
    else:
        c = tracker.status_counts(work)
        m = st.columns(5)
        m[0].metric("Total", c["total"])
        m[1].metric("Applied/Submitted", c["applied"])
        m[2].metric("Preparing", c["preparing"])
        m[3].metric("Critical", c["critical"])
        m[4].metric("Need verification", c["verify"])
        st.markdown(st.session_state.summary or tracker.plain_summary(work))
        urgent = tracker.urgent_list(work)
        if not urgent.empty:
            st.subheader("🔥 Urgent deadlines")
            st.dataframe(urgent[["scholarship_name", "deadline", "days_remaining", "urgency", "status"]], hide_index=True, width="stretch")

with tab_export:
    work = st.session_state.work_df
    if work is None or work.empty:
        st.info("Nothing to export yet.")
    else:
        st.caption("Downloads use bytes already stored in session state. They do not rerun the pipeline or clear results.")
        if st.session_state.export_xlsx is None or st.session_state.export_csv is None:
            persist_frames(work)
        st.download_button("⬇️ Download Excel", data=st.session_state.export_xlsx, file_name="scholarhunter_v2.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch", on_click="ignore")
        st.download_button("⬇️ Download CSV", data=st.session_state.export_csv, file_name="scholarhunter_v2.csv",
                           mime="text/csv", width="stretch", on_click="ignore")
