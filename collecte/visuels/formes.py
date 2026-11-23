"""Visualisation v2 : formes, limites et mise en forme des valeurs (texte, nombre, unité, cellule)."""
import logging
import re
import secrets
from decimal import Decimal

from parametres import libelles as LB
from referentiel.formule import NA
from referentiel.models import KPI

from .. import visualisation as V
from ..nombres import arrondi, chiffres, sans_milliers  # noqa: F401  règle unique d'arrondi (comme les pages)

journal = logging.getLogger("reporting.visualisation")

# ---------------------------------------------------------------- formes et limites
TYPES = {  # code : rendu, largeur et hauteur par défaut, KPI au plus (0 : aucun KPI)
    "chiffre": {"rendu": "html", "largeur": 3, "hauteur": "m", "max": 1},
    "barres": {"rendu": "echarts", "largeur": 6, "hauteur": "m", "max": 8},
    "barres_empilees": {"rendu": "echarts", "largeur": 6, "hauteur": "m", "max": 8},
    "courbe": {"rendu": "echarts", "largeur": 6, "hauteur": "m", "max": 8},
    "anneau": {"rendu": "echarts", "largeur": 4, "hauteur": "m", "max": 8},
    "tableau": {"rendu": "html", "largeur": 12, "hauteur": "m", "max": 300},
    "organisations": {"rendu": "echarts", "largeur": 6, "hauteur": "m", "max": 1},
    "comparaison_n1": {"rendu": "echarts", "largeur": 6, "hauteur": "m", "max": 20},
    "remplissage": {"rendu": "echarts", "largeur": 6, "hauteur": "m", "max": 0},
}
SPECIAUX = ("auto", "indisponible")
LARGEURS = (3, 4, 6, 8, 9, 12)
HAUTEURS = ("s", "m", "l")
AXES = ("", "periodes", "organisations", "kpis", "reponses")
SERIES = ("", "kpis", "organisations", "reponses", "n_n1")
OPTIONS = {  # option : valeurs permises (une liste) ou type attendu
    "orientation": ["", "verticale", "horizontale"],
    "valeurs_ecrites": ["", "aucune", "derniere", "toutes"],
    "tri": ["", "valeur", "arbre", "nom"],
    "max": int,
    "repere": bool,
    "cent_pour_cent": bool,
    "forme_anneau": ["", "anneau", "camembert"],
    "total_centre": bool,
    "colonnes": ["", "periodes", "organisations"],
    "cases": list,
    "remplissage_par": ["", "organisations", "themes", "total"],
}
FILTRES_DEFAUT = {"periode": "auto", "comparaison": "n1", "org": None, "referentiel": "je_reponds_a", "themes": [],
                  "valeurs": "validees"}
TAILLE_MAX = 200 * 1024  # définition JSON d'une vue
MAX_VISUELS = 40  # visuels d'une vue (une vue convertie qui en a plus les garde : voir plafond_visuels)
MAX_KPIS_GRAPHIQUE = 8
MAX_KPIS_TABLEAU = 300
MAX_PERIODES = 24
MIN_PERIODES = 2
MAX_CATEGORIES = 30
MAX_SERIES = 8
MAX_ORGS_COLONNES = 12
MAX_BARRES_ORGS = 15
MAX_SOMMETS_CHIFFRE = 5
LIGNES_TABLEAU = 25
ID_VISUEL = re.compile(r"^[a-z0-9-]{1,24}$")
MOIS = {"annee": 12, "semestre": 6, "trimestre": 3, "mois": 1}


def lib(cle, n=None, **valeurs):
    return LB.libelle(cle, n=n, **valeurs)


def nouvel_id():
    return "v" + secrets.token_hex(4)


# ---------------------------------------------------------------- mise en forme (nombres de la langue)
def nombre(v, decimales, milliers=True):
    """« 1 234,56 » en français (comme ``templatetags.collecte.nombre``) ; séparateurs du fichier de langue sinon.
    Arrondi comme Excel (``arrondi``) ; ``milliers=False`` : sans séparateur de milliers (année)."""
    texte = chiffres(v, decimales, milliers)
    return texte.replace(",", "\0").replace(".", lib("format.decimal")).replace("\0", lib("format.milliers"))


