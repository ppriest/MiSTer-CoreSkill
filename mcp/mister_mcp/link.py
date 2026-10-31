"""One SSH connection to the MiSTer for the whole server, and a monitor of what it is running.

Every board command (Board.sh) runs as a channel on the same connection instead of a new plink
login each time; the connection is opened on first use and again after it drops. File copies
still go through pscp: the MiSTer serves no SFTP.

The monitor reads /tmp/RBFNAME, CORENAME and FULLPATH every POLL seconds. mister_state and the
status page read its last result, so any number of sessions asking costs the board nothing. While
the board does not answer, it retries at POLL, doubling to at most BACKOFF_MAX.

Host keys: ~/.mister/known_hosts, first one seen is kept; a changed key is refused.
"""
import logging
import threading
import time

import paramiko

from . import jobs as J
from .cores import ToolError

POLL = 10
BACKOFF_MAX = 120
CONNECT_TIMEOUT = 8
KNOWN_HOSTS = J.STATE / "known_hosts"
logging.getLogger("paramiko").setLevel(logging.WARNING)   # not a line per connect in server.log


class Link:
    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._who = None                     # (host, user, password) the client was opened with
        self.connected_at = None
        self.last_error = None

    def _open(self, host, user, pw):
        c = paramiko.SSHClient()
        KNOWN_HOSTS.parent.mkdir(parents=True, exist_ok=True)
        KNOWN_HOSTS.touch(exist_ok=True)
        c.load_host_keys(str(KNOWN_HOSTS))
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(host, username=user, password=pw, timeout=CONNECT_TIMEOUT,
                  banner_timeout=CONNECT_TIMEOUT, auth_timeout=CONNECT_TIMEOUT,
                  look_for_keys=False, allow_agent=False)
        c.get_transport().set_keepalive(30)
        c.save_host_keys(str(KNOWN_HOSTS))
        return c

    def _client_for(self, host, user, pw):
        with self._lock:
            t = self._client.get_transport() if self._client else None
            if t is None or not t.is_active() or self._who != (host, user, pw):
                self.close_locked()
                try:
                    self._client = self._open(host, user, pw)
                except paramiko.BadHostKeyException as e:
                    self.last_error = f"host key for {host} changed; refused (see {KNOWN_HOSTS})"
                    raise ToolError(self.last_error) from e
                except (OSError, paramiko.SSHException) as e:
                    self.last_error = f"cannot connect to {host}: {e}"
                    raise ToolError(self.last_error) from e
                self._who = (host, user, pw)
                self.connected_at = time.time()
                self.last_error = None
            return self._client

    def run(self, host, user, pw, command, timeout=60):
        """(returncode, stdout, stderr). One retry on a fresh connection if the old one had died."""
        for attempt in (0, 1):
            c = self._client_for(host, user, pw)
            try:
                _, out, err = c.exec_command(command, timeout=timeout)
                o = out.read().decode("utf-8", "replace")
                e = err.read().decode("utf-8", "replace")
                return out.channel.recv_exit_status(), o, e
            except TimeoutError:
                raise ToolError(f"no answer from {host} in {timeout} s")
            except (OSError, EOFError, paramiko.SSHException) as e:
                with self._lock:
                    self.close_locked()
                if attempt:
                    self.last_error = f"{host}: {e}"
                    raise ToolError(self.last_error) from e

    def close_locked(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self.connected_at = None

    def status(self):
        t = self._client.get_transport() if self._client else None
        return {"connected": bool(t and t.is_active()), "host": self._who[0] if self._who else None,
                "connected_at": _ts(self.connected_at), "error": self.last_error}


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None


LINK = Link()


class Monitor:
    """What the MiSTer is running, read every POLL seconds on the shared connection."""

    def __init__(self):
        self.state = {"rbf": None, "setname": None, "path": None}
        self.checked = None                  # time of the last successful read
        self.since = None                    # time the current core was first seen
        self.error = None
        self.changes = []                    # the last 20 cores seen: {t, rbf, setname}
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if not self._thread:
            self._thread = threading.Thread(target=self._loop, name="mister-monitor", daemon=True)
            self._thread.start()

    def poke(self):
        """Read again now (after a launch or reboot)."""
        self._wake.set()

    def read(self):
        from .board import Board              # board imports this module
        s = Board().state()
        now = time.time()
        if (s["rbf"], s["setname"]) != (self.state["rbf"], self.state["setname"]) or self.since is None:
            self.since = now
            self.changes = (self.changes + [{"t": _ts(now), "rbf": s["rbf"], "setname": s["setname"]}])[-20:]
        self.state, self.checked, self.error = s, now, None
        return s

    def _loop(self):
        wait = POLL
        while True:
            try:
                self.read()
                wait = POLL
            except Exception as e:           # the board off or unreachable: keep trying, slower
                self.error = str(e) or type(e).__name__
                wait = min(BACKOFF_MAX, wait * 2)
            self._wake.wait(wait)
            self._wake.clear()

    def snapshot(self):
        now = time.time()
        return dict(self.state, running=bool(self._thread), poll_s=POLL,
                    checked=_ts(self.checked), age_s=round(now - self.checked) if self.checked else None,
                    since=_ts(self.since), error=self.error, link=LINK.status(), changes=self.changes[::-1])


MONITOR = Monitor()
