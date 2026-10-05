#!/usr/bin/env python3
"""lunaapp — the vendored micro-kit this app is built on.

Stdlib only. Each app VENDORS this file (copies it into its own repo) — no
shared install, no import-path coupling; an app pins the kit it shipped with.

What an app gets:
  Handler + run()      route table + quiet HTTP server (env PORT, LUNA_APP_HOST);
                       run() accepts handler_cls for apps with dynamic routes
  send_json/send_html  response helpers on the handler (+ redirect, read_body)
  topbar() / foot()    the standard header and page-end colophon
  parse_form()         urlencoded form body → flat dict
  esc() / Raw / render()  HTML templating that escapes by default
  http_get()           GET with TTL cache, last-good retention, and ONE log
                       line per up→down / down→up transition (never per failure)
  http_status()        up/age introspection for a fetched URL
  Poller               background fetch thread + optional ring-buffer history
  status_payload()     a small /status.json shape {summary, rev, ok}
  atomic_write()       temp → chmod → fsync → os.replace, per-file lock
  today_iso() / date_label_fr() / MONTHS_FR / WEEKDAYS_FR   one clock
                       (Europe/Paris) + French date labels
  extract_proposal() … proposal_card()
                       a propose-validate guardrail: a model PROPOSES a write
                       inside <<<KIND:target>>>…<<<END>>> markers and only a
                       human tap applies it. (Unused by the sudoku: no model
                       is anywhere near the solving loop.)
  app_version()        VERSION file + git short hash, computed once at startup
  log()                one line to stderr; transitions and errors only
"""
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = None


def log(msg):
    """One line to stderr → journald (the unit's default sink). Use sparingly:
    state transitions and errors, never per-request / per-failure traffic."""
    print(msg, file=sys.stderr, flush=True)


# --- version ------------------------------------------------------------------

def app_version(app_file):
    """Footer signature: (version, build). version='v0.1.0' from the repo's
    VERSION file; build is the running code's short git hash, or '' if git
    can't resolve it. Computed once at startup — never per-request, never crashes."""
    root = Path(app_file).resolve().parent
    try:
        num = (root / "VERSION").read_text().strip()
    except OSError:
        num = ""
    version = f"v{num}" if num else ""
    build = ""
    try:
        build = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
    except Exception:
        build = ""
    return version, build


# --- HTML templating (escape by default) ---------------------------------------

class Raw(str):
    """Marks a string as pre-built markup — esc()/render() pass it through."""


def esc(v):
    """HTML-escape anything for interpolation (Raw passes through unescaped)."""
    return v if isinstance(v, Raw) else html.escape(str(v), quote=True)


def render(template, **kw):
    """$-substitution templating (string.Template — CSS/JS braces are safe)
    with every value escaped by default; wrap trusted markup in Raw().
    A literal $ in the template (e.g. a JS regex anchor) is written $$."""
    return Template(template).substitute({k: esc(v) for k, v in kw.items()})


def topbar(title, parent_href=None, parent_label=None, home_href="/"):
    """The standard header: a HIERARCHICAL "up one level" back link plus a
    "🏠 Home" chip. Returns a `<header class="topbar">…</header>` string.

      • The `‹ …` link always goes UP EXACTLY ONE LEVEL in the app's own hierarchy,
        NOT wherever the browser came from — predictable, and it never depends on a
        Referer sniff that loses typed form data on the way back.
      • `parent_href=None` marks a TOP-LEVEL page: the up link renders `‹ Home`
        → home_href and the separate chip is suppressed (one control, not two).
      • On a deeper page, pass the parent one step up: `parent_href="<url>"`,
        `parent_label="Month"` → the up link is `‹ Month` and a `🏠 Home` chip is
        added on the right so home is always one tap away.

    Pure: builds a string, no I/O. hrefs are emitted verbatim (path-absolute "/"
    or app-relative "../" — never an absolute host, so the app works both on its
    own port and behind a reverse proxy)."""
    top_level = parent_href is None or parent_href == home_href
    if parent_href is None:
        up_href, up_label = home_href, "Home"
    else:
        up_href, up_label = parent_href, (parent_label or "Back")
    back = f'<a class="back" href="{esc(up_href)}">‹ {esc(up_label)}</a>'
    chip = "" if top_level else f'<a class="home" href="{esc(home_href)}">🏠 Home</a>'
    return f'<header class="topbar">{back}<h1>{esc(title)}</h1>{chip}</header>'

