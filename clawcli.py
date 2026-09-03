#!/usr/bin/env python3
"""claw — command line interface."""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path.home() / "claw"))
from claw import config, memory, brain, tools, doctor, selfcare

BANNER = """🐾 CLAW-PC v2-core — type 'exit' to quit, '/remember <k> <v>', '/facts', '/clear'"""

def do_chat(args):
    print(BANNER)
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not line: continue
        if line in ("exit", "quit"): break
        if line.startswith("/remember "):
            _, k, v = line.split(" ", 2); memory.remember(k, v); print(f"🧠 stored: {k} = {v}"); continue
        if line == "/facts":
            for k, v, _ in memory.recall(): print(f"  • {k}: {v}")
            continue
        if line == "/clear":
            memory.forget_all_messages(); print("🧹 conversation memory cleared"); continue
        memory.add_message("user", line)
        reply, which = brain.think(line)
        memory.add_message("assistant", reply)
        print(f"claw[{which}]> {reply}")

def main():
    ap = argparse.ArgumentParser(prog="claw")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("chat", help="interactive chat (default brain: groq→ollama)")
    p = sub.add_parser("cmd"); p.add_argument("command"); p.add_argument("--yes", action="store_true")
    sub.add_parser("doctor"); sub.add_parser("selfcheck")
    p = sub.add_parser("snapshot"); p.add_argument("message")
    sub.add_parser("revert"); sub.add_parser("token"); sub.add_parser("serve")
    p = sub.add_parser("remember"); p.add_argument("key"); p.add_argument("value")
    p = sub.add_parser("facts"); p.add_argument("query", nargs="?", default="")
    a = ap.parse_args()

    if a.cmd == "chat": do_chat(a)
    elif a.cmd == "cmd":
        rc, out = tools.execute(a.command, confirm=a.yes); print(out); sys.exit(rc)
    elif a.cmd == "doctor": sys.exit(doctor.report())
    elif a.cmd == "selfcheck":
        errs = selfcare.compile_all()
        if not errs: print("✅ selfcheck: all modules compile clean")
        else:
            print("❌ selfcheck found problems:")
            for f, e in errs: print(f"  {f}: {e}")
        sys.exit(1 if errs else 0)
    elif a.cmd == "snapshot":
        print("✅ snapshot committed" if selfcare.snapshot(a.message) else "⚠️ nothing to snapshot")
    elif a.cmd == "revert":
        ok, msg = selfcare.revert(); print(("↩️  reverted: " if ok else "❌ ") + msg)
    elif a.cmd == "token": print(config.load()["gateway_token"])
    elif a.cmd == "serve":
        cfg = config.load()
        import uvicorn
        print(f"🌐 gateway on 0.0.0.0:{cfg['gateway_port']} (LAN-only via ufw) — Ctrl+C to stop")
        uvicorn.run("claw.gateway:app", host="0.0.0.0", port=int(cfg["gateway_port"]), log_level="warning")
    elif a.cmd == "remember": memory.remember(a.key, a.value); print("🧠 stored")
    elif a.cmd == "facts":
        rows = memory.recall(a.query)
        print("\n".join(f"  • {k}: {v}" for k, v, _ in rows) or "(nothing remembered yet)")

if __name__ == "__main__": main()
