"""Export et import de la configuration : niveaux, unités, types de saisie et de réponse, catégories de description,
champs personnalisés, référentiel KPI, organisations, libellés d'import, règles de cohérence.

Un seul classeur Excel, réimportable : il sert de sauvegarde, de suivi hors de l'outil, et de point de départ pour
une autre entreprise (modèle vierge). L'import passe par un aperçu champ par champ ; rien n'est supprimé (un KPI
absent du fichier peut seulement être désactivé, si on le demande). Tout ou rien : une seule ligne refusée et rien
n'est enregistré.
L'ancien format technique (en-têtes id_…, nom_fr…) est aussi reconnu. Un code de KPI qui ne diffère d'un code
existant que par la casse est un conflit : la ligne est rejetée.
"""
import copy
import datetime
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from parametres import couleurs as CO
from parametres import langues as L
from parametres import niveaux as N
from parametres import rapprochement_unites as RU
from parametres import referentiel as PR
from parametres.libelles import libelle
from parametres.models import (CategorieDescription, ChampPersonnalise, Instance, Langue, NiveauHierarchique, TypeReponse,
                               TypeSaisie, Unite)
from referentiel import formule as F
from referentiel.echange import enregistrer_descriptions, reconstruire_toutes_dependances
from referentiel.models import KPI, Frequence, Organisation, OrgAlias, Referentiel, normaliser_code, valider_code_kpi, verifier_formule

from . import dates_courtes as DC
from . import configuration_referentiels as CR
from . import fichiers as X
from . import reglages as R
from .models import Campagne, Journal, RegleCoherence
from .statistiques_postgresql import statistiques_a_jour
from espaces import contexte as ESP

# (champ, en-tête, largeur, type) ; type : texte, entier, bool, pourcent, date, liste (« a ; b »), une référence
# (niveau, unite, type_saisie, type_reponse : code ou nom), ou la classe de choix
COLONNES_NIVEAU = [("code", "Code", 14, "texte"), ("rang", "Rang", 7, "entier"), ("nom", "Nom", 20, "texte"),
                   ("nom_pluriel", "Nom au pluriel", 20, "texte"), ("couleur", "Couleur", 10, "texte")]
COLONNES_UNITE = [("code", "Code", 14, "texte"), ("symbole", "Symbole", 14, "texte"), ("libelle", "Libellé", 28, "texte"),
                  ("entier", "Nombre entier", 10, "bool"), ("decimales", "Décimales", 9, "entier"), ("famille", "Famille", 16, "texte"),
                  ("ordre", "Ordre", 7, "entier")]
COLONNES_TYPE_SAISIE = [("code", "Code", 14, "texte"), ("libelle", "Libellé", 24, "texte"), ("abrege", "Étiquette courte", 14, "texte"),
                        ("couleur", "Couleur", 10, "texte"), ("comportement", "Comportement", 18, TypeSaisie.Comportement),
                        ("ordre", "Ordre", 7, "entier")]
COLONNES_TYPE_REPONSE = [("code", "Code", 14, "texte"), ("libelle", "Libellé", 24, "texte"), ("format", "Format", 16, TypeReponse.Format),
                         ("valeurs", "Valeurs possibles", 40, "liste"), ("colonnes", "Colonnes (tableau)", 40, "json"),
                         ("ordre", "Ordre", 7, "entier")]
COLONNES_CATEGORIE = [("code", "Code", 16, "texte"), ("libelle", "Libellé", 28, "texte"), ("ordre", "Ordre", 7, "entier"),
                      ("affichee", "Affichée au contributeur", 12, "bool"), ("obligatoire", "Obligatoire", 10, "bool")]
COLONNES_CHAMP = [("code", "Code", 16, "texte"), ("libelle", "Libellé", 28, "texte"), ("type", "Type", 14, ChampPersonnalise.Type),
                  ("valeurs", "Valeurs possibles", 40, "liste"), ("ordre", "Ordre", 7, "entier")]
# onglets des listes réglables : (onglet, autres noms, modèle, colonnes, référence alimentée)
REGLABLES = [
    ("Unités", ("Unites", "Units"), Unite, COLONNES_UNITE, "unite"),
    ("Types de saisie", ("Input types",), TypeSaisie, COLONNES_TYPE_SAISIE, "type_saisie"),
    ("Types de réponse", ("Answer types",), TypeReponse, COLONNES_TYPE_REPONSE, "type_reponse"),
    ("Catégories", ("Catégories de description",), CategorieDescription, COLONNES_CATEGORIE, "categorie"),
    ("Champs", ("Champs personnalisés",), ChampPersonnalise, COLONNES_CHAMP, "champ"),
]
COLONNES_KPI = [
    ("code", "ID KPI", 11, "texte"), ("ordre", "Ordre", 7, "entier"), ("libelle", "Nom", 55, "texte"),
    ("type_saisie", "Type de saisie", 16, "type_saisie"),
    ("type_reponse", "Type de réponse", 14, "type_reponse"), ("unite", "Unité", 12, "unite"),
    ("decimales", "Décimales", 9, "entier"), ("granularite", "Granularité", 11, "niveau"),
    ("methode_agregation", "Agrégation", 11, KPI.Agregation), ("agregation_temps", "Agrégation dans le temps", 14, KPI.AgregationTemps),
    ("formule", "Formule", 40, "texte"),
    ("equipe_responsable", "Équipe responsable", 18, "texte"),
    ("preuve_obligatoire", "Preuve obligatoire", 10, "bool"), ("confidentialite", "Confidentialité", 14, KPI.Confidentialite),
    ("actif", "Actif", 7, "bool"), ("saisie_au_dessus", "Saisie aux niveaux supérieurs", 12, "bool"),
    ("na_compte_zero", "Source N/A comptée comme 0", 12, "bool"),
]
# en-têtes de l'ancien format technique (anciens fichiers de référentiel) encore acceptés
ALIAS_KPI = {"code": ["ID", "Code KPI"], "desc:description": ["description"], "desc:a_inclure": ["a_inclure"],
             "desc:a_exclure": ["a_exclure"], "desc:source": ["source_donnees", "Source des données"]}
# textes traduisibles de chaque onglet : une colonne par langue (« Libellé (FR) », « Libellé (EN) »…)
TRADUITS = {"Niveaux": ("nom", "nom_pluriel"), "Unités": ("symbole", "libelle"), "Types de saisie": ("libelle", "abrege"),
            "Types de réponse": ("libelle", "valeurs"), "Catégories": ("libelle",), "Champs": ("libelle", "valeurs"), "KPI": ("libelle",)}
COLONNES_LANGUE = [("code", "Code", 10, "texte"), ("libelle", "Libellé", 18, "texte"), ("ordre", "Ordre", 7, "entier"),
                   ("active", "Active", 8, "bool"), ("defaut", "Par défaut", 10, "bool")]
# onglet Réglages : réglages de l'espace, un par ligne, repérés par leur code (le libellé n'est qu'une aide à la lecture)
COLONNES_REGLAGES = [("code", "Code", 14, "texte"), ("libelle", "Libellé", 40, "texte"), ("valeur", "Valeur", 14, "monnaie")]
REGLAGE_MONNAIE = "monnaie"  # monnaie de référence (code ISO 4217, parametres/monnaies.py)
REFERENCES = {"niveau", "unite", "type_saisie", "type_reponse"}
SANS = ("—", "-", "–", "aucune", "sans")  # unité explicitement retirée


def langues_fichier(codes=None):
    """Langues des colonnes traduites : la référence d'abord, puis les autres dans l'ordre de Paramètres › Langues."""
    ref = L.reference()
    codes = codes if codes is not None else [l.code for l in Langue.objects.all()]
    return [ref] + [c for c in codes if c != ref]


def traduire_colonnes(colonnes, champs, langues):
    """Chaque texte traduisible devient une colonne par langue : « Libellé (FR) » (référence : le champ lui-même),
    « Libellé (EN) » (``tr:libelle:en``)… ; les en-têtes sans langue restent acceptés pour la référence."""
    sortie = []
    for champ, entete, largeur, genre in colonnes:
        if champ not in champs:
            sortie.append((champ, entete, largeur, genre))
            continue
        sortie.append((champ, f"{entete} {L.suffixe(langues[0])}", largeur, genre))
        sortie += [(f"tr:{champ}:{l}", f"{entete} {L.suffixe(l)}", largeur, genre) for l in langues[1:]]
    return sortie


def alias_reference(colonnes, champs, langues):
    """{champ de référence: [en-tête sans langue]} : fichiers d'avant les langues."""
    return {c: [e.rsplit(" (", 1)[0]] for c, e, _, _ in colonnes if c in champs}


# Onglet KPI : l'essentiel d'abord (mêmes colonnes que le fichier référentiel), le reste regroupé et replié à droite
ESSENTIELLES_KPI = ["code", "libelle", "type_saisie", "type_reponse", "unite", "granularite", "methode_agregation", "formule"]


def colonnes_kpi(categories, champs, langues=None):
    """Colonnes de l'onglet KPI : les champs du KPI, nom et descriptions dans chaque langue, une par champ personnalisé ;
    les colonnes essentielles (et la première description dans la langue de référence) d'abord."""
    langues = langues or langues_fichier()
    genres = {"case": "bool", "date": "date", "liste": "liste_champ", "texte": "texte"}
    descriptions = []
    for c in categories:
        descriptions.append((f"desc:{c.code}", f"{c.libelle} {L.suffixe(langues[0])}", 40, "texte"))
        descriptions += [(f"desc:{c.code}:{l}", f"{c.libelle} {L.suffixe(l)}", 40, "texte") for l in langues[1:]]
    toutes = (traduire_colonnes(COLONNES_KPI, TRADUITS["KPI"], langues) + descriptions
              + [(f"champ:{c.code}", c.libelle, 16, genres.get(c.type, "texte")) for c in champs])
    premieres = ESSENTIELLES_KPI + ([f"desc:{categories[0].code}"] if categories else [])
    essentielles = sorted((c for c in toutes if c[0] in premieres), key=lambda c: premieres.index(c[0]))
    return essentielles + [c for c in toutes if c[0] not in premieres]


def nb_essentielles(colonnes):
    """Nombre de colonnes essentielles en tête de l'onglet KPI (les suivantes sont repliées)."""
    n = 0
    for c in colonnes:
        if c[0] not in ESSENTIELLES_KPI and not (c[0].startswith("desc:") and c[0].count(":") == 1):
            break
        n += 1
    return n


def alias_kpi(categories, langues):
    """En-têtes acceptés en plus : ancien format technique, noms et descriptions sans langue (référence), nom_fr / nom_en."""
    alias = {k: list(v) for k, v in ALIAS_KPI.items()}
    alias.setdefault("libelle", []).extend(["Nom", f"nom_{langues[0]}", "nom_fr" if langues[0] == "fr" else ""])
    for l in langues[1:]:
        alias[f"tr:libelle:{l}"] = [f"nom_{l}"]
    for c in categories:
        alias.setdefault(f"desc:{c.code}", []).append(c.libelle)
    return alias
