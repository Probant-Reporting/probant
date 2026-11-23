"""Paquet référentiel : classeur Excel (écriture, modèle à remplir, exemple)."""
import re
from decimal import Decimal

from openpyxl.worksheet.datavalidation import DataValidation

from parametres import langues as L
from parametres import niveaux as N
from parametres.models import CategorieDescription, ChampPersonnalise, Instance, Langue, TypeReponse, TypeSaisie, Unite
from referentiel.models import KPI, Frequence, Referentiel

from .. import fichiers as X
from ..models import RegleCoherence

from .modele import FORMAT, Paquet, VERSION_FORMAT, texte_dans_langue
from ..configuration import langues_fichier
from .extraction import _textes, _valeurs


# ================================================================= Excel : écriture
# (clé, en-tête, largeur, genre) ; genre : texte, entier, bool, textes (une colonne par langue), valeurs (liste par
# langue, « a ; b »), ref:<genre> (unité, type, niveau : écrit par son nom, comme dans le classeur de configuration ;
# relu par son nom ou son code), ou une classe de choix (libellé écrit, code ou libellé relu).
# Mêmes en-têtes et mêmes valeurs que le classeur de configuration.
COL_THEMES = [("code", "Code", 24, "texte"), ("parent", "Parent", 24, "texte"), ("nom", "Nom", 36, "textes"),
              ("ordre", "Ordre", 7, "entier")]
COL_KPI = [("code", "ID KPI", 14, "texte"), ("libelle", "Nom", 48, "textes"), ("theme", "Thème", 24, "texte"),
           ("type_saisie", "Type de saisie", 14, "ref:type_saisie"), ("type_reponse", "Type de réponse", 14, "ref:type_reponse"),
           ("unite", "Unité", 12, "ref:unite"), ("granularite", "Granularité", 12, "ref:niveau"),
           ("methode_agregation", "Agrégation", 11, KPI.Agregation), ("formule", "Formule", 36, "texte"),
           # colonnes avancées (repliées à droite)
           ("ordre", "Ordre dans le thème", 9, "entier"), ("libelle_local", "Libellé dans le référentiel", 30, "textes"),
           ("obligatoire", "Obligatoire", 10, "bool"), ("dans_referentiel", "Dans le référentiel", 10, "bool"),
           ("decimales", "Décimales", 9, "entier"), ("agregation_temps", "Agrégation dans le temps", 14, KPI.AgregationTemps),
           ("preuve_obligatoire", "Preuve obligatoire", 10, "bool"), ("confidentialite", "Confidentialité", 13, KPI.Confidentialite),
           ("actif", "Actif", 7, "bool"), ("saisie_au_dessus", "Saisie aux niveaux supérieurs", 12, "bool"),
           ("na_compte_zero", "Source N/A comptée comme 0", 12, "bool")]
ESSENTIELLES_KPI = ("code", "libelle", "theme", "type_saisie", "type_reponse", "unite", "granularite", "methode_agregation", "formule")
# Modèle « système existant » : les colonnes utiles pour décrire un référentiel existant (les autres restent lues)
COL_MODELE = ("code", "libelle", "theme", "unite", "type_reponse", "granularite", "methode_agregation")
COL_REGLES = [("nom", "Nom", 32, "texte"), ("description", "Description", 44, "texte"), ("gauche", "Partie gauche", 28, "texte"),
              ("operateur", "Opérateur", 10, RegleCoherence.Operateur), ("droite", "Partie droite", 28, "texte"),
              ("tolerance", "Tolérance (%)", 11, "pourcent"), ("niveau", "Niveau", 12, "ref:niveau"), ("bloquante", "Bloquante", 10, "bool"),
              ("actif", "Active", 7, "bool")]
COL_NIVEAUX = [("code", "Code", 14, "texte"), ("rang", "Rang", 7, "entier"), ("nom", "Nom", 20, "textes"),
               ("nom_pluriel", "Nom au pluriel", 20, "textes")]
COL_UNITES = [("code", "Code", 14, "texte"), ("symbole", "Symbole", 14, "textes"), ("libelle", "Libellé", 26, "textes"),
              ("entier", "Nombre entier", 10, "bool"), ("decimales", "Décimales", 9, "entier"), ("famille", "Famille", 16, "texte")]
