"""Contrôle des modèles de la bibliothèque avant génération (``python3 manage.py bibliotheque --validate``).

Reprend les règles que l'outil appliquera à l'installation (fiche KPI, formules, agrégations), pour qu'un modèle refusé le
soit ici, pas chez un client, et ajoute celles de la bibliothèque : textes en français et en anglais, une définition pour
chaque KPI, sources des formules dans le modèle, fichier de couverture de la norme complet. Les quatre premiers socles
(définis dans socles.py, descriptions anglaises dans documentation.T) sont contrôlés sans les règles propres aux nouveaux
modèles (``strict``).
"""
import csv
import datetime
import json
import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError

from referentiel import formule as F
from referentiel.models import CODE_KPI, CODE_REFERENTIEL, CODES_REFERENTIEL_RESERVES, verifier_formule

from . import socles as S
from . import sources
from .outils import NIVEAUX_CONSEILLES
from .outils import langue as texte_langue

STATUTS_COUVERTURE = ("covered", "partial", "automatic", "out_of_scope", "todo")  # automatic : rempli par l'export, sans KPI
EXIGENCES = ("mandatory", "if_applicable", "voluntary")
COLONNES_COUVERTURE = ("reference", "requirement", "datapoint", "status", "kpi_codes", "note")
AGREGATIONS = ("Somme", "Formule", "Décompte", "Aucune")
TEMPS = ("", "somme", "moyenne", "derniere", "aucune")
CODE_THEME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
COULEUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
FICHIER = re.compile(r"^[a-z0-9_]+\.json$")


@dataclass
class Rapport:
    code: str
    erreurs: list = field(default_factory=list)
    avertissements: list = field(default_factory=list)
    chiffres: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.erreurs


def elements(socle):
    """KPI placés dans l'arbre : [(code, thème, référence dans la norme, obligatoire)]."""
    sortie = []

    def parcourir(noeuds, parent):
        for n in noeuds:
            if S.est_theme(n):
                parcourir(n[3], n[0])
            else:
                t = (n,) if isinstance(n, str) else tuple(n)
                sortie.append((t[0], parent, t[1] if len(t) > 1 else "", t[2] if len(t) > 2 else True))
    parcourir(socle["arbre"], "")
    return sortie


def themes(socle):
    sortie = []

    def parcourir(noeuds, profondeur):
        for n in noeuds:
            if S.est_theme(n):
                sortie.append((n[0], n[1], n[2], profondeur))
                parcourir(n[3], profondeur + 1)
            elif not isinstance(n, (str, tuple, list)) or (isinstance(n, (tuple, list)) and not n):
                raise ValueError(f"nœud illisible dans l'arbre : {n!r}")
    parcourir(socle["arbre"], 1)
    return sortie


