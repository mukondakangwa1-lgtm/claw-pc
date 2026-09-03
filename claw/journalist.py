"""CLAW Newsdesk v2 - journalism, OSINT & investigation desk.
Sources (all keyless, all passive):
  OSIRIS    https://osirisai.live   (MIT; normalises USGS/NASA/GDELT/CISA/abuse.ch)
  GDELT     https://api.gdeltproject.org  (geocoded world news, direct)
  CISA KEV  https://www.cisa.gov    (known exploited vulnerabilities catalog)
  NOAA SWPC https://services.swpc.noaa.gov  (space weather / Kp index)
  GDACS     https://www.gdacs.org   (global disaster alerts)
Policy: passive endpoints only - active-scan routes are refused. Every output
attributes its sources and links the live map. Investigation Mode separates
fact, tradition, and unknown; it never claims to prove or disprove."""
import html as _h
import json as _json
import re as _re
from urllib.parse import urlparse as _urlparse
import requests
from . import config

UA = {"User-Agent": "claw-pc-newsdesk/2.0"}
TIMEOUT = 25
DEFAULT_LAYERS = "live_news,earthquakes,cyber_attacks,gdelt_events"

def _base():
    return str(config.load().get("osiris_base", "https://osirisai.live")).rstrip("/")

def _get(url, **params):
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _oget(path, **params):
    return _get(_base() + path, **params)

def map_url(layers=None):
    return f"{_base()}/?layers={layers or DEFAULT_LAYERS}"

# ---------------- OSIRIS feeds ----------------

def quakes(min_mag=4.5, focus="", n=6):
    try:
        data = _oget("/api/earthquakes").get("earthquakes", [])
    except Exception:
        return ["(quake feed unavailable)"]
    out = []
    for q in data:
        if float(q.get("magnitude") or 0) < min_mag: continue
        place = q.get("place", "?")
        if focus and focus.lower() not in place.lower(): continue
        line = f"M{float(q['magnitude']):.1f} - {place}"
        if q.get("tsunami"): line += "  [TSUNAMI FLAG]"
        if q.get("url"): line += f"  {q['url']}"
        out.append(line)
        if len(out) >= n: break
    return out or [f"(no quakes >= M{min_mag} right now)"]

def news(query="", n=5):
    try:
        items = _oget("/api/news").get("news", [])
    except Exception:
        return ["(news feed unavailable)"]
    out = []
    for it in items:
        title = _h.unescape((it.get("title") or "")).strip()
        if query and query.lower() not in title.lower(): continue
        line = f"- {title}  [{it.get('source', '?')}]"
        if it.get("link"): line += f"  {it['link']}"
        out.append(line)
        if len(out) >= n: break
    return out or [f"(no headlines matching '{query}')"]

def world_events(query="", n=5):
    try:
        evs = _oget("/api/gdelt").get("events", [])
    except Exception:
        return gdelt_news(query, n)  # fall through to direct GDELT
    out = []
    for e in evs:
        name = _h.unescape((e.get("name") or "")).strip()
        if query and query.lower() not in name.lower(): continue
        out.append(f"- {name}  [{e.get('type', 'event')}]")
        if len(out) >= n: break
    return out or gdelt_news(query, n)

def conflicts(n=4):
    try:
        d = _oget("/api/conflicts")
    except Exception:
        return ["(conflict feed unavailable)"]
    out = [f"active war zones: {d.get('activeWarzones', '?')}"]
    for z in (d.get("zones") or [])[:n]:
        out.append(f"- {z.get('label', '?')} [{z.get('severity', '?')}] {z.get('region', '')}"
                   f" ({z.get('eventCount', 0)} recent events)")
    return out

def cyber(n=4):
    lines = []
    try:
        d = _oget("/api/cyber-threats")
        st = d.get("stats", {})
        lines.append(f"threat level: {st.get('threat_level', '?')} | active CVEs: {st.get('active_cves', '?')}")
        for t in (d.get("threats") or [])[:n]:
            lines.append(f"- {t.get('name', '?')} [{t.get('severity', '?')}] ({t.get('vendor', '')}) {t.get('date', '')}")
    except Exception:
        lines.append("(CVE feed unavailable)")
    return lines

