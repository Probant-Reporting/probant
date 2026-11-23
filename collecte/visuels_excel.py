"""Visualisation v2 : export Excel d'un visuel ou de toute une vue, calculé par le serveur (jamais à partir des données
du navigateur). Onglet « À lire » en premier (vue, visuel, filtres, périmètre, sens de validée, provisoire et en attente,
date, version), puis « Données » : le tableau de données du visuel (le même que celui de la page), avec les nombres
exacts aux décimales de l'unité, les pourcentages de 0 à 100 et une colonne « État ». Sans visuel choisi, un onglet
par visuel."""
import re

from django.conf import settings
from django.utils import timezone
from openpyxl.styles import Alignment

from . import dates_courtes as DC
from . import fichiers as F
from .visuels import lib, nombre_excel

ETATS = {"valide": "visu.etat.valide", "provisoire": "visu.etat.provisoire", "attente": "visu.etat.attente",
         "na": "visu.etat.na"}
INTERDITS = re.compile(r"[\[\]:*?/\\]")


def _nom_onglet(texte, pris):
    base = INTERDITS.sub(" ", str(texte or "")).strip()[:28] or lib("visu.export.donnees")
    nom, n = base, 1
    while nom.lower() in pris:
        n += 1
        nom = f"{base[:25]} ({n})"
    pris.add(nom.lower())
    return nom


def _filtres(donnees):
    f = donnees["filtres"]
    morceaux = []
    if f["periode"]["libelle"]:
        morceaux.append(lib("visu.export.periode", periode=f["periode"]["libelle"]))
    if f["comparaison"]["libelle"]:
        morceaux.append(lib("visu.export.comparaison", periode=f["comparaison"]["libelle"]))
    morceaux.append(lib("visu.export.organisation", org=f["org"]["nom"]))
    morceaux.append(lib("visu.filtres.brouillons" if f["valeurs"] == "brouillons" else "visu.filtres.validees"))
    if f["referentiel"]["nom"]:
        morceaux.append(f"{lib('visu.filtres.referentiel')} : {f['referentiel']['nom']}")
    return " · ".join(morceaux)


ESPACE = " "  # espace insécable avant l'unité, comme dans la page


def _litteral(texte):
    """Texte écrit tel quel dans un format de nombre Excel (entre guillemets ; un guillemet du texte est retiré)."""
    return '"' + str(texte).replace('"', "") + '"'


def format_excel(c):
    """Format de nombre Excel d'une cellule de valeur : décimales de l'unité ; « % » d'un pourcentage (nombre de 0 à
    100) ; symbole de l'unité ; écart relatif : le sens (▲ hausse, ▼ baisse, = égal) avant le nombre, comme dans la
    page. L'unité et le sens sont dans le format, jamais dans la valeur : la cellule reste un nombre."""
    fmt = F.format_nombre(c.get("d") or 0)
    if c.get("ecart"):
        pct = _litteral(ESPACE + "%")
        return f"{_litteral('▲ +')}{fmt}{pct};{_litteral('▼ −')}{fmt}{pct};{_litteral('= ')}{fmt}{pct}"
    if c.get("p"):
        return fmt + _litteral(ESPACE + "%")
    if c.get("s"):
        return fmt + _litteral(ESPACE + c["s"])
    return fmt


def onglet_donnees(wb, nom, visuel):
    """Onglet d'un visuel : son tableau de données, nombres exacts, colonne « État »."""
    ws = wb.create_sheet(nom)
    t = visuel.get("tableau")
    if not t or not t.get("lignes"):
        F.ecrire_cellule(ws, 1, 1, visuel.get("message") or lib("visu.export.sans_donnees"))
        return ws
    entetes = list(t["entetes"]) + [lib("visu.etat.colonne")]
    for col, e in enumerate(entetes, start=1):
        F.ecrire_cellule(ws, 1, col, e)
    F.entetes(ws)
    for i, ligne in enumerate(t["lignes"], start=2):
        for col, c in enumerate(ligne["cellules"], start=1):
            if c.get("v") is not None:
                cell = ws.cell(i, col, nombre_excel(c["v"], c.get("d") or 0))  # arrondi comme Excel, comme dans la page
                cell.number_format = format_excel(c)
            else:
                F.ecrire_cellule(ws, i, col, c.get("t", ""))
        etat = ligne.get("etat") or ""
        F.ecrire_cellule(ws, i, len(entetes), lib(ETATS[etat]) if etat in ETATS else "")
    F.largeurs(ws, [42] + [18] * (len(entetes) - 1))
    ws.freeze_panes = "B2"
    for cell in ws[1]:
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    return ws


def classeur(nom_vue, donnees, ids=None):
    """Classeur d'une vue (ou des visuels ``ids``) à partir des données calculées par ``visuels.donnees``."""
    wb = F.classeur()
    ids = [i for i in (ids or donnees["ordre"]) if i in donnees["visuels"]]
    visuels = [donnees["visuels"][i] for i in ids]
    a_lire = [(lib("visu.export.vue"), nom_vue)]
    if len(visuels) == 1:
        a_lire.append((lib("visu.export.visuel"), visuels[0]["titre"]))
        if visuels[0].get("sous_titre"):
            a_lire.append(("", visuels[0]["sous_titre"]))
    else:
        a_lire.append((lib("visu.export.visuels"), ", ".join(v["titre"] for v in visuels)[:500]))
    a_lire += [
        (lib("visu.export.filtres"), _filtres(donnees)),
        (lib("visu.export.perimetre"), lib("visu.export.perimetre_texte")),
        (lib("visu.etat.valide"), lib("visu.export.validee_texte")),
        (lib("visu.etat.provisoire").capitalize(), lib("visu.export.provisoire_texte")),
        (lib("visu.etat.attente").capitalize(), lib("visu.export.attente_texte")),
        (lib("visu.export.nombres"), lib("visu.export.nombres_texte")),
        (lib("visu.export.date"), DC.date_courte(timezone.localdate())),
        (lib("visu.export.version"), settings.VERSION),
    ]
    F.feuille_lisez_moi(wb, lib("visu.export.titre", vue=nom_vue), a_lire, index=0, nom=lib("visu.export.a_lire"))
    pris = {lib("visu.export.a_lire").lower()}
    for v in visuels:
        nom = lib("visu.export.donnees") if len(visuels) == 1 else _nom_onglet(v["titre"], pris)
        onglet_donnees(wb, nom, v)
    return wb


def reponse(nom_vue, donnees, ids=None):
    visuels = [donnees["visuels"][i]["titre"] for i in (ids or []) if i in donnees["visuels"]]
    nom = F.nom_fichier("Visualisation", nom_vue, *(visuels[:1] if len(visuels) == 1 else []))
    return F.reponse_excel(classeur(nom_vue, donnees, ids), nom)
