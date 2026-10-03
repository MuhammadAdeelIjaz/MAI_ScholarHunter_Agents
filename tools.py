"""Web search, page extraction, deadline verification and CV parsing."""
from __future__ import annotations
import re, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None
import tracker

class SearchBudget:
    """Per-run search budget. One instance per pipeline run, so concurrent users never share results."""
    def __init__(self, max_calls=4):
        self.lock = threading.Lock()
        self.max_calls = max(1, min(int(max_calls), 5))
        self.used = 0
        self.results = []
        self.queries = []

    def run(self, query):
        """Run one capped DuckDuckGo search. Returns a short text summary (never raises)."""
        if DDGS is None:
            return "Search dependency missing. Install requirements.txt."
        with self.lock:
            if self.used >= self.max_calls:
                return "SEARCH LIMIT REACHED"
            self.used += 1
            self.queries.append(query)
            call_no = self.used
        hits, last_err = [], ""
        for _ in range(2):
            try:
                hits = list(DDGS().text(query, max_results=10) or [])
                if hits:
                    break
            except Exception as exc:
                last_err = str(exc)
        if not hits:
            return f"No results ({call_no}/{self.max_calls}). {last_err[:120]}"
        lines = []
        with self.lock:
            for h in hits[:8]:
                url = h.get("href") or h.get("url") or ""
                title = (h.get("title") or "").strip()
                snippet = (h.get("body") or h.get("snippet") or "").strip()
                if url:
                    self.results.append({"title": title, "url": url, "snippet": snippet, "query": query})
                    lines.append(f"- {title} | {url} | {snippet[:180]}")
        return "\n".join(lines)

_AGGREGATORS=("scholars4dev","scholarshipportal","scholarship-positions","opportunitiesforyouth","scholarshipsads","youthop","opportunitydesk","findaphd","fastweb","scholarshipdb","studyportals","topuniversities","scholarshipscorner","afterschoolafrica")
_BLOCKED=("facebook.","youtube.","youtu.be","linkedin.","reddit.","quora.","twitter.","x.com","instagram.","tiktok.","pinterest.")
def is_blocked(url): return any(b in urlparse(url).netloc.lower() for b in _BLOCKED)
def trust_score(url):
    host=urlparse(url).netloc.lower()
    if any(a in host for a in _AGGREGATORS): return 0
    if host.endswith(".edu") or ".edu." in host or ".ac." in host or host.endswith(".gov") or ".gov." in host or host.endswith(".int"): return 3
    if host.endswith(".org") or any(k in host for k in ("scholarship","fellowship","daad","chevening","fulbright")): return 2
    return 1
def norm_url(url):
    p=urlparse((url or "").strip().lower()); host=p.netloc[4:] if p.netloc.startswith("www.") else p.netloc; path=re.sub(r"/+","/",p.path or "").rstrip("/"); return f"{host}{path}"

_HEADERS={"User-Agent":"Mozilla/5.0 (compatible; ScholarHunterAgents/2.0)"}
def fetch_page(url,max_chars=6000):
    try:
        r=requests.get(url,headers=_HEADERS,timeout=10,allow_redirects=True)
        if r.status_code!=200 or "html" not in r.headers.get("content-type","").lower(): return ""
        soup=BeautifulSoup(r.text[:600000],"html.parser")
        for t in soup(["script","style","nav","footer","header","noscript","form","svg"]): t.decompose()
        return re.sub(r"\s+"," ",soup.get_text(" ",strip=True))[:max_chars]
    except Exception: return ""
def fetch_pages(urls,max_chars=6000):
    if not urls: return {}
    with ThreadPoolExecutor(max_workers=6) as ex: texts=list(ex.map(lambda u:fetch_page(u,max_chars),urls))
    return dict(zip(urls,texts))

_DEADLINE_WORDS=re.compile(r"(application\s+deadline|applications?\s+(?:close|closing|closes|must be submitted)|closing\s+date|submission\s+deadline|deadline|apply\s+by|last\s+date|due\s+date)",re.I)
_ROLLING_WORDS=re.compile(r"\b(rolling admissions?|rolling deadline|rolling basis|open year[- ]round|applications? (?:are )?accepted year[- ]round|no fixed deadline)\b",re.I)
_MON=r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE_PATTERNS=[
 re.compile(r"\b20\d{2}-\d{1,2}-\d{1,2}\b"),
 re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]20\d{2}\b"),
 re.compile(r"\b"+_MON+r"\.?\s+\d{1,2},?\s+20\d{2}\b",re.I),
 re.compile(r"\b\d{1,2}\s+"+_MON+r"\.?,?\s+20\d{2}\b",re.I)]
_YEARLESS=[
 re.compile(r"\b\d{1,2}\s+"+_MON+r"\b(?!\s*,?\s*\d)",re.I),
 re.compile(r"\b"+_MON+r"\.?\s+\d{1,2}\b(?!\s*,?\s*\d)",re.I)]
