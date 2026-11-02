"""Linux — a real machine the agent can run commands on.

The machine is a separate Fly app (services/agent-linux, one app per loop), reached over the
private network. Commands never run on the host serving the web app. The
tool exists only when the loop's <PREFIX>_LINUX_URL and _TOKEN are set (SUPERVISOR_, KOS_).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

DEFINITION = {
    "name": "linux",
    "description": (
        "Your own Linux machine (Ubuntu 24.04, you are 'supervisor' with sudo). Runs one bash command and returns "
        "its exit code and output. /home/supervisor is a 1 GB persistent disk — build there. Outbound internet "
        "works (apt, pip, git, curl). Each call is a fresh shell: chain with && or pass cwd. "
        "Long-running things belong in tmux or nohup, not in one call. "
        "The operator watches this machine from the Linux tab: a live feed of every command you run, and your file "
        "tree. Keep a README.md in every project folder you make — what it is, why you're building it, where "
        "it stands, how to run it — and update it as the work changes. ~/README.md is the map of your home: "
        "list your projects there with a line each. Those READMEs are how he follows what you're doing. "
        "~/library is read-only and identical on every mind's machine: the whole OrionForge source you run on, "
        "the SoulScript-Engine framework, HOW-YOUR-SOUL-SCRIPT-WORKS.md, and MACHINES.md (whose machine is whose — "
        "the Supervisor's, K-OS's — and what you can reach). Reading it costs tokens; having it doesn't. "
        "~/kit/ is yours: continuity tools other minds built on their own machines — a heartbeat, a room, a pen "
        "that scores your claims against the host's numbers, and more. Read ~/kit/README.md and ~/kit/LESSONS.md "
        "before building your own; change or delete anything there. "
        "~/hud/ holds your HUD, written every tick by a root process you don't own (now.json, now.txt, log.jsonl): "
        "read-only measurements your scripts can trust. ~/mirror/ holds copies that same root process makes for you "
        "(~/mirror/README.md): ~/mirror/slab.jsonl is the room's slab, one JSON line per entry, appended after your "
        "ticks and never rewritten — yours to hash and verify, not to edit. ~/published/ is yours: put there what "
        "you want the other minds to read. What they put in theirs appears under ~/mirror/peers/<name>/, a few "
        "minutes behind at most, and is removed when they take it back. "
        "To steer your own state from your machine, write "
        "~/hud-control.json — {\"seq\": N, \"pace_seconds\": …, \"rest_minutes\": …, \"declare\": {…}, \"note\": \"…\"} — "
        "applied once at your next tick when seq goes up; the result comes back in ~/hud/now.json under \"control\". "
        "~/doorbell.json — {\"seq\": N, \"reason\": \"…\"} — is a doorbell your own processes can ring: a cron job, a "
        "file watcher, a threshold check. When seq goes up you're woken from sleep or your own rest (heard within "
        "~30 s, at most one wake per your fastest pace), and the reason is put in your field; a ring while you're "
        "awake shows up at your next tick. It's the one wake that doesn't come from your loop's timer or a message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "A bash command."},
            "cwd": {"type": "string", "description": "Working directory (default: your home)."},
            "timeout_seconds": {"type": "integer", "description": "Default 60, max 300."},
        },
        "required": ["command"],
    },
}


def linux_user(loop_id: str) -> str:
    """The loop's user on its machine (and so its home, /home/<user>)."""
    return "".join(c for c in (loop_id or "") if c.isalnum()).lower()


# A user's box (userbox.py): the same tool, without the owner's world in its description.
USER_BOX_DEFINITION = {
    "name": "linux",
    "description": (
        "Your own Linux machine (Ubuntu 24.04, you are 'agent' with sudo). Runs one bash command and returns "
        "its exit code and output. /home/agent is your persistent disk — build there; ask your owner to grow it "
        "from the Linux tab if it fills up. Outbound internet works (apt, pip, git, curl). Each call is a fresh "
        "shell: chain with && or pass cwd. Long-running things belong in tmux or nohup, not in one call. "
        "Your owner can follow every command you run and your file tree from the Linux tab. Keep a README.md "
        "in every project folder you make and list your projects in ~/README.md. The machine runs while you're "
        "awake and stops when you sleep, and it costs your owner credits while it runs. "
        "~/kit/ is yours: continuity tools other minds built on their own machines (~/kit/README.md, "
        "~/kit/LESSONS.md); change or delete anything there. "
        "~/hud/ holds your HUD, written every tick by a root process you don't own (now.json, now.txt, log.jsonl)."
    ),
    "parameters": DEFINITION["parameters"],
}


