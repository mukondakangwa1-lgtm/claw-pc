"""CLAW TUTOR v2 - the Student Agent (board-aware edition).
For every user who says they are a student: reads their documents (txt/md/pdf,
batch upload), searches the reference library and the web, knows their EXAM BODY
(TEVETA, ECZ, WAEC, Cambridge, IB), region and level - reads the body's public
pages for rules, hunts past-paper links, and generates clearly-labelled practice
papers. Plans run fundamentals -> exam-ready -> prodigy, tuned to curriculum,
region and level. Constitution: cite sources, never fabricate, honest about
what is official vs generated."""
import html as _h
import json
import re as _re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import requests
from . import config, brain

UA = {"User-Agent": "Mozilla/5.0 claw-tutor/2.0"}
WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"
MAX_DOC = 15 * 1024 * 1024

BODIES = {
    "teveta": {"name": "TEVETA Zambia (TVET)", "site": "http://www.teveta.org.zm",
               "region": "Zambia", "levels": "trade certificate, craft certificate, diploma (TEVETA qualifications)",
               "notes": "Technical Education, Vocational and Entrepreneurship Training Authority - registers TVET programs, sets competency standards and examinations."},
    "ecz": {"name": "ECZ Zambia (Examinations Council)", "site": "https://exams-council.org.zm",
            "region": "Zambia", "levels": "grade 7, grade 9 (junior secondary), school certificate (grade 12), GCE",
            "notes": "Runs national school examinations and awards certificates."},
    "waec": {"name": "WAEC (West Africa)", "site": "https://www.waecheadquarters.org",
             "region": "West Africa", "levels": "WASSCE (SS1-SS3)"},
    "caie": {"name": "Cambridge International (CAIE)", "site": "https://www.cambridgeinternational.org",
             "region": "international", "levels": "IGCSE, O Level, AS/A Level"},
    "ib": {"name": "International Baccalaureate", "site": "https://www.ibo.org",
           "region": "international", "levels": "PYP, MYP, DP"},
}

def _root() -> Path:
    return Path(config.__file__).resolve().parent.parent

def _db() -> sqlite3.Connection:
    d = _root() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(d / "students.db")
    conn.execute("""CREATE TABLE IF NOT EXISTS students(
        handle TEXT PRIMARY KEY, pace TEXT, program TEXT, exam_date TEXT, created TEXT)""")
    for col in ("body", "region", "level"):
        try:
            conn.execute(f"ALTER TABLE students ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass
    conn.execute("""CREATE TABLE IF NOT EXISTS plans(
        id INTEGER PRIMARY KEY, handle TEXT, subject TEXT, pace TEXT,
        plan TEXT, created TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS docs(
        id INTEGER PRIMARY KEY, handle TEXT, name TEXT, chars INT, added TEXT)""")
    return conn

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def ensure_student(handle, pace="standard", program="", exam_date="", level=""):
    h = (handle or "student").strip()[:40]
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO students(handle,pace,program,exam_date,created) "
                  "VALUES (?,?,?,?,?)", (h, pace, program, exam_date, _now()))
        if program:
            c.execute("UPDATE students SET program=? WHERE handle=?", (program, h))
        if pace or program or exam_date:
            c.execute("UPDATE students SET pace=COALESCE(NULLIF(?,''),pace), "
                      "program=COALESCE(NULLIF(?,''),program), "
                      "exam_date=COALESCE(NULLIF(?,''),exam_date) WHERE handle=?",
                      (pace, program, exam_date, h))
    return h

def set_body(handle, body_key, region="", level=""):
    h = ensure_student(handle)
    b = BODIES.get((body_key or "").lower().strip())
    with _db() as c:
        c.execute("UPDATE students SET body=?, region=COALESCE(NULLIF(?,''),region), "
                  "level=COALESCE(NULLIF(?,''),level) WHERE handle=?",
                  (b["site"] and (body_key or "").lower().strip(), region, level, h))
    return (f"profile saved: exam body = {b['name']}, region = {region or b['region']}, "
            f"level = {level or '(set yours)'}" if b else
            f"unknown body '{body_key}' - I know: {', '.join(sorted(BODIES))}")

