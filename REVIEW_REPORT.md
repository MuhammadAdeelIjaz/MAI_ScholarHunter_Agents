# Review report: ScholarHunter_Agents_V2 (GPT-generated code)

Tested on Python 3.11 (resolved: crewai 0.134.0, streamlit 1.49.1, litellm 1.72.0). Original: 6 tests passed, imports OK, CrewAI accepted the custom LLM.

## Defects found and fixed
| # | Problem | Impact | Fix |
|---|---|---|---|
| 1 | LLM-supplied deadlines counted as "current" (an unverified date went to Current Opportunities) | Violates "never present unverified as current"; hallucinated dates | Current = deadline found in fetched text (or explicit rolling) AND not expired; LLM dates without evidence are dropped; LLM cannot set `verified` flags |
| 2 | DB step sent ~12 pages x 2.5K chars (~9-10K tokens) + 4,200 max tokens in ONE request | Exceeds Groq free-tier 8K tokens/min -> 413/429 failures (most likely cause of deployment errors) | 8 items, ~800-char evidence windows, per-stage max tokens (1.0-2.8K), 4 s stage pauses, 429 retry using Groq's retry-after hint, clear message on 413 |
| 3 | Global search budget/results shared by all users | Concurrent users mixed results | Per-run `SearchBudget` object |
| 4 | Tracker edits matched on `official_link` | Rows with empty links overwrote each other | Edits merged by row `id` |
| 5 | Tracker saved to one shared JSON file | Visitors saw each other's notes | File persistence off by default (`SCHOLARHUNTER_PERSIST=1` to enable) |
| 6 | Profile was never displayed | Missing required "profile" output | New Profile tab incl. queries used |
| 7 | Deadline source not shown/exported | Spec: "where did this deadline come from?" | `deadline_source` column (link) in UI, CSV, Excel |
| 8 | Dates like "15th October 2026", "Sept", year-less dates; first date chosen blindly | Missed deadlines | Ordinal/Sept handling, earliest upcoming date wins, year-less dates returned unverified |
| 9 | Dependencies unpinned in a wide range; `pysqlite3-binary` unconditional | Possible build failures on newer Python | Pinned tested crewai/streamlit; pysqlite3 only on Linux Python < 3.14; README says use Python 3.11 |
| 10 | `use_container_width` deprecated; downloads could rerun | Future breakage / state risk | `width="stretch"`; `on_click="ignore"` on downloads |
| 11 | Counts included expired items; duplicates only by URL | Wrong totals | Expired excluded; dedupe by URL and name |
| 12 | No fallback when API quota is exhausted | Dead demo | Demo mode (labelled sample data), sidebar own-key field, 3 live runs per session |
| 13 | `env.example` misnamed, duplicate `config.toml`, no secrets template | Setup confusion | `.env.example`, `.streamlit/secrets.toml.example`, duplicate removed |

## Still not done vs. the upgrade prompt (be honest in the presentation)
* Scout is **not tool-calling**: the LLM plans queries, Python runs the searches. Present it as "LLM-planned, tool-executed".
* Verification is deterministic Python (not a separate LLM agent).
* No `storage.py` / SQLite; results live in the browser session (refresh loses them). Export Excel to keep work.
* Flat file structure (not the suggested folders); seed list has 6 hints without dates.
* Live behaviour with the real Groq/DuckDuckGo services could not be run in this review (no keys/network); everything else was tested with mocked LLM/search.