def controler(socle, kpis=None, regles=None, unites=None, types_reponse=None, couverture=None, propres=None,
              regles_propres=None):
    """Rapport d'un modèle. ``couverture`` : chemin du fichier de couverture (nouveaux modèles), ou None. ``propres`` : codes
    des KPI que le fichier du modèle définit lui-même (règles de textes complètes) ; un KPI repris d'ailleurs garde les
    siennes (ses textes se corrigent là où il est défini)."""
    kpis = S.KPIS if kpis is None else kpis
    regles = S.REGLES if regles is None else regles
    unites = {u[0] for u in (S.UNITES if unites is None else unites)}
    formats = {t[0]: t[2] for t in (S.TYPES_REPONSE if types_reponse is None else types_reponse)}
    types_saisie = {t[0]: t[4] for t in S.TYPES_SAISIE}
    strict = "module" in socle  # modèle de definitions/ : règles complètes
    r = Rapport(socle.get("code", "?"))
    E, A = r.erreurs.append, r.avertissements.append

    # ------------------------------------------------ en-tête du modèle
    code = socle.get("code", "")
    if not CODE_REFERENTIEL.match(code) or code in CODES_REFERENTIEL_RESERVES:
        E(f"code du modèle invalide : « {code} » (lettres, chiffres, - et _, 30 caractères au plus)")
    if not FICHIER.match(socle.get("fichier", "")):
        E(f"fichier JSON invalide : « {socle.get('fichier')} » (minuscules, chiffres, _ ; .json)")
    if not COULEUR.match(socle.get("couleur", "")):
        E(f"couleur invalide : « {socle.get('couleur')} » (#RRVVBB)")
    for cle in ("nom", "description", "thematique"):
        v = socle.get(cle)
        if not (isinstance(v, tuple) and len(v) == 2 and all(isinstance(x, str) and x.strip() for x in v)):
            E(f"{cle} : il faut un couple (français, anglais) non vide")
    date = socle.get("date")
    if date or strict:
        try:
            jour = datetime.date.fromisoformat(str(date or ""))
            if len(str(date)) != 10:
                raise ValueError
        except ValueError:
            E(f"date de la version invalide : « {date} » (AAAA-MM-JJ, obligatoire)")
        else:
            if jour > datetime.date.today():
                E(f"date de la version dans le futur : {date}")
    if strict:
        for erreur in sources.erreurs(socle.get("source")):
            E(erreur)
        if not re.match(r"^\d+\.\d+(\.\d+)?$", str(socle.get("version", ""))):
            E(f"version du modèle invalide : « {socle.get('version')} » (ex. 1.0)")
        controler_libelles(socle, E)

    # ------------------------------------------------ arbre
    try:
        ths = themes(socle)
    except ValueError as e:
        E(str(e))
        return r
    vus = set()
    for c, fr, en, profondeur in ths:
        if not CODE_THEME.match(c):
            E(f"thème « {c} » : code invalide (lettres, chiffres, _ . -)")
        if c in vus:
            E(f"thème « {c} » : code utilisé deux fois")
        vus.add(c)
        if not (fr.strip() and en.strip()):
            E(f"thème « {c} » : nom français et anglais obligatoires")
        if profondeur > 4:
            A(f"thème « {c} » : profondeur {profondeur} (plus de 4 niveaux se lit mal)")
    els = elements(socle)
    places = [c for c, *_ in els]
    doubles = sorted({c for c in places if places.count(c) > 1})
    if doubles:
        E("KPI placé deux fois dans l'arbre : " + ", ".join(doubles))
    places = set(places)
    for c, theme, _, _ in els:
        if not theme:
            A(f"{c} : placé hors de tout thème")

    # ------------------------------------------------ KPI
    non_numeriques = {c for c, d in kpis.items() if formats.get(d["reponse"]) not in ("nombre", "pourcentage")}
    graphe = {c: F.codes_cites(d["formule"], "N") for c, d in kpis.items() if d["formule"] and _lisible(d["formule"])}
    for c in sorted(places):
        d = kpis.get(c)
        if d is None:
            E(f"{c} : KPI placé dans l'arbre mais défini nulle part (KPIS)")
            continue
        _controler_kpi(c, d, kpis, formats, types_saisie, unites, non_numeriques, graphe, places,
                       strict and (propres is None or c in propres), E, A)

    # ------------------------------------------------ colonnes des tableaux
    types = S.TYPES_REPONSE if types_reponse is None else types_reponse
    listes = {x[0] for x in types if x[2] == "liste"}
    for code_type in sorted({kpis[c]["reponse"] for c in places if c in kpis and formats.get(kpis[c]["reponse"]) == "tableau"}):
        from collecte.tableaux import erreurs_colonnes

        definition = next(x for x in types if x[0] == code_type)
        for e in erreurs_colonnes(definition[3], listes):
            E(f"tableau {code_type} : {e}")
        for col in definition[3] if isinstance(definition[3], list) else []:
            lib = col.get("libelle") if isinstance(col, dict) else None
            if strict and not (isinstance(lib, dict) and lib.get("fr") and lib.get("en")):
                E(f"tableau {code_type} : colonne « {col.get('code')} » sans libellé français et anglais")

        # ------------------------------------------------ règles de cohérence
    for nom in socle.get("regles", []):
        if nom not in regles:
            E(f"règle « {nom} » : définie nulle part (REGLES)")
            continue
        g, op, dr, desc = regles[nom][:4]
        if op not in ("<", "<=", "=", ">=", ">", "!="):
            E(f"règle « {nom} » : opérateur « {op} » inconnu")
        for cote in (g, dr):
            if not _lisible(cote):
                E(f"règle « {nom} » : expression illisible « {cote} »")
                continue
            hors = sorted(F.codes_cites(cote) - places)
            if hors:
                E(f"règle « {nom} » : cite des KPI absents du modèle : " + ", ".join(hors))
        if strict and (regles_propres is None or nom in regles_propres) and not (texte_langue(desc, "fr") and texte_langue(desc, "en") and len(regles[nom]) > 4 and regles[nom][4]):
            E(f"règle « {nom} » : description (fr, en) et nom anglais obligatoires")

    # ------------------------------------------------ couverture de la norme
    if couverture is not None:
        _controler_couverture(couverture, els, kpis, r, E, A)
    elif strict:
        E("fichier de couverture absent (<nom>_coverage.csv à côté du modèle)")

    r.chiffres.update({
        "kpi": len(places), "calcules": sum(1 for c in places if c in kpis and kpis[c]["type"] == "Calculé"),
        "textes": sum(1 for c in places if c in kpis and formats.get(kpis[c]["reponse"]) in ("texte", "tableau")),
        "facultatifs": sum(1 for *_, o in els if not o), "themes": len(ths), "regles": len(socle.get("regles", []))})
    return r


