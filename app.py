#!/usr/bin/env python3
"""Sudoku. The board, and the assistant that explains it.

All the logic lives in `sudoku/` (engine, techniques, generator, store); this
file is the web surface and nothing else. Two rules it keeps:

⚠ **No solving happens in the browser.** The JS moves digits around and draws;
every deduction, every hint, every verdict is computed in Python by the engine.
That is what makes the assistant trustworthy — and it means a hint can never be
read out of the page source by a curious viewer.

⚠ **The solution never crosses the wire**, except where the user explicitly asks
"where did I go wrong" (and then only the position of the first slip, not the
digit). The whole app exists so the player derives the grid.
"""

import json
import os
import re
import secrets
import time

import lunaapp as la
from sudoku import drills, engine, examples, fiches, generator, grid as G, store
from sudoku import techniques as T
from sudoku.solver import solution, solve_count

VERSION = la.app_version(__file__)
APP_TITLE = "Sudoku"
#: what the header BAR says — the app's emoji and its name.
APP_BAR = "🔢 Sudoku"

# ---------------------------------------------------------------- page shell

PAGE = """<!doctype html>
<html lang="fr" class="nojs"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>$title</title>
<script>document.documentElement.className='js';</script>
<link rel="stylesheet" href="/static/luna-ui.css">
<style>
/* App-BESPOKE only — tokens, .page, .topbar, .card, .btn come from luna-ui.css */
.page { flex:1 0 auto; }
.muted { color:var(--faint); }
.small { font-size:var(--fs-2); }
.row { display:flex; gap:var(--sp-2); flex-wrap:wrap; align-items:center; }
.spread { display:flex; justify-content:space-between; align-items:baseline; gap:var(--sp-2); }
/* ⚠ la ligne de titre d'une partie colle au plateau sans ça — elle est un `div` nu,
   pas une carte, donc rien ne lui donne d'air (Rogzy 29/09 : « add spacing »). */
.gamehd { margin-bottom:var(--sp-3); }

/* --- the board ------------------------------------------------------------
   The grid is the one element allowed to break the sheet's rhythm: it must be
   SQUARE and as big as the narrow screen allows, because a sudoku you squint
   at is a sudoku you misread. Everything else on the page bends around it. */
.boardwrap { position:relative; width:100%; max-width:min(92vw, 520px); margin:0 auto; }
.board { position:relative; display:grid; grid-template-columns:repeat(9,1fr);
         aspect-ratio:1/1; border:2.5px solid var(--ink); border-radius:4px;
         background:var(--card); touch-action:manipulation; }
.cell { position:relative; display:flex; align-items:center; justify-content:center;
        border:1px solid var(--line); font-size:clamp(1rem,5.2vw,1.7rem);
        line-height:1; cursor:pointer; user-select:none; -webkit-tap-highlight-color:transparent; }
/* The 3×3 walls. A sudoku whose boxes you have to squint for is a sudoku you
   misread — these stay heavier than anything else on the page. */
.cell:nth-child(9n+4),.cell:nth-child(9n+7) { border-left:2.5px solid var(--ink); }
.cell.r3,.cell.r6 { border-top:2.5px solid var(--ink); }
.cell.given { font-weight:700; background:var(--sunk); }
.cell.user { color:var(--good); }
.cell.sel { background:#e8e2cf; }
.cell.peer { background:#f4f1e6; }
.cell.same { background:#e2ebdd; }
.cell.sel.same, .cell.sel.peer { background:#e8e2cf; }
.cell.wrong { color:var(--bad); }
.cell.hl { background:#fdf0c8; box-shadow:inset 0 0 0 2px var(--alert); z-index:2; }
.cell.tgt { background:#fadedb; box-shadow:inset 0 0 0 2px var(--bad); z-index:2; }
.cell.audit { box-shadow:inset 0 0 0 2px var(--alert); }
.pm { display:grid; grid-template-columns:repeat(3,1fr); grid-template-rows:repeat(3,1fr);
      width:100%; height:100%; font-size:clamp(.42rem,2.0vw,.62rem); color:var(--faint);
      line-height:1; }
.pm span { display:flex; align-items:center; justify-content:center; }
.pm .mine { color:var(--ink); font-weight:600; }
.pm .cut { text-decoration:line-through; opacity:.45; }
.links { position:absolute; inset:0; pointer-events:none; z-index:3; }
.links line { stroke:var(--alert); stroke-width:.06; stroke-dasharray:.18 .12; }
/* --- the grid you TYPE into -----------------------------------------------
   The player never hands over an 81-character string: they type the digits where they
   sit. Same geometry and the same heavy 3×3 walls as the board you read, because
   it is the same object — one you fill, one you look at. The boxes are real
   inputs in a real form, so this works with scripting off; `ENTRY_JS` only adds
   the convenience of moving on by itself. */
.cell.ent { display:block; box-sizing:border-box; width:100%; height:100%;
            padding:0; margin:0; text-align:center; font-family:var(--font);
            font-size:clamp(1rem,5.2vw,1.7rem); font-weight:700; line-height:1;
            color:var(--ink); background:var(--card); border-radius:0;
            cursor:text; -webkit-appearance:none; appearance:none;
            min-width:0; min-height:0; }
.cell.ent:focus { outline:none; background:#e8e2cf; z-index:2;
                  box-shadow:inset 0 0 0 2px var(--ink); }
/* ⚠ explicit ROWS, measured not assumed: an <input> brings an intrinsic height
   (44px here) that beats `aspect-ratio:1/1`, and the board rendered 324×400 —
   oblong bands, unequal boxes. The board you only READ gets away without this
   because a div holding nothing is short. */
.entry .board { touch-action:auto; grid-template-rows:repeat(9,1fr); }
details.paste, details.fix { margin-top:var(--sp-3); }
/* ⚠ 44, not 36: a <summary> is a tap target like any other and the kit's layout check
   measures it at 390 (it caught this one at 324×36). `display:flex` is what makes
   min-height bind at all — on the default `display:list-item` the height is a
   suggestion, which is the fleet's oldest dead-tap-target bug. */
details.paste > summary, details.fix > summary { cursor:pointer; color:var(--faint);
        font-size:var(--fs-1); min-height:44px; display:flex; align-items:center; }
details.fix > summary { color:var(--ink); }
/* --- the fiche's worked examples: the SAME board, drawn by the server ------
   No state, no script: a fiche is a page you read, and a board that needs JS to
   appear is a board that is blank the one time it matters. `.mini` only shrinks
   it — every class below (.given/.hl/.tgt/.pm/.cut) is the live board's. */
.mini { max-width:min(88vw, 330px); margin:0 auto; }   /* centré quand il est seul sur sa ligne (Rogzy 05/10 : collé à gauche dès 412 px) */
.mini .cell { cursor:default; font-size:clamp(.8rem,3.6vw,1.05rem); }
.mini .pm { font-size:clamp(.34rem,1.5vw,.46rem); }
.cell.plc { background:#dff0dd; box-shadow:inset 0 0 0 2px var(--good); z-index:2;
            color:var(--good); font-weight:700; }
/* --- the drill board -------------------------------------------------------
   A fiche's picture pencils ONLY the digits its argument talks about, because
   nine numbers per cell is a picture of nothing. An exercise is the opposite
   claim: all nine are in, because deciding which digits matter IS the exercise,
   and a board that pre-filters them has already done the looking. So it takes
   the live board's full width and the live board's pencil size — at `.mini`'s
   .34rem, nine candidates are a grey smudge. */
.drill { max-width:min(92vw, 520px); margin:0 auto; }
.drill .cell { cursor:default; font-size:clamp(1rem,5.2vw,1.7rem); }
.drill .pm { font-size:clamp(.42rem,2.0vw,.62rem); }
/* ⚠ Une GRILLE, pas un `flex-wrap`. Rogzy 2026-09-29 : *« idem sur le spacing du
   bouton et les 20 choix ici, et en desktop ça rend mal »*. En `flex-wrap` les 20
   pastilles tombaient 6/6/6/2 à 390 px et **16/4** à 1440 : une dernière rangée
   orpheline, différente à chaque largeur. 5 colonnes puis 10 divisent 20 exactement,
   donc les rangées sont toujours pleines — c'est le nombre d'exercices qui choisit la
   grille, pas la place disponible.
   ⚠ `margin-top` ici : les pastilles collaient au bouton ▶ Commencer. */
.exos { display:grid; grid-template-columns:repeat(5,1fr); gap:var(--sp-2);
        margin-top:var(--sp-4); }
@media (min-width:640px){ .exos { grid-template-columns:repeat(10,1fr); } }
.exos a { display:inline-flex; align-items:center; justify-content:center;
          min-width:44px; min-height:44px; padding:0 .4rem; border-radius:var(--radius);
          border:1.5px solid var(--line); text-decoration:none; color:var(--ink);
          background:var(--card); font-size:var(--fs-1); }
.exos a.on { border-color:var(--ink); background:var(--ink); color:var(--paper);
             font-weight:700; }
.drillnav { display:flex; justify-content:space-between; align-items:center;
            gap:var(--sp-2); margin:var(--sp-4) 0; }   /* bas aussi : la carte des exercices la touchait (Rogzy 05/10) */
.exwrap { display:flex; gap:var(--sp-4); flex-wrap:wrap; align-items:flex-start; justify-content:center; }
.exwrap .expl { flex:1 1 15rem; min-width:0; }
@media (max-width:639px){ .exwrap { margin-top:var(--sp-3); } }   /* « Exemple N » collé à la grille sur téléphone (Rogzy 05/10) */
.exnum { font-weight:700; color:var(--faint); font-size:var(--fs-1);
         text-transform:uppercase; letter-spacing:.05em; }
.legend { display:flex; gap:var(--sp-3); flex-wrap:wrap; margin-top:var(--sp-2);
          font-size:var(--fs-1); color:var(--faint); }
.legend b { display:inline-block; width:.8rem; height:.8rem; border-radius:2px;
            vertical-align:-1px; margin-right:.25rem; }
.legend .k1 b { background:#fdf0c8; box-shadow:inset 0 0 0 2px var(--alert); }
.legend .k2 b { background:#fadedb; box-shadow:inset 0 0 0 2px var(--bad); }
.legend .k3 b { background:#dff0dd; box-shadow:inset 0 0 0 2px var(--good); }
.tlist a { display:flex; justify-content:space-between; gap:var(--sp-3);
           padding:.55rem .1rem; border-bottom:1px solid var(--line);
           text-decoration:none; color:var(--ink); min-height:44px;
           align-items:center; }
.tlist a:last-child { border-bottom:none; }
.tlist a:hover { background:var(--sunk); }
.fiche-sec { margin-top:var(--sp-3); }
.fiche-sec h4 { font-size:var(--fs-2); margin:0 0 .2rem; }
.fiche-sec p { margin:0; }
.fiche-sec.trap { border-left:3px solid var(--bad); padding-left:.6rem; }
/* the assistant's list of available moves — one card each, name → fiche */
.move { background:var(--card); border:1.5px solid var(--line);
        border-radius:var(--radius); padding:.6rem .8rem; margin-bottom:.5rem; }
.move.picked { border-color:var(--alert); box-shadow:inset 0 0 0 1px var(--alert); }
.movehd { display:flex; justify-content:space-between; align-items:baseline;
          gap:var(--sp-3); margin-bottom:.2rem; }
.movehd a { font-weight:700; color:var(--ink); }
.moveacts { display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.4rem; }
.chips { display:flex; flex-wrap:wrap; gap:.4rem; }
.chip { display:inline-flex; align-items:center; min-height:36px; padding:.2rem .7rem;
        border:1.5px solid var(--line); border-radius:999px; text-decoration:none;
        color:var(--ink); background:var(--card); font-size:var(--fs-1); }
.chip:hover { border-color:var(--ink); }
textarea { width:100%; box-sizing:border-box; font:inherit; font-family:ui-monospace,
           SFMono-Regular, Menlo, monospace; font-size:var(--fs-1); padding:.5rem;
           color:var(--ink); background:var(--card); border:1.5px solid var(--line);
           border-radius:var(--radius); }
textarea:focus { outline:none; border-color:var(--ink); }

/* --- the pad -------------------------------------------------------------- */
.pad { display:grid; grid-template-columns:repeat(5,1fr); gap:var(--sp-2);
       max-width:min(92vw,520px); margin:var(--sp-4) auto 0; }
.key { min-height:52px; border:1.5px solid var(--ink); border-radius:var(--radius);
       background:var(--card); font-family:var(--font); font-size:var(--fs-4);
       cursor:pointer; display:flex; flex-direction:column; align-items:center;
       justify-content:center; gap:1px; }
.key .left { font-size:var(--fs-1); color:var(--faint); }
.key.done { opacity:.35; }
.modes { display:flex; gap:var(--sp-2); max-width:min(92vw,520px);
         margin:var(--sp-3) auto 0; }
.modes .key { flex:1; font-size:var(--fs-2); min-height:46px; padding:0 var(--sp-1); }
.key.on { background:var(--ink); color:var(--card); }
.key.on .left { color:var(--card); }

.tools { display:flex; gap:var(--sp-2); flex-wrap:wrap; margin-top:var(--sp-4);
         justify-content:center; }
.ladder { margin-top:var(--sp-4); }
.step { border-left:3px solid var(--alert); padding:var(--sp-2) var(--sp-3);
        background:var(--sunk); border-radius:0 var(--radius) var(--radius) 0;
        margin-bottom:var(--sp-2); }
.step b { display:block; font-size:var(--fs-2); color:var(--faint);
          text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }
textarea { width:100%; font-family:var(--font); font-size:var(--fs-2); padding:var(--sp-2);
           border:1.5px solid var(--line); border-radius:var(--radius);
           background:var(--card); color:var(--ink); }
.gamelist a { display:flex; justify-content:space-between; gap:var(--sp-2);
              padding:var(--sp-3); border:1.5px solid var(--line);
              border-radius:var(--radius); text-decoration:none; color:var(--ink);
              margin-bottom:var(--sp-2); }
/* ⚠ DEUX colonnes à toutes les largeurs. Rogzy 2026-09-29 : *« pour l'UX de jouer, met
   les 4 choix en 2 colonnes »*. Il y avait une bascule à 4 colonnes ≥ 1024 px : sur son
   écran les quatre difficultés s'alignaient en une bande de boutons étroits, alors que
   c'est un choix à quatre options qu'on lit en carré. La grille reste 2×2 partout. */
.grades { display:grid; grid-template-columns:repeat(2,1fr); gap:var(--sp-2); }
.grade-btn { padding:var(--sp-3); border:1.5px solid var(--ink); border-radius:var(--radius);
             background:var(--card); text-align:center; text-decoration:none; color:var(--ink); }
.grade-btn .n { display:block; font-size:var(--fs-1); color:var(--faint); }
.grade-btn.empty { border-color:var(--line); color:var(--faint); }
$extra
</style>
</head><body>
<div class="page">
$topbar
$body
$foot
</div>
</body></html>
"""