_ORDINAL=re.compile(r"(?<=\d)(?:st|nd|rd|th)\b",re.I)

def _yearless_to_date(raw, today):
    """'15 Oct' / 'October 15' -> next occurrence on/after today. Returned as UNVERIFIED by the caller."""
    for year in (today.year, today.year + 1):
        d = tracker.parse_deadline(f"{raw.replace(',', '')} {year}")
        if d and d >= today:
            return d
    return None

def extract_deadline(text,today:Optional[date]=None)->Tuple[Optional[str],str,Optional[int],bool]:
    """Return (iso_deadline, status, days_remaining, verified).
    verified=True only when a full date with a year sits next to a deadline keyword (or rolling is stated).
    Several dates -> earliest UPCOMING one (most actionable); if none upcoming -> latest past one (expired).
    Year-less dates are returned with verified=False so they never count as verified."""
    today = today or date.today()
    if not text: return None,"unknown",None,False
    text = _ORDINAL.sub("", text)
    if _ROLLING_WORDS.search(text): return None,"rolling",None,True
    full, yearless = [], []
    for kw in _DEADLINE_WORDS.finditer(text):
        start,end = max(0,kw.start()-60), min(len(text),kw.end()+200); window = text[start:end]
        for pattern in _DATE_PATTERNS:
            for m in pattern.finditer(window):
                d = tracker.parse_deadline(m.group(0))
                if d: full.append(d)
        for pattern in _YEARLESS:
            for m in pattern.finditer(window):
                d = _yearless_to_date(m.group(0), today)
                if d: yearless.append(d)
    if full:
        upcoming = sorted(d for d in full if d >= today)
        d = upcoming[0] if upcoming else max(full)
        status,days,_ = tracker.classify_deadline(d, today=today)
        return d.isoformat(),status,days,True
    if yearless:
        d = min(yearless); status,days,_ = tracker.classify_deadline(d, today=today)
        return d.isoformat(),status,days,False
    return None,"unknown",None,False

def verify_page(url,page_text="",snippet=""):
    deadline,status,days,verified = extract_deadline(" ".join(x for x in [page_text,snippet] if x)); trust = trust_score(url)
    got = deadline is not None or status == "rolling"
    return {"deadline":deadline,"deadline_status":status,"days_remaining":days,"is_expired":status=="expired",
            "deadline_verified":bool(verified and status in {"upcoming","expired","rolling"}),
            "deadline_source":url if got else "",
            "verification_status":"expired" if status=="expired" else "verified" if verified and trust>=2 else "partially_verified" if got else "unverified",
            "source_type":"official/preferred" if trust>=2 else "web"}

_EVIDENCE_WORDS=re.compile(r"(deadline|apply by|closing date|closes|ielts|toefl|gre|gpa|cgpa|funding|stipend|tuition|eligib|requirement|referee|recommendation|proposal|statement of purpose)",re.I)
def evidence_snippet(page, n=900):
    """Compact evidence for the LLM: page start plus windows around key words (keeps requests under the Groq TPM limit)."""
    page = page or ""
    if len(page) <= n: return page
    out = page[:260]; used = 260
    for m in _EVIDENCE_WORDS.finditer(page[260:]):
        if used >= n: break
        s = 260 + max(0, m.start()-50); chunk = page[s:s+170]
        if chunk[:40] in out: continue
        out += " … " + chunk; used += len(chunk) + 3
    return out[:n]

def dedupe_results(items):
    seen_urls=set(); seen_titles=set(); out=[]
    for item in items:
        u=norm_url(item.get("url","")); t=re.sub(r"[^a-z0-9]+"," ",item.get("title","").lower()).strip()
        if (u and u in seen_urls) or (t and t in seen_titles): continue
        if u: seen_urls.add(u)
        if t: seen_titles.add(t)
        out.append(item)
    return out

def clean_text(text):
    text=text.replace("\x00"," "); text=re.sub(r"[ \t\u00a0]+"," ",text); text=re.sub(r"[^\x09\x0A\x20-\x7E\u00A1-\uFFFF]","",text); text=re.sub(r"\n\s*\n+","\n\n",text); return text.strip()
def parse_cv(file_obj,filename="",max_chars=6000):
    if filename.lower().endswith(".txt"):
        raw=file_obj.read(); raw=raw.decode("utf-8",errors="ignore") if isinstance(raw,bytes) else str(raw); return clean_text(raw)[:max_chars]
    from pypdf import PdfReader
    reader=PdfReader(file_obj)
    if getattr(reader,"is_encrypted",False):
        try: reader.decrypt("")
        except Exception as exc: raise ValueError("The PDF is password protected.") from exc
    pages=[]
    for page in reader.pages:
        try: pages.append(page.extract_text() or "")
        except Exception: pass
    text=clean_text("\n".join(pages))
    if not text: raise ValueError("No readable text found. The PDF may be scanned and require OCR.")
    return text[:max_chars]