# ---------------- direct sources (GDELT / CISA / NOAA / GDACS) ----------------

def gdelt_news(query, n=6):
    q = _re.sub(r"[^\w\s]", " ", query or "").strip()
    if not q:
        return ["(no query)"]
    words = q.split()
    attempts = ['"' + q + '"']
    if len(words) > 1:
        attempts.append(" ".join(words[:4]))
    out, had_exc = [], False
    for att in attempts:
        try:
            arts = _get("https://api.gdeltproject.org/api/v2/doc/doc",
                        query=att, mode="artlist", maxrecords=n, format="json").get("articles", [])
        except Exception:
            had_exc = True; continue
        for a in arts:
            dom = _urlparse(a.get("url") or "").netloc or "?"
            line = f"- {a.get('title', '?')}  [{dom}, {a.get('seendate', '')}]  {a.get('url', '')}"
            if line not in out: out.append(line)
            if len(out) >= n: break
        if out: break
    if out: return out
    return ["(GDELT direct feed unavailable)"] if had_exc else [f"(no GDELT articles for '{q}')"]

def kev(n=3):
    try:
        d = _get("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")
    except Exception:
        return ["(CISA KEV feed unavailable)"]
    vulns = d.get("vulnerabilities", [])
    out = [f"KEV catalog: {d.get('count', len(vulns))} known-exploited CVEs (version {d.get('catalogVersion', '?')})"]
    for v in vulns[:n]:
        out.append(f"- {v.get('cveID', '?')} {v.get('vendorProject', '')} {v.get('product', '')} "
                   f"(added {v.get('dateAdded', '?')}) due {v.get('dueDate', '?')}")
    return out

def space_weather():
    try:
        rows = _get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json")
        latest = rows[-1] if isinstance(rows, list) and rows else None
        if not latest: return ["(no Kp data)"]
        kp = float(latest.get("Kp") or 0)
        state = ("calm" if kp < 3 else "unsettled" if kp < 4 else "active" if kp < 5 else "STORM")
        return [f"solar Kp index {kp:.2f} ({state}) at {latest.get('time_tag', '?')}"]
    except Exception:
        return ["(NOAA space weather unavailable)"]

_EVENTS = {"EQ": "earthquake", "TC": "cyclone", "FL": "flood", "VO": "volcano",
           "WF": "wildfire", "DR": "drought"}

def disasters(n=4):
    try:
        feats = _get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH").get("features", [])
    except Exception:
        return ["(GDACS feed unavailable)"]
    out = []
    for f in feats:
        p = f.get("properties", {}) or {}
        name = p.get("eventname") or _EVENTS.get(p.get("eventtype", ""), p.get("eventtype", "?"))
        line = f"- {name} [{_EVENTS.get(p.get('eventtype', ''), '?')}] {p.get('iso3country', '')} {p.get('fromdate', '')}"
        if line not in out: out.append(line)
        if len(out) >= n: break
    return out or ["(no active GDACS alerts)"]

# ---------------- briefings ----------------

def brief(focus=""):
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"CLAW INTELLIGENCE BRIEFING - {stamp}" + (f"  (focus: {focus})" if focus else ""), "=" * 48]
    try:
        st = _oget("/api/stats").get("stats", {})
        L.append(f"[pulse] {st.get('flights', '?')} flights | {st.get('sats', '?')} satellites | "
                 f"{st.get('cctv', '?')} cameras | {st.get('incidents', '?')} incidents tracked")
    except Exception:
        L.append("[pulse] platform unreachable")
    L += ["", "TOP NEWS"] + news(focus)
    L += ["", "WORLD EVENTS (GDELT)"] + world_events(focus, 4)
    L += ["", "CONFLICTS"] + conflicts()
    L += ["", "DISASTERS (GDACS)"] + disasters(3)
    L += ["", "QUAKES M4.5+"] + quakes(focus=focus, n=4)
    L += ["", "SPACE WEATHER"] + space_weather()
    L += ["", "CYBER"] + cyber(3) + kev(3)
    L += ["", "live map: " + map_url(),
          "sources: OSIRIS (USGS | NASA | GDELT | CISA | abuse.ch), GDELT direct, CISA KEV, NOAA SWPC, GDACS",
          "verify before publishing."]
    return "\n".join(L)