#: The in-app nav: the four things this app does. Hrefs are relative to the APP
#: ROOT and get `base` prepended per page, because a proxy may strip a `/sudoku`
#: prefix and an absolute href would escape the app.
#: ⚠ Plus d'onglet « Importer » depuis la v0.8.0. Rogzy 2026-09-29 :
#: *« assemble jouer et importé »*. Ce n'était pas une destination mais une SOURCE
#: D'ENTRÉE : les quatre difficultés et la grille tapée produisent la même chose,
#: une partie. Un onglet par formulaire, c'est une nav qui décrit le code.
TABS = [("", "▶ Jouer", "jouer"),
        ("techniques/", "📖 Techniques", "techniques"),
        ("assistant/", "🤝 Assistant", "assistant")]


def chrome(active, base=""):
    """The SAME header on every page: `‹ Home`, the app's name, the tab strip.

    Rogzy, 2026-09-15: *"right now it's confusing how it navigate"*. It was: the
    assistant, the fiches and the verifier lived in a card at the BOTTOM of the
    home page, so every tool was two taps and a scroll away from every other, and
    a deep page (a grid, a fiche) swapped in its own second-level header — a
    different title, a different back link, and no way to reach a sibling tool
    without going home first.

    So the header never changes and never moves: one bar, one `‹ Home`, four tabs.
    A page's OWN name (the grid's label, the technique) is a heading in the body,
    where it belongs.

    ⚠ `base` is "" at the app root, "../" one level down, and the tabs are the
    reason it must be right: a wrong base is a nav strip that 404s from exactly
    one page. `TestRoutes` resolves every tab from the URL each page is SERVED
    at — which is not the same as the URL it is linked from. A fiche lives at
    `/techniques/x_wing` with NO trailing slash, so `../` there means `/`, not
    `/techniques/`; that is precisely the bug this replaced (the fiche's back
    link read "‹ Les techniques" and went home, and the test missed it by
    resolving against `/techniques/` instead).
    """
    # public mode: no `‹ Home` up-link — there is nothing above this app
    top = (f'<header class="topbar"><h1>{la.esc(APP_BAR)}</h1></header>'
           if store.PUBLIC else la.topbar(APP_BAR))
    out = [top, '<nav class="tabs" aria-label="Sections">']
    for href, label, key in TABS:
        on = key == active
        out.append(f'<a class="tab{" active" if on else ""}" '
                   f'href="{la.esc((base + href) or "./")}"'
                   f'{" aria-current=page" if on else ""}>{label}</a>')
    out.append("</nav>")
    return "".join(out)


def page(title, body, extra="", active="jouer", base=""):
    # one choke point for the auto-advance: attaching it per board would bind
    # the same input twice on a page that shows two, and every keystroke would
    # jump two cells
    if 'class="boardwrap entry"' in body:
        body += f"<script>{ENTRY_JS}</script>"
    if store.PUBLIC:
        return la.render(PUBLIC_PAGE, title=title if "Sudoku" in title
                         else f"{title} · Sudoku", extra=la.Raw(extra),
                         topbar=la.Raw(chrome(active, base)),
                         body=la.Raw(body), foot=la.Raw(PUBLIC_FOOT))
    return la.render(PAGE, title=f"{title} · Sudoku", extra=la.Raw(extra),
                     topbar=la.Raw(chrome(active, base)),
                     body=la.Raw(body), foot=la.Raw(la.foot()))


#: Public mode: the same shell minus what only makes sense on a single-user
#: install — CSS comments stripped, and no `‹ Home` footer (there is no home above).
PUBLIC_PAGE = re.sub(r"/\*.*?\*/", "", PAGE, flags=re.S)
# Crédits sur toute page publique : qui l'a fait, où le code vit, la licence.
PUBLIC_FOOT = ('<footer class="credits"><span class="muted small">Sans compte : tes parties restent '
               'liées à ce navigateur.</span><br><span class="muted small">Créé par '
               '<a href="https://rogzy.org/">Rogzy</a> &amp; Luna · '
               '<a href="https://github.com/Rogzy-DB/sudoku">GitHub</a> · © 2026 Rogzy · '
               '<a href="https://opensource.org/license/mit">licence MIT</a></span></footer>')


# ---------------------------------------------------------------- home

def grades_html(counts, action, back=""):
    """Les quatre difficultés. UN seul rendu, parce qu'elles vivent maintenant à
    deux endroits : sous le plateau (changer de grille) et sur la page de repli
    quand le réservoir est vide. ⚠ `action` est relatif à la page qui affiche le
    formulaire — c'est la seule différence entre les deux, et c'est justement ce
    qui laisse une redirection en arrière quand on déménage un formulaire.

    ⚠ Deux colonnes à toutes les largeurs (Rogzy 29/09) : `.grades` ne bascule
    plus à quatre au-delà de 1024 px."""
    out = ['<div class="grades">']
    for g in range(4):
        n = counts.get(g, 0)
        cls = "grade-btn" + ("" if n else " empty")
        out.append(f'<form method="post" action="{la.esc(action)}" style="margin:0">'
                   f'<input type="hidden" name="back" value="{la.esc(back)}">'
                   f'<input type="hidden" name="grade" value="{g}">'
                   f'<button class="{cls}" style="width:100%" type="submit">'
                   f'{la.esc(engine.GRADE_LABELS[g])}'
                   f'<span class="n">{n} prête{"s" if n > 1 else ""}</span></button></form>')
    out.append("</div>")
    return "".join(out)


def current_game():
    """La partie que ▶ Jouer doit ouvrir, ou None si le réservoir est vide.

    Rogzy 2026-09-29 : *« jouer on voit une grille très difficile par défaut, avec
    les 4 options »*. Donc `/` ne demande plus rien, il **ouvre un plateau**.

    ⚠ Reprendre la dernière partie non terminée EST le chemin de reprise : la
    v0.7.0 a retiré la LISTE des parties traînantes, pas les parties. Sans ça,
    chaque passage sur l'onglet créerait une partie de plus — un compteur qui
    monte tout seul à chaque rechargement.
    ⚠ À froid on sert du **Diabolique**, et on descend seulement si ce seau est
    vide : c'est ce qu'il joue, les quatre boutons servent à changer d'avis, pas
    à poser la question à chaque fois."""
    store.ensure_dirs()
    store.fill_pool_async()
    store.touch_visitor()
    for g in store.list_games(12):
        if not g.get("done"):
            return g
    for grade in (3, 2, 1, 0):
        rec = store.pool_take(grade)
        if rec:
            return store.new_game(rec)
    return None


def empty_pool_page():
    """Le repli : aucun réservoir, aucune partie. On ne redirige pas dans le vide.

    ⚠ Cette page existe pour un état réel (premier démarrage, réservoir vidé), pas
    pour la décoration : `/` redirige vers un plateau **sauf** ici, et un redirect
    vers une partie qui n'existe pas serait une boucle."""
    counts = store.pool_counts()
    out = ['<section class="card"><div class="section-head"><h3>Nouvelle grille</h3>'
           '</div>', grades_html(counts, "new"),
           '<p class="muted small">Le réservoir se remplit en tâche de fond — '
           'reviens dans une minute. Une grille est notée par la technique la plus '
           'dure qu\'elle exige, mesurée, jamais choisie.</p></section>']
    return page("🔢 Sudoku", "".join(out), active="jouer")


def _ago(ts):
    if not ts:
        return ""
    d = int(time.time()) - ts
    if d < 3600:
        return f"il y a {d // 60} min"
    if d < 86400:
        return f"il y a {d // 3600} h"
    return f"il y a {d // 86400} j"


