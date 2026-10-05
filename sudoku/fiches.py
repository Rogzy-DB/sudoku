# -*- coding: utf-8 -*-
"""The AUTHORED half of a technique fiche: what it is, why the conclusion holds,
how to spot it, and the trap that costs people the most time.

This is the one place in the app where French about sudoku is written by hand,
and the boundary is deliberate: everything the fiche says about a *particular*
position — which cells, which digit, what it removes — is generated from the
step's structure at render time, exactly as a hint is (`why_fr`). Prose explains
the RULE; the engine explains the MOVE. A worked example whose commentary was
typed here would be a claim nobody re-checks.

`piege` is optional and rationed: it is for the mistakes that actually happen,
not a third paragraph for symmetry.
"""

FICHES = {
    # ---- palier 0 : placements -------------------------------------------
    "full_house": {
        "quoi": "Une unité (ligne, colonne ou boîte) où huit cases sont déjà "
                "remplies. La neuvième n'a plus le choix.",
        "pourquoi": "Chaque unité contient les neuf chiffres, une fois chacun. "
                    "S'il en manque un seul, la seule case libre le prend.",
        "reperer": "Balaye les unités les plus remplies avant tout le reste : "
                   "c'est le coup gratuit, et il en débloque souvent d'autres.",
    },
    "naked_single": {
        "quoi": "Une case dont il ne reste qu'un seul candidat.",
        "pourquoi": "Ses pairs (ligne, colonne, boîte) ont éliminé les huit "
                    "autres chiffres. Ce qui reste est la réponse.",
        "reperer": "C'est ce que tes petits chiffres montrent tout seuls : une "
                   "case avec une seule marque. D'où l'intérêt de les tenir à jour.",
        "piege": "« Nu » veut dire vu depuis la CASE. Ne le confonds pas avec le "
                 "single caché, qui se voit depuis l'UNITÉ.",
    },
    "hidden_single": {
        "quoi": "Dans une unité, un chiffre n'a plus qu'une seule case possible — "
                "même si cette case a encore plusieurs candidats.",
        "pourquoi": "Le chiffre doit bien se placer quelque part dans l'unité. "
                    "S'il ne reste qu'une case pour lui, c'est là.",
        "reperer": "Prends un chiffre, pas une case : suis ses lignes et colonnes "
                   "à travers une boîte et regarde ce qui reste.",
        "piege": "Il est « caché » parce que la case porte d'autres candidats : "
                 "tu ne le verras jamais en regardant les cases une par une.",
    },

    # ---- palier 1 : la base ----------------------------------------------
    "pointing": {
        "quoi": "Dans une boîte, toutes les places d'un chiffre tombent sur une "
                "même ligne (ou colonne).",
        "pourquoi": "Le chiffre est forcément dans cette boîte, donc forcément sur "
                    "cette ligne. Il ne peut plus être ailleurs sur la ligne.",
        "reperer": "Boîte par boîte, chiffre par chiffre : deux ou trois places "
                   "alignées, et tu nettoies le reste de la ligne.",
    },
    "claiming": {
        "quoi": "L'inverse : sur une ligne (ou colonne), toutes les places d'un "
                "chiffre tombent dans une même boîte.",
        "pourquoi": "Le chiffre est forcément sur cette ligne, donc forcément dans "
                    "cette boîte. Il quitte le reste de la boîte.",
        "reperer": "Quand une ligne n'a plus que deux ou trois places pour un "
                   "chiffre, vérifie si elles partagent une boîte.",
        "piege": "Pointing et claiming sont le même fait vu des deux côtés. Ce qui "
                 "change, c'est ce que tu nettoies : la ligne, ou la boîte.",
    },
    "naked_pair": {
        "quoi": "Deux cases d'une même unité qui ne portent, à elles deux, que "
                "deux candidats.",
        "pourquoi": "Ces deux chiffres occuperont ces deux cases, dans un ordre ou "
                    "l'autre. Ils n'ont plus de place ailleurs dans l'unité.",
        "reperer": "Cherche les cases à deux candidats et compare-les dans l'unité.",
        "piege": "Tu ne sais pas lequel va où — et tu n'en as pas besoin. La "
                 "conclusion porte sur les AUTRES cases, jamais sur la paire.",
    },
    "naked_triple": {
        "quoi": "Trois cases d'une unité qui ne portent, à elles trois, que trois "
                "candidats en tout.",
        "pourquoi": "Trois chiffres pour trois cases : ils y sont enfermés et "
                    "quittent le reste de l'unité.",
        "reperer": "Les trois cases n'ont pas besoin d'avoir les trois candidats "
                   "chacune : {1,2}, {2,3}, {1,3} est un triplet nu parfait.",
        "piege": "C'est le total des candidats qui compte, pas leur nombre par case.",
    },
    "naked_quad": {
        "quoi": "Même chose avec quatre cases et quatre candidats.",
        "pourquoi": "Quatre chiffres enfermés dans quatre cases : ils disparaissent "
                    "des cinq autres cases de l'unité.",
        "reperer": "Rare et pénible à voir à l'œil. Quand une unité a beaucoup de "
                   "cases à deux ou trois candidats, ça vaut le coup de compter.",
    },
    "hidden_pair": {
        "quoi": "Dans une unité, deux chiffres qui n'ont plus que les deux mêmes "
                "cases possibles.",
        "pourquoi": "Ces deux chiffres doivent tenir dans ces deux cases : ils les "
                    "remplissent toutes les deux. Tout autre candidat y est faux.",
        "reperer": "Compte les places de chaque chiffre dans l'unité, pas les "
                   "candidats de chaque case.",
        "piege": "Le nettoyage se fait DANS la paire, pas autour d'elle — c'est "
                 "l'exact contraire de la paire nue.",
    },
    "hidden_triple": {
        "quoi": "Trois chiffres qui n'ont plus que les trois mêmes cases dans une "
                "unité.",
        "pourquoi": "Trois chiffres à caser dans trois cases : ils les occupent "
                    "toutes, et tous les autres candidats de ces cases tombent.",
        "reperer": "Souvent invisible parce que les trois cases sont chargées : "
                   "c'est justement ce que le nettoyage va corriger.",
    },
    "hidden_quad": {
        "quoi": "Quatre chiffres confinés aux quatre mêmes cases d'une unité.",
        "pourquoi": "Quatre chiffres, quatre cases : ils les prennent toutes, le "
                    "reste des candidats de ces cases saute.",
        "reperer": "Le plus discret des quatre. Cherche-le quand une unité a peu "
                   "de cases libres mais des candidats partout.",
    },

    # ---- palier 2 : un seul chiffre --------------------------------------
    "x_wing": {
        "quoi": "Un chiffre qui n'a que deux places dans chacune de deux lignes, "
                "et ces places tombent sur les deux mêmes colonnes.",
        "pourquoi": "Les deux lignes prendront le chiffre sur ces quatre cases, en "
                    "diagonale d'une façon ou de l'autre. Dans les deux cas, les "
                    "deux colonnes sont servies : le chiffre les quitte ailleurs.",
        "reperer": "Un chiffre à la fois. Note les lignes où il n'a que deux "
                   "places et compare leurs colonnes. Ça marche aussi en échangeant "
                   "lignes et colonnes.",
        "piege": "Il faut EXACTEMENT deux places par ligne. Trois, et le "
                 "raisonnement tombe.",
    },
    "swordfish": {
        "quoi": "Le X-Wing en trois lignes et trois colonnes.",
        "pourquoi": "Trois lignes doivent poser le chiffre dans trois colonnes : "
                    "elles les remplissent toutes les trois. Le chiffre quitte ces "
                    "colonnes partout ailleurs.",
        "reperer": "Chaque ligne peut avoir deux OU trois places, du moment que "
                   "tout tient dans trois colonnes au total.",
        "piege": "On le rate en exigeant trois places partout. La condition porte "
                 "sur l'union des colonnes, pas sur le compte par ligne.",
    },
    "jellyfish": {
        "quoi": "Le même motif en quatre lignes et quatre colonnes.",
        "pourquoi": "Quatre lignes, quatre colonnes : identique au Swordfish, d'un "
                    "cran plus large.",
        "reperer": "Rarement nécessaire : au-delà du Swordfish, une autre technique "
                   "est presque toujours passée avant.",
    },
    "skyscraper": {
        "quoi": "Deux lignes où le chiffre n'a que deux places, qui partagent une "
                "colonne. Les deux bouts libres sont les « toits ».",
        "pourquoi": "Si le chiffre n'était sur aucun des deux toits, il serait sur "
                    "la colonne commune dans les deux lignes — deux fois dans la "
                    "même colonne, impossible. Donc au moins un toit est le chiffre, "
                    "et toute case qui voit les deux toits le perd.",
        "reperer": "Deux paires du même chiffre, alignées par un bout, décalées par "
                   "l'autre.",
        "piege": "La conclusion vise ce qui voit les DEUX toits — jamais les toits "
                 "eux-mêmes, dont on ignore lequel est le bon.",
    },
    "two_string_kite": {
        "quoi": "Une ligne et une colonne où le chiffre n'a que deux places, et "
                "dont un bout chacune se retrouve dans la même boîte.",
        "pourquoi": "La boîte ne peut pas contenir le chiffre deux fois : au moins "
                    "un des deux bouts opposés est le chiffre. Ce qui voit les deux "
                    "bouts libres le perd.",
        "reperer": "Même conclusion que le skyscraper, articulation différente : "
                   "ici c'est une boîte qui sert de charnière, pas une colonne.",
    },
    "simple_colouring": {
        "quoi": "On colorie en deux couleurs la chaîne des paires fortes d'un "
                "chiffre (les unités où il n'a plus que deux places).",
        "pourquoi": "Le long d'une paire forte, le chiffre est vrai d'un côté ou de "
                    "l'autre : les couleurs alternent, et l'une des deux est vraie "
                    "partout. Deux cases de la MÊME couleur dans une même unité : "
                    "cette couleur est fausse en entier. Sinon, une case extérieure "
                    "qui voit les deux couleurs perd le chiffre, puisque l'une des "
                    "deux est forcément vraie.",
        "reperer": "Prends le chiffre le plus contraint et suis ses paires fortes "
                   "de proche en proche.",
        "piege": "Les deux conclusions sont différentes : la première tue une "
                 "couleur entière, la seconde ne touche que des cases hors chaîne.",
    },

    # ---- palier 3 : plusieurs chiffres -----------------------------------
    "xy_wing": {
        "quoi": "Un pivot à deux candidats {a,b} qui voit deux « ailes », {a,c} et "
                "{b,c}.",
        "pourquoi": "Le pivot vaut a ou b. S'il vaut a, l'aile {a,c} tombe sur c ; "
                    "s'il vaut b, c'est l'autre aile qui tombe sur c. Dans les deux "
                    "cas une aile vaut c, donc toute case voyant les deux ailes "
                    "perd c.",
        "reperer": "Trois cases à deux candidats, trois chiffres en tout, le pivot "
                   "au milieu qui voit les deux autres.",
        "piege": "Les ailes n'ont pas besoin de se voir entre elles. C'est le pivot "
                 "qui doit voir les deux.",
    },
    "xyz_wing": {
        "quoi": "La même idée avec un pivot à TROIS candidats {a,b,c} et deux ailes "
                "{a,c} et {b,c}.",
        "pourquoi": "Les trois cases peuvent valoir c. Une case qui les voit toutes "
                    "les trois perd c, parce que l'une des trois le prendra.",
        "reperer": "Comme le XY-Wing, mais les victimes doivent voir le pivot AUSSI "
                   "— il y en a donc beaucoup moins.",
    },
    "w_wing": {
        "quoi": "Deux cases portant la même paire {a,b}, qui ne se voient pas, "
                "reliées par un lien fort sur l'un des deux chiffres.",
        "pourquoi": "Le lien fort est une unité où a n'a plus que deux places : "
                    "l'une des deux EST un a. Si ce bout-là voit une des ailes, "
                    "cette aile ne peut pas être a — elle est donc b. Quel que soit "
                    "le bout vrai, au moins une aile vaut b : toute case voyant les "
                    "deux ailes perd b.",
        "reperer": "Deux cases jumelles {a,b} éloignées, puis une unité où a n'a "
                   "que deux places, un bout par aile.",
        "piege": "🔴 Le lien fort porte sur le chiffre que tu GARDES, et tu élimines "
                 "l'AUTRE. Un lien fort sur a fait tomber des b. Un solveur qui te "
                 "dit « lien fort sur 2, retirez les 6 » a raison ; l'inverse serait "
                 "faux.",
    },
    "remote_pairs": {
        "quoi": "Une chaîne de cases portant toutes la même paire {a,b}, chacune "
                "voyant la suivante.",
        "pourquoi": "Le long de la chaîne, les valeurs alternent : a, b, a, b… Deux "
                    "cases séparées par un nombre IMPAIR de pas sont donc opposées, "
                    "l'une vaut a et l'autre b. Toute case qui voit ces deux-là perd "
                    "a ET b d'un coup.",
        "reperer": "Repère les paires identiques répétées, puis compte les pas. "
                   "Nombre pair : rien à en tirer.",
        "piege": "C'est la seule technique de ce palier qui retire deux chiffres à "
                 "la fois. Compte les pas deux fois avant d'y croire.",
    },
    "unique_rectangle_1": {
        "quoi": "Quatre cases formant un rectangle sur deux lignes, deux colonnes "
                "et deux boîtes : trois portent exactement {a,b}, la quatrième "
                "porte {a,b} plus autre chose.",
        "pourquoi": "Si la quatrième valait a ou b, les quatre coins seraient "
                    "interchangeables en diagonale et la grille aurait deux "
                    "solutions. Une grille correcte n'en a qu'une : la quatrième "
                    "case prend forcément l'un de ses candidats supplémentaires.",
        "reperer": "Deux paires identiques sur une ligne, deux mêmes colonnes "
                   "ailleurs — et un coin un peu plus chargé.",
        "piege": "🔴 L'argument repose sur l'UNICITÉ de la solution. Sur une grille "
                 "importée d'on ne sait où, il ne vaut rien : le moteur refuse de "
                 "l'utiliser tant qu'il n'a pas vérifié que la solution est unique.",
    },
    "bug_plus_one": {
        "quoi": "Toutes les cases libres ont exactement deux candidats sauf UNE, "
                "qui en a trois.",
        "pourquoi": "Une grille où chaque case libre a deux candidats et chaque "
                    "chiffre deux places par unité se résout de deux façons. La "
                    "case à trois candidats est la seule qui puisse casser cette "
                    "symétrie : elle prend le candidat qui apparaît trois fois dans "
                    "l'une de ses unités.",
        "reperer": "Fin de grille, plus que des paires partout, et une case qui "
                   "dépasse.",
        "piege": "🔴 Même réserve que le rectangle unique : c'est un argument "
                 "d'unicité, pas de logique pure.",
    },
}