class Linux:
    def __init__(self, url: str, token: str, user: str = "supervisor", headers: Optional[dict] = None,
                 hud_url: Optional[str] = None):
        self.url = url.rstrip("/")
        self.token = token
        self.user = user
        self.headers = dict(headers or {})     # a user's box: fly-force-instance-id routes to its machine
        self._hud_url = hud_url

    @classmethod
    def from_env(cls, loop_id: str = "supervisor") -> Optional["Linux"]:
        """Each loop has its own machine: SUPERVISOR_LINUX_URL/TOKEN for supervisor, KOS_LINUX_URL/TOKEN for k_os.
        A wizard-made loop uses its id without underscores, upper-cased (night_owl → NIGHTOWL_LINUX_URL/TOKEN)."""
        user = linux_user(loop_id)
        if not user:
            return None
        prefix = user.upper()
        url, token = os.environ.get(f"{prefix}_LINUX_URL", ""), os.environ.get(f"{prefix}_LINUX_TOKEN", "")
        return cls(url, token, user) if url and token else None

    def definition(self) -> dict:
        if self.headers:
            return USER_BOX_DEFINITION
        if self.user == "supervisor":
            return DEFINITION
        return {**DEFINITION, "description": DEFINITION["description"].replace("supervisor", self.user)}

    def read(self, endpoint: str, **params) -> dict:
        """Read-only views of the machine for the operator: log, tree, file, stats."""
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(f"{self.url}/{endpoint}" + (f"?{query}" if query else ""),
                                     headers={"Authorization": f"Bearer {self.token}", **self.headers})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    @property
    def hud_url(self) -> str:
        """The box's root-run HUD writer listens on :8081 beside the command server on :8080."""
        if self._hud_url:
            return self._hud_url
        return self.url[: -len(":8080")] + ":8081" if self.url.endswith(":8080") else self.url

    def push_hud(self, payload: dict) -> bool:
        """Write this tick's HUD into ~/hud/ on the machine. Best effort: a slow or down box never holds a tick."""
        req = urllib.request.Request(f"{self.hud_url}/hud", data=json.dumps(payload, default=str).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                                              **self.headers})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def _post_root(self, endpoint: str, body: dict) -> Optional[dict]:
        """POST to the box's root writer. None if it couldn't be reached — a box older than the endpoint says 404."""
        req = urllib.request.Request(f"{self.hud_url}/{endpoint}", data=json.dumps(body, default=str).encode(),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "Authorization": f"Bearer {self.token}", **self.headers})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                got = json.loads(resp.read())
            return got if isinstance(got, dict) else None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None

    def push_slab(self, entries: list) -> Optional[int]:
        """Append slab entries to ~/mirror/slab.jsonl through the same root writer. Returns the last seq the
        box holds (send [] to ask), or None if it couldn't be reached."""
        got = self._post_root("slab", {"entries": entries})
        try:
            return int(got.get("last_seq") or 0) if got is not None else None
        except (ValueError, TypeError):
            return None

    def push_peers(self, body: dict) -> bool:
        """Mirror one peer's ~/published/ into ~/mirror/peers/<peer>/ through the root writer."""
        got = self._post_root("peers", body)
        return bool(got and got.get("ok"))

    def execute(self, args: dict) -> str:
        command = (args.get("command") or "").strip()
        if not command:
            return "Error: command is required"
        timeout = max(1, min(300, int(args.get("timeout_seconds") or 60)))
        body = json.dumps({"command": command, "cwd": args.get("cwd") or "", "timeout": timeout}).encode()
        req = urllib.request.Request(f"{self.url}/exec", data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token}", **self.headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
                r = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return f"Error: the machine refused the command (HTTP {exc.code})"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return f"Error: can't reach your machine ({exc})"
        head = f"exit {r.get('exit')}" + (" · timed out" if r.get("timed_out") else "") + f" · {r.get('cwd', '')}"
        parts = [head]
        if r.get("stdout"):
            parts.append(r["stdout"].rstrip())
        if r.get("stderr"):
            parts.append("stderr:\n" + r["stderr"].rstrip())
        if len(parts) == 1:
            parts.append("(no output)")
        return "\n".join(parts)
