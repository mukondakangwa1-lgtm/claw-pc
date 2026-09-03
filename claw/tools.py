"""Sandboxed shell tool. Allowlist first-word; hard-block list; --yes gate for risky ops."""
import shlex, subprocess

ALLOWED_FIRST = {
    "ls","cat","head","tail","pwd","df","free","uname","uptime","whoami","date","id",
    "ping","dig","whois","host","ip","ss","ps","top","du","wc","file","stat","find","grep",
    "nmap","traceroute","curl","wget","git","python3","pip","sqlite3","systemctl","journalctl",
    "apt","apt-get","ufw","ollama","nvidia-smi","lsusb","lspci","lsblk","sha256sum","tar","gzip",
}
HARD_BLOCK = ["mkfs", "shutdown", "reboot", "poweroff", "dd if=", ":(){", "> /dev/sd", "chown -R /"]
NEEDS_CONFIRM = ["sudo", "rm -rf", "apt ", "ufw", "systemctl", "pip install", "nmap -Pn", "--script"]

def execute(command: str, confirm: bool = False):
    try:
        parts = shlex.split(command)
    except ValueError:
        return 1, "parse error"
    if not parts:
        return 1, "empty command"
    if parts[0] not in ALLOWED_FIRST:
        return 1, f"blocked: '{parts[0]}' is not in the allowlist (tools.py ALLOWED_FIRST)"
    low = command.lower()
    for bad in HARD_BLOCK:
        if bad in low:
            return 1, f"blocked: '{bad}' is on the never-run list"
    if not confirm and any(p in low for p in NEEDS_CONFIRM):
        return 1, "needs confirmation: re-run with --yes"
    try:
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
        out = (p.stdout + p.stderr).strip() or "(no output)"
        return p.returncode, out[:8000]
    except subprocess.TimeoutExpired:
        return 124, "timeout after 120s"