def controler_libelles(socle, E):
    """Nom, description et thématique du modèle dans les fichiers de langue (libelles/referentiels.<langue>.json) : le
    français et l'anglais identiques au modèle, l'espagnol traduit (les paquets ne portent que le français et l'anglais)."""
    from parametres import libelles as LB

    for lg in ("fr", "en", "es"):
        table = LB.table(lg)
        for champ in ("nom", "description", "thematique"):
            cle = f"referentiels.socle.{socle['code'].lower()}.{champ}"
            attendu = socle[champ][0 if lg == "fr" else 1] if lg in ("fr", "en") and isinstance(socle.get(champ), tuple) else None
            if not table.get(cle):
                E(f"libelles/referentiels.{lg}.json : clé « {cle} » absente")
            elif attendu is not None and table[cle] != attendu:
                E(f"libelles/referentiels.{lg}.json : « {cle} » différent du modèle")


def _lisible(expression):
    try:
        F.references(expression)
        return True
    except F.FormuleInvalide:
        return False


def _controler_kpi(c, d, kpis, formats, types_saisie, unites, non_numeriques, graphe, places, strict, E, A):
    if not CODE_KPI.match(c):
        E(f"{c} : code invalide (30 caractères au plus, sans espace, crochet ni @)")
    if not (str(d.get("fr", "")).strip() and str(d.get("en", "")).strip()):
        E(f"{c} : nom français et anglais obligatoires")
    for lg in ("fr", "en"):
        if len(str(d.get(lg, ""))) > 300:
            E(f"{c} : nom {lg} trop long (300 caractères au plus)")
    comportement = types_saisie.get(d["type"])
    fmt = formats.get(d["reponse"])
    if comportement is None:
        E(f"{c} : type de saisie « {d['type']} » inconnu ({', '.join(types_saisie)})")
        return
    if fmt is None:
        E(f"{c} : type de réponse « {d['reponse']} » inconnu ({', '.join(formats)})")
        return
    if d["unite"] and d["unite"] not in unites:
        E(f"{c} : unité « {d['unite']} » inconnue (UNITES)")
    if fmt in ("pourcentage", "oui_non", "liste", "texte", "tableau") and d["unite"]:
        E(f"{c} : pas d'unité pour un {fmt} (pourcentage stocké en fraction, affiché en %)")
    if fmt == "nombre" and not d["unite"]:
        A(f"{c} : nombre sans unité")
    if d["agregation"] not in AGREGATIONS:
        E(f"{c} : agrégation « {d['agregation']} » inconnue ({', '.join(AGREGATIONS)})")
    if d["temps"] not in TEMPS:
        E(f"{c} : agrégation dans le temps « {d['temps']} » inconnue")
    if d.get("niveau", "") not in NIVEAUX_CONSEILLES:
        E(f"{c} : niveau conseillé « {d['niveau']} » inconnu ({', '.join(n for n in NIVEAUX_CONSEILLES if n)})")
    if d.get("confidentialite", "") not in ("", "Restreint", "Confidentiel"):
        E(f"{c} : confidentialité « {d['confidentialite']} » inconnue (Restreint, Confidentiel ou rien)")
    # mêmes règles que KPI.erreurs_regles (fiche KPI)
    calcule, herite = comportement == "calcul", comportement == "herite"
    if calcule:
        if not d["formule"].strip():
            E(f"{c} : KPI calculé sans formule")
        if fmt not in ("nombre", "pourcentage"):
            E(f"{c} : un KPI calculé donne un nombre ou un pourcentage")
    elif d["formule"].strip():
        E(f"{c} : formule sur un KPI qui n'est pas calculé")
    ag = d["agregation"]
    if herite and ag != "Aucune":
        E(f"{c} : un paramètre hérité (facteur) a l'agrégation « Aucune »")
    elif ag == "Formule" and not calcule:
        E(f"{c} : l'agrégation « Formule » est réservée aux KPI calculés")
    elif fmt in ("texte", "tableau") and ag != "Aucune":
        E(f"{c} : un texte rédigé ou un tableau a l'agrégation « Aucune »")
    elif ag == "Somme" and fmt != "nombre":
        E(f"{c} : « Somme » seulement pour un nombre (pourcentage : « Formule » ou « Aucune » ; oui / non, liste : « Décompte »)")
    elif ag == "Décompte" and fmt in ("nombre", "pourcentage"):
        E(f"{c} : « Décompte » seulement pour un oui / non ou une liste")
    if fmt in ("texte", "tableau") and d["temps"] not in ("", "aucune"):
        E(f"{c} : un texte rédigé se saisit à chaque fréquence (agrégation dans le temps « aucune »)")
    if fmt in ("oui_non", "liste") and d["temps"] in ("somme", "moyenne"):
        E(f"{c} : un oui / non ou une liste ne s'additionne pas dans le temps (« derniere »)")
    if d["decimales"] is not None and not (isinstance(d["decimales"], int) and 0 <= d["decimales"] <= 10):
        E(f"{c} : décimales entre 0 et 10")
    if calcule and d["formule"].strip():
        try:
            verifier_formule(c, d["formule"], kpis_existants=set(kpis), graphe=graphe, non_numeriques=non_numeriques)
        except ValidationError as e:
            E(f"{c} : formule refusée : {' '.join(e.messages)}")
        else:
            hors = sorted(F.codes_cites(d["formule"]) - places)
            if hors:
                E(f"{c} : sources de la formule absentes du modèle (les placer dans l'arbre) : " + ", ".join(hors))
    # définition
    if strict:
        for cat in ("description", "a_inclure", "a_exclure", "source"):
            v = d.get(cat)
            if v and not (isinstance(v, tuple) and len(v) == 2 and all(x.strip() for x in v)):
                E(f"{c} : {cat} en couple (français, anglais)")
        if not d.get("description"):
            E(f"{c} : définition (description) obligatoire")
        if not calcule and not herite and fmt in ("nombre", "tableau") and not d.get("source"):
            A(f"{c} : source des données conseillée (où le contributeur trouve la valeur)")


