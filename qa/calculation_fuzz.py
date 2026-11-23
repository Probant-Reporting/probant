"""Random calculation cases (property testing): the tool's engine against an independent second calculation.

    python3 qa/calculation_fuzz.py --seeds 0:500 [--out DIR] [--minimize] [--stop-after N]
    python3 qa/calculation_fuzz.py --replay DIR/case-123.json     # one saved case, differences on screen

Each case is generated from its seed (reproducible): a tree of 1 to 6 levels (flexible attachment, closed organisations
with or without a closing date, organisations with an opening date, set at the start or later by the organisation form), entered KPIs (number, percentage, yes / no, list), calculated KPIs with random formulas
([X], [X@N-1], [X@P-1], [X@YYYY], constants, + - * /, parentheses, unary minus, odd spacing), inherited parameters,
aggregations (sum, formula, count, none), "N/A counts as 0", entry above the granularity, forced values, legacy imports
(on entered, aggregated and calculated cells), annual / quarterly / monthly frameworks (aggregation over time), open,
review, preparation and closed campaigns, KPIs requested only from a given period ("Requested since", set at creation,
then moved earlier or later by the KPI management; a move the tool refuses changes nothing), a year that calculates only the KPIs of its campaigns and of the periods it
contains (a KPI of a framework without campaign gets no cell). The case is built in a throw-away test database, calculated by the tool
(``recalculer``, period by period, then a second pass that must change nothing), the organisation tree of the closed
periods is recorded (as at a closing), then a few entries are changed one at a time (the recalculation that follows an
entry). After a closing, the tree can change (organisations moved, created, closed), then a closed period is reopened
("keep the figures of the time" or "recalculate with today's organisation") and corrected: a period kept with the figures
of the time follows the tree of its closing, and only the corrected organisation and its totals of the time are redone. A rare case is also drawn on purpose : a closed year followed by an open
one, an organisation moved after the closing, the closed year reopened with "keep", formulas `[X@N-1]` recalculated above
their granularity and on an inherited parameter, then corrections of the moved organisation and of the factor of its
parent of the time. After each step, every calculated, aggregated or cumulated cell is
compared with ``qa/independent_calculation.py`` (value, N/A, incomplete, error).

Third review, on request: ``--v3`` draws more shapes (half-year framework, two campaigns of two yearly
frameworks on the same year, "table" answers, validation, forced value then back to the calculation, batch of entries as
an import, correction imported into a closed campaign, writes after a "keep" reopening, which the kept periods that
read the changed period follow); ``--full-check`` compares, after each change, the state left by the tool (targeted
recalculation) with a full recalculation of every non-frozen period; ``--pages`` compares, at the end, the figures of the
Visualisation (validated values; also the MCP server for a reader), of a visual limited to one KPI, and the detail of
each total with the saved cells; ``--postgres`` uses the database of DATABASE_URL.

A difference is written to ``--out`` (case-<seed>.json, with the differences); ``--minimize`` first reduces the case
to a smaller one that still differs. Exit code: 0 if no difference, 1 otherwise. Invented data only.
"""
# Commentaires en français (règles du projet) ; messages à l'écran en anglais (outil pour l'IT et les développeurs).
import argparse
import copy
import datetime
import json
import os
import random
import sys
import tempfile
import time
import traceback
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "qa"))

import independent_calculation as IC  # noqa: E402

MOIS_PAR = IC.MOIS_PAR


# ---------------------------------------------------------------- génération
def _date(d):
    return d.isoformat()


def _nombre(R, pourcentage=False):
    if pourcentage:
        return format(Decimal(R.randint(0, 10000)) / Decimal(10000), "f")
    t = R.random()
    if t < 0.12:
        return "0"
    if t < 0.15:
        return str(R.choice([10 ** 12, 4 * 10 ** 11, 999999999999]))  # grands nombres : totaux au-delà de 10^15
    if t < 0.20:
        return "-" + str(R.randint(1, 500))
    if t < 0.55:
        return str(R.randint(1, 1000))
    return format(Decimal(R.randint(1, 100000)) / Decimal(10 ** R.randint(1, 3)), "f")


def _formule(R, i, kpis, annees, profondeur=0):
    """Formule aléatoire du KPI d'indice ``i`` : références aux KPI numériques ; même période seulement vers les KPI
    précédents (pas de boucle), autres périodes vers tous, années fixes vers les précédents (pas de boucle dans le temps)."""
    numeriques = [k for k in kpis if k["fmt"] in ("nombre", "pourcentage")]
    moi = kpis[i - 1]
    # sources surtout du même niveau ou plus fines (agrégées), ou paramètres hérités : moins de cases incomplètes
    utiles = [k for k in numeriques if k["gran"] >= moi["gran"] or k["comp"] == "herite"]
    if utiles and R.random() < 0.85:
        numeriques = utiles
    avant = [k for k in numeriques if int(k["code"][1:]) < i]

    def ref():
        t = R.random()
        if t < 0.62 and avant:
            k, dec = R.choice(avant), R.choice(["", "", "", "@N"])
        elif t < 0.75 and numeriques:
            k, dec = R.choice(numeriques + [None]), "@N-1"
        elif t < 0.90 and numeriques:
            k, dec = R.choice(numeriques + [None]), "@P-1"
        elif avant:
            k, dec = R.choice(avant), "@" + str(R.choice([annees[0] - 1, annees[0], annees[0], annees[-1] + 1 if len(annees) > 1 else annees[0]]))
        else:
            return None
        code = f"K{i}" if k is None else k["code"]
        esp = R.choice(["", "", "", " "])
        if dec and R.random() < 0.1:
            dec = dec.replace("@", " @ ")
        return f"[{esp}{code}{dec}{esp}]"

    def const():
        return R.choice(["0", "1", "2", "3", "10", "100", "1000", "0.5", "1.25", "7"])

    def expr(d):
        if d >= 3 or (d > 0 and R.random() < 0.45):
            if R.random() < 0.72:
                r = ref()
                if r:
                    return r
            return const()
        op = R.choices(["+", "-", "*", "/"], [3, 2, 2, 3])[0]
        a, b = expr(d + 1), expr(d + 1)
        s = R.choice(["", " ", " ", "  "])
        texte = f"{a}{s}{op}{s}{b}"
        if R.random() < 0.08:
            texte = f"-{texte}" if R.random() < 0.5 else f"- ({texte})"
        return f"({texte})" if d > 0 and (R.random() < 0.6 or op in "+-") else texte

    f = expr(0)
    if "[" not in f:
        f = f"{ref() or f'[K{i}@P-1]'} + {f}"
    return f


