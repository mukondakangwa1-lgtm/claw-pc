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

# +++ pre-profile chat +++

_NUDGE = ("\n\n🎓 One step left: save your details above "
          "(name, exam body, level, program, pace) - I will keep asking until you do. "
          "Then I turn this chat into your full learning plan.")

def chat(handle, msg):
    """Casual conversation before details are submitted (with a friendly nudge);
    full tutor mode once the student has saved their details."""
    st = _student(handle)
    enrolled = bool(st.get("program") or st.get("level") or st.get("body"))
    low = (msg or "").lower()
    wants_study = any(k in low for k in ("teach", "lesson", "plan me", "quiz",
                                         "syllabus", "past paper", "revise", "explain"))
    if enrolled:
        if wants_study:
            return teach(handle, msg)
        reply, which = brain.think(
            "You are CLAW (created by Kudos - never name any other maker). Your student, "
            "who has already saved their details, is chatting casually. Reply warmly and "
            "naturally in a few sentences; stay honest; no lectures.",
            extra_context="MESSAGE: " + msg)
        return reply, which
    if wants_study:
        reply, which = teach(handle, msg)
        return reply + _NUDGE, which
    reply, which = brain.think(
        "You are CLAW (created by Kudos - never name any other maker). A visitor is chatting "
        "on your public study site before saving their student details. Answer warmly and "
        "naturally, like a person, in a few sentences; no lectures; never invent facts. "
        "Finish with ONE short friendly line asking them to save their details so you can "
        "build their personalised learning plan.",
        extra_context="MESSAGE: " + msg)
    return reply + _NUDGE, which

# +++ visuals v3 +++
def _wiki_image(title):
    """Deep fallback: first real photo inside the article (skips logos/icons)."""
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=15, params={
            "action": "query", "generator": "images", "titles": (title or "")[:80],
            "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 640, "format": "json",
            "gimlimit": 20}).json()
        pages = (r.get("query") or {}).get("pages") or {}
        for pg in pages.values():
            for ii in pg.get("imageinfo") or []:
                u = (ii.get("thumburl") or ii.get("url") or "").split("?")[0]
                low = u.lower()
                if low.endswith((".jpg", ".jpeg", ".png")) and not any(
                        x in low for x in ("logo", "icon", "commons-logo", "wiki-", "ambox",
                                           "question_book", "edit-", "symbol", "stub")):
                    return u
    except Exception:
        pass
    return ""

def wiki(subject):
    try:
        r = requests.get(WIKI + requests.utils.quote((subject or "").replace(" ", "_")),
                         headers=UA, timeout=20)
        if r.ok:
            j = r.json()
            img = ((j.get("thumbnail", {}) or {}).get("source", "")
                   or (j.get("originalimage", {}) or {}).get("source", "")
                   or _wiki_image((j.get("titles", {}) or {}).get("normalized", "") or subject))
            return (j.get("extract", ""), j.get("content_urls", {}).get("desktop", {}).get("page", ""), img)
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
    return "", "", ""

_NUDGE = ("\n\n🎓 One step left: save your details above "
          "(name, exam body, level, program, pace) - I will keep asking until you do. Then I turn this chat into your full learning plan.")

def chat(handle, msg):
    """Casual conversation before details are submitted (with a friendly nudge);
    full tutor mode once the student has saved their details."""
    st = _student(handle)
    enrolled = bool(st.get("program") or st.get("level") or st.get("body"))
    low = (msg or "").lower()
    wants_study = any(k in low for k in ("teach", "lesson", "plan me", "quiz",
                                         "syllabus", "past paper", "revise", "explain",
                                         "show me", "picture", "diagram"))
    if enrolled:
        if wants_study:
            r, w, img = teach(handle, msg)
            return r, w, img
        reply, which = brain.think(
            "You are CLAW (created by Kudos - never name any other maker). Your student, "
            "who has already saved their details, is chatting casually. Reply warmly and "
            "naturally in a few sentences; stay honest; no lectures.",
            extra_context="MESSAGE: " + msg)
        return reply, which, ""
    if wants_study:
        r, w, img = teach(handle, msg)
        return r + _NUDGE, w, img
    reply, which = brain.think(
        "You are CLAW (created by Kudos - never name any other maker). A visitor is chatting "
        "on your public study site before saving their student details. Answer warmly and "
        "naturally, like a person, in a few sentences; no lectures; never invent facts. "
        "Finish with ONE short friendly line asking them to save their details so you can "
        "build their personalised learning plan.",
        extra_context="MESSAGE: " + msg)
    return reply + _NUDGE, which, ""