def lire_couverture(chemin, modele=None):
    """Colonnes, lignes et numéro de chaque ligne dans le fichier (les lignes vides sont sautées). Un fichier partagé par
    plusieurs modèles (colonne ``template``, inventaire maître des ESRS) ne rend que les lignes du modèle ``modele``."""
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lecteur = csv.DictReader(f)
        lignes, numeros = [], []
        for ligne in lecteur:
            lignes.append(ligne)
            numeros.append(lecteur.line_num)
        colonnes = tuple(lecteur.fieldnames or ())
    if modele is not None and "template" in colonnes:
        garde = [i for i, ligne in enumerate(lignes) if (ligne.get("template") or "").strip() == modele]
        lignes, numeros = [lignes[i] for i in garde], [numeros[i] for i in garde]
    return colonnes, lignes, numeros


def _controler_couverture(chemin, els, kpis, r, E, A):
    if not chemin.exists():
        E(f"fichier de couverture absent : {chemin.name}")
        return
    colonnes, lignes, numeros = lire_couverture(chemin, r.code)
    if colonnes and colonnes[:len(COLONNES_COUVERTURE)] != COLONNES_COUVERTURE:
        E(f"{chemin.name} : colonnes attendues {', '.join(COLONNES_COUVERTURE)}")
        return
    if not lignes:
        E(f"{chemin.name} : aucune exigence listée" + (f" pour {r.code}" if "template" in colonnes else ""))
        return
    obligatoires = {c: o for c, _, _, o in els}
    cites, refs, compte = set(), set(), {s: 0 for s in STATUTS_COUVERTURE}
    for n, ligne in zip(numeros, lignes):
        ou = f"{chemin.name}, ligne {n}"
        if None in ligne:
            E(f"{ou} : trop de colonnes (mettre entre guillemets un texte qui contient une virgule)")
            continue
        ref, exigence, statut = (ligne.get(k, "").strip() for k in ("reference", "requirement", "status"))
        codes = (ligne.get("kpi_codes") or "").split()
        note = (ligne.get("note") or "").strip()
        if not ref or not (ligne.get("datapoint") or "").strip():
            E(f"{ou} : référence et exigence (datapoint) obligatoires")
        if ref in refs:
            E(f"{ou} : référence « {ref} » listée deux fois")
        refs.add(ref)
        if exigence not in EXIGENCES:
            E(f"{ou} : requirement « {exigence} » inconnu ({', '.join(EXIGENCES)})")
        if statut not in STATUTS_COUVERTURE:
            E(f"{ou} : status « {statut} » inconnu ({', '.join(STATUTS_COUVERTURE)})")
            continue
        compte[statut] += 1
        if statut == "todo":
            E(f"{ou} : « {ref} » encore à traiter (todo)")
        if statut in ("covered", "partial"):
            if not codes:
                E(f"{ou} : « {ref} » couvert sans KPI (kpi_codes)")
            for c in codes:
                if c not in obligatoires:
                    E(f"{ou} : {c} n'est pas dans l'arbre du modèle")
                elif exigence == "mandatory" and not obligatoires[c]:
                    E(f"{ou} : {c} répond à une exigence obligatoire mais est facultatif dans le modèle")
                elif exigence == "voluntary" and obligatoires[c]:
                    A(f"{ou} : {c} répond à une exigence facultative (« may ») mais est obligatoire dans le modèle")
            cites.update(codes)
        if statut == "automatic" and codes:
            E(f"{ou} : « {ref} » rempli automatiquement mais avec des KPI (les mettre en « covered »)")
        if statut in ("partial", "automatic", "out_of_scope") and not note:
            E(f"{ou} : « {ref} » {statut} sans explication (note)")
        if statut == "out_of_scope" and codes:
            E(f"{ou} : « {ref} » hors périmètre mais avec des KPI")
    sans_exigence = sorted(c for c in obligatoires if c not in cites and kpis.get(c, {}).get("type") == "Saisi")
    if sans_exigence:
        A("KPI saisis qui ne répondent à aucune exigence de la norme (données de calcul ?) : " + ", ".join(sans_exigence))
    total = len(lignes)
    r.chiffres["couverture"] = {**compte, "total": total,
                                "taux": round(100 * (compte["covered"] + compte["partial"] + compte["automatic"]) / total) if total else 0}
    _controler_correspondance(chemin, lignes, r, E)


