# ScholarHunter Agents V2

Multi-agent scholarship discovery, verification, gap analysis and tracking (PakAngels GenAI & AgenticAI, Cohort 11, Hackathon 2).
Streamlit + CrewAI + Groq (`openai/gpt-oss-120b`) + DuckDuckGo (`ddgs`).

**Discover → Verify → Understand → Manage**

## What is AI and what is plain Python (honest map)

| Step | Who does it |
|---|---|
| Profile extraction from CV | LLM agent (CrewAI) |
| Search-query planning | LLM agent (CrewAI) |
| Running searches, fetching pages (max searches enforced) | Python tools |
| Deadline extraction, date normalisation, expired / upcoming / rolling | Python (deterministic, no LLM) |
| Structuring scholarship records | LLM agent (CrewAI) |
| Verification (a deadline counts only if found in fetched page text) | Python |
| Fit reasons and gap analysis | LLM agent (CrewAI) |
| Tracker, urgency, Excel/CSV export | Python |

Key rule: **an LLM-supplied date is never trusted.** A scholarship appears under *Current Opportunities* only if its deadline was found in source text and has not passed (or the page explicitly says rolling). Everything else goes to *Needs Verification*; expired items go to *Expired / historical*.

## Modes
* **Live** - real run using Groq (needs `GROQ_API_KEY`, or paste your own key in the sidebar).
* **Demo** - clearly labelled fictional sample data; no API, no network. Use this for the video and as a fallback during judging.

## Run locally (Python 3.11)
```bash
python3.11 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then put your key in .env (this file is git-ignored)
streamlit run app.py
python -m pytest -q tests       # 17 tests
```

## Deploy on Streamlit Community Cloud
1. Push this folder to a **public** GitHub repo (no `.env`, no `secrets.toml`; `.gitignore` already blocks them).
2. share.streamlit.io -> New app -> select repo, branch, main file `app.py`.
3. **Advanced settings -> Python version: 3.11** (important; an app created with another version must be deleted and re-created).
4. Advanced settings -> Secrets, paste: `GROQ_API_KEY = "your_key"`.
5. Deploy. Open the URL in a private window and test Demo mode first, then one Live run with 2 searches.

## Free-tier limits (Groq, gpt-oss-120b)
About 8,000 tokens/minute and 200,000 tokens/day per organisation (check your Groq console; limits change). The app therefore: caps searches (slider, max 5), sends compact page evidence to the LLM, pauses between stages, retries 429 errors using Groq's "try again in Xs" hint, and limits each browser session to 3 live runs.

## Files
`app.py` UI and session state · `crew.py` agents/tasks/orchestration · `tools.py` search, page fetch, deadline extraction, CV parsing · `tracker.py` dates, urgency, tracker · `schemas.py` Pydantic models · `export.py` CSV/Excel · `demo.py` sample data · `data/seed_scholarships.json` fallback hints (no dates) · `tests/`.

## Security
No keys in code. Key order: sidebar field -> Streamlit secrets -> environment/.env. Keys are redacted from error messages. CV text stays in the session and is not written to disk. Tracker file persistence is OFF by default (set `SCHOLARHUNTER_PERSIST=1` for single-user local use).

## Troubleshooting
| Symptom | Fix |
|---|---|
| Build fails on Streamlit Cloud | Recreate the app with Python 3.11 |
| "GROQ_API_KEY not found" | Add it in Secrets, or use Demo mode |
| "quota temporarily used up" / 429 | Wait ~1 minute, lower Max searches, or use your own key |
| Few or no current results | Normal when pages show no verifiable date; check *Needs Verification* |
