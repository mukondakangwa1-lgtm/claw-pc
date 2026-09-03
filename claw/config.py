import os, tomllib, pathlib

DEFAULTS = {
    "node_name": "claw-pc", "gateway_port": 8787, "gateway_token": "",
    "groq_api_key": "", "groq_model": "llama-3.3-70b-versatile",
    "ollama_url": "http://localhost:11434", "ollama_model": "qwen2.5-coder:1.5b",
    "osiris_base": "https://osirisai.live",
    "observer_city": "Lusaka", "observer_lat": -15.42, "observer_lon": 28.28,
}

def load():
    p = pathlib.Path.home() / "claw" / "config.toml"
    cfg = dict(DEFAULTS)
    if p.exists():
        cfg.update(tomllib.loads(p.read_text()))
    if os.environ.get("CLAW_GROQ_KEY"):
        cfg["groq_api_key"] = os.environ["CLAW_GROQ_KEY"]
    return cfg
