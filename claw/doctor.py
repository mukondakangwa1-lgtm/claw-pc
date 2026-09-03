"""claw doctor — self-diagnosis. Every check answers: is Claw healthy right now?"""
import os, socket, shutil, pathlib, time
from . import config

def _check_net():
    try:
        s = socket.create_connection(("1.1.1.1", 443), timeout=4); s.close(); return True, "internet up"
    except Exception as e: return False, f"internet down ({e.__class__.__name__})"

def _check_groq(cfg):
    if not cfg["groq_api_key"]: return None, "no API key set (offline brain only)"
    try:
        r = requests_ok_groq(cfg); return (True, "groq reachable") if r else (False, "groq rejected key")
    except Exception as e: return False, f"groq unreachable ({e.__class__.__name__})"

def requests_ok_groq(cfg):
    import requests
    r = requests.get("https://api.groq.com/openai/v1/models",
                     headers={"Authorization": f"Bearer {cfg['groq_api_key']}"}, timeout=15)
    return r.status_code == 200

def _check_ollama(cfg):
    try:
        import requests
        r = requests.get(f"{cfg['ollama_url']}/api/tags", timeout=5)
        return (True, f"ollama up ({len(r.json().get('models', []))} model(s))") if r.ok else (False, "ollama error")
    except Exception: return None, "ollama not running (optional offline brain)"

def run():
    cfg = config.load()
    results = []
    ok, msg = _check_net(); results.append(("net", ok, msg))
    du = shutil.disk_usage("/")
    pct = du.used / du.total * 100
    results.append(("disk", pct < 90, f"root {pct:.0f}% used ({du.free//2**30} GB free)"))
    mem = {}
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1); mem[k] = int(v.split()[0])
    avail_gb = mem["MemAvailable"] / 2**20
    results.append(("ram", avail_gb > 0.5, f"{avail_gb:.1f} GB available"))
    try:
        socket.getaddrinfo("kali.org", 443); results.append(("dns", True, "DNS resolving"))
    except Exception as e: results.append(("dns", False, f"DNS broken ({e.__class__.__name__})"))
    g_ok, g_msg = _check_groq(cfg); results.append(("brain:groq", g_ok, g_msg))
    o_ok, o_msg = _check_ollama(cfg); results.append(("brain:ollama", o_ok, o_msg))
    results.append(("gateway-token", bool(cfg["gateway_token"]), "token configured" if cfg["gateway_token"] else "missing"))
    git_dir = pathlib.Path.home() / "claw" / ".git"
    results.append(("git(self-edit rails)", git_dir.exists(), "repo present" if git_dir.exists() else "not a git repo yet"))
    return results

def report():
    results = run()
    icons = {True: "✅", False: "❌", None: "⚠️ "}
    print(f"🐾 CLAW doctor — {time.strftime('%Y-%m-%d %H:%M')}")
    for name, ok, msg in results:
        print(f"  {icons[ok]} {name:18} {msg}")
    hard_fails = [r for r in results if r[1] is False]
    print(f"\nverdict: {'UNHEALTHY — fix ❌ above' if hard_fails else 'HEALTHY'}")
    return 1 if hard_fails else 0