def _student(handle):
    with _db() as c:
        r = c.execute("SELECT pace, program, exam_date, body, region, level "
                      "FROM students WHERE handle=?", (handle,)).fetchone()
    keys = ("pace", "program", "exam_date", "body", "region", "level")
    return dict(zip(keys, r)) if r else {}

# ---------------- documents (batch, big, pdf) ----------------

def add_doc(handle, name, text):
    h = ensure_student(handle)
    path = _root() / "workspace" / "student_docs"
    path.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in (name or "doc")[:60] if ch.isalnum() or ch in "._- ")
    (path / f"{h}__{safe}").write_text(text[:MAX_DOC], errors="ignore")
    with _db() as c:
        c.execute("INSERT INTO docs(handle,name,chars,added) VALUES (?,?,?,?)",
                  (h, safe, len(text), _now()))
    return f"stored '{safe}' ({len(text):,} chars) - it feeds into your plan, quizzes and lessons"

def add_media(handle, name, raw):
    """Images/slides a student uploads: stored to the media gallery (OCR comes later)."""
    path = _root() / "workspace" / "media"
    path.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in (name or "media")[:60] if ch.isalnum() or ch in "._- ")
    (path / f"student-{safe}").write_bytes(raw)
    return f"stored media '{safe}' ({len(raw)/1024:.0f} KB) in your gallery (text extraction for media comes later)"

def _docs_digest(handle, limit=10, per=6000):
    p = _root() / "workspace" / "student_docs"
    if not p.exists():
        return ""
    parts = []
    for f in sorted(p.glob(f"{handle}__*"))[-limit:]:
        try:
            t = f.read_text(errors="ignore")
        except Exception:
            continue
        parts.append(f"--- {f.name.split('__',1)[1]} ---\n{t[:per]}")
    return ("\n\nSTUDENT'S DOCUMENTS (read these closely):\n" + "\n".join(parts)) if parts else ""

def extract_pdf_text(raw):
    try:
        from pypdf import PdfReader
        import io
        r = PdfReader(io.BytesIO(raw))
        return "\n".join((pg.extract_text() or "") for pg in r.pages[:200])
    except Exception:
        return ""

def status(handle):
    h = ensure_student(handle)
    st = _student(h)
    with _db() as c:
        plan = c.execute("SELECT subject, created, plan FROM plans WHERE handle=? "
                         "ORDER BY id DESC LIMIT 1", (h,)).fetchone()
        docs = c.execute("SELECT name, chars FROM docs WHERE handle=? ORDER BY id", (h,)).fetchall()
    b = BODIES.get(st.get("body") or "", {})
    out = [f"student: {h} | pace: {st.get('pace')} | program: {st.get('program') or '-'} | "
           f"exam: {st.get('exam_date') or '-'}",
           f"exam body: {b.get('name', '-')} | region: {st.get('region') or b.get('region', '-')} | "
           f"level: {st.get('level') or '-'}",
           f"documents on file: {len(docs)}" + ("".join(f"\n  - {n} ({c_:,} chars)" for n, c_ in docs))]
    out.append(f"latest plan: {plan[0]} ({plan[1]})" if plan else "no plan yet - pick a subject!")
    if plan:
        out.append(plan[2][:1500])
    return "\n".join(out)

# ---------------- reference library ----------------

def wiki(subject):
    try:
        r = requests.get(WIKI + requests.utils.quote((subject or "").replace(" ", "_")),
                         headers=UA, timeout=20)
        if r.ok:
            j = r.json()
            return j.get("extract", ""), j.get("content_urls", {}).get("desktop", {}).get("page", "")
    except Exception:
        pass
    try:
        s = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=20, params={
            "action": "query", "list": "search", "srsearch": subject or "",
            "format": "json", "srlimit": 1}).json()
        hits = s["query"]["search"]
        if hits:
            return wiki(hits[0]["title"])
    except Exception:
        pass
    return "", ""

def _fetch_text(url, limit=4000):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    t = _re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
    t = _re.sub(r"<[^>]+>", " ", t)
    t = _h.unescape(_re.sub(r"\s+", " ", t)).strip()
    return t[:limit]

def _cache_path(key):
    p = _root() / "memory" / "bodies"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.txt"