COLONNES_ORG = [("nom", "Nom", 28, "texte"), ("code", "Code", 16, "texte"), ("nom_court", "Nom court", 16, "texte"), ("niveau", "Niveau", 10, "niveau"),
                ("parent", "Rattachée à", 28, "texte"), ("type_site", "Type de site", 12, Organisation.TypeSite),
                ("rang", "Ordre", 7, "entier"), ("actif", "Active", 7, "bool"),
                # date d'ouverture : vide = ouverte depuis toujours ; une cellule vide garde
                # la date enregistrée (comme toute cellule vide de ce fichier) ; « — » la retire
                ("date_ouverture", "Ouverte depuis", 14, "jour")]
COLONNES_ALIAS = [("organisation", "Organisation", 28, "texte"), ("source", "Source", 14, "texte"),
                  ("libelle", "Libellé", 36, "texte"), ("id_externe", "ID externe", 14, "texte")]
COLONNES_REGLE = [("nom", "Nom", 32, "texte"), ("description", "Description", 50, "texte"), ("gauche", "Partie gauche", 30, "texte"),
                  ("operateur", "Opérateur", 10, RegleCoherence.Operateur), ("droite", "Partie droite", 30, "texte"),
                  ("tolerance", "Tolérance (%)", 12, "pourcent"), ("niveau", "Niveau", 10, "niveau"),
                  ("bloquante", "Bloquante", 10, "bool"), ("actif", "Active", 7, "bool")]
SYNONYMES = {"yes": "Oui", "no": "Non", "nombre entier": "nombre", "entier": "nombre", "montant": "nombre", "": None, "<=": "<=", "≤": "<=", ">=": ">=", "≥": ">="}


# ---------------------------------------------------------------- valeurs de cellule
def nom_reference(objet):
    """Nom affiché d'une référence : niveau (nom), unité (symbole), type (libellé)."""
    if objet is None:
        return ""
    return getattr(objet, "nom", None) or getattr(objet, "symbole", None) or getattr(objet, "libelle", None) or str(objet)


def en_cellule(v, genre):
    if genre in REFERENCES:
        return nom_reference(v) if not isinstance(v, str) else v
    if genre == "liste":
        return " ; ".join(v or [])
    if genre == "json":  # colonnes d'un tableau : leur description JSON, telle quelle
        return json.dumps(v, ensure_ascii=False) if v else ""
    if genre == "bool":
        return "Oui" if v else "Non"
    if genre == "pourcent":
        return X.nombre(Decimal(v) * 100) if v else 0
    if genre == "jour":
        return v.strftime("%d/%m/%Y") if v else ""
    if isinstance(genre, type):
        try:
            return genre(v).label
        except ValueError:
            return v
    return v


MESSAGES_REFERENCE = {  # clés des messages d'une cellule de référence inconnue
    "niveau": "admin.config.erreur.niveau_inconnu", "unite": "admin.config.erreur.unite_inconnue",
    "type_saisie": "admin.config.erreur.type_saisie_inconnu", "type_reponse": "admin.config.erreur.type_reponse_inconnu",
}


def depuis_cellule(v, genre, cles=None):
    """Valeur de modèle depuis une cellule ; ValueError avec un message lisible si elle est invalide.

    ``cles`` : {clé normalisée (code, nom…): code} pour une colonne de référence (niveau, unité, type)."""
    t = X.texte(v)
    if genre in REFERENCES:
        if not t:
            return None
        if genre == "unite" and t.lower() in SANS:
            return ""
        cles = cles or {}
        if isinstance(cles, ClesUnites):  # symbole exact, code ou traduction ; jamais une forme sans symboles
            code = cles.get("=" + t) or cles.rapprocher(t)[0]
        else:
            code = cles.get("=" + t) or cles.get(X.normaliser(t))  # le code ou le symbole exact d'abord (« m³ », « % »)
        if code is None:
            raise ValueError(libelle(MESSAGES_REFERENCE[genre], valeur=t))
        return code
    if genre == "liste":
        return [x.strip() for x in t.replace("\n", ";").split(";") if x.strip()] if t else None
    if genre == "json":
        if not t:
            return None
        try:
            return json.loads(t)
        except (ValueError, RecursionError):  # RecursionError : imbrication démesurée ([[[[…]]]])
            raise ValueError(libelle("admin.config.erreur.json", valeur=t[:60]))
    if genre == "jour":  # date d'un champ du modèle (objet date) ; « — » : date retirée
        if not t:
            return None
        if t in ("—", "-"):
            return ""
        if isinstance(v, datetime.date):
            return v.date() if isinstance(v, datetime.datetime) else v
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(t, fmt).date()
            except ValueError:
                continue
        raise ValueError(libelle("admin.config.erreur.date", valeur=t))
    if genre == "date":
        if not t:
            return None
        if hasattr(v, "date"):
            return v.date().isoformat()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M"):
            try:
                return datetime.datetime.strptime(t, fmt).date().isoformat()
            except ValueError:
                continue
        raise ValueError(libelle("admin.config.erreur.date", valeur=t))
    if genre == "bool":
        return X.oui(t) if t else None
    if genre == "entier":
        if not t:
            return None
        try:
            return int(X.lire_decimal(v))
        except (ValueError, TypeError):
            raise ValueError(libelle("admin.config.erreur.entier", valeur=t))
    if genre == "pourcent":
        try:
            d = X.lire_decimal(v)
        except ValueError:
            raise ValueError(libelle("admin.config.erreur.nombre", valeur=t))
        return None if d is None else d / 100
    if isinstance(genre, type):
        if not t:
            return None
        t = SYNONYMES.get(t.lower(), t)
        n = X.normaliser(t)
        for code, nom_choix in genre.choices:
            if n in (X.normaliser(code), X.normaliser(nom_choix)):
                return code
        raise ValueError(libelle("admin.config.erreur.valeur_possible", valeur=t, valeurs=", ".join(l for _, l in genre.choices)))
    return t


def lire_onglet(lignes, colonnes, cle, autres=None):
    """[(numéro de ligne, {champ: cellule brute})] : en-têtes reconnus par leur libellé ou leur nom technique.

    ``autres`` : {champ: [autres en-têtes acceptés]} (ancien format)."""
    def technique(champ):  # « libelle », « description » (desc:description) ; rien pour une colonne de langue
        morceaux = champ.split(":")
        return [morceaux[-1]] if len(morceaux) <= 2 and morceaux[0] != "tr" else []
    alias = {champ: X.entetes_acceptes(entete) + technique(champ) + [x for a in (autres or {}).get(champ, []) if a
                                                                    for x in X.entetes_acceptes(a)]
             for champ, entete, _, _ in colonnes}
    i, cols = X.trouver_colonnes(lignes, alias, (cle,))
    if i is None:
        return None
    sortie = []
    for n, row in enumerate(lignes[i + 1:], start=i + 2):
        d = {champ: row[j] if j < len(row) else None for champ, j in cols.items()}
        if X.texte(d.get(cle)):
            sortie.append((n, d))
    return sortie


# ---------------------------------------------------------------- analyse
@dataclass
class Changement:
    numero: int
    cle: str
    action: str = "rejet"  # creer, modifier, inchange, rejet, desactiver
    motif: str = ""
    avertissement: str = ""  # ligne acceptée, mais à relire (valeurs qui ne compteront plus : date d'ouverture)
    champs: list = field(default_factory=list)  # (libellé, avant, après)
    objet: object = None
    descriptions: dict | None = None  # KPI : {langue: {code de catégorie: texte}} après import
    place_ancienne: list | None = None  # KPI d'un ancien classeur : chemin de thèmes dans le référentiel par défaut


@dataclass
class AnalyseConfig:
    erreur: str = ""
    onglets: dict = field(default_factory=dict)  # nom → [Changement]
    desactiver_absents: bool = False
    niveaux: dict = field(default_factory=dict)  # code → niveau après import (existant ou nouveau)
    refs: dict = field(default_factory=dict)  # genre (unite, type_saisie, type_reponse, categorie, champ) → {code: objet}
    cles: dict = field(default_factory=dict)  # genre → {code, nom ou symbole: code}
    notes_unites: dict = field(default_factory=dict)  # ligne de l'onglet KPI → unité reconnue malgré la casse (avertissement)
    non_numeriques: set = field(default_factory=set)  # KPI à réponse oui / non ou liste (hors des formules)
    granularites: dict = field(default_factory=dict)  # ID KPI → code du niveau de saisie (pour les règles sans niveau)
    rangs: dict = field(default_factory=dict)  # code → rang après import
    cles_niveau: dict = field(default_factory=dict)  # code, nom ou pluriel normalisé → code
    langues: list = field(default_factory=list)  # codes des langues après import (référence d'abord)
    referentiels: dict = field(default_factory=dict)  # code → référentiel après import
    themes: dict = field(default_factory=dict)  # (référentiel, code) → thème après import
    parents_themes: dict = field(default_factory=dict)  # (référentiel, code) → (référentiel, code du parent)
    elements_fichier: set = field(default_factory=set)  # (référentiel, KPI) décrits dans l'onglet Éléments
    defaut: str = ""  # langue par défaut après import
    monnaie: str = ""  # monnaie de référence après import (onglet Réglages)

    def compte(self, onglet, action):
        return sum(1 for c in self.onglets.get(onglet, []) if c.action == action)

    @property
    def resume(self):
        return [(nom, [(a, libelle(cle), self.compte(nom, a)) for a, cle in ACTIONS_CONFIG]) for nom in self.onglets]

    @property
    def nb_rejets(self):
        return sum(1 for cs in self.onglets.values() for c in cs if c.action == "rejet")

    @property
    def nb_ecritures(self):
        return sum(1 for cs in self.onglets.values() for c in cs if c.action in ("creer", "modifier", "desactiver"))

    @property
    def change_quelque_chose(self):
        """Vrai si l'import changerait quelque chose (création, modification, désactivation, niveau supprimé, langue
        par défaut) : un fichier réimporté tel quel n'écrit rien, pas même au journal."""
        return bool(self.nb_ecritures or any(c.action == "supprimer" for cs in self.onglets.values() for c in cs)
                    or (self.defaut and self.defaut != Instance.courante().langue))

    @property
    def importable(self):
        """Tout ou rien : une seule ligne refusée, et rien n'est enregistré."""
        return not self.erreur and not self.nb_rejets and self.change_quelque_chose

    def apercu(self, onglet, limite=300):
        ordre = {"rejet": 0, "modifier": 1, "desactiver": 2, "creer": 3}
        return sorted((c for c in self.onglets.get(onglet, []) if c.action in ordre), key=lambda c: (ordre[c.action], c.numero))[:limite]


ACTIONS_CONFIG = [("creer", "admin.config.action.creer"), ("modifier", "admin.config.action.modifier"),
                  ("desactiver", "admin.config.action.desactiver"), ("supprimer", "admin.config.action.supprimer"),
                  ("inchange", "admin.config.action.inchange"), ("rejet", "admin.config.action.rejet")]  # clés des libellés