COL_TYPES_SAISIE = [("code", "Code", 14, "texte"), ("libelle", "Libellé", 22, "textes"), ("abrege", "Étiquette courte", 14, "textes"),
                    ("couleur", "Couleur", 10, "texte"), ("comportement", "Comportement", 18, TypeSaisie.Comportement)]
COL_TYPES_REPONSE = [("code", "Code", 14, "texte"), ("libelle", "Libellé", 22, "textes"), ("format", "Format", 16, TypeReponse.Format),
                     ("valeurs", "Valeurs possibles", 36, "valeurs"), ("colonnes", "Colonnes (tableau)", 36, "json")]
COL_CATEGORIES = [("code", "Code", 16, "texte"), ("libelle", "Libellé", 26, "textes"), ("ordre", "Ordre", 7, "entier"),
                  ("affichee", "Affichée au contributeur", 12, "bool"), ("obligatoire", "Obligatoire", 10, "bool")]
COL_CHAMPS = [("code", "Code", 16, "texte"), ("libelle", "Libellé", 26, "textes"), ("type", "Type", 14, ChampPersonnalise.Type),
              ("valeurs", "Valeurs possibles", 36, "valeurs")]
COL_LANGUES = [("code", "Code", 10, "texte"), ("libelle", "Libellé", 18, "texte")]
REGLAGES = [  # (onglet, attribut du paquet, colonnes)
    ("Niveaux", "niveaux", COL_NIVEAUX), ("Unités", "unites", COL_UNITES), ("Types de saisie", "types_saisie", COL_TYPES_SAISIE),
    ("Types de réponse", "types_reponse", COL_TYPES_REPONSE), ("Catégories", "categories", COL_CATEGORIES),
    ("Champs", "champs", COL_CHAMPS), ("Langues", "langues", COL_LANGUES),
]
CHAMPS_REFERENTIEL = [  # (clé, libellé de la ligne, genre) de l'onglet Référentiel (une ligne par champ)
    ("code", "Code", "texte"), ("identifiant", "Identifiant", "texte"), ("nom", "Nom", "textes"), ("description", "Description", "textes"), ("version", "Version", "texte"),
    ("date_version", "Date de la version", "date"), ("origine", "Origine", "origine"), ("frequence", "Fréquence", Frequence), ("mois_debut", "Mois de début d'exercice", "entier"),
    ("comparaison", "Comparaison", Referentiel.Comparaison), ("couleur", "Couleur", "texte"),
]
CHAMPS_MODELE = ("code", "nom", "description", "frequence", "mois_debut", "comparaison")  # onglet Référentiel du modèle
AUTRES_LIGNES_REFERENTIEL = ("Format", "Langue de référence", "Exporté le", "Exporté de")
SUFFIXE = re.compile(r"^\s*(?P<base>.+?)\s*\((?P<langue>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?)\)\s*$")
# références écrites par leur nom : (attribut du paquet, champs dont le texte sert de nom, le premier étant écrit)
REFERENCES = {"niveau": ("niveaux", ("nom", "nom_pluriel")), "type_saisie": ("types_saisie", ("libelle", "abrege")),
              "type_reponse": ("types_reponse", ("libelle",)), "unite": ("unites", ("symbole", "libelle"))}


def _colonnes(specs, langues):
    """Colonnes réelles : un texte traduisible devient une colonne par langue (« Nom (FR) », « Nom (EN) »…)."""
    sortie = []
    for cle, entete, largeur, genre in specs:
        if genre in ("textes", "valeurs"):
            sortie += [((cle, lg), f"{entete} {L.suffixe(lg)}", largeur, genre) for lg in langues]
        else:
            sortie.append(((cle, None), entete, largeur, genre))
    return sortie


def noms_references(p):
    """{genre: {code: texte écrit}} : le nom d'un niveau, le libellé d'un type, le symbole d'une unité, dans la langue de
    référence du paquet ; le code quand ce nom est ambigu (porté par deux réglages, ou égal au code d'un autre)."""
    lg = p.langue_reference
    sortie = {}
    for genre, (attr, champs) in REFERENCES.items():
        objets = getattr(p, attr)
        noms = {o["code"]: texte_dans_langue(o.get(champs[0]), lg, lg) or o["code"] for o in objets}
        compte = {}
        for n in noms.values():
            compte[n] = compte.get(n, 0) + 1
        codes = {o["code"] for o in objets}
        sortie[genre] = {c: n if compte[n] == 1 and (n == c or n not in codes) else c for c, n in noms.items()}
    return sortie