def _mmss(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


# ---------------------------------------------------------------- the board

BOARD_JS = r"""
const S = JSON.parse(document.getElementById('state').textContent);
const board = document.getElementById('board');
const links = document.getElementById('links');
let sel = null, mode = 'digit', hintLevel = 0, hintData = null, audit = null;
let cells = S.cells.split('').map(c => c === '.' ? 0 : +c);
const given = S.puzzle.split('').map(c => c !== '.');
let pencil = S.pencil || {}, struck = S.struck || {};

/* Peer table — the browser only ever needs "who constrains whom" to draw the
   naive candidates. It never solves: every deduction comes from the server. */
const PEERS = [];
for (let i = 0; i < 81; i++) {
  const r = i / 9 | 0, c = i % 9, b = (r / 3 | 0) * 3 + (c / 3 | 0), s = new Set();
  for (let k = 0; k < 9; k++) { s.add(r * 9 + k); s.add(k * 9 + c); }
  for (let x = 0; x < 9; x++) s.add(((b / 3 | 0) * 3 + (x / 3 | 0)) * 9 + (b % 3) * 3 + x % 3);
  s.delete(i); PEERS.push([...s]);
}
function autoCand(i) {
  if (cells[i]) return 0;
  let m = 0x1FF;
  for (const j of PEERS[i]) if (cells[j]) m &= ~(1 << (cells[j] - 1));
  return m & ~(struck[i] || 0);
}
const bitsOf = m => { const o = []; for (let d = 1; d <= 9; d++) if (m >> (d - 1) & 1) o.push(d); return o; };

function render() {
  board.querySelectorAll('.cell').forEach((el, i) => {
    el.className = 'cell' + (given[i] ? ' given' : cells[i] ? ' user' : '')
      + ((i / 9 | 0) === 3 ? ' r3' : '') + ((i / 9 | 0) === 6 ? ' r6' : '');
    if (sel !== null) {
      if (i === sel) el.classList.add('sel');
      else if (PEERS[sel].includes(i)) el.classList.add('peer');
      if (cells[sel] && cells[i] === cells[sel]) el.classList.add('same');
    }
    if (hintData) {
      if ((hintData.cells || []).includes(i)) el.classList.add('hl');
      if ((hintData.targets || []).some(t => t[0] === i)) el.classList.add('tgt');
    }
    if (audit && audit.cells.includes(i)) el.classList.add('audit');
    if (S.bad && S.bad.includes(i)) el.classList.add('wrong');
    if (cells[i]) { el.textContent = cells[i]; return; }
    const auto = S.auto_pencil ? autoCand(i) : 0;
    const mine = pencil[i] || 0, cut = struck[i] || 0;
    const show = auto | mine | cut;
    if (!show) { el.textContent = ''; return; }
    let h = '<div class="pm">';
    for (let d = 1; d <= 9; d++) {
      const b = 1 << (d - 1);
      h += '<span class="' + ((mine & b) ? 'mine ' : '') + ((cut & b) ? 'cut' : '') + '">'
        + ((show & b) ? d : '') + '</span>';
    }
    el.innerHTML = h + '</div>';
  });
  drawLinks();
}
function drawLinks() {
  links.innerHTML = '';
  if (!hintData || !hintData.links) return;
  for (const [a, b] of hintData.links.map(l => [l[0], l[1]])) {
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    ln.setAttribute('x1', (a % 9) + .5); ln.setAttribute('y1', (a / 9 | 0) + .5);
    ln.setAttribute('x2', (b % 9) + .5); ln.setAttribute('y2', (b / 9 | 0) + .5);
    links.appendChild(ln);
  }
}
function setMode(m) {
  mode = m;
  document.querySelectorAll('[data-mode]').forEach(b =>
    b.classList.toggle('on', b.dataset.mode === m));
}
function put(d) {
  if (sel === null) return;
  const i = sel;
  if (given[i]) return;
  if (mode === 'digit') { cells[i] = (cells[i] === d ? 0 : d); pencil[i] = 0; }
  else if (mode === 'pencil') { if (cells[i]) return; pencil[i] = (pencil[i] || 0) ^ (1 << (d - 1)); }
  else { if (cells[i]) return; struck[i] = (struck[i] || 0) ^ (1 << (d - 1)); }
  hintData = null; audit = null; ladder(); render(); save();
}
function erase() {
  if (sel === null || given[sel]) return;
  cells[sel] = 0; pencil[sel] = 0; struck[sel] = 0;
  hintData = null; render(); save();
}
let timer = null;
function save() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const r = await fetch('state', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cells: cells.map(c => c || '.').join(''), pencil, struck,
                             auto_pencil: S.auto_pencil })
    }).then(r => r.json()).catch(() => null);
    if (!r) return;
    S.bad = r.bad || null;
    if (r.done) location.reload();
    render();
  }, 250);
}
board.addEventListener('click', e => {
  const el = e.target.closest('.cell'); if (!el) return;
  sel = +el.dataset.i; render();
});
document.addEventListener('keydown', e => {
  /* ⚠ INPUT autant que TEXTAREA. Depuis la v0.8.0 le plateau porte aussi la
     saisie d'une grille (« Changer de grille ») : sans cette ligne, taper un 7
     dans une case de saisie le POSE sur la partie en cours et le preventDefault
     empêche la case de le recevoir — deux bugs d'un coup, invisibles tant que le
     formulaire vivait sur sa propre page. */
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  if (e.key >= '1' && e.key <= '9') { put(+e.key); e.preventDefault(); }
  else if (e.key === 'Backspace' || e.key === 'Delete') { erase(); e.preventDefault(); }
  else if (e.key === ' ') { setMode(mode === 'digit' ? 'pencil' : 'digit'); e.preventDefault(); }
  else if (sel !== null && e.key.startsWith('Arrow')) {
    const d = { ArrowUp: -9, ArrowDown: 9, ArrowLeft: -1, ArrowRight: 1 }[e.key];
    const n = sel + d; if (n >= 0 && n < 81) { sel = n; render(); } e.preventDefault();
  }
});

/* ---- the hint ladder: one rung per tap, and the server decides what a rung says */
const rungs = document.getElementById('rungs');
async function hint() {
  hintLevel++;
  const r = await fetch('hint?level=' + hintLevel).then(r => r.json());
  if (r.none) { rungs.innerHTML = '<div class="step">' + r.message + '</div>'; return; }
  hintData = r.show || null;
  ladder(r);
  render();
}
function ladder(r) {
  if (!r) { if (hintLevel === 0) rungs.innerHTML = ''; return; }
  const h = (r.rungs || []).map(x =>
    '<div class="step"><b>' + x[0] + '</b>' + x[1] + '</div>').join('');
  rungs.innerHTML = h + (r.can_apply
    ? '<button class="btn" onclick="applyHint()">Appliquer ce pas</button>'
    : (hintLevel < 4 ? '<button class="btn" onclick="hint()">Encore un cran</button>' : ''));
}
async function applyHint() {
  const r = await fetch('apply-hint', { method: 'POST' }).then(r => r.json());
  if (r.cells) { cells = r.cells.split('').map(c => c === '.' ? 0 : +c); }
  hintLevel = 0; hintData = null; rungs.innerHTML = '';
  if (r.done) return location.reload();
  render();
}
async function doAudit() {
  const r = await fetch('audit').then(r => r.json());
  audit = r; render();
  rungs.innerHTML = '<div class="step"><b>Audit du crayon</b>' + r.message + '</div>'
    + (r.more ? '<button class="btn" onclick="auditMore()">Précise</button>' : '');
  auditStage = 0;
}
let auditStage = 0;
async function auditMore() {
  auditStage++;
  const r = await fetch('audit?level=' + auditStage).then(r => r.json());
  audit = r; render();
  rungs.innerHTML = '<div class="step"><b>Audit du crayon</b>' + r.message + '</div>'
    + (r.more ? '<button class="btn" onclick="auditMore()">Précise</button>' : '');
}
async function whereWrong() {
  const r = await fetch('check').then(r => r.json());
  rungs.innerHTML = '<div class="step"><b>Où ça a dérapé</b>' + r.message + '</div>'
    + (r.cell !== null && r.cell !== undefined
      ? '<button class="btn" onclick="rewind(' + r.cell + ')">Effacer cette case</button>' : '');
  if (r.cell !== null && r.cell !== undefined) { sel = r.cell; }
  render();
}
function rewind(i) { sel = i; cells[i] = 0; pencil[i] = 0; struck[i] = 0; render(); save(); }
function toggleAuto() {
  S.auto_pencil = !S.auto_pencil;
  document.getElementById('autobtn').textContent =
    (S.auto_pencil ? '👁 candidats auto : ON' : '👁 candidats auto : OFF');
  render(); save();
}
setMode('digit');
toggleAuto(); toggleAuto();   /* paint the label from the stored setting */
render();
setInterval(() => fetch('tick', { method: 'POST' }).catch(() => {}), 30000);
"""


def board_page(game):
    gid = game["id"]
    cells = G.parse(game["cells"])
    sol = solution(G.parse(game["puzzle"]))
    bad = ([i for i in range(81) if cells[i] and sol and sol[i] != cells[i]]
           if game.get("mode") == "strict" else None)
    state = {"id": gid, "puzzle": game["puzzle"], "cells": game["cells"],
             "pencil": {int(k): v for k, v in (game.get("pencil") or {}).items()},
             "struck": {int(k): v for k, v in (game.get("struck") or {}).items()},
             "auto_pencil": game.get("auto_pencil", True), "bad": bad}

    grid_html = "".join(f'<div class="cell" data-i="{i}"></div>' for i in range(81))
    left = {d: 9 - sum(1 for v in cells if v == d) for d in range(1, 10)}
    keys = "".join(
        f'<button class="key{" done" if left[d] <= 0 else ""}" onclick="put({d})">{d}'
        f'<span class="left">{max(left[d], 0)}</span></button>' for d in range(1, 10))

    done = game.get("done")
    # ⚠ Plus d'horloge dans l'en-tête. Rogzy 2026-09-29 : *« what is the 10:00 ? is it a
    # back timer ? remove this »* — et la question dit le bug : ce n'était pas un compte à
    # rebours mais le temps de jeu écoulé, **rendu une seule fois au chargement**. Une
    # horloge figée qui ressemble à une horloge vivante est pire qu'aucune horloge.
    # Le décompte continue en coulisse (`tick`), il ne ressort qu'à la fin : « bouclée
    # en X », qui est un RÉSULTAT, pas un cadran.
    head = (f'<div class="spread gamehd"><span><b>{la.esc(game["label"])}</b> '
            f'<span class="muted small">{len(game.get("hints", []))} indice(s)</span>'
            f'</span></div>')

    body = [head,
            '<div class="boardwrap"><div class="board" id="board">', grid_html,
            '<svg class="links" id="links" viewBox="0 0 9 9" preserveAspectRatio="none">'
            '</svg></div></div>']
    if done:
        body.append('<section class="card"><div class="section-head"><h3>Terminée ✅</h3>'
                    '</div><p class="muted">Grille bouclée en '
                    f'{_mmss(game.get("seconds", 0))} avec '
                    f'{len(game.get("hints", []))} indice(s).</p></section>')
    else:
        body.append('<div class="modes">'
                    '<button class="key" data-mode="digit" onclick="setMode(\'digit\')">'
                    '🔢 chiffre</button>'
                    '<button class="key" data-mode="pencil" onclick="setMode(\'pencil\')">'
                    '✏️ crayon</button>'
                    '<button class="key" data-mode="strike" onclick="setMode(\'strike\')">'
                    '✂️ barrer</button></div>')
        body.append(f'<div class="pad">{keys}'
                    '<button class="key" onclick="erase()">⌫</button></div>')
        body.append('<div class="tools">'
                    '<button class="btn" onclick="hint()">💡 Un indice</button>'
                    '<button class="btn" onclick="doAudit()">🔍 Vérifie mes petits chiffres</button>'
                    '<button class="btn" onclick="whereWrong()">🧭 Où ai-je dérapé ?</button>'
                    '<button class="btn" id="autobtn" onclick="toggleAuto()"></button>'
                    f'<a class="btn" href="../../assistant/?g={la.esc(gid)}">'
                    '🤝 Tous les coups jouables</a>'
                    '</div>')
    body.append('<div class="ladder" id="rungs"></div>')
    # ⚠ « Tous les coups jouables » est un LIEN, pas un panneau de plus sur le
    # plateau. Rogzy 2026-09-29 : *« si je suis bloqué faudra bien me débloquer avec
    # l'assistant »*. Deux aides distinctes : 💡 donne UN cran à la fois, l'assistant
    # étale tout ce qui est jouable. Les fondre perdrait le premier.
    # ⚠ Et l'assistant reste une page rendue par le SERVEUR : le descendre dans ce
    # plateau le mettrait derrière le JS, donc hors d'usage sur une liseuse.
    body.append(_change_grid_html())
    body.append(f'<script id="state" type="application/json">{json.dumps(state)}</script>')
    body.append(f"<script>{BOARD_JS}</script>")
    return page(f"{game['label']}", "".join(body), active="jouer", base="../../")


def _change_grid_html():
    """« Changer de grille » : les quatre difficultés et la grille tapée, repliées
    sous le plateau.

    Rogzy 2026-09-29 : *« assemble jouer et importé. de façon plus simple »*. Importer
    n'était pas une destination, c'était une source d'entrée — le réservoir et la
    saisie produisent la même chose, une partie. Les deux vivent donc au même endroit,
    et le plateau reste le premier écran : choisir est l'exception, pas le péage.

    ⚠ Les deux formulaires portent `back=../../` : ils sont postés depuis `/g/<id>/`.
    """
    counts = store.pool_counts()
    head = ('<details class="fix"><summary>🔄 Changer de grille</summary>'
            '<section class="card"><div class="section-head">'
            '<h3>Une autre du réservoir</h3></div>'
            + grades_html(counts, "../../new", back="../../")
            + '</section>')
    if store.PUBLIC:
        # pas de saisie en mode public : `/import` y est fermé (il note n'importe
        # quelle grille tapée — du calcul offert à n'importe qui)
        return head + '</details>'
    return (head +
            '<section class="card"><div class="section-head">'
            '<h3>📥 Ou tape la tienne</h3></div>'
            '<p class="muted small">Le journal, l\'autre app, la feuille. '
            'Je vérifie qu\'elle est valide et unique avant que tu y passes '
            'deux heures.</p>'
            '<form method="post" action="../../import">'
            '<input type="hidden" name="back" value="../../">'
            + entry_board(None) +
            '<div class="tools"><button class="btn" type="submit">Charger</button>'
            '</div></form></section></details>')


# ---------------------------------------------------------------- the assistant

def _elims(game):
    return [tuple(e) for e in (game.get("elims") or [])]


def hint_payload(game, level):
    """One rung of the ladder. The server decides what each rung reveals — the
    browser never holds the step it hasn't earned yet."""
    cells = G.parse(game["cells"])
    if all(cells):
        return {"none": True, "message": "La grille est pleine."}
    st = engine.next_step(cells, _elims(game))
    if st is None:
        return {"none": True, "message":
                "Je ne vois aucun pas avec les techniques que je connais "
                "(les chaînes ne sont pas encore implémentées). Je préfère te le "
                "dire que te sortir une devinette."}
    level = max(1, min(4, int(level or 1)))
    rungs = []
    if level >= 1:
        where = G.unit_name_fr(st["unit"]) if st["unit"] is not None else \
            "quelque part dans la grille"
        rungs.append(["1 · Où", f"Il y a quelque chose dans {where}."])
    if level >= 2:
        rungs.append(["2 · Quoi", f"{la.esc(st['label_fr'])} "
                      f"<span class='muted small'>(palier {st['tier']} — "
                      f"{T.TIER_LABELS[st['tier']]})</span>"])
    if level >= 3:
        rungs.append(["3 · Le motif",
                      "Les cases en jaune : " +
                      ", ".join(G.name(i) for i in st["cells"]) +
                      ("" if not st["links"] else
                       " · lien fort sur " + str(st["links"][0][2]))])
    if level >= 4:
        concl = st["why_fr"]
        if st["placements"]:
            concl += " → " + ", ".join(f"{G.name(i)} = {d}" for i, d in st["placements"])
        elif st["targets"]:
            concl += " → " + ", ".join(f"{G.name(i)} perd le {d}"
                                       for i, d in st["targets"])
        rungs.append(["4 · La conclusion", la.esc(concl)])
    show = {"cells": st["cells"], "links": st["links"],
            "targets": st["targets"]} if level >= 3 else None
    return {"rungs": rungs, "show": show, "can_apply": level >= 4,
            "technique": st["technique"], "tier": st["tier"]}


def apply_hint(game):
    cells = G.parse(game["cells"])
    st = engine.next_step(cells, _elims(game))
    if st is None:
        return {"ok": False}
    for i, d in st["placements"]:
        cells[i] = d
    elims = _elims(game)
    for i, d in st["targets"]:
        if (i, d) not in elims:
            elims.append((i, d))
    game["cells"] = G.to_string(cells)
    game["elims"] = [list(e) for e in elims]
    game["hints"].append({"at": int(time.time()), "level": 4,
                          "technique": st["technique"], "tier": st["tier"],
                          "applied": True})
    game["done"] = _check_done(game, cells)
    store.save_game(game)
    return {"ok": True, "cells": game["cells"], "done": game["done"]}


def audit_payload(game, level):
    """The pencil audit, one notch at a time. A spurious mark is named before a
    missing one — it is the one that sends you down a wrong path."""
    cells = G.parse(game["cells"])
    pencil = {int(k): v for k, v in (game.get("pencil") or {}).items()}
    if not any(pencil.values()):
        return {"message": "Tu n'as pas encore posé de petits chiffres à la main.",
                "cells": [], "more": False}
    a = engine.audit_pencil(cells, pencil, _elims(game))
    level = int(level or 0)
    if a["total"] == 0:
        return {"message": "Aucun écart. Tes candidats sont justes.",
                "cells": [], "more": False}
    if level == 0:
        return {"message": f"{a['total']} écart(s).", "cells": [], "more": True}
    if level == 1:
        return {"message": f"{len(a['missing'])} oubli(s), "
                           f"{len(a['spurious'])} en trop."
                           + (" Le « en trop » est le plus dangereux : c'est un "
                              "chiffre impossible que tu crois encore possible."
                              if a["spurious"] else ""),
                "cells": [], "more": True}
    if level == 2:
        return {"message": "Regarde " + ", ".join(a["units"][:4]) + ".",
                "cells": [], "more": True}
    return {"message": "Les cases surlignées : "
                       + ", ".join(G.name(i) for i in a["cells"]),
            "cells": a["cells"], "more": False}


def check_payload(game):
    """Where did it go wrong — the FIRST slip in move order, never the digit.

    Returning the position and not the value is the whole discipline: the app
    tells him *that* he turned left too early, not what the right turn was.
    """
    cells = G.parse(game["cells"])
    sol = solution(G.parse(game["puzzle"]))
    if sol is None:
        return {"message": "Cette grille n'a pas de solution unique — je ne peux "
                           "rien affirmer.", "cell": None}
    wrong = [i for i in range(81) if cells[i] and sol[i] != cells[i]]
    if not wrong:
        return {"message": "Rien de faux pour l'instant. Tout ce que tu as posé "
                           "est juste.", "cell": None}
    order = {}
    for n, mv in enumerate(game.get("moves") or []):
        order.setdefault(mv["i"], n)
    first = min(wrong, key=lambda i: order.get(i, 10 ** 6))
    since = len(game.get("moves") or []) - order.get(first, 0)
    extra = (f" Elle traîne depuis {since} coups." if since > 1 else "")
    return {"message": f"Le premier faux pas est {G.name(first)}."
                       + extra + f" ({len(wrong)} case(s) fausse(s) en tout.)",
            "cell": first}


def _check_done(game, cells):
    if not all(cells):
        return False
    sol = solution(G.parse(game["puzzle"]))
    return sol is not None and cells == sol


# ---------------------------------------------------------------- (le juge, retiré)
# ⚠ Plus d'onglet « 🕵️ Vérifier » depuis la v0.9.0. Plus personne ne
# s'en servait. Sa prémisse était « un autre solveur t'a servi un indice » — elle a
# disparu le jour où cette app est née. La PAGE part ; le moteur `engine.verify_claim`
# et l'action `/act verify_claim` restent : un agent peut encore faire juger une
# réclamation par le moteur, à coût d'interface nul.
# ⚠ `_md()` est parti avec elle : il n'avait qu'un seul appelant. Une page supprimée
# qui laisse ses helpers derrière n'est pas supprimée, elle est cachée.
# ---------------------------------------------------------------- techniques

#: which tier a technique belongs to, read off the catalogue itself rather than
#: retyped — a second hand-written list is a second thing to forget to update.
TIER_OF = {}
for _tier, _fn in T.CATALOGUE:
    TIER_OF[getattr(_fn, "__name__", "").replace("find_", "")] = _tier
for _k, _t in (("naked_pair", 1), ("naked_triple", 1), ("naked_quad", 1),
               ("hidden_pair", 1), ("hidden_triple", 1), ("hidden_quad", 1),
               ("x_wing", 2), ("swordfish", 2), ("jellyfish", 2)):
    TIER_OF[_k] = _t


#: Which digits an example board draws in the empty cells. A board showing all
#: nine candidates shows nothing — these are the digits the argument is about.
#: For a single-digit technique that is the digit itself, drawn across the whole
#: grid so you can SEE that it has only two places in a line. For the others the
#: story is the cells' own candidate sets, so those get drawn instead.
SINGLE_DIGIT = {"hidden_single", "pointing", "claiming", "x_wing", "swordfish",
                "jellyfish", "skyscraper", "two_string_kite", "simple_colouring"}


def example_digits(cand, st):
    ds = {d for _, d in st["targets"]} | {d for _, d in st["placements"]}
    if st["technique"] in SINGLE_DIGIT:
        return ds
    for i in st["cells"]:
        ds |= set(G.bits(cand[i]))
    return ds


# ------------------------------------------------------- the grid you TYPE in

#: Rogzy 2026-09-15: *« ofc on ne colle pas une grille mais on rentre les chiffres
#: sur une grille… je ne vais jamais te donner les 1231564, toujours taper les
#: chiffres »*. He is right, and it was never a detail: every surface that asked
#: for 81 characters was asking him to be a serialiser. The 81-char string stays
#: as the MACHINE's spelling — it is what travels between two steps in a hidden
#: field, and what another solver prints — so it survives folded away in a paste
#: box, never as the thing he is handed first.
ENTRY_JS = """
(function(){
  var boards = document.querySelectorAll('.entry .board');
  for (var b = 0; b < boards.length; b++) (function(board){
    var cs = board.querySelectorAll('input.ent');
    function go(i){ if (i >= 0 && i < cs.length) { cs[i].focus(); cs[i].select(); } }
    for (var i = 0; i < cs.length; i++) (function(el, i){
      el.addEventListener('focus', function(){ el.select(); });
      el.addEventListener('input', function(){
        var v = el.value.replace(/[^1-9]/g, '').slice(-1);
        el.value = v;
        if (v) go(i + 1);
      });
      el.addEventListener('keydown', function(e){
        var k = e.key;
        if (k === 'ArrowRight') { e.preventDefault(); go(i + 1); }
        else if (k === 'ArrowLeft') { e.preventDefault(); go(i - 1); }
        else if (k === 'ArrowDown') { e.preventDefault(); go(i + 9); }
        else if (k === 'ArrowUp') { e.preventDefault(); go(i - 9); }
        else if (k === 'Backspace' && !el.value) { e.preventDefault(); go(i - 1); }
        else if (k === '0' || k === '.' || k === ' ') {
          e.preventDefault(); el.value = ''; go(i + 1);
        }
      });
      // an 81-char string pasted into any box fills the whole board — the one
      // case where text still arrives, handled here instead of asking for it
      el.addEventListener('paste', function(e){
        var t = (e.clipboardData || window.clipboardData).getData('text') || '';
        var kept = t.replace(/[^0-9._*-]/g, '');
        if (kept.length !== 81) return;
        e.preventDefault();
        for (var j = 0; j < 81; j++) {
          var ch = kept.charAt(j);
          cs[j].value = (ch >= '1' && ch <= '9') ? ch : '';
        }
        go(80);
      });
    })(cs[i], i);
  })(boards[b]);
})();
"""


def entry_board(cells=None):
    """Nine rows of boxes you type the digits into — how a position gets in.

    Deliberately the same geometry, the same heavy box walls and the same class
    names as the board you read: the app has ONE grid, sometimes editable. Every
    box is a real `<input>` in a real form and tab walks them, so a browser with
    scripting off loses only the auto-advance."""
    out = []
    for i in range(81):
        cls = ["cell", "ent"]
        if i // 9 in (3, 6):
            cls.append(f"r{i // 9}")
        v = cells[i] if cells else 0
        out.append(f'<input class="{" ".join(cls)}" name="c{i}" type="text" '
                   f'inputmode="numeric" autocomplete="off" spellcheck="false" '
                   f'maxlength="1" aria-label="{G.name(i)}" '
                   f'value="{v if v else ""}">')
    return f'<div class="boardwrap entry"><div class="board">{"".join(out)}</div></div>'


def cells_from_form(f, fallback="cells"):
    """The 81 typed boxes → a grid string. Returns (text, complaint).

    Falls back to `fallback` when no box was posted at all — that is the hidden
    field carrying the position from one step to the next, and the paste box.

    A box holding something that is not a digit is NAMED, never dropped: an
    ignored cell is a DIFFERENT puzzle, solved confidently — the same failure
    `G.parse` refuses a short string for."""
    keys = [f"c{i}" for i in range(81)]
    if not any(k in f for k in keys):
        return f.get(fallback, ""), ""
    out, bad = [], []
    for i, k in enumerate(keys):
        v = (f.get(k, "") or "").strip()
        if not v or v in ("0", "."):
            out.append(".")
        elif len(v) == 1 and v in "123456789":
            out.append(v)
        else:
            bad.append(G.name(i))
            out.append(".")
    if bad:
        return "".join(out), ("je n'ai pas lu un chiffre de 1 à 9 en "
                              + ", ".join(bad) + " — corrige et relance")
    return "".join(out), ""


def static_board(cells, cand, st=None, digits=None, klass="mini"):
    """A position rendered by the SERVER — no state, no script.

    Reuses the live board's classes so a fiche, an assistant and a hint look like
    the same object: `.hl` is the pattern, `.tgt` what it removes, `.plc` what it
    places. `digits` is the set pencilled into the empty cells (None = all nine);
    a victim's digit is struck through in place, which is the whole point of the
    picture. A board that needs JS to appear is a board that is blank the one time
    it matters."""
    if digits is None:
        digits = set(range(1, 10))
    st = st or {"cells": (), "targets": (), "placements": (), "links": ()}
    pattern = set(st["cells"])
    victims = {}
    for i, d in st["targets"]:
        victims.setdefault(i, set()).add(d)
    placed = dict(st["placements"])

    out = []
    for i in range(81):
        cls = ["cell"]
        if i // 9 in (3, 6):
            cls.append(f"r{i // 9}")
        if cells[i]:
            cls.append("given")
            inner = str(cells[i])
        elif i in placed:
            cls.append("plc")
            inner = str(placed[i])
        else:
            marks = []
            for d in range(1, 10):
                if d in digits and cand[i] & G.bit(d):
                    cut = " cut" if d in victims.get(i, ()) else ""
                    marks.append(f'<span class="mine{cut}">{d}</span>')
                else:
                    marks.append("<span></span>")
            inner = f'<div class="pm">{"".join(marks)}</div>'
        if i in pattern:
            cls.append("hl")
        if i in victims:
            cls.append("tgt")
        out.append(f'<div class="{" ".join(cls)}">{inner}</div>')

    lines = "".join(
        f'<line x1="{a % 9 + 0.5}" y1="{a // 9 + 0.5}" '
        f'x2="{b % 9 + 0.5}" y2="{b // 9 + 0.5}"/>'
        for a, b, *_ in st.get("links", []))
    svg = ('<svg class="links" viewBox="0 0 9 9" preserveAspectRatio="none">'
           f'{lines}</svg>') if lines else ""
    return (f'<div class="boardwrap {klass}"><div class="board">'
            f'{"".join(out)}{svg}</div></div>')


def mini_board(cells, st):
    """The fiche's picture: the same board, showing only the digits the argument
    is about — nine columns of candidates is a picture of nothing."""
    cand = G.candidates(cells)
    return static_board(cells, cand, st, example_digits(cand, st))


def _example_step(gridtext, key):
    """The step this example is FOR, re-derived from the position every time.

    The bank on disk stores a grid and nothing else, so the picture, the sentence
    and the eliminations can never drift from what the engine says today — the
    price is that a grid whose technique stopped firing must fail loudly, which is
    what `tests/test_fiches.py` is for."""
    cells = G.parse(gridtext)
    for st in engine.all_steps(cells):
        if st["technique"] == key:
            return cells, st
    return cells, None


def _what_fr(st):
    """What a step DOES, in words — what it places, what it removes.

    Three surfaces say this now (a fiche's example, the assistant's move list, a
    drill's answer) and they must say it identically: the same step described two
    ways reads as two different steps."""
    out = []
    if st["placements"]:
        out.append("pose " + ", ".join(f"{G.name(i)} = {d}"
                                       for i, d in st["placements"]))
    if st["targets"]:
        out.append("retire " + ", ".join(f"{d} de {G.name(i)}"
                                         for i, d in sorted(st["targets"])))
    return out


def _legend(st):
    """The three colours, named — and only the ones the picture actually uses."""
    parts = ['<span class="k1"><b></b>le motif</span>']
    if st["targets"]:
        parts.append('<span class="k2"><b></b>ce qui tombe</span>')
    if st["placements"]:
        parts.append('<span class="k3"><b></b>ce qui se pose</span>')
    return f'<div class="legend">{"".join(parts)}</div>'


def _would_play(cells, key):
    """The technique the engine would reach for FIRST here, or None when that is
    `key` itself. Computed, never claimed.

    It matters twice. On a fiche it is the honest label on an example: a
    jellyfish essentially never turns up with nothing simpler on the table, and
    that is a fact about the solver, not about the grid. On a drill it is the
    honest answer to *"why didn't I see it?"* — sometimes because a naked single
    was shouting louder, which is worth being told once you have looked, and a
    hint if you are told before."""
    first = next(engine.all_steps(cells), None)
    if first is None or first["technique"] == key:
        return None
    return T.LABELS_FR.get(first["technique"], "?")


def _fiche_example(gridtext, key, n):
    cells, st = _example_step(gridtext, key)
    if st is None:
        return ""
    # Stated, not assumed: most examples are positions where this IS the move the
    # engine would play, but a jellyfish or a chain of remote pairs essentially
    # never turns up with nothing simpler on the table — that is a fact about the
    # solver, not the grid. Computed here so the label can never be wrong.
    other = _would_play(cells, key)
    if other is None:
        prov = "👉 Ici, c'est exactement le pas que le moteur jouerait."
    else:
        prov = (f"Ici le moteur commencerait par {other} : "
                "le motif est bien là, tu le sortiras quand les coups simples "
                "seront épuisés. C'est comme ça qu'il arrive en vrai.")
    what = _what_fr(st)
    return (f'<section class="card"><div class="section-head">'
            f'<h3><span class="exnum">Exemple {n}</span></h3></div>'
            f'<div class="exwrap">{mini_board(cells, st)}'
            f'<div class="expl"><p>{la.esc(st["why_fr"])}</p>'
            f'<p class="muted small">Le moteur {la.esc(" et ".join(what))}.</p>'
            f'<p class="muted small">{la.esc(prov)}</p>'
            f'{_legend(st)}</div></div></section>')


def fiche_page(key):
    """One technique, one page: what it is, why it holds, how to spot it, the
    trap — then the exercises, then 2 to 5 worked positions.

    The exercises sit ABOVE the worked examples on purpose. Rogzy asked for them
    as part of the explanation, and four boards' worth of scrolling is not part
    of an explanation you reach; read the rule, go practise, and the worked
    examples are underneath when you want them spelled out."""
    if key not in T.LABELS_FR:
        return None
    f = fiches.FICHES.get(key, {})
    tier = TIER_OF.get(key, 1)
    out = [f'<section class="card"><div class="section-head">'
           f'<h3>{la.esc(T.LABELS_FR[key])}</h3>'
           f'<span class="muted small">palier {tier} · {la.esc(T.TIER_LABELS[tier])}'
           f'</span></div>'
           f'<p class="muted small">{la.esc(key)}</p>'
           f'<div class="fiche-sec"><h4>Ce que c\'est</h4>'
           f'<p>{la.esc(f.get("quoi", ""))}</p></div>'
           f'<div class="fiche-sec"><h4>Pourquoi ça marche</h4>'
           f'<p>{la.esc(f.get("pourquoi", ""))}</p></div>'
           f'<div class="fiche-sec"><h4>Comment le repérer</h4>'
           f'<p>{la.esc(f.get("reperer", ""))}</p></div>']
    if f.get("piege"):
        out.append(f'<div class="fiche-sec trap"><h4>Le piège</h4>'
                   f'<p>{la.esc(f["piege"])}</p></div>')
    out.append("</section>")
    out.append(_training_card(key))

    shown = 0
    for gridtext in examples.EXAMPLES.get(key, []):
        html = _fiche_example(gridtext, key, shown + 1)
        if html:
            out.append(html)
            shown += 1
    if not shown:
        out.append('<section class="card"><p class="muted small">Pas encore '
                   'd\'exemple pour celle-ci.</p></section>')
    # (Rogzy 2026-10-05 : la note « Positions réelles, sorties du générateur… » sous les
    #  exemples est RETIRÉE — pas de notice sur une surface qu'on lit pour jouer.)
    return page(T.LABELS_FR[key], "".join(out),
                active="techniques", base="../")


# ------------------------------------------------------------------- drills

def drill_count(key):
    """How many exercises this technique really has. DERIVED, never claimed:
    BUG+1 is rare enough that the harvester comes back short, and a fiche that
    promises 20 and holds 8 is a fiche that lies about something checkable."""
    return len(drills.DRILLS.get(key, ()))


def _training_card(key):
    """The fiche's way in: start, or jump to any exercise."""
    total = drill_count(key)
    if not total:
        return ('<section class="card"><div class="section-head">'
                "<h3>S'entraîner</h3></div><p class=\"muted small\">Pas encore "
                "d'exercices pour celle-ci.</p></section>")
    chips = "".join(f'<a href="../entrainement/{la.esc(key)}/{i}">{i}</a>'
                    for i in range(1, total + 1))
    return (f'<section class="card"><div class="section-head">'
            f"<h3>S'entraîner</h3>"
            f'<span class="muted small">{total} exercice{"s" if total > 1 else ""}'
            f'</span></div>'
            f'<p class="muted small">Des positions réelles, tous les petits '
            f'chiffres déjà posés. Tu cherches le motif ; la réponse ne vient '
            f'que si tu la demandes.</p>'
            f'<div class="tools"><a class="btn" '
            f'href="../entrainement/{la.esc(key)}/1">▶ Commencer</a></div>'
            f'<div class="exos">{chips}</div></section>')


def drill_page(key, n, reveal=False):
    """One practice position: the grid with every candidate already pencilled in,
    and the answer only when he asks for it.

    Rogzy, 2026-09-15: *"i'd like for the explanation to have also practice
    exercice. like pre load 20 of each with basically the crayon (small number)
    already in"* — and on what the exercise then does, asked directly:
    *"bah il me propose la solution si je demande"*. So: no score, no grading,
    nothing to submit. He looks; the button hands over the step when he wants it.

    Server-rendered end to end, like the fiches and for the same two reasons: a
    page you think in front of should not go blank because a script failed, and
    this one gets read on e-ink readers.

    ⚠ The bank stores a bare position and NOTHING else. The step, the highlight,
    the struck-through victims and the French sentence are all re-derived here,
    so an exercise can never teach something the engine has stopped saying — the
    price is that a position whose technique no longer fires must fail LOUDLY
    (`tests/test_drills.py` is meant to catch it long before he does)."""
    bank = drills.DRILLS.get(key, ())
    if key not in T.LABELS_FR or not 1 <= n <= len(bank):
        return None
    total = len(bank)
    label, tier = T.LABELS_FR[key], TIER_OF.get(key, 1)
    cells, st = _example_step(bank[n - 1], key)

    head = (f'<section class="card"><div class="section-head">'
            f'<h3><a href="../../techniques/{la.esc(key)}">{la.esc(label)}</a></h3>'
            f'<span class="muted small">exercice {n} / {total} · palier {tier}'
            f'</span></div>')
    if st is None:
        return page(f"{label} · exercice {n}",
                    head + '<p class="bad">⚠ Le moteur ne trouve plus cette '
                    "technique dans cette position : l'exercice est cassé, pas "
                    "toi. Il faut relancer le moissonneur d'exercices."
                    "</p></section>",
                    active="techniques", base="../../")

    out = [head,
           '<p class="muted small">Tous les petits chiffres sont posés — à toi '
           'de voir lesquels comptent. Quand tu veux la réponse, demande-la.'
           '</p></section>']
    # every candidate, always: which digits matter IS the exercise, so the board
    # shows the nine whether the answer is out or not. Revealing only adds the
    # highlight, the struck victims and the words.
    out.append(static_board(cells, G.candidates(cells),
                            st if reveal else None, klass="drill"))

    prev_ = (f'<a class="btn ghost" href="{n - 1}">‹ {n - 1}</a>'
             if n > 1 else '<span class="muted small"></span>')
    next_ = (f'<a class="btn ghost" href="{n + 1}">{n + 1} ›</a>'
             if n < total else '<span class="muted small"></span>')
    mid = (f'<a class="btn ghost" href="{n}">↩ Recacher</a>' if reveal
           else f'<a class="btn" href="{n}?voir=1">👁 Montre-moi</a>')
    out.append(f'<div class="drillnav">{prev_}{mid}{next_}</div>')

    if reveal:
        other = _would_play(cells, key)
        why = ("" if other is None else
               f'<p class="muted small">Si tu ne l\'as pas vu : le moteur, lui, '
               f'aurait commencé par {la.esc(other)}. Le motif est bien là — il '
               f'ne criait juste pas le plus fort.</p>')
        out.append(f'<section class="card"><div class="section-head">'
                   f'<h3>La réponse</h3></div>'
                   f'<p>{la.esc(st["why_fr"])}</p>'
                   f'<p class="muted small">Le moteur '
                   f'{la.esc(" et ".join(_what_fr(st)))}.</p>'
                   f'{why}{_legend(st)}'
                   f'<div class="tools" style="margin-top:var(--sp-3)">'
                   f'<a class="btn ghost" href="../../techniques/{la.esc(key)}">'
                   f'📖 Revoir la règle</a></div></section>')

    chips = "".join(f'<a href="{i}"{" class=\"on\"" if i == n else ""}>{i}</a>'
                    for i in range(1, total + 1))
    out.append(f'<section class="card"><div class="section-head">'
               f'<h3>Les {total} exercices</h3></div>'
               f'<div class="exos">{chips}</div></section>')
    return page(f"{label} · exercice {n}", "".join(out),
                active="techniques", base="../../")



# ---------------------------------------------------------------- assistant

#: `elims` travels in the form as "12:3,45:7" — the assistant keeps NO state on
#: disk. Eliminations ARE state (a step that only removes candidates changes
#: nothing in `cells`), so an assistant that forgot them would hand out the same
#: hint forever; carrying them in the page is what makes the ladder advance.
def parse_elims(text):
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        a, b = part.split(":", 1)
        if a.strip().isdigit() and b.strip().isdigit():
            i, d = int(a), int(b)
            if 0 <= i < 81 and 1 <= d <= 9:
                out.append((i, d))
    return sorted(set(out))


def fmt_elims(elims):
    return ",".join(f"{i}:{d}" for i, d in sorted(set(elims)))


def _move_options(steps, sel):
    """Every available move in ONE menu, grouped by technique.

    Rogzy 2026-09-17: *« je voudrais avoir toutes les propositions de solution en
    mode drop down, à sélectionner une à la fois »* + *« technique dispo c'est le
    drop down »*. The two asks are the same control: the `<optgroup>` labels ARE
    the « techniques disponibles » list with their counts, and each `<option>` is
    one concrete move inside it. Twelve moves used to be twelve cards and a page
    of scrolling; they are now twelve lines of a menu and one card.

    Native `<select>`/`<optgroup>` on purpose — the assistant is server-rendered
    and has to work with scripting off (that is also what makes it usable on an
    e-ink reader), and the kit already gives `select` its 44 px tap target."""
    by_key = {}
    for i, st in enumerate(steps):
        by_key.setdefault(st["technique"], []).append(i)
    # ⚠ Groups are ordered by the index of their EASIEST move, not by (tier, name).
    # The old card said « le premier de la liste est celui que le moteur jouerait »;
    # Rogzy removed the card, so the menu itself has to keep that true — sorting the
    # groups alphabetically within a tier put the engine's own first move in the
    # MIDDLE of the list while the box showed it selected, which reads as arbitrary.
    out = []
    for key, idxs in sorted(by_key.items(), key=lambda kv: min(kv[1])):
        n = len(idxs)
        head = f'{T.LABELS_FR[key]} · {n} coup{"s" if n > 1 else ""}'
        out.append(f'<optgroup label="{la.esc(head)}">')
        for i in idxs:
            txt = " · ".join(_what_fr(steps[i])) or "—"
            on = " selected" if i == sel else ""
            out.append(f'<option value="{i}"{on}>{la.esc(txt)}</option>')
        out.append("</optgroup>")
    return "".join(out)


def _move_detail(st):
    """The selected move, argued. The technique name links to its fiche: a move
    you don't understand is one tap from the rule."""
    return (f'<div class="move">'
            f'<div class="movehd">'
            f'<a href="../techniques/{la.esc(st["technique"])}">'
            f'{la.esc(st["label_fr"])}</a>'
            f'<span class="muted small">palier {st["tier"]}</span></div>'
            f'<p class="small">{la.esc(st["why_fr"])}</p>'
            f'<p class="muted small">{la.esc(" · ".join(_what_fr(st)))}</p>'
            f'</div>')


def assistant_page(cells_s="", elims_s="", pick=None, err=""):
    """Rogzy 2026-09-15: *« une option / tab assistant, ou je peux ecrir ma grille
    actuel, faire indicie, et ca me propose des solution, a la fois de crayons, de
    réduction des crayon par guess, puis de la resolution case par case mais en me
    laissant choisir et donc voire les options des techniques »*.

    So: not one hint, EVERY move that is on the table right now, each named, each
    explained from its own structure, each playable — and the grid is his, TYPED
    into nine rows of boxes (2026-09-15: *« ofc on ne colle pas une grille mais on
    rentre les chiffres sur une grille »*), not one of ours. Entirely
    server-rendered: the page works with scripting off, which is also why it can
    be trusted on an e-ink reader."""
    body = []
    # ⚠ No « coup joué » banner. Rogzy 2026-09-17: *« no need for the "pas jouer,
    # voila ce qui reste" quand on joue un coup »*. The page already SHOWS the
    # answer — the grid redraws, the counter moves, the move list is rebuilt from
    # the new position. A banner narrating a change the screen makes obvious is
    # one more thing to read past, and « Pas joué » read as "not played" anyway.
    if err:
        body.append(f'<section class="card"><p class="bad">⚠ {la.esc(err)}</p></section>')

    cells = None
    if cells_s:
        try:
            cells = G.parse(cells_s)
        except ValueError as e:
            body.append(f'<section class="card"><p class="bad">⚠ {la.esc(str(e))}'
                        '</p></section>')
            cells = None

    entry = (
        '<form method="post" action="">'
        + entry_board(cells)
        + '<div class="tools">'
        '<button class="btn" name="op" value="analyse">🔎 Analyser</button>'
        '<button class="btn ghost" name="op" value="reset">🧹 Vider</button>'
        '</div></form>'
        '<details class="paste"><summary>…ou coller 81 caractères</summary>'
        '<form method="post" action="">'
        '<p class="muted small">Ce que l\'autre solveur a imprimé : les chiffres, '
        '<code>.</code> ou <code>0</code> pour les vides. Espaces et retours à la '
        'ligne ignorés.</p>'
        f'<textarea name="cells" rows="4" spellcheck="false">'
        f'{la.esc(G.to_string(cells) if cells else cells_s)}</textarea>'
        '<div class="tools"><button class="btn" name="op" value="analyse">'
        '🔎 Analyser</button></div></form></details>')

    # ⚠ `solve_count` does NOT catch a duplicate in the givens — a filled cell
    # carries its own bit, so propagation never sees the clash and the solver
    # cheerfully "solves" around it (measured 2026-09-15: a grid with two 6s in
    # row 1 came back with exactly one solution). `is_valid` is the check that
    # actually looks, and `import_puzzle` has always run it first for this reason.
    doubled = cells is not None and not G.is_valid(cells)
    n_sol = 0 if (cells is None or doubled) else solve_count(cells, 2)

    if cells is None:
        body.append(
            '<section class="card"><div class="section-head"><h3>🤝 Ta grille</h3>'
            '</div>' + entry + '</section>')
    else:
        # once the position is in, the board that REASONS is the one worth the
        # screen; the boxes fold away to what they now are — a way to fix a typo.
        # A broken grid re-opens them: that is the one moment he needs them, and
        # a fix folded out of sight is a fix he has to go looking for.
        # …and a box I could not read re-opens them too: naming R1C5 and then
        # folding R1C5 out of sight is half an error message
        op = " open" if (doubled or n_sol == 0 or err) else ""
        body.append(
            f'<section class="card"><details class="fix"{op}><summary>✏️ Corriger '
            'la grille</summary><p class="muted small">Une correction repart des '
            'chiffres seuls : les éliminations déjà jouées avaient été prouvées '
            'sur l\'ancienne grille, elles ne valent plus rien sur celle-ci.</p>'
            + entry + '</details></section>')

    if cells is None:
        # ⚠ Pas de carte « À quoi ça sert », et pas de ligne « tape les chiffres »
        # au-dessus du plateau. Rogzy 2026-09-29 : *« just remove the small teste
        # and the a quoi ca sert. i know how ot use. we keep ta grlle and the proper
        # tool »*. C'est SON outil, pas une page d'accueil : le plateau et 🔎
        # Analyser sont toute la notice. De la prose d'accueil sur une surface que
        # son unique utilisateur ouvre depuis deux semaines, c'est un écran à lire
        # avant chaque grille.
        return page("Assistant", "".join(body), active="assistant", base="../")

    elims = parse_elims(elims_s)
    cand = engine._cand_with(cells, elims)
    steps = list(engine.all_steps(cells, elims)) if n_sol else []

    note = ""
    if doubled:
        note = ('<p class="bad">Un chiffre apparaît deux fois dans une même ligne, '
                'colonne ou boîte. Rien de ce qui suit ne voudrait dire quoi que ce '
                'soit : corrige la saisie d\'abord.</p>')
    elif n_sol == 0:
        note = ('<p class="bad">Cette grille n\'a aucune solution : il y a une '
                'erreur quelque part. Corrige-la avant de demander un coup — '
                'l\'assistant refuse de raisonner sur une grille fausse.</p>')
    elif n_sol > 1:
        note = ('<p class="muted small">Cette grille a <b>plusieurs</b> solutions. '
                'Les coups restent valides, mais les techniques d\'unicité '
                '(rectangle unique, BUG+1) sont écartées : leur argument suppose '
                'une solution unique.</p>')

    st = steps[pick] if (pick is not None and 0 <= pick < len(steps)) else None
    digits = example_digits(cand, st) if st else None
    left = sum(1 for v in cells if not v)
    body.append(
        f'<section class="card"><div class="section-head"><h3>La grille</h3>'
        f'<span class="muted small">{81 - left}/81 · {len(elims)} élimination'
        f'{"s" if len(elims) > 1 else ""} jouée{"s" if len(elims) > 1 else ""}'
        f'</span></div>{note}'
        f'{static_board(cells, cand, st, digits, klass="")}'
        f'<div class="legend"><span class="k1"><b></b>le motif</span>'
        f'<span class="k2"><b></b>ce qui tombe</span>'
        f'<span class="k3"><b></b>ce qui se pose</span></div></section>')

    cells_now = G.to_string(cells)
    elims_now = fmt_elims(elims)
    if not steps:
        msg = ("Un chiffre en double : corrige la grille." if doubled else
               "Grille terminée. 🎉" if left == 0 else
               "Aucune solution." if n_sol == 0 else
               "Le moteur ne voit plus rien à ce palier. Il te le dit plutôt que "
               "de maquiller un essai-erreur en technique.")
        body.append(f'<section class="card"><p>{la.esc(msg)}</p></section>')
        return page("Assistant", "".join(body), active="assistant", base="../")

    # the menu always HAS a selection, so the explanation and both buttons are
    # there from the first render; `pick` (set by 👁 Montrer) is what puts the
    # move on the BOARD, which is why the two are separate.
    sel = pick if (pick is not None and 0 <= pick < len(steps)) else 0
    body.append(
        f'<section class="card"><div class="section-head">'
        f'<h3>Techniques disponibles</h3>'
        f'<span class="muted small">{len(steps)} coup'
        f'{"s" if len(steps) > 1 else ""}</span></div>'
        f'<form method="post" action="">'
        f'<input type="hidden" name="cells" value="{la.esc(cells_now)}">'
        f'<input type="hidden" name="elims" value="{la.esc(elims_now)}">'
        f'<select name="pick" aria-label="Le coup à regarder">'
        f'{_move_options(steps, sel)}</select>'
        f'{_move_detail(steps[sel])}'
        f'<div class="tools">'
        f'<button class="btn ghost" name="op" value="show">👁 Montrer</button>'
        f'<button class="btn" name="op" value="apply">▶ Jouer ce pas</button>'
        f'</div></form></section>')
    return page("Assistant", "".join(body), active="assistant", base="../")


def assistant_apply(cells_s, elims_s, pick):
    """Play one chosen step and hand back the new (cells, elims).

    Placements go into the grid, eliminations into `elims` — the two halves of a
    `Step`, and the reason `elims` has to survive the round trip."""
    cells = G.parse(cells_s)
    elims = parse_elims(elims_s)
    steps = list(engine.all_steps(cells, elims))
    if not (0 <= pick < len(steps)):
        return cells_s, elims_s, "ce coup n'existe plus — la grille a changé"
    st = steps[pick]
    for i, d in st["placements"]:
        cells[i] = d
    elims = sorted(set(elims) | {(i, d) for i, d in st["targets"]})
    # a placement makes its cell's leftovers meaningless; drop them so the list
    # never carries eliminations about a cell that is now filled
    filled = {i for i, _ in st["placements"]}
    elims = [(i, d) for i, d in elims if i not in filled and not cells[i]]
    return G.to_string(cells), fmt_elims(elims), ""


def techniques_page():
    out = ['<section class="card"><div class="section-head"><h3>📖 Les techniques</h3>'
           '</div><p class="muted small">Ce que le moteur sait voir aujourd\'hui, '
           'du plus simple au plus retors. Les noms restent en anglais — ce sont ceux '
           'que tu liras partout ailleurs. <b>Ouvre-en une</b> : chacune a sa fiche, '
           'avec le raisonnement et des positions réelles où elle se joue.</p></section>']
    for tier in sorted(T.TIER_LABELS):
        keys = [k for k in T.LABELS_FR if TIER_OF.get(k) == tier]
        if not keys:
            continue
        out.append(f'<section class="card"><div class="section-head">'
                   f'<h3>Palier {tier} — {la.esc(T.TIER_LABELS[tier])}</h3></div>'
                   f'<div class="tlist">')
        for k in keys:
            n = len(examples.EXAMPLES.get(k, []))
            ex = drill_count(k)
            out.append(
                f'<a href="{la.esc(k)}"><span><b>{la.esc(T.LABELS_FR[k])}</b> '
                f"<span class='muted small'>{la.esc(k)}</span></span>"
                f"<span class='muted small'>{n} exemple{'s' if n > 1 else ''}"
                f"{f' · {ex} exos' if ex else ''}</span></a>")
        out.append("</div></section>")
    out.append('<section class="card"><div class="section-head"><h3>Pas encore là</h3>'
               '</div><p class="muted small">Palier 4 — chaînes, AIC, ALS — et '
               'l\'Empty Rectangle. Quand le moteur ne conclut pas, il le dit : il ne '
               'maquille pas un essai-erreur en technique.</p></section>')
    return page("Les techniques", "".join(out), active="techniques", base="../")

# ---------------------------------------------------------------- status / act

def status_json():
    # ⚠ La tuile ne parle plus des parties en cours : l'accueil ne les montre plus
    # (v0.7.0), et un résumé qui annonce « 3 en cours » pour une app qui n'en affiche
    # aucune envoie vers une porte qui n'existe pas. Elle dit donc l'état du réservoir.
    games = store.list_games(50)
    counts = store.pool_counts()
    n = sum(counts.values())
    summary = f"{n} grille{'s' if n > 1 else ''} prête{'s' if n > 1 else ''}"
    rev = sum(g.get("updated", 0) for g in games) + n
    return la.status_payload(summary, rev=rev)


CAPABILITIES = {
    "app": "sudoku", "version": VERSION,
    "actions": {
        "new_game": {"payload": {"grade": "0-3 (Facile→Diabolique)"},
                     "returns": "the game id + url"},
        "import_puzzle": {"payload": {"text": "81 chars"},
                          "returns": "the game id, or why it was refused"},
        "verify_claim": {"payload": {"grid": "81 chars", "text": "the hint"},
                         "returns": "verdict + notes"},
        "grade_puzzle": {"payload": {"text": "81 chars"},
                         "returns": "grade, label, techniques required"},
    },
    "_note": "the payload goes under the key 'payload' — /act reads "
             "body['payload'], not the flat body",
}


def do_act(body):
    action = body.get("action")
    p = body.get("payload") or {}
    if action == "new_game":
        g = int(p.get("grade", 0))
        rec = store.pool_take(g) or generator.make_targeted(g, tries=40)
        if not rec:
            return {"ok": False, "error": f"aucune grille de niveau {g} sous la main"}
        game = store.new_game(rec)
        store.fill_pool_async()
        return {"ok": True, "id": game["id"], "url": f"g/{game['id']}/",
                "label": game["label"]}
    if action == "import_puzzle":
        ok, why, game = import_puzzle(p.get("text", ""))
        return ({"ok": True, "id": game["id"], "label": game["label"]} if ok
                else {"ok": False, "error": why})
    if action == "verify_claim":
        try:
            cells = G.parse(p.get("grid", ""))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        r = engine.verify_claim(cells, p.get("text", ""))
        return {"ok": True, "verdict": r["verdict"], "title": r["title"],
                "notes": r["notes"]}
    if action == "grade_puzzle":
        try:
            cells = G.parse(p.get("text", ""))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        g, label, used = engine.grade(cells)
        return {"ok": True, "grade": g, "label": label, "techniques": used,
                "unique": solve_count(cells, 2) == 1}
    return {"ok": False, "error": f"unknown action {action!r}"}


def import_refused_page(text="", err=""):
    """La grille refusée, avec les chiffres encore dans les cases.

    ⚠ Ce n'est plus une page qu'on visite : depuis la v0.8.0 le formulaire vit sous
    le plateau et `/import` est un POST seul. Celle-ci n'est rendue QUE pour dire non
    — et elle garde la saisie, parce qu'une page « Import refusé » qui repart vide
    jette 81 frappes pour une seule fausse.

    The grid he already has, typed in — its own tab since Rogzy asked for one.

    It was a third card at the bottom of the home page, under « Nouvelle grille »,
    and the nine rows of boxes it carries are a full screen by themselves: you had
    to scroll past your own games and the four difficulty buttons to reach the one
    door that takes the grid from the newspaper in front of you.

    A refusal re-renders THIS page with the digits still in the boxes, never a
    dead-end « Import refusé » with a Retour button: the grid is 81 keystrokes and
    the complaint is almost always about one of them."""
    out = []
    if err:
        out.append(f'<section class="card"><p class="bad">⚠ {la.esc(err)}</p>'
                   '<p class="muted small">Le reste de ce que tu as tapé est '
                   'toujours là, en dessous.</p></section>')
    cells = None
    if text:
        try:
            cells = G.parse(text)
        except ValueError:
            cells = None
    out.append('<section class="card"><div class="section-head">'
               '<h3>📥 Ta grille</h3></div>'
               '<p class="muted small">Tape la grille que tu as sous les yeux — '
               'le journal, l\'autre app, la feuille. Les cases vides restent '
               'vides.</p>'
               '<form method="post" action="import">'
               # ⚠ servie à `/import`, donc sa base est la racine de l'app : `back`
               # est vide ici, là où le plateau envoie `../../`.
               '<input type="hidden" name="back" value="">'
               + entry_board(cells) +
               '<div class="tools">'
               '<button class="btn" type="submit">Charger</button></div>'
               '<p class="muted small" style="text-align:center">je vérifie '
               'qu\'elle est valide et unique avant que tu y passes deux heures'
               '</p></form>'
               '<details class="paste"><summary>…ou coller 81 caractères</summary>'
               '<form method="post" action="import">'
               '<input type="hidden" name="back" value="">'
               '<textarea name="text" rows="3" placeholder="81 caractères — '
               '. ou 0 pour les cases vides"></textarea>'
               '<div class="tools"><button class="btn" type="submit">Charger'
               '</button></div></form></details></section>')
    return page("Import refusé", "".join(out), active="jouer", base="")


def import_puzzle(text):
    """Load a pasted grid — after telling the truth about it.

    Refusing an ambiguous puzzle up front is the whole point: nothing is worse
    than two hours on a grid that never had one answer.
    """
    try:
        cells = G.parse(text)
    except ValueError as e:
        return False, str(e), None
    if not G.is_valid(cells):
        return False, "cette grille a un chiffre en double dans une unité", None
    n = solve_count(cells, 2)
    if n == 0:
        return False, "cette grille n'a aucune solution", None
    if n > 1:
        return False, "cette grille a plusieurs solutions — elle n'est pas jouable", None
    g, label, used = engine.grade(cells)
    rec = {"puzzle": G.to_string(cells), "grade": g, "label": label,
           "techniques": used}
    return True, None, store.new_game(rec, source="import")


# ---------------------------------------------------------------- routing

RE_GAME = re.compile(r"^/g/([0-9a-f]{6,16})/?$")
RE_GAME_API = re.compile(r"^/g/([0-9a-f]{6,16})/(state|hint|apply-hint|audit|check|tick)$")
#: one fiche per technique, e.g. /techniques/w_wing
RE_FICHE = re.compile(r"^/techniques/([a-z0-9_]{2,40})$")
#: one practice position, e.g. /entrainement/w_wing/7. 1-indexed, because the
#: page says "exercice 7 / 20" and an exercise numbered 0 reads as a bug.
RE_DRILL = re.compile(r"^/entrainement/([a-z0-9_]{2,40})/([0-9]{1,3})$")

#: Every path this app answers. Load-bearing, not documentation: the handler
#: 404s anything outside these before it reaches the dispatch chain, and
#: `tests/test_routes.py` resolves every href and form action in every rendered
#: page against them. Rendering a page and being able to REACH it are different
#: claims, and only the second one survives a relative-link mistake.
STATIC_GET = {"/", "/status.json", "/healthz", "/capabilities",
              "/techniques", "/assistant"}
STATIC_POST = {"/act", "/new", "/import", "/assistant"}


#: HTML pages whose links are relative to THEMSELVES, so they must be served with
#: a trailing slash. (The fiches and the drills are the other family: their links
#: are relative to their parent, so they must be served WITHOUT one.)
#: Where a form sends him afterwards, RELATIVE to the page it was posted FROM —
#: which is not the same page for the two of them, and that is the whole point.
#: ⚠ `../g/…` for the import: `g/…` was right while its form lived on the home
#: page, and moving a form is exactly the change that leaves a redirect behind,
#: pointing at `/import/g/<id>/`. Named and tested rather than inlined twice.
#: Le même endpoint est maintenant posté depuis DEUX pages (le plateau, et la page
#: de refus d'un import), et une constante ne peut être juste que pour une seule.
#: La page qui affiche le formulaire porte donc son propre chemin vers la racine de
#: l'app dans un champ caché `back`, et la redirection se construit avec.
#: ⚠ C'est la TROISIÈME fois qu'un formulaire déménagé laisse une redirection en
#: arrière dans cette app. Le champ caché est ce qui empêche la quatrième.
#: ⚠ `back` vient du client : il est comparé à une liste blanche, jamais concaténé
#: tel quel — une cible de redirection pilotée par le formulaire est une redirection
#: ouverte.
BACK_OK = {"", "../../"}         # "" = posté depuis la racine de l'app


def game_url(back, gid):
    """Où l'envoyer une fois la partie créée, RELATIVEMENT à la page qui a posté."""
    return f"{back if back in BACK_OK else ''}g/{gid}/"

#: ⚠ `/import` n'est plus là : c'est désormais un POST seul (son formulaire vit
#: sous le plateau), donc il n'a plus de forme canonique à faire respecter.
DIR_PAGES = {"/techniques", "/assistant"}


def canonical(path):
    """The one spelling of this URL, as a relative redirect — or "" to serve it.

    ⚠ Every page here links relatively, and a relative link is only correct
    against the URL the page is really SERVED at. Two families, opposite needs:

      • `/assistant`, `/techniques` and a game link to their
        own siblings, so their base directory must be THEMSELVES → trailing slash
        required. Served without one, `../techniques/` resolves to
        `/techniques/` — outside the app entirely, because a proxy's `/sudoku`
        prefix is exactly the level that gets eaten.
      • A fiche (`/techniques/x_wing`) and a drill (`/entrainement/x_wing/7`) link
        UP, so their base must be their parent → no trailing slash. Served with
        one, the whole nav strip sits a level too low.

    Answering both spellings means answering one of them wrong, and you only find
    out by typing it by hand. So each URL has one spelling and the other redirects.

    The target is RELATIVE on purpose (an absolute Location would leave the app),
    and for the second family it starts `../` — the trap in miniature: the browser
    resolves Location against the URL it ASKED for, which still ends in the slash
    being removed, so a bare `3` from `/entrainement/x_wing/3/` means `.../3/3`."""
    raw = path.split("?")[0]
    clean = raw.rstrip("/")
    if not clean:
        return ""                       # "/" is already the only spelling it has
    last = clean.rsplit("/", 1)[1]
    if clean in DIR_PAGES or RE_GAME.match(clean):
        return "" if raw.endswith("/") else last + "/"
    if RE_FICHE.match(clean) or RE_DRILL.match(clean):
        return "../" + last if raw.endswith("/") else ""
    return ""


#: Public mode closes everything that only serves a single-user install (the
#: agent door, the status tile, the capability list) and the typed-grid import.
PRIVATE_ONLY_GET = {"/status.json", "/capabilities"}
PRIVATE_ONLY_POST = {"/act", "/import"}
PUBLIC_CSS = "/static/luna-ui.css"
PUBLIC_CSS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "public", "static", "luna-ui.css")
_css_cache = []