def _cles_reference(a, genre):
    return a.cles_niveau if genre == "niveau" else a.cles.get(genre, {})


def _objets_reference(a, genre):
    return a.niveaux if genre == "niveau" else a.refs.get(genre, {})


def appliquer_champs(obj, d, colonnes, ch, existe, ignorer=(), a=None):
    """Copie les cellules sur l'objet ; note les champs modifiés. Renvoie False si une cellule est invalide.

    Une colonne de référence (niveau, unité, type) pointe vers l'objet, existant ou créé par ce fichier."""
    for champ, entete, _, genre in colonnes:
        if champ not in d or champ in ignorer or ":" in champ:
            continue
        try:
            v = depuis_cellule(d[champ], genre, _cles_reference(a, genre) if a else None)
        except ValueError as e:
            ch.motif = f"{entete} : {e}."
            return False
        if v is None:
            if genre in ("texte",):
                v = ""
            else:
                continue  # cellule vide : la valeur actuelle est gardée
        if genre in REFERENCES:
            objets = _objets_reference(a, genre)
            avant = getattr(obj, f"{champ}_id")
            v = v or None  # « — » : unité retirée
            if avant != v:
                if existe:
                    ch.champs.append((entete, nom_reference(objets.get(avant)) if avant else "—", nom_reference(objets.get(v)) or "—"))
                if v in objets:
                    setattr(obj, champ, objets[v])  # objet en mémoire : il peut n'être créé que par ce fichier
                else:
                    setattr(obj, f"{champ}_id", v)
            continue
        if genre == "jour" and v == "":
            v = None  # « — » : date retirée
        avant = getattr(obj, champ)
        if avant != v:
            if existe:
                ch.champs.append((entete, en_cellule(avant, genre), en_cellule(v, genre)))
            setattr(obj, champ, v)
    return True


def _liste_langue(v):
    """Valeurs traduites d'une liste, par position : « Certified ; ; Not engaged » garde la case vide du milieu."""
    t = X.texte(v)
    return [x.strip() for x in t.replace("\n", ";").split(";")] if t else []


def appliquer_traductions(obj, d, colonnes, ch, existe):
    """Colonnes « tr:champ:langue » : textes de l'objet dans les autres langues (cellule vide = traduction retirée)."""
    for champ, entete, _, _ in colonnes:
        if not champ.startswith("tr:") or champ not in d:
            continue
        _, nom, langue = champ.split(":", 2)
        if nom == "valeurs":
            cles = L.cles_valeurs(obj)
            if not cles:
                continue
            avant, apres = X.sans_fin_vide(L.valeurs_langue(obj, langue)), X.sans_fin_vide(_liste_langue(d[champ])[:len(cles)])
            if avant != apres:
                if existe:
                    ch.champs.append((entete, " ; ".join(avant), " ; ".join(apres)))
                L.definir_valeurs(obj, langue, apres, len(cles))
            continue
        avant, apres = L.texte(obj, nom, langue), X.texte(d[champ])
        if avant != apres:
            if existe:
                ch.champs.append((entete, X.court(avant), X.court(apres)))
            L.definir(obj, nom, langue, apres)


def _cellules_traduites(obj, colonnes):
    """Valeurs des colonnes « tr:… » d'un objet (export)."""
    sortie = {}
    for champ, _, _, _ in colonnes:
        if champ.startswith("tr:"):
            _, nom, langue = champ.split(":", 2)
            sortie[champ] = (" ; ".join(X.sans_fin_vide(L.valeurs_langue(obj, langue))) if nom == "valeurs"
                             else L.texte(obj, nom, langue))
    return sortie


def _cles_niveau(niveaux):
    """{code, nom ou pluriel normalisé: code} ; le code l'emporte sur un nom identique."""
    cles = {}
    for n in niveaux.values():
        for t in (n.nom_pluriel, n.nom, *[v for d in (n.traductions or {}).values() for v in (d or {}).values() if isinstance(v, str)]):
            cles.setdefault(X.normaliser(t), n.code)
    for n in niveaux.values():
        cles[X.normaliser(n.code)] = n.code
    return cles


def _analyser_niveaux(a, lignes):
    """Niveaux après import. Un niveau absent du fichier et vide (sans organisation, KPI ni règle) est supprimé ;
    l'ordre des niveaux déjà utilisés ne change pas ici (il se règle dans Paramètres › Niveaux, qui vérifie l'arbre)."""
    existants = {n.code: n for n in NiveauHierarchique.objects.all()}
    a.niveaux = dict(existants)
    a.rangs = {c: n.rang for c, n in existants.items()}
    a.cles_niveau = _cles_niveau(a.niveaux)
    if lignes is None:
        return
    colonnes = traduire_colonnes(COLONNES_NIVEAU, TRADUITS["Niveaux"], a.langues)
    donnees = lire_onglet(lignes, colonnes, "code", alias_reference(colonnes, TRADUITS["Niveaux"], a.langues))
    if donnees is None:
        return
    utilises = N.utilises()
    changements, vus, ordre = [], {}, []
    for n, d in donnees:
        code = X.texte(d["code"])
        ch = Changement(n, code)
        changements.append(ch)
        if code in vus:
            ch.motif = libelle("admin.config.erreur.code_double", ligne=vus[code])
            continue
        vus[code] = n
        if not N.CODE_VALIDE.match(code):
            ch.motif = libelle("admin.config.erreur.niveau_code")
            continue
        niv = copy.copy(existants[code]) if code in existants else NiveauHierarchique(code=code)  # rien de modifié si rejet
        ch.objet = niv
        if not appliquer_champs(niv, d, colonnes, ch, code in existants, ignorer=("code", "rang")):
            continue
        appliquer_traductions(niv, d, colonnes, ch, code in existants)
        if not niv.nom:
            ch.motif = libelle("admin.config.erreur.nom_manquant")
            continue
        niv.nom_pluriel = niv.nom_pluriel or niv.nom
        couleur = (niv.couleur or "").upper()
        if not CO.valide(couleur):
            if code in existants or couleur:
                ch.motif = libelle("admin.config.erreur.couleur")
                continue
            couleur = CO.COULEURS_NIVEAUX[len(ordre) % len(CO.COULEURS_NIVEAUX)]
        if couleur != (existants[code].couleur.upper() if code in existants else None):
            niv.couleur = couleur
            niv.deriver_couleurs()
        try:
            rang = depuis_cellule(d.get("rang"), "entier")
        except ValueError as e:
            ch.motif = libelle("admin.config.erreur.rang", erreur=e)
            continue
        ordre.append((rang if rang is not None else (niv.rang if code in existants else 99), 0, len(ordre), niv, ch))
        ch.action = "creer" if code not in existants else ("modifier" if ch.champs else "inchange")
    retenus = {niv.code for *_, niv, ch in ordre}
    for code, niv in existants.items():
        if code in retenus:
            continue
        if code in utilises or code in vus:  # utilisé, ou ligne rejetée : gardé tel quel
            ordre.append((niv.rang, 1, len(ordre), niv, None))
        else:
            changements.append(Changement(0, code, action="supprimer", objet=niv, motif=libelle("admin.config.erreur.niveau_vide")))
            del a.niveaux[code]
    ordre.sort(key=lambda x: x[:3])
    if len(ordre) > NiveauHierarchique.MAXIMUM:
        for *_, ch in ordre:
            if ch and ch.action == "creer":
                ch.action, ch.motif = "rejet", libelle("admin.config.erreur.niveaux_max", maximum=NiveauHierarchique.MAXIMUM)
        ordre = [x for x in ordre if not x[4] or x[4].action != "rejet"]
    # les niveaux utilisés gardent leur ordre relatif : sinon des organisations passeraient au-dessus de leur rattachement
    avant = [x[3].code for x in sorted(ordre, key=lambda x: x[3].rang if x[3].code in existants else 0) if x[3].code in utilises]
    apres = [x[3].code for x in ordre if x[3].code in utilises]
    if avant != apres:
        for *_, ch in ordre:
            if ch and ch.objet.code in utilises:
                ch.action, ch.motif = "rejet", libelle("admin.config.erreur.niveaux_ordre")
        return _niveaux_rejetes(a, changements, existants)
    for rang, (*_, niv, ch) in enumerate(ordre, start=1):
        if niv.code in existants and existants[niv.code].rang != rang and ch and ch.action != "rejet":
            ch.champs.append(("Rang", existants[niv.code].rang, rang))
            ch.action = "modifier" if ch.action == "inchange" else ch.action
        a.rangs[niv.code] = rang
        a.niveaux[niv.code] = niv
    for c in [c for c in a.rangs if c not in a.niveaux]:
        del a.rangs[c]
    a.cles_niveau = _cles_niveau(a.niveaux)
    a.onglets["Niveaux"] = changements


def _niveaux_rejetes(a, changements, existants):
    """Onglet Niveaux refusé en bloc : les niveaux actuels restent tels quels."""
    for c in changements:
        if c.action != "rejet":
            c.action, c.motif = "rejet", c.motif or libelle("admin.config.erreur.niveaux_refuses")
    a.niveaux = dict(existants)
    a.rangs = {c: n.rang for c, n in existants.items()}
    a.cles_niveau = _cles_niveau(a.niveaux)
    a.onglets["Niveaux"] = changements


def analyser(fichier, desactiver_absents=False):
    with L.session():
        return _analyser(fichier, desactiver_absents)


def _analyser(fichier, desactiver_absents):
    a = AnalyseConfig(desactiver_absents=desactiver_absents)
    try:
        onglets = X.lire(fichier)
    except X.FichierInvalide as e:
        a.erreur = str(e)
        return a
    par_nom = X.onglets_en_francais({X.normaliser(n): lignes for n, lignes in onglets.items()})

    def onglet(*noms):
        for n in noms:
            if X.normaliser(n) in par_nom:
                return par_nom[X.normaliser(n)]
        return None

    _analyser_langues(a, onglet("Langues", "Languages"))
    _analyser_reglages_espace(a, onglet("Réglages", "Settings"))
    _analyser_niveaux(a, onglet("Niveaux", "Levels"))
    for nom, autres, modele, colonnes, genre in REGLABLES:
        _analyser_reglable(a, nom, onglet(nom, *autres), modele, colonnes, genre)
    CR.analyser_referentiels(a, onglet("Référentiels", "Referentiels", "Frameworks"))
    CR.analyser_themes(a, onglet("Thèmes", "Themes"))
    orgs = _analyser_organisations(a, onglet("Organisations", "Organisation structure"))
    _analyser_alias(a, onglet("Alias", "Libellés d'import"), orgs)
    kpi_lignes = onglet("KPI", "Référentiel", "CSV")
    if kpi_lignes is None and len(onglets) == 1:
        kpi_lignes = next(iter(onglets.values()))
    kpis = _analyser_kpi(a, kpi_lignes)
    CR.analyser_elements(a, onglet("Éléments", "Elements"), kpis)
    _analyser_regles(a, onglet("Règles de cohérence", "Règles"), kpis)
    if not a.onglets:
        a.erreur = libelle("admin.config.erreur.aucun_onglet")
    return a


