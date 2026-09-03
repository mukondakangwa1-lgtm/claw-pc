"""FastAPI gateway — what claw-phone and claw-cloud will talk to. Token-authenticated, LAN-only via ufw."""
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from . import config, brain, memory, tools, selfcare

app = FastAPI(title="claw-pc gateway")

def auth(x_claw_token: str = Header(default="")):
    if x_claw_token != config.load()["gateway_token"]:
        raise HTTPException(401, "bad token")

class Chat(BaseModel):
    message: str

class Cmd(BaseModel):
    command: str
    confirm: bool = False

@app.get("/health")
def health(x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    cfg = config.load()
    return {"status": "ok", "node": cfg["node_name"], "version": __import__("claw").VERSION}

@app.post("/chat")
def chat(c: Chat, x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    memory.add_message("user", c.message)
    reply, which = brain.think(c.message)
    memory.add_message("assistant", reply)
    return {"reply": reply, "brain": which}

@app.post("/cmd")
def cmd(c: Cmd, x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    rc, out = tools.execute(c.command, confirm=c.confirm)
    return {"returncode": rc, "output": out}

@app.get("/selfcheck")
def selfcheck(x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    errs = selfcare.compile_all()
    return {"ok": not errs, "errors": errs}