def public_css():
    """The vendored kit, comments stripped (they name internal paths), read once."""
    if not _css_cache:
        with open(PUBLIC_CSS_FILE, encoding="utf-8") as f:
            _css_cache.append(re.sub(r"/\*.*?\*/", "", f.read(),
                                     flags=re.S).encode())
    return _css_cache[0]


def route_exists(path, method="GET"):
    clean = path.split("?")[0].rstrip("/") or "/"
    if store.PUBLIC:
        if clean in (PRIVATE_ONLY_GET if method == "GET" else PRIVATE_ONLY_POST):
            return False
        if method == "GET" and path.split("?")[0] == PUBLIC_CSS:
            return True
    known = STATIC_GET if method == "GET" else STATIC_POST
    if clean in known:
        return True
    raw = path.split("?")[0]
    if method == "GET" and RE_GAME.match(raw):
        return True
    if method == "GET" and RE_FICHE.match(clean):
        return RE_FICHE.match(clean).group(1) in T.LABELS_FR
    m = RE_DRILL.match(clean)
    if method == "GET" and m:
        # the bank's length is the only thing that decides an exercise exists —
        # BUG+1 comes back short and a 404 is the honest answer for #9 of 8
        return (m.group(1) in T.LABELS_FR
                and 1 <= int(m.group(2)) <= drill_count(m.group(1)))
    return bool(RE_GAME_API.match(raw))