def codes_references(p):
    """{genre: fonction texte → code du paquet} : relit un niveau, un type, une unité écrits par leur code ou leur nom
    (dans n'importe quelle langue). Un texte inconnu du paquet est gardé tel quel (réglage de l'installation)."""
    lecteurs = {}
    for genre, (attr, champs) in REFERENCES.items():
        objets = getattr(p, attr)
        codes, exacts, normalises = {o["code"] for o in objets}, {}, {}
        for o in objets:
            for ch in champs:
                for t in (o.get(ch) or {}).values():
                    if t:
                        exacts.setdefault(t, o["code"])
                        if X.normaliser(t):
                            normalises.setdefault(X.normaliser(t), o["code"])

        def lire_(v, codes=codes, exacts=exacts, normalises=normalises, objets=objets, genre=genre):
            t = X.texte(v)
            if not t or t in codes:
                return t
            if genre == "unite":  # symbole exact, code ou traduction ; jamais une forme sans symboles
                from parametres.rapprochement_unites import rapprocher_unite

                u = None if t in exacts else rapprocher_unite([t], objets, casse=False).unite
                return exacts.get(t) or (u["code"] if u else t)
            return exacts.get(t) or normalises.get(X.normaliser(t)) or t
        lecteurs[genre] = lire_
    return lecteurs


def _cellule(d, cle, langue, genre, noms=None):
    v = d.get(cle)
    if genre == "textes":
        return (v or {}).get(langue, "")
    if genre == "valeurs":
        return " ; ".join((v or {}).get(langue, []))
    if genre == "bool":
        return "" if v is None else ("Oui" if v else "Non")
    if genre == "pourcent":
        return X.nombre(Decimal(str(v or 0)) * 100)
    if genre == "origine":
        return Referentiel.LIBELLES_ORIGINE.get(v, v or "")
    if genre == "json":  # colonnes d'un tableau
        import json

        return json.dumps(v, ensure_ascii=False) if v else ""
    if genre == "date":  # date de la version : AAAA-MM-JJ, lisible dans toutes les langues
        return v.isoformat() if hasattr(v, "isoformat") else (v or "")
    if isinstance(genre, str) and genre.startswith("ref:"):
        return (noms or {}).get(genre[4:], {}).get(v, v) if v not in (None, "") else ""
    if isinstance(genre, type):
        try:
            return genre(v).label if v not in (None, "") else ""
        except ValueError:
            return v
    if isinstance(v, dict):  # texte par langue dans une colonne à une langue (nom, explication d'une règle) : le premier
        return next((t for t in v.values() if t), "")
    return "" if v is None else v


def _onglet(wb, nom, specs, lignes, langues, listes=None, langue="fr", noms=None, cles=("code",), figer=2, avancees=None,
            role="remplir"):
    """Onglet aux règles communes : en-têtes dans la langue du fichier, clés grises, cellules modifiables jaunes, largeurs,
    filtre, listes déroulantes (``listes`` : {clé de colonne, « bool » ou nom d'une classe de choix: plage de l'onglet
    Listes}) ; ``avancees`` : colonnes (clé, langue) regroupées et repliées à droite."""
    cols = _colonnes(specs, langues)
    if avancees is not None:
        cols = [c for c in cols if c[0] not in avancees] + [c for c in cols if c[0] in avancees]
    roles = ["cle" if cle in cles else role for (cle, _), _, _, _ in cols]
    ws = X.onglet_donnees(wb, nom, [(e, t) for _, e, t, _ in cols],
                          [[_cellule(d, cle, lg, g, noms) for (cle, lg), _, _, g in cols] for d in lignes], roles, langue, figer)
    if avancees:
        X.replier_colonnes(ws, len(cols) - sum(1 for c in cols if c[0] in avancees) + 1, len(cols))
    fin = max(len(lignes) + 300, 500)
    listes = listes or {}
    for j, ((cle, _), _, _, genre) in enumerate(cols, start=1):
        source = listes.get(cle) or (listes.get("bool") if genre == "bool" else None)
        if source is None and isinstance(genre, type):
            source = listes.get(genre.__name__)
        if source:
            dv = DataValidation(type="list", formula1=source, allow_blank=True)
            dv.add(f"{X.get_column_letter(j)}2:{X.get_column_letter(j)}{fin}")
            ws.add_data_validation(dv)
    return ws


