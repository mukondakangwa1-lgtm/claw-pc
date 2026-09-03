"""CLAW BEYOND - off-world network watch.
"We don't know the laws of these lands" - so Claw only logs what is observable.
Sources (all keyless, all passive):
  NASA DSN Now     https://eyes.nasa.gov/dsn/data/dsn.xml
                   live deep-space comms: which craft is talking to which dish
  OSIRIS /api/satellites  live positions of ~19,000 tracked orbital objects
  Helioviewer      https://api.helioviewer.org (live solar imagery)
  NOAA SWPC        planetary K-index (geomagnetic conditions)
Every observation is stored in memory/beyond.db for later recall: claw skylog.
House rule: this desk records signal and geometry. What it MEANS stays unknown
until evidence says otherwise - especially out there."""
import math
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from . import config

UA = {"User-Agent": "claw-pc-beyond/1.0"}
DSN_URL = "https://eyes.nasa.gov/dsn/data/dsn.xml"
KEV_AU_KM = 149_597_870.7
C_KM_S = 299_792.458

_STATIONS = {"10": "Goldstone", "20": "Goldstone", "30": "Madrid", "40": "Canberra"}
_CRAFT = {"VGR1": "VOYAGER 1", "VGR2": "VOYAGER 2", "M01O": "MARS ODYSSEY",
          "LRO": "LUNAR RECON ORBITER", "KPLO": "DANURI (KPLO)", "SOHO": "SOHO",
          "ESCB": "ESCAPADE-B", "MEX": "MARS EXPRESS", "JNO": "JUNO",
          "HAY": "HAYABUSA2", "MGA": "MAVEN", "GLL": "GALILEO LEGACY"}
_WHERE = {"voyager1": "VGR1", "voyager2": "VGR2", "marsodyssey": "M01O",
          "odyssey": "M01O", "lro": "LRO", "danuri": "KPLO", "kplo": "KPLO",
          "soho": "SOHO", "escapade": "ESCB", "marsexpress": "MEX",
          "juno": "JNO", "maven": "MGA", "hayabusa": "HAY"}

def _root() -> Path:
    return Path(config.__file__).resolve().parent.parent

def _db() -> sqlite3.Connection:
    d = _root() / "memory" / "beyond"
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(d / "skylog.db")
    conn.execute("CREATE TABLE IF NOT EXISTS observations("
                 "id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, summary TEXT, data TEXT)")
    return conn

def record(kind, summary, data=""):
    with _db() as c:
        c.execute("INSERT INTO observations(ts, kind, summary, data) VALUES (?,?,?,?)",
                  (datetime.now(timezone.utc).isoformat(timespec="seconds"), kind, summary, data))