def foot(home_href="/"):
    """The standard page-end colophon: ONE way home, and nothing else — no version
    string (a version is a dev artefact in a shipped page).

    ⚠ Emit it as a **DIRECT CHILD of `.page`**: that is what the kit's
    `.page > footer` styles. Pure: builds a string, no I/O."""
    return (f'<footer><a class="home" href="{esc(home_href)}">'
            f'\u2039 Home</a></footer>')


# --- HTTP fetch: TTL cache + last-good + transition logging ---------------------

_http_cache = {}
_http_lock = threading.Lock()


def http_get(url, timeout=4, ttl=0, text=False):
    """GET url → parsed JSON (or stripped text with text=True). TTL-cached
    (ttl=0 always refetches); on failure returns the LAST GOOD value — None
    only if there never was one. Journals exactly one line per up→down and
    down→up transition per URL, never one per failing request."""
    now = time.time()
    with _http_lock:
        c = _http_cache.setdefault(url, {"good": None, "good_t": 0.0, "up": None})
        if ttl and c["up"] and now - c["good_t"] < ttl:
            return c["good"]
    err = None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read()
        val = raw.decode().strip() if text else json.loads(raw)
    except Exception as e:
        val, err = None, e
    with _http_lock:
        if err is None:
            if c["up"] is False:
                log(f"upstream up again: {url}")
            c.update(good=val, good_t=now, up=True)
            return val
        if c["up"] is not False:  # None (first ever) or True → announce the drop
            log(f"upstream DOWN: {url} ({err.__class__.__name__}: {err})")
        c["up"] = False
        return c["good"]


def http_status(url):
    """{'up': True/False/None, 'age': seconds since last good fetch or None}
    for a URL previously passed to http_get. up=None → never attempted."""
    with _http_lock:
        c = _http_cache.get(url)
        if not c:
            return {"up": None, "age": None}
        return {"up": c["up"],
                "age": (time.time() - c["good_t"]) if c["good_t"] else None}


# --- background poller -----------------------------------------------------------

class Poller:
    """Calls fn() every `interval` seconds in a daemon thread so requests never
    wait on the network. Keeps the last non-None result (.value), when it landed
    (.updated / .age), whether the LAST run succeeded (.ok), and — with
    history=N — a ring buffer of the last N results (.history) for sparklines."""

    def __init__(self, fn, interval=10, history=0):
        self.fn, self.interval = fn, interval
        self.value, self.updated, self.ok = None, None, False
        self.history = deque(maxlen=history) if history else None
        self._thread = None

    def poll_once(self):
        try:
            v = self.fn()
        except Exception as e:
            log(f"poller error: {e.__class__.__name__}: {e}")
            v = None
        if v is not None:
            self.value, self.updated, self.ok = v, time.time(), True
            if self.history is not None:
                self.history.append(v)
        else:
            self.ok = False
        return v

    def start(self):
        def loop():
            while True:
                self.poll_once()
                time.sleep(self.interval)
        self._thread = threading.Thread(target=loop, daemon=True, name="lunaapp-poller")
        self._thread.start()
        return self

    @property
    def age(self):
        """Seconds since the last successful poll, or None if never."""
        return None if self.updated is None else time.time() - self.updated


# --- the standard status contract -------------------------------------------------

_last_rev = [0]  # keep-last-rev state (per process; reset only by restart)