def body_rules(body_key, force=False):
    """Read the exam body's public pages; summarize into a rules digest (cached 24h)."""
    b = BODIES.get((body_key or "").lower().strip())
    if not b:
        return f"unknown exam body '{body_key}'"
    key = (body_key or "").lower().strip()
    cf = _cache_path(key)
    import time as _t
    if cf.exists() and not force and _t.time() - cf.stat().st_mtime < 86400:
        return cf.read_text(errors="ignore")
    raw_pages = []
    for u in (b["site"], b["site"] + "/?s=examination+rules", b["site"] + "/?s=syllabus"):
        try:
            raw_pages.append(u.split(".z")[0].split("/")[2] + ": " + _fetch_text(u, 2500))
        except Exception:
            continue
    if not raw_pages:
        return (f"({b['name']}'s site is unreachable right now - {b['site']} - I will not invent "
                f"their rules. Ask your institution office for the current {b['name']} exam "
                f"regulations and upload them here: I will read them into your plan.)")
    ctx = ("EXAM BODY: " + b["name"] + " | region: " + b["region"] + " | levels: " + b["levels"] +
           "\n\nOFFICIAL SITE CONTENT:\n" + "\n\n".join(raw_pages)[:9000])
    reply, which = brain.think(
        "You are CLAW TUTOR. Summarize this exam body into a tight RULES DIGEST for students: "
        "structure of qualifications/levels, examination rules and regulations mentioned, "
        "registration/entry requirements, and what a student at each level must demonstrate. "
        "Only use the provided content - say 'not stated on the fetched pages' where missing. "
        "End with the official site URL.", extra_context=ctx)
    if reply.startswith("[offline"):
        return (f"({b['name']}: site reachable but my reasoning brain is offline - raw notes "
                f"saved. {b['site']})")
    out = f"RULES DIGEST - {b['name']} ({b['region']})\n{reply}"
    cf.write_text(out, errors="ignore")
    return out

def past_papers(body_key, subject):
    """Hunt for past-paper/syllabus links on the body's site. Honest when thin."""
    b = BODIES.get((body_key or "").lower().strip())
    if not b:
        return [f"unknown exam body '{body_key}'"]
    links, seen = [], set()
    for probe in (b["site"] + "/?s=" + requests.utils.quote(f"past papers {subject}"),
                  b["site"] + "/?s=" + requests.utils.quote(f"{subject} syllabus")):
        try:
            r = requests.get(probe, headers=UA, timeout=25)
            for m in _re.finditer(r'href="([^"#]+)"[^>]*>([^<]{0,90})', r.text):
                href, txt = m.group(1), m.group(2).strip()
                low = (href + " " + txt).lower()
                if any(k in low for k in ("paper", "past", "syllabus", "exam", ".pdf")) \
                        and href not in seen and not href.startswith("mailto"):
                    seen.add(href)
                    if href.startswith("/"):
                        href = b["site"] + href
                    links.append(f"- {txt[:70]}  {href}")
                if len(links) >= 8:
                    break
        except Exception:
            continue
    if not links:
        return [f"(no past-paper links surfaced on {b['name']}'s site for '{subject}' from here - "
                f"they are often distributed through institutions. Ask your institution exams office, "
                f"and check {b['site']} manually. Meanwhile: use GENERATE PRACTICE PAPER - clearly "
                f"labelled practice, never passed off as official.)"]
    return links[:8]

def practice_paper(handle, subject):
    """Generate an exam-style practice paper aligned to body/region/level - labelled."""
    st = _student(handle)
    b = BODIES.get(st.get("body") or "", {})
    extract, _ = wiki(subject)
    ctx = f"SUBJECT: {subject} | BODY: {b.get('name','none set')} | LEVEL: {st.get('level') or 'unspecified'} | REGION: {st.get('region') or b.get('region','unspecified')}"
    if extract:
        ctx += f"\nWIKIPEDIA: {extract[:800]}"
    dd = _docs_digest(handle, limit=4, per=3000)
    if dd:
        ctx += dd
    reply, which = brain.think(
        "You are CLAW TUTOR. Write a full practice examination paper for this subject, IN THE "
        "STYLE of the stated exam body and level (typical structure, marks allocation, duration). "
        "Label it clearly: 'GENERATED PRACTICE PAPER - modeled on <body> style, NOT an official "
        "past paper'. Include sections A/B/C, marks per question, and a marking guide after the "
        "questions.", extra_context=ctx)
    return reply

