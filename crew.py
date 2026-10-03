"""CrewAI + Groq orchestration for ScholarHunter Agents V2."""
from __future__ import annotations
import json, os, re, time
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY","true")
os.environ.setdefault("CREWAI_TRACING_ENABLED","false")
os.environ.setdefault("OTEL_SDK_DISABLED","true")
from crewai import LLM, Agent, Crew, Process, Task
import tools, tracker
from schemas import CandidateProfile, GapReport, RawResult, ScholarshipRecord

MODEL=os.getenv("GROQ_MODEL","groq/openai/gpt-oss-120b")
SEED_PATH=Path(__file__).parent/"data"/"seed_scholarships.json"
_REACT_LINE=re.compile(r"^\s*(thought|action|action input|observation|final answer)\s*:",re.I)
_PLAIN="Reply directly with the requested content as plain text. Do not call any tools or functions."
NO_TOOLS="\n\nDo not call any tools or functions. Reply with plain text only."

def _sanitize(messages):
    out=[]
    for m in messages:
        content=m.get("content") if isinstance(m,dict) else None
        if not isinstance(content,str): out.append(m); continue
        keep=[]
        for line in content.split("\n"):
            low=line.lower()
            if _REACT_LINE.match(line) or "i must use these formats" in low or "to give my best complete final answer" in low: continue
            keep.append(line)
        out.append({**m,"content":re.sub(r"(?i)final answer","answer","\n".join(keep))})
    out.append({"role":"user","content":_PLAIN}); return out

def _retry_after(msg):
    """Parse Groq's 'try again in 7.4s' / '1m3.4s' hint (seconds)."""
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)s", msg, re.I)
    if not m: return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))

class GptOssGroqLLM(LLM):
    """CrewAI LLM that calls Groq through LiteLLM and returns plain text (gpt-oss rejects ReAct tool formats)."""
    def __init__(self, api_key, temperature=0.1):
        super().__init__(model=MODEL, api_key=api_key, temperature=temperature, max_tokens=2000)
        self._groq_key = api_key; self._temp = temperature
        self.max_out = 2000   # set per stage by the pipeline (reasoning tokens count against this)

    def call(self, messages, *args, **kwargs):
        import litellm
        if isinstance(messages, str): messages = [{"role": "user", "content": messages}]
        clean = _sanitize(messages); last = None
        for attempt in range(4):
            try:
                resp = litellm.completion(model=MODEL, api_key=self._groq_key, messages=clean, temperature=self._temp, max_tokens=self.max_out, timeout=90)
                text = (resp.choices[0].message.content or "").strip()
                if not text: raise ValueError("Model returned an empty answer")
                return "Thought: done\nFinal Answer: " + text
            except Exception as exc:
                last = exc; low = str(exc).lower()
                if "request too large" in low or "413" in low:
                    raise RuntimeError("The request is larger than the Groq free-tier per-minute token limit. Lower 'Max searches' and try again.") from None
                if attempt < 3 and ("429" in low or "rate limit" in low or "rate_limit" in low):
                    time.sleep(min((_retry_after(str(exc)) or 12) + 1.5, 40)); continue
                if attempt < 3 and any(k in low for k in ("tool_use_fail", "tool choice is none", "empty answer", "timeout", "overloaded", "503")):
                    clean = clean + [{"role": "user", "content": "Return ordinary text only."}]; time.sleep(2); continue
                raise
        raise last

def get_llm(api_key,temperature=0.1): return GptOssGroqLLM(api_key,temperature)

def _balanced(text,start):
    open_c=text[start]; close_c="}" if open_c=="{" else "]"; depth=0; in_str=False; esc=False
    for j in range(start,len(text)):
        c=text[j]
        if in_str:
            if esc: esc=False
            elif c=="\\": esc=True
            elif c=='"': in_str=False
            continue
        if c=='"': in_str=True
        elif c==open_c: depth+=1
        elif c==close_c:
            depth-=1
            if depth==0: return text[start:j+1]
    return None

def extract_json(text):
    t=re.sub(r"^```(?:json)?\s*|\s*```$","",str(text or "").strip(),flags=re.I).strip()
    try: return json.loads(t)
    except Exception: pass
    for i,ch in enumerate(t):
        if ch in "{[":
            chunk=_balanced(t,i)
            if chunk:
                try: return json.loads(chunk)
                except Exception: pass
    raise ValueError("Could not find valid JSON in model output")