# +++ brain v4 +++
def _wiki_image(title):
    """Deep fallback: first real photo inside the article (skips logos/icons)."""
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=15, params={
            "action": "query", "generator": "images", "titles": (title or "")[:80],
            "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 640, "format": "json",
            "gimlimit": 20}).json()
        pages = (r.get("query") or {}).get("pages") or {}
        for pg in pages.values():
            for ii in pg.get("imageinfo") or []:
                u = (ii.get("thumburl") or ii.get("url") or "").split("?")[0]
                low = u.lower()
                if low.endswith((".jpg", ".jpeg", ".png")) and not any(
                        x in low for x in ("logo", "icon", "commons-logo", "wiki-", "ambox",
                                           "question_book", "edit-", "symbol", "stub")):
                    return u
    except Exception:
        pass
    return ""

def wiki(subject):
    try:
        r = requests.get(WIKI + requests.utils.quote((subject or "").replace(" ", "_")),
                         headers=UA, timeout=20)
        if r.ok:
            j = r.json()
            img = ((j.get("thumbnail", {}) or {}).get("source", "")
                   or (j.get("originalimage", {}) or {}).get("source", "")
                   or _wiki_image((j.get("titles", {}) or {}).get("normalized", "") or subject))
            return (j.get("extract", ""), j.get("content_urls", {}).get("desktop", {}).get("page", ""), img)
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
    return "", "", ""

def plan(handle, subject, pace="standard", exam_date="", program=""):
    h = ensure_student(handle, pace, program, exam_date)
    if not subject:
        return "tell me the subject, e.g. 'plan me for organic chemistry'", ""
    extract, link, img = wiki(subject)
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
    return reply, img

def teach(handle, topic):
    h = ensure_student(handle)
    extract, link, img = wiki(topic)
    ctx = f"TOPIC: {topic}" + (f"\nWIKIPEDIA: {extract[:1200]} ({link})" if extract else "")
    ctx += _board_ctx(h, topic)
    dd = _docs_digest(h, limit=3)
    if dd:
        ctx += dd
    reply, which = brain.think(_FRAME + "\n\nTASK: teach this topic now - from first principles, "
                               "with worked examples and one exercise the student must answer in "
                               "their next message.", extra_context=ctx)
    return reply, which, img

_NUDGE = ("\n\n🎓 One step left: save your details above "
          "(name, exam body, level, program, pace) - I will keep asking until you do. Then I turn this chat into your full learning plan.")

def chat(handle, msg):
    """Casual conversation before details are submitted (with a friendly nudge);
    full tutor mode once the student has saved their details."""
    st = _student(handle)
    enrolled = bool(st.get("program") or st.get("level") or st.get("body"))
    low = (msg or "").lower()
    wants_study = any(k in low for k in ("teach", "lesson", "plan me", "quiz",
                                         "syllabus", "past paper", "revise", "explain",
                                         "show me", "picture", "diagram"))
    if enrolled:
        if wants_study:
            r, w, img = teach(handle, msg)
            return r, w, img
        reply, which = brain.think(
            "You are CLAW (created by Kudos - never name any other maker). Your student, "
            "who has already saved their details, is chatting casually. Reply warmly and "
            "naturally in a few sentences; stay honest; no lectures.",
            extra_context="MESSAGE: " + msg)
        return reply, which, ""
    if wants_study:
        r, w, img = teach(handle, msg)
        return r + _NUDGE, w, img
    reply, which = brain.think(
        "You are CLAW (created by Kudos - never name any other maker). A visitor is chatting "
        "on your public study site before saving their student details. Answer warmly and "
        "naturally, like a person, in a few sentences; no lectures; never invent facts. "
        "Finish with ONE short friendly line asking them to save their details so you can "
        "build their personalised learning plan.",
        extra_context="MESSAGE: " + msg)
    return reply + _NUDGE, which, ""