def generate(seed):
    R = random.Random(seed)
    L = R.choice([1, 2, 2, 3, 3, 3, 4, 4, 5, 6])
    mois_debut = R.choice([1, 1, 1, 1, 4, 7])
    frequences = ["annee"] + (["mois"] if R.random() < 0.4 else []) + (["trimestre"] if R.random() < 0.2 else [])
    premiere = R.choice([2021, 2022, 2023])
    n_annees = R.choice([1, 2, 2, 3]) if "mois" in frequences else R.choice([1, 2, 3, 3, 4])
    annees = list(range(premiere, premiere + n_annees))
    statuts = ["ouverte", "revue", "cloturee", "preparation"]
    periods = []
    for a in annees:
        statut_annee = R.choices(statuts, [4, 1, 4, 1])[0]
        debut = datetime.date(a, mois_debut, 1)
        periods.append(dict(type="annee", debut=_date(debut), status=statut_annee))
        for f in ("trimestre", "mois"):
            if f not in frequences:
                continue
            for j in range(12 // MOIS_PAR[f]):
                if R.random() < 0.04:
                    continue  # période manquante : le cumul de l'année est incomplet
                d = IC.ajouter_mois(debut, j * MOIS_PAR[f])
                st = statut_annee if R.random() < 0.6 else R.choices(statuts, [4, 1, 3, 1])[0]
                periods.append(dict(type=f, debut=_date(d), status=st))
    # arbre
    orgs = []
    racines = R.choice([1, 1, 1, 2])
    for i in range(racines):
        orgs.append(dict(id=f"O{len(orgs)}", rank=1, parent=None, active=True, closed=None))
    for r in range(2, L + 1):
        n = R.randint(1 if r < L else 1, 3 if len(orgs) < 10 else 1)
        if R.random() < 0.08 and r < L:
            n = 0  # niveau sans organisation
        for _ in range(n):
            plus_haut = [o for o in orgs if o["rank"] < r]
            juste = [o for o in plus_haut if o["rank"] == r - 1]
            parent = R.choice(juste) if juste and R.random() < 0.85 else R.choice(plus_haut)
            orgs.append(dict(id=f"O{len(orgs)}", rank=r, parent=parent["id"], active=True, closed=None))
    # fermetures (les organisations en dessous ferment au plus tard en même temps)
    for o in orgs[racines:]:
        if R.random() < 0.15:
            o["active"] = False
            if R.random() < 0.8:
                a = R.choice(annees + [annees[0] - 1])
                o["closed"] = _date(datetime.date(a, R.randint(1, 12), R.choice([1, 15, 28])))
    par_id = {o["id"]: o for o in orgs}
    for o in orgs:  # dans l'ordre : les parents d'abord
        p = par_id.get(o["parent"]) if o["parent"] else None
        if p is not None and not p["active"]:
            if o["active"] or (o["closed"] and (p["closed"] is None or o["closed"] > p["closed"])) or (o["closed"] is None and p["closed"]):
                o["active"], o["closed"] = False, p["closed"]
    # KPI
    kpis = []
    n_kpis = R.randint(2, 9)
    for i in range(1, n_kpis + 1):
        comp = R.choices(["saisie", "calcul", "herite"], [55, 35, 10])[0] if i > 1 else "saisie"
        k = dict(code=f"K{i}", comp=comp, gran=R.randint(1, L), above=False, na0=False, formula="", active=R.random() < 0.95)
        if comp == "saisie":
            k["fmt"] = R.choices(["nombre", "pourcentage", "oui_non", "liste", "texte"], [66, 10, 10, 9, 5])[0]
            if k["fmt"] == "nombre":
                k["agg"] = R.choices(["Somme", "Aucune"], [80, 20])[0]
            elif k["fmt"] in ("pourcentage", "texte"):  # texte rédigé : jamais agrégé 
                k["agg"] = "Aucune"
            else:
                k["agg"] = R.choices(["Décompte", "Aucune"], [75, 25])[0]
            k["above"] = R.random() < 0.2 and k["fmt"] != "texte"
        elif comp == "herite":
            k["fmt"], k["agg"] = R.choices(["nombre", "pourcentage"], [85, 15])[0], "Aucune"
        else:
            k["fmt"] = R.choices(["nombre", "pourcentage"], [85, 15])[0]
            k["agg"] = R.choices(["Formule", "Somme", "Aucune"], [45, 40, 15])[0]
            if k["fmt"] == "pourcentage" and k["agg"] == "Somme":
                k["agg"] = "Formule"
            k["na0"] = R.random() < 0.35
        if k["fmt"] in ("nombre", "pourcentage"):
            k["temps"] = R.choice(["somme", "moyenne", "derniere", "aucune"]) if R.random() < 0.5 else (
                "derniere" if comp == "herite" else "moyenne" if k["fmt"] == "pourcentage" else "somme")
        elif k["fmt"] == "texte":
            k["temps"] = "aucune"
        else:
            k["temps"] = R.choice(["derniere", "derniere", "aucune"])
        fs = [f for f in frequences if R.random() < (0.9 if f == "annee" else 0.5)]
        k["freqs"] = fs if fs or R.random() < 0.3 else ["annee"]
        kpis.append(k)
    for i, k in enumerate(kpis, start=1):
        if k["comp"] == "calcul":
            k["formula"] = _formule(R, i, kpis, annees)
    _ouvertures(seed, orgs, annees, mois_debut)
    _autre_referentiel(seed, kpis)
    cas = dict(seed=seed, levels=L, mois_debut=mois_debut, frequencies=frequences, periods=periods, orgs=orgs, kpis=kpis,
               inputs=[], changes=[])
    _saisies(R, cas)
    _ouverture_apres_coup(seed, cas, annees)
    _ouverture_parent_apres_coup(seed, cas, annees)
    _apres_cloture(seed, cas, annees)
    _demande_depuis(seed, cas)
    _annuel_et_plus_frequent(seed, cas)
    _arbre_garde_n1(seed, cas)
    if V3:
        _tableaux_v3(seed, cas)
        _semestres_v3(seed, cas)
        _deuxieme_campagne_v3(seed, cas)
        _brouillon_site_ferme_v3(seed, cas)
        _ecritures_v3(seed, cas)
        _imports_calcules_v3(seed, cas)
    if V4:
        _demandes_seulement_v4(cas)
        _transparence_v4(seed, cas)
        _recloture_v4(seed, cas)
    _sans_chiffre_en_sommeil(cas)
    return cas


def _sans_chiffre_en_sommeil(cas):
    """Un chiffre importé sur la case d'un KPI calculé d'une période qui n'est pas figée au départ (une seconde campagne
    ouverte ajoutée à un exercice clos compris) est désormais une valeur forcée (``Oracle.origine_d_un_import``) : la
    règle de l'import ne laisse plus naître de chiffre « en sommeil », que la clôture rendait officiel sans recalcul
    (graines 13041, 14501, 15486). Seule l'origine change : aucun tirage de plus, les cas restent les mêmes."""
    calcules = {k["code"] for k in cas["kpis"] if k["comp"] == "calcul"}
    figees = {f"{p['type']}:{p['debut']}" for p in cas["periods"] if IC.statut_effectif(p) in ("cloturee", "gardee")}
    for s in cas["inputs"]:
        if s["origin"] == "import" and s["k"] in calcules and s["p"] not in figees:
            s["origin"] = "forcee"


def _periodes_visees(cas):
    """Clés des périodes que citent les changements déjà tirés (réouvertes, corrigées)."""
    return {ch["p"] for ch in cas["changes"] if "p" in ch}


def _tableaux_v3(seed, cas):
    """Format « tableau » (lignes en nombre variable, enregistré en tableau Markdown, hors de
    tout calcul) : des KPI « texte rédigé » deviennent des tableaux, et leurs réponses des tableaux Markdown."""
    R = random.Random(seed * 7919 + 59)
    textes = [k for k in cas["kpis"] if k["fmt"] == "texte"]
    if not textes or R.random() >= 0.6:
        return
    codes = set()
    for k in textes:
        if R.random() < 0.7:
            k["fmt"] = "tableau"
            codes.add(k["code"])
    for x in cas["inputs"] + [ch for ch in cas["changes"] if "k" in ch]:
        if x["k"] in codes and x.get("v") not in (None, "NA"):
            x["v"] = R.choice(TABLEAUX)


def _semestres_v3(seed, cas):
    """Un référentiel semestriel (forme jamais tirée avant la troisième passe) : semestres de chaque exercice, des KPI qui
    s'y collectent (leur année se cumule alors depuis les semestres, ou depuis les mois / trimestres s'ils sont plus
    fins), et leurs saisies."""
    R = random.Random(seed * 7919 + 47)
    if R.random() >= 0.3 or "semestre" in cas["frequencies"]:
        return
    cas["frequencies"] = cas["frequencies"] + ["semestre"]
    annees = [p for p in cas["periods"] if p["type"] == "annee"]
    nouvelles = []
    for a in annees:
        d = datetime.date.fromisoformat(a["debut"])
        for j in range(2):
            if R.random() < 0.05:
                continue  # semestre manquant : le cumul de l'année est incomplet
            st = a["status"] if R.random() < 0.7 else R.choice(["ouverte", "revue", "cloturee"])
            nouvelles.append(dict(type="semestre", debut=_date(IC.ajouter_mois(d, 6 * j)), status=st))
    cas["periods"] += nouvelles
    choisis = [k for k in cas["kpis"] if k["fmt"] not in ("texte", "tableau") and R.random() < 0.4]
    for k in choisis:
        k["freqs"] = list(k["freqs"]) + ["semestre"]
    o = IC.Oracle(cas)
    for p in nouvelles:
        q = o.periodes[IC.tuple_cle(f"semestre:{p['debut']}")]
        for k in choisis:
            if k["comp"] == "calcul" or o.freq[k["code"]] not in ("semestre",) and k["temps"] != "aucune":
                continue
            for x in cas["orgs"]:
                if o.ouverte(x["id"], q) and (x["rank"] == k["gran"] or (k["comp"] == "herite" and o.porte_lui_meme(k["code"], x["id"]))):
                    if R.random() < 0.9:
                        cas["inputs"].append(dict(k=k["code"], o=x["id"], p=f"semestre:{p['debut']}",
                                                  origin="import" if p["status"] == "cloturee" else "saisie",
                                                  v=_valeur_au_hasard(R, k)))


def _deuxieme_campagne_v3(seed, cas):
    """Deux campagnes sur un même exercice : un second référentiel annuel (« bis ») qui
    partage des KPI avec les autres, une campagne sur des exercices que les changements tirés ne visent pas, d'un statut
    tiré à part (l'une clôturée, l'autre ouverte : l'exercice n'est figé que si toutes ses campagnes sont clôturées)."""
    R = random.Random(seed * 7919 + 53)
    if R.random() >= 0.3:
        return
    visees = _periodes_visees(cas)
    annees = [p for p in cas["periods"] if p["type"] == "annee" and f"annee:{p['debut']}" not in visees]
    if not annees:
        return
    for p in R.sample(annees, R.randint(1, len(annees))):
        p["bis"] = R.choice(["ouverte", "cloturee", "cloturee", "revue"])
    communs = [k for k in cas["kpis"] if R.random() < 0.35]
    propres = [k for k in cas["kpis"] if k not in communs and R.random() < 0.2]
    for k in communs + propres:
        k["freqs"] = list(k["freqs"]) + ["bis"]
        if k in propres:
            k["freqs"] = [f for f in k["freqs"] if f in ("bis", "mois", "trimestre", "semestre")]


def _brouillon_site_ferme_v3(seed, cas):
    """Règle « Tout brouillon compte » : un site fermé pendant une période non figée qui n'a, sur
    la période, aucune valeur d'un KPI saisi (somme ou décompte, pas cumulé) mais un brouillon d'un autre KPI : le total
    des valeurs validées au-dessus est « en attente » (contrôle ``--pages``, ``_ecarts_brouillons``). Forme rare sans
    tirage exprès (les sites fermés ont presque toujours une valeur de chaque KPI)."""
    R = random.Random(seed * 7919 + 61)
    if R.random() >= 0.5:
        return
    o = IC.Oracle(cas)
    candidats = []
    for p in o.periodes.values():
        perimetre = o.perimetre(p)
        if o.figee(p) or p.fermees:
            continue
        for x in cas["orgs"]:
            if x["active"] or not o.ouverte(x["id"], p):
                continue
            ks = [k for k in cas["kpis"] if k["comp"] == "saisie" and k["gran"] == x["rank"] and k["active"]
                  and (perimetre is None or k["code"] in perimetre)]
            cle = f"{p.type}:{p.debut.isoformat()}"
            soeurs = {y["id"] for y in cas["orgs"] if y["parent"] == x["parent"] and y["id"] != x["id"] and y["active"]
                      and o.ouverte(y["id"], p)}
            for k in ks:
                # une organisation sœur active avec une valeur de K : sans le site fermé, le total serait un chiffre
                if not any(s["k"] == k["code"] and s["p"] == cle and s["o"] in soeurs and s["v"] is not None
                           for s in cas["inputs"]):
                    continue
                if k["agg"] in ("Somme", "Décompte") and not o.cumule(k["code"], p) and x["parent"] and \
                        o.produite(k["code"], x["parent"], p):
                    autres = [k2 for k2 in ks if k2 is not k and k2["fmt"] not in ("texte", "tableau")]
                    if autres:
                        candidats.append((p, x["id"], k, autres))
    if not candidats:
        return
    p, oid, k, autres = R.choice(candidats)
    k2, cle = R.choice(autres), f"{p.type}:{p.debut.isoformat()}"
    # le site fermé (et ce qui est en dessous) n'a sur la période que ce brouillon ; les autres valeurs de K sur la période
    # sont validées (reprises comme un import) : sans le site fermé, le total des valeurs validées serait un chiffre
    dessous = set(o.descendants(oid))
    cas["inputs"] = [s for s in cas["inputs"] if not (s["o"] in dessous and s["p"] == cle)]
    for s in cas["inputs"]:
        if s["p"] == cle and s["k"] == k["code"] and s["origin"] == "saisie" and s["v"] is not None:
            s["origin"] = "import"
    cas["inputs"].append(dict(k=k2["code"], o=oid, p=cle, origin="saisie", v=_valeur_au_hasard(R, k2, 0)))


# --v3 (troisième) : écritures de plus après les autres changements (validation, valeur forcée puis
# retour au calcul, lot de saisies comme un import, correction importée dans une campagne clôturée). Tirées à part
# (graine dérivée) et seulement sur demande : les cas des graines déjà jouées, et ceux de la suite, ne changent pas.
V3 = False


def _imports_calcules_v3(seed, cas):
    """Import de valeurs (``collecte/imports.py``, aperçu puis confirmation « Forcer ces valeurs ») d'un chiffre sur la case
    d'un KPI calculé d'un exercice non clôturé : la case devient une valeur forcée, et les totaux et les formules qui la
    lisent ([X@N-1] compris) suivent tout de suite. Graine dérivée : les autres tirages ne changent pas."""
    R = random.Random(seed * 7919 + 71)
    if R.random() >= 0.5:
        return
    courant = _cas_apres(cas, len(cas["changes"]))
    o = IC.Oracle(courant)
    # exercices ouverts d'une seule campagne (la ligne « Exercice » du fichier désigne la période sans ambiguïté)
    ouvertes = [p for p in o.periodes.values() if p.type == "annee" and not o.figee(p) and p.cle not in o.bis
                and not p.fermees]
    for _ in range(R.randint(1, 3)):
        if not ouvertes:
            return
        p = R.choice(ouvertes)
        perimetre = o.perimetre(p)
        cases = [(k, x["id"]) for k in cas["kpis"] if k["comp"] == "calcul" and k["active"] and k["fmt"] in ("nombre", "pourcentage")
                 and (perimetre is None or k["code"] in perimetre)
                 for x in o.arbre(p).values() if x["active"] and o.ouverte(x["id"], p)
                 and (x["rank"] == k["gran"] or (x["rank"] < k["gran"] and k["agg"] != "Aucune"))]
        if not cases:
            continue
        k, oid = R.choice(cases)
        origine = o.origine_d_un_import(p, k["code"])
        if origine is None:
            continue
        cas["changes"].append(dict(type="import_calcule", k=k["code"], o=oid, p=f"{p.type}:{p.debut.isoformat()}",
                                   origin=origine, v=_valeur_au_hasard(R, k, 0.1)))


def _ecritures_v3(seed, cas):
    R = random.Random(seed * 7919 + 43)
    if R.random() >= 0.6:
        return
    courant = _cas_apres(cas, len(cas["changes"]))
    courant["closure_orgs"] = copy.deepcopy(cas["orgs"])  # arbre noté à la clôture (``verifier``)
    o = IC.Oracle(courant)
    libres = [p for p in o.periodes.values() if not o.figee(p)]
    closes = [p for p in o.periodes.values() if p.statut == "cloturee"]
    closes = [p for p in closes if p.cle not in o.bis]  # une seule campagne sur la période (import sans ambiguïté)
    # deux campagnes sur l'exercice, l'une clôturée (règle « Figer ses chiffres ») : ses KPI ne se
    # saisissent pas dans l'autre (règle : saisie, import et assistants refusés) ; seule une correction importée dans
    # la campagne clôturée les change
    partielles = [p for p in libres if o.a_figer(p)]
    entrees = {(s["k"], s["o"], s["p"]): s for s in courant["inputs"]}
    ajouts = []

    def cle(p):
        return f"{p.type}:{p.debut.isoformat()}"

    def demande(k, p):
        perimetre = o.perimetre(p)
        return k["active"] and (perimetre is None or k["code"] in perimetre)

    def cases_saisies(p, figes=False):
        """Cases à saisir de la période ; ``figes`` : seulement celles des KPI figés par sa campagne clôturée (correction
        importée), sinon seulement les autres."""
        return [(k, x["id"]) for k in cas["kpis"] if k["comp"] in ("saisie", "herite") and k["fmt"] not in ("texte", "tableau") and demande(k, p)
                and (k["code"] in o.a_figer(p)) == figes
                for x in o.arbre(p).values() if o.ouverte(x["id"], p)
                and (x["rank"] == k["gran"] or (k["comp"] == "herite" and o.porte_lui_meme(k["code"], x["id"], p)))]

    def cases_calculees(p, figes=False):
        return [(k, x["id"]) for k in cas["kpis"] if k["comp"] == "calcul" and demande(k, p) and (k["code"] in o.a_figer(p)) == figes
                for x in o.arbre(p).values()
                if o.ouverte(x["id"], p) and (x["rank"] == k["gran"] or (x["rank"] < k["gran"] and k["agg"] != "Aucune"))]

    for _ in range(R.randint(1, 4)):
        t = R.random()
        if t < 0.15 and libres:  # validation d'une saisie (le statut seul change)
            p = R.choice(libres)
            brouillons = [s for s in entrees.values() if s["p"] == cle(p) and s["origin"] == "saisie" and s["v"] is not None
                          and o.kpis[s["k"]]["comp"] != "calcul"]
            if brouillons:
                s = R.choice(brouillons)
                ajouts.append(dict(type="validate", k=s["k"], o=s["o"], p=s["p"]))
        elif t < 0.45 and libres:  # valeur forcée sur une case calculée, parfois suivie du retour au calcul
            p = R.choice(libres)
            cases = cases_calculees(p)
            if cases:
                k, oid = R.choice(cases)
                ajouts.append(dict(type="force", k=k["code"], o=oid, p=cle(p), origin="forcee", v=_valeur_au_hasard(R, k, 0.15)))
                if R.random() < 0.6:
                    ajouts.append(dict(type="unforce", k=k["code"], o=oid, p=cle(p)))
        elif t < 0.75 and libres:  # lot de saisies (comme un import ou un paquet) : un seul recalcul par période
            cellules = []
            for _ in range(R.randint(2, 6)):
                p = R.choice(libres)
                cases = cases_saisies(p)
                if cases:
                    k, oid = R.choice(cases)
                    v = None if R.random() < 0.1 else _valeur_au_hasard(R, k, 0.15)
                    cellules.append(dict(k=k["code"], o=oid, p=cle(p), origin="saisie", v=v))
            if cellules:
                ajouts.append(dict(type="batch", cells=list({(c["k"], c["o"], c["p"]): c for c in cellules}.values())))
        elif closes or partielles:  # correction importée dans une campagne clôturée : l'organisation et ses totaux
            p = R.choice(closes + partielles)
            figes = p in partielles  # campagne clôturée à côté d'une ouverte : ses KPI figés
            cases = cases_saisies(p, figes) + (cases_calculees(p, figes) if R.random() < 0.3 else [])
            if cases:
                k, oid = R.choice(cases)
                ajouts.append(dict(type="import", k=k["code"], o=oid, p=cle(p), origin="import", v=_valeur_au_hasard(R, k, 0.1)))
    cas["changes"] += ajouts


# --v4 (quatrième passe) : une période rouverte puis reclôturée, l'arbre changé après la reclôture, puis rouverte une
# seconde fois et corrigée. Tirée à part (graine dérivée) et seulement sur demande : les autres cas ne changent pas.
V4 = False


def _recloture_v4(seed, cas):
    """README (« Reopening a past year ») : une deuxième clôture après « garder les chiffres de l'époque » garde l'arbre de
    la première ; après « recalculer avec l'organisation d'aujourd'hui », la clôture suivante note l'arbre de ce jour, et
    les chiffres enregistrés sont ceux du calcul de ce jour. Après la reclôture, une organisation est parfois déplacée,
    puis la période est rouverte une seconde fois (l'un des deux modes) et corrigée."""
    R = random.Random(seed * 7919 + 71)
    reouvertures = [ch for ch in cas["changes"] if ch.get("type") == "reopen"]
    if len(reouvertures) != 1 or R.random() >= 0.7:
        return
    cle = reouvertures[0]["p"]
    avant = len(cas["changes"])
    ajouts = [dict(type="reclose", p=cle)]
    orgs = _cas_apres(cas, avant)["orgs"]
    lignee = set()  # organisation déplacée et son parent d'avant : les corrections les visent d'abord
    if R.random() < 0.6:  # arbre changé après la reclôture
        feuilles = [x for x in orgs if x["parent"] and x["active"] and not any(y["parent"] == x["id"] for y in orgs)]
        if feuilles:
            x = R.choice(feuilles)
            parents = [y for y in orgs if y["rank"] < x["rank"] and y["id"] != x["parent"] and y["active"]]
            if parents:
                ajouts.append(dict(type="move", o=x["id"], parent=R.choice(parents)["id"]))
                lignee = {x["id"], x["parent"]}
    ajouts.append(dict(type="reopen", p=cle, mode="garder" if R.random() < 0.6 else "recalculer"))
    cas["changes"] += ajouts
    # corrections : cases saisies des organisations ouvertes dans l'arbre que suit la période rouverte
    c = _cas_apres(cas, len(cas["changes"]))
    c["closure_orgs"] = copy.deepcopy(cas["orgs"])
    if reouvertures[0]["mode"] != "garder":
        c["closure_orgs_by_period"] = {cle: copy.deepcopy(orgs)}
    o = IC.Oracle(c)
    p = o.periodes[IC.tuple_cle(cle)]
    arbre = o.arbre(p)
    possibles = [(k, x) for k in c["kpis"] if k["comp"] in ("saisie", "herite") and k["fmt"] not in ("texte", "tableau")
                 for x in arbre if o.ouverte(x, p)
                 and (arbre[x]["rank"] == k["gran"] or (k["comp"] == "herite" and o.porte_lui_meme(k["code"], x, p)))]
    visees = [(k, x) for k, x in possibles if x in lignee]
    for _ in range(R.randint(1, 3)):
        if not possibles:
            break
        k, oid = R.choice(visees if visees and R.random() < 0.7 else possibles)
        v = None if R.random() < 0.1 else _valeur_au_hasard(R, k, 0.1)
        cas["changes"].append(dict(type="fix", k=k["code"], o=oid, p=cle, origin="saisie", v=v))


def _demandes_seulement_v4(cas):
    """Valeurs de départ seulement là où un référentiel demande le KPI (« demandé depuis » posé à la création) : l'outil
    refuse une valeur hors du périmètre d'une période (saisie, import) et refuse de reculer la date d'un KPI qui a des
    valeurs. Sans cela, une période close notait dans son périmètre un KPI qu'elle ne demandait pas (il y avait une
    case), un état que l'outil ne permet pas d'atteindre (graine 16057)."""
    o = IC.Oracle(cas)
    garder = []
    for s in cas["inputs"]:
        p = o.periodes[IC.tuple_cle(s["p"])]
        perimetre = o.perimetre(p)
        if perimetre is None or s["k"] in perimetre:
            garder.append(s)
    cas["inputs"] = garder


def _transparence_v4(seed, cas):
    """Forme du modèle de transparence des rémunérations (``referentiel/bibliotheque/definitions``) : effectifs saisis
    (somme), moyennes saisies sans valeur au-dessus, totaux calculés additionnés (moyenne × effectif), écart recalculé à
    chaque niveau sur les totaux (agrégation « Formule », pourcentage), part des femmes d'un quartile saisie et part des
    hommes calculée (100 % moins la part des femmes, sans valeur au-dessus). N/A d'un employeur qui ne déclare pas (ses
    effectifs et ses moyennes), effectif nul, organisations ouvertes ou fermées en cours d'année ; puis quelques saisies
    après le premier calcul, dans les exercices non figés."""
    R = random.Random(seed * 7919 + 79)
    if R.random() >= 0.35:
        return
    L, n = cas["levels"], len(cas["kpis"])
    g = R.choice([L, L, max(1, L - 1), R.randint(1, L)])
    nbf, nbh, mf, mh, tf, th, ec, qf, qh = (f"K{n + i}" for i in range(1, 10))
    base = dict(above=False, na0=False, formula="", active=True, freqs=["annee"], gran=g)
    cas["kpis"] += [
        dict(base, code=nbf, comp="saisie", fmt="nombre", agg="Somme", temps="derniere"),
        dict(base, code=nbh, comp="saisie", fmt="nombre", agg="Somme", temps="derniere"),
        dict(base, code=mf, comp="saisie", fmt="nombre", agg="Aucune", temps="derniere"),
        dict(base, code=mh, comp="saisie", fmt="nombre", agg="Aucune", temps="derniere"),
        dict(base, code=tf, comp="calcul", fmt="nombre", agg="Somme", temps="somme", formula=f"[{mf}] * [{nbf}]"),
        dict(base, code=th, comp="calcul", fmt="nombre", agg="Somme", temps="somme", formula=f"[{mh}] * [{nbh}]"),
        dict(base, code=ec, comp="calcul", fmt="pourcentage", agg="Formule", temps="moyenne",
             formula=f"([{th}] / [{nbh}] - [{tf}] / [{nbf}]) / ([{th}] / [{nbh}])"),
        dict(base, code=qf, comp="saisie", fmt="pourcentage", agg="Aucune", temps="derniere"),
        dict(base, code=qh, comp="calcul", fmt="pourcentage", agg="Aucune", temps="moyenne", formula=f"1 - [{qf}]"),
    ]
    o = IC.Oracle(cas)

    def valeurs(R):
        if R.random() < 0.1:  # employeur qui ne déclare pas : N/A
            return ["NA", "NA", "NA", "NA", "NA"]
        nf, nh = (str(0 if R.random() < 0.08 else R.randint(1, 400)) for _ in range(2))  # effectif nul parfois
        return [nf, nh, str(R.randint(20000, 90000)), str(R.randint(20000, 90000)),
                format(Decimal(R.randint(0, 100)) / 100, "f")]

    for p in cas["periods"]:
        if p["type"] != "annee":
            continue
        q = o.periodes[(p["type"], datetime.date.fromisoformat(p["debut"]))]
        cle = f"annee:{p['debut']}"
        for x in cas["orgs"]:
            if x["rank"] != g or not o.ouverte(x["id"], q) or R.random() < 0.08:
                continue
            for k, v in zip((nbf, nbh, mf, mh, qf), valeurs(R)):
                if R.random() < 0.97:
                    cas["inputs"].append(dict(k=k, o=x["id"], p=cle, origin="saisie", v=v))
    courant = _cas_apres(cas, len(cas["changes"]))
    oc = IC.Oracle(courant)
    libres = [q for q in oc.periodes.values() if q.type == "annee" and not oc.figee(q)]
    for _ in range(R.randint(0, 3)):
        if not libres:
            break
        q = R.choice(libres)
        orgs = [x for x in oc.arbre(q) if oc.rang(x, q) == g and oc.ouverte(x, q)]
        k, v = R.choice(list(zip((nbf, nbh, mf, mh, qf), valeurs(R))))
        # KPI figé par une campagne clôturée de l'exercice (règle « Figer ses chiffres ») : sa saisie est refusée
        if orgs and k not in oc.a_figer(q):
            cas["changes"].append(dict(k=k, o=R.choice(orgs), p=f"annee:{q.debut.isoformat()}", origin="saisie", v=v))


def _sans_remplacees(c, remplacees):
    """Le cas ``c`` sans les anciennes saisies de KPI devenus calculés que le premier calcul a remplacées (``verifier``) ;
    une valeur écrite ensuite sur la même case (forcée, importée) reste."""
    c["inputs"] = [s for s in c["inputs"] if not (s["origin"] == "saisie" and (s["k"], s["o"], s["p"]) in remplacees)]
    return c


class _Memoires:
    """Valeurs enregistrées des périodes figées, vues par le second calcul : celles du premier calcul du cas (``defaut``),
    sauf pour une période reclôturée après une réouverture « recalculer » : le calcul du jour de la reclôture (``par``)."""

    def __init__(self, defaut):
        self.defaut, self.par = defaut, {}

    def _o(self, p):
        """(second calcul, la période vue par lui) : un calcul de reclôture lit la période telle qu'il la voit (non
        figée), pas l'objet de l'appelant (où elle est close)."""
        s = self.par.get(p.cle)
        return (self.defaut, p) if s is None else (s, s.periodes[p.cle])

    def produite(self, k, o, p):
        s, q = self._o(p)
        return s.produite(k, o, q)

    def valeur(self, c, k, o, p):
        s, q = self._o(p)
        return s.valeur(q if c.cle == p.cle else c, k, o, q)

    def attendu(self, k, o, p):
        s, q = self._o(p)
        return s.attendu(k, o, q)


def _arbre_garde_n1(seed, cas):
    """Cas rare tiré exprès (recalcul ciblé dans l'arbre de chaque période) : un exercice clos
    suivi d'un exercice ouvert ; deux KPI de plus, une formule [X@N-1] refaite au-dessus de sa granularité (agrégation
    « Formule ») et une formule qui lit un paramètre hérité par [FE@N-1] ; après la clôture, une organisation est
    déplacée sous un autre parent, l'exercice clos est rouvert en gardant les chiffres de l'époque, puis corrigé (la
    valeur de l'organisation déplacée, le facteur de son parent de l'époque). Seulement sans autre réouverture dans le
    cas. Tiré à part (graine dérivée) : les autres tirages ne changent pas."""
    R = random.Random(seed * 7919 + 37)
    if R.random() >= 0.5 or cas["levels"] < 2 or any(ch.get("type") == "reopen" for ch in cas["changes"]):
        return
    annees = sorted((p for p in cas["periods"] if p["type"] == "annee"), key=lambda p: p["debut"])
    if annees and annees[-1]["status"] == "cloturee":  # exercice suivant, ouvert (sans saisie des autres KPI)
        d = datetime.date.fromisoformat(annees[-1]["debut"])
        annees.append(dict(type="annee", debut=_date(d.replace(year=d.year + 1)), status="ouverte"))
        cas["periods"].append(annees[-1])
    paires = [(a, b) for a, b in zip(annees, annees[1:]) if a["status"] == "cloturee" and b["status"] != "cloturee"]
    if not paires:
        return
    clos, ouvert = R.choice(paires)
    courant = _cas_apres(cas, len(cas["changes"]))["orgs"]  # l'arbre après les changements déjà tirés
    L = cas["levels"]
    parents = [o for o in courant if o["rank"] < L and o["active"]]
    feuilles = [o for o in courant if o["rank"] == L and o["active"] and o["parent"]
                and not any(y["parent"] == o["id"] for y in courant)]
    if len(parents) < 2 or not feuilles:
        return
    x = R.choice(feuilles)
    nouveau = R.choice([p for p in parents if p["id"] != x["parent"]])
    rangs = {o["id"]: o["rank"] for o in courant}
    ancien = x["parent"] if rangs[x["parent"]] == L - 1 else x["id"]  # facteur du parent de l'époque (ou le sien)
    n = len(cas["kpis"])
    eff, fe = f"K{n + 1}", f"K{n + 2}"
    base = dict(above=False, na0=False, formula="", active=True, freqs=["annee"])
    cas["kpis"] += [
        dict(base, code=eff, comp="saisie", gran=L, fmt="nombre", agg="Somme", temps="somme"),
        dict(base, code=fe, comp="herite", gran=L - 1, fmt="nombre", agg="Aucune", temps="derniere"),
        dict(base, code=f"K{n + 3}", comp="calcul", gran=L, fmt="nombre", agg="Formule", temps="somme",
             formula=f"[{eff}] - [{eff}@N-1]"),
        dict(base, code=f"K{n + 4}", comp="calcul", gran=L, fmt="nombre", agg="Somme", temps="somme",
             formula=f"[{eff}] * [{fe}@N-1]"),
    ]
    o = IC.Oracle(cas)
    for p in (clos, ouvert):
        q = o.periodes[(p["type"], datetime.date.fromisoformat(p["debut"]))]
        cle = f"{p['type']}:{p['debut']}"
        for org in cas["orgs"]:
            if not o.ouverte(org["id"], q):
                continue
            if org["rank"] == L and R.random() < 0.95:
                cas["inputs"].append(dict(k=eff, o=org["id"], p=cle, origin="saisie", v=str(R.randint(1, 50))))
            elif org["rank"] == L - 1 and R.random() < 0.95:
                cas["inputs"].append(dict(k=fe, o=org["id"], p=cle, origin="saisie", v=str(R.randint(1, 9))))
    cle = f"{clos['type']}:{clos['debut']}"
    cas["changes"] += [dict(type="move", o=x["id"], parent=nouveau["id"]), dict(type="reopen", p=cle, mode="garder"),
                       dict(type="fix", k=eff, o=x["id"], p=cle, origin="saisie", v=str(R.randint(51, 99))),
                       dict(type="fix", k=fe, o=ancien, p=cle, origin="saisie", v=str(R.randint(10, 19)))]


def _annuel_et_plus_frequent(seed, cas):
    """Un KPI cumulé, dans le référentiel annuel ET dans un référentiel plus fréquent, avec
    des dates « demandé depuis » différentes (le plus fréquent en cours d'exercice ; l'annuel depuis toujours, ou plus
    tard). Tiré à part (graine dérivée) : les autres tirages ne changent pas."""
    R = random.Random(seed * 7919 + 41)
    if R.random() >= 0.35:
        return
    fines = [f for f in cas["frequencies"] if f != "annee"]
    if not fines or "annee" not in cas["frequencies"]:
        return
    candidats = [k for k in cas["kpis"] if k["comp"] in ("saisie", "herite") and k["fmt"] in ("nombre", "pourcentage")
                 and k["temps"] != "aucune"]
    if not candidats:
        return
    k, f = R.choice(candidats), R.choice(fines)
    k["freqs"] = sorted(set(k["freqs"]) | {"annee", f}, key=lambda x: (x == "autre", x))
    debuts = sorted(q["debut"] for q in cas["periods"] if q["type"] == f)
    annees = sorted(q["debut"] for q in cas["periods"] if q["type"] == "annee")
    if not debuts:
        return
    k.setdefault("depuis", {})[f] = R.choice(debuts)
    k["depuis"]["annee"] = None if R.random() < 0.5 or not annees else R.choice(annees)
    if k["depuis"]["annee"] is None:
        del k["depuis"]["annee"]


def _demande_depuis(seed, cas):
    """« Demandé depuis » : des KPI d'un référentiel demandés seulement à partir d'une période
    (posé à la création), et des dates avancées ou reculées après coup par la gestion des KPI (un recul que l'outil
    refuse, faute de quoi il retirerait des valeurs ou toucherait une campagne clôturée, est noté « refuse » par
    l'exécution et ne compte pas). Tiré à part (graine dérivée) : les autres tirages ne changent pas."""
    R = random.Random(seed * 7919 + 31)
    debuts = {}
    for q in cas["periods"]:
        debuts.setdefault(q["type"], []).append(q["debut"])
    elements = [(k, f) for k in cas["kpis"] for f in k["freqs"] if f in debuts]
    if not elements:
        return
    if R.random() < 0.35:
        for k, f in elements:
            if R.random() < 0.35:
                k.setdefault("depuis", {})[f] = R.choice(sorted(debuts[f]))
    if R.random() < 0.4:
        for _ in range(R.randint(1, 3)):
            k, f = R.choice(elements)
            ch = dict(type="depuis", k=k["code"], f=f, date=R.choice(sorted(debuts[f])))
            cas["changes"].insert(R.randint(0, len(cas["changes"])), ch)


def _apres_cloture(seed, cas, annees):
    """(arbre gardé à chaque clôture) : après la clôture, l'arbre change (organisations déplacées,
    créées, fermées), puis une période close est rouverte (« garder les chiffres de l'époque » ou « recalculer avec
    l'organisation d'aujourd'hui ») et corrigée. Une seule période rouverte par cas. Tiré à part (graine dérivée) : les
    autres tirages ne changent pas."""
    R = random.Random(seed * 7919 + 29)
    if R.random() >= 0.45:
        return
    closes = [q for q in cas["periods"] if q["status"] == "cloturee"]
    if not closes:
        return
    q = R.choice(closes)
    cle = f"{q['type']}:{q['debut']}"
    ajouts = []
    courant = _cas_apres(cas, len(cas["changes"]))  # l'arbre après les changements déjà tirés
    orgs = courant["orgs"]
    for _ in range(R.randint(1, 3)):
        t = R.random()
        feuilles = [x for x in orgs if x["parent"] and not any(y["parent"] == x["id"] for y in orgs)]
        if t < 0.5 and feuilles:  # déplacée
            x = R.choice(feuilles)
            parents = [y for y in orgs if y["rank"] < x["rank"] and y["id"] != x["parent"] and y["active"]]
            if parents:
                ch = dict(type="move", o=x["id"], parent=R.choice(parents)["id"])
                x["parent"] = ch["parent"]
                ajouts.append(ch)
        elif t < 0.8 and cas["levels"] > 1:  # créée
            r = R.randint(2, cas["levels"])
            parents = [y for y in orgs if y["rank"] < r and y["active"]]
            if parents:
                juste = [y for y in parents if y["rank"] == r - 1]
                parent = R.choice(juste) if juste and R.random() < 0.85 else R.choice(parents)
                ch = dict(type="create", o=f"N{len(orgs)}", rank=r, parent=parent["id"])
                orgs.append(dict(id=ch["o"], rank=r, parent=parent["id"], active=True, closed=None, opened=None))
                ajouts.append(ch)
        else:  # fermée (sans organisation ouverte en dessous)
            fermables = [x for x in orgs if x["parent"] and x["active"]
                         and not any(y["parent"] == x["id"] and y["active"] for y in orgs)]
            if fermables:
                x = R.choice(fermables)
                debut = min(datetime.date.fromisoformat(z["debut"]) for z in cas["periods"])
                ch = dict(type="close", o=x["id"], date=_date(debut + datetime.timedelta(days=R.randint(0, 365 * 2))))
                x["active"], x["closed"] = False, ch["date"]
                ajouts.append(ch)
    ajouts.append(dict(type="reopen", p=cle, mode="garder" if R.random() < 0.7 else "recalculer"))
    o = IC.Oracle(cas)  # corrections : sur des cases saisies de l'arbre de la clôture
    p = o.periodes[IC.tuple_cle(cle)]
    possibles = [(k, x["id"]) for k in cas["kpis"] if k["comp"] in ("saisie", "herite") for x in cas["orgs"]
                 if o.ouverte(x["id"], p) and (x["rank"] == k["gran"] or (k["comp"] == "herite" and o.porte_lui_meme(k["code"], x["id"])))]
    for _ in range(R.randint(1, 3)):
        if not possibles:
            break
        k, oid = R.choice(possibles)
        v = None if R.random() < 0.1 else _valeur_au_hasard(R, k, 0.1)
        ajouts.append(dict(type="fix", k=k["code"], o=oid, p=cle, origin="saisie", v=v))
    cas["changes"] += ajouts


def _date_au_hasard(R, annees, mois_debut):
    """Une date entre l'exercice d'avant le premier et la fin du dernier : souvent un début d'exercice ou de mois."""
    a = R.choice([annees[0] - 1] + annees)
    m = mois_debut if R.random() < 0.4 else R.randint(1, 12)
    return datetime.date(a + (1 if m < mois_debut and R.random() < 0.5 else 0), m, R.choice([1, 1, 15, 28]))


def _ouvertures(seed, orgs, annees, mois_debut):
    """Dates d'ouverture, tirées à part (graine dérivée) : les cas des graines déjà jouées
    restent les mêmes, avec des dates en plus. Une organisation s'ouvre au plus tôt avec son parent et au plus tard à
    sa fermeture (comme la fiche l'exige)."""
    R = random.Random(seed * 7919 + 13)
    par_id = {o["id"]: o for o in orgs}
    for o in orgs:  # dans l'ordre : les parents d'abord
        o["opened"] = None
        if o["parent"] and R.random() < 0.2:
            o["opened"] = _date(_date_au_hasard(R, annees, mois_debut))
        p = par_id.get(o["parent"]) if o["parent"] else None
        if p is not None and p.get("opened") and (o["opened"] is None or o["opened"] < p["opened"]):
            o["opened"] = p["opened"] if R.random() < 0.7 else None
        if o["opened"] and o.get("closed") and o["opened"] > o["closed"]:
            o["opened"] = None


def _autre_referentiel(seed, kpis):
    """Un référentiel annuel de plus, sans aucune campagne (« autre ») : ses KPI n'ont de case dans aucune période qui
    ne les demande pas par un autre référentiel. Tiré à part (graine dérivée)."""
    R = random.Random(seed * 7919 + 19)
    if R.random() >= 0.3:
        return
    for k in R.sample(kpis, min(len(kpis), R.choice([1, 1, 2]))):
        k["freqs"] = list(k["freqs"]) + ["autre"]


def _ouverture_apres_coup(seed, cas, annees):
    """Date d'ouverture posée après coup par la fiche (organisation sans enfant ouverte plus tôt qu'elle)."""
    R = random.Random(seed * 7919 + 17)
    if R.random() >= 0.2:
        return
    feuilles = [x for x in cas["orgs"] if x["parent"] and x["active"] and not any(y["parent"] == x["id"] for y in cas["orgs"])]
    if not feuilles:
        return
    x = R.choice(feuilles)
    date = _date_au_hasard(R, annees, cas["mois_debut"])
    parent = next(y for y in cas["orgs"] if y["id"] == x["parent"])
    if parent.get("opened") and _date(date) < parent["opened"]:
        return
    cas["changes"].insert(R.randint(0, len(cas["changes"])), dict(type="open", o=x["id"], date=_date(date)))


def _ouverture_parent_apres_coup(seed, cas, annees):
    """Date d'ouverture posée après coup sur une organisation qui a des enfants : elle vaut
    aussi pour les organisations en dessous. Tirée à part (graine dérivée) : les autres tirages ne changent pas."""
    R = random.Random(seed * 7919 + 23)
    if R.random() >= 0.25:
        return
    parents = [x for x in cas["orgs"] if x["parent"] and x["active"] and any(y["parent"] == x["id"] for y in cas["orgs"])]
    if not parents:
        return
    x = R.choice(parents)
    date = _date_au_hasard(R, annees, cas["mois_debut"])
    cas["changes"].insert(R.randint(0, len(cas["changes"])), dict(type="open", o=x["id"], date=_date(date)))


# réponses rédigées (format « texte rédigé ») : n'entrent dans aucun calcul ; le moteur ne doit jamais s'y arrêter
TEXTES = ("# Politique\n- **charte** signée", "Texte *simple*.", "1. un\n2. deux", "[lien](https://example.org)")
TABLEAUX = ("| N | T |\n|---|---|\n| 12 | site A |", "| N | T |\n|---|---|\n| 1.5 | x |\n| 3 | y |")


def _valeur_au_hasard(R, k, na=0.08):
    if R.random() < na:
        return "NA"
    if k["fmt"] == "oui_non":
        return R.choice(["Oui", "Non"])
    if k["fmt"] == "liste":
        return R.choice(["A", "B", "C"])
    if k["fmt"] == "texte":
        return R.choice(TEXTES)
    if k["fmt"] == "tableau":
        return R.choice(TABLEAUX)
    return _nombre(R, k["fmt"] == "pourcentage")


def _saisies(R, cas):
    """Saisies, imports, valeurs forcées ; puis les changements de la seconde étape (saisies dans des périodes non figées)."""
    o = IC.Oracle(cas)
    entrees = {}
    densite = R.choice([0.8, 0.95, 1.0, 1.0])  # part des cases saisies (1 : tout est saisi, les totaux sont complets)
    for p in o.periodes.values():
        figee = o.figee(p)
        for k in cas["kpis"]:
            plus_fine = o.freq[k["code"]]
            for org in cas["orgs"]:
                oid = org["id"]
                if not o.ouverte(oid, p):
                    continue
                ro, rk = org["rank"], k["gran"]
                origine = "import" if R.random() < (0.5 if figee else 0.12) else "saisie"
                if k["comp"] in ("saisie", "herite") and (ro == rk or (k["comp"] == "herite" and o.porte_lui_meme(k["code"], oid))):
                    collectee = p.type in (k["freqs"] or []) and (plus_fine == p.type or k["temps"] == "aucune")
                    if R.random() < (densite if collectee else 0.04):
                        entrees[(k["code"], oid, p)] = (origine, _valeur_au_hasard(R, k))
                elif k["comp"] == "saisie" and ro < rk:
                    if k["above"] and R.random() < 0.3:
                        entrees[(k["code"], oid, p)] = (origine, _valeur_au_hasard(R, k))
                    elif k["agg"] != "Aucune" and R.random() < (0.12 if figee else 0.04):
                        entrees[(k["code"], oid, p)] = ("import", _valeur_au_hasard(R, k))  # total publié (fichier historique)
                elif k["comp"] == "calcul" and ro <= rk and (ro == rk or k["agg"] != "Aucune"):
                    t = R.random()
                    if t < (0.15 if figee else 0.05):
                        # période non figée : devient une valeur forcée (``_sans_chiffre_en_sommeil``)
                        entrees[(k["code"], oid, p)] = ("import", _valeur_au_hasard(R, k))
                    elif t < (0.18 if figee else 0.08):
                        entrees[(k["code"], oid, p)] = ("forcee", _valeur_au_hasard(R, k))
                    elif t < (0.20 if figee else 0.10):
                        entrees[(k["code"], oid, p)] = ("saisie", _valeur_au_hasard(R, k))  # avant le passage en « Calculé »
    cas["inputs"] = [dict(k=k, o=oid, p=f"{p.type}:{p.debut.isoformat()}", origin=origine, v=v)
                     for (k, oid, p), (origine, v) in entrees.items()]
    # changements : saisies (origine « saisie ») de KPI saisis, dans des périodes non figées
    possibles = [(k, oid, p) for (k, oid, p), (origine, v) in entrees.items()
                 if not o.figee(p) and origine == "saisie" and o.kpis[k]["comp"] != "calcul"]
    for _ in range(R.choice([0, 1, 2, 3])):
        if not possibles:
            break
        k, oid, p = R.choice(possibles)
        v = None if R.random() < 0.15 else _valeur_au_hasard(R, o.kpis[k], 0.1)
        cas["changes"].append(dict(k=k, o=oid, p=f"{p.type}:{p.debut.isoformat()}", origin="saisie", v=v))
    # fermeture d'une organisation après coup (sans organisation ouverte en dessous) : les périodes non figées sont
    # refaites, les périodes figées gardent leurs valeurs
    if R.random() < 0.3:
        fermables = [x for x in cas["orgs"] if x["parent"] and x["active"]
                     and not any(y["parent"] == x["id"] and y["active"] for y in cas["orgs"])]
        if fermables:
            x = R.choice(fermables)
            debut = min(datetime.date.fromisoformat(q["debut"]) for q in cas["periods"])
            date = debut + datetime.timedelta(days=R.randint(0, 365 * 2))
            cas["changes"].insert(R.randint(0, len(cas["changes"])), dict(type="close", o=x["id"], date=_date(date)))
    # rattachement ailleurs (organisation sans enfant, vers un parent d'un niveau supérieur)
    if R.random() < 0.2:
        feuilles = [x for x in cas["orgs"] if x["parent"] and not any(y["parent"] == x["id"] for y in cas["orgs"])]
        if feuilles:
            x = R.choice(feuilles)
            parents = [y for y in cas["orgs"] if y["rank"] < x["rank"] and y["id"] != x["parent"] and y["active"]]
            if parents:
                cas["changes"].insert(R.randint(0, len(cas["changes"])), dict(type="move", o=x["id"], parent=R.choice(parents)["id"]))


# ---------------------------------------------------------------- l'outil
DJANGO_PRET = False
GARDER_URL = False  # --postgres : la base de DATABASE_URL (sinon SQLite en mémoire)
PLEIN_DEMANDE = False  # --full-check


def preparer_django():
    """Django sur une base de test en mémoire (le dossier des données est un dossier temporaire)."""
    global DJANGO_PRET
    from django.apps import apps

    if DJANGO_PRET or apps.ready:  # déjà prêt (tests de l'outil : la base de test existe)
        return
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fuzz-")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if not GARDER_URL:
        os.environ.pop("DATABASE_URL", None)
    import django

    django.setup()
    from django.db import connection
    from django.test.utils import setup_test_environment

    setup_test_environment()
    connection.creation.create_test_db(verbosity=0, autoclobber=True, keepdb=False)
    DJANGO_PRET = True


class _Annuler(Exception):
    pass


def executer(cas, n1=None):
    """Construit le cas dans la base, le calcule avec l'outil et renvoie les états successifs :
    [("initial", lignes), ("pass2", lignes), ("change1", lignes)…] ; lignes : {(type, début, KPI, org): (...)}.
    ``n1`` (liste) : reçoit les comparaisons avec N-1 de l'état final (``_comparaisons_n1``)."""
    preparer_django()
    from django.db import transaction

    etats = []
    try:
        with transaction.atomic():
            _executer(cas, etats, n1)
            raise _Annuler()
    except _Annuler:
        pass
    return etats


def _executer(cas, etats, n1=None):
    from collecte import periodes as P
    from collecte.calcul import recalculer
    from collecte.models import Reponse
    from parametres.models import NiveauHierarchique, TypeReponse, TypeSaisie
    from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel, verifier_formule

    Referentiel.objects.all().delete()
    KPI.objects.all().delete()
    NiveauHierarchique.objects.all().delete()
    for r in range(1, cas["levels"] + 1):
        n = NiveauHierarchique(code=f"N{r}", rang=r, nom=f"Niveau {r}", nom_pluriel=f"Niveaux {r}", couleur="#1F5FAD")
        n.deriver_couleurs()
        n.save()
    TypeReponse.objects.get_or_create(code="OuiNon", defaults=dict(libelle="Oui / non", format="oui_non"))
    TypeReponse.objects.get_or_create(code="Liste", defaults=dict(libelle="Liste", format="liste", valeurs=["A", "B", "C"]))
    TypeReponse.objects.get_or_create(code="TexteRedige", defaults=dict(libelle="Texte rédigé", format="texte"))
    TypeReponse.objects.get_or_create(code="TableauFuzz", defaults=dict(libelle="Tableau", format="tableau", colonnes=[
        {"code": "n", "libelle": {"fr": "N"}, "type": "nombre"}, {"code": "t", "libelle": {"fr": "T"}, "type": "texte"}]))
    types_reponse = {"nombre": "Numérique", "pourcentage": "Pourcentage", "oui_non": "OuiNon", "liste": "Liste", "texte": "TexteRedige",
                     "tableau": "TableauFuzz"}
    types_saisie = {t.comportement: t.code for t in TypeSaisie.objects.all()}
    refs = {}
    for i, f in enumerate(cas["frequencies"], start=1):
        refs[f] = Referentiel.objects.create(code=f"R{f.upper()[:3]}", nom=f"Référentiel {f}", frequence=f,
                                             mois_debut=cas["mois_debut"], ordre=i)
    if any("bis" in k["freqs"] for k in cas["kpis"]) or any(p.get("bis") for p in cas["periods"]):  # second annuel
        refs["bis"] = Referentiel.objects.create(code="RBIS", nom="Second référentiel annuel", frequence="annee",
                                                 mois_debut=cas["mois_debut"], ordre=8)
    if any("autre" in k["freqs"] for k in cas["kpis"]):  # référentiel annuel sans campagne (``_autre_referentiel``)
        refs["autre"] = Referentiel.objects.create(code="RAUT", nom="Autre référentiel", frequence="annee",
                                                   mois_debut=cas["mois_debut"], ordre=9)
    orgs = {}
    for o in cas["orgs"]:
        orgs[o["id"]] = Organisation.objects.create(
            nom=o["id"], niveau_id=f"N{o['rank']}", parent=orgs.get(o["parent"]), actif=o["active"],
            date_desactivation=datetime.date.fromisoformat(o["closed"]) if o.get("closed") else None,
            date_ouverture=datetime.date.fromisoformat(o["opened"]) if o.get("opened") else None)
    for k in cas["kpis"]:
        kpi = KPI(code=k["code"], type_saisie_id=types_saisie[k["comp"]], type_reponse_id=types_reponse[k["fmt"]],
                  formule=k["formula"], granularite_id=f"N{k['gran']}", methode_agregation=k["agg"],
                  agregation_temps=k["temps"], saisie_au_dessus=k["above"], na_compte_zero=k["na0"], actif=k["active"])
        kpi.agregation_temps_choisie = kpi.na_compte_zero_choisi = True
        erreurs = kpi.erreurs_regles()
        if erreurs:
            raise ValueError(f"invalid generated KPI {k['code']}: {erreurs}")
        kpi.save()
        for j, f in enumerate(k["freqs"]):
            depuis = (k.get("depuis") or {}).get(f)
            e = ElementReferentiel(referentiel=refs[f], kpi=kpi, ordre=j,
                                   demande_depuis=datetime.date.fromisoformat(depuis) if depuis else None)
            e.depuis_choisi = True
            e.save()
    codes = {k["code"] for k in cas["kpis"]}
    for k in cas["kpis"]:
        if k["comp"] == "calcul":
            verifier_formule(k["code"], k["formula"], kpis_existants=codes)
    periodes = {}
    for p in cas["periods"]:
        d = datetime.date.fromisoformat(p["debut"])
        c, _ = P.campagne(refs[p["type"]], d, statut=p["status"])
        periodes[(p["type"], d)] = c.periode
        if p.get("bis"):  # seconde campagne sur le même exercice
            P.campagne(refs["bis"], d, statut=p["bis"])
    from collecte.models import Periode

    # campagnes créées d'un coup avec leur statut : rien n'est encore figé (la note se fait après le premier calcul,
    # comme une campagne clôturée après sa saisie ; règle « Figer ses chiffres »)
    Periode.objects.update(figes_partiels=None)
    statut_de = {"import": Reponse.Statut.VALIDE, "forcee": Reponse.Statut.VALIDE, "saisie": Reponse.Statut.BROUILLON}
    lignes = []
    for s in cas["inputs"]:
        lignes.append(Reponse(periode=periodes[IC.tuple_cle(s["p"])], kpi_id=s["k"], organisation=orgs[s["o"]],
                              origine=s["origin"], statut=statut_de[s["origin"]], **_champs(s["v"])))
    Reponse.objects.bulk_create(lignes)
    ordre = sorted(periodes.values(), key=lambda q: (q.fin, IC.FINESSE[q.type]))
    for q in ordre:
        recalculer(q)
    etats.append(("initial", _lire(periodes)))
    from collecte.calcul import noter_arbres_clos

    noter_arbres_clos()  # arbre des périodes closes noté, comme à une clôture 
    from collecte.calcul import noter_figes_partiels_existants

    # KPI d'une campagne clôturée à côté d'une campagne ouverte figés, comme à sa clôture 
    noter_figes_partiels_existants()
    if V3:  # périmètre des périodes closes noté aussi, comme la mise à jour (``collecte/0041``) ou une clôture
        from collecte.calcul import geler_periodes_closes

        geler_periodes_closes()
    for q in ordre:
        if not _figee(cas, q):
            recalculer(q)
    etats.append(("pass2", _lire(periodes)))
    for i, ch in enumerate(cas["changes"], start=1):
        _un_changement(cas, ch, i, etats, orgs, refs, periodes)
        if PLEIN is not None:  # recalcul ciblé (ou partiel) = recalcul complet de toutes les périodes libres
            ecarts = _ecarts_au_complet(periodes, ordre, etats[-1][1])
            if ecarts:
                PLEIN.append(dict(step=f"change{i}", change=ch, cells=ecarts[:8], n=len(ecarts)))
    if n1 is not None:  # comparaisons avec N-1 (``verifier``), seulement sur demande
        n1.extend(_comparaisons_n1(orgs))
    if PAGES is not None:
        PAGES.extend(_ecarts_des_pages(periodes, _gelees_du_cas(cas)))


def _gelees_du_cas(cas):
    """{(type, début): KPI figés par une campagne clôturée} d'après le cas (seconde écriture, ``independent_calculation``),
    tels que notés au début du cas."""
    o = IC.Oracle(cas)
    return {(p.type, p.debut.isoformat()): o.a_figer(p) for p in o.periodes.values()}


# --pages : à la fin du cas, avant de valider les brouillons, un total au-dessus d'un brouillon n'a pas de valeur validée
# (``_ecarts_brouillons``) ; puis, toutes les saisies validées, les chiffres que montrent la Visualisation (et le serveur MCP
# pour un lecteur : ``visualisation.CalculateurValide``) et le détail d'un total (``vues_cellule._detail_agregat``) sont
# comparés aux cases enregistrées (celles de la Saisie, de la Consolidation et des exports) ; None : pas de contrôle
PAGES = None
PAGES_DEMANDE = False
PAGES_IMPORTS = os.environ.get("FUZZ_PAGES_IMPORTS") == "1"


def _ecarts_des_pages(periodes, gelees=None):
    from collecte import calcul as C
    from collecte.models import Campagne, Reponse
    from collecte.visualisation import CalculateurValide, valeur_officielle, valeurs_egales
    from collecte.vues_cellule import detail_agregat
    from referentiel.models import KPI

    from collecte.visualisation import Source
    from referentiel.models import Utilisateur

    kpis = {k.code: k for k in KPI.objects.select_related("type_reponse", "type_saisie", "granularite")}
    ecarts_brouillons = _ecarts_brouillons(periodes, kpis, gelees or {})
    Reponse.objects.filter(origine="saisie", statut="brouillon").update(statut="valide")  # sans signal : aucun recalcul
    valide = CalculateurValide()
    admin = Utilisateur(username="admin-fuzz", role=Utilisateur.Role.ADMIN)  # pas enregistré : voit tout
    pages_kpi = {}  # une Source par KPI (codes=[KPI]), comme un visuel de la Visualisation ou une case de la Consolidation
    noms = {}
    ecarts = []
    par_pk = {q.pk: q for q in periodes.values()}
    for r in Reponse.objects.filter(periode_id__in=par_pk, origine__in=["calcul", "agregation", "cumul"]).select_related(
            "organisation"):
        q, k = par_pk[r.periode_id], kpis[r.kpi_id]
        noms[r.organisation_id] = r.organisation.nom
        cle = (q.type, q.debut.isoformat(), r.kpi_id, r.organisation.nom)
        v = valide.valeur(r.kpi_id, r.organisation_id, q)
        officielle = valeur_officielle(r, k)
        if (v is None) != (officielle is None) or (v is not None and not valeurs_egales(v, officielle, k)):
            ecarts.append(dict(page="visualisation (MCP reader)", cell=cle, stored=str(officielle), shown=str(v)))
        if r.kpi_id not in pages_kpi:
            pages_kpi[r.kpi_id] = Source(admin, codes=[r.kpi_id])
        point = pages_kpi[r.kpi_id].point(r.kpi_id, r.organisation, q)
        vu = None if point is None else point.valeur
        if point is None:
            ecarts.append(dict(page="visualisation (one KPI)", cell=cle, stored=str(officielle), shown="no point"))
        elif (vu is None) != (officielle is None) or (vu is not None and not valeurs_egales(vu, officielle, k)):
            ecarts.append(dict(page="visualisation (one KPI)", cell=cle, stored=str(officielle), shown=str(vu)))
        if r.origine != "agregation" or k.methode_agregation not in ("Somme", "Décompte"):
            continue
        c = Campagne.objects.filter(periode=q).first()
        detail = detail_agregat(c, k, r.organisation)
        listes = {n["org"].id for n in detail}
        calc = C.Calculateur(q)
        rang_k = calc.rangs[k.granularite_id]
        enfants = [e for e in calc.enfants(r.organisation_id, q, k.code) if calc.rangs[e.niveau_id] <= rang_k]
        detail_k = calc._avec_detail(rang_k, q, k.code)
        courtes = calc.frequences[k.code] if calc.cumule(k, q) else None
        comptes = {e.id for e in enfants if calc.valeur(k.code, e.id, q) is not None or (e.id in detail_k and (
            e.actif or e.id in calc.avec_valeurs(q, k.code)
            or (courtes is not None and e.id in calc.avec_valeurs_courtes(q, courtes, k.code))))}
        if not comptes <= listes:  # une organisation additionnée (ou qui rend le total incomplet) absente du détail
            ecarts.append(dict(page="detail of a total", cell=cle, counted_not_listed=sorted(
                calc.orgs[x].nom for x in comptes - listes)))
        # saisie au-dessus avec des mois : sans le total des organisations du dessous, l'année d'une organisation au-dessus
        # est le cumul de ses propres mois (README, « Entry at higher levels ») ; le détail montre alors les enfants
        # incomplets (observation de la troisième passe, graine 24 : explication à choisir, pas un chiffre faux) ; de même
        # pour un KPI calculé en somme dont une source se saisit au-dessus : sa formule refaite à ce niveau (graine 3030)
        if r.valeur is not None and not r.non_applicable and not r.texte and k.methode_agregation == "Somme" and not (
                k.saisissable_au_dessus and calc.cumule(k, q)) and not (k.est_calcule and calc._sources_au_dessus(k)):
            somme = sum((n["r"].valeur for n in detail if n["r"] is not None and n["r"].valeur is not None
                         and not n["r"].non_applicable), Decimal(0))
            # point à décider (troisième passe) : dans une période non figée, un total importé tel quel
            # (fichier historique) sur un enfant reste affiché, mais le parent additionne le total recalculé de cet enfant ;
            # écart connu, compté à part (``--pages`` le signale seulement avec ``PAGES_IMPORTS``)
            # de même pour une ancienne saisie d'un KPI devenu calculé, gardée dans une période figée (graine 4559)
            importe = any(n["r"] is not None and (
                (n["r"].origine == "import" and (calc.rangs[n["org"].niveau_id] < rang_k or k.est_calcule))
                or (n["r"].origine == "saisie" and k.est_calcule)) for n in detail)
            if abs(somme - r.valeur) > Decimal("1e-6") * max(1, abs(r.valeur)) and (PAGES_IMPORTS or not importe):
                ecarts.append(dict(page="detail of a total", cell=cle, total=str(r.valeur), sum_of_detail=str(somme)))
    ecarts += _ecarts_consolidation(periodes, kpis, admin)
    return ecarts_brouillons + ecarts


def _ecarts_brouillons(periodes, kpis, gelees):
    """Avant de tout valider : Visualisation des valeurs validées (``CalculateurValide``) × valeurs pas encore validées.
    Seconde écriture de la règle du module (``collecte/visualisation.py`` : s'il manque une source validée, le total est
    « en attente »), sans le moteur : dans une période non figée, un total en somme ou décompte d'une organisation dont
    une organisation du dessous, au niveau du KPI, a une valeur saisie en brouillon de ce KPI ou d'une source de sa
    formule (même période, même niveau) n'a pas de valeur validée — que cette organisation soit active ou fermée
    pendant la période (un site fermé en brouillon sortait du total sans un mot). Hors du
    contrôle : un KPI calculé avec une valeur forcée sur la période (elle remplace le calcul).

    Règle « Tout brouillon compte » (règle du projet) : un site fermé pendant la période, au niveau
    d'un KPI saisi qui ne se cumule pas depuis des périodes plus courtes, sans valeur validée de ce KPI, dont lui-même
    ou une organisation en dessous a une valeur pas encore validée de N'IMPORTE QUEL KPI sur la période, compte dans le
    total de chacun de ses ancêtres (par des organisations ouvertes) : ce total n'a pas de valeur validée. Les KPI figés
    par une campagne clôturée sont hors du contrôle : leurs totaux sont ceux enregistrés."""
    from collecte.models import Campagne, Reponse
    from collecte.visualisation import CalculateurValide
    from referentiel.models import ElementReferentiel, KPIFormule, Organisation

    parents = dict(Organisation.objects.values_list("id", "parent_id"))
    niveaux = dict(Organisation.objects.values_list("id", "niveau_id"))
    noms = dict(Organisation.objects.values_list("id", "nom"))
    etats = {o: (actif, fin, debut) for o, actif, fin, debut in Organisation.objects.values_list(
        "id", "actif", "date_desactivation", "date_ouverture")}

    def ouverte(o, q):  # seconde écriture de la règle d'ouverture (README, « closed during the period »)
        actif, fin, _ = etats[o]
        if not actif and not (fin and fin >= q.debut):
            return False
        x = o
        while x is not None:  # pas ouverte avant ses ancêtres
            if etats[x][2] is not None and etats[x][2] > q.fin:
                return False
            x = parents.get(x)
        return True
    graphe = {}
    for c, s in KPIFormule.objects.filter(decalage="N").values_list("kpi_calcule_id", "kpi_source_id"):
        graphe.setdefault(c, set()).add(s)

    def fermeture(code):
        vus, pile = set(), [code]
        while pile:
            x = pile.pop()
            if x not in vus:
                vus.add(x)
                pile.extend(graphe.get(x, ()))
        return vus

    enfants_de = {}
    for o, par in parents.items():
        if par is not None:
            enfants_de.setdefault(par, []).append(o)
    finesse = {"mois": 1, "trimestre": 2, "semestre": 3, "annee": 4}
    frequence = {}  # fréquence la plus fine des référentiels actifs qui contiennent le KPI (seconde écriture)
    for k, f in ElementReferentiel.objects.filter(referentiel__actif=True).values_list("kpi_id", "referentiel__frequence"):
        if k not in frequence or finesse[f] < finesse[frequence[k]]:
            frequence[k] = f

    def se_cumule(k, q):
        f = frequence.get(k.code)
        return (not k.est_calcule and k.agregation_temps != "aucune" and f is not None
                and finesse[f] < finesse[q.type])

    valide, ecarts = CalculateurValide(), []
    for q in periodes.values():
        statuts = list(Campagne.objects.filter(periode=q).values_list("statut", "chiffres_gardes"))
        if all(st == Campagne.Statut.CLOTUREE for st, _ in statuts) or any(g for st, g in statuts if st != Campagne.Statut.CLOTUREE):
            continue  # période figée (close, ou rouverte en gardant les chiffres) : ses totaux sont ceux enregistrés
        # une organisation au-dessus qui porte une valeur validée du KPI (saisie au-dessus, total importé) : son total ne
        # dépend pas du dessous (« held by an input »), on ne remonte pas plus haut
        tenues = set(Reponse.objects.filter(periode=q, statut="valide", origine__in=["saisie", "import", "forcee"]).exclude(
            valeur=None, texte="", non_applicable=False).values_list("kpi_id", "organisation_id"))
        attente = {}  # {KPI: {organisation: [organisations du dessous, au niveau du KPI, avec une valeur en brouillon]}}
        for k, o in Reponse.objects.filter(periode=q, origine="saisie", statut="brouillon").exclude(
                valeur=None, texte="", non_applicable=False).values_list("kpi_id", "organisation_id"):
            if kpis[k].est_calcule or niveaux.get(o) != kpis[k].granularite_id or not ouverte(o, q):
                continue
            x = parents.get(o)
            while x is not None and (k, x) not in tenues:
                attente.setdefault(k, {}).setdefault(x, []).append(o)
                x = parents.get(x)
        forces = set(Reponse.objects.filter(periode=q, origine="forcee").values_list("kpi_id", flat=True))
        figes_q = gelees.get((q.type, q.debut.isoformat()), ())
        # « Tout brouillon compte » : organisations qui ont une valeur pas encore validée sur la période (n'importe quel
        # KPI ; une ancienne saisie d'un KPI devenu calculé n'est pas une valeur, hors KPI figé), et celles au-dessus
        brouillon_dessous = set()
        for k, o, origine in Reponse.objects.filter(periode=q, origine__in=["saisie", "import", "forcee"]).exclude(
                statut="valide").exclude(valeur=None, texte="", non_applicable=False).values_list(
                "kpi_id", "organisation_id", "origine"):
            if origine == "saisie" and kpis[k].est_calcule and k not in figes_q:
                continue
            x = o
            while x is not None and x not in brouillon_dessous:
                brouillon_dessous.add(x)
                x = parents.get(x)
        validees = set(Reponse.objects.filter(periode=q, statut="valide", origine__in=["saisie", "import", "forcee"])
                       .exclude(valeur=None, texte="", non_applicable=False).values_list("kpi_id", "organisation_id"))

        def fermees_avec_brouillon(k, racine):
            """Sites fermés pendant la période sous ``racine`` (par des organisations ouvertes), au niveau du KPI, sans
            valeur validée de ce KPI, avec une valeur pas encore validée sur la période (eux ou en dessous)."""
            sortie, pile = [], list(enfants_de.get(racine, ()))
            while pile:
                x = pile.pop()
                if not ouverte(x, q):
                    continue
                if niveaux.get(x) == k.granularite_id:
                    if not etats[x][0] and (k.code, x) not in validees and x in brouillon_dessous:
                        sortie.append(x)
                    continue
                pile.extend(enfants_de.get(x, ()))
            return sortie
        figes = gelees.get((q.type, q.debut.isoformat()), ())
        for r in Reponse.objects.filter(periode=q, origine="agregation").select_related("organisation"):
            k = kpis[r.kpi_id]
            if k.methode_agregation not in ("Somme", "Décompte") or (k.est_calcule and r.kpi_id in forces):
                continue
            if r.kpi_id in figes:
                continue  # KPI figé par une campagne clôturée : ses totaux sont ceux enregistrés
            def tenue_en_chemin(o):  # une valeur validée du KPI du total, sur l'organisation du brouillon ou entre les deux
                x = o
                while x is not None and x != r.organisation_id:
                    if (r.kpi_id, x) in tenues:
                        return True
                    x = parents.get(x)
                return False

            dessous = sorted({(s, noms[o]) for s in fermeture(r.kpi_id) if s in kpis and kpis[s].granularite_id == k.granularite_id
                              for o in attente.get(s, {}).get(r.organisation_id, ()) if not tenue_en_chemin(o)})
            fermees = [] if k.est_calcule or se_cumule(k, q) else sorted(
                noms[x] for x in fermees_avec_brouillon(k, r.organisation_id) if not tenue_en_chemin(x))
            if not dessous and not fermees:
                continue
            v = valide.valeur(r.kpi_id, r.organisation_id, q)
            if v is not None and dessous:
                ecarts.append(dict(page="visualisation (draft below)", cell=(q.type, q.debut.isoformat(), r.kpi_id,
                                   r.organisation.nom), shown=str(v), drafts_below=dessous))
            elif v is not None:
                ecarts.append(dict(page="visualisation (closed site with a draft)", cell=(
                    q.type, q.debut.isoformat(), r.kpi_id, r.organisation.nom), shown=str(v), closed_sites=fermees))
    return ecarts


def _ecarts_consolidation(periodes, kpis, admin):
    """Consolidation (brouillons compris : les valeurs de l'outil) : chaque total en somme est la somme des lignes
    montrées juste en dessous (règle écrite dans ``consolidation.tableau``), et chaque case montre la valeur enregistrée.
    Mêmes cas mis à part que pour le détail d'un total (saisie au-dessus cumulée, formule refaite au-dessus, total
    importé tel quel d'un enfant dans une période non figée)."""
    from collecte import calcul as C
    from collecte import consolidation as CO
    from collecte.models import Reponse

    ecarts = []
    for q in periodes.values():
        calc = C.Calculateur(q)
        stockees = {(k, o): (v, na, origine) for k, o, v, na, origine in Reponse.objects.filter(periode=q).values_list(
            "kpi_id", "organisation_id", "valeur", "non_applicable", "origine")}
        for k in kpis.values():
            if k.methode_agregation != "Somme" or not k.est_numerique or k.est_pourcentage or k.est_herite or not k.actif:
                continue
            if (k.saisissable_au_dessus and calc.cumule(k, q)) or (k.est_calcule and calc._sources_au_dessus(k)):
                continue
            rang_k = calc.rangs[k.granularite_id]
            t = CO.tableau(admin, q, [k], brouillons=True, avec_vides=True)
            if not t.kpis:
                continue
            valeurs = {l.org.id: (l.cases[0].point.valeur if l.cases[0].point is not None else None) for l in t.lignes}
            enfants = {}
            for l in t.lignes:
                enfants.setdefault(l.parent_id, []).append(l.org)
            for l in t.lignes:
                v = valeurs[l.org.id]
                cle = (q.type, q.debut.isoformat(), k.code, l.org.nom)
                s = stockees.get((k.code, l.org.id))
                vu = None if s is None or s[1] or s[0] is None else s[0]
                if isinstance(v, Decimal) != isinstance(vu, Decimal) or (isinstance(v, Decimal) and abs(v - vu) > Decimal("1e-6")):
                    if not (s is None and v is None):
                        ecarts.append(dict(page="consolidation cell", cell=cle, stored=str(vu), shown=str(v)))
                dessous = [e for e in enfants.get(l.org.id, []) if calc.rangs[e.niveau_id] <= rang_k]
                if not isinstance(v, Decimal) or not dessous or calc.rangs[l.org.niveau_id] >= rang_k:
                    continue
                if s is not None and s[2] != "agregation":
                    continue  # valeur saisie ou importée à ce niveau : elle remplace le total
                tenues = [(stockees.get((k.code, e.id)) or (None, False, ""))[2] for e in dessous]
                if any((t == "import" and (calc.rangs[e.niveau_id] < rang_k or k.est_calcule)) or (t == "saisie" and k.est_calcule)
                       for t, e in zip(tenues, dessous)) and not PAGES_IMPORTS:
                    continue
                somme = sum((valeurs[e.id] for e in dessous if isinstance(valeurs[e.id], Decimal)), Decimal(0))
                if abs(somme - v) > Decimal("1e-6") * max(1, abs(v)):
                    ecarts.append(dict(page="consolidation total", cell=cle, total=str(v), sum_of_rows=str(somme),
                                       rows=sorted(e.nom for e in dessous)))
    return ecarts


# --full-check : après chaque changement, l'état laissé par l'outil (recalcul ciblé, partiel, ou rien) est comparé au
# recalcul complet de toutes les périodes non figées (dans un point de sauvegarde annulé) ; None : pas de contrôle
PLEIN = None


def _ecarts_au_complet(periodes, ordre, apres):
    """Cases des périodes non figées dont l'état diffère après un recalcul complet (valeur, statut, texte, N/A, origine ;
    le message n'est pas comparé). Le recalcul complet est annulé : l'exécution continue depuis l'état de l'outil."""
    from django.db import transaction

    from collecte.calcul import figee, recalculer

    complet = None
    try:
        with transaction.atomic():
            for q in ordre:
                if not figee(q):
                    recalculer(q)
            complet = _lire(periodes)
            raise _Annuler()
    except _Annuler:
        pass
    libres = {(q.type, q.debut.isoformat()) for q in ordre if not figee(q)}
    ecarts = []
    for cle in sorted(set(apres) | set(complet)):
        if cle[:2] not in libres:
            continue
        a, b = apres.get(cle), complet.get(cle)
        if (a is None) != (b is None) or (a is not None and (a[:5] != b[:5])):
            ecarts.append(dict(cell=cle, tool=None if a is None else [str(x) for x in a[:5]],
                               full=None if b is None else [str(x) for x in b[:5]]))
    return ecarts


def _un_changement(cas, ch, i, etats, orgs, refs, periodes):
    from collecte.models import Reponse
    from referentiel.models import Organisation

    if True:
        if ch.get("type") == "close":  # Administration › Organisations : désactivée, avec sa date de fermeture
            from collecte.calcul import recalculer_en_cours

            o = orgs[ch["o"]]
            o.actif, o.date_desactivation = False, datetime.date.fromisoformat(ch["date"])
            o.save()
            recalculer_en_cours()
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "open":  # Administration › Organisations : date d'ouverture posée après coup
            from collecte.calcul import recalculer_en_cours

            o = orgs[ch["o"]]
            o.date_ouverture = datetime.date.fromisoformat(ch["date"])
            o.save()
            recalculer_en_cours()
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "create":  # Administration › Organisations : créée après la clôture
            from collecte.calcul import recalculer_en_cours

            orgs[ch["o"]] = Organisation.objects.create(nom=ch["o"], niveau_id=f"N{ch['rank']}", parent=orgs[ch["parent"]])
            recalculer_en_cours()
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "reopen":  # Administration › Campagnes : réouverture, l'un des deux modes
            from collecte.administration import changer_statut
            from collecte.models import Campagne

            c = Campagne.objects.get(periode=periodes[IC.tuple_cle(ch["p"])], referentiel=refs[ch["p"].split(":")[0]])
            changer_statut(None, c, "rouvrir", garder=ch["mode"] == "garder")  # personne : le journal l'accepte
            if ch["mode"] == "garder":
                # chiffres publiés marqués (le message seul, que le calcul ne lit pas) : une case réécrite par une
                # correction perd la marque ; ``verifier`` exige qu'elle soit dans la lignée de l'époque refaite
                Reponse.objects.filter(periode=c.periode, origine__in=["calcul", "agregation", "cumul"]).update(
                    message_calcul=PUBLIE)
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "reclose":  # Administration › Campagnes : clôturée de nouveau après la réouverture
            from collecte.administration import changer_statut
            from collecte.models import Campagne

            c = Campagne.objects.get(periode=periodes[IC.tuple_cle(ch["p"])], referentiel=refs[ch["p"].split(":")[0]])
            changer_statut(None, c, "cloturer")
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "depuis":  # Référentiels › contenu : « Demandé depuis » avancé ou reculé
            from django.core.exceptions import ValidationError

            from collecte.demande_depuis import changer

            ch.pop("refuse", None)
            try:
                changer(None, refs[ch["f"]], [ch["k"]], datetime.date.fromisoformat(ch["date"]), confirmer=True)
            except ValidationError:
                ch["refuse"] = True  # refusé par l'outil (valeurs, campagne clôturée) : rien ne change
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "move":  # Administration › Organisations : rattachée ailleurs
            from collecte.calcul import recalculer_en_cours

            o = orgs[ch["o"]]
            o.parent = orgs[ch["parent"]]
            o.save()
            recalculer_en_cours()
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") == "import_calcule":
            _importer_calcule(ch, orgs, periodes)
            etats.append((f"change{i}", _lire(periodes)))
            return
        if ch.get("type") in ("validate", "force", "unforce", "import", "batch"):
            _ecriture_v3(ch, orgs, periodes)
            etats.append((f"change{i}", _lire(periodes)))
            return
        q = periodes[IC.tuple_cle(ch["p"])]
        r = Reponse.objects.filter(periode=q, kpi_id=ch["k"], organisation=orgs[ch["o"]]).first() or Reponse(
            periode=q, kpi_id=ch["k"], organisation=orgs[ch["o"]])
        for champ, v in _champs(ch["v"]).items():
            setattr(r, champ, v)
        r.origine, r.statut = Reponse.Origine.SAISIE, Reponse.Statut.BROUILLON
        r.save()  # signal : recalcul de la période et de ce qui en dépend, alertes de cohérence
        etats.append((f"change{i}", _lire(periodes)))


def _importer_calcule(ch, orgs, periodes):
    """``_imports_calcules_v3`` par le vrai chemin de l'outil : un fichier (ID KPI, Organisation, Exercice, Valeur),
    l'aperçu (``imports.analyser``), puis l'import confirmé (``imports.appliquer(forcer=…)``, par paquets comme la page).
    Une ligne que l'aperçu ne propose pas de forcer (même chiffre que la case) est notée « refuse » : rien ne change."""
    import io

    from openpyxl import Workbook

    from collecte import imports as I
    from referentiel.models import Utilisateur

    admin = Utilisateur.objects.filter(username="admin-fuzz-import").first()
    if admin is None:  # sans le registre commun des comptes (base jetable du fuzz) : créé sans ``save``
        admin = Utilisateur.objects.bulk_create([Utilisateur(username="admin-fuzz-import", role=Utilisateur.Role.ADMIN)])[0]
        admin = Utilisateur.objects.get(username="admin-fuzz-import")
    q = periodes[IC.tuple_cle(ch["p"])]
    v = ch["v"]
    if v == "NA":
        valeur = "N/A"
    else:
        from referentiel.models import KPI

        d = Decimal(v) * (100 if KPI.objects.get(code=ch["k"]).est_pourcentage else 1)
        valeur = format(d.normalize(), "f")
    wb = Workbook()
    wb.active.append(["ID KPI", "Code organisation", "Organisation", "Exercice", "Valeur"])
    wb.active.append([ch["k"], orgs[ch["o"]].code, orgs[ch["o"]].nom, q.debut.year, valeur])
    flux = io.BytesIO()
    wb.save(flux)

    def fichier():
        f = io.BytesIO(flux.getvalue())
        f.name = "fuzz.xlsx"
        return f

    a = I.analyser(admin, fichier())
    cles = [l.cle for l in a.a_forcer]
    if not cles:
        ch["refuse"] = True
        ch["motif"] = a.lignes[0].motif if a.lignes else a.erreur
        return
    I.appliquer(admin, fichier(), "fuzz.xlsx", forcer=cles, par_paquets=True)


PUBLIE = "publié (essai du fuzz)"


def _ecriture_v3(ch, orgs, periodes):
    """Écritures de ``_ecritures_v3``, par les mêmes gestes que l'outil : la validation (statut seul, le signal de la
    saisie recalcule), « accepter » une valeur forcée et « revenir au calcul » (``collecte/forcage.py`` : mêmes champs,
    puis ``apres_modification``), un lot de saisies (``signals.en_lot`` : un recalcul par période à la fin, comme un
    import ou un paquet), une correction importée dans une campagne clôturée (``imports._ecrire_historique`` : origine
    « import », signalée au lot)."""
    from collecte.models import Reponse
    from collecte.signals import apres_modification, en_lot, signaler

    def reponse(c):
        q = periodes[IC.tuple_cle(c["p"])]
        return q, (Reponse.objects.filter(periode=q, kpi_id=c["k"], organisation=orgs[c["o"]]).first()
                   or Reponse(periode=q, kpi_id=c["k"], organisation=orgs[c["o"]]))

    t = ch["type"]
    if t == "validate":
        q, r = reponse(ch)
        if r.pk is not None:
            r.statut = Reponse.Statut.VALIDE
            r.save(update_fields=["statut", "date_maj"])  # comme ``saisie.valider``
    elif t == "force":
        q, r = reponse(ch)
        for champ, v in _champs(ch["v"]).items():
            setattr(r, champ, v)
        r.message_calcul, r.origine, r.statut = "", Reponse.Origine.FORCEE, Reponse.Statut.VALIDE
        r.save()
        apres_modification(q, [ch["k"]], {orgs[ch["o"]].id})
    elif t == "unforce":
        q, r = reponse(ch)
        if r.pk is not None and r.origine == Reponse.Origine.FORCEE:
            r.origine, r.statut = Reponse.Origine.CALCUL, Reponse.Statut.CALCULE
            r.save()
            apres_modification(q, [ch["k"]], {orgs[ch["o"]].id})
    elif t == "import":
        from collecte.models import Campagne
        from collecte.saisie import dans_la_campagne
        from referentiel.models import KPI

        q, _ = reponse(ch)
        ch.pop("refuse", None)
        closes = [c for c in Campagne.objects.filter(periode=q, statut=Campagne.Statut.CLOTUREE)]
        kpi = KPI.objects.get(code=ch["k"])
        if closes and not any(dans_la_campagne(c, kpi) for c in closes):
            # KPI pas demandé dans la campagne clôturée (périmètre noté à la clôture) : l'import le refuse
            # (``imports``, motif « pas demandé ») ; rien ne change
            ch["refuse"] = True
            return
        # chiffres publiés marqués (comme à la réouverture « garder ») : seule la lignée refaite peut perdre la marque
        Reponse.objects.filter(periode=q, origine__in=["calcul", "agregation", "cumul"]).update(message_calcul=PUBLIE)
        with en_lot():
            q, r = reponse(ch)
            for champ, v in _champs(ch["v"]).items():
                setattr(r, champ, v)
            r.origine, r.statut = Reponse.Origine.IMPORT, Reponse.Statut.VALIDE
            r.save()
            signaler(r)
    elif t == "batch":
        with en_lot():
            for c in ch["cells"]:
                q, r = reponse(c)
                for champ, v in _champs(c["v"]).items():
                    setattr(r, champ, v)
                r.origine, r.statut = Reponse.Origine.SAISIE, Reponse.Statut.BROUILLON
                r.save()  # signal : noté pour le recalcul de fin de lot


def _comparaisons_n1(orgs):
    """Pour chaque campagne non clôturée qui a une période de comparaison : (période, période comparée, cases de la
    période comparée, cases que l'outil garde comme comparaison, ``saisie.valeurs_n1``, la règle de toutes les pages)."""
    from collecte import saisie as S
    from collecte.models import Campagne, Reponse

    noms = {o.id: nom for nom, o in orgs.items()}
    sortie = []
    for c in Campagne.objects.exclude(statut="cloturee").select_related("periode", "referentiel"):
        prec = S.periode_comparaison(c)
        if prec is None:
            continue
        paires = set(Reponse.objects.filter(periode=prec).values_list("kpi_id", "organisation_id"))
        gardees = S.valeurs_n1(c, paires)
        sortie.append(((c.periode.type, c.periode.debut.isoformat()), (prec.type, prec.debut.isoformat()),
                       sorted((k, noms[o]) for k, o in paires), sorted((k, noms[o]) for k, o in gardees)))
    return sortie


def _figee(cas, q):
    return any(p["type"] == q.type and p["debut"] == q.debut.isoformat() and IC.statut_effectif(p) == "cloturee"
               for p in cas["periods"])


def _champs(v):
    if v is None:
        return dict(valeur=None, texte="", non_applicable=False)
    if v == "NA":
        return dict(valeur=None, texte="", non_applicable=True)
    if v in ("Oui", "Non", "A", "B", "C") or v in TEXTES or v in TABLEAUX:
        return dict(valeur=None, texte=v, non_applicable=False)
    return dict(valeur=Decimal(v), texte="", non_applicable=False)


def _lire(periodes):
    from collecte.models import Reponse

    par_pk = {q.pk: q for q in periodes.values()}
    out = {}
    for r in Reponse.objects.filter(periode_id__in=par_pk).values_list(
            "periode_id", "kpi_id", "organisation__nom", "statut", "valeur", "texte", "non_applicable", "origine", "message_calcul"):
        q = par_pk[r[0]]
        out[(q.type, q.debut.isoformat(), r[1], r[2])] = r[3:]
    return out


# ---------------------------------------------------------------- comparaison
def _decompte(texte):
    total = Counter()
    for morceau in (texte or "").split(" · "):
        nom, _, n = morceau.rpartition(" : ")
        if nom and n.isdigit():
            total[nom] += int(n)
        elif morceau:
            total[morceau] += 1
    return total


def _proche(attendu, valeur):
    v = Fraction(valeur)
    tol = Fraction(1, 10 ** 9) + abs(attendu.v) * Fraction(1, 10 ** 13)
    if not attendu.exact:
        tol = Fraction(1, 10 ** 6) * max(1, abs(attendu.v))
    return abs(attendu.v - v) <= tol


def comparer(cas, lignes, saisies=None, memoire_figee=None, stockees=None):
    """Différences entre les lignes de l'outil et le second calcul : [dict(...)]. Renvoie (différences, oracle, compte).
    ``stockees`` : cases des périodes figées refaites par une correction (``refaire_figee``)."""
    stockees = stockees or {}
    o = IC.Oracle(cas, saisies=saisies, memoire_figee=memoire_figee, stockees=stockees)
    diffs, compte = [], Counter()
    vues = set()
    for p in o.periodes.values():
        for k in cas["kpis"]:
            for org in cas["orgs"]:
                cle = (p.type, p.debut.isoformat(), k["code"], org["id"])
                # période figée : ses cases gardent les valeurs d'avant les changements (README : une campagne clôturée
                # n'est plus recalculée par un changement de ses sous-périodes, ni par une organisation fermée depuis)
                source = memoire_figee if memoire_figee is not None and o.figee_kpi(p, k["code"]) else o
                if not source.produite(k["code"], org["id"], p):
                    continue
                vues.add(cle)
                if o.bloquee(k["code"], org["id"], p):  # saisies relues en base (une correction compte)
                    compte["held by an input"] += 1
                    continue
                if source is not o and (k["code"], org["id"], p.cle) in stockees:
                    statut, v = stockees[(k["code"], org["id"], p.cle)]
                    statut = statut if statut != "calcule" or v is not None else "incomplet"
                else:
                    statut, v = source.attendu(k["code"], org["id"], p)
                ligne = lignes.get(cle)
                if statut == "imprecis":
                    compte["not verifiable (decimal precision)"] += 1
                    continue
                if ligne is None:
                    diffs.append(dict(cell=cle, expected=statut, expected_value=_texte(v), tool="missing row"))
                    continue
                st, valeur, texte, na, origine, message = ligne
                outil = "na" if na else st if st in ("incomplet", "erreur") else "calcule" if st == "calcule" else st
                if outil != statut:
                    diffs.append(dict(cell=cle, expected=statut, expected_value=_texte(v), tool=outil,
                                      tool_value=None if valeur is None else str(valeur), tool_text=texte, message=message))
                    continue
                if statut == "calcule":
                    ok = True
                    if isinstance(v, IC.Nombre):
                        ok = valeur is not None and not texte and _proche(v, valeur)
                    elif isinstance(v, Counter):
                        ok = _decompte(texte) == +v and valeur == sum(v.values())
                    else:
                        ok = texte == v
                    if not ok:
                        diffs.append(dict(cell=cle, expected=statut, expected_value=_texte(v), tool=outil,
                                          tool_value=None if valeur is None else str(valeur), tool_text=texte, message=message))
                        continue
                compte["same (" + statut + ")"] += 1
    for cle, ligne in lignes.items():
        if ligne[4] in ("calcul", "agregation", "cumul") and cle not in vues:
            diffs.append(dict(cell=cle, expected="no calculated cell", tool=ligne[0], tool_value=str(ligne[1]), origin=ligne[4]))
    return diffs, o, compte


def _texte(v):
    if isinstance(v, IC.Nombre):
        return str(float(v.v)) + ("" if v.exact else " (inexact)")
    if isinstance(v, Counter):
        return dict(v)
    return v


def _cas_apres(cas, n):
    """Le cas après ses ``n`` premiers changements (saisies modifiées, organisations fermées)."""
    c = copy.deepcopy(cas)
    d = {(s["k"], s["o"], s["p"]): s for s in c["inputs"]}
    for ch in cas["changes"][:n]:
        if ch.get("type") == "close":
            o = next(x for x in c["orgs"] if x["id"] == ch["o"])
            o["active"], o["closed"] = False, ch["date"]
        elif ch.get("type") == "move":
            next(x for x in c["orgs"] if x["id"] == ch["o"])["parent"] = ch["parent"]
        elif ch.get("type") == "open":
            next(x for x in c["orgs"] if x["id"] == ch["o"])["opened"] = ch["date"]
        elif ch.get("type") == "create":
            c["orgs"].append(dict(id=ch["o"], rank=ch["rank"], parent=ch["parent"], active=True, closed=None, opened=None))
        elif ch.get("type") == "reopen":
            q = next(x for x in c["periods"] if f"{x['type']}:{x['debut']}" == ch["p"])
            q["status"] = "gardee" if ch["mode"] == "garder" else "revue"
        elif ch.get("type") == "reclose":
            next(x for x in c["periods"] if f"{x['type']}:{x['debut']}" == ch["p"])["status"] = "cloturee"
        elif ch.get("type") == "depuis":
            if not ch.get("refuse"):
                next(x for x in c["kpis"] if x["code"] == ch["k"]).setdefault("depuis", {})[ch["f"]] = ch["date"]
        elif ch.get("type") == "validate":
            pass  # le statut seul : rien ne change pour le calcul
        elif ch.get("type") == "unforce":
            s = d.get((ch["k"], ch["o"], ch["p"]))
            if s is not None and s["origin"] == "forcee":
                del d[(ch["k"], ch["o"], ch["p"])]  # la case reprend le résultat du calcul
        elif ch.get("type") == "batch":
            for x in ch["cells"]:
                d[(x["k"], x["o"], x["p"])] = dict(x)
        elif ch.get("type") == "import" and ch.get("refuse"):
            pass  # refusé par l'outil (KPI pas demandé dans la campagne clôturée) : rien ne change
        elif ch.get("type") == "import_calcule" and ch.get("refuse"):
            pass  # même chiffre que la case : l'aperçu n'a rien à forcer
        else:
            d[(ch["k"], ch["o"], ch["p"])] = dict(ch)
    c["inputs"] = list(d.values())
    return c


def refaire_figee(cas_i, ch, memoire, stockees):
    """Correction ``ch`` dans une période rouverte en gardant les chiffres de l'époque (README) : refait, dans l'arbre de la clôture, l'organisation corrigée et ses ancêtres (et ses descendants pour un
    paramètre hérité ; toutes si cela fait tout l'arbre), pour le KPI corrigé et ceux qui en dépendent dans la période
    (tous les KPI si une organisation fermée de la lignée n'a pas d'autre valeur dans sa branche) ; les autres cases sont
    lues telles qu'enregistrées. Met à jour ``stockees`` (cases enregistrées) avec les cases refaites. Renvoie (KPI
    refaits, organisations refaites ou None pour toutes) : les seules cases que l'outil peut réécrire."""
    o = IC.Oracle(cas_i, memoire_figee=memoire, stockees=stockees)
    p = o.periodes[IC.tuple_cle(ch["p"])]
    arbre, k, org = o.orgs_cloture_par.get(p.cle, o.orgs_cloture) if o.figee(p) else o.orgs_cloture, ch["k"], ch["o"]
    # règle « Figer ses chiffres » : correction importée d'un KPI figé par la campagne clôturée d'une période
    # dont une autre campagne est ouverte : la même règle, pour les seuls KPI figés, dans l'arbre du jour où ils l'ont été
    figes = o.gelees(p)
    if org not in arbre:
        return set(), set()
    fermees, x = [], org
    while x is not None:
        if not arbre[x]["active"]:
            fermees.append(x)
        x = arbre[x]["parent"]
    tous = False
    for e in fermees:
        branche = set(o.descendants(e, p, k))
        n = sum(1 for (kk, oo, cp), (origine, v) in o.saisies.items() if cp == p.cle and oo in branche and v is not None
                and not (origine == "saisie" and o.kpis[kk]["comp"] == "calcul"))
        tous = tous or n <= 1
    m = cas_i.get("mois_debut", 1)
    exercice = str(p.debut.year if p.debut.month >= m else p.debut.year - 1)
    inverse = {}
    for kk in cas_i["kpis"]:
        if kk["comp"] == "calcul":
            try:
                for r in IC.references(IC.analyser(kk["formula"])):
                    if r[2] in ("N", exercice):
                        inverse.setdefault(r[1], set()).add(kk["code"])
            except IC.FormuleIllisible:
                pass
    kpis, pile = set(), list(o.kpis) if tous else [k]
    while pile:
        x = pile.pop()
        if x not in kpis:
            kpis.add(x)
            pile += list(inverse.get(x, ()))
    if figes:
        kpis &= figes
    touchees, x = set(), org
    while x is not None and x not in touchees:
        touchees.add(x)
        x = arbre[x]["parent"]
    if o.kpis[k]["comp"] == "herite":
        touchees |= set(o.descendants(org, p, k))
    orgs = None if len(touchees) >= len(arbre) else touchees
    o = IC.Oracle(cas_i, memoire_figee=memoire, stockees=stockees, refaites={p.cle: (kpis, orgs)})
    nouvelles = {}
    for kk in kpis:
        if kk not in o.kpis:
            continue
        for oo in (arbre if orgs is None else orgs):
            if not o.produite(kk, oo, p) or o.bloquee(kk, oo, p):
                continue
            statut, v = o.attendu(kk, oo, p)
            if statut == "imprecis":
                continue
            v = o.valeur(p, kk, oo, p)
            if isinstance(v, IC.Nombre):
                r = IC.arrondi_base(v.v)
                v = IC.Nombre(r, v.exact and r == v.v)
            nouvelles[(kk, oo, p.cle)] = (statut, v)
    stockees.update(nouvelles)
    return kpis, orgs


def refaire_lectrices(cas_i, cellules, memoire, stockees):
    """Saisie (lot, valeur forcée, retour au calcul) dans une période non figée ``cellules`` = [(KPI, organisation, clé
    de période)] alors qu'une période est rouverte en gardant les chiffres de l'époque (README, « Which cells a
    correction recalculates, period by period ») : toute période qui lit la période changée ([X@P-1],
    [X@N-1], [X@AAAA], cumul d'une période plus longue), de proche en proche, refait les KPI qui lisent les KPI changés
    (et ceux qui en dépendent dans la période), pour les organisations touchées dans la période lue et leurs ancêtres
    dans son arbre à elle (plus, pour un paramètre hérité changé, les descendants de l'organisation saisie dans cet
    arbre). Seules les périodes rouvertes « garder » gardent leurs autres cases : leurs cases refaites sont recalculées
    ici et notées dans ``stockees`` ; une période close n'est jamais refaite. Renvoie {clé: (KPI, organisations)} des
    périodes « garder » refaites (les seules cases qu'une écriture peut y réécrire). Écrit d'après le README."""
    o = IC.Oracle(cas_i, memoire_figee=memoire, stockees=stockees)
    m = cas_i.get("mois_debut", 1)

    def exercice(q):
        return q.debut.year if q.debut.month >= m else q.debut.year - 1

    refs = {}
    for kk in cas_i["kpis"]:
        if kk["comp"] == "calcul":
            try:
                refs[kk["code"]] = IC.references(IC.analyser(kk["formula"]))
            except IC.FormuleIllisible:
                refs[kk["code"]] = []

    def meme_periode(codes, q):
        decs, sortie, pile = ("N", str(exercice(q))), set(), list(codes)
        while pile:
            x = pile.pop()
            if x in sortie:
                continue
            sortie.add(x)
            pile += [c for c, rs in refs.items() if any(r[1] == x and r[2] in decs for r in rs)]
        return sortie

    def lit(g, x):
        """Décalages par lesquels la période ``g`` lit la période ``x``."""
        decs = set()
        if g.type == x.type and g.cle != x.cle:
            if g.debut == IC.ajouter_mois(x.debut, IC.MOIS_PAR[x.type]):
                decs.add("P-1")
            if g.debut == IC.ajouter_mois(x.debut, 12):
                decs.add("N-1")
            if g.debut.month == x.debut.month:
                decs.add(str(exercice(x)))
        if IC.FINESSE[x.type] < IC.FINESSE[g.type] and g.debut <= x.debut and x.fin <= g.fin:
            decs.add("cumul")
        return decs

    def descendants(x, q):
        return set(o.descendants(x, q)) if x in o.arbre(q) else set()

    def ancetres(xs, q):
        arbre, sortie = o.arbre(q), set()
        for x in xs:
            while x is not None and x in arbre and x not in sortie:
                sortie.add(x)
                x = arbre[x]["parent"]
        return sortie

    refaites, pile = {}, []
    for k, oid, cle in cellules:
        x = o.periodes[cle]
        herite = o.kpis[k]["comp"] == "herite"
        touchees = ancetres({oid} | (descendants(oid, x) if herite else set()), x)
        pile.append((x, meme_periode({k}, x), touchees, oid if herite else None))
    vus = set()
    while pile:
        x, kpis_x, orgs_x, depart = pile.pop()
        for g in o.periodes.values():
            if g.statut == "cloturee" or g.cle == x.cle:
                continue
            decs = lit(g, x)
            if not decs:
                continue
            lus = {c for c, rs in refs.items() if any(r[1] in kpis_x and r[2] in decs - {"cumul"} for r in rs)}
            if "cumul" in decs:
                lus |= {kk for kk in kpis_x if o.kpis[kk]["comp"] != "calcul"}
            kpis_g = meme_periode(lus, g) if lus else set()
            if not kpis_g:
                continue
            base = {y for y in orgs_x if y in o.arbre(g)} | (descendants(depart, g) if depart is not None else set())
            orgs_g = ancetres(base, g)
            cle = (g.cle, frozenset(kpis_g), frozenset(orgs_g))
            if cle in vus:
                continue
            vus.add(cle)
            if g.statut == "gardee":
                ks, os_ = refaites.setdefault(g.cle, (set(), set()))
                ks |= kpis_g
                os_ |= orgs_g
            pile.append((g, kpis_g, orgs_g, depart))
    if refaites:
        o = IC.Oracle(cas_i, memoire_figee=memoire, stockees=stockees, refaites=refaites)
        nouvelles = {}
        for cle, (kpis, orgs) in refaites.items():
            p = o.periodes[cle]
            for kk in kpis:
                for oo in orgs:
                    if kk not in o.kpis or not o.produite(kk, oo, p) or o.bloquee(kk, oo, p):
                        continue
                    statut, v = o.attendu(kk, oo, p)
                    if statut == "imprecis":
                        continue
                    v = o.valeur(p, kk, oo, p)
                    if isinstance(v, IC.Nombre):
                        r = IC.arrondi_base(v.v)
                        v = IC.Nombre(r, v.exact and r == v.v)
                    nouvelles[(kk, oo, cle)] = (statut, v)
        stockees.update(nouvelles)
    return refaites


def verifier(cas):
    """Compare chaque état de l'outil avec le second calcul. Renvoie (différences par étape, compte)."""
    global PLEIN, PAGES
    n1 = []
    PLEIN = [] if PLEIN_DEMANDE else None
    PAGES = [] if PAGES_DEMANDE else None
    try:
        etats = executer(cas, n1)
        plein, pages = PLEIN, PAGES
    finally:
        PLEIN = PAGES = None
    resultat, compte = {}, Counter()
    if plein:
        resultat["targeted != full"] = plein
    if pages:
        resultat["pages"] = pages
    if plein is not None:
        compte["full recalculations compared"] += len(cas["changes"])
    initial = dict(etats)["pass2"]
    # deuxième passage : ne change rien (statut, valeur)
    avant = dict(etats)["initial"]
    for cle in set(avant) | set(initial):
        a, b = avant.get(cle), initial.get(cle)
        if (a is None) != (b is None) or (a and (a[0], a[2], a[3]) != (b[0], b[2], b[3])) or (
                a and a[1] is not None and b[1] is not None and abs(a[1] - b[1]) > Decimal("1e-6") * max(1, abs(a[1]))):
            resultat.setdefault("second pass", []).append(dict(cell=cle, first=str(a), second=str(b)))
    d, oracle0, c = comparer(cas, initial)
    compte.update(c)
    if d:
        resultat["initial"] = d
    cloture, stockees = copy.deepcopy(cas["orgs"]), {}  # arbre noté à la clôture ; cases figées refaites
    # KPI figés par une campagne clôturée, notés au début du cas (règle « Figer ses chiffres »)
    figes = {f"{t}:{d}": sorted(v) for (t, d), v in _gelees_du_cas(cas).items() if v}
    # période reclôturée après une réouverture « recalculer » (--v4) : son arbre et ses chiffres sont ceux du jour de la
    # reclôture (README) ; ``memoire`` donne à chaque période figée ses chiffres enregistrés
    cloture_par, memoire = {}, _Memoires(oracle0)
    # README : une ancienne saisie d'un KPI devenu calculé, dans une période non figée, est remplacée par le calcul ;
    # celles des périodes non figées au premier calcul ne sont plus en base quand le KPI se fige ensuite (note « Figer
    # ses chiffres », reclôture) : le second calcul ne les relit pas
    calcules = {k["code"] for k in cas["kpis"] if k["comp"] == "calcul"}
    libres0 = {f"{p['type']}:{p['debut']}" for p in cas["periods"] if IC.statut_effectif(p) != "cloturee"}
    remplacees = {(s["k"], s["o"], s["p"]) for s in cas["inputs"]
                  if s["origin"] == "saisie" and s["k"] in calcules and s["p"] in libres0}
    for i, (nom, lignes) in enumerate(etats[2:], start=1):
        ch = cas["changes"][i - 1]
        if ch.get("type") == "reclose":
            prec = _sans_remplacees(_cas_apres(cas, i - 1), remplacees)
            if next(x for x in prec["periods"] if f"{x['type']}:{x['debut']}" == ch["p"])["status"] != "gardee":
                prec["closure_orgs"] = copy.deepcopy(cloture)
                prec["closure_orgs_by_period"] = copy.deepcopy(cloture_par)
                prec["partial_frozen"] = figes
                memoire.par[IC.tuple_cle(ch["p"])] = IC.Oracle(prec, memoire_figee=memoire, stockees=dict(stockees))
                cloture_par[ch["p"]] = copy.deepcopy(prec["orgs"])
        elif ch.get("type") == "reopen" and ch["mode"] != "garder":
            cloture_par.pop(ch["p"], None)
            memoire.par.pop(IC.tuple_cle(ch["p"]), None)
            # README (« Recalculation », « Recalculate with today's organisation ») : la période rouverte n'est plus
            # figée, le résultat de la formule remplace l'ancienne saisie d'un KPI calculé (sauf KPI figé par une
            # campagne clôturée) ; à la reclôture, c'est ce résultat qui se fige, plus l'ancienne saisie
            remplacees |= {(s["k"], s["o"], s["p"]) for s in _cas_apres(cas, i)["inputs"]
                           if s["p"] == ch["p"] and s["origin"] == "saisie" and s["k"] in calcules
                           and s["k"] not in figes.get(ch["p"], ())}
        cas_i = _sans_remplacees(_cas_apres(cas, i), remplacees)
        cas_i["closure_orgs"] = copy.deepcopy(cloture)
        cas_i["closure_orgs_by_period"] = copy.deepcopy(cloture_par)
        cas_i["partial_frozen"] = figes
        q = next((x for x in cas_i["periods"] if f"{x['type']}:{x['debut']}" == ch.get("p")), None)
        if ch.get("type") == "reopen" and ch["mode"] != "garder":
            stockees = {c_: v for c_, v in stockees.items() if f"{c_[2][0]}:{c_[2][1].isoformat()}" != ch["p"]}
        d5 = ch.get("type") == "import" and not ch.get("refuse") and q is not None and IC.statut_effectif(q) == "cloturee"  # période close
        figes_q = IC.Oracle(cas_i).gelees(IC.Oracle(cas_i).periodes[IC.tuple_cle(ch["p"])]) if q is not None else ()
        if ch.get("type") == "import" and not ch.get("refuse") and ch["k"] in figes_q:  # KPI figé par la campagne clôturée
            d5 = True
        if (ch.get("type") == "fix" and q is not None and q["status"] == "gardee") or d5:
            permises = refaire_figee(cas_i, ch, memoire, stockees)
            # chiffres publiés (marqués à la réouverture) : seule la lignée de l'époque refaite peut être réécrite, en
            # comparant à l'état d'avant la correction (pas au recalcul complet, qui n'est pas la référence ici)
            avant = etats[i][1]
            for cle, ligne in lignes.items():
                marque = (avant.get(cle) or (None,) * 6)[4] in ("calcul", "agregation", "cumul") if d5 else (
                    (avant.get(cle) or (None,) * 6)[5] == PUBLIE)  # marquées par l'écriture elle-même
                if f"{cle[0]}:{cle[1]}" != ch["p"] or not marque or ligne[5] == PUBLIE:
                    continue
                if figes_q and cle[2] not in figes_q:
                    continue  # KPI de la campagne ouverte : recalcul ordinaire (comparé au second calcul plus bas)
                if not (cle[2] in permises[0] and (permises[1] is None or cle[3] in permises[1])):
                    resultat.setdefault(nom, []).append(dict(cell=cle, expected="published figure kept",
                                                             tool="rewritten", tool_value=str(ligne[1]), message=ligne[5]))
        libres = [(c_["k"], c_["o"], IC.tuple_cle(c_["p"])) for c_ in (
            ch["cells"] if ch.get("type") == "batch" else [ch] if ch.get("type") in ("force", "unforce", "import_calcule", None) and "p" in ch
            else [])]
        libres = [x for x in libres if next(y for y in cas_i["periods"] if (y["type"], y["debut"]) == (
            x[2][0], x[2][1].isoformat()))["status"] not in ("cloturee", "gardee")]
        corrigee = None
        if (ch.get("type") == "fix" and q is not None and q["status"] == "gardee") or d5:
            # correction d'une période figée : les périodes « garder » qui la lisent la suivent aussi (README)
            libres, corrigee = [(ch["k"], ch["o"], IC.tuple_cle(ch["p"]))], ch["p"]
        if libres and any(y["status"] == "gardee" for y in cas_i["periods"]):
            permises = refaire_lectrices(cas_i, libres, memoire, stockees)
            # chiffres publiés d'une période « garder » : seules les cases qui lisent la période changée peuvent bouger
            avant = etats[i][1]
            for cle, ligne in lignes.items():
                a = avant.get(cle)
                pc = (cle[0], datetime.date.fromisoformat(cle[1]))
                if a is None or a[4] not in ("calcul", "agregation", "cumul") or f"{cle[0]}:{cle[1]}" == corrigee or not any(
                        y["status"] == "gardee" and (y["type"], y["debut"]) == cle[:2] for y in cas_i["periods"]):
                    continue
                if (a[0], a[1], a[2], a[3]) == (ligne[0], ligne[1], ligne[2], ligne[3]):
                    continue
                ks, os_ = permises.get(pc, (set(), set()))
                if not (cle[2] in ks and cle[3] in os_):
                    resultat.setdefault(nom, []).append(dict(cell=cle, expected="published figure kept",
                                                             tool="changed", before=str(a[:4]), tool_value=str(ligne[:4])))
        d, _, c = comparer(cas_i, lignes, memoire_figee=memoire, stockees=stockees)
        compte.update(c)
        if d:
            resultat.setdefault(nom, []).extend(d)
    # comparaison avec N-1 (README) : pour une période comparée jamais close
    fin = _sans_remplacees(_cas_apres(cas, len(cas["changes"])), remplacees)
    fin["closure_orgs"] = copy.deepcopy(cloture)
    fin["closure_orgs_by_period"] = copy.deepcopy(cloture_par)
    fin["partial_frozen"] = figes
    o = IC.Oracle(fin)
    jamais_closes = {(x["type"], x["debut"]) for x in cas["periods"] if IC.statut_effectif(x) != "cloturee"}
    for periode, prec, paires, gardees in n1:
        if tuple(prec) not in jamais_closes:
            continue
        p = o.periodes[(prec[0], datetime.date.fromisoformat(prec[1]))]
        attendues = sorted((k, org) for k, org in map(tuple, paires) if k in o.kpis and o.comparable(k, org, p))
        outil = sorted(map(tuple, gardees))
        if attendues != outil:
            resultat.setdefault("n1", []).append(dict(cell=[periode, prec], expected=sorted(set(attendues) - set(outil)),
                                                      tool=sorted(set(outil) - set(attendues))))
        compte["N-1 comparisons"] += len(paires)
    return resultat, compte


# ---------------------------------------------------------------- réduction
def reduire(cas, toujours=None, budget=400):
    """Réduit un cas qui diffère : retire des changements, des saisies, des périodes, des organisations, des KPI, et
    simplifie les formules, tant que le cas réduit diffère encore (au plus ``budget`` exécutions)."""
    essais = [0]

    def differe(c):
        if essais[0] >= budget:
            return False
        essais[0] += 1
        try:
            r, _ = verifier(c)
        except Exception:
            return False
        return bool(r) if toujours is None else toujours(r)

    def essayer(liste_nom, cas):
        changé = True
        while changé:
            changé = False
            n = len(cas[liste_nom])
            taille = max(1, n // 2)
            while taille >= 1:
                i = 0
                while i < len(cas[liste_nom]):
                    c = copy.deepcopy(cas)
                    del c[liste_nom][i:i + taille]
                    c = _coherent(c)
                    if c is not None and differe(c):
                        cas, changé = c, True
                    else:
                        i += taille
                taille //= 2
        return cas

    for nom in ("changes", "inputs", "periods", "orgs", "kpis", "inputs"):
        cas = essayer(nom, cas)
    # formules : remplacer une formule par un de ses morceaux
    for k in list(cas["kpis"]):
        if k["comp"] != "calcul":
            continue
        for morceau in _morceaux(k["formula"]):
            c = copy.deepcopy(cas)
            next(x for x in c["kpis"] if x["code"] == k["code"])["formula"] = morceau
            if differe(c):
                cas = c
                k = next(x for x in cas["kpis"] if x["code"] == k["code"])
    # réglages : ramener chaque option à sa valeur la plus simple
    for k in list(cas["kpis"]):
        for champ, simple in (("above", False), ("na0", False), ("active", True), ("freqs", ["annee"])):
            if k.get(champ) != simple:
                c = copy.deepcopy(cas)
                next(x for x in c["kpis"] if x["code"] == k["code"])[champ] = simple
                if differe(_coherent(c) or cas):
                    cas = _coherent(c)
    return cas


def _morceaux(formule):
    """Sous-formules (opérandes de premier niveau) d'une formule, des plus courtes aux plus longues."""
    try:
        arbre = IC.analyser(formule)
    except IC.FormuleIllisible:
        return []
    out = []

    def texte(n):
        t = n[0]
        if t == "ref":
            return f"[{n[1]}{'' if n[2] == 'N' else '@' + n[2]}]"
        if t == "num":
            return str(n[1]) if n[1].denominator == 1 else format(Decimal(n[1].numerator) / Decimal(n[1].denominator), "f")
        if t == "neg":
            return f"-({texte(n[1])})"
        return f"({texte(n[1])} {t} {texte(n[2])})"

    def parcourir(n):
        if n[0] in ("+", "-", "*", "/"):
            out.append(texte(n[1]))
            out.append(texte(n[2]))
            parcourir(n[1])
            parcourir(n[2])
        elif n[0] == "neg":
            out.append(texte(n[1]))
    parcourir(arbre)
    return sorted({m for m in out if "[" in m}, key=len)


def _coherent(cas):
    """Après un retrait : enlève ce qui cite un élément disparu ; None si le cas n'a plus de sens."""
    orgs = {o["id"] for o in cas["orgs"]}
    if not cas["orgs"] or any(o["parent"] and o["parent"] not in orgs for o in cas["orgs"]):
        return None
    kpis = {k["code"] for k in cas["kpis"]}
    for k in cas["kpis"]:
        if k["comp"] == "calcul":
            try:
                if any(r[1] not in kpis for r in IC.references(IC.analyser(k["formula"]))):
                    return None
            except IC.FormuleIllisible:
                return None
    if not any(p["type"] == "annee" for p in cas["periods"]) and not cas["periods"]:
        return None
    periodes = {f"{p['type']}:{p['debut']}" for p in cas["periods"]}
    garder = lambda s: s["k"] in kpis and s["o"] in orgs and s["p"] in periodes  # noqa: E731
    cas["inputs"] = [s for s in cas["inputs"] if garder(s)]
    crees = {s["o"] for s in cas["changes"] if s.get("type") == "create" and s["parent"] in orgs}
    tous = orgs | crees
    for s in cas["changes"]:
        if s.get("type") == "batch":
            s["cells"] = [x for x in s["cells"] if garder(x)]
    cas["changes"] = [s for s in cas["changes"] if (
        bool(s["cells"]) if s.get("type") == "batch" else
        s["o"] in tous and s.get("parent", s["o"]) in tous if s.get("type") in ("close", "move", "open", "create")
        else s["p"] in periodes if s.get("type") in ("reopen", "reclose")
        else s["k"] in kpis if s.get("type") == "depuis"
        else s["k"] in kpis and s["o"] in orgs and s["p"] in periodes if s.get("type") == "fix" else garder(s))]
    return cas


# ---------------------------------------------------------------- ligne de commande
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", default="0:100", help="range of seeds, e.g. 0:500")
    ap.add_argument("--out", default=None, help="folder for the cases that differ (default: a temporary folder)")
    ap.add_argument("--minimize", action="store_true", help="reduce each differing case before saving it")
    ap.add_argument("--replay", help="run one saved case (JSON) and print its differences")
    ap.add_argument("--stop-after", type=int, default=0, help="stop after N differing cases (0: never)")
    ap.add_argument("--v3", action="store_true", help="more writes: validation, forced value and back to the calculation, "
                    "batch of entries, correction imported in a closed campaign (third review)")
    ap.add_argument("--full-check", action="store_true", help="after each change, compare the tool's state with a full "
                    "recalculation of every non-frozen period")
    ap.add_argument("--pages", action="store_true", help="at the end of each case, compare the figures of the "
                    "Visualisation (validated values) and the detail of each total with the saved cells")
    ap.add_argument("--postgres", action="store_true", help="use the database of DATABASE_URL (a test database is created)")
    ap.add_argument("--v4", action="store_true", help="a reopened period closed again, the tree changed, then reopened "
                    "a second time (either mode) and corrected (fourth review)")
    args = ap.parse_args()
    global V3, V4, PLEIN_DEMANDE, GARDER_URL, PAGES_DEMANDE
    V3, V4, PLEIN_DEMANDE, GARDER_URL, PAGES_DEMANDE = args.v3, args.v4, args.full_check, args.postgres, args.pages
    if args.replay:
        cas = json.load(open(args.replay))
        cas = cas.get("case", cas)
        r, compte = verifier(cas)
        print(json.dumps(r, indent=1, default=str, ensure_ascii=False))
        print(dict(compte))
        return 1 if r else 0
    out = Path(args.out or tempfile.mkdtemp(prefix="fuzz-out-"))
    out.mkdir(parents=True, exist_ok=True)
    a, b = (int(x) for x in args.seeds.split(":"))
    total, differents, compte, debut = 0, 0, Counter(), time.time()
    for seed in range(a, b):
        cas = generate(seed)
        try:
            r, c = verifier(cas)
        except Exception:
            r, c = {"crash": [traceback.format_exc()]}, Counter()
        total += 1
        compte.update(c)
        for ch in cas["changes"]:  # imports confirmés sur des cases calculées (``_imports_calcules_v3``)
            if ch.get("type") == "import_calcule":
                compte["calculated cells imported: " + ("nothing to force" if ch.get("refuse") else "forced")] += 1
        if r:
            differents += 1
            if args.minimize and "crash" not in r:
                cas = reduire(cas)
                r, _ = verifier(cas)
            (out / f"case-{seed}.json").write_text(json.dumps(dict(case=cas, differences=r), indent=1, default=str,
                                                              ensure_ascii=False))
            print(f"seed {seed}: DIFFERENT ({', '.join(f'{k}: {len(v)}' for k, v in r.items())})", flush=True)
            if args.stop_after and differents >= args.stop_after:
                break
        if total % 50 == 0:
            print(f"{total} cases, {differents} different, {time.time() - debut:.0f} s", flush=True)
    print(f"Done: {total} cases, {differents} different; cells: {dict(compte)}; cases in {out}", flush=True)
    return 1 if differents else 0


if __name__ == "__main__":
    sys.exit(main())