def _analyser_langues(a, lignes):
    """Langues après import : création, libellé, ordre, activité, langue par défaut. La langue de référence reste active."""
    existantes = {l.code: l for l in Langue.objects.all()}
    ref, i = L.reference(), Instance.courante()
    a.defaut = i.langue
    a.langues = langues_fichier(list(existantes))
    if lignes is None:
        return
    donnees = lire_onglet(lignes, COLONNES_LANGUE, "code")
    if donnees is None:
        return
    changements, vus, defauts = [], {}, []
    for n, d in donnees:
        code = X.texte(d["code"])
        ch = Changement(n, code)
        changements.append(ch)
        if code in vus:
            ch.motif = libelle("admin.config.erreur.code_double", ligne=vus[code])
            continue
        vus[code] = n
        try:
            from parametres.models import valider_code_langue

            valider_code_langue(code)
        except ValidationError as e:
            ch.motif = " ".join(e.messages)
            continue
        lg = copy.copy(existantes[code]) if code in existantes else Langue(code=code, ordre=len(existantes) + len(vus))
        if not appliquer_champs(lg, d, COLONNES_LANGUE, ch, code in existantes, ignorer=("code", "defaut")):
            continue
        lg.libelle = lg.libelle or code
        if code == ref and not lg.active:
            ch.motif = libelle("admin.config.erreur.langue_reference")
            continue
        defaut = depuis_cellule(d.get("defaut"), "bool") if "defaut" in d else None
        if defaut:
            if not lg.active:
                ch.motif = libelle("admin.config.erreur.langue_defaut_active")
                continue
            defauts.append((ch, code))
        ch.objet, ch.action = lg, "creer" if code not in existantes else ("modifier" if ch.champs else "inchange")
    if len(defauts) > 1:
        for ch, _ in defauts:
            ch.action, ch.motif = "rejet", libelle("admin.config.erreur.une_langue_defaut")
    elif defauts and defauts[0][1] != a.defaut:
        ch, code = defauts[0]
        ch.champs.append(("Par défaut", L.libelle(a.defaut), ch.objet.libelle))
        ch.action = "modifier" if ch.action == "inchange" else ch.action
        a.defaut = code
    a.langues = langues_fichier(list(existantes) + [c.cle for c in changements if c.action == "creer"])
    a.onglets["Langues"] = changements


def _analyser_reglages_espace(a, lignes):
    """Onglet Réglages : la monnaie de référence (code ISO 4217 ou symbole d'une monnaie de la liste). Une cellule vide
    garde le réglage ; une monnaie hors de la liste ou un code de réglage inconnu refusent la ligne (tout ou rien)."""
    from parametres import monnaies as MO

    actuelle = MO.reference()
    a.monnaie = actuelle
    if lignes is None:
        return
    donnees = lire_onglet(lignes, COLONNES_REGLAGES, "code")
    if donnees is None:
        return
    changements, vus = [], {}
    for n, d in donnees:
        code = X.texte(d["code"])
        ch = Changement(n, code)
        changements.append(ch)
        if code.lower() in vus:
            ch.motif = libelle("admin.config.erreur.code_double", ligne=vus[code.lower()])
            continue
        vus[code.lower()] = n
        if code.lower() != REGLAGE_MONNAIE:
            ch.motif = libelle("admin.monnaies.config_reglage_inconnu", code=code)
            continue
        brut = X.texte(d.get("valeur"))
        if not brut:
            ch.action = "inchange"
            continue
        voulue = MO.depuis_texte(brut)
        if voulue is None:
            ch.motif = libelle("admin.monnaies.config_inconnue", valeur=brut[:40], liste=", ".join(MO.CODES))
            continue
        if voulue != actuelle:
            ch.champs.append(("Monnaie de référence", actuelle, voulue))
            a.monnaie = voulue
        ch.action = "modifier" if ch.champs else "inchange"
    a.onglets["Réglages"] = changements


def _analyser_organisations(a, lignes):
    """Organisations après import : {nom: Organisation} (existantes et nouvelles), pour les alias et les parents."""
    existantes = {o.nom: o for o in Organisation.objects.all()}
    connues = dict(existantes)
    if lignes is None:
        return connues
    donnees = lire_onglet(lignes, COLONNES_ORG, "nom")
    if donnees is None:
        return connues
    changements, parents = [], {}
    codes = {o.code: o.nom for o in existantes.values()}
    for n, d in donnees:
        nom = X.texte(d["nom"])
        o = existantes.get(nom) or Organisation(nom=nom, actif=True)
        ch = Changement(n, nom, objet=o)
        changements.append(ch)
        if not appliquer_champs(o, d, COLONNES_ORG, ch, nom in existantes, ignorer=("nom", "parent", "code"), a=a):
            continue
        code = normaliser_code(d.get("code"))
        if code and code != o.code:  # code vide : gardé (ou tiré du nom à la création)
            autre = codes.get(code)
            if autre is not None and autre != nom:
                ch.motif = libelle("admin.config.erreur.org_code_pris", code=code, autre=autre)
                continue
            if o.pk:
                ch.champs.append(("Code", o.code, code))
            codes.pop(o.code, None)
            o.code = code
        if o.code:
            codes[o.code] = nom
        if not o.niveau_id:
            ch.motif = libelle("admin.config.erreur.org_niveau", niveaux=", ".join(n.nom for n in sorted(a.niveaux.values(), key=lambda n: a.rangs[n.code])))
            continue
        parents[nom] = X.texte(d.get("parent")) if "parent" in d else (o.parent.nom if o.parent_id else "")
        connues[nom] = o
    for ch in changements:
        o = ch.objet
        if ch.motif:
            continue
        parent_nom = parents[ch.cle]
        parent = connues.get(parent_nom) if parent_nom else None
        if parent_nom and parent is None:
            ch.motif = libelle("admin.config.erreur.org_parent_inconnu", nom=parent_nom)
            continue
        rang = a.rangs[o.niveau_id]
        if rang == 1 and parent:
            ch.motif = libelle("admin.config.erreur.org_sommet", niveau=a.niveaux[o.niveau_id].nom)
            continue
        if rang > 1 and (parent is None or a.rangs.get(parent.niveau_id, 99) >= rang):
            ch.motif = libelle("admin.config.erreur.org_niveau_superieur", niveau=a.niveaux[o.niveau_id].nom)
            continue
        avant = existantes[ch.cle].parent.nom if ch.cle in existantes and existantes[ch.cle].parent_id else ""
        if o.pk and avant != parent_nom:
            ch.champs.append(("Rattachée à", avant, parent_nom))
        o._parent_nom = parent_nom
        ch.action = "creer" if not o.pk else ("modifier" if ch.champs else "inchange")
    # une organisation désactivée ne garde pas d'organisations collectées rattachées (elles ne compteraient plus)
    retenues = {c.cle: c.objet for c in changements if c.action in ("creer", "modifier", "inchange")}
    finales = {nom: o for nom, o in existantes.items()} | retenues
    parent_de = {nom: (getattr(o, "_parent_nom", None) if nom in retenues else (o.parent.nom if o.parent_id else ""))
                 for nom, o in finales.items()}
    for ch in changements:
        if ch.action in ("creer", "modifier") and not ch.objet.actif:
            actives = sorted(nom for nom, o in finales.items() if o.actif and parent_de.get(nom) == ch.cle)
            if actives:
                ch.action = "rejet"
                ch.motif = libelle("admin.config.erreur.org_enfants_actifs",
                                   noms=", ".join(actives[:3]) + (" …" if len(actives) > 3 else ""))
    # date d'ouverture après la date de fermeture : refusée, comme dans la fiche 
    for ch in changements:
        o = ch.objet
        # sans date de fermeture, une organisation désactivée est fermée depuis aujourd'hui au plus tard (comme la fiche)
        if (ch.action in ("creer", "modifier") and o.date_ouverture and not o.actif
                and o.date_ouverture > (o.date_desactivation or datetime.date.today())):
            ch.action = "rejet"
            ch.motif = libelle("admin.organisation.erreur.ouverture_apres_fermeture")
    # ni l'inverse : une organisation collectée rattachée à une organisation qui ne l'est plus (ou ne le sera plus)
    for ch in changements:
        if ch.action in ("creer", "modifier") and ch.objet.actif:
            parent = finales.get(parent_de.get(ch.cle) or "")
            if parent is not None and not parent.actif:
                ch.action = "rejet"
                ch.motif = libelle("admin.config.erreur.org_parent_ferme", parent=parent.nom)
    _avertir_ouverture(changements, finales, parent_de)
    a.onglets["Organisations"] = changements
    return connues


def _avertir_ouverture(changements, finales, parent_de):
    """Date d'ouverture posée ou changée, ou organisation rattachée ailleurs : une organisation
    n'est pas ouverte avant son parent (``calcul.ouverte``) ; les valeurs de l'organisation et de celles en dessous sur
    des périodes qui finissent avant la date qui compte pour chacune ne compteraient plus dans aucun total. Comme la
    fiche, l'aperçu le dit (avertissement sur la ligne) ; l'import reste possible (pas de case de confirmation ici :
    l'administrateur relit l'aperçu avant « Importer »)."""
    from django.db.models import Q

    from .models import Reponse

    touchees = [ch for ch in changements if ch.action == "modifier" and ch.objet.pk
                and any(lib in ("Ouverte depuis", "Rattachée à") for lib, *_ in ch.champs)]
    if not touchees:
        return
    lues = {nom: (parent or "", date) for nom, parent, date in Organisation.objects.values_list("nom", "parent__nom", "date_ouverture")}
    ids = dict(Organisation.objects.values_list("nom", "id"))

    def effective(nom, parents, dates):
        date, x, vus = None, nom, set()
        while x and x not in vus:
            vus.add(x)
            d = dates.get(x)
            if d and (date is None or d > date):
                date = d
            x = parents.get(x)
        return date

    parents_avant = {n: p for n, (p, _) in lues.items()}
    dates_avant = {n: d for n, (_, d) in lues.items()}
    dates_apres = {n: o.date_ouverture for n, o in finales.items()}
    enfants = defaultdict(list)
    for n, p in parent_de.items():
        if p:
            enfants[p].append(n)
    for ch in touchees:
        branche, pile = [], [ch.cle]
        while pile:
            x = pile.pop()
            if x not in branche:
                branche.append(x)
                pile.extend(enfants.get(x, ()))
        filtre = Q()
        for n in branche:
            apres, avant = effective(n, parent_de, dates_apres), effective(n, parents_avant, dates_avant)
            if n in ids and apres is not None and (avant is None or apres > avant):
                filtre |= Q(organisation_id=ids[n], periode__fin__lt=apres)
        if not filtre:
            continue
        valeurs = (Reponse.objects.filter(filtre).filter(origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT,
                                                                     Reponse.Origine.FORCEE])
                   .filter(Q(valeur__isnull=False) | Q(non_applicable=True) | ~Q(texte="")))
        n = valeurs.count()
        if n:
            premiere = valeurs.order_by("periode__debut").select_related("periode").first().periode
            ch.avertissement = libelle("admin.config.avertissement.valeurs_avant_ouverture", n=n, periode=str(premiere))