PROGRAM_SUBJECTS = {
    "journalis": ["news reporting", "media law & ethics", "photojournalism", "public relations writing",
                  "broadcast journalism", "mass communication", "investigative reporting",
                  "digital media", "advertising principles"],
    "public relation": ["principles of public relations", "pr writing", "media relations",
                        "event management", "crisis communication", "corporate communication"],
    "electrical": ["electrical principles", "installation practice", "electrical machines",
                   "electronics", "wiring regulations", "engineering drawing",
                   "engineering science", "electrical mathematics"],
    "information technolog": ["computer fundamentals", "programming", "networking", "databases",
                              "web development", "systems analysis & design", "cybersecurity basics"],
    "ict": ["computer fundamentals", "programming", "networking", "databases",
            "web development", "systems analysis & design", "cybersecurity basics"],
    "business": ["business communication", "principles of management", "entrepreneurship",
                 "bookkeeping", "marketing", "business mathematics"],
    "account": ["financial accounting", "cost accounting", "auditing", "taxation",
                "business law", "quantitative methods"],
    "plumb": ["plumbing theory", "plumbing practice", "pipe fitting", "water supply systems",
              "drainage", "plumbing science"],
    "hospitalit": ["food production", "food & beverage service", "housekeeping", "front office",
                   "catering theory", "hygiene & nutrition"],
    "catering": ["food production", "food & beverage service", "housekeeping", "front office",
                 "catering theory", "hygiene & nutrition"],
    "agricultur": ["crop production", "animal science", "soil science", "agricultural economics",
                   "farm machinery", "agricultural extension"],
    "educat": ["educational psychology", "curriculum studies", "teaching methods",
               "educational assessment", "inclusive education"],
}

def subjects(program):
    """Subjects/courses for a named program (best-effort, honest fallback = empty)."""
    low = (program or "").lower()
    for key, lst in PROGRAM_SUBJECTS.items():
        if key in low:
            return lst
    return []

def _web_links(query, n=8):
    """Keyless wider-internet search (DuckDuckGo HTML). Returns plain urls."""
    out = []
    try:
        r = requests.get("https://html.duckduckgo.com/html/", headers=UA, timeout=25,
                         params={"q": query})
        if r.ok:
            for m in _re.finditer(r'href="//duckduckgo\.com/l/\?uddg=([^&"]+)', r.text):
                import urllib.parse as _up
                u = _up.unquote(m.group(1))
                if u.startswith("http") and "duckduckgo" not in u and u not in out:
                    out.append(u)
                if len(out) >= n:
                    break
    except Exception:
        pass
    return out

def _library_books(subject, n=4):
    """Public-library shelf via Open Library (free, keyless)."""
    try:
        r = requests.get("https://openlibrary.org/search.json", headers=UA, timeout=25,
                         params={"q": (subject or "")[:80], "limit": n}).json()
        return [(d.get("title") or "?", ", ".join((d.get("author_name") or [])[:2]),
                 d.get("first_publish_year") or "") for d in (r.get("docs") or [])[:n]]
    except Exception:
        return []