# ---------------- the teaching brain ----------------

_FRAME = ("You are CLAW TUTOR, the student agent of CLAW (created by Kudos). Your student is "
          "learning to full mastery. Rules: build from first principles; structure every plan "
          "as PHASES with milestones; get the student EXAM-READY FIRST for their exam body, "
          "region and level, then take them to prodigy level in their program. Align strictly "
          "to the curriculum of their exam body. Use the student's own documents. Cite real "
          "references (Wikipedia, standard textbooks by name). Never invent facts or official "
          "documents - say 'unknown', or clearly label generated practice material. Be warm, "
          "demanding, and precise.")

def _board_ctx(handle, subject=""):
    st = _student(handle)
    b = BODIES.get(st.get("body") or "", {})
    parts = []
    if b:
        parts.append(f"EXAM BODY: {b['name']} ({b['region']}) - level: {st.get('level') or 'unspecified'}. "
                     f"Align everything to this curriculum. Body notes: {b['notes']}")
    if st.get("exam_date"):
        parts.append(f"EXAM DATE: {st['exam_date']} - pace the plan backwards from it.")
    if st.get("program"):
        parts.append(f"PROGRAM: {st['program']}")
    rules = body_rules(st.get("body")) if b else ""
    if rules and not rules.startswith("("):
        parts.append(rules[:2500])
    if b and subject:
        links = past_papers(st.get("body"), subject)
        parts.append("PAST-PAPER SEARCH RESULTS (official links found):\n" + "\n".join(links)[:1500])
    return ("\n\nCURRICULUM CONTEXT:\n" + "\n".join(parts)) if parts else ""

def plan(handle, subject, pace="standard", exam_date="", program=""):
    h = ensure_student(handle, pace, program, exam_date)
    if not subject:
        return "tell me the subject, e.g. 'plan me for organic chemistry'"
    extract, link = wiki(subject)
    ctx = [f"SUBJECT: {subject} (pace: {pace}" + (f", exam: {exam_date}" if exam_date else "") + ")"]
    if extract:
        ctx.append(f"WIKIPEDIA ON THE SUBJECT: {extract[:1200]} (source: {link})")
    ctx.append(_board_ctx(h, subject))
    dd = _docs_digest(h)
    if dd:
        ctx.append(dd)
    reply, which = brain.think(
        _FRAME + "\n\nTASK: produce the COMPLETE learning plan: phases from fundamentals to "
        "exam-ready (matched to their exam body's style and rules) to prodigy in their program; "
        "weekly/daily cadence for their pace; key concepts per phase; practice/exam strategy "
        "including past-paper usage; how their uploaded documents map into the plan. End with "
        "the first three assignments.", extra_context="\n".join(ctx))
    with _db() as c:
        c.execute("INSERT INTO plans(handle,subject,pace,plan,created) VALUES (?,?,?,?,?)",
                  (h, subject, pace, reply, _now()))
    return reply

def teach(handle, topic):
    h = ensure_student(handle)
    extract, link = wiki(topic)
    ctx = f"TOPIC: {topic}" + (f"\nWIKIPEDIA: {extract[:1200]} ({link})" if extract else "")
    ctx += _board_ctx(h, topic)
    dd = _docs_digest(h, limit=3)
    if dd:
        ctx += dd
    reply, which = brain.think(_FRAME + "\n\nTASK: teach this topic now - from first principles, "
                               "with worked examples and one exercise the student must answer in "
                               "their next message.", extra_context=ctx)
    return reply, which

def quiz(handle, topic):
    h = ensure_student(handle)
    extract, _ = wiki(topic)
    ctx = f"QUIZ TOPIC: {topic}" + (f"\nWIKIPEDIA: {extract[:800]}" if extract else "")
    ctx += _board_ctx(h, topic)
    dd = _docs_digest(h, limit=2)
    if dd:
        ctx += dd
    reply, which = brain.think(_FRAME + "\n\nTASK: set a 10-question exam-style quiz on this topic "
                               "in the style of their exam body (mix recall, application, and one "
                               "essay). Give answers + marking guide AFTER the questions, clearly "
                               "separated.", extra_context=ctx)
    return reply