def _analyser_alias(a, lignes, orgs):
    if lignes is None:
        return
    donnees = lire_onglet(lignes, COLONNES_ALIAS, "libelle")
    if donnees is None:
        return
    existants = {(x.source, x.libelle): x for x in OrgAlias.objects.select_related("organisation")}
    changements, vus = [], set()
    for n, d in donnees:
        source, texte_alias = X.texte(d.get("source")) or "Import", X.texte(d["libelle"])  # la source est un contenu
        ch = Changement(n, f"{texte_alias} ({source})")
        changements.append(ch)
        if (source, texte_alias) in vus:
            ch.motif = libelle("admin.config.erreur.doublon")
            continue
        vus.add((source, texte_alias))
        org = orgs.get(X.texte(d.get("organisation")))
        if org is None:
            ch.motif = libelle("admin.config.erreur.org_inconnue", nom=X.texte(d.get("organisation")))
            continue
        x = existants.get((source, texte_alias))
        id_externe = X.texte(d.get("id_externe"))
        if x is None:
            ch.action, ch.objet = "creer", (org, source, texte_alias, id_externe)
        else:
            if x.organisation.nom != org.nom:
                ch.champs.append(("Organisation", x.organisation.nom, org.nom))
            if "id_externe" in d and x.id_externe != id_externe:
                ch.champs.append(("ID externe", x.id_externe, id_externe))
            ch.action = "modifier" if ch.champs else "inchange"
            ch.objet = (org, source, texte_alias, id_externe if "id_externe" in d else x.id_externe)
    a.onglets["Alias"] = changements


SECTIONS = {"unite": "unites", "type_saisie": "types-saisie", "type_reponse": "types-reponse", "categorie": "categories",
            "champ": "champs"}
CODE_SIMPLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,29}$")  # catégories et champs : le code sert de nom de colonne


class ClesUnites(dict):
    """Clés exactes des unités (« =code », « =symbole ») et les unités elles-mêmes (``objets``, {code: unité}, tenu à jour
    par l'analyse) : une cellule se lit avec la règle unique des unités (``rapprochement_unites``), jamais par une forme
    sans symboles (« m » n'est pas « M€ », « MW » n'est pas « mW »)."""

    def __init__(self, objets):
        super().__init__()
        self.objets = objets

    def rapprocher(self, texte):
        """(code ou None, avertissement) : avertissement quand seule la casse diffère (rapprochée sans risque)."""
        r = RU.rapprocher_unite([texte], self.objets.values())
        if r.unite is None:
            return None, ""
        if r.casse:
            return r.unite.code, libelle("admin.config.unite_casse_reprise", texte=r.texte, symbole=r.casse)
        return r.unite.code, ""


def _cles_objets(objets):
    """{« =code », « =symbole », clé normalisée du code, du libellé, du symbole ou de l'étiquette: code} ; pour les unités,
    seulement les clés exactes, avec les unités (``ClesUnites``)."""
    if objets and all(isinstance(o, Unite) for o in objets.values()):
        cles = ClesUnites(objets)
        for code, o in objets.items():
            for t in RU.ecritures(o)[1]:
                cles.setdefault("=" + t, code)
        for code in objets:
            cles["=" + code] = code
        for u in Unite.objects.filter(code__in=list(objets)):  # symbole d'avant l'import (onglet Unités qui le change)
            for t in RU.ecritures(u)[1]:
                cles.setdefault("=" + t, u.code)
        return cles
    cles = {}
    for code, o in objets.items():
        traduits = [v for d in (getattr(o, "traductions", None) or {}).values() for c, v in (d or {}).items() if c != "valeurs"]
        for t in (getattr(o, "symbole", ""), getattr(o, "libelle", ""), getattr(o, "abrege", ""), *traduits):
            if t:
                cles.setdefault("=" + t, code)
                if X.normaliser(t):
                    cles.setdefault(X.normaliser(t), code)
    for code in objets:
        cles["=" + code] = code
        if X.normaliser(code):
            cles[X.normaliser(code)] = code
    return cles


def _controle_reglable(obj, avant, nb_usages):
    """Motif de rejet d'une ligne d'un onglet réglable, ou "" (comportement ou format d'un type utilisé figés…)."""
    if isinstance(obj, Unite):
        obj.symbole = obj.symbole or obj.code
        if avant.get("symbole") is not None:  # unité existante : son symbole est figé par les valeurs de ses KPI
            motif = R.motif_symbole_unite(obj.code, (avant["symbole"], avant.get("traductions")), (obj.symbole, obj.traductions))
            if motif:
                return motif
    elif not getattr(obj, "libelle", ""):
        return libelle("admin.config.erreur.libelle_manquant")
    if isinstance(obj, (CategorieDescription, ChampPersonnalise)) and not CODE_SIMPLE.match(obj.code):
        return libelle("admin.config.erreur.code_simple")
    if len(obj.code) > obj._meta.get_field("code").max_length:
        return libelle("admin.config.erreur.code_long", maximum=obj._meta.get_field("code").max_length)
    if isinstance(obj, TypeSaisie):
        obj.abrege = obj.abrege or obj.libelle[:20]
        couleur = (obj.couleur or "").upper()
        if not CO.valide(couleur):
            return libelle("admin.config.erreur.couleur")
        if couleur != avant.get("couleur") or not obj.couleur_fond:
            obj.couleur = couleur
            obj.deriver_couleurs()
        if nb_usages and obj.comportement != avant.get("comportement"):
            return libelle("admin.config.erreur.type_comportement", n=nb_usages)
    if isinstance(obj, TypeReponse):
        if nb_usages and obj.format != avant.get("format"):
            return libelle("admin.config.erreur.type_format", n=nb_usages)
        if obj.format == TypeReponse.Format.LISTE and not obj.valeurs:
            return libelle("admin.config.erreur.liste_valeurs")
        if obj.format == TypeReponse.Format.TABLEAU:
            from . import tableaux

            listes = set(TypeReponse.objects.filter(format=TypeReponse.Format.LISTE).values_list("code", flat=True))
            erreurs = tableaux.erreurs_colonnes(obj.colonnes, listes)
            if erreurs:
                return " ".join(erreurs)
        retirees = set(avant.get("valeurs") or []) - set(obj.valeurs or [])
        if retirees:
            from .models import Reponse

            from .tableaux import valeurs_utilisees

            if Reponse.objects.filter(kpi__type_reponse=obj.code, texte__in=retirees).exists() or valeurs_utilisees(obj.code, retirees):
                return libelle("admin.config.erreur.valeurs_utilisees", n=len(retirees), valeurs=", ".join(sorted(retirees)))
    if isinstance(obj, ChampPersonnalise):
        if nb_usages and obj.type != avant.get("type"):
            return libelle("admin.config.erreur.champ_type", n=nb_usages)
        if obj.type == ChampPersonnalise.Type.LISTE and not obj.valeurs:
            return libelle("admin.config.erreur.liste_valeurs")
    return ""


def _analyser_reglable(a, nom, lignes, modele, colonnes, genre):
    """Unités, types, catégories, champs : création et modification (rien n'est supprimé par un import)."""
    existants = {o.code: o for o in modele.objects.all()}
    a.refs[genre] = dict(existants)
    colonnes = traduire_colonnes(colonnes, TRADUITS[nom], a.langues)
    donnees = lire_onglet(lignes, colonnes, "code", alias_reference(colonnes, TRADUITS[nom], a.langues)) if lignes is not None else None
    if donnees is not None:
        usages = PR.usages().get(SECTIONS[genre], {})
        changements, vus = [], {}
        for n, d in donnees:
            code = X.texte(d["code"])
            ch = Changement(n, code)
            changements.append(ch)
            if code in vus:
                ch.motif = libelle("admin.config.erreur.code_double", ligne=vus[code])
                continue
            vus[code] = n
            obj = copy.copy(existants[code]) if code in existants else modele(code=code)
            avant = {c: getattr(obj, c, None) for c in ("couleur", "comportement", "format", "type", "valeurs", "symbole")}
            avant["traductions"] = copy.deepcopy(getattr(obj, "traductions", None) or {})
            if not appliquer_champs(obj, d, colonnes, ch, code in existants, ignorer=("code",), a=a):
                continue
            appliquer_traductions(obj, d, colonnes, ch, code in existants)
            ch.motif = _controle_reglable(obj, avant, usages.get(code, 0))
            if ch.motif:
                continue
            if isinstance(obj, Unite) and avant.get("symbole") is not None:
                # casse seule du symbole d'une unité utilisée, quand elle peut en changer le sens : l'aperçu le
                # dit sur la ligne ; l'administrateur relit l'aperçu avant « Importer » (comme une date d'ouverture)
                ch.avertissement = R.avertissement_symbole_unite(obj.code, (avant["symbole"], avant.get("traductions")),
                                                                 (obj.symbole, obj.traductions))
            ch.objet = obj
            ch.action = "creer" if code not in existants else ("modifier" if ch.champs else "inchange")
            a.refs[genre][code] = obj
        a.onglets[nom] = changements
    a.cles[genre] = _cles_objets(a.refs[genre])


def _valeur_champ(c, brut):
    """Valeur d'un champ personnalisé depuis une cellule : None = cellule vide (valeur gardée), "" ou False = retirée."""
    t = X.texte(brut)
    if c.type == ChampPersonnalise.Type.CASE:
        return X.oui(t) if t else None
    if c.type == ChampPersonnalise.Type.DATE:
        return depuis_cellule(brut, "date") or ""
    if c.type == ChampPersonnalise.Type.LISTE and t:
        cle = L.cle_valeur(c, c.valeurs, t)  # valeur de référence, écrite dans n'importe quelle langue
        if cle:
            return cle
        raise ValueError(libelle("admin.config.erreur.valeur_possible", valeur=t, valeurs=", ".join(c.valeurs)))
    return t


def _unites_manquantes(a, donnees):
    """Unité citée dans l'onglet KPI mais inconnue : créée (annoncée dans l'onglet Unités de l'aperçu)."""
    cles = a.cles["unite"]
    if not isinstance(cles, ClesUnites):  # installation sans aucune unité
        cles = a.cles["unite"] = ClesUnites(a.refs["unite"])
    nouvelles = a.onglets.setdefault("Unités", [])
    for n, d in donnees:
        t = X.texte(d.get("unite"))
        if not t or t.lower() in SANS or cles.get("=" + t):
            continue
        code, note = cles.rapprocher(t)
        if code:
            if note:
                a.notes_unites[n] = note  # écart de casse seul : dit sur la ligne du KPI
            continue
        code, i = t[:56], 2
        while code in a.refs["unite"]:
            code, i = f"{t[:56]}~{i}", i + 1
        u = PR.nouvelle_unite(t, code, len(a.refs["unite"]) + 1)
        a.refs["unite"][code] = u
        cles["=" + t] = code
        nouvelles.append(Changement(n, code, action="creer", objet=u, motif=libelle("admin.config.unite_citee")))