def _controler_correspondance(chemin, lignes, r, E):
    """Correspondance facultative avec une liste de points de données tierce (``<nom>_efrag.csv`` à côté du fichier de
    couverture, colonnes ``reference``, ``efrag_id``) : tenue dans l'atelier seulement, elle n'est jamais publiée (les
    documents de l'EFRAG ne sont pas réutilisables). Quand elle est là, chaque point de la liste renvoie à une ligne du
    modèle qui est couverte : la couverture à 100 % vaut aussi contre la liste."""
    interne = chemin.with_name(chemin.stem + "_efrag.csv")
    if not interne.exists():
        return
    with open(interne, encoding="utf-8-sig", newline="") as f:
        correspondance = [c for c in csv.DictReader(f) if c.get("reference")]
    statuts = {(ligne.get("reference") or "").strip(): (ligne.get("status") or "").strip() for ligne in lignes}
    ids = [c["efrag_id"].strip() for c in correspondance if (c.get("efrag_id") or "").strip()]
    if len(ids) != len(set(ids)):
        E(f"{interne.name} : un point de la liste renvoie à plusieurs lignes")
    points = 0
    for c in correspondance:
        ref, point = c["reference"].strip(), (c.get("efrag_id") or "").strip()
        if ref not in statuts:
            continue  # ligne d'un autre modèle de la famille
        if point:
            points += 1
            if statuts[ref] not in ("covered", "partial", "automatic"):
                E(f"{interne.name} : le point {point} renvoie à « {ref} », qui n'est pas couverte")
    absentes = sorted(set(statuts) - {c["reference"].strip() for c in correspondance})
    if absentes:
        E(f"{interne.name} : lignes du modèle sans correspondance : {', '.join(absentes[:5])}")
    r.chiffres["liste_tierce"] = points


