"""Database probe for the browser journeys (qa/journeys.js): reads one JSON request per line on standard input and
answers one JSON line. Read only: each request names one of the checks below (no free code).

    DATA_DIR=/folder/of/the/disposable/demo python3 qa/journeys_probe.py

    DATA_DIR=… python3 qa/journeys_probe.py --prepare   # before the journey: the current campaign goes back to
                                                        # "in preparation" (the only write, on the disposable copy)
    python3 qa/journeys_probe.py --fix-xlsx in.xlsx out.xlsx "abc=42"   # corrects a downloaded rejection file

Request: {"q": "name", "args": {...}}  →  answer: {"ok": true, "r": ...} or {"ok": false, "error": "..."}.
Used on a disposable demo only (no real data).
"""
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402

from collecte import saisie as S  # noqa: E402
from collecte.models import (Alerte, Campagne, DemandeForcage, Journal, Preuve, Relance, ReglageExport,  # noqa: E402
                             Reponse, VueVisu)
from parametres.models import Instance, Langue, NiveauHierarchique  # noqa: E402
from referentiel.models import KPI, Attribution, Organisation, Utilisateur  # noqa: E402


def _reponse(a):
    r = Reponse.objects.filter(periode__campagnes__pk=a["campagne"], kpi_id=a["kpi"], organisation_id=a["org"]).first()
    if r is None:
        return None
    return {"valeur": None if r.valeur is None else format(r.valeur.normalize(), "f"), "texte": r.texte, "na": r.non_applicable,
            "commentaire": r.commentaire, "statut": r.statut, "origine": r.origine,
            "preuves": Preuve.objects.filter(reponse=r).count()}


def _cases(a):
    """Cases numériques saisissables d'une personne (pas pourcentage, pas entier, pas calculées), avec N-1 connu."""
    u = Utilisateur.objects.get(username=a["user"])
    c = Campagne.objects.get(pk=a["campagne"])
    sortie = []
    for k, o in S.cellules(u, campagne=c):
        if k.est_calcule or not k.est_numerique or k.est_pourcentage or k.est_entier or k.est_herite:
            continue
        sortie.append({"kpi": k.code, "org": o.pk, "org_nom": o.nom, "nom": k.nom})
        if len(sortie) >= a.get("n", 12):
            break
    return sortie


def _empreinte(a):
    """Nombre de lignes et somme de contrôle des tables métier (aucune écriture attendue pour un lecteur)."""
    import hashlib

    tables = [t for t in connection.introspection.table_names() if t.startswith(("collecte_", "referentiel_", "parametres_"))]
    sortie = {}
    with connection.cursor() as cur:
        for t in sorted(tables):
            h = hashlib.sha256()
            cur.execute(f'SELECT * FROM "{t}" ORDER BY 1')
            for ligne in cur.fetchall():
                h.update(repr(ligne).encode())
            sortie[t] = h.hexdigest()[:16]
    return sortie


def _calcules(a):
    """KPI calculés numériques d'une organisation (granularité de son niveau), sans demande de valeur forcée."""
    c = Campagne.objects.get(pk=a["campagne"])
    org = Organisation.objects.get(nom=a["org_nom"])
    sortie = []
    for k in KPI.objects.filter(actif=True, type_saisie__comportement="calcul", granularite=org.niveau).order_by("code"):
        if S.dans_la_campagne(c, k) and k.est_numerique and not k.est_pourcentage and not DemandeForcage.objects.filter(kpi=k, organisation=org).exists():
            sortie.append({"kpi": k.code, "org": org.pk, "niveau": org.niveau_id})
        if len(sortie) >= a.get("n", 2):
            break
    return sortie


def _alerte_justifiable(a):
    """Alerte ouverte d'une case de la personne qui se justifie dans le panneau (pas un écart N-1, pas un calcul)."""
    u = Utilisateur.objects.get(username=a["user"])
    c = Campagne.objects.get(pk=a["campagne"])
    cases = {(k.code, o.pk) for k, o in S.cellules(u, campagne=c)}
    for x in Alerte.objects.filter(campagne=c, statut=Alerte.Statut.OUVERTE).exclude(controle__in=["ecart_n1", "calcul"]).order_by("pk"):
        if (x.kpi_id, x.organisation_id) in cases:
            return {"pk": x.pk, "kpi": x.kpi_id, "org": x.organisation_id}
    return None