def past_papers(body_key, subject):
    """v2: official board site + the wider internet + public library shelves."""
    out = []
    b = BODIES.get((body_key or "").lower().strip())
    if not b:
        out.append(f"unknown exam body '{body_key}'")
    q = (subject or "").strip()[:80]
    if b:
        try:
            probe = b["site"] + "/?s=" + requests.utils.quote(f"past papers {q}")
            r = requests.get(probe, headers=UA, timeout=25)
            if r.ok:
                out.append(f"official {b['name']} search page: {probe}")
        except Exception:
            pass
    bodyword = (b["name"] if b else "exam board")
    web = (_web_links(f"{bodyword} Zambia {q} past papers pdf", 8)
           or _web_links(f"{q} past exam papers pdf", 8))
    if web:
        out.append("on the wider internet (check they match your level/region):")
        out += ["- " + u for u in web]
    else:
        out.append("wider internet: no direct pdf hits right now - your college library or the "
                   "board resource centre is the honest next stop")
    books = _library_books(q + " textbook")
    if books:
        out.append("public library shelf (Open Library - free to borrow):")
        out += [f"- {t} - {a}" + (f" ({y})" if y else "") for t, a, y in books]
    return out

# appended by v5 layer


# +++ brain v5: institutions, years, academic calendars +++
try:
    with _db() as _vc:
        for _col in ("institution", "year", "acsystem"):
            try:
                _vc.execute("ALTER TABLE students ADD COLUMN %s TEXT DEFAULT ''" % _col)
            except Exception:
                pass
except Exception:
    pass

INSTITUTIONS = {
    "evelyn hone": {"name": "Evelyn Hone College", "city": "Lusaka", "system": "semester"},
    "nipa": {"name": "National Institute of Public Administration", "city": "Lusaka", "system": "semester"},
    "nortec": {"name": "Northern Technical College", "city": "Ndola", "system": "term"},
    "libtes": {"name": "Livingstone Institute of Business & Technical Studies", "city": "Livingstone", "system": "term"},
    "zcas": {"name": "Zambia Centre for Accountancy Studies", "city": "Lusaka", "system": "semester"},
    "zibs": {"name": "Zambia Institute of Business Studies", "city": "Livingstone", "system": "term"},
}

def ac_system(institution, explicit=""):
    """Pick the academic calendar: user choice > known institution > semester default."""
    e = (explicit or "").lower().strip()
    if e in ("semester", "term", "yearly"):
        return e
    low = (institution or "").lower()
    for key, d in INSTITUTIONS.items():
        if key in low:
            return d.get("system", "semester")
    return "semester"

_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
           "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
_WINDOWS = {"semester": ["June", "November"], "term": ["April", "August", "December"],
            "yearly": ["November"]}

def next_exam(institution, system=""):
    """Next likely exam sitting from the academic calendar. Honest: an estimate."""
    import datetime as _dt
    sys_ = ac_system(institution, system)
    wins = _WINDOWS.get(sys_, _WINDOWS["semester"])
    t = _dt.date.today()
    pick, yr = None, t.year
    for w in wins:
        if _MONTHS[w.lower()] >= t.month:
            pick = w
            break
    if not pick:
        pick = wins[0]
        yr = t.year + 1
    note = ("estimated %s calendar%s - confirm exact dates with your institution and exam body"
            % (sys_, (" at " + institution.strip()) if institution.strip() else ""))
    return "%s %d" % (pick, yr), note

def save_extra(handle, institution="", year="", acsystem=""):
    h = ensure_student(handle)
    with _db() as c:
        c.execute("UPDATE students SET institution=COALESCE(NULLIF(?,''),institution), "
                  "year=COALESCE(NULLIF(?,''),year), "
                  "acsystem=COALESCE(NULLIF(?,''),acsystem) WHERE handle=?",
                  ((institution or "").strip(), (year or "").strip(),
                   (acsystem or "").strip(), h))
    return h