def _listes(wb, p, langue="fr", noms=None):
    """Onglet Listes : valeurs des listes déroulantes (noms des réglages du paquet, choix fixes) ; renvoie {nom: plage},
    avec les colonnes qui s'y réfèrent (granularité, parent…)."""
    nom_onglet = X.nom_onglet("Listes", langue)
    ws = wb.create_sheet(nom_onglet)
    noms = noms or noms_references(p)
    rangs = sorted(p.niveaux, key=lambda n: n.get("rang") or 0)
    colonnes = [
        ("bool", "Oui / Non", ["Oui", "Non"]),
        ("type_saisie", "Type de saisie", [noms["type_saisie"][t["code"]] for t in p.types_saisie]),
        ("type_reponse", "Type de réponse", [noms["type_reponse"][t["code"]] for t in p.types_reponse]),
        ("unite", "Unité", [noms["unite"][u["code"]] for u in p.unites]),
        ("niveau", "Niveau", [noms["niveau"][n["code"]] for n in rangs]),
        ("theme", "Thème", [t["code"] for t in p.themes]),
        ("Agregation", "Agrégation", [l for _, l in KPI.Agregation.choices]),
        ("AgregationTemps", "Agrégation dans le temps", [l for _, l in KPI.AgregationTemps.choices]),
        ("Confidentialite", "Confidentialité", [l for _, l in KPI.Confidentialite.choices]),
        ("Frequence", "Fréquence", [l for _, l in Frequence.choices]),
        ("Comparaison", "Comparaison", [l for _, l in Referentiel.Comparaison.choices]),
        ("Origine", "Origine", list(Referentiel.LIBELLES_ORIGINE.values())),
        ("Operateur", "Opérateur", [l for _, l in RegleCoherence.Operateur.choices]),
        ("Comportement", "Comportement", [l for _, l in TypeSaisie.Comportement.choices]),
        ("Format", "Format", [l for _, l in TypeReponse.Format.choices]),
        ("Type", "Type de champ", [l for _, l in ChampPersonnalise.Type.choices]),
    ]
    plages = {}
    for j, (cle, titre, valeurs) in enumerate(colonnes, start=1):
        X.style_entete(ws.cell(1, j, X.entete(titre, langue)), "info")
        for i, v in enumerate(valeurs, start=2):
            X.ecrire_cellule(ws, i, j, v)
        col = X.get_column_letter(j)
        place = len(valeurs) + (200 if cle in ("unite", "theme", "type_reponse", "type_saisie", "niveau") else 0)  # place pour en ajouter
        plages[cle] = f"={nom_onglet}!${col}$2:${col}${max(place, 1) + 1}"
    X.largeurs(ws, [18] * len(colonnes))
    ws.freeze_panes = "A2"
    plages.update(granularite=plages["niveau"], parent=plages["theme"])
    return plages


