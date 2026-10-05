"""Persistence — games, and the pre-generated puzzle pool.

A game is stored as its **move journal** plus the folded state. The journal is
the expensive-looking choice and it is the right one: undo/redo, exact resume,
"where did I go wrong", replay, and the whole learning layer all fall out of it
for a few kB per puzzle. Reconstructing any of those from a snapshot is
impossible after the fact.

Every write goes through `lunaapp.atomic_write` (temp → chmod → fsync →
os.replace): no window where a file exists half-written or unreadable.

⚠ The pool exists because generating a hard puzzle takes seconds, and seconds
spent while the player waits are seconds spent looking at a spinner. Generation
happens in a background thread that stops as soon as every bucket is full — a
filler that keeps running because "it might as well" is a CPU leak with a nice
name.
"""

import json
import os
import random
import re
import shutil
import threading
import time
import uuid

import lunaapp as la
from . import generator as gen
from .grid import parse, to_string

DATA_DIR = os.environ.get("SUDOKU_DIR", "./data")
GAMES_DIR = os.path.join(DATA_DIR, "games")
POOL_DIR = os.path.join(DATA_DIR, "pool")

#: how many ready-to-play puzzles we keep per grade
POOL_TARGET = int(os.environ.get("SUDOKU_POOL_TARGET", "12"))

_lock = threading.Lock()
_filling = threading.Event()

# --- public mode (SUDOKU_PUBLIC=1) ----------------------------------------------
#: Public mode: friends, no accounts. Every browser is a VISITOR (an opaque
#: cookie id) and its games live under GAMES_DIR/<sid>/. The pool stays SHARED.
#: ⚠ FAIL CLOSED: in public mode a game function called with no visitor bound
#: raises instead of falling back to the flat GAMES_DIR — a forgotten scope must
#: be a 500, never somebody else's games.
PUBLIC = os.environ.get("SUDOKU_PUBLIC", "") == "1"
RE_SID = re.compile(r"^[A-Za-z0-9_-]{24}$")
RE_GID = re.compile(r"^[0-9a-f]{6,16}$")
MAX_GAMES_PER_VISITOR = 30
MAX_VISITORS = 20000
VISITOR_TTL_S = 180 * 86400
#: in public mode a bucket is POPPED only while it holds more than this many; at or
#: below it, visitors share a random one of what is left. A burst of strangers must
#: never empty the pool and push generation into the request path.
PUBLIC_POOL_KEEP = 4

_ctx = threading.local()


class VisitorsFull(Exception):
    """The hard cap on visitor directories is reached: no NEW visitor may persist."""


def bind_visitor(sid):
    """Scope this thread's game functions to one visitor (None = unbind)."""
    _ctx.sid = sid if (sid and RE_SID.match(sid)) else None


def games_dir():
    if not PUBLIC:
        return GAMES_DIR
    sid = getattr(_ctx, "sid", None)
    if not sid or not RE_SID.match(sid):
        raise RuntimeError("public mode: no visitor bound to this request")
    return os.path.join(GAMES_DIR, sid)


def visitor_count():
    try:
        with os.scandir(GAMES_DIR) as it:
            return sum(1 for e in it if e.is_dir() and RE_SID.match(e.name))
    except OSError:
        return 0


def touch_visitor():
    """Mark the bound visitor as alive (its dir mtime is what pruning reads)."""
    if PUBLIC:
        try:
            os.utime(games_dir())
        except (OSError, RuntimeError):
            pass


def prune_visitors(max_age_s=None, now=None):
    """Delete visitor dirs untouched for longer than max_age_s. Returns how many."""
    if not PUBLIC:
        return 0
    max_age_s = VISITOR_TTL_S if max_age_s is None else max_age_s
    now = time.time() if now is None else now
    n = 0
    try:
        entries = list(os.scandir(GAMES_DIR))
    except OSError:
        return 0
    for e in entries:
        try:
            if (e.is_dir(follow_symlinks=False) and RE_SID.match(e.name)
                    and now - e.stat(follow_symlinks=False).st_mtime > max_age_s):
                shutil.rmtree(e.path)
                n += 1
        except OSError:
            continue
    return n


def prune_loop(interval_s=86400):
    """At startup, then once a day. Never raises: it runs beside the server."""
    while True:
        try:
            n = prune_visitors()
            if n:
                la.log(f"pruned {n} idle visitor dir(s)")
        except Exception as e:          # noqa: BLE001 — the server must outlive it
            la.log(f"prune failed: {e.__class__.__name__}: {e}")
        time.sleep(interval_s)


def start_pruner():
    threading.Thread(target=prune_loop, daemon=True, name="sudoku-pruner").start()


def ensure_dirs():
    for d in (DATA_DIR, GAMES_DIR, POOL_DIR):
        os.makedirs(d, exist_ok=True)
        try:
            os.chmod(d, 0o775)
        except OSError:
            pass


# --- the pool ------------------------------------------------------------------

def _pool_path(g):
    return os.path.join(POOL_DIR, f"{g}.jsonl")


def pool_counts():
    out = {}
    for g in range(4):
        try:
            with open(_pool_path(g)) as f:
                out[g] = sum(1 for line in f if line.strip())
        except OSError:
            out[g] = 0
    return out