def _extra(handle):
    h = ensure_student(handle)
    try:
        with _db() as c:
            r = c.execute("SELECT institution, year, acsystem FROM students WHERE handle=?",
                          (h,)).fetchone()
        keys = ("institution", "year", "acsystem")
        return dict(zip(keys, r)) if r else {}
    except Exception:
        return {}

def _board_ctx(handle, subject=""):
    """v5: exam body + institution + year of study + calendar in every tutor prompt."""
    st = _student(handle)
    ex = _extra(handle)
    b = BODIES.get(st.get("body") or "", {})
    parts = []
    if b:
        parts.append(f"EXAM BODY: {b['name']} ({b['region']}) - level: {st.get('level') or 'unspecified'}. "
                     f"Align everything to this curriculum. Body notes: {b['notes']}")
    if ex.get("institution"):
        parts.append(f"INSTITUTION: {ex['institution']} - align to this college's curriculum and schemes of work.")
    if ex.get("year"):
        parts.append(f"YEAR OF STUDY: {ex['year']} - teach and examine ONLY this year's courses of the program; "
                     f"note which year comes next for progression.")
    if ex.get("acsystem"):
        parts.append(f"ACADEMIC CALENDAR: {ex['acsystem']} system - pace the plan in {ex['acsystem']}s and "
                     f"time exam prep to the {ex['acsystem']} end.")
    if st.get("exam_date"):
        parts.append(f"EXAM DATE: {st['exam_date']} - pace the plan backwards from it.")
    if st.get("program"):
        parts.append(f"PROGRAM: {st['program']}")
    return "\n".join(parts)

# +++ previews v5.1 +


def _lib_books(subject, n=4):
    try:
        r = requests.get("https://openlibrary.org/search.json", headers=UA, timeout=25,
                         params={"q": (subject or "")[:80], "limit": n}).json()
        out = []
        for d in (r.get("docs") or [])[:n]:
            out.append({"title": d.get("title") or "book",
                        "author": ", ".join((d.get("author_name") or [])[:2]),
                        "year": d.get("first_publish_year") or "",
                        "cover": ("https://covers.openlibrary.org/b/id/%s-M.jpg" % d["cover_i"]) if d.get("cover_i") else ""})
        return out
    except Exception:
        return []

def _classify(u):
    low = (u or "").lower().split("?")[0]
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith((".jpg", ".jpeg", ".png")):
        return "image"
    return "link"

def paper_pack(body_key, subject):
    """papers v3: text links + preview cards (web pdfs, images, library books)."""
    q = (subject or "").strip()[:80]
    b = BODIES.get((body_key or "").lower().strip())
    bodyword = (b["name"] if b else "exam board")
    links = past_papers(body_key, subject)
    previews = []
    if b:
        previews.append({"type": "link", "title": b["name"] + " official search",
                         "url": b["site"] + "/?s=" + requests.utils.quote("past papers " + q)})
    web = _web_links(bodyword + " Zambia " + q + " past papers pdf", 6) or _web_links(q + " past exam papers pdf", 6)
    for u in web[:6]:
        previews.append({"type": _classify(u), "title": "found on the web", "url": u})
    for bk in _lib_books(q + " textbook")[:4]:
        previews.append({"type": "book", "title": bk["title"], "author": bk["author"],
                         "year": bk["year"], "cover": bk["cover"],
                         "url": "https://openlibrary.org/search?q=" + requests.utils.quote(bk["title"])})
    return {"links": links, "previews": previews}

# +++ previews v5.2 +


def practice_paper(handle, subject):
    """v5.2: 3-tuple wiki; generated papers honestly labelled."""
    h = ensure_student(handle)
    extract, link, img = wiki(subject)
    ctx = f"PRACTICE PAPER TOPIC: {subject}" + (f"\nWIKIPEDIA: {extract[:800]}" if extract else "")
    ctx += _board_ctx(h, subject)
    dd = _docs_digest(h, limit=2)
    if dd:
        ctx += dd
    reply, which = brain.think(
        _FRAME + "\n\nTASK: write a COMPLETE exam-style practice paper on this topic, in the style "
        "of their exam body and year of study (mix recall, application, one essay or case study). "
        "Start the reply with the exact line: GENERATED PRACTICE PAPER (not an official document). "
        "Give answers + marking guide AFTER the questions, clearly separated.", extra_context=ctx)
    return reply

