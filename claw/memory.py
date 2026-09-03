import sqlite3, time, pathlib

DB = pathlib.Path.home() / "claw" / "memory" / "claw.db"

def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, ts REAL, key TEXT, value TEXT)")
    return c

def add_message(role, content):
    with _conn() as c:
        c.execute("INSERT INTO messages(ts, role, content) VALUES (?,?,?)", (time.time(), role, content))

def recent(n=8):
    with _conn() as c:
        rows = c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return list(reversed(rows))

def remember(key, value):
    with _conn() as c:
        c.execute("INSERT INTO facts(ts, key, value) VALUES (?,?,?)", (time.time(), key.lower(), value))

def recall(q=""):
    with _conn() as c:
        if q:
            return c.execute("SELECT key, value, ts FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY id DESC LIMIT 20",
                             (f"%{q}%", f"%{q}%")).fetchall()
        return c.execute("SELECT key, value, ts FROM facts ORDER BY id DESC LIMIT 20").fetchall()

def forget_all_messages():
    with _conn() as c:
        c.execute("DELETE FROM messages")