A_LIRE = {
    "fr": [
        "# Comment s'en servir",
        ("Modifier", "Les cellules jaunes se modifient ; les clés grises (codes) relient chaque ligne : ne pas les modifier. "
                     "Mêmes colonnes et mêmes valeurs que le classeur de configuration (types, unités et niveaux par leur nom)."),
        ("Importer", "Administration › Référentiels et KPI › Ajouter un référentiel › Importer un fichier (ou, pour une nouvelle version, "
                     "la page Versions et partage du référentiel) : l'aperçu montre ce qui sera créé, modifié, en conflit ou "
                     "rejeté, et les réglages repris ou créés, avant d'enregistrer."),
        ("Codes déjà utilisés", "Un KPI dont l'ID existe déjà se réutilise (le même KPI, une seule valeur saisie), se renomme ou "
                                "s'ignore."),
        ("Rien n'est supprimé", "Une cellule vide ne retire rien ; un KPI ou un thème absent reste, sauf demande explicite."),
        ("Onglet KPI", "L'essentiel d'abord ; les colonnes avancées sont regroupées à droite : bouton « + » au-dessus des colonnes."),
        ("Formules", "Codes entre crochets : [CODE] / [AUTRE] * 1000 ; [CODE@N-1] = même période l'an dernier ; [CODE@P-1] = "
                     "période précédente."),
        "# Onglets",
        ("Référentiel", "Une ligne par information : code, nom et description par langue, version, fréquence, mois de début "
                        "d'exercice, comparaison, couleur."),
        ("Thèmes", "Arbre des thèmes : code (clé), parent (code du thème au-dessus, vide au sommet), nom par langue, ordre."),
        ("KPI", "Une ligne par KPI dans l'ordre du référentiel ; « Dans le référentiel » = Non pour un KPI qui sert seulement "
                "dans une formule."),
        ("Règles de cohérence", "Contrôles entre KPI ; tolérance en % (1 = 1 %)."),
        ("Niveaux, Unités, Types, Catégories, Champs", "Réglages utilisés : à l'import, chacun est relié à celui de l'installation "
                                                        "(même code, même nom) ou créé."),
    ],
    "en": [
        "# How to use it",
        ("Edit", "Yellow cells can be changed; grey keys (codes) link each row: do not change them. Same columns and values as "
                 "the configuration workbook (types, units and levels by their name)."),
        ("Import", "Administration › Frameworks and KPIs › Add a framework › Import a file (or, for a new version, the framework's Versions "
                   "and sharing page): the preview shows what will be created, changed, in conflict or rejected, and the settings "
                   "reused or created, before saving."),
        ("Codes already used", "A KPI whose ID already exists is reused (same KPI, one value), renamed or skipped."),
        ("Nothing is deleted", "An empty cell removes nothing; a missing KPI or theme stays, unless explicitly asked."),
        ("KPI sheet", "Essentials first; advanced columns are grouped on the right: “+” button above the columns."),
        ("Formulas", "Codes in square brackets: [CODE] / [OTHER] * 1000; [CODE@N-1] = same period last year; [CODE@P-1] = "
                     "previous period."),
        "# Sheets",
        ("Framework", "One row per item: code, name and description per language, version, frequency, fiscal year start month, "
                      "comparison, colour."),
        ("Themes", "Theme tree: code (key), parent (code of the theme above, empty at the top), name per language, order."),
        ("KPI", "One row per KPI in the framework order; “In the framework” = No for a KPI only used in a formula."),
        ("Consistency rules", "Checks between KPIs; tolerance in % (1 = 1%)."),
        ("Levels, Units, Types, Categories, Fields", "Settings used: on import, each one is linked to the installation's (same "
                                                      "code, same name) or created."),
    ],
}
A_LIRE_MODELE = {
    "fr": [
        "# Décrire son système existant",
        ("1. Référentiel", "Onglet Référentiel : code (court, sans espace), nom, fréquence, mois de début d'exercice."),
        ("2. KPI", "Onglet KPI, une ligne par indicateur : ID, nom, thème (son nom : il sera créé), unité, type de réponse, "
                   "granularité (niveau de saisie), agrégation entre organisations, définition. Seuls l'ID et le nom sont "
                   "obligatoires ; sans granularité, l'outil choisit le niveau (le plus bas de l'arbre pour une saisie). "
                   "Choisir dans les listes déroulantes."),
        ("Exemple", "L'onglet « Exemple – KPI » montre un référentiel rempli ; il n'est pas importé."),
        ("3. Importer", "Administration › Référentiels et KPI › Ajouter un référentiel › Importer un fichier : l'aperçu signale ce qui "
                        "manque avant d'enregistrer."),
        ("Pour aller plus loin", "Toutes les colonnes du fichier référentiel complet sont aussi reconnues (formule, type de "
                                 "saisie, décimales…) : les ajouter avec leur en-tête si besoin."),
    ],
    "en": [
        "# Describe your existing system",
        ("1. Framework", "Framework sheet: code (short, no space), name, frequency, fiscal year start month."),
        ("2. KPI", "KPI sheet, one row per indicator: ID, name, theme (its name: it will be created), unit, answer type, "
                   "granularity (input level), aggregation across organisations, definition. Only the ID and name are required; "
                   "without a granularity, the tool picks the level (the lowest of the tree for an input). Pick from the "
                   "drop-down lists."),
        ("Example", "The “Example – KPI” sheet shows a filled framework; it is not imported."),
        ("3. Import", "Administration › Frameworks and KPIs › Add a framework › Import a file: the preview shows what is missing before "
                      "saving."),
        ("Going further", "All columns of the full framework file are also read (formula, input type, decimals…): add them with "
                          "their header if needed."),
    ],
}