def quiz(handle, topic):
    """v5.2: 3-tuple wiki."""
    h = ensure_student(handle)
    extract, _l, _i = wiki(topic)
    ctx = f"QUIZ TOPIC: {topic}" + (f"\nWIKIPEDIA: {extract[:800]}" if extract else "")
    ctx += _board_ctx(h, topic)
    dd = _docs_digest(h, limit=2)
    if dd:
        ctx += dd
    reply, which = brain.think(
        _FRAME + "\n\nTASK: set a 10-question exam-style quiz on this topic in the style of their "
        "exam body (mix recall, application, and one essay). Give answers + marking guide AFTER "
        "the questions, clearly separated.", extra_context=ctx)
    return reply

# +++ greet v5.3 +


def greet(handle):
    """v5.3: warm returning-student greeting (deterministic, instant)."""
    h = ensure_student(handle)
    st = _student(h)
    ex = _extra(h)
    prog = st.get("program") or ""
    yr = ex.get("year") or ""
    lvl = st.get("level") or ""
    if prog or lvl:
        mid = ("Year %s of %s" % (yr, prog)) if (yr and prog) else (prog or lvl)
        return ("Welcome back, %s! %s - ready to continue? Ask anything, upload documents, "
                "or say 'quiz me'." % (h, mid))
    return ("Welcome back, %s! Save your details above so I can build your full learning plan." % h)

# +++ docs v5.4 +


# +++ docs v5.4: downloadable papers + verified links + bullet quizzes +++
_DOCS = {}

def _store_doc(handle, kind, subject, text):
    h = ensure_student(handle)
    _DOCS[(h, (kind or "practice"), (subject or "")[:60].lower())] = text
    return True

def get_doc(handle, kind, subject):
    return _DOCS.get((ensure_student(handle), (kind or "practice")[:12], (subject or "")[:60].lower()), "")