def pourcent_texte(texte):
    """« 12,5 % » en français et en espagnol, « 12.5% » en anglais (fichier de langue)."""
    return lib("format.pourcent", valeur=texte)


def nombre_excel(v, decimales):
    """Nombre à virgule écrit dans un classeur : arrondi aux décimales de l'unité comme dans la page (``arrondi``) ;
    un entier ou un décimal exact est écrit tel quel (Excel l'affiche lui-même aux décimales du format)."""
    return float(arrondi(v, decimales)) if isinstance(v, float) else v


def formater(v, kpi):
    """Valeur (Decimal, N/A, réponse ou décompte) au format du KPI ; « – » sans valeur."""
    if v is None:
        return "–"
    if v is NA:
        return lib("visu.etat.na")
    if not isinstance(v, Decimal):
        return kpi.reponse_affichee(v.texte(kpi.choix) if hasattr(v, "texte") else str(v))
    if kpi.est_pourcentage:
        return pourcent_texte(nombre(v * 100, kpi.decimales))
    return f"{nombre(v, kpi.decimales, milliers=not sans_milliers(kpi))} {kpi.symbole}".strip()


def texte_point(p, kpi):
    if p is None or (p.valeur is None and not p.en_attente):
        return "–"
    if p.en_attente:
        return lib("visu.etat.attente_long")
    return formater(p.valeur, kpi)


def etat_point(p):
    if p is None or (p.valeur is None and not p.en_attente):
        return "vide"
    if p.en_attente:
        return "attente"
    if p.na:
        return "na"
    return "provisoire" if p.provisoire else "valide"


def texte_lu(p, kpi):
    """Texte d'un tableau ou d'une infobulle : la valeur, et « (provisoire) » le cas échéant."""
    t = texte_point(p, kpi)
    return f"{t} ({lib('visu.etat.provisoire')})" if p is not None and p.provisoire and p.valeur is not None else t


def valeur_json(p, kpi):
    """Nombre à dessiner (pourcentage de 0 à 100) ; None sans valeur numérique."""
    if p is None or p.nombre is None:
        return None
    return float(p.nombre * 100) if kpi.est_pourcentage else float(p.nombre)


def ecart(p, n1):
    """(« ▲ +4,2 % », sens, fraction) de l'écart relatif, ou (« », None, None)."""
    e = V.ecart(p, n1)
    if e is None:
        return "", None, None
    if e == 0:
        return "= " + pourcent_texte("0"), "egal", 0.0
    signe = "+" if e > 0 else "−"
    return f"{'▲' if e > 0 else '▼'} {pourcent_texte(signe + nombre(abs(e) * 100, 1))}", "hausse" if e > 0 else "baisse", float(e)


def unite(kpi):
    return {"symbole": kpi.symbole, "pourcentage": kpi.est_pourcentage, "decimales": kpi.decimales,
            "numerique": kpi.est_numerique}


def meme_unite(kpis):
    return len({(k.format, k.symbole) for k in kpis}) <= 1


def additionnable(kpi):
    return kpi.est_numerique and not kpi.est_pourcentage and kpi.methode_agregation == KPI.Agregation.SOMME


def cellule(texte, valeur=None, kpi=None, etat=None, **autres):
    """Cellule d'un tableau de données : texte affiché ; nombre exact pour l'Excel (pourcentage de 0 à 100), avec ce
    qu'il faut pour son format de nombre : décimales (« d »), pourcentage (« p »), symbole de l'unité (« s »), écart
    relatif (``ecart=True`` : le sens ▲ ▼ = est écrit par le format, ``visuels_excel.format_excel``)."""
    c = {"t": texte}
    if valeur is not None:
        c["v"] = valeur
        if kpi is not None:
            c["d"] = kpi.decimales
            c["p"] = kpi.est_pourcentage
            if not kpi.est_pourcentage and kpi.symbole:
                c["s"] = kpi.symbole
    if etat:
        c["e"] = etat
    c.update(autres)
    return c
