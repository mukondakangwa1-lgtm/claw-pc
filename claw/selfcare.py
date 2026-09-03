"""Self-edit rails + self-debug. Rule: snapshot BEFORE changing anything, selfcheck AFTER; revert on failure."""
import subprocess, pathlib, sys, py_compile

CLAW = pathlib.Path.home() / "claw"

def _git(*args):
    return subprocess.run(["git", "-C", str(CLAW), *args], capture_output=True, text=True)

def snapshot(message):
    _git("add", "-A")
    r = _git("commit", "-m", message, "--allow-empty")
    return r.returncode == 0 or "nothing to commit" in r.stdout

def revert():
    r = _git("reset", "--hard", "HEAD~1")
    return r.returncode == 0, r.stdout.strip() or r.stderr.strip()

def compile_all():
    """Self-debug: byte-compile every claw python file; returns list of (file, error)."""
    errors = []
    targets = list((CLAW / "claw").glob("*.py")) + [CLAW / "clawcli.py"]
    for f in targets:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append((f.name, str(e)))
    return errors