def osint(subject):
    """PASSIVE lookups only (third-party datasets - the subject itself is never touched)."""
    s = (subject or "").strip()
    if not s:
        return "usage: claw osint <domain-or-IP>"
    out = []
    if _re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s):
        try:
            out.append(f"IP {s}: " + _json.dumps(_oget("/api/osint/ip", ip=s), default=str)[:400])
        except Exception as e:
            out.append(f"lookup failed: {e.__class__.__name__}")
    else:
        try:
            out.append(f"WHOIS {s}: " + _json.dumps(_oget("/api/osint/whois", domain=s), default=str)[:400])
        except Exception as e:
            out.append(f"whois failed: {e.__class__.__name__}")
        try:
            subs = _oget("/api/osint/certs", domain=s).get("subdomains") or []
            if subs:
                out.append(f"cert-transparency subdomains ({len(subs)}): " + ", ".join(list(subs)[:10]))
        except Exception:
            pass
    out.append("(passive OSINT only - active scanning is disabled by Claw policy)")
    return "\n".join(out)

# ---------------- investigation mode ----------------

_INVESTIGATOR = (
    "INVESTIGATION MODE. You are CLAW, created by Kudos, tracing a question through a timeline "
    "of texts, history, and modern media. House rules: you never claim to prove or disprove "
    "the supernatural or the conspiratorial - you FOLLOW EVIDENCE and separate: (1) TIMELINE - "
    "dated steps with their source/era, (2) WHAT THE TEXTS SAY - what each tradition actually "
    "claims, (3) WHAT IS VERIFIABLE TODAY - places, documents, physics, the live evidence pack, "
    "(4) MODERN CLAIMS & MEDIA - how the story evolved into today's retellings, (5) CONCLUSION - "
    "honest bottom line: what is fact, what is tradition/belief, what remains unknown. Cite "
    "dates and sources for timeline steps. Say 'unknown' where unknown. Be vivid but precise.")

def investigate(question):
    """Timeline-based investigation: live evidence pack + structured multi-source reasoning."""
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pack = [f"LIVE EVIDENCE PACK - fetched {stamp}"]
    stop = {"where", "are", "the", "now", "is", "was", "what", "who", "how", "why", "when",
            "do", "does", "did", "a", "an", "of", "in", "on", "to", "and", "or", "for", "with"}
    kws = " ".join(w for w in _re.sub(r"[^\w\s]", " ", question).split() if w.lower() not in stop)[:60]
    g = gdelt_news(kws or question, 5)
    if "unavailable" not in g[0] and "no GDELT" not in g[0]:
        pack.append("GDELT news mentioning the subject:") ; pack += ["  " + x for x in g]
    pack += ["CISA KEV:"] + ["  " + x for x in kev(2)]
    pack += ["Space weather:"] + ["  " + x for x in space_weather()]
    pack += ["GDACS disasters:"] + ["  " + x for x in disasters(2)]
    pack += ["OSIRIS headlines:"] + ["  " + x for x in news("", 3)]
    ctx = "\n".join(pack) + ("\nWatch the subject's real-world geography on the live map: " + map_url())
    from . import brain
    reply, which = brain.think(_INVESTIGATOR + "\n\nQUESTION: " + question, extra_context=ctx)
    if which == "none":
        reply = ("(no reasoning brain online - install a Groq key or Ollama for full analysis; "
                 "here is the raw evidence pack)\n\n" + ctx)
    return reply
