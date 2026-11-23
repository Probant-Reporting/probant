"""Paquet référentiel : forme JSON et bibliothèque des référentiels fournis."""
import copy
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from referentiel.models import Referentiel

from .modele import BIBLIOTHEQUE, Paquet, PaquetInvalide, _t, documents_affiches


# ================================================================= JSON (bibliothèque)
def vers_json(p):
    d = asdict(p)
    if not d.get("documents"):  # l'export d'un référentiel garde sa forme d'avant : la rubrique n'existe que pour un modèle fourni
        d.pop("documents", None)
    return json.dumps(d, ensure_ascii=False, indent=1)


def depuis_dict(d):
    if not isinstance(d, dict) or not isinstance(d.get("referentiel"), dict):
        raise PaquetInvalide(_t("referentiels.paquets.illisible"))
    noms = {f for f in Paquet.__dataclass_fields__}
    d = {k: copy.deepcopy(v) for k, v in d.items() if k in noms}
    _controler_forme(d)
    return Paquet(**d)


LISTES_PAQUET = ("langues", "niveaux", "unites", "types_saisie", "types_reponse", "categories", "champs", "themes", "kpis", "regles",
                 "documents")


def _controler_forme(d):
    """Forme d'un paquet JSON (fichier modifié à la main ou forgé) : rubriques et en-tête du référentiel du bon type,
    textes et nombres simples remis en forme ; PaquetInvalide qui nomme la partie en cause sinon. Le détail des
    éléments est contrôlé par l'aperçu (vues_paquets._analyse)."""
    def refus(champ):
        raise PaquetInvalide(_t("referentiels.paquets.contenu_inattendu", champ=champ))

    langue = d.get("langue_reference", "fr")
    if not isinstance(langue, str) or not langue.strip():
        refus("langue_reference")
    for cle in ("exporte_le", "exporte_de"):
        if cle in d and not isinstance(d[cle], str):
            d[cle] = "" if d[cle] is None or isinstance(d[cle], (dict, list)) else str(d[cle])
    ref = d["referentiel"]
    for cle, v in list(ref.items()):
        if cle in ("nom", "description", "thematique"):  # textes par langue
            if v is None:
                ref[cle] = {}
            elif isinstance(v, str):
                ref[cle] = {langue: v}
            elif isinstance(v, dict) and all(isinstance(c, str) and isinstance(t, (str, type(None))) for c, t in v.items()):
                ref[cle] = {c: t or "" for c, t in v.items()}
            else:
                refus(f"referentiel.{cle}")
        elif cle == "mois_debut":
            if v in (None, ""):
                del ref[cle]
            elif isinstance(v, bool) or not (isinstance(v, int) or isinstance(v, str) and v.strip().isdecimal()) or not 1 <= int(v) <= 12:
                refus(f"referentiel.{cle}")
            else:
                ref[cle] = int(v)
        elif cle == "date_version":  # AAAA-MM-JJ, ou vide
            if v in (None, ""):
                ref[cle] = ""
            elif not isinstance(v, str) or not _date_iso(v):
                refus(f"referentiel.{cle}")
        elif v is None:
            ref[cle] = ""
        elif isinstance(v, (bool, dict, list)):
            refus(f"referentiel.{cle}")
        elif not isinstance(v, str):
            ref[cle] = str(v)
    for cle in LISTES_PAQUET:
        if cle not in d:
            continue
        if d[cle] is None:
            d[cle] = []
        elif not isinstance(d[cle], list) or not all(isinstance(x, dict) for x in d[cle]):
            refus(cle)
        for i, x in enumerate(d[cle]):
            if cle == "documents":  # documents sources : des textes simples
                d[cle][i] = x = {c: "" if v is None else str(v) for c, v in x.items()
                                 if isinstance(c, str) and not isinstance(v, (dict, list))}
            for champ in TEXTES_LISTES.get(cle, ()):  # textes traduits : {langue: texte} (un texte seul : langue de référence)
                v = x.get(champ)
                if v is None:
                    continue
                if isinstance(v, str):
                    x[champ] = {langue: v}
                elif isinstance(v, dict) and all(isinstance(c, str) and isinstance(t, (str, type(None))) for c, t in v.items()):
                    x[champ] = {c: t or "" for c, t in v.items()}
                else:
                    refus(f"{cle}[{i + 1}].{champ}")
            for champ, (bas, haut) in ENTIERS_LISTES.get(cle, {}).items():
                v = x.get(champ)
                if v in (None, ""):
                    continue
                if isinstance(v, bool) or not (isinstance(v, int) or isinstance(v, str) and v.strip().lstrip("-").isdecimal()) \
                        or not bas <= int(v) <= haut:
                    refus(f"{cle}[{i + 1}].{champ}")
                x[champ] = int(v)
            if cle == "types_reponse" and "colonnes" in x:  # tableau : liste de colonnes {code, libelle, type, liste, unite}
                if x["colonnes"] is None:
                    x["colonnes"] = []
                elif not isinstance(x["colonnes"], list) or not all(isinstance(c, dict) for c in x["colonnes"]):
                    refus(f"{cle}[{i + 1}].colonnes")
            if cle == "regles" and x.get("tolerance") not in (None, ""):
                try:
                    t = Decimal(str(x["tolerance"]).replace(",", "."))
                except (InvalidOperation, ValueError):
                    refus(f"{cle}[{i + 1}].tolerance")
                if isinstance(x["tolerance"], (bool, dict, list)) or not t.is_finite() or abs(t) > 10 ** 9:
                    refus(f"{cle}[{i + 1}].tolerance")