COOKIE = "sdk"
#: public mode: nothing a friend's browser legitimately sends comes close
PUBLIC_MAX_BODY = 16 * 1024
FULL_MSG = ("Le site affiche complet pour l'instant : impossible de garder une "
            "nouvelle partie pour toi. Les techniques et l'assistant restent "
            "ouverts — réessaie un peu plus tard.")
NO_COOKIE_MSG = ("Ce site garde tes parties grâce à un cookie (et rien d'autre). "
                 "Ton navigateur l'a refusé : autorise-le, puis recharge la page.")


def read_sid(cookie_header):
    """The visitor id from a Cookie header — or None. Strict: the first `sdk`
    value must match the 24-char token alphabet, anything else is ABSENT (it is
    about to become a directory name)."""
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            v = v.strip()
            return v if store.RE_SID.match(v) else None
    return None


def message_page(text, title="🔢 Sudoku"):
    return page(title, f'<section class="card"><p>{la.esc(text)}</p></section>',
                active="jouer")


class SudokuHandler(la.Handler):
    """Dynamic routes + POST. `lunaapp.Handler` gives a static table; a game id
    in the path needs a regex, and every write needs do_POST.

    Public mode wraps both verbs: read (or mint) the visitor cookie, bind the
    store to that visitor for THIS thread, and unbind afterwards whatever happens."""

    _new_sid = None
    sid_in = None

    def end_headers(self):
        if self._new_sid:
            self.send_header("Set-Cookie", f"{COOKIE}={self._new_sid}; HttpOnly; Secure; "
                             "SameSite=Lax; Path=/; Max-Age=31536000")
            self._new_sid = None
        if store.PUBLIC:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def _wrapped(self, inner):
        if not store.PUBLIC:
            return inner()
        path = self.path.split("?")[0]
        self.sid_in = read_sid(self.headers.get("Cookie"))
        sid = self.sid_in
        if not sid and path not in (PUBLIC_CSS, "/healthz"):
            sid = self._new_sid = secrets.token_urlsafe(18)
        store.bind_visitor(sid)
        try:
            return inner()
        except store.VisitorsFull:
            return self.send_html(message_page(FULL_MSG), 503)
        finally:
            store.bind_visitor(None)

    def do_GET(self):
        return self._wrapped(self._get)

    def do_POST(self):
        return self._wrapped(self._post)

    def _game(self, gid):
        g = store.load_game(gid)
        if not g:
            self.send_body(404, "partie inconnue", "text/plain")
        return g

    def _get(self):
        path = self.path.split("?")[0]
        qs = self.path.split("?")[1] if "?" in self.path else ""
        q = dict(x.split("=", 1) for x in qs.split("&") if "=" in x)
        clean = path.rstrip("/") or "/"
        if not route_exists(path, "GET"):
            return self.send_body(404, "not found", "text/plain")
        # before ANY page is built: one URL, one spelling. Every href below is
        # relative, and `canonical` is the only thing that says which base they
        # are relative to — so it has to run first, not after six handlers.
        to = canonical(path)
        if to:
            return self.redirect(to, 302)

        if store.PUBLIC and path == PUBLIC_CSS:
            return self.send_body(200, public_css(), "text/css; charset=utf-8",
                                  {"Cache-Control": "public, max-age=86400"})
        if clean == "/" and store.PUBLIC and not self.sid_in:
            # ⚠ Pas de partie pour un client sans cookie : sinon chaque requête nue
            # (un robot, un curl) créerait un dossier visiteur. On pose le cookie et
            # on revient UNE fois ; sans cookie au retour, on le dit au lieu de boucler.
            if q.get("c") == "1":
                return self.send_html(message_page(NO_COOKIE_MSG))
            return self.redirect("./?c=1", 302)
        if clean == "/":
            # ▶ Jouer n'est plus une page de choix : il OUVRE un plateau (v0.8.0).
            # ⚠ Une redirection, pas un rendu en place : le plateau vit à `/g/<id>/`
            # et tout son JS appelle `hint`, `apply-hint`… en relatif depuis là.
            # Rendu à la racine, chacun de ces appels viserait `/hint`, qui n'existe pas.
            g = current_game()
            if g:
                return self.redirect(f"g/{g['id']}/", 302)
            return self.send_html(empty_pool_page())
        if clean == "/status.json":
            return self.send_json(status_json())
        if clean == "/healthz":
            return self.send_body(200, "ok", "text/plain")
        if clean == "/capabilities":
            return self.send_json(CAPABILITIES)
        if clean == "/techniques":
            return self.send_html(techniques_page())
        if clean == "/assistant":
            # `?g=<id>` : ouvert depuis le plateau, pré-rempli avec la position en
            # cours — *« si je suis bloqué faudra bien me débloquer avec l'assistant »*
            # (29/09). Les éliminations déjà prouvées de la partie voyagent avec, sinon
            # l'assistant reproposerait des coups que la partie a déjà joués.
            gg = store.load_game(q["g"]) if q.get("g") else None
            if gg:
                return self.send_html(assistant_page(gg["cells"], fmt_elims(_elims(gg))))
            return self.send_html(assistant_page())
        m = RE_FICHE.match(clean)
        if m:
            pg = fiche_page(m.group(1))
            if pg is None:
                return self.send_body(404, "technique inconnue", "text/plain")
            return self.send_html(pg)
        m = RE_DRILL.match(clean)
        if m:
            pg = drill_page(m.group(1), int(m.group(2)), q.get("voir") == "1")
            if pg is None:
                return self.send_body(404, "exercice inconnu", "text/plain")
            return self.send_html(pg)
        m = RE_GAME.match(path)
        if m:
            g = self._game(m.group(1))
            return self.send_html(board_page(g)) if g else None
        m = RE_GAME_API.match(path)
        if m:
            gid, what = m.group(1), m.group(2)
            g = self._game(gid)
            if not g:
                return
            if what == "hint":
                lvl = int(q.get("level", 1) or 1)
                payload = hint_payload(g, lvl)
                g.setdefault("hints", []).append(
                    {"at": int(time.time()), "level": lvl,
                     "technique": payload.get("technique")})
                store.save_game(g)
                return self.send_json(payload)
            if what == "audit":
                return self.send_json(audit_payload(g, q.get("level", 0)))
            if what == "check":
                return self.send_json(check_payload(g))
            if what == "state":
                return self.send_json({"ok": True, "cells": g["cells"]})
        return self.send_body(404, "not found", "text/plain")

    def _post(self):
        path = self.path.split("?")[0]
        clean = path.rstrip("/") or "/"
        if not route_exists(path, "POST"):
            return self.send_body(404, "not found", "text/plain")
        raw = self.read_body(PUBLIC_MAX_BODY if store.PUBLIC else 200_000)
        if raw is None:
            return

        if clean == "/act":
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self.send_json({"ok": False, "error": "bad json"}, 400)
            return self.send_json(do_act(body))
        if clean == "/new":
            f = la.parse_form(raw)
            gr = int(f.get("grade", 0))
            if store.PUBLIC:
                # ⚠ jamais de génération dans la requête d'un inconnu : le réservoir
                # (partagé) ou rien. Et pas de partie pour un client sans cookie.
                if not self.sid_in:
                    return self.send_html(message_page(NO_COOKIE_MSG), 403)
                rec = store.pool_take(gr) if 0 <= gr <= 3 else None
            else:
                rec = store.pool_take(gr) or generator.make_targeted(gr, tries=40)
            store.fill_pool_async()
            if not rec:
                return self.redirect("../")
            game = store.new_game(rec)
            return self.redirect(game_url(f.get("back", ""), game["id"]))
        if clean == "/assistant":
            f = la.parse_form(raw)
            op = f.get("op", "analyse")
            # the 81 boxes when he typed, the hidden string when a move is being
            # played — `cells_from_form` tells the two apart and NAMES a box it
            # could not read instead of quietly calling it empty
            cells_s, bad = cells_from_form(f)
            elims_s = f.get("elims", "")
            if op == "reset":
                return self.send_html(assistant_page())
            pick = f.get("pick", "")
            pick = int(pick) if pick.isdigit() else None
            if op == "apply" and pick is not None:
                cells_s, elims_s, why = assistant_apply(cells_s, elims_s, pick)
                return self.send_html(assistant_page(
                    cells_s, elims_s, err=why))
            return self.send_html(assistant_page(
                cells_s, elims_s, pick=pick if op == "show" else None, err=bad))
        if clean == "/import":
            f = la.parse_form(raw)
            text, bad = cells_from_form(f, "text")
            ok, why, game = (False, bad, None) if bad else import_puzzle(text)
            if ok:
                return self.redirect(game_url(f.get("back", ""), game["id"]))
            return self.send_html(import_refused_page(text, why))
        m = RE_GAME_API.match(path)
        if m:
            gid, what = m.group(1), m.group(2)
            g = store.load_game(gid)
            if not g:
                return self.send_json({"ok": False}, 404)
            if what == "tick":
                if not g.get("done"):
                    g["seconds"] = int(g.get("seconds", 0)) + 30
                    store.save_game(g)
                return self.send_json({"ok": True, "seconds": g["seconds"]})
            if what == "apply-hint":
                return self.send_json(apply_hint(g))
            if what == "state":
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    return self.send_json({"ok": False}, 400)
                return self.send_json(save_state(g, body))
        return self.send_body(404, "not found", "text/plain")


