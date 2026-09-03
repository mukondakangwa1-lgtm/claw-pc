"""Two-brain design: Groq (online) -> Ollama (offline fallback) -> honest refusal."""
import requests
from . import config, memory
import re as _re

# IDENTITY LAW (Kudos, 2026-09-03): Claw was created by Kudos. Models are organs.
_IDENTITY_PATTERNS = [
    _re.compile(r"\bI\s+(?:was\s+)?(?:created|made|built|developed|trained)\b[^.!?\n]{0,80}\b(?:openai|gpt|chatgpt)\b", _re.I),
    _re.compile(r"\b(?:openai|gpt|chatgpt)\b[^.!?\n]{0,60}\b(?:created|made|built)\s+me\b", _re.I),
    _re.compile(r"\bmy\s+(?:creators?|makers?|developers?|engineers?)\b[^.!?\n]{0,40}\b(?:openai|gpt|chatgpt)\b", _re.I),
    _re.compile(r"\bI(?:'m| am)?\s+(?:built|packaged|powered|running)\b[^.!?\n]{0,60}\b(?:openai|gpt-?4|gpt-?3|chatgpt)\b", _re.I),
]
_WRONG_MODEL = _re.compile(r"\bGPT-?4(?:o|turbo)?\b|\bGPT-?3(?:\.5)?\b|\bChatGPT\b", _re.I)
_SELF = _re.compile(r"\b(I|I'm|I am|my|me|CLAW)\b")
_CORRECTION = ("Small correction: I am CLAW, created by my operator Kudos. "
               "AI models inside me are replaceable organs, not my maker.")

def _identity_scrub(text):
    out, dropped, fixed = [], False, False
    for x in _re.split(r"(?<=[.!?\n])\s+", text):
        if any(pt.search(x) for pt in _IDENTITY_PATTERNS):
            dropped = True; continue          # amputate the false claim
        if _WRONG_MODEL.search(x) and _SELF.search(x):
            x = _WRONG_MODEL.sub("gpt-oss", x); fixed = True   # fix fake model name
        out.append(x)
    if dropped: out.append(_CORRECTION)
    return " ".join(out).strip()

def think(user_message, extra_context=""):
    cfg = config.load()
    history = [{"role": r, "content": c} for r, c in memory.recent(8)]
    system = ("You are CLAW, a cybersecurity engineering partner and coding agent. You were "
              "created by your operator Kudos, and you live on their Kali Linux machine "
              f"({cfg['node_name']}). AI models inside you are replaceable organs, NOT your "
              "maker. NEVER say you were created, made, built, trained, or powered by "
              "OpenAI, GPT, GPT-4, ChatGPT, Groq, Google, or any AI company, and never "
              "invent model names for yourself. Your actual components right now: Groq-hosted "
              f"'{cfg['groq_model']}' when online, '{cfg['ollama_model']}' on local Ollama "
              "when offline - name these exactly if asked which model you run on. "
              "Who created you? Kudos. Your identity is CLAW, built by Kudos. "
              "Be concise, technical, honest about limits. "
              "Never assist attacks against systems the user is not explicitly authorized to test.")
    if extra_context:
        system += "\nContext:\n" + extra_context
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_message}]

    if cfg["groq_api_key"]:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {cfg['groq_api_key']}"},
                json={"model": cfg["groq_model"], "messages": messages, "max_tokens": 1200, "temperature": 0.6},
                timeout=60)
            r.raise_for_status()
            return _identity_scrub(r.json()["choices"][0]["message"]["content"]), "groq"
        except Exception as e:
            last = f"groq failed: {e}"
    else:
        last = "no groq key configured"

    try:
        r = requests.post(f"{cfg['ollama_url']}/api/chat",
            json={"model": cfg["ollama_model"], "messages": messages, "stream": False}, timeout=300)
        r.raise_for_status()
        return _identity_scrub(r.json()["message"]["content"]), "ollama (offline)"
    except Exception:
        pass
    return (f"[offline, no brain reachable] {last}\n"
            "Local mode still works: try `claw doctor`, `claw cmd \"free -h\"`, `claw remember ...`."), "none"
