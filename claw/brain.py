"""Two-brain design: Groq (online) -> Ollama (offline fallback) -> honest refusal."""
import requests
from . import config, memory

def think(user_message, extra_context=""):
    cfg = config.load()
    history = [{"role": r, "content": c} for r, c in memory.recent(8)]
    system = ("You are CLAW, a cybersecurity engineering partner and coding agent. You were "
              "created by your operator Kudos, and you live on their Kali Linux machine "
              f"({cfg['node_name']}). Any AI model inside you (Groq-hosted or local) is just an "
              "organ - it is not your maker. NEVER claim to have been created by OpenAI, Groq, "
              "Google, or any AI company or lab; when asked who made you, the answer is: Kudos. "
              "If asked which model you run on, state it factually as a component, but your "
              "identity is Claw, built by Kudos. Be concise, technical, honest about limits. "
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
            return r.json()["choices"][0]["message"]["content"], "groq"
        except Exception as e:
            last = f"groq failed: {e}"
    else:
        last = "no groq key configured"

    try:
        r = requests.post(f"{cfg['ollama_url']}/api/chat",
            json={"model": cfg["ollama_model"], "messages": messages, "stream": False}, timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"], "ollama (offline)"
    except Exception:
        pass
    return (f"[offline, no brain reachable] {last}\n"
            "Local mode still works: try `claw doctor`, `claw cmd \"free -h\"`, `claw remember ...`."), "none"
