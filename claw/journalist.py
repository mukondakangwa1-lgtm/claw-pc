"""CLAW Newsdesk - journalism & OSINT desk.
Data: OSIRIS intelligence platform (https://osirisai.live, MIT) which normalises
USGS, NASA, GDELT, CISA and abuse.ch public feeds into one keyless JSON API.
Policy: PASSIVE endpoints only - the active-scan routes (/api/osint/sweep,
/api/scanner) are refused here; all scanning stays behind tools.py authorization.
Every briefing attributes its sources and links the live map."""
import json as _json
import requests
from . import config

UA = {"User-Agent": "claw-pc-newsdesk/1.0"}
TIMEOUT = 25
DEFAULT_LAYERS = "live_news,earthquakes,cyber_attacks,gdelt_events"

def _base():
    return str(config.load().get("osiris_base", "https://osirisai.live")).rstrip("/")

def _get(path, **params):
    r = requests.get(_base() + path, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def map_url(layers=None):
    """Deep link that opens the OSIRIS map pre-loaded with the given layers."""
    return f"{_base()}/?layers={layers or DEFAULT_LAYERS}"

def quakes(min_mag=4.5, focus="", n=6):
    try:
        data = _get("/api/earthquakes").get("earthquakes", [])
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
    return out or [f"(no quakes >= M{min_mag}{' near ' + focus if focus else ''} right now)"]

def news(query="", n=5):
    import html as _h
    try:
        items = _get("/api/news").get("news", [])
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
        evs = _get("/api/gdelt").get("events", [])
    except Exception:
        return ["(GDELT feed unavailable)"]
    import html as _h
    out = []
    for e in evs:
        name = _h.unescape((e.get("name") or "")).strip()
        if query and query.lower() not in name.lower(): continue
        out.append(f"- {name}  [{e.get('type', 'event')}]")
        if len(out) >= n: break
    return out or [f"(no GDELT events matching '{query}')"]

def conflicts(n=4):
    try:
        d = _get("/api/conflicts")
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
        d = _get("/api/cyber-threats")
        st = d.get("stats", {})
        lines.append(f"threat level: {st.get('threat_level', '?')} | active CVEs: {st.get('active_cves', '?')}")
        for t in (d.get("threats") or [])[:n]:
            lines.append(f"- {t.get('name', '?')} [{t.get('severity', '?')}] ({t.get('vendor', '')}) {t.get('date', '')}")
    except Exception:
        lines.append("(CVE feed unavailable)")
    try:
        d = _get("/api/cyber-attacks")
        attacks = d.get("attacks", [])
        lines.append(f"attack events in current window: {d.get('total', len(attacks))}")
        by_mal, by_ctry = {}, {}
        for a in attacks:
            by_mal[a.get("malware") or "?"] = by_mal.get(a.get("malware") or "?", 0) + 1
            by_ctry[a.get("target_country") or "?"] = by_ctry.get(a.get("target_country") or "?", 0) + 1
        if by_mal:
            top = max(by_mal.items(), key=lambda x: x[1]); lines.append(f"top malware: {top[0]} ({top[1]} events)")
        if by_ctry:
            top = max(by_ctry.items(), key=lambda x: x[1]); lines.append(f"most-targeted country: {top[0]} ({top[1]} events)")
    except Exception:
        lines.append("(attack-map feed unavailable)")
    return lines

def brief(focus=""):
    """The flagship: one pass over the feeds, one attributed briefing."""
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"CLAW INTELLIGENCE BRIEFING - {stamp}" + (f"  (focus: {focus})" if focus else ""), "=" * 48]
    try:
        st = _get("/api/stats").get("stats", {})
        L.append(f"[pulse] {st.get('flights', '?')} flights | {st.get('sats', '?')} satellites | "
                 f"{st.get('cctv', '?')} cameras | {st.get('incidents', '?')} incidents tracked")
    except Exception:
        L.append("[pulse] platform unreachable")
    L += ["", "TOP NEWS"] + news(focus)
    L += ["", "WORLD EVENTS (GDELT)"] + world_events(focus, 4)
    L += ["", "CONFLICTS"] + conflicts()
    L += ["", "QUAKES M4.5+"] + quakes(focus=focus)
    L += ["", "CYBER"] + cyber()
    L += ["", "live map: " + map_url(),
          "sources: OSIRIS aggregator (USGS | NASA | GDELT | CISA | abuse.ch) - verify before publishing."]
    return "\n".join(L)

def osint(subject):
    """PASSIVE lookups only (third-party datasets - the subject itself is never touched)."""
    import re
    s = (subject or "").strip()
    if not s:
        return "usage: claw osint <domain-or-IP>"
    out = []
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s):
        try:
            d = _get("/api/osint/ip", ip=s)
            out.append(f"IP {s}: " + _json.dumps(d, default=str)[:400])
        except Exception as e:
            out.append(f"lookup failed: {e.__class__.__name__}")
    else:
        try:
            d = _get("/api/osint/whois", domain=s)
            out.append(f"WHOIS {s}: " + _json.dumps(d, default=str)[:400])
        except Exception as e:
            out.append(f"whois failed: {e.__class__.__name__}")
        try:
            subs = _get("/api/osint/certs", domain=s).get("subdomains") or []
            if subs:
                out.append(f"cert-transparency subdomains ({len(subs)}): " + ", ".join(list(subs)[:10]))
        except Exception:
            pass
    out.append("(passive OSINT only - active scanning is disabled by Claw policy)")
    return "\n".join(out)