def _date_iso(v):
    import datetime

    try:
        datetime.date.fromisoformat(v.strip())
        return len(v.strip()) == 10
    except ValueError:
        return False


# textes traduits ({langue: texte}) et nombres entiers (bornes) des éléments d'un paquet, par rubrique
TEXTES_LISTES = {"niveaux": ("nom", "nom_pluriel"), "unites": ("symbole", "libelle"), "types_saisie": ("libelle", "abrege"),
                 "types_reponse": ("libelle",), "categories": ("libelle",), "champs": ("libelle",), "themes": ("nom",),
                 "kpis": ("libelle",)}
ENTIERS_LISTES = {"niveaux": {"rang": (0, 1000)}, "unites": {"decimales": (0, 10)}, "categories": {"ordre": (0, 10 ** 6)},
                  "themes": {"ordre": (0, 10 ** 6)}, "kpis": {"decimales": (0, 10)}}


def depuis_json(texte):
    try:
        return depuis_dict(json.loads(texte))
    except json.JSONDecodeError as e:
        raise PaquetInvalide(_t("referentiels.paquets.json_illisible", erreur=str(e)))
    except RecursionError:  # imbrication démesurée ([[[[…]]]])
        raise PaquetInvalide(_t("referentiels.paquets.illisible"))


# ================================================================= bibliothèque fournie avec l'outil
@dataclass
class Fourni:
    nom_fichier: str
    paquet: Paquet
    installe: Referentiel | None = None

    @property
    def etat(self):
        """« absent », « installe », « a_jour » (même version), « mise_a_jour » (version plus récente dans la bibliothèque)."""
        if self.installe is None:
            return "absent"
        c = comparer_versions(self.paquet.version, self.installe.version)
        return "mise_a_jour" if c > 0 else "a_jour"


def bibliotheque():
    """Référentiels fournis (fichiers JSON du dossier ``referentiel/bibliotheque``), avec leur état dans l'installation
    (installé = un référentiel de même identifiant). Leurs montants sont écrits dans la monnaie de référence de l'espace
    (``parametres.monnaies.adapter_paquet`` : « € » devient « $ » si l'espace compte en dollars) ; rien ne change en euros."""
    from parametres import monnaies as MO

    refs = {str(r.identifiant): r for r in Referentiel.objects.all()}
    monnaie = MO.reference()
    sortie = []
    for chemin in sorted(BIBLIOTHEQUE.glob("*.json")):
        p = MO.adapter_paquet(depuis_json(chemin.read_text(encoding="utf-8")), monnaie)
        sortie.append(Fourni(chemin.name, p, refs.get(str(p.referentiel.get("identifiant") or ""))))
    return sortie


def ordre_modeles():
    """{code du modèle : rang} des définitions de la bibliothèque (``SOCLE["ordre"]`` : norme VS, transparence des
    rémunérations, puis ESRS 2, E1 à E5, S1 à S4, G1, l'ordre de la norme)."""
    from referentiel.bibliotheque import socles as S
    from referentiel.bibliotheque.socles_retires import SOCLES_RETIRES

    return {s["code"]: s.get("ordre", 10 ** 6) for s in [*SOCLES_RETIRES, *S.SOCLES]}


_DOCUMENTS_FOURNIS = {}  # nom du fichier -> ((taille, date de modification), identifiant, documents)


def documents_fournis(identifiant):
    """Documents sources du modèle de la bibliothèque qui a cet identifiant (``[]`` si ce n'est pas un modèle fourni). Lu
    dans les fichiers JSON de la bibliothèque, gardé en mémoire tant que le fichier ne change pas : l'en-tête d'un
    référentiel installé l'affiche sans lire dix mégaoctets à chaque page. Rien n'est enregistré en base."""
    identifiant = str(identifiant or "")
    for chemin in sorted(BIBLIOTHEQUE.glob("*.json")):
        etat = chemin.stat()
        cle = (etat.st_size, etat.st_mtime_ns)
        connu = _DOCUMENTS_FOURNIS.get(chemin.name)
        if connu is None or connu[0] != cle:
            try:
                d = json.loads(chemin.read_text(encoding="utf-8"))
                connu = (cle, str((d.get("referentiel") or {}).get("identifiant") or ""), d.get("documents") or [])
            except (OSError, ValueError, AttributeError):
                connu = (cle, "", [])
            _DOCUMENTS_FOURNIS[chemin.name] = connu
        if connu[1] and connu[1] == identifiant:
            return documents_affiches(connu[2])
    return []


def fourni(nom_fichier):
    for f in bibliotheque():
        if f.nom_fichier == nom_fichier:
            return f
    raise PaquetInvalide(_t("referentiels.paquets.fourni_introuvable"))


def comparer_versions(a, b):
    """1 si a est plus récente que b, -1 si plus ancienne, 0 si identique (« 1.10 » > « 1.9 »)."""
    def cle(v):
        morceaux = [(0, int(x), "") if x.isdecimal() else (1, 0, x) for x in re.split(r"[.\-_ ]+", str(v or "").strip()) if x]
        while morceaux and morceaux[-1] == (0, 0, ""):
            morceaux.pop()
        return morceaux
    ca, cb = cle(a), cle(b)
    return (ca > cb) - (ca < cb)