def skylog(kind="", n=15):
    with _db() as c:
        if kind:
            rows = c.execute("SELECT ts, kind, summary FROM observations WHERE kind=? "
                             "ORDER BY id DESC LIMIT ?", (kind, n)).fetchall()
        else:
            rows = c.execute("SELECT ts, kind, summary FROM observations "
                             "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    if not rows:
        return ["(skylog empty - run claw dsn / space / overhead / sun / horizons first)"]
    return [f"{ts}  [{kind}]  {summary}" for ts, kind, summary in rows]

def _osiris(path, **params):
    base = str(config.load().get("osiris_base", "https://osirisai.live")).rstrip("/")
    r = requests.get(base + path, params=params, headers=UA, timeout=40)
    r.raise_for_status()
    return r.json()

def _station(dish_name):
    return _STATIONS.get((dish_name or "")[:2], dish_name)

def _fmt_range(km):
    try:
        km = float(km)
    except (TypeError, ValueError):
        return ""
    if km <= 0:
        return ""
    if km > 1e7:
        lt = km / C_KM_S / 3600
        return f"{km/1e9:,.1f} B km (~{lt:.1f} light-hours one-way)"
    return f"{km:,.0f} km"

def dsn():
    """Who is Earth talking to right now? (NASA Deep Space Network, live)"""
    try:
        r = requests.get(DSN_URL, headers=UA, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        return f"(DSN feed unavailable: {e.__class__.__name__})"
    lines, names = [], []
    for dish in root.iter("dish"):
        tgt = dish.find("target")
        if tgt is None:
            continue
        cid = tgt.get("name") or ""
        if cid in ("", "DSN", "DSS"):
            continue
        craft = _CRAFT.get(cid, cid)
        names.append(craft)
        rng = _fmt_range(tgt.get("downlegRange"))
        lines.append(f"- {craft} <-> {_station(dish.get('name',''))} [{dish.get('activity','')}]"
                     + (f" - range {rng}" if rng else ""))
    if not lines:
        out = "DSN: no downlink contacts at this instant (deep space is quiet)"
    else:
        out = ("DEEP SPACE NETWORK - live contacts ({}):".format(len(lines))
               + "\n" + "\n".join(lines)
               + "\ndishes: DSS-2x Goldstone | DSS-3x Madrid | DSS-4x Canberra | eyes.nasa.gov/dsn/index.html")
    record("dsn", f"{len(names)} contacts: {', '.join(sorted(set(names))[:5]) or 'none'}", out)
    return out

def space():
    """Geomagnetic conditions (NOAA planetary K-index)."""
    try:
        rows = requests.get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
                            headers=UA, timeout=20).json()
        latest = rows[-1]
        kp = float(latest.get("Kp") or 0)
        state = ("calm" if kp < 3 else "unsettled" if kp < 4 else "active" if kp < 5 else "STORM")
        out = f"space weather: Kp {kp:.2f} ({state}) at {latest.get('time_tag', '?')} | services.swpc.noaa.gov"
    except Exception as e:
        out = f"(space weather unavailable: {e.__class__.__name__})"
    record("space", out.split(" | ")[0], out)
    return out

def whereis(name="voyager2"):
    """Where is a deep-space craft right now? (NASA DSN live tracking ranges)"""
    key = (name or "voyager2").lower().replace(" ", "").replace("-", "").replace("_", "")
    cid = _WHERE.get(key)
    if not cid:
        return f"unknown craft '{name}' - I track: {', '.join(sorted(_WHERE.values()))}"
    label = _CRAFT.get(cid, cid)
    try:
        r = requests.get(DSN_URL, headers=UA, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        return f"(DSN feed unavailable: {e.__class__.__name__})"
    hits = []
    for dish in root.iter("dish"):
        tgt = dish.find("target")
        if tgt is not None and tgt.get("name") == cid:
            hits.append((_station(dish.get("name", "")), tgt.get("downlegRange", "-1")))
    if not hits:
        out = (f"{label}: not on any DSN dish at this instant (deep-space craft are handed "
               f"between Goldstone/Madrid/Canberra as Earth rotates - retry later or see "
               f"eyes.nasa.gov). Last known facts only come from live tracking.")
    else:
        hits.sort(key=lambda h: -float(h[1]) if h[1] and float(h[1] or 0) > 0 else 0)
        dish, rng = hits[0]
        rng_s = _fmt_range(rng)
        extra = f" - range {rng_s}" if rng_s else ""
        n = f" ({len(hits)} dishes)" if len(hits) > 1 else ""
        out = f"{label}: tracked by {dish}{n}{extra} [NASA DSN, live]"
    record("whereis", out, out)
    return out

def sun():
    """Live image of the Sun (SDO/AIA 171 via Helioviewer)."""
    d = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond//1000:03d}Z"
    try:
        r = requests.get("https://api.helioviewer.org/", headers=UA, timeout=60, params={
            "action": "takeScreenshot", "date": d, "imageScale": 2.428,
            "layers": "[SDO,AIA,AIA,171,1,100]", "x0": 0, "y0": 0,
            "width": 800, "height": 800, "display": "true"})
        r.raise_for_status()
        out_dir = _root() / "memory" / "beyond"
        out_dir.mkdir(parents=True, exist_ok=True)
        if r.headers.get("content-type", "").startswith("image"):
            path = out_dir / f"sun-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.png"
            path.write_bytes(r.content)
            out = (f"live Sun captured (SDO/AIA 171A) -> {path} | view: "
                   f"https://helioviewer.org/?date={d[:19].replace('T','%20')}")
        else:
            j = r.json()
            out = f"live Sun screenshot queued: {j.get('url', 'check helioviewer.org')}"
    except Exception as e:
        return f"(helioviewer unavailable: {e.__class__.__name__})"
    record("sun", "SDO/AIA 171A image captured", out)
    return out

def overhead(min_el=25, n=10, category=""):
    """What's above the operator right now? (OSIRIS live satellite positions)"""
    cfg = config.load()
    try:
        lat0 = math.radians(float(cfg.get("observer_lat", -15.42)))
        lon0 = math.radians(float(cfg.get("observer_lon", 28.28)))
        city = str(cfg.get("observer_city", "operator location"))
    except Exception:
        lat0, lon0, city = math.radians(-15.42), math.radians(28.28), "operator location"
    try:
        d = _osiris("/api/satellites")
        sats = d.get("satellites", [])
    except Exception as e:
        return f"(satellite catalog unavailable: {e.__class__.__name__})"
    R = 6371.0
    out = []
    for sat in sats:
        cat = sat.get("category", "?")
        if category and category.lower() != cat.lower():
            continue
        try:
            alt = float(sat.get("alt") or 0)
            la = math.radians(float(sat.get("lat") or 0))
            lo = math.radians(float(sat.get("lng") or 0))
        except (TypeError, ValueError):
            continue
        cos_c = (math.sin(lat0) * math.sin(la) + math.cos(lat0) * math.cos(la) * math.cos(lo - lon0))
        cos_c = max(-1.0, min(1.0, cos_c))
        c = math.acos(cos_c)
        r = R + max(alt, 100.0)
        # elevation above local horizon from subpoint geometry
        v = (math.cos(c) - R / r) / math.sqrt(max(1e-9, (1 - R / r) * (1 - R / r) + 4 * (R / r) * math.sin(c / 2) ** 2))
        el = math.degrees(math.atan2(math.cos(c) - R / r, math.sin(c)))
        if el >= min_el:
            slant = math.sqrt(max(0.0, r * r + R * R - 2 * r * R * cos_c))
            out.append((el, sat.get("name", "?"), alt, cat, slant))
    out.sort(reverse=True)
    hdr = (f"above {city} right now, elevation >={min_el} deg "
           f"({len(sats):,} objects scanned):")
    if not out:
        body = "(nothing that high overhead at this moment)"
    else:
        body = "\n".join(f"- {name}: {el:.0f} deg up, {alt:,.0f} km alt, {cat} "
                          f"(slant {sl:,.0f} km)" for el, name, alt, cat, sl in out[:n])
    res = hdr + "\n" + body
    record("overhead", f"{len(out)} objects above {min_el} deg now", res)
    return res