def controler_tout():
    """Rapports de tous les modèles de la bibliothèque, et conflits de définition entre fichiers."""
    from . import definitions as D

    modules = {m.__name__.rsplit(".", 1)[-1]: m for m in D.charger()}
    rapports = []
    for s in S.SOCLES:
        m = modules.get(s.get("module"))
        r = controler(s, couverture=D.couverture(m) if m else None, propres=set(getattr(m, "KPIS", {})) if m else None,
                      regles_propres=set(getattr(m, "REGLES", {})) if m else None)
        if r.ok and not S.CONFLITS:
            from collecte import paquets as P

            controler_version(s, P.BIBLIOTHEQUE / s["fichier"], r)
        rapports.append(r)
    controler_unites(rapports)
    return S.CONFLITS, rapports


# Unités qu'une installation a pu créer à la main, aux codes et symboles proches de ceux des modèles (« kgCO2eq/kWh »,
# « tCO2eq/M€ »…) : celles de l'ancienne démo à trois niveaux, retirée, gardées pour ce contrôle et pour son
# jeu d'essai (collecte/aides_tests/jeu_trois_niveaux.py). Code, symbole, libellé, nombre entier, décimales, famille.
UNITES_REGLEES_A_LA_MAIN = [
    ("kWh", "kWh", "kilowattheure", False, 0, "Énergie"), ("m³", "m³", "mètre cube", False, 0, "Volume"),
    ("kgCO2eq", "kgCO2eq", "kilogramme équivalent CO2", False, 0, "Émissions"),
    ("kgCO2eq/kWh", "kgCO2eq/kWh", "facteur d'émission", False, 3, "Émissions"),
    ("tCO2eq/M€", "tCO2eq/M€", "intensité carbone", False, 1, "Émissions"), ("t", "t", "tonne", False, 1, "Masse"),
    ("accidents", "accidents", "nombre d'accidents", True, 0, "Comptage"), ("salariés", "salariés", "salariés", True, 0, "Effectif"),
    ("h", "h", "heure", False, 0, "Durée"), ("M€", "M€", "million d'euros", False, 1, "Monnaie"),
]