def _run(agent_factory:Callable[[],Agent],description,expected,inputs,attempts=3):
    last=None
    for attempt in range(attempts):
        agent=agent_factory(); task=Task(description=description+NO_TOOLS,expected_output=expected,agent=agent)
        try:
            out=Crew(agents=[agent],tasks=[task],process=Process.sequential,verbose=False).kickoff(inputs={k:str(v) for k,v in inputs.items()})
            return getattr(out,"raw",None) or str(out)
        except Exception as exc:
            last=exc
            if attempt<attempts-1 and any(k in str(exc).lower() for k in ("429","rate limit","timeout","overloaded","tool_use_fail")):
                time.sleep(4*(attempt+1)); continue
            raise
    raise last

def _run_json(factory,description,expected,inputs):
    raw=_run(factory,description,expected,inputs)
    try: return extract_json(raw)
    except ValueError: return extract_json(_run(factory,description+"\nReturn ONLY valid JSON. No prose or code fences.",expected,inputs,attempts=2))

def analyze_profile(cv_text,interests,domain,countries,level,llm):
    llm.max_out=2000
    def factory(): return Agent(role="Academic Profile Analyst",goal="Convert candidate information into a precise search-ready profile.",backstory="Extract only stated facts; missing information stays null.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
    desc=("Build a candidate profile. Never invent facts.\nLevel: {level}\nInterests: {interests}\nDomain: {domain}\nCountries: {countries}\nCV:\n{cv_text}\n\nReturn JSON with name, highest_degree, field_of_study, institution, gpa, english_test, publications, research_experience(list), skills(list), research_interests(list), target_domain, target_level, countries(list), keywords(list of 6-10 concise search terms).")
    data=_run_json(factory,desc,"One JSON object.",dict(level=level,interests=interests or "not provided",domain=domain or "not provided",countries=", ".join(countries),cv_text=(cv_text or "not provided")[:4000]))
    if isinstance(data,list): data=data[0] if data else {}
    p=CandidateProfile(**data); p.countries=countries; p.target_level=level
    if domain: p.target_domain=domain
    if interests and not p.research_interests: p.research_interests=[x.strip() for x in re.split(r"[,;\n]",interests) if x.strip()]
    kws=list(p.keywords)
    for x in [*p.research_interests,p.field_of_study,p.target_domain,f"{level} scholarship","fully funded"]:
        if x and x.lower() not in {k.lower() for k in kws}: kws.append(x)
    p.keywords=kws[:10]; return p

def _fallback_queries(profile,level):
    year=date.today().year; base=profile.target_domain or (profile.research_interests[0] if profile.research_interests else profile.field_of_study or ""); countries=profile.countries or [""]
    qs=[f'{level} fully funded scholarship {c} {base} application deadline {year} open' for c in countries]
    qs += [f'{level} fully funded {base} deadline {year} university',f'{level} fellowship {base} applications open {year}']
    return [re.sub(r"\s+"," ",q).strip() for q in qs]

def scout_opportunities(profile,level,max_searches,llm)->Tuple[List[RawResult],List[str],str]:
    """LLM plans the queries; Python executes the capped searches and fetches pages; dates are extracted deterministically."""
    max_searches=max(1,min(int(max_searches),5)); budget=tools.SearchBudget(max_searches); llm.max_out=1000
    def factory(): return Agent(role="Scholarship Intelligence Scout",goal="Plan searches for current open funded opportunities on official sources.",backstory="Prefer current-cycle university, government and programme pages.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
    desc=("Today is {today}. Plan exactly {n} searches for CURRENT or UPCOMING scholarships/funded positions.\nKeywords: {keywords}\nCountries: {countries}\nLevel: {level}\nEach query should include level, country where possible, current year, and freshness terms like 'applications open' or 'application deadline'. Prefer official sources. Return ONLY a JSON array of strings.")
    warning=""; queries=[]
    try:
        data=_run_json(factory,desc,"JSON array of search query strings.",dict(today=date.today().isoformat(),n=max_searches,keywords=", ".join(profile.keywords),countries=", ".join(profile.countries),level=level))
        if isinstance(data,dict): data=data.get("queries",[])
        queries=[str(q).strip() for q in data if str(q).strip()]
    except Exception as exc: warning=f"Scout planning failed ({str(exc)[:90]}); fallback searches were used."
    for q in _fallback_queries(profile,level):
        if len(queries)>=max_searches: break
        if q not in queries: queries.append(q)
    for q in queries[:max_searches]: budget.run(q)
    items=[]
    for item in list(budget.results):
        url=item.get("url","")
        if not url.startswith("http") or tools.is_blocked(url): continue
        item["trust"]=tools.trust_score(url); items.append(item)
    items=tools.dedupe_results(sorted(items,key=lambda x:-x["trust"]))[:14]
    pages=tools.fetch_pages([i["url"] for i in items[:10]],max_chars=6000)
    raw=[]
    for item in items:
        page=pages.get(item["url"],""); v=tools.verify_page(item["url"],page,item.get("snippet",""))
        if v["deadline_status"]=="expired": continue
        raw.append(RawResult(title=item.get("title",""),url=item["url"],snippet=item.get("snippet",""),query=item.get("query",""),page_text=page,trust=item["trust"],deadline=v["deadline"],deadline_status=v["deadline_status"],days_remaining=v["days_remaining"]))
    # keep the best-evidenced items first (deadline found, then trust)
    raw.sort(key=lambda r:(r.deadline is None and r.deadline_status!="rolling", -r.trust))
    return raw,list(budget.queries),warning

def _load_seed():
    try: return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except Exception: return []
def seed_records(level,countries):
    wanted={c.lower() for c in countries}; out=[]
    for s in _load_seed():
        if level and level.lower() not in s.get("level","").lower(): continue
        out.append(ScholarshipRecord(**s,deadline=None,confidence="low",verification_status="unverified",notes="Seed discovery hint only. Verify live cycle and deadline on official site."))
    out.sort(key=lambda r:0 if r.country.lower() in wanted else 1); return out[:10]

def _architect(llm): return Agent(role="Scholarship Data Architect",goal="Turn web evidence into clean scholarship records.",backstory="Never invent deadlines or eligibility facts.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
def _task_database(raw,level,llm):
    llm.max_out=2800
    payload=[{"title":r.title[:120],"url":r.url,"snippet":r.snippet[:220],"evidence":tools.evidence_snippet(r.page_text,800),"detected_deadline":r.deadline,"detected_status":r.deadline_status} for r in raw[:8]]
    desc=("Build one record per DISTINCT scholarship/fellowship/funded position. Use only supplied evidence. Never invent a deadline. Preserve detected_deadline when provided. Prefer supplied URL as official_link. Target level: {level}\nRESULTS:\n{results}\nReturn ONLY JSON array with country, scholarship_name, provider, level, deadline, requirements, funding, official_link, application_link, confidence.")
    data=_run_json(lambda:_architect(llm),desc,"JSON array.",dict(level=level,results=json.dumps(payload,ensure_ascii=False)))
    if isinstance(data,dict): data=data.get("records") or data.get("scholarships") or []
    out=[]
    for item in data if isinstance(data,list) else []:
        try: out.append(ScholarshipRecord(**item))
        except Exception: pass
    return out

def _gap_agent(llm): return Agent(role="Application Readiness Mentor",goal="Explain strengths, gaps and next actions without overclaiming.",backstory="Reason only from profile and scholarship evidence.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
def _task_gap(profile,records,llm):
    llm.max_out=2200
    payload=[{"url":r.official_link,"name":r.scholarship_name,"country":r.country,"level":r.level,"requirements":r.requirements[:200]} for r in records[:8]]
    desc=("Candidate profile: {profile}\nScholarships: {items}\nReturn JSON with strengths(3-5), gaps(3-5), recommendations(3-5), per_item. Each per_item has url, fit_score(0-100 AI-estimated), top_gaps(max3), fit_reasons(max3). Use known facts only.")
    data=_run_json(lambda:_gap_agent(llm),desc,"One JSON gap report.",dict(profile=profile.model_dump_json(),items=json.dumps(payload,ensure_ascii=False)))
    if isinstance(data,list): data={"per_item":data}
    return GapReport(**data)
def _heuristic_fit(profile,rec,level):
    text=f"{rec.scholarship_name} {rec.provider} {rec.country} {rec.level} {rec.requirements}".lower(); hits=0
    for kw in profile.keywords:
        words=re.findall(r"[a-z]{4,}",kw.lower())
        if words and any(w in text for w in words): hits+=1
    return max(0,min(100,30+7*hits+(10 if level.lower() in text else 0)))
def _name_key(rec): return re.sub(r"[^a-z0-9]+","",rec.scholarship_name.lower())
def _find_evidence(rec,raw_by_url,raw_by_host):
    ev=raw_by_url.get(tools.norm_url(rec.official_link))
    if ev: return ev
    host=urlparse(rec.official_link).netloc.lower().replace("www.","") if rec.official_link else ""
    return raw_by_host.get(host)
def _post_verify(records,raw,profile,level):
    """Deterministic verification. Nothing the LLM says about deadline/verification is trusted."""
    raw_by_url={tools.norm_url(r.url):r for r in raw}; raw_by_host={}
    for r in raw: raw_by_host.setdefault(urlparse(r.url).netloc.lower().replace("www.",""),r)
    out=[]; seen_url=set(); seen_name=set()
    for rec in records:
        ukey=tools.norm_url(rec.official_link); nkey=_name_key(rec)
        if (ukey and ukey in seen_url) or (nkey and nkey in seen_name): continue
        if ukey: seen_url.add(ukey)
        if nkey: seen_name.add(nkey)
        rec.deadline_verified=False; rec.deadline_source=""
        evidence=_find_evidence(rec,raw_by_url,raw_by_host)
        if evidence:
            v=tools.verify_page(evidence.url,evidence.page_text,evidence.snippet)
            rec.deadline=v["deadline"]   # only a date found in source text is kept; LLM-only dates are dropped
            rec.deadline_status=v["deadline_status"]; rec.days_remaining=v["days_remaining"]; rec.is_expired=v["is_expired"]; rec.deadline_verified=v["deadline_verified"]; rec.deadline_source=v["deadline_source"]; rec.verification_status=v["verification_status"]; rec.source_type=v["source_type"]
        else:
            rec.deadline=None; rec.deadline_status="unknown"; rec.days_remaining=None; rec.is_expired=False; rec.verification_status="unverified"
        if rec.is_expired: continue
        if not rec.fit_score: rec.fit_score=_heuristic_fit(profile,rec,level)
        rec.fit_level="High" if rec.fit_score>=70 else "Medium" if rec.fit_score>=45 else "Low"; out.append(rec)
    return out

def build_database_and_gaps(profile,raw,level,llm,parallel=False):
    warning=""
    if not raw:
        seeds=seed_records(level,profile.countries)
        return seeds,GapReport(gaps=["No live opportunity with a verifiable current cycle was found in this search."],recommendations=["Broaden countries/keywords or retry later, then verify seed hints on official sites."]),"No live current opportunities were verified. Seed discovery hints are shown separately and are not treated as current."
    try: records=_task_database(raw,level,llm)
    except Exception as exc:
        warning=f"Database structuring failed ({str(exc)[:100]}). Conservative records were built from search evidence."
        records=[ScholarshipRecord(scholarship_name=r.title or urlparse(r.url).netloc,provider=urlparse(r.url).netloc.replace("www.",""),country=next((c for c in profile.countries if c.lower() in (r.title+" "+r.snippet).lower()),"Unknown"),level=level,deadline=r.deadline,official_link=r.url,confidence="low",notes="Auto-built from search evidence; review official page.") for r in raw]
    records=_post_verify(records,raw,profile,level)
    try: gap=_task_gap(profile,records,llm) if records else GapReport()
    except Exception as exc: gap=GapReport(); warning += f" Gap analysis failed: {str(exc)[:90]}"
    by_url={tools.norm_url(x.url):x for x in gap.per_item if x.url}
    for rec in records:
        item=by_url.get(tools.norm_url(rec.official_link))
        if item:
            rec.fit_score=item.fit_score or rec.fit_score; rec.top_gaps=item.top_gaps; rec.fit_reasons=item.fit_reasons; rec.fit_level="High" if rec.fit_score>=70 else "Medium" if rec.fit_score>=45 else "Low"
    return records,gap,warning.strip()

def tracker_summary(df,llm): return tracker.plain_summary(df)
