"""Réponses en forme de tableau (format « tableau »).

Certaines normes demandent une liste de longueur variable : une ligne par polluant, par code de déchet, par filiale, par
matière. Le type de réponse définit les colonnes (``TypeReponse.colonnes``) :

    [{"code": "polluant", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "liste", "liste": "VS-POLLUANT"},
     {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"}]

- ``nombre`` : un nombre (virgule ou point) ; ``texte`` : un texte court sur une ligne ; ``liste`` : une valeur d'un autre
  type de réponse « liste de choix » (son code dans ``liste``), écrite dans n'importe quelle langue de l'installation.
- La réponse est enregistrée comme un **tableau Markdown** dans ``Reponse.texte`` : tout ce qui sait afficher, exporter,
  importer ou exclure des calculs un texte rédigé le fait aussi pour un tableau. L'en-tête est réécrit dans la langue de
  référence ; les nombres sont enregistrés avec un point ; les valeurs de liste par leur valeur de référence.
- Un tableau n'est ni additionné ni calculé par l'outil : ``fusionner`` regroupe les lignes de plusieurs organisations
  quand un export le demande (lignes de même clé additionnées).
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError

from parametres import langues as L
from parametres.libelles import libelle

MAX_LIGNES = 500
TYPES_COLONNE = ("nombre", "texte", "liste")
_SEPARATEUR = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


@dataclass
class Colonne:
    code: str
    libelles: dict
    type: str
    liste: str = ""
    unite: str = ""

    def libelle(self, langue=None):
        lg = langue or L.courante()
        t = self.libelles.get(lg) or self.libelles.get(L.reference()) or next((v for v in self.libelles.values() if v), self.code)
        return f"{t} ({self.unite})" if self.unite else t


def colonnes(type_reponse):
    """Colonnes d'un type de réponse « tableau » (liste vide sinon) ; une colonne mal décrite est ignorée."""
    sortie = []
    for c in (type_reponse.colonnes or []) if type_reponse is not None else []:
        if not isinstance(c, dict) or c.get("type") not in TYPES_COLONNE or not str(c.get("code") or "").strip():
            continue
        lib = c.get("libelle")
        libelles = lib if isinstance(lib, dict) else ({L.reference(): str(lib)} if lib else {})
        sortie.append(Colonne(str(c["code"]).strip(), {k: str(v) for k, v in libelles.items() if v}, c["type"],
                              str(c.get("liste") or ""), str(c.get("unite") or "")))
    return sortie


def erreurs_colonnes(valeur, listes_connues):
    """Motifs de refus d'une définition de colonnes (réglages, fichiers) ; ``listes_connues`` : codes des types « liste »."""
    erreurs, vus = [], set()
    if not isinstance(valeur, list) or not valeur:
        return [libelle("messages.tableau.colonnes_vides")]
    for i, c in enumerate(valeur, start=1):
        if not isinstance(c, dict):
            erreurs.append(libelle("messages.tableau.colonne_illisible", n=i))
            continue
        code = str(c.get("code") or "").strip()
        if not code or code in vus:
            erreurs.append(libelle("messages.tableau.code_colonne", n=i))
        vus.add(code)
        if c.get("type") not in TYPES_COLONNE:
            erreurs.append(libelle("messages.tableau.type_colonne", n=i, types=", ".join(TYPES_COLONNE)))
        elif c["type"] == "liste" and c.get("liste") not in listes_connues:
            erreurs.append(libelle("messages.tableau.liste_inconnue", n=i, liste=c.get("liste") or "—"))
    return erreurs


def valeurs_utilisees(code_liste, valeurs):
    """Vrai si une réponse d'un KPI au format « tableau » porte une de ``valeurs`` dans une colonne qui renvoie à la liste
    ``code_liste`` : retirer cette valeur de la liste rendrait la réponse impossible à enregistrer de nouveau ou à
    réimporter (même règle que pour une réponse « liste », Paramètres et classeur de configuration)."""
    from parametres.models import TypeReponse

    from .models import Reponse

    for t in TypeReponse.objects.filter(format=TypeReponse.Format.TABLEAU):
        rangs = [i for i, c in enumerate(colonnes(t)) if c.type == "liste" and c.liste == code_liste]
        if not rangs:
            continue
        for texte in Reponse.objects.filter(kpi__type_reponse=t.pk).exclude(texte="").values_list("texte", flat=True).iterator():
            if any(i < len(ligne) and ligne[i] in valeurs for ligne in lignes_brutes(texte) for i in rangs):
                return True
    return False


def _cellules(ligne):
    """Cellules d'une ligne de tableau Markdown (« \\| » : barre écrite dans une cellule)."""
    t = ligne.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|") and not t.endswith("\\|"):
        t = t[:-1]
    morceaux = re.split(r"(?<!\\)\|", t)
    return [m.strip().replace("\\|", "|") for m in morceaux]


def lignes_brutes(texte):
    """Lignes de données (listes de textes) d'un tableau Markdown, sans l'en-tête ni la ligne de séparation."""
    lignes = [l for l in (texte or "").replace("\r\n", "\n").split("\n") if l.strip()]
    if not lignes:
        return []
    if len(lignes) >= 2 and _SEPARATEUR.match(lignes[1].strip()):
        lignes = lignes[2:]
    elif lignes and _SEPARATEUR.match(lignes[0].strip()):
        lignes = lignes[1:]
    return [_cellules(l) for l in lignes if not _SEPARATEUR.match(l.strip())]