def _analyser_kpi(a, lignes):
    """KPI après import : ensemble des codes (existants et nouveaux valides), pour les règles.

    Note aussi la granularité de chacun (``a.granularites``) : niveau proposé pour une règle importée sans niveau ;
    et les KPI à réponse oui / non ou liste (``a.non_numeriques``), exclus des formules."""
    existants = {k.code: k for k in KPI.objects.prefetch_related("descriptions")}
    a.granularites = {kid: k.granularite_id for kid, k in existants.items()}
    a.non_numeriques = {kid for kid, k in existants.items() if not k.est_numerique}
    types_avant = {kid: k.type_reponse for kid, k in existants.items()}  # avant l'import (les KPI changent en mémoire)
    unites_avant = {kid: k.unite_id for kid, k in existants.items()}
    if lignes is None:
        return set(existants)
    categories = sorted(a.refs["categorie"].values(), key=lambda c: (c.ordre, c.code))
    champs_perso = sorted(a.refs["champ"].values(), key=lambda c: (c.ordre, c.code))
    colonnes = colonnes_kpi(categories, champs_perso, a.langues)
    anciennes = [("ancien:theme", "Thème", 28, "texte"), ("ancien:sous_theme", "Sous-thème", 30, "texte")]  # avant les référentiels
    donnees = lire_onglet(lignes, colonnes + anciennes, "code", alias_kpi(categories, a.langues))
    if donnees is None:
        return set(existants)
    _unites_manquantes(a, donnees)
    minuscules = {kid.lower(): kid for kid in existants}
    numerique = next((t for t in a.refs["type_reponse"].values() if t.format == TypeReponse.Format.NOMBRE), None)
    changements, vus = [], {}
    for n, d in donnees:
        kid = X.texte(d["code"])
        ch = Changement(n, kid)
        changements.append(ch)
        if kid.lower() in vus:
            ch.motif = libelle("admin.config.erreur.code_double", ligne=vus[kid.lower()])
            continue
        vus[kid.lower()] = n
        existe = kid in existants
        if not existe and kid.lower() in minuscules:
            ch.motif = libelle("admin.config.erreur.kpi_conflit", code=minuscules[kid.lower()])
            continue
        try:
            valider_code_kpi(kid)
        except ValidationError as e:
            ch.motif = " ".join(e.messages)
            continue
        k = existants.get(kid) or KPI(code=kid)  # objets modifiés en mémoire seulement
        ch.objet = k
        decimales_avant = k.decimales
        if not appliquer_champs(k, d, colonnes, ch, existe, ignorer=("code",), a=a):
            continue
        appliquer_traductions(k, d, colonnes, ch, existe)
        CR.place_ancienne(a, ch, d, existe)
        if not k.type_reponse_id and numerique:
            k.type_reponse = numerique  # nouveau KPI sans type de réponse : un nombre
        manque = [lib for lib, ok in (("Granularité", k.granularite_id), ("Type de saisie", k.type_saisie_id),
                                      ("Type de réponse", k.type_reponse_id)) if not ok]  # noms des colonnes du fichier
        if manque:
            ch.motif = libelle("admin.config.erreur.kpi_manque", colonnes=", ".join(manque))
            continue
        # descriptions : une colonne par catégorie et par langue (texte vide = retiré) ; seuls les changements sont gardés
        textes = {(x.langue, x.categorie_id): x.texte for x in k.descriptions.all()} if existe else {}
        ch.descriptions = {}
        for i, l in enumerate(a.langues):
            for c in categories:
                col = f"desc:{c.code}" if i == 0 else f"desc:{c.code}:{l}"
                if col in d:
                    t, avant = X.texte(d[col]), textes.get((l, c.code), "")
                    if t != avant:
                        if existe:
                            ch.champs.append((f"{c.libelle} {L.suffixe(l)}", X.court(avant), X.court(t)))
                        ch.descriptions.setdefault(l, {})[c.code] = t
        ref = a.langues[0]
        for c in categories:
            if c.obligatoire and not ch.descriptions.get(ref, {}).get(c.code, textes.get((ref, c.code), "")):
                ch.motif = libelle("admin.config.erreur.description_obligatoire", nom=c.libelle)
        if ch.motif:
            continue
        # champs personnalisés : une colonne par champ
        valeurs = dict(k.champs)
        for c in champs_perso:
            col = f"champ:{c.code}"
            if col not in d:
                continue
            try:
                v = _valeur_champ(c, d[col])
            except ValueError as e:
                ch.motif = libelle("admin.config.erreur.champ_perso", nom=c.libelle, erreur=e)
                break
            if v is None or v == valeurs.get(c.code, "" if c.type != "case" else False):
                continue
            if existe:
                ch.champs.append((c.libelle, en_cellule(valeurs.get(c.code), "bool") if c.type == "case" else valeurs.get(c.code, ""),
                                  en_cellule(v, "bool") if c.type == "case" else v))
            if v in ("", False):
                valeurs.pop(c.code, None)
            else:
                valeurs[c.code] = v
        if ch.motif:
            continue
        k.champs = valeurs
        # case « Une source N/A compte comme 0 » : celle du fichier ; vide pour un nouveau KPI : d'après la formule
        k.na_compte_zero_choisi = X.texte(d.get("na_compte_zero")) != ""
        k.deduire_reglages()
        ch.champs = [c for c in ch.champs if c[0] != "Décimales"]  # unité « nombre entier » : toujours 0 décimale
        if existe and k.decimales != decimales_avant:
            ch.champs.append(("Décimales", en_cellule(decimales_avant, "entier"), en_cellule(k.decimales, "entier")))
        try:
            k.clean_fields(exclude=["code", "formule", "granularite", "type_saisie", "type_reponse", "unite", "champs"])
            erreurs = k.erreurs_regles()
            if erreurs:
                raise ValidationError(list(erreurs.values()))
        except ValidationError as e:
            ch.motif = " ".join(_messages(e))
            continue
        if existe:  # mêmes contrôles que la fiche KPI : le format et l'unité d'un KPI qui a des réponses ne changent plus
            ch.motif = (R.motif_format_fige(kid, types_avant.get(kid), k.type_reponse)
                        or R.motif_unite_figee(kid, unites_avant.get(kid), k.unite))
            if ch.motif:
                continue
        ch.action = "creer" if not existe else ("modifier" if ch.champs else "inchange")
        if n in a.notes_unites:  # unité reconnue malgré un écart de casse : à relire dans l'aperçu
            ch.avertissement = " ".join(x for x in (ch.avertissement, a.notes_unites[n]) if x)
        a.granularites[kid] = k.granularite_id
        if k.est_numerique:
            a.non_numeriques.discard(kid)
        else:
            a.non_numeriques.add(kid)
    # un KPI cité dans une formule (après l'import) reste un nombre : refusé avant de contrôler les formules qui le citent
    _refuser_cites_devenus_texte(a, changements, types_avant)
    # formules : références vers des KPI existants ou créés par ce fichier, numériques, sans boucle
    ids = set(existants) | {c.cle for c in changements if c.action != "rejet"}
    graphe = {}
    for kid, k in existants.items():
        if k.est_calcule and k.formule:
            graphe[kid] = F.codes_cites(k.formule, "N")
    for c in changements:
        if c.action != "rejet":
            graphe[c.cle] = F.codes_cites(c.objet.formule, "N") if c.objet.est_calcule else set()
    for c in changements:
        k = c.objet
        if c.action == "rejet" or not k.est_calcule or not k.formule.strip():
            continue
        try:
            verifier_formule(k.code, k.formule, kpis_existants=ids, graphe=graphe, non_numeriques=a.non_numeriques)
        except ValidationError as e:
            c.action, c.motif = "rejet", libelle("admin.config.erreur.formule", erreur=" ".join(e.messages))
    _refuser_cites_devenus_texte(a, changements, types_avant)  # une formule refusée garde celle de la base
    if a.desactiver_absents:
        for kid, k in existants.items():
            if kid.lower() not in vus and k.actif:
                ch = Changement(0, kid, action="desactiver", objet=k, champs=[("Actif", "Oui", "Non")])
                ch.motif = libelle("admin.config.erreur.absent_fichier")
                changements.append(ch)
    a.onglets["KPI"] = changements
    return {c.cle for c in changements if c.action != "rejet"} | set(existants)


def _refuser_cites_devenus_texte(a, changements, types_avant):
    """Refuse la ligne d'un KPI existant qui deviendrait oui / non ou liste alors qu'une formule le cite après l'import
    (celle du fichier pour une ligne gardée, sinon celle de la base) : « Ce KPI est utilisé dans la formule de … »."""
    gardes = [c for c in changements if c.action != "rejet" and c.objet is not None]
    cites = R.citations({c.cle: c.objet.formule if c.objet.est_calcule else "" for c in gardes})
    for c in gardes:
        avant = types_avant.get(c.cle)
        if avant is not None and avant.format in R.FORMATS_NUMERIQUES and not c.objet.est_numerique:
            motif = R.motif_cite_en_formule(c.objet.format, cites.get(c.cle))
            if motif:
                c.action, c.motif = "rejet", motif
                a.non_numeriques.discard(c.cle)  # il reste un nombre


def _messages(e):
    if hasattr(e, "message_dict"):
        noms = {c: entete for c, entete, _, _ in COLONNES_KPI}
        return [f"{noms.get(c, c)} : {' '.join(m)}" if c != "__all__" else " ".join(m) for c, m in e.message_dict.items()]
    return e.messages


def _analyser_regles(a, lignes, kpis):
    if lignes is None:
        return
    donnees = lire_onglet(lignes, COLONNES_REGLE, "nom")
    if donnees is None:
        return
    existantes = {r.nom: r for r in RegleCoherence.objects.all()}
    changements, vus = [], set()
    for n, d in donnees:
        nom = X.texte(d["nom"])
        ch = Changement(n, nom)
        changements.append(ch)
        if nom in vus:
            ch.motif = libelle("admin.config.erreur.regle_nom_double")
            continue
        vus.add(nom)
        r = existantes.get(nom) or RegleCoherence(nom=nom)
        ch.objet = r
        if not appliquer_champs(r, d, COLONNES_REGLE, ch, r.pk is not None, ignorer=("nom",), a=a):
            continue
        if not r.niveau_id:  # sans niveau : celui du premier KPI cité à gauche
            try:
                cites = [x.kpi for x in F.references(r.gauche)]
            except F.FormuleInvalide:
                cites = []
            r.niveau_id = next((a.granularites[x] for x in cites if a.granularites.get(x)), None)
        if not r.niveau_id:
            ch.motif = libelle("admin.config.erreur.regle_niveau")
            continue
        try:
            for cote in (r.gauche, r.droite):
                if not cote.strip():
                    raise ValidationError(libelle("admin.config.erreur.regle_parties"))
                verifier_formule("__regle__", cote, kpis_existants=kpis, non_numeriques=a.non_numeriques)
        except ValidationError as e:
            ch.motif = " ".join(e.messages)
            continue
        ch.action = "creer" if not r.pk else ("modifier" if ch.champs else "inchange")
    a.onglets["Règles de cohérence"] = changements