REQUETES = {
    "campagne": lambda a: (lambda c: c and {"pk": c.pk, "statut": c.statut, "exercice": c.exercice})(
        Campagne.objects.filter(**({"pk": a["pk"]} if "pk" in a else {"exercice": a["exercice"], "referentiel_id": a.get("ref", "VS_BASE")})).first()),
    "reponse": _reponse,
    "cases": _cases,
    "utilisateur": lambda a: (lambda u: u and {"pk": u.pk, "role": u.role, "doit_changer_mdp": u.doit_changer_mdp, "actif": u.is_active,
                                               "langue": getattr(u, "langue", ""), "email": u.email})(
        Utilisateur.objects.filter(**({"username": a["username"]} if "username" in a else {"email": a["email"]})).first()),
    "attributions": lambda a: sorted(f"{k}|{o}" for k, o in Attribution.objects.filter(utilisateur__username=a["user"]).values_list("kpi_id", "organisation_id")),
    "preuves": lambda a: Preuve.objects.filter(reponse__periode__campagnes__pk=a["campagne"], reponse__kpi_id=a["kpi"],
                                               reponse__organisation_id=a["org"]).count(),
    "alertes": lambda a: [{"pk": x.pk, "statut": getattr(x, "statut", ""), "justification": x.justification, "controle": x.controle}
                          for x in Alerte.objects.filter(campagne_id=a["campagne"], kpi_id=a["kpi"], organisation_id=a["org"])],
    "demandes": lambda a: [{"pk": d.pk, "statut": d.statut, "valeur": None if d.valeur is None else format(d.valeur.normalize(), "f")}
                           for d in DemandeForcage.objects.filter(kpi_id=a["kpi"], organisation_id=a["org"]).order_by("pk")],
    "relances": lambda a: [{"statut": r.statut} for r in Relance.objects.order_by("-pk")[: a.get("n", 5)]],
    "journal": lambda a: Journal.objects.filter(action=a["action"]).count(),
    "exports": lambda a: [{"pk": r.pk, "nom": r.nom} for r in ReglageExport.objects.filter(partage=True).order_by("ordre", "nom")],
    "vues": lambda a: [{"pk": v.pk, "nom": v.nom, "visuels": len(v.visuels or [])}
                       for v in VueVisu.objects.filter(proprietaire__username=a["user"]).order_by("pk")],
    "instance": lambda a: (lambda i: {"nom": i.nom, "sous_titre": i.sous_titre, "langue": i.langue})(Instance.objects.get(pk=1)),
    "campagne_dates": lambda a: (lambda c: {"date_ouverture": c.date_ouverture, "date_fin_saisie": c.date_fin_saisie})(Campagne.objects.get(pk=a["pk"])),
    "niveaux": lambda a: [{"code": n.code, "nom": n.nom} for n in NiveauHierarchique.objects.order_by("rang")],
    "langues": lambda a: [{"code": l.code, "active": l.active} for l in Langue.objects.order_by("code")],
    "empreinte": _empreinte,
    "calcules": _calcules,
    "alerte_justifiable": _alerte_justifiable,
    "alerte": lambda a: (lambda x: x and {"statut": x.statut, "justification": x.justification})(Alerte.objects.filter(pk=a["pk"]).first()),
    "org": lambda a: (lambda o: o and {"pk": o.pk, "nom": o.nom})(Organisation.objects.filter(nom=a["nom"]).first()),
}


def preparer():
    """Seule écriture de l'outil, avant le parcours, sur la démo jetable : la campagne ouverte la plus récente du
    référentiel principal repasse « en préparation », pour que l'administrateur la prépare puis l'ouvre."""
    c = Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).order_by("-exercice", "referentiel__ordre").first()
    if c is not None:
        Campagne.objects.filter(pk=c.pk).update(statut=Campagne.Statut.PREPARATION)
    print(json.dumps({"campagne": c and c.pk, "exercice": c and c.exercice}))


def corriger_classeur(entree, sortie, remplacements):
    """Fichier des lignes refusées corrigé comme le ferait une personne : chaque cellule égale à un texte « avant »
    reçoit le texte « après » (« abc=42 »). Outil de recette, sur un fichier de la démo jetable."""
    from openpyxl import load_workbook

    paires = dict(r.split("=", 1) for r in remplacements)
    wb = load_workbook(entree)
    n = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.strip() in paires:
                    c.value = paires[c.value.strip()]
                    n += 1
    wb.save(sortie)
    print(json.dumps({"remplacees": n}))


def main():
    if sys.argv[1:] == ["--prepare"]:
        return preparer()
    if sys.argv[1:2] == ["--fix-xlsx"]:
        return corriger_classeur(sys.argv[2], sys.argv[3], sys.argv[4:])
    for ligne in sys.stdin:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            d = json.loads(ligne)
            r = REQUETES[d["q"]](d.get("args") or {})
            print(json.dumps({"ok": True, "r": r}, default=str), flush=True)
        except Exception as e:  # noqa: BLE001 — renvoyée au script, qui la signale
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}), flush=True)
        finally:
            connection.close()  # relire la base à chaque requête (le serveur écrit à côté)


if __name__ == "__main__":
    main()
