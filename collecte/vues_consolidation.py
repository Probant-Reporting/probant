"""Tableau de bord › Consolidation : page et export Excel (calcul dans ``consolidation.py``)."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from parametres.libelles import libelle
from referentiel.plans import Plan

from . import consolidation as CO
from . import saisie as S
from .models import SelectionKPI
from .templatetags.collecte import formater
from .views import groupes_campagnes
from .vues_communes import campagne_affichee, memoriser_session


CASES = ("brouillons", "n1", "vides", "parametres")  # cases à cocher de la page
MODES = ("theme", "liste", "choix")  # choix des KPI : un thème, une liste enregistrée, ou cochés un par un
SENS = ("orgs", "kpis")  # organisations en lignes (par défaut), ou KPI en lignes (lignes et colonnes interverties)


def _reglages(request, campagne):
    """Choix de la page : KPI (mode, thème, liste, KPI cochés), cases (brouillons, N-1, colonnes sans valeur, paramètres
    hérités), sens du tableau et profondeur des organisations en colonnes. Ceux de l'adresse, sinon les derniers de la
    personne pour ce référentiel (mémorisés dans la session). Sans choix, les brouillons comptent pendant la saisie
    (campagne ouverte ou en revue : c'est là que la consolidation se suit), pas ensuite."""
    memo = (request.session.get("consolidation") or {}).get(str(campagne.referentiel_id))
    g = request.GET
    if any(k in g for k in ("theme", "liste", "selection", "choix_kpi", "kpis", "sens", "niveaux", "masquer_vides", *CASES)):
        mode = g.get("choix_kpi") or ("liste" if g.get("liste") or g.get("selection") else "theme")
        r = {"mode": mode if mode in MODES else "theme", "theme": ",".join(x for v in g.getlist("theme") for x in v.split(",") if x.strip()),
             "liste": g.get("selection") or g.get("liste", ""), "kpis": g.getlist("kpis")[:500],
             **{k: g.get(k) == "1" for k in CASES}, "sens": g.get("sens") if g.get("sens") in SENS else "orgs",
             # KPI sans valeur montrés sauf si « Masquer les KPI vides » est coché 
             **({"vides": g.get("masquer_vides") != "1"} if "masquer_vides" in g else {} if "vides" in g else {"vides": True}),
             "niveaux": int(g["niveaux"]) if str(g.get("niveaux", "")).isdecimal() else 1}
    elif memo is not None:
        r = {"mode": memo.get("mode", "liste" if memo.get("liste") else "theme"), "theme": memo.get("theme", ""),
             "liste": memo.get("liste", ""), "kpis": list(memo.get("kpis") or []), **{k: bool(memo.get(k)) for k in CASES},
             "sens": memo.get("sens", "orgs"), "niveaux": int(memo.get("niveaux", 1))}
    else:
        en_saisie = campagne.statut in (campagne.Statut.OUVERTE, campagne.Statut.REVUE)
        r = {"mode": "theme", "theme": "", "liste": "", "kpis": [], **{k: False for k in CASES}, "brouillons": en_saisie, "vides": True,
             "sens": "orgs", "niveaux": 1}
    r["niveaux"] = min(max(r["niveaux"], 0), 8)
    tous = dict(request.session.get("consolidation") or {})
    tous[str(campagne.referentiel_id)] = r
    memoriser_session(request, "consolidation", tous)
    return r


def _donnees(request):
    campagne = campagne_affichee(request)
    if campagne is None:
        return None, {}
    r = _reglages(request, campagne)
    plan = Plan(campagne.referentiel)
    CO.preparer(plan, request.user, campagne)
    kpis, theme, liste, mode = CO.choix_kpi(request.user, plan, r["theme"], r["liste"], r["mode"], r["kpis"])
    themes = CO.themes_choisis(plan, r["theme"]) if mode == "theme" else []
    en_lignes = r["sens"] == "kpis"
    t = CO.tableau(request.user, campagne.periode, kpis, brouillons=r["brouillons"], avec_n1=r["n1"],
                   avec_vides=r["vides"], avec_parametres=r["parametres"],
                   max_kpis=CO.MAX_LIGNES_KPI if en_lignes else CO.MAX_COLONNES)
    d = {"reglages": r, "comparaison": S.libelle_comparaison(campagne), "plan": plan, "kpis": t.kpis,
         "theme": theme, "liste": liste, "mode": mode, "lignes": t.lignes, "caches": t.caches, "vides": t.vides,
         "parametres": t.parametres, "etats": t.etats, "query": _query(themes, liste, mode, [k.code for k in kpis], r),
         "en_lignes": en_lignes, "profondeurs": CO.profondeurs(t.lignes),
         "themes_choisis": themes, "theme_nom": (themes[0].tr("nom") if len(themes) == 1 else libelle("suivi.conso.n_themes", n=len(themes))) if themes else ""}
    if en_lignes:
        d["colonnes_orgs"], d["rangs_kpi"] = CO.transposer(t, r["niveaux"])
    return campagne, d


def _query(themes, liste, mode, codes, r):
    """Réglages de la page en paramètres d'adresse (lien de l'export Excel)."""
    from urllib.parse import urlencode

    return urlencode([("choix_kpi", mode), ("theme", ",".join(str(t.id) for t in themes)), ("selection", liste.pk if liste else ""),
                      *[("kpis", c) for c in (codes if mode == "choix" else [])],
                      *[(k, "1" if r[k] else "0") for k in CASES], ("sens", r["sens"]), ("niveaux", r["niveaux"])])


def _ck(request, plan, themes, liste, mode, codes):
    """Contexte du sélecteur de KPI partagé avec Import / Export (``echanges/_choix_kpi.html``)."""
    listes = list(SelectionKPI.visibles(request.user).prefetch_related("kpis").order_by("nom"))
    for x in listes:
        x.codes = " ".join(sorted(k.code for k in x.kpis.all()))
        x.nb = len(x.codes.split()) if x.codes else 0
        x.modifiable = x.modifiable_par(request.user)
    return {"listes": listes, "groupes": CO.groupes_a_cocher(plan), "mode": mode, "themes_ids": {t.id for t in themes},
            "selection": str(liste.pk) if liste else "", "choisis": set(codes) if mode == "choix" else set()}


@never_cache  # retour arrière du navigateur : les valeurs sont relues
@login_required
def consolidation(request):
    campagne, d = _donnees(request)
    if campagne is None:
        return render(request, "collecte/aucune_campagne.html")
    return render(request, "collecte/consolidation.html", {
        **d, "campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user), "page": "tableau_de_bord", "consolidation": True,
        "themes": CO.themes(d["plan"], campagne.referentiel),
        "ck": _ck(request, d["plan"], d["themes_choisis"], d["liste"], d["mode"], d["reglages"]["kpis"]),
        "max_colonnes": CO.MAX_LIGNES_KPI if d["en_lignes"] else CO.MAX_COLONNES,
    })


def _texte(case, kpi):
    """Contenu d'une case dans le fichier Excel : la valeur affichée, ou ce qui en tient lieu."""
    if case.absente or case.point is None:
        return ""
    p = case.point
    if p.en_attente and case.partiel is not None:
        return case.partiel
    if p.en_attente:
        return libelle("suivi.conso.en_attente")
    if p.valeur is None:
        if case.partiel is not None:  # total partiel : le nombre (en italique, avec une note dans le fichier)
            return case.partiel
        if case.erreur:
            return libelle("suivi.conso.erreur")
        return libelle("suivi.conso.incomplet") if case.incomplet else ""  # « — » (non saisie) : case vide
    return p.nombre if p.nombre is not None and not kpi.est_pourcentage else formater(p.valeur, kpi)


@login_required
def consolidation_excel(request):
    """Le tableau tel qu'affiché, toutes les lignes dépliées (retrait selon le niveau)."""
    from django.utils.text import slugify
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font

    from .fichiers import ajouter, reponse_excel

    campagne, d = _donnees(request)
    if campagne is None:
        return HttpResponse(status=404)
    avec_n1 = d["reglages"]["n1"]
    wb = Workbook()
    ws = wb.active
    ws.title = libelle("suivi.conso.titre")[:31]
    ajouter(ws, [f"{campagne.referentiel} · {campagne.periode}",
                 libelle("suivi.conso.excel.brouillons" if d["reglages"]["brouillons"] else "suivi.conso.excel.validees")])
    ws.cell(1, 1).font = Font(bold=True)
    ajouter(ws, [])
    pas = 3 if avec_n1 else 1

    def titres_colonne(nom, court):
        return [nom] + ([f"{court} – {d['comparaison']}", f"{court} – {libelle('suivi.conso.col.ecart')}"] if avec_n1 else [])

    def kpi_nom(k):
        unite = f" ({k.symbole})" if k.symbole and not k.est_pourcentage else ""
        return f"{k.code} – {k.nom}{unite}"

    # [(libellés de tête de ligne, retrait, cases)] et en-têtes : le même tableau que la page, dans le même sens
    if d["en_lignes"]:
        entete = [libelle("suivi.conso.col.kpi")] + [t for l in d["colonnes_orgs"] for t in titres_colonne(f"{l.org.nom} ({l.org.niveau or ''})", l.org.nom)]
        lignes = [([kpi_nom(k)], 0, cases) for k, cases in d["rangs_kpi"]]
        en_tete = 1
    else:
        entete = [libelle("suivi.conso.col.organisation"), libelle("suivi.conso.col.niveau")] + [t for k in d["kpis"] for t in titres_colonne(kpi_nom(k), k.code)]
        lignes = [([l.org.nom, str(l.org.niveau or "")], l.prof, l.cases) for l in d["lignes"]]
        en_tete = 2
    ajouter(ws, entete)
    for cell in ws[3]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for tete, retrait, cases in lignes:
        valeurs = list(tete)
        for case in cases:
            valeurs.append(_texte(case, case.kpi))
            if avec_n1:
                valeurs += [_texte(CO.Case(case.kpi, point=case.n1), case.kpi), float(case.ecart) if case.ecart is not None else ""]
        ajouter(ws, valeurs)
        ws.cell(ws.max_row, 1).alignment = Alignment(indent=retrait * 2)
        for i, case in enumerate(cases):
            colonne = en_tete + 1 + i * pas
            if case.partiel is not None and case.point is not None and case.point.valeur is None:  # (en attente compris)
                # total partiel : en italique gris, avec une note qui dit ce qui manque
                cellule = ws.cell(ws.max_row, colonne)
                cellule.font = Font(italic=True, color="6B6B6B")
                cellule.comment = Comment(libelle("suivi.conso.partiel_note", n=case.manquants), libelle("suivi.conso.titre"))
            if avec_n1:
                ws.cell(ws.max_row, colonne + 2).number_format = "0.0%"
    ws.column_dimensions["A"].width = 44 if d["en_lignes"] else 36
    ws.freeze_panes = ws.cell(4, en_tete + 1).coordinate
    return reponse_excel(wb, slugify(f"consolidation {campagne.referentiel.code} {campagne.periode}") or "consolidation")
