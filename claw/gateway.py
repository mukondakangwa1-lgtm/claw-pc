"""FastAPI gateway — what claw-phone and claw-cloud will talk to. Token-authenticated, LAN-only via ufw."""
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import os
from . import config, brain, memory, tools, selfcare

app = FastAPI(title="claw-pc gateway")

def auth(x_claw_token: str = Header(default="")):
    if x_claw_token != config.load()["gateway_token"]:
        raise HTTPException(401, "bad token")

class Chat(BaseModel):
    message: str = ""
    handle: str = ""
    subject: str = ""
    pace: str = ""
    exam_date: str = ""
    program: str = ""
    mode: str = ""
    institution: str = ""
    year: str = ""
    acsystem: str = ""

class Cmd(BaseModel):
    command: str
    confirm: bool = False

@app.get("/health")
def health(x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    cfg = config.load()
    return {"status": "ok", "node": cfg["node_name"], "version": __import__("claw").VERSION}

@app.get("/sky")
def sky_ep(x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    from claw import beyond
    return {"dsn": beyond.dsn(), "space": beyond.space()}
@app.post("/visual")
def visual_ep(c: Chat, x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    import glob as _glob, os as _os
    from claw import brain, memory
    from claw.beyond import _root as _broot
    msg = (c.message or "").strip()
    low = msg.lower()
    image = None
    try:
        if "sun" in low or "solar" in low:
            from claw import beyond as _beyond
            _beyond.sun()
            suns = sorted(_glob.glob(str(_broot() / "memory" / "beyond" / "sun-*.png")))
            if suns:
                image = _os.path.basename(suns[-1])
        elif any(k in low for k in ("show me", "picture", "photo", "image", "visual", "media")):
            cands = []
            for pat in ("workspace/media/*.png", "workspace/media/*.jpg", "workspace/media/*.jpeg",
                        "memory/beyond/sun-*.png"):
                cands += _glob.glob(str(_broot() / pat))
            if cands:
                image = _os.path.basename(max(cands, key=_os.path.getmtime))
    except Exception:
        image = None
    reply, which = brain.think(msg)
    memory.add_message("user", msg)
    memory.add_message("assistant", reply)
    if "map" in low:
        try:
            from claw import journalist
            reply = reply + "\nlive map: " + journalist.map_url()
        except Exception:
            pass
    return {"reply": reply, "brain": which, "image": image}



@app.get("/brief")
def brief_ep(x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    from claw import journalist
    return {"briefing": journalist.brief()}

@app.post("/investigate")
def investigate_ep(c: Chat, x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    from claw import journalist
    return {"investigation": journalist.investigate(c.message)}

@app.post("/stop")
def stop_ep(x_claw_token: str = Header(default="")):
    auth(x_claw_token)
    import os as _os
    _os._exit(0)

# ---------- PUBLIC SITE (no token; rate-limited; educational tutor only) ----------
_PUB = {}
def _rate(ip, limit=8, window=60):
    import time as _t
    now = _t.time()
    q = [t for t in _PUB.get(ip, []) if now - t < window]
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="slow down - try in a minute")

@app.get("/site2", response_class=HTMLResponse)
def site2_ep():
    return SITE_HTML.replace("<h1>🐾 CLAW — public desk</h1>", "<h1>🐾 CLAW — public desk</h1><div style='background:#238636;color:#fff;padding:8px;border-radius:10px;margin:6px 0;text-align:center;font-weight:bold'>&#9989; CLAW VISUAL EDITION &mdash; LIVE</div>", 1) + "\n<!-- VISUALS-V3-LIVE -->"

@app.get("/site", response_class=HTMLResponse)
def site_ep():
    return SITE_HTML

@app.post("/api/public/chat")
def pub_chat(c: Chat, x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local")
    from claw import tutor
    msg = (c.message or "").strip()[:2000]
    handle = (c.handle or "student")
    reply, which, img = tutor.chat(handle, msg)
    return {"reply": reply, "brain": which, "image": img}

@app.post("/api/public/plan")
def pub_plan(c: Chat, x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local")
    from claw import tutor
    reply, img = tutor.plan((c.handle or "student"), (c.subject or "").strip()[:80],
                            (c.pace or "standard")[:12], (c.exam_date or "")[:24], (c.program or "")[:60])
    return {"reply": reply, "image": img}

@app.get("/api/public/status")
def pub_status(handle: str = "student", x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    from claw import tutor
    return {"status": tutor.status((handle or "student")[:40])}

@app.get("/api/public/subjects")
def pub_subjects(program: str = "", x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=30)
    from claw import tutor
    return {"subjects": tutor.subjects((program or "")[:60])}

@app.get("/api/public/autodate")
def pub_autodate(institution: str = "", system: str = "", year: str = "",
                 x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=30)
    from claw import tutor
    d, note = tutor.next_exam((institution or "")[:60], (system or "")[:12])
    return {"date": d, "note": note}


@app.get("/api/public/preview")
def pub_preview(url: str = "", x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=20)
    import socket, ipaddress as _ipa
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "http(s) links only")
    try:
        hostn = url.split("/", 3)[2].split(":")[0].lower()
    except Exception:
        raise HTTPException(400, "bad url")
    if hostn in ("localhost", "::1") or hostn.startswith(("127.", "10.", "192.168.", "0.0.", "169.254.")):
        raise HTTPException(400, "local addresses are not fetchable")
    try:
        for _inf in socket.getaddrinfo(hostn, None):
            if _ipa.ip_address(_inf[4][0]).is_private:
                raise HTTPException(400, "private addresses are not fetchable")
    except HTTPException:
        raise
    except Exception:
        pass
    import requests as _rq
    r = _rq.get(url, headers={"User-Agent": "Mozilla/5.0 claw-tutor/2.0"}, timeout=25)
    buf = r.content[: 8 * 1024 * 1024]
    ct = (r.headers.get("content-type") or "").lower()
    if buf[:5] == b"%PDF-" or "pdf" in ct:
        mt = "application/pdf"
    elif "png" in ct:
        mt = "image/png"
    elif "jpeg" in ct or "jpg" in ct:
        mt = "image/jpeg"
    else:
        mt = "application/octet-stream"
    from fastapi.responses import Response as _Resp
    return _Resp(content=buf, media_type=mt)



@app.get("/api/public/greet")
def pub_greet(handle: str = "student", x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=30)
    from claw import tutor
    return {"reply": tutor.greet((handle or "student")[:40])}



@app.get("/api/public/doc")
def pub_doc(handle: str = "student", kind: str = "practice", subject: str = "",
            x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=30)
    from claw import tutor
    txt = tutor.get_doc((handle or "student")[:40], (kind or "practice")[:12], (subject or "")[:60])
    if not txt:
        return {"reply": "nothing generated yet - press GENERATE PRACTICE PAPER or say 'quiz me on X' first"}
    safe = "".join(ch for ch in (subject or kind)[:40] if ch.isalnum() or ch in "._- ") or kind
    from fastapi.responses import Response as _Resp
    return _Resp(content=txt, media_type="text/plain; charset=utf-8",
                 headers={"Content-Disposition": "attachment; filename=claw-%s-%s.txt" % ((kind or "doc")[:12], safe)})


# ---------- MEDIA GALLERY (token via header OR ?token= for webview) ----------
def _auth_q(x_claw_token: str = Header(default=""), token: str = ""):
    cfg = config.load()
    if x_claw_token != cfg["gateway_token"] and token != cfg["gateway_token"]:
        raise HTTPException(status_code=401, detail="unauthorized")

import pathlib as _pl
def _media_dirs():
    root = _pl.Path(config.__file__).resolve().parent.parent
    dirs = [root / "workspace" / "media", root / "memory" / "beyond"]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return dirs

@app.get("/media", response_class=HTMLResponse)
def media_ep(token: str = "", x_claw_token: str = Header(default="")):
    _auth_q(x_claw_token, token)
    items = []
    for d in _media_dirs():
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm"):
                    items.append(f.name)
    cells = "".join(
        f'<a href="media/f/{n}?token={token}"><img src="media/f/{n}?token={token}" loading="lazy"></a>'
        for n in items if n.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")))
    vids = "".join(f'<p><a href="media/f/{n}?token={token}">{n}</a></p>'
                   for n in items if n.lower().endswith((".mp4", ".webm")))
    return ("<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>CLAW media</title><style>body{background:#0b0e11;color:#e6e6e6;font-family:sans-serif}"
            "h1{color:#7ce38b}img{max-width:100%;border-radius:10px;margin:6px 0}a{color:#ffd866}</style></head>"
            "<body><h1>🐾 CLAW media gallery</h1>" + (cells or "<p>(no images yet - ask Claw for the Sun: claw sun)</p>")
            + vids + "</body></html>")

@app.get("/media/f/{name}")
def media_file(name: str, token: str = "", x_claw_token: str = Header(default="")):
    _auth_q(x_claw_token, token)
    import os as _os
    safe = _os.path.basename(name)
    for d in _media_dirs():
        f = d / safe
        if f.exists():
            return FileResponse(str(f))
    raise HTTPException(status_code=404, detail="not found")


# ---------- EXAM-BODY AWARE STUDENT TOOLS (public, rate-limited) ----------
@app.post("/api/public/profile")
def pub_profile(c: Chat, x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local")
    from claw import tutor
    tutor.ensure_student((c.handle or "student")[:40], program=(c.program or "").strip()[:60])
    rep = tutor.set_body((c.handle or "student")[:40],
                         (c.subject or "").strip()[:16],
                         "",
                         (c.pace or "").strip()[:40])
    tutor.save_extra((c.handle or "student")[:40],
                     (c.institution or "").strip()[:60],
                     (c.year or "").strip()[:4],
                     (c.acsystem or "").strip()[:12])
    return {"reply": rep}

@app.post("/api/public/examprep")
def pub_examprep(c: Chat, x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=4)
    from claw import tutor
    handle = (c.handle or "student")[:40]
    subject = (c.subject or "").strip()[:80]
    st = tutor._student(handle)
    body = st.get("body") or ""
    if not body:
        return {"error": "save your exam body first (TEVETA, ECZ, ...)"}
    if (c.mode or "").strip() == "papers":
        pp = tutor.paper_pack(body, subject)
        return {"links": pp["links"], "previews": pp["previews"], "reply": tutor.body_rules(body)}
    _t = tutor.practice_paper(handle, subject)
    import urllib.parse as _up
    _u = "/api/public/doc?handle=" + _up.quote((handle or "student")[:40]) + "&kind=practice&subject=" + _up.quote(subject or "")
    return {"reply": _t, "previews": [{"type": "link", "title": "download this paper", "url": _u}]}

@app.post("/api/public/upload2")
def pub_upload2(file: UploadFile = File(...), handle: str = Form("student"),
                x_forwarded_for: str = Header(default=""), host: str = Header(default="")):
    _rate(x_forwarded_for or host or "local", limit=25)
    from claw import tutor
    raw = file.file.read(tutor.MAX_DOC + 1)
    if len(raw) > tutor.MAX_DOC:
        raise HTTPException(status_code=413, detail="file too big (max 15MB)")
    name = file.filename or "file"
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        return {"reply": tutor.add_media((handle or "student")[:40], name, raw)}
    if ext == "pdf":
        text = tutor.extract_pdf_text(raw)
        if not text.strip():
            return {"reply": f"'{name}' is a PDF I could not extract text from (likely scanned "
                             f"images) - re-upload the pages as images for now; OCR is on the roadmap"}
        return {"reply": tutor.add_doc((handle or "student")[:40], name + ".txt", text)}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"reply": f"'{name}': unsupported type for now (txt/md/pdf/images)"}
    return {"reply": tutor.add_doc((handle or "student")[:40], name, text)}

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

SITE_HTML = '<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>CLAW - public desk</title>\n<style>\n body{background:#0b0e11;color:#e6e6e6;font-family:system-ui,sans-serif;margin:0;padding:12px;max-width:780px;margin:auto}\n h1{color:#7ce38b;font-size:1.3rem} small{color:#8a97a3}\n input,select,textarea,button{background:#161b22;color:#e6e6e6;border:1px solid #2d333b;border-radius:8px;padding:8px;margin:3px 0;font-size:1rem}\n input,select{width:42%} textarea{width:100%;min-height:70px} button{cursor:pointer;padding:9px 14px}\n button.act{background:#238636;border-color:#238636;color:#fff}\n .me{color:#7ce38b;margin:6px 0} .claw{color:#ffd866;margin:6px 0;white-space:pre-wrap}\n .box{background:#0d1117;border:1px solid #2d333b;border-radius:10px;padding:10px;margin:8px 0;max-height:430px;overflow:auto}\n label{color:#8a97a3;font-size:.85rem}\n</style></head><body>\n<h1>🐾 CLAW — public desk</h1>\n<small>your exam-body-aware study agent · exam prep → mastery · honest, sourced</small>\n<div id="pf1">\n <label>your name</label><input id="h" placeholder="nickname" style="width:30%">\n <label>pace</label><select id="p"><option>casual</option><option selected>standard</option><option>intense</option></select>\n <label>exam date</label><input id="e" placeholder="e.g. June 2027" style="width:26%">\n</div>\n<div id="pf2">\n <label>exam body</label>\n <select id="b"><option value="">— none —</option><option value="teveta">TEVETA Zambia</option><option value="ecz">ECZ Zambia</option><option value="waec">WAEC</option><option value="caie">Cambridge (CAIE)</option><option value="ib">IB</option></select>\n <label>level</label><input id="l" placeholder="e.g. craft certificate" style="width:30%">\n <label>program</label><input id="g" placeholder="e.g. electrical diploma" style="width:34%">\n</div>\n<div>\n <label>institution</label><input id="ins" list="il" placeholder="e.g. Evelyn Hone College" style="width:30%">\n <datalist id="il"><option>Evelyn Hone College</option><option>NIPA</option><option>NORTEC</option><option>ZCAS</option><option>LIBTES</option><option>ZIBS</option></datalist>\n <label>year</label><select id="y"><option value="">?</option><option>1</option><option>2</option><option>3</option><option>4</option></select>\n <label>calendar</label><select id="cs"><option value="">auto</option><option value="semester">semester</option><option value="term">term</option><option value="yearly">yearly</option></select>\n</div>\n<button id="sb" onclick="saveProfile()">SAVE PROFILE</button><a id="eb" style="display:none;margin-left:10px;color:#8a97a3;cursor:pointer" onclick="showProf()">edit details</a>\n<div>\n <label>subject</label><input list="sl" id="s" placeholder="e.g. entrepreneurship" style="width:44%"><datalist id="sl"></datalist>\n <button class="act" onclick="makePlan()">BUILD MY LEARNING PLAN</button>\n <button onclick="prep(\'papers\')">PAST PAPERS & RULES</button>\n <button onclick="prep(\'practice\')">GENERATE PRACTICE PAPER</button>\n</div>\n<div>\n <label>documents & media (txt/md/pdf/images · up to 15 MB each · select many)</label><br>\n <input type="file" id="f" multiple><button onclick="up()">SEND ALL TO CLAW</button>\n <button onclick="stat()">my status</button>\n</div>\n<div class="box" id="log">say hi - chat works even before you save your details (claw will keep asking!)</div>\n<textarea id="m" placeholder="ask, answer exercises, or say \'quiz me on X\'"></textarea>\n<button class="act" onclick="chat()">SEND</button>\n<script>\nconst B=\"\";\n\nfunction addImg(u){const d=document.getElementById("log");var im=new Image();im.src=u;im.style.cssText="max-width:100%;border-radius:10px;margin:2px 0;display:block";im.onload=function(){d.scrollTop=d.scrollHeight;};d.appendChild(im);}\n\nfunction add(c,t){const d=document.getElementById("log");\n d.innerHTML=d.innerHTML+\'<div class="\'+c+\'">\'+t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/(https?:\\/\\/[^\\s<"]+|\\/api\\/[^\\s<"]+)/g,\'<a href="$1" target="_blank" rel="noopener">$1</a>\')+\'</div>\';\n d.scrollTop=d.scrollHeight;}function addLink(u,t){const d=document.getElementById("log");d.innerHTML=d.innerHTML+\'<div class="claw">\U0001f517 <a href="\'+u.replace(/"/g,"&quot;")+\'" target="_blank" rel="noopener">\'+(t||"open link")+\'</a></div>\';d.scrollTop=d.scrollHeight;}\nfunction addPrev(pv){if(!pv)return;if(pv.type==="image"){add("claw","\U0001f5bc "+(pv.title||"image"));addImg(pv.url);}else if(pv.type==="book"){add("claw","\U0001f4d8 "+pv.title+(pv.author?" - "+pv.author:"")+(pv.year?" ("+pv.year+")":""));if(pv.cover)addImg(pv.cover);addLink(pv.url,"open in Open Library");}else if(pv.type==="pdf"){add("claw","\U0001f4c4 "+(pv.title||"past paper"));addLink(pv.url,"open the paper (PDF)");}else{addLink(pv.url,pv.title||"open link");}}\n\nfunction H(){return document.getElementById("h").value||"student";}\nasync function post(path,obj){\n const r=await fetch(B+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj)});\n return r.json().catch(()=>({reply:"(server error)"}));}\nasync function saveProfile(){\n const j=await post("/api/public/profile",{handle:H(),subject:document.getElementById("b").value,\n  pace:document.getElementById("l").value,program:document.getElementById("g").value,\n  institution:document.getElementById("ins").value,year:document.getElementById("y").value,acsystem:document.getElementById("cs").value});\n add("claw",j.reply||j.error||"saved");if(j.reply&&!j.error){store();hideProf();}}\nasync function chat(){\n const m=document.getElementById("m").value.trim();if(!m)return;\n document.getElementById("m").value="";add("me","you: "+m);\n const j=await post("/api/public/chat",{handle:H(),message:m});\n add("claw",j.reply||j.error||"(empty)");if(j.image)addImg(j.image);}\nasync function makePlan(){\n const s=document.getElementById("s").value.trim();if(!s)return;\n add("me","build my plan for: "+s);add("claw","…designing your full plan…");\n const j=await post("/api/public/plan",{handle:H(),subject:s,pace:document.getElementById("p").value,\n  exam_date:document.getElementById("e").value,program:document.getElementById("g").value});\n add("claw",j.reply||j.error||"(empty)");if(j.image)addImg(j.image);}\nasync function prep(mode){\n const s=document.getElementById("s").value.trim();if(!s)return;\n add("me",(mode==="papers"?"find past papers & rules for: ":"generate a practice paper for: ")+s);\n add("claw","…searching the exam body…");\n const j=await post("/api/public/examprep",{handle:H(),subject:s,mode:mode});\n add("claw",(j.links?j.links.join("\\n")+"\\n\\n":"")+(j.reply||j.error||""));if(j.previews)j.previews.forEach(function(pv){addPrev(pv);});}\nasync function up(){\n const fs=document.getElementById("f").files;if(!fs.length)return;\n for(const f of fs){\n  if(f.size>15*1024*1024){add("claw","✗ "+f.name+" is over 15 MB — skip");continue;}\n  const fd=new FormData();fd.append("file",f);fd.append("handle",H());\n  try{const r=await fetch(B+"/api/public/upload2",{method:"POST",body:fd});\n   const j=await r.json();add("claw",(j.reply||j.error||"stored")+"");}\n  catch(e){add("claw","✗ "+f.name+" failed: "+e);}}\n document.getElementById("f").value="";}\nasync function stat(){\n const r=await fetch(B+"/api/public/status?handle="+encodeURIComponent(H()));\n const j=await r.json().catch(()=>({status:"(error)"}));add("claw",j.status||"(none)");}\ndocument.getElementById("m").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();chat();}});\nfunction remember(){try{const d=JSON.parse(localStorage.getItem("clawProfile")||"{}");["h","p","e","b","l","g","s"].forEach(function(k){if(d[k])document.getElementById(k).value=d[k];});subs();}catch(e){}}\nfunction store(){try{const d={};["h","p","e","b","l","g","s"].forEach(function(k){d[k]=document.getElementById(k).value;});localStorage.setItem("clawProfile",JSON.stringify(d));}catch(e){}}\nasync function subs(){try{const g=document.getElementById("g").value.trim();const el=document.getElementById("sl");if(!el)return;el.innerHTML="";if(!g)return;const r=await fetch("/api/public/subjects?program="+encodeURIComponent(g));const j=await r.json();(j.subjects||[]).forEach(function(s){const o=document.createElement("option");o.value=s;el.appendChild(o);});}catch(e){}}\ndocument.getElementById("g").addEventListener("change",subs);\n\nfunction academic(){try{var q=new URLSearchParams({institution:document.getElementById("ins").value,system:document.getElementById("cs").value,year:document.getElementById("y").value});fetch(B+"/api/public/autodate?"+q).then(function(r){return r.json();}).then(function(j){if(j.date)document.getElementById("e").value=j.date;document.getElementById("e").title=j.note||"";}).catch(function(){});}catch(e){}}\n["ins","cs","y"].forEach(function(k){var el=document.getElementById(k);if(el)el.addEventListener("change",academic);});\n\n\ntry{window.addEventListener("beforeunload",function(){var d={};["h","p","e","b","l","g","s","ins","y","cs"].forEach(function(k){d[k]=document.getElementById(k).value;});localStorage.setItem("clawProfile",JSON.stringify(d));});}catch(e){}\n\n\nfunction hideProf(){try{["pf1","pf2"].forEach(function(i){document.getElementById(i).style.display="none";});document.getElementById("sb").style.display="none";var e=document.getElementById("eb");if(e)e.style.display="inline";}catch(e){}}\nfunction showProf(){try{["pf1","pf2"].forEach(function(i){document.getElementById(i).style.display="";});document.getElementById("sb").style.display="";var e=document.getElementById("eb");if(e)e.style.display="none";}catch(e){}}\n\nremember();\n\ntry{var _d=JSON.parse(localStorage.getItem("clawProfile")||"{}");if(_d.h){if(_d.b||_d.g)hideProf();fetch(B+"/api/public/greet?handle="+encodeURIComponent(_d.h)).then(function(r){return r.json();}).then(function(j){if(j.reply)add("claw",j.reply);}).catch(function(){});}}catch(e){}\n\n\n</script></body></html>\n'