# ---------------------------------------------------------------- application
def appliquer(utilisateur, fichier, nom_fichier="", desactiver_absents=False):
    """Enregistre le fichier, tout ou rien : une seule ligne refusée, dans n'importe quel
    onglet, et rien n'est enregistré ; un fichier qui ne change rien n'écrit rien, pas même au journal.
    Renvoie (analyse, nombre d'écritures, exercices recalculés)."""
    a = analyser(fichier, desactiver_absents)
    if not a.importable:
        return a, 0, []
    with ESP.atomic():
        for c in a.onglets.get("Langues", []):
            if c.action in ("creer", "modifier"):
                c.objet.save()
        if a.defaut and a.defaut != Instance.courante().langue:
            i = Instance.courante()
            Journal.ecrire(utilisateur, "reglage_langues", i, "langue", i.langue, a.defaut)
            i.langue = a.defaut
            i.save(update_fields=["langue"])
        if any(c.action == "modifier" for c in a.onglets.get("Réglages", [])):
            i = Instance.objects.select_for_update().get(pk=Instance.courante().pk)  # relue sous verrou avant d'écrire
            if a.monnaie and i.monnaie != a.monnaie:
                Journal.ecrire(utilisateur, "reglage_referentiel", i, "Monnaie de référence", i.monnaie, a.monnaie)
                i.monnaie = a.monnaie
                i.save(update_fields=["monnaie", "date_maj"])
        for c in a.onglets.get("Niveaux", []):
            if c.action == "supprimer":
                c.objet.delete()
        for code, niv in a.niveaux.items():
            niv.rang = a.rangs[code]
            niv.save()
        for nom, *_ in REGLABLES:  # unités, types, catégories, champs : avant les KPI qui s'y réfèrent
            for c in a.onglets.get(nom, []):
                if c.action in ("creer", "modifier"):
                    c.objet.save()
        CR.appliquer_referentiels(a)
        CR.appliquer_themes(a)
        orgs = {o.nom: o for o in Organisation.objects.all()}
        a_ecrire = [c for c in a.onglets.get("Organisations", []) if c.action in ("creer", "modifier")]
        for c in sorted(a_ecrire, key=lambda c: a.rangs[c.objet.niveau_id]):  # les parents d'abord (rang 1 = sommet)
            o = c.objet
            o.parent = orgs.get(o._parent_nom) if o._parent_nom else None
            o.save()
            orgs[o.nom] = o
        for c in a.onglets.get("Alias", []):
            if c.action in ("creer", "modifier"):
                org, source, libelle, id_externe = c.objet
                OrgAlias.objects.update_or_create(source=source, libelle=libelle,
                                                  defaults={"organisation": orgs[org.nom], "id_externe": id_externe})
        modifies_calcul = False
        for c in a.onglets.get("KPI", []):
            if c.action in ("creer", "modifier", "desactiver"):
                k = c.objet
                if c.action == "desactiver":
                    k.actif = False
                super(KPI, k).save()  # dépendances reconstruites une seule fois plus bas
                for langue, textes in (c.descriptions or {}).items():
                    enregistrer_descriptions(k, textes, langue)
                modifies_calcul = modifies_calcul or c.action != "modifier" or any(
                    lib in ("Formule", "Granularité", "Agrégation", "Agrégation dans le temps", "Type de saisie", "Type de réponse", "Actif",
                            "Source N/A comptée comme 0")
                    for lib, _, _ in c.champs)
                if c.action != "creer":
                    for lib, avant, apres in c.champs:
                        Journal.ecrire(utilisateur, "reglage_kpi", k, lib, avant, apres)
        reconstruire_toutes_dependances()
        CR.appliquer_elements(a, utilisateur)
        CR.appliquer_places_anciennes(a, {c.cle: c.objet for c in a.onglets.get("KPI", []) if c.objet is not None})
        for c in a.onglets.get("Règles de cohérence", []):
            if c.action in ("creer", "modifier"):
                c.objet.save()
        Journal.ecrire(utilisateur, "import_configuration", utilisateur, "fichier", "",
                       f"{nom_fichier} : " + " ; ".join(f"{nom} {sum(1 for c in cs if c.action in ('creer', 'modifier', 'desactiver'))}"
                                                       for nom, cs in a.onglets.items()))
        # PostgreSQL : ANALYZE après la validation, avant les recalculs (test :
        # collecte/test_statistiques_a_jour_configuration_postgresql.py)
        statistiques_a_jour()
    campagnes = []
    autres = [c for nom in ("Organisations", "Règles de cohérence") for c in a.onglets.get(nom, []) if c.action in ("creer", "modifier")]
    if modifies_calcul or autres:
        from .calcul import recalculer
        from .coherence import controler

        faites = set()
        for camp in Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).select_related("referentiel", "periode"):
            if camp.periode_id not in faites:
                recalculer(camp)
                faites.add(camp.periode_id)
            controler(camp)
            campagnes.append(camp.nom_complet)
    return a, a.nb_ecritures, campagnes


# ---------------------------------------------------------------- export et modèle vierge
A_LIRE = {
    "fr": [
        "# Comment s'en servir",
        ("Modifier", "Les cellules jaunes se modifient ; les clés grises (codes) ne se modifient pas : elles relient chaque ligne "
                     "à ce qui existe dans l'outil. Une ligne ajoutée est une création."),
        ("Réimporter", "Administration › Fichiers de configuration › Modifier en masse : l'aperçu montre chaque création et chaque champ "
                       "modifié (avant → après) avant d'enregistrer. On peut n'importer qu'un onglet. Tout ou rien : une "
                       "seule ligne refusée, et rien n'est enregistré."),
        ("Rien n'est supprimé", "Une ligne absente reste dans l'outil ; pour arrêter un KPI : Actif = Non. Une cellule vide garde "
                                "la valeur actuelle (sauf les textes, qui sont vidés)."),
        ("Listes déroulantes", "Valeurs fermées (types, unités, niveaux, oui / non…) : choisir dans la liste (onglet Listes)."),
        ("Onglet KPI", "L'essentiel d'abord ; les colonnes avancées (ordre, décimales, traductions, autres descriptions, champs "
                       "personnalisés…) sont regroupées à droite : bouton « + » au-dessus des colonnes pour les afficher."),
        ("Langues", "Une colonne par langue pour les textes traduisibles, ex. « Nom (FR) », « Nom (EN) » ; la première est la "
                    "langue de référence."),
        ("Formules", "Codes entre crochets : [CODE] / [AUTRE] * 1000 ; [CODE@N-1] = exercice précédent."),
        "# Onglets",
        ("Langues, Niveaux", "Langues des contenus ; niveaux de l'arbre du sommet (rang 1) vers le bas."),
        ("Réglages", "Réglages de l'espace, un par ligne : monnaie de référence des modèles de la bibliothèque (code ISO 4217 : "
                     "EUR, USD, GBP, CHF…). Aucune valeur n'est convertie."),
        ("Unités, Types, Catégories, Champs", "Réglages des fiches KPI : unités, types de saisie et de réponse, rubriques de la "
                                              "définition, champs personnalisés."),
        ("Référentiels, Thèmes, Éléments", "Cadres de reporting, leur arbre de thèmes et la place de chaque KPI dans chacun."),
        ("KPI", "Le catalogue : une ligne par KPI, repérée par son ID."),
        ("Organisations, Alias", "L'arbre des organisations (code stable des exports) et leurs autres noms dans les fichiers."),
        ("Règles de cohérence", "Contrôles entre KPI. Tolérance en % (1 = 1 %)."),
        "# Pour une autre structure",
        ("Démarrer", "Partir du modèle vierge : remplir Niveaux, Unités, Types si besoin, puis Organisations, KPI et Règles ; "
                     "importer ; créer les comptes dans l'outil."),
    ],
    "en": [
        "# How to use it",
        ("Edit", "Yellow cells can be changed; grey keys (codes) must not be changed: they link each row to what exists in the "
                 "tool. An added row is a creation."),
        ("Import again", "Administration › Configuration files › Edit in bulk: the preview shows each creation and each changed "
                         "field (before → after) before saving. A single sheet can be imported. All or nothing: a single refused "
                         "row, and nothing is saved."),
        ("Nothing is deleted", "A missing row stays in the tool; to stop a KPI: Active = No. An empty cell keeps the current value "
                               "(texts are emptied)."),
        ("Drop-down lists", "Closed values (types, units, levels, yes / no…): pick from the list (Lists sheet)."),
        ("KPI sheet", "Essentials first; advanced columns (order, decimals, translations, other descriptions, custom fields…) are "
                      "grouped on the right: “+” button above the columns to show them."),
        ("Languages", "One column per language for translatable texts, e.g. “Name (FR)”, “Name (EN)”; the first one is the "
                      "reference language."),
        ("Formulas", "Codes in square brackets: [CODE] / [OTHER] * 1000; [CODE@N-1] = previous year."),
        "# Sheets",
        ("Languages, Levels", "Content languages; levels of the tree from the top (rank 1) down."),
        ("Settings", "Settings of the space, one per row: reference currency of the library templates (ISO 4217 code: EUR, "
                     "USD, GBP, CHF…). No value is converted."),
        ("Units, Types, Categories, Fields", "KPI settings: units, input and answer types, definition sections, custom fields."),
        ("Frameworks, Themes, Elements", "Reporting frameworks, their theme tree and the place of each KPI in each of them."),
        ("KPI", "The catalogue: one row per KPI, identified by its ID."),
        ("Organisations, Aliases", "The organisation tree (stable export code) and their other names in files."),
        ("Consistency rules", "Checks between KPIs. Tolerance in % (1 = 1%)."),
    ],
}
# Clés de chaque onglet (grises, à ne pas modifier) et première colonne qui défile
CLES = {"Thèmes": ({"referentiel", "code"}, 3), "Éléments": ({"referentiel", "kpi"}, 3), "Organisations": ({"nom"}, 2),
        "Alias": ({"source", "libelle"}, 4), "Règles de cohérence": ({"nom"}, 2), "KPI": ({"code"}, 3)}