def classeur(p, vierge=False, langue=None):
    """Classeur Excel d'un fichier référentiel (``vierge`` : modèle « système existant », simplifié, avec un exemple)."""
    langue = langue or L.courante()
    with L.session():
        return _modele(p, langue) if vierge else _classeur(p, langue)


def _feuille_referentiel(wb, p, langues, listes, langue, champs=None):
    """Onglet Référentiel : une ligne par information (libellé gris, valeur jaune)."""
    lignes = [] if champs is not None else [["Format", f"{FORMAT} {VERSION_FORMAT}"]]
    for cle, libelle, genre in CHAMPS_REFERENTIEL:
        if champs is not None and cle not in champs:
            continue
        if genre == "textes":
            for lg in langues:
                lignes.append([X.entete(f"{libelle} {L.suffixe(lg)}", langue), (p.referentiel.get(cle) or {}).get(lg, "")])
        else:
            lignes.append([X.entete(libelle, langue), _cellule(p.referentiel, cle, None, genre)])
    if champs is None:
        lignes.append([X.entete("Langue de référence", langue), p.langue_reference])
        if p.exporte_le:
            lignes += [[X.entete("Exporté le", langue), p.exporte_le], [X.entete("Exporté de", langue), p.exporte_de]]
    ws = X.onglet_donnees(wb, "Référentiel", [("Information", 30), ("Valeur", 70)], lignes, ["cle", "remplir"], langue, 2, index=0)
    ws.auto_filter.ref = None
    for i in range(2, ws.max_row + 1):
        ws.cell(i, 2).alignment = X.Alignment(horizontal="left", vertical="top", wrap_text=True)
    for cle, liste in (("Frequence", "Fréquence"), ("Comparaison", "Comparaison"), ("Origine", "Origine")):
        ligne = next((r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == X.entete(liste, langue)), None)
        if ligne:
            dv = DataValidation(type="list", formula1=listes[cle], allow_blank=True)
            dv.add(f"B{ligne}")
            ws.add_data_validation(dv)
    return ws


def _classeur(p, langue):
    wb = X.classeur()
    langues = [l["code"] for l in p.langues] or [p.langue_reference]
    noms = noms_references(p)
    listes = _listes(wb, p, langue, noms)
    _feuille_referentiel(wb, p, langues, listes, langue)
    _onglet(wb, "Thèmes", COL_THEMES, p.themes, langues, listes, langue)
    specs = _kpi_specs(p)
    _onglet(wb, "KPI", specs, [_kpi_vers_ligne(k) for k in p.kpis], langues, listes, langue, noms, figer=3,
            avancees=_avancees(specs, langues, p.langue_reference))
    _onglet(wb, "Règles de cohérence", COL_REGLES, p.regles, langues, listes, langue, noms, cles=("nom",))
    fixes = {c: v for c, v in listes.items() if c[:1].isupper() or c == "bool"}
    for nom, attr, specs_ in REGLAGES:
        _onglet(wb, nom, specs_, getattr(p, attr), langues, fixes, langue)
    wb.move_sheet(X.nom_onglet("Listes", langue), offset=len(wb.sheetnames))
    sel = lambda fr, en: X.selon(langue, fr, en)  # noqa: E731
    X.feuille_a_lire(wb, sel("Fichier référentiel", "Framework file") + f" – {p.nom()}", [
        (sel("Référentiel", "Framework"), f"{p.nom()} ({p.code}), version {p.version}"),
        (sel("Contenu", "Content"), sel(f"{p.nb_elements} KPI dans le référentiel, {len(p.kpis) - p.nb_elements} KPI sources de "
                                        f"formules, {len(p.themes)} thèmes, {len(p.regles)} règles de cohérence",
                                        f"{p.nb_elements} KPIs in the framework, {len(p.kpis) - p.nb_elements} formula source KPIs, "
                                        f"{len(p.themes)} themes, {len(p.regles)} consistency rules")),
        (sel("Exporté", "Exported"), sel(f"le {p.exporte_le} depuis « {p.exporte_de} »", f"on {p.exporte_le} from “{p.exporte_de}”")
         if p.exporte_le else "—"),
    ] + A_LIRE["en" if X.anglais(langue) else "fr"], langue)
    return wb