def status_payload(summary, rev=None, ok=True):
    """A small status contract: {summary, rev, ok}. KEEP-LAST-REV: a falsy rev
    (failure) reuses the last known one, so an upstream hiccup never flaps it."""
    if rev:
        _last_rev[0] = int(rev)
    return {"summary": summary, "rev": _last_rev[0], "ok": bool(ok)}


# --- atomic file writes -------------------------------------------------------------

_file_locks = {}
_file_locks_guard = threading.Lock()


def _lock_for(path):
    with _file_locks_guard:
        return _file_locks.setdefault(str(path), threading.Lock())


def atomic_write(path, data, mode=0o664):
    """Whole-file write that can never leave a torn/empty file: temp file in the
    same dir → chmod (BEFORE replace: mkstemp's 0600 would otherwise be the
    file's final mode) → fsync → os.replace. A per-file threading.Lock
    serializes concurrent writers in this process (ThreadingHTTPServer)."""
    path = Path(path)
    if isinstance(data, str):
        data = data.encode()
    with _lock_for(path):
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fchmod(f.fileno(), mode)
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# --- one clock: dates (Europe/Paris) + French labels ---------------------------------

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
WEEKDAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def now_paris():
    return datetime.now(PARIS) if PARIS else datetime.now()


def today_iso():
    return now_paris().strftime("%Y-%m-%d")