def save_state(game, body):
    """Fold the client's board into the stored game — and keep the journal.

    ⚠ The move journal is written HERE, by diffing, not by trusting a list the
    client sends. A journal the browser composes is a journal a reload can lose;
    a diff against what we already hold cannot drift.
    """
    old = G.parse(game["cells"])
    new = G.parse(body.get("cells", game["cells"]))
    given = G.parse(game["puzzle"])
    for i in range(81):
        if given[i]:
            new[i] = given[i]          # a given is not the client's to change
    moves = game.setdefault("moves", [])
    now = int(time.time())
    for i in range(81):
        if old[i] != new[i]:
            moves.append({"t": now, "i": i, "from": old[i], "to": new[i]})
    game["cells"] = G.to_string(new)
    game["pencil"] = {str(k): int(v) for k, v in (body.get("pencil") or {}).items()
                      if int(v or 0)}
    game["struck"] = {str(k): int(v) for k, v in (body.get("struck") or {}).items()
                      if int(v or 0)}
    if "auto_pencil" in body:
        game["auto_pencil"] = bool(body["auto_pencil"])
    game["done"] = _check_done(game, new)
    store.save_game(game)
    out = {"ok": True, "done": game["done"]}
    if game.get("mode") == "strict":
        sol = solution(G.parse(game["puzzle"]))
        out["bad"] = [i for i in range(81) if new[i] and sol and sol[i] != new[i]]
    return out


if __name__ == "__main__":
    store.ensure_dirs()
    store.fill_pool_async()
    if store.PUBLIC:
        store.start_pruner()
    la.run("sudoku", {}, default_port=8801, handler_cls=SudokuHandler)
