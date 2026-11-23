"""Traductions par fichier (Paramètres › Langues) : exporter ce qui manque (ou tout) dans une langue ou dans toutes,
le faire traduire (à la main, par un prestataire ou une IA), puis réimporter le fichier avec un aperçu des changements.

Une ligne par texte : clé technique (à ne pas modifier), section, élément, texte de départ (langue de référence), puis
une colonne « Traduction (CODE) » par langue. Une traduction vide est ignorée : l'import n'efface jamais un texte.
"""
from dataclasses import dataclass, field

from openpyxl.styles import Alignment

from collecte import fichiers as X

from . import langues as L
from . import traductions as TR
from .libelles import libelle

BASE = ["Clé", "Section", "Élément", "Texte de départ"]
# en-têtes acceptés au réimport : français, anglais et espagnol 
COLONNES = {"cle": ["Clé", "Cle", "Key", "Clave"],
            "source": ["Texte de départ", "Source", "Texte source", "Source text", "Starting text", "Original text",
                       "Texto de partida", "Texto de origen", "Texto original"]}
MOTS_TRADUCTION = ("Traduction", "Translation", "Traducción")


def entete(code):
    return f"Traduction ({code.upper()})"


def consigne_ia(codes):
    noms = ", ".join(f"{L.libelle(c)} → colonne « {entete(c)} »" for c in codes)
    return (f"Traduis chaque texte de la colonne « Texte de départ » ({L.libelle(L.reference())}) dans chaque langue demandée, "
            f"sur la même ligne : {noms}. Ne remplis que les cellules vides de ces colonnes. Ne modifie pas les colonnes "
            "« Clé », « Section », « Élément » ni « Texte de départ », et ne change pas l'ordre des lignes. Garde tels quels "
            "les codes, les symboles d'unités (kWh, tCO2eq, m³…), les nombres et les sigles (GES, CSRD, ESRS…). Style : "
            "professionnel, vocabulaire du reporting d'indicateurs. Rends le fichier complet au même format.")


def _elements(code):
    """{clé: Element} de toutes les sections pour une langue (tous les textes)."""
    return {e.cle: e for section, _ in TR.SECTIONS for e in TR.elements(code, section, tout=True)}


def lignes(codes, tout=False):
    """[[clé, section, élément, texte de départ, traduction langue 1, …]] ; sans ``tout``, seulement les lignes où une
    traduction manque dans au moins une des langues."""
    par_langue = {c: _elements(c) for c in codes}
    sortie = []
    for section, titre in TR.titres_sections():
        for e in TR.elements(codes[0], section, tout=True):
            actuels = [par_langue[c].get(e.cle) for c in codes]
            manque = any(a is not None and not a.actuel and not a.facultatif for a in actuels)
            if tout or manque:
                sortie.append([e.cle, titre, e.quoi, e.source] + [(a.actuel if a else "") for a in actuels])
    return sortie


def exporter(codes, tout=False, format="xlsx"):
    entetes = BASE + [entete(c) for c in codes]
    nom = f"traductions_{'_'.join(codes) if len(codes) < 4 else 'toutes_langues'}_{'tout' if tout else 'a_traduire'}"
    donnees = lignes(codes, tout)
    if format == "csv":
        return X.reponse_csv([entetes] + donnees, nom)
    wb = X.classeur()
    ws = wb.create_sheet("Traductions")
    X.ajouter(ws, entetes)
    for ligne in donnees:
        X.ajouter(ws, ligne)
    X.entetes(ws)
    X.largeurs(ws, [8, 22, 28, 60] + [55] * len(codes))
    ws.freeze_panes = "E2"
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=len(entetes)):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    langues_txt = ", ".join(f"{L.libelle(c)} ({c})" for c in codes)
    X.feuille_lisez_moi(wb, f"Traductions : {langues_txt}", [
        ("Contenu", f"{len(donnees)} texte(s) {'(tous)' if tout else 'à traduire dans au moins une langue'} : noms et "
                    "définitions des KPI, thèmes, niveaux, unités, types, catégories, champs, valeurs des listes."),
        ("À remplir", "Les colonnes « Traduction (…) » de l'onglet Traductions, une par langue. Une cellule vide est ignorée à l'import."),
        ("À ne pas modifier", "La colonne « Clé » (elle relie chaque ligne au bon texte) ; les autres colonnes servent de repère."),
        ("Réimporter", "Administration › Paramètres › Langues : un aperçu montre les changements avant de les enregistrer."),
        "# Avec une IA",
        ("Consigne à donner", consigne_ia(codes)),
    ])
    return X.reponse_excel(wb, nom)


@dataclass
class Analyse:
    code: str = ""
    changements: list = field(default_factory=list)  # [{cle, quoi, source, avant, apres, alerte}]
    inchanges: int = 0
    vides: int = 0
    inconnues: int = 0

    @property
    def libelle(self):
        return L.libelle(self.code)

    @property
    def donnees(self):
        return {c["cle"]: c["apres"] for c in self.changements}

    @property
    def alertes(self):
        return sum(1 for c in self.changements if c["alerte"])


def analyser(fichier, codes, seule=None):
    """Compare le fichier aux traductions actuelles, sans rien enregistrer : ([Analyse par langue trouvée], erreur).
    ``seule`` : page d'une langue, où une colonne « Traduction » sans code vaut pour cette langue."""
    try:
        onglets = X.lire(fichier)
    except X.FichierInvalide as e:
        return [], str(e)
    attendues = {X.normaliser(f"{mot} ({c.upper()})"): c for c in codes for mot in MOTS_TRADUCTION}
    if seule:
        attendues.update({X.normaliser(mot): seule for mot in MOTS_TRADUCTION})
    for rangs in onglets.values():
        debut, cols = X.trouver_colonnes(rangs, COLONNES, ["cle"])
        if debut is None:
            continue
        colonnes_langue = {i: attendues[X.normaliser(h)] for i, h in enumerate(rangs[debut]) if X.normaliser(h) in attendues}
        if not colonnes_langue:
            continue
        analyses = []
        for i, code in colonnes_langue.items():
            a, actuels = Analyse(code), _elements(code)
            for r in rangs[debut + 1:]:
                cel = lambda j: X.texte(r[j]) if j is not None and j < len(r) else ""  # noqa: E731
                cle, apres = cel(cols["cle"]), cel(i)
                if not cle:
                    continue
                e = actuels.get(cle)
                if e is None:
                    a.inconnues += 1
                elif not apres:
                    a.vides += 1
                elif apres == (e.actuel or "").strip():
                    a.inchanges += 1
                else:
                    source = cel(cols.get("source"))
                    alerte = libelle("admin.traductions.alerte_depart") if source and source.strip() != e.source.strip() else ""
                    a.changements.append({"cle": cle, "quoi": e.quoi, "source": e.source, "avant": e.actuel, "apres": apres, "alerte": alerte})
            analyses.append(a)
        return analyses, ""
    return [], libelle("admin.traductions.colonnes_introuvables")