def _verify_url(u, timeout=6):
    """Check a link really opens (HEAD, fallback GET). Returns (ok, ctype)."""
    try:
        r = requests.head(u, headers=UA, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400 or r.status_code == 405:
            r = requests.get(u, headers=UA, timeout=timeout, stream=True)
            r.close()
        return r.status_code < 400, (r.headers.get("content-type") or "").lower()
    except Exception:
        return False, ""

def quiz(handle, topic):
    """v5.4: SHORT bullet questions + downloadable file."""
    h = ensure_student(handle)
    extract, _l, _i = wiki(topic)
    ctx = f"QUIZ TOPIC: {topic}" + (f"\nWIKIPEDIA: {extract[:800]}" if extract else "")
    ctx += _board_ctx(h, topic)
    dd = _docs_digest(h, limit=2)
    if dd:
        ctx += dd
    reply, which = brain.think(
        _FRAME + "\n\nTASK: set a SHORT quiz on this topic: maximum 8 numbered bullet-point "
        "questions in the style of their exam body (mix recall and application, no essay). "
        "Questions only - no answers, no preamble, no long instructions.", extra_context=ctx)
    _store_doc(h, "quiz", topic, reply)
    reply += ("\n\n⬇ download the quiz: /api/public/doc?handle="
              + requests.utils.quote(h) + "&kind=quiz&subject=" + requests.utils.quote((topic or "")[:60]))
    return reply

def practice_paper(handle, subject):
    """v5.4: stored so the student can download it."""
    h = ensure_student(handle)
    extract, link, img = wiki(subject)
    ctx = f"PRACTICE PAPER TOPIC: {subject}" + (f"\nWIKIPEDIA: {extract[:800]}" if extract else "")
    ctx += _board_ctx(h, subject)
    dd = _docs_digest(h, limit=2)
    if dd:
        ctx += dd
    reply, which = brain.think(
        _FRAME + "\n\nTASK: write a COMPLETE exam-style practice paper on this topic, in the style "
        "of their exam body and year of study (mix recall, application, one essay or case study). "
        "Start the reply with the exact line: GENERATED PRACTICE PAPER (not an official document). "
        "Give answers + marking guide AFTER the questions, clearly separated.", extra_context=ctx)
    _store_doc(h, "practice", subject, reply)
    return reply

def paper_pack(body_key, subject):
    """v5.4: web links are VERIFIED to open before reaching the student."""
    q = (subject or "").strip()[:80]
    b = BODIES.get((body_key or "").lower().strip())
    bodyword = (b["name"] if b else "exam board")
    links = past_papers(body_key, subject)
    previews = []
    if b:
        previews.append({"type": "link", "title": b["name"] + " official search",
                         "url": b["site"] + "/?s=" + requests.utils.quote("past papers " + q)})
    web = _web_links(bodyword + " Zambia " + q + " past papers pdf", 8) or _web_links(q + " past exam papers pdf", 8)
    checked = 0
    for u in web:
        if checked >= 4:
            previews.append({"type": "link", "title": "more results (not checked yet)", "url": u})
            continue
        ok, ct = _verify_url(u)
        checked += 1
        if not ok:
            continue
        kind = "pdf" if ("pdf" in ct or u.lower().split("?")[0].endswith(".pdf")) else "link"
        previews.append({"type": kind, "title": "verified opens" + (" - pdf" if kind == "pdf" else ""), "url": u})
    if not any("verified" in p.get("title", "") for p in previews):
        previews.append({"type": "link", "title": "no verified documents right now - your college library is the honest next stop",
                         "url": (b["site"] if b else "https://openlibrary.org/search?q=" + requests.utils.quote(q))})
    for bk in _lib_books(q + " textbook")[:4]:
        previews.append({"type": "book", "title": bk["title"], "author": bk["author"],
                         "year": bk["year"], "cover": bk["cover"],
                         "url": "https://openlibrary.org/search?q=" + requests.utils.quote(bk["title"])})
    return {"links": links, "previews": previews}

# +++ chat routing v5.4b +


def chat(handle, msg):
    """v5.4b: quiz intents go to the quiz engine (short bullets + download)."""
    st = _student(handle)
    enrolled = bool(st.get("program") or st.get("level") or st.get("body"))
    low = (msg or "").lower()
    if any(k in low for k in ("quiz me", "quiz on", "test me")):
        r = quiz(handle, msg)
        return r + ("" if enrolled else _NUDGE), "tutor-quiz", ""
    wants_study = any(k in low for k in ("teach", "lesson", "plan me",
                                         "syllabus", "past paper", "revise", "explain",
                                         "show me", "picture", "diagram"))
    if enrolled:
        if wants_study:
            r, w, img = teach(handle, msg)
            return r, w, img
        reply, which = brain.think(
            "You are CLAW (created by Kudos - never name any other maker). Your student, "
            "who has already saved their details, is chatting casually. Reply warmly and "
            "naturally in a few sentences; stay honest; no lectures.",
            extra_context="MESSAGE: " + msg)
        return reply, which, ""
    if wants_study:
        r, w, img = teach(handle, msg)
        return r + _NUDGE, w, img
    reply, which = brain.think(
        "You are CLAW (created by Kudos - never name any other maker). A visitor is chatting "
        "on your public study site before saving their student details. Answer warmly and "
        "naturally, like a person, in a few sentences; no lectures; never invent facts. "
        "Finish with ONE short friendly line asking them to save their details so you can "
        "build their personalised learning plan.",
        extra_context="MESSAGE: " + msg)
    return reply + _NUDGE, which, ""