def _avancees(specs, langues, ref):
    """Colonnes (clé, langue) de l'onglet KPI regroupées à droite : tout sauf l'essentiel dans la langue de référence (et
    la première description)."""
    premiere = next((c for c, *_ in specs if c.startswith("desc:")), None)
    return {(c, lg) for (c, lg), *_ in _colonnes(specs, langues)
            if not ((c in ESSENTIELLES_KPI or c == premiere) and lg in (None, ref))}


def _modele(p, langue):
    """Modèle « système existant » : À lire, Référentiel (l'essentiel), KPI (8 colonnes), un exemple, les listes."""
    wb = X.classeur()
    lg = p.langue_reference
    noms = noms_references(p)
    listes = _listes(wb, p, langue, noms)
    _feuille_referentiel(wb, p, [lg], listes, langue, champs=CHAMPS_MODELE)
    specs = _specs_modele(p)
    _onglet(wb, "KPI", specs, [], [lg], listes, langue, noms, figer=3)
    exemple = exemple_paquet(p)
    ws = _onglet(wb, "Exemple – KPI", specs, [_kpi_vers_ligne(k) for k in exemple.kpis], [lg], None, langue, noms, figer=3,
                 role="info")  # pour information : non importé
    ws.sheet_properties.tabColor = "BDBDBD"
    wb.move_sheet(X.nom_onglet("Listes", langue), offset=len(wb.sheetnames))
    sel = lambda fr, en: X.selon(langue, fr, en)  # noqa: E731
    X.feuille_a_lire(wb, sel("Modèle « système existant »", "“Existing system” template") + f" – {Instance.courante().titre}",
                     A_LIRE_MODELE["en" if X.anglais(langue) else "fr"], langue)
    return wb


def _kpi_specs(p):
    """Colonnes de l'onglet KPI : les champs fixes, une colonne par catégorie de description et par langue, une par champ
    personnalisé."""
    specs = list(COL_KPI)
    for c in sorted(p.categories, key=lambda c: (c.get("ordre") or 0, c["code"])):
        specs.append((f"desc:{c['code']}", texte_dans_langue(c.get("libelle"), p.langue_reference, p.langue_reference) or c["code"], 36, "textes"))
    for c in p.champs:
        genre = "bool" if c.get("type") == "case" else "texte"
        specs.append((f"champ:{c['code']}", texte_dans_langue(c.get("libelle"), p.langue_reference, p.langue_reference) or c["code"], 16, genre))
    return specs


def _specs_modele(p):
    """Les 8 colonnes du modèle : ID, nom, thème, unité, type de réponse, granularité, agrégation, définition (première
    catégorie de description)."""
    specs = {s[0]: s for s in _kpi_specs(p)}
    premiere = next((c for c in specs if c.startswith("desc:")), None)
    return [specs[c] for c in COL_MODELE] + ([(premiere, *specs[premiere][1:3], "textes")] if premiere else [])


def _kpi_vers_ligne(k):
    e = k.get("element") or {}
    d = {c: k.get(c) for c in ("code", "libelle", "type_saisie", "type_reponse", "unite", "decimales", "granularite",
                                "methode_agregation", "agregation_temps", "formule", "saisie_au_dessus", "na_compte_zero",
                                "preuve_obligatoire", "confidentialite", "actif")}
    d.update(theme=e.get("theme", ""), ordre=e.get("ordre"), libelle_local=e.get("libelle") or {},
             obligatoire=e.get("obligatoire") if e else None, dans_referentiel=bool(k.get("element") is not None))
    for lg, textes in (k.get("descriptions") or {}).items():
        for cat, t in textes.items():
            d.setdefault(f"desc:{cat}", {})[lg] = t
    for c, v in (k.get("champs") or {}).items():
        d[f"champ:{c}"] = v
    return d