def date_label_fr(date):
    """'2026-07-02' → 'jeu. 2 juillet' (falls back to the raw string)."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        return f"{WEEKDAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month - 1]}"
    except (ValueError, TypeError):
        return date


# --- propose-validate guardrail --------------------------------------------------------
# The house pattern for LLM-suggested writes: the model emits
#   <<<KIND:target>>> …content… <<<END>>>
# the app extracts it into a proposal {kind, target, md}, PERSISTS it (so a page
# reload never loses it), renders proposal_card() with a Sauver button, and only
# the human tap routes it through apply_proposal() + the app's per-kind
# validators. The LLM never writes a file itself.

PROPOSAL_RE = re.compile(r"<<<([A-Z]+):([^>\n]+)>>>\s*(.*?)\s*<<<END>>>", re.S)


def extract_proposal(text, kinds):
    """Pull the first recognized proposal block out of an LLM reply.

    kinds: {MARKER: (kind_name, normalize_fn|None)} — normalize_fn(target)
    returns the cleaned target, or None/'' to reject the block (an invalid
    target means "not a proposal", the block stays in the text).
    Returns (proposal|None, cleaned_text)."""
    for m in PROPOSAL_RE.finditer(text):
        entry = kinds.get(m.group(1))
        if not entry:
            continue
        kind, normalize = entry
        target = m.group(2).strip()
        if normalize:
            target = normalize(target)
            if not target:
                continue
        prop = {"kind": kind, "target": target, "md": m.group(3).strip()}
        cleaned = (text[:m.start()] + text[m.end():]).strip()
        return prop, cleaned
    return None, text


def save_proposal(path, prop):
    """Persist the pending proposal (atomic) so it survives reloads/restarts."""
    atomic_write(path, json.dumps(prop, ensure_ascii=False))


def load_proposal(path):
    """The pending proposal, or None. Corrupt/missing file → None (never raises)."""
    try:
        prop = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(prop, dict) and all(k in prop for k in ("kind", "target", "md")):
        return prop
    return None


def clear_proposal(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def apply_proposal(prop, handlers):
    """Dispatch a HUMAN-approved proposal to the app's per-kind validator/writer.
    handlers: {kind: fn(target, md) -> confirmation_str}. Raises on unknown kind;
    validators raise on bad content — the caller turns that into a chat message."""
    fn = handlers.get(prop.get("kind"))
    if fn is None:
        raise ValueError(f"kind de proposition inconnu: {prop.get('kind')!r}")
    return fn(prop["target"], prop["md"])


def proposal_card(prop, what, save_action="save", dismiss_action="dismiss"):
    """The pending-proposal card: content preview + Sauver / Ignorer. The forms
    carry NO payload — the server applies/clears the PERSISTED proposal, so the
    card is stateless and safe to re-render on every page load until resolved."""
    return f"""
  <div class="turn proposal">
    <div class="who">🤖 Proposition à enregistrer — {esc(what)} ({esc(prop['target'])})</div>
    <pre>{esc(prop['md'])}</pre>
    <div class="row">
      <form method="post" action="{esc(save_action)}"><button type="submit">💾 Sauver</button></form>
      <form method="post" action="{esc(dismiss_action)}"><button class="ghost" type="submit">✕ Ignorer</button></form>
    </div>
  </div>"""


# --- HTTP server: route table + quiet entrypoint -------------------------------------

class Handler(BaseHTTPRequestHandler):
    """Route-table handler. `routes` maps path → zero-arg callable returning:
    dict → JSON 200 · str → HTML 200 · (code, dict|str) → that status code.
    Write-capable apps subclass this and add do_POST."""
    routes = {}

    def send_body(self, code, body, ctype, extra=None):
        """`extra`: additional response headers ({name: value}). Three apps had
        forked this method for exactly that — a Cache-Control, a nosniff, a
        Content-Disposition — so it belongs here rather than in three copies."""
        b = body if isinstance(body, (bytes, bytearray)) else body.encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client went away mid-response — not an app error, keep journald quiet

    def send_json(self, obj, code=200):
        self.send_body(code, json.dumps(obj), "application/json")

    def send_html(self, s, code=200):
        self.send_body(code, s, "text/html; charset=utf-8")

    def redirect(self, loc, code=303):
        """303 See Other — the POST-redirect-GET pattern (refresh never re-posts).

        `Content-Length: 0` is not decoration: today every app in the fleet serves
        HTTP/1.0 (the BaseHTTPRequestHandler default), where the connection closes
        after each response and its absence is harmless — but the day someone sets
        `protocol_version = "HTTP/1.1"`, a redirect with neither Content-Length nor
        Transfer-Encoding leaves the client waiting for a body that never comes.
        Four apps had already added it by hand; one line here retires the trap."""
        try:
            self.send_response(code)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client went away — same reason send_body swallows it

    def read_body(self, max_bytes=None):
        """The request body; None (after a 413) if it exceeds max_bytes.
        A malformed/negative Content-Length reads as an empty body."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        if max_bytes and n > max_bytes:
            self.send_body(413, "payload too large", "text/plain")
            return None
        return self.rfile.read(n) if n > 0 else b""

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        fn = self.routes.get(path)
        if fn is None:
            return self.send_body(404, "not found", "text/plain")
        try:
            r = fn()
        except Exception as e:
            log(f"500 on {path}: {e.__class__.__name__}: {e}")
            return self.send_body(500, "internal error", "text/plain")
        code = 200
        if isinstance(r, tuple):
            code, r = r
        if isinstance(r, dict):
            self.send_json(r, code)
        else:
            self.send_html(r, code)

    def log_message(self, *a):  # quiet — journald gets transitions, not traffic
        pass


def parse_form(body):
    """application/x-www-form-urlencoded body → {key: first_value}."""
    d = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {k: v[0] for k, v in d.items()}


def run(name, routes, default_port=8771, handler_cls=None):
    """Entrypoint: bind $LUNA_APP_HOST (default 127.0.0.1) on $PORT and serve
    forever. Loopback by default: put a reverse proxy in front.
    handler_cls: a Handler subclass for apps with dynamic routes / POST."""
    port = int(os.environ.get("PORT") or default_port)
    handler = type("RouteHandler", (handler_cls or Handler,),
                   {"routes": dict(routes)})
    # Loopback by default; LUNA_APP_HOST binds another address (0.0.0.0 in a container).
    host = os.environ.get("LUNA_APP_HOST", "127.0.0.1")
    print(f"{name} on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), handler).serve_forever()