def _types_listes(cols):
    from parametres.models import TypeReponse

    codes = {c.liste for c in cols if c.type == "liste"}
    return {t.code: t for t in TypeReponse.objects.filter(code__in=codes)}


def _nombre(texte):
    from .saisie import NOMBRE_SAISI, VALEUR_MAX, texte_nombre

    t = texte_nombre(texte.strip())
    if not NOMBRE_SAISI.fullmatch(t) or len(t) > 60:
        raise ValueError
    v = Decimal(t)
    if not v.is_finite() or abs(v) >= VALEUR_MAX:
        raise ValueError
    return v


def _texte_nombre(v):
    t = format(v.normalize(), "f")
    return t if "." not in t else t.rstrip("0").rstrip(".")


def lire(texte, type_reponse):
    """Tableau Markdown enregistré (normalisé) à partir de ce qui est saisi ou importé ; ValidationError qui nomme la
    ligne et la colonne en cause. Vide : ""."""
    cols = colonnes(type_reponse)
    if not cols:
        raise ValidationError(libelle("messages.tableau.sans_colonnes"))
    listes = _types_listes(cols)
    sortie, erreurs = [], []
    for n, cells in enumerate(lignes_brutes(texte), start=1):
        if not any(cells):
            continue
        if len(cells) > len(cols) and any(cells[len(cols):]):
            erreurs.append(libelle("messages.tableau.trop_de_colonnes", n=n, attendu=len(cols)))
            continue
        cells = (cells + [""] * len(cols))[:len(cols)]
        ligne = []
        for col, brut in zip(cols, cells):
            brut = " ".join(brut.split())
            if not brut:
                ligne.append("")
                continue
            if col.type == "nombre":
                try:
                    ligne.append(_texte_nombre(_nombre(brut)))
                except (ValueError, ArithmeticError):
                    erreurs.append(libelle("messages.tableau.nombre", n=n, colonne=col.libelle()))
                    ligne.append(brut)
            elif col.type == "liste":
                t = listes.get(col.liste)
                cle = L.cle_valeur(t, list(t.valeurs or []), brut) if t is not None else None
                if cle is None:
                    erreurs.append(libelle("messages.tableau.valeur_liste", n=n, colonne=col.libelle(), valeur=brut[:60]))
                    ligne.append(brut)
                else:
                    ligne.append(cle)
            else:
                ligne.append(brut[:500])
        sortie.append(ligne)
    if len(sortie) > MAX_LIGNES:
        erreurs.append(libelle("messages.tableau.trop_de_lignes", max=MAX_LIGNES))
    if erreurs:
        raise ValidationError(erreurs[:10])
    return ecrire(sortie, cols) if sortie else ""


def _echapper(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def ecrire(lignes, cols, langue=None):
    """Tableau Markdown de lignes (listes de textes, dans l'ordre des colonnes) ; en-tête dans la langue de référence."""
    lg = langue or L.reference()
    entete = "| " + " | ".join(_echapper(c.libelle(lg)) for c in cols) + " |"
    separation = "|" + "|".join(" ---: " if c.type == "nombre" else " --- " for c in cols) + "|"
    corps = ["| " + " | ".join(_echapper(v) for v in l) + " |" for l in lignes]
    return "\n".join([entete, separation] + corps)


def lignes(texte, type_reponse):
    """Lignes d'une réponse enregistrée : [{code de colonne: Decimal | texte | valeur de référence de la liste}]."""
    cols = colonnes(type_reponse)
    sortie = []
    for cells in lignes_brutes(texte):
        cells = (cells + [""] * len(cols))[:len(cols)]
        ligne = {}
        for col, v in zip(cols, cells):
            if col.type == "nombre" and v:
                try:
                    ligne[col.code] = _nombre(v)
                except (ValueError, ArithmeticError):
                    ligne[col.code] = None
            else:
                ligne[col.code] = v or None
        if any(x is not None for x in ligne.values()):
            sortie.append(ligne)
    return sortie


def fusionner(listes_de_lignes, type_reponse):
    """Lignes de plusieurs réponses regroupées : les lignes dont les colonnes texte et liste sont égales n'en font qu'une,
    leurs nombres additionnés (ordre de première apparition)."""
    cols = colonnes(type_reponse)
    cles = [c.code for c in cols if c.type != "nombre"]
    nombres = [c.code for c in cols if c.type == "nombre"]
    regroupees = {}
    for ls in listes_de_lignes:
        for l in ls:
            cle = tuple((l.get(k) or "").strip().lower() if isinstance(l.get(k), str) else l.get(k) for k in cles)
            if cle not in regroupees:
                regroupees[cle] = dict(l)
                continue
            r = regroupees[cle]
            for k in nombres:
                if l.get(k) is not None:
                    r[k] = (r.get(k) or Decimal(0)) + l[k]
    return list(regroupees.values())


def resume(texte):
    """Nombre de lignes d'un tableau enregistré (affichage court dans les listes)."""
    return len([l for l in lignes_brutes(texte) if any(l)])