def lignes_kpi(kpis, categories, champs_perso, langues=None):
    """Cellules de l'onglet KPI : champs du KPI, nom et descriptions par langue, champs personnalisés."""
    langues = langues or langues_fichier()
    colonnes = colonnes_kpi(categories, champs_perso, langues)
    lignes = []
    for k in kpis:
        textes = {(d.langue, d.categorie_id): d.texte for d in k.descriptions.all()}
        traduits = _cellules_traduites(k, colonnes)
        ligne = []
        for c, _, _, g in colonnes:
            if c in traduits:
                ligne.append(traduits[c])
            elif c.startswith("desc:"):
                morceaux = c.split(":")
                ligne.append(textes.get((morceaux[2] if len(morceaux) > 2 else langues[0], morceaux[1]), ""))
            elif c.startswith("champ:"):
                v = k.champs.get(c[6:])
                if g == "bool":  # case jamais cochée ni décochée : vide (comme dans le fichier référentiel)
                    v = "" if v is None else ("Oui" if v else "Non")
                elif g == "date" and v:
                    v = datetime.date.fromisoformat(v)
                ligne.append(v or "")
            else:
                ligne.append(en_cellule(getattr(k, c), g))
        lignes.append(ligne)
    return colonnes, lignes


def classeur(vierge=False, langue=None):
    langue = langue or L.courante()
    with L.session():
        return _classeur(vierge, langue)


def lignes_traduites(objets, colonnes):
    """Lignes d'un onglet dont certaines colonnes sont traduites (« tr:champ:langue »)."""
    lignes = []
    for o in objets:
        traduits = _cellules_traduites(o, colonnes)
        lignes.append([traduits[c] if c in traduits else en_cellule(getattr(o, c), g) for c, _, _, g in colonnes])
    return lignes


def _classeur(vierge, langue="fr"):
    wb = X.classeur()
    langues = langues_fichier()
    defaut = Instance.courante().langue
    niveaux = N.tous()
    categories, champs_perso = list(CategorieDescription.objects.all()), list(ChampPersonnalise.objects.all())
    reglables = {nom: [] if vierge else list(modele.objects.all()) for nom, _, modele, _, _ in REGLABLES}
    kpis = [] if vierge else list(KPI.objects.select_related("granularite").prefetch_related("descriptions").order_by("ordre", "code"))
    orgs = [] if vierge else sorted(Organisation.objects.select_related("parent", "niveau"), key=_cle_org)
    alias = [] if vierge else list(OrgAlias.objects.select_related("organisation").order_by("organisation__nom", "source", "libelle"))
    regles = [] if vierge else list(RegleCoherence.objects.select_related("niveau"))
    listes = X.nom_onglet("Listes", langue)
    onglet = lambda nom, colonnes, lignes: _onglet(wb, nom, colonnes, lignes, langue, listes)  # noqa: E731
    onglet("Langues", COLONNES_LANGUE, [[l.code, l.libelle, l.ordre, en_cellule(l.active, "bool"), en_cellule(l.code == defaut, "bool")]
                                        for l in Langue.objects.all()])
    from parametres import monnaies as MO

    onglet("Réglages", COLONNES_REGLAGES, [[REGLAGE_MONNAIE, libelle("admin.monnaies.config_libelle", langue), MO.reference()]])
    colonnes = traduire_colonnes(COLONNES_NIVEAU, TRADUITS["Niveaux"], langues)
    ws = onglet("Niveaux", colonnes, lignes_traduites(niveaux, colonnes))
    for i, n in enumerate(niveaux, start=2):  # chaque niveau à sa couleur
        c = ws.cell(i, 3)
        c.fill, c.font = PatternFill("solid", fgColor=n.couleur_pale.lstrip("#")), Font(bold=True, color=n.couleur_texte.lstrip("#"))
    for nom, _, _, colonnes, _ in REGLABLES:
        colonnes = traduire_colonnes(colonnes, TRADUITS[nom], langues)
        onglet(nom, colonnes, lignes_traduites(reglables[nom], colonnes))
    structure = CR.onglets(langues, vierge)
    for nom, colonnes, lignes in structure[:2]:  # Référentiels, Thèmes
        onglet(nom, colonnes, lignes)
    colonnes, lignes = lignes_kpi(kpis, categories, champs_perso, langues)
    ws = onglet("KPI", colonnes, lignes)
    X.replier_colonnes(ws, nb_essentielles(colonnes) + 1, len(colonnes))
    onglet(*structure[2])  # Éléments
    for j, (c, _, _, g) in enumerate(colonnes, start=1):  # champ « liste » : ses valeurs en liste déroulante
        champ = next((x for x in champs_perso if c == f"champ:{x.code}"), None)
        if champ and champ.type == "liste" and champ.valeurs:
            dv = DataValidation(type="list", formula1='"' + ",".join(v.replace(",", " ").replace('"', "'") for v in champ.valeurs) + '"',
                                allow_blank=True)
            dv.add(f"{X.get_column_letter(j)}2:{X.get_column_letter(j)}{max(len(lignes) + 200, 500)}")
            ws.add_data_validation(dv)
    onglet("Organisations", COLONNES_ORG,
           [[o.nom, o.code, o.nom_court, en_cellule(o.niveau, "niveau"), o.parent.nom if o.parent else "",
             en_cellule(o.type_site, Organisation.TypeSite) if o.type_site else "", o.rang, en_cellule(o.actif, "bool"),
             en_cellule(o.date_ouverture, "jour")] for o in orgs])
    onglet("Alias", COLONNES_ALIAS, [[x.organisation.nom, x.source, x.libelle, x.id_externe] for x in alias])
    onglet("Règles de cohérence", COLONNES_REGLE, [[en_cellule(getattr(r, c), g) for c, _, _, g in COLONNES_REGLE] for r in regles])
    _listes(wb, niveaux, langue)
    sel = lambda fr, en: X.selon(langue, fr, en)  # noqa: E731
    X.feuille_a_lire(wb, sel("Configuration complète", "Full configuration") + f" – {Instance.courante().titre}", [
        (sel("Exporté le", "Exported on"), DC.date_heure_courte(timezone.localtime(), langue)),
        (sel("Contenu", "Content"), sel("Modèle vierge", "Blank template") if vierge else sel(
            f"{len(niveaux)} niveaux, {len(reglables['Unités'])} unités, {len(kpis)} KPI, {len(orgs)} organisations, "
            f"{len(alias)} libellés d'import, {len(regles)} règles de cohérence",
            f"{len(niveaux)} levels, {len(reglables['Unités'])} units, {len(kpis)} KPIs, {len(orgs)} organisations, "
            f"{len(alias)} import labels, {len(regles)} consistency rules")),
    ] + A_LIRE["en" if X.anglais(langue) else "fr"], langue)
    return wb


def _cle_org(o):
    chemin = []
    while o:
        chemin.append((o.rang, o.nom))
        o = o.parent
    return tuple(reversed(chemin))


def _onglet(wb, nom, colonnes, lignes, langue="fr", listes="Listes"):
    """Onglet aux règles communes (clés grises, cellules modifiables jaunes, en-têtes dans la langue du fichier), avec
    les listes déroulantes des valeurs fermées."""
    cles, figer = CLES.get(nom, ({colonnes[0][0]}, 2))
    roles = ["cle" if c in cles else "remplir" for c, _, _, _ in colonnes]
    ws = X.onglet_donnees(wb, nom, [(e, t) for _, e, t, _ in colonnes], lignes, roles, langue, figer)
    fin = max(len(lignes) + 200, 500)
    for j, (_, _, _, genre) in enumerate(colonnes, start=1):
        source = _source_liste(genre, listes)
        if source:
            dv = DataValidation(type="list", formula1=source, allow_blank=True)
            dv.add(f"{X.get_column_letter(j)}2:{X.get_column_letter(j)}{fin}")
            ws.add_data_validation(dv)
    return ws


LISTES = [("Oui / Non", "bool"), ("Type de saisie", "type_saisie"), ("Type de réponse", "type_reponse"), ("Unité", "unite"),
          ("Niveau", "niveau"), ("Agrégation", KPI.Agregation), ("Agrégation dans le temps", KPI.AgregationTemps),
          ("Confidentialité", KPI.Confidentialite), ("Fréquence", Frequence), ("Comparaison", Referentiel.Comparaison),
          ("Type de site", Organisation.TypeSite), ("Opérateur", RegleCoherence.Operateur),
          ("Comportement", TypeSaisie.Comportement), ("Format", TypeReponse.Format), ("Type de champ", ChampPersonnalise.Type),
          ("Monnaie", "monnaie")]
TAILLES_LISTES = {"niveau": NiveauHierarchique.MAXIMUM, "type_saisie": 20, "type_reponse": 30, "unite": 300}  # place pour en ajouter


def _valeurs_liste(genre, niveaux=None):
    if genre == "niveau":
        return [n.nom for n in (niveaux if niveaux is not None else N.tous())]
    if genre == "type_saisie":
        return [t.libelle for t in TypeSaisie.objects.all()]
    if genre == "type_reponse":
        return [t.libelle for t in TypeReponse.objects.all()]
    if genre == "unite":
        return [u.symbole for u in Unite.objects.all()]
    if genre == "monnaie":
        from parametres.monnaies import CODES

        return list(CODES)
    return ["Oui", "Non"] if genre == "bool" else [l for _, l in genre.choices]


def _source_liste(genre, onglet="Listes"):
    """Plage de l'onglet Listes ; les listes réglables (niveaux, types, unités) ont de la place pour en ajouter."""
    for j, (_, g) in enumerate(LISTES, start=1):
        if g is genre or (isinstance(g, str) and g == genre):
            col = X.get_column_letter(j)
            n = TAILLES_LISTES.get(g) if isinstance(g, str) and g in TAILLES_LISTES else len(_valeurs_liste(g))
            return f"={onglet}!${col}$2:${col}${max(n, 1) + 1}"
    return None


def _listes(wb, niveaux=None, langue="fr"):
    ws = wb.create_sheet(X.nom_onglet("Listes", langue))
    for j, (titre, genre) in enumerate(LISTES, start=1):
        X.style_entete(ws.cell(1, j, X.entete(titre, langue)), "info")
        for i, v in enumerate(_valeurs_liste(genre, niveaux), start=2):
            X.ecrire_cellule(ws, i, j, v)
    X.largeurs(ws, [18] * len(LISTES))
    ws.freeze_panes = "A2"


def exporter(format="xlsx", vierge=False, style="fr", langue=None):
    langue = langue or L.courante()
    sel = lambda fr, en: X.selon(langue, fr, en)  # noqa: E731
    nom = X.nom_fichier(sel("Configuration modele vierge", "Configuration blank template") if vierge
                        else sel("Configuration complete", "Full configuration"))
    if format == "csv":
        kpis = [] if vierge else KPI.objects.select_related("granularite").prefetch_related("descriptions").order_by("ordre", "code")
        with L.session():
            colonnes, lignes = lignes_kpi(kpis, list(CategorieDescription.objects.all()), list(ChampPersonnalise.objects.all()))
        lignes = [[X.entete(e, langue) for _, e, _, _ in colonnes]] + lignes
        return X.reponse_csv(lignes, X.nom_fichier(sel("Catalogue KPI", "KPI catalogue")), style)
    return X.reponse_excel(classeur(vierge, langue), nom)