def pool_push(rec):
    g = rec.get("grade")
    if g is None or not 0 <= g <= 3:
        return False
    with _lock:
        ensure_dirs()
        p = _pool_path(g)
        old = ""
        if os.path.exists(p):
            with open(p) as f:
                old = f.read()
        la.atomic_write(p, old + json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def pool_take(g):
    """Pop one puzzle of that grade, or None. Generates nothing — the caller
    decides whether to wait for a fresh one or offer something else.

    Public mode: pop only above `PUBLIC_POOL_KEEP`; at or below it, hand out a
    random one WITHOUT removing it (strangers share puzzles, the pool never runs
    dry, and the filler tops it back up in the background as before)."""
    with _lock:
        p = _pool_path(g)
        if not os.path.exists(p):
            return None
        with open(p) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        if not lines:
            return None
        if PUBLIC and len(lines) <= PUBLIC_POOL_KEEP:
            return json.loads(random.choice(lines))
        rec = json.loads(lines[0])
        la.atomic_write(p, "\n".join(lines[1:]) + ("\n" if lines[1:] else ""))
        return rec


#: set SUDOKU_POOL_FILL=0 to keep the background generator OFF — tests do, and
#: so should any process that only means to READ the store. A filler thread that
#: outlives its data directory writes into a path that no longer exists.
FILL_ENABLED = os.environ.get("SUDOKU_POOL_FILL", "1") != "0"


def fill_pool(target=None, budget_s=25):
    """Top the buckets up, then stop. Runs in a thread; never loops forever."""
    if _filling.is_set() or not FILL_ENABLED:
        return
    _filling.set()
    try:
        target = target or POOL_TARGET
        rng = random.Random()
        t0 = time.time()
        while time.time() - t0 < budget_s:
            counts = pool_counts()
            if all(counts.get(g, 0) >= target for g in range(4)):
                return
            rec = gen.make(rng)
            if rec["grade"] is not None and counts.get(rec["grade"], 0) < target:
                try:
                    pool_push(rec)
                except OSError:
                    return       # the data dir went away under us — stop, quietly
    finally:
        _filling.clear()


def fill_pool_async(**kw):
    if FILL_ENABLED and not _filling.is_set():
        threading.Thread(target=fill_pool, kwargs=kw, daemon=True).start()


# --- games ---------------------------------------------------------------------

def new_id():
    return uuid.uuid4().hex[:10]


def game_path(gid):
    """⚠ The id is validated BEFORE it touches a path: `/assistant/?g=` hands us
    a raw query string, and `../` in it must not walk out of the games dir."""
    if not isinstance(gid, str) or not RE_GID.match(gid):
        raise ValueError(f"bad game id {gid!r}")
    return os.path.join(games_dir(), f"{gid}.json")


def save_game(game):
    ensure_dirs()
    d = games_dir()
    if d != GAMES_DIR:
        os.makedirs(d, exist_ok=True)
    game["updated"] = int(time.time())
    la.atomic_write(game_path(game["id"]), json.dumps(game, ensure_ascii=False,
                                                      indent=1))
    return game


def load_game(gid):
    try:
        with open(game_path(gid)) as f:
            g = json.load(f)
    except (OSError, ValueError):
        return None
    return g if isinstance(g, dict) else None


def list_games(limit=40):
    ensure_dirs()
    d = games_dir()
    out = []
    try:
        names = os.listdir(d)
    except FileNotFoundError:
        return out                    # a visitor with no game yet has no dir yet
    for fn in names:
        if not fn.endswith(".json"):
            continue
        g = load_game(fn[:-5])
        if g:
            out.append(g)
    out.sort(key=lambda g: g.get("updated", 0), reverse=True)
    return out[:limit]


def _make_room():
    """Public mode, before a new game: refuse a NEW visitor past the hard cap, and
    keep an existing one at MAX_GAMES_PER_VISITOR − 1 so the new game fits —
    oldest FINISHED first, else oldest."""
    d = games_dir()
    if not os.path.isdir(d):
        if visitor_count() >= MAX_VISITORS:
            raise VisitorsFull()
        return
    games = list_games(limit=10**6)
    games.sort(key=lambda g: (not g.get("done"), g.get("created", 0),
                              g.get("updated", 0)))
    while len(games) >= MAX_GAMES_PER_VISITOR:
        victim = games.pop(0)
        try:
            os.unlink(game_path(victim["id"]))
        except (OSError, ValueError, KeyError):
            pass


def new_game(rec, source="pool", mode="libre", auto_pencil=None):
    """Turn a pool record (or an import) into a fresh game.

    Public mode may raise `VisitorsFull` — the caller says so, politely."""
    if auto_pencil is None:
        auto_pencil = (rec.get("grade") or 0) <= 1
    if PUBLIC:
        _make_room()
    return save_game({
        "id": new_id(),
        "created": int(time.time()),
        "puzzle": rec["puzzle"],
        "cells": rec["puzzle"],
        "grade": rec.get("grade"),
        "label": rec.get("label") or "?",
        "techniques": rec.get("techniques") or [],
        "pencil": {},          # his own marks:        {"12": mask}
        "struck": {},          # his own crossings:    {"12": mask}
        "elims": [],           # PROVEN eliminations:  [[cell, digit], ...]
        "moves": [],
        "hints": [],           # [{"at": ts, "level": n, "technique": "..."}]
        "seconds": 0,
        "done": False,
        "mode": mode,
        "auto_pencil": bool(auto_pencil),
        "source": source,
    })