def modele_vierge(langue=None):
    """Modèle « système existant » : paquet vide avec les réglages de l'installation (listes déroulantes) et un exemple."""
    langue = langue or L.courante()
    with L.session():
        langues = langues_fichier()
        p = Paquet(referentiel={"code": "", "nom": {}, "description": {}, "couleur": "#1F5FAD", "frequence": Frequence.ANNEE,
                                "mois_debut": 1, "comparaison": Referentiel.Comparaison.N1, "version": "1.0",
                                "origine": Referentiel.Origine.CREE},
                   langue_reference=langues[0], langues=[{"code": l.code, "libelle": l.libelle} for l in
                                                          sorted(Langue.objects.all(), key=lambda l: langues.index(l.code))])
        p.niveaux = [{"code": n.code, "rang": n.rang, "nom": _textes(n, "nom", langues), "nom_pluriel": _textes(n, "nom_pluriel", langues)}
                     for n in N.tous()]
        p.unites = [{"code": u.code, "symbole": _textes(u, "symbole", langues), "libelle": _textes(u, "libelle", langues),
                     "entier": u.entier, "decimales": u.decimales, "famille": u.famille} for u in Unite.objects.all()]
        p.types_saisie = [{"code": t.code, "libelle": _textes(t, "libelle", langues), "abrege": _textes(t, "abrege", langues),
                           "couleur": t.couleur, "comportement": t.comportement} for t in TypeSaisie.objects.all()]
        p.types_reponse = [{"code": t.code, "libelle": _textes(t, "libelle", langues), "format": t.format,
                            "valeurs": _valeurs(t, langues)} for t in TypeReponse.objects.all()]
        p.categories = [{"code": c.code, "libelle": _textes(c, "libelle", langues), "ordre": c.ordre, "affichee": c.affichee,
                         "obligatoire": c.obligatoire} for c in CategorieDescription.objects.all()]
        p.champs = [{"code": c.code, "libelle": _textes(c, "libelle", langues), "type": c.type, "valeurs": _valeurs(c, langues)}
                    for c in ChampPersonnalise.objects.all()]
        nom = X.nom_fichier(X.selon(langue, "Modele systeme existant", "Existing system template"))
        return X.reponse_excel(classeur(p, vierge=True, langue=langue), nom)


def exemple_paquet(p):
    """Petit référentiel rempli, montré dans le modèle (onglet « Exemple – KPI », non importé)."""
    lg = p.langue_reference
    nombre = next((t["code"] for t in p.types_reponse if t["format"] == "nombre"), "")
    oui_non = next((t["code"] for t in p.types_reponse if t["format"] == "oui_non"), nombre)
    niveaux = sorted(p.niveaux, key=lambda n: n["rang"])
    bas, haut = (niveaux[-1]["code"], niveaux[min(1, len(niveaux) - 1)]["code"]) if niveaux else ("", "")
    unite = next((u["code"] for u in p.unites if (u.get("symbole") or {}).get(lg) == "kWh"), "kWh")
    ex = Paquet(referentiel={}, langue_reference=lg)
    ex.categories, ex.champs = p.categories, []
    premiere = next((c["code"] for c in sorted(p.categories, key=lambda c: (c.get("ordre") or 0, c["code"]))), None)

    def kpi(code, nom, theme, type_reponse, unite_, niveau, agregation, definition=""):
        return {"code": code, "libelle": {lg: nom}, "type_saisie": "", "type_reponse": type_reponse, "unite": unite_,
                "decimales": None, "granularite": niveau, "methode_agregation": agregation, "agregation_temps": "",
                "formule": "", "preuve_obligatoire": False, "confidentialite": "", "actif": True,
                "descriptions": {lg: {premiere: definition}} if premiere and definition else {},
                "champs": {}, "element": {"theme": theme, "ordre": None, "libelle": {}, "obligatoire": True}}
    ex.kpis = [
        kpi("EX-ELEC", "Électricité consommée", "Énergie", nombre, unite, bas, "Somme",
            "Électricité achetée et consommée pendant la période, relevés des compteurs."),
        kpi("EX-GAZ", "Gaz naturel consommé", "Énergie", nombre, unite, bas, "Somme"),
        kpi("EX-EFF", "Effectif au 31/12", "Social", nombre, "", haut, "Somme", "Salariés en CDI et CDD, en personnes physiques."),
        kpi("EX-AT", "Accidents du travail avec arrêt", "Social", nombre, "", bas, "Somme"),
        kpi("EX-ISO", "Certification ISO 14001", "Environnement", oui_non, "", bas, "Décompte"),
    ]
    return ex


def nom_fichier(p, langue=None):
    """Nom explicite d'un fichier référentiel : « Fichier-referentiel_VS_BASE_v1.2_2026-10-27 »."""
    return X.nom_fichier(X.selon(langue or L.courante(), "Fichier referentiel", "Framework file"), p.code or "referentiel",
                         f"v{p.version}")


def reponse_excel(p, langue=None):
    return X.reponse_excel(classeur(p, langue=langue), nom_fichier(p, langue))