def unites_connues():
    """[(origine, [unités en dicts de paquet])] qu'une installation peut déjà avoir quand elle installe un modèle : unités
    de départ (referentiel/0004), catalogue (Paramètres › Unités), unités créées à la main et celles de la démo à deux
    espaces, unités des autres modèles, et celles des socles retirés (une installation existante a pu les
    installer)."""
    import importlib

    from parametres.catalogue_unites import THEMES

    from .socles_retires import SOCLES_RETIRES

    def d(code, symbole, libelle=""):
        return {"code": code, "symbole": {"fr": symbole}, "libelle": {"fr": libelle} if libelle else {}}
    depart = importlib.import_module("referentiel.migrations.0004_fiche_kpi").UNITES_BASE
    groupes = [("unités de départ", [d(s, s, l) for s, l, *_ in depart]),
               ("catalogue", [d(s, s, l) for _, _, unites in THEMES for s, l, *_ in unites])]
    achats = importlib.import_module("collecte.management.commands._achats")
    groupes.append(("démos", [d(code, symbole, libelle)
                              for code, symbole, libelle, *_ in [*UNITES_REGLEES_A_LA_MAIN, *getattr(achats, "UNITES", [])]]))
    for s in S.SOCLES:
        groupes.append((f"modèle {s['code']}", list(S.paquet(s).unites)))
    for s in SOCLES_RETIRES:
        groupes.append((f"modèle retiré {s['code']}", list(S.paquet(s).unites)))
    return groupes


def controler_unites(rapports):
    """Chaque unité d'un modèle, rapprochée comme à l'installation (``parametres.rapprochement_unites``, règle unique)
    parmi les unités qu'une installation peut déjà avoir, reçoit une unité de même symbole, ou est créée :
    jamais une autre unité (« €/h » rangée en « h » avant la mise à jour), ni une unité qui ne diffère que par la casse."""
    from parametres.rapprochement_unites import ecritures, rapprocher_unite, symbole_normalise

    groupes = unites_connues()
    tout = [u for _, unites in groupes for u in unites]
    par_code = {r.code: r for r in rapports}
    for s in S.SOCLES:
        r = par_code.get(s["code"])
        if r is None:
            continue
        for u in S.paquet(s).unites:
            voulu = {symbole_normalise(x) for x in ecritures(u)[1]} or {symbole_normalise(u["code"])}
            for origine, unites in [*groupes, ("toutes", tout)]:
                trouve = rapprocher_unite((u.get("symbole") or {}).values(), unites, code=u["code"])
                if trouve.unite is None:
                    continue
                code, symboles, _ = ecritures(trouve.unite)
                if trouve.casse or not voulu & {symbole_normalise(x) for x in symboles}:
                    r.erreurs.append(f"unité « {u['code']} » rapprochée de « {symboles[0] if symboles else code} » ({origine}) à "
                                     "l'installation : un KPI recevrait une autre unité")
                    break


def controler_version(socle, chemin, r):
    """Version et date face au fichier JSON déjà généré : une nouvelle version a une nouvelle date (erreur) ; un contenu
    changé sans nouvelle version ne sera pas proposé aux installations qui ont déjà le modèle (avertissement)."""
    from collecte import paquets as P

    if not chemin.exists():
        return
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    nouveau = json.loads(P.vers_json(S.paquet(socle)))
    va, vn = (ancien.get("referentiel") or {}), nouveau["referentiel"]
    if va.get("version") != vn.get("version"):
        if va.get("date_version") and va.get("date_version") == vn.get("date_version"):
            r.erreurs.append(f"nouvelle version {vn.get('version')} avec la date de la précédente ({vn.get('date_version')}) : "
                             "changer SOCLE[\"date\"]")
        return

    def sans_date(d):  # les documents sources ne changent pas le contenu du modèle : pas de nouvelle version pour eux
        return {**{k: v for k, v in d.items() if k != "documents"},
                "referentiel": {k: v for k, v in (d.get("referentiel") or {}).items() if k != "date_version"}}
    if sans_date(ancien) != sans_date(nouveau):
        r.avertissements.append(f"contenu changé sans nouvelle version (toujours {vn.get('version')}) : les installations qui "
                                "ont déjà le modèle ne verront pas la mise à jour ; augmenter SOCLE[\"version\"] et la date, "
                                "sauf pour un modèle jamais publié")
    elif va.get("date_version") and va.get("date_version") != vn.get("date_version"):
        r.avertissements.append("date changée sans nouvelle version : la date suit la version")
