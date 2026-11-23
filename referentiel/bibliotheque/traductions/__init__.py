"""Textes d'une famille de modèles de la bibliothèque dans les cinq langues de l'interface que les définitions ne portent
pas (espagnol, allemand, italien, néerlandais, portugais du Portugal).

Les définitions de ``definitions/`` écrivent leurs textes en français et en anglais (couples (fr, en)). Une famille de
modèles qui a ses traductions les déclare dans son ``SOCLE`` (``"traductions": "esrs"``) : ``socles.paquet`` ajoute alors,
au paquet JSON du modèle, les cinq autres langues, lues dans ``<famille>.<langue>.json`` à côté de ce fichier. Rien de plus
n'est écrit en base que ce que l'installation d'un paquet y met déjà (textes de la langue de référence dans le champ, les
autres dans ``traductions``) ; aucune migration.

Un fichier de langue est un dictionnaire {texte anglais: traduction}. La clé est le texte anglais de la définition, tel que le
paquet le porte : un nom (KPI, thème, colonne ou valeur de liste, règle) en entier, une description phrase par phrase (une phrase
écrite pareil dans plusieurs descriptions est traduite une seule fois : un même terme = une même traduction). Une
description n'est ajoutée à une langue que si toutes ses phrases y sont traduites : on ne mélange jamais deux langues dans un
même paragraphe, le repli sur l'anglais reste entier. Les codes, unités, clés des listes (leurs valeurs françaises) et
références de paragraphes ne changent pas : ce sont les mêmes dans toutes les langues.

Pour savoir ce qui manque : ``python3 manage.py bibliotheque --untranslated <famille> --language <langue>``.
"""
import copy
import json
import re
from functools import lru_cache
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
LANGUES = ("es", "de", "it", "nl", "pt")
LIBELLES_LANGUES = {"es": "Español", "de": "Deutsch", "it": "Italiano", "nl": "Nederlands", "pt": "Português"}
# Une phrase se termine par « . ! ? » suivi d'une espace et d'une majuscule, d'une parenthèse ou d'un guillemet.
FIN_DE_PHRASE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(“\"\[])")


@lru_cache(maxsize=None)
def table(famille, langue):
    """{texte anglais: traduction} d'une famille dans une langue ; vide si le fichier n'existe pas."""
    chemin = DOSSIER / f"{famille}.{langue}.json"
    if not chemin.exists():
        return {}
    return json.loads(chemin.read_text(encoding="utf-8"))


def phrases(texte):
    """Phrases d'une description anglaise (la jointure par une espace redonne le texte)."""
    return FIN_DE_PHRASE.split(texte)


def traduire_nom(famille, langue, anglais):
    return table(famille, langue).get(anglais, "")


def traduire_description(famille, langue, anglais):
    """Description dans une langue, ou une chaîne vide si une de ses phrases n'est pas traduite."""
    tab = table(famille, langue)
    morceaux = [tab.get(p, "") for p in phrases(anglais)]
    return " ".join(morceaux) if all(morceaux) else ""


def _noms(textes, famille, langue):
    """Ajoute la langue à un {langue: texte} d'un nom, d'après son texte anglais."""
    if isinstance(textes, dict) and textes.get("en"):
        t = traduire_nom(famille, langue, textes["en"])
        if t:
            textes[langue] = t


def ajouter(paquet, famille):
    """Ajoute à un paquet de la bibliothèque (``socles.paquet``) les langues de ``LANGUES`` : nom, description et thématique
    du modèle (fichiers de langue ``referentiels.socle.<code>.*``, déjà complets), thèmes, KPI, descriptions, types de
    réponse, valeurs des listes, colonnes des tableaux et règles. Ce qui n'est pas traduit n'est pas ajouté."""
    from parametres import libelles as LB

    code = paquet.referentiel["code"].lower()
    for lg in LANGUES:
        table_lg = LB.table(lg)
        for champ in ("nom", "description", "thematique"):
            texte = table_lg.get(f"referentiels.socle.{code}.{champ}")
            if texte:
                paquet.referentiel[champ][lg] = texte
    paquet.langues = paquet.langues + [{"code": lg, "libelle": LIBELLES_LANGUES[lg]} for lg in LANGUES]
    for lg in LANGUES:
        for t in paquet.themes:
            _noms(t["nom"], famille, lg)
        for k in paquet.kpis:
            _noms(k["libelle"], famille, lg)
            for cat, anglais in (k["descriptions"].get("en") or {}).items():
                texte = traduire_description(famille, lg, anglais)
                if texte:
                    k["descriptions"].setdefault(lg, {})[cat] = texte
        for r in paquet.regles:
            en = (r.get("traductions") or {}).get("en") or {}
            nom = traduire_nom(famille, lg, en.get("nom", ""))
            description = traduire_description(famille, lg, en.get("description", ""))
            if nom or description:
                r.setdefault("traductions", {})[lg] = {c: v for c, v in (("nom", nom), ("description", description)) if v}
    types = []
    for t in paquet.types_reponse:
        t = copy.deepcopy(t)  # les colonnes sont celles du catalogue commun : ne jamais les modifier en place
        for lg in LANGUES:
            _noms(t["libelle"], famille, lg)
            valeurs = t.get("valeurs") or {}
            if valeurs.get("en"):
                liste = [traduire_nom(famille, lg, v) for v in valeurs["en"]]
                if all(liste):
                    valeurs[lg] = liste
            for colonne in t.get("colonnes") or []:
                _noms(colonne.get("libelle"), famille, lg)
        types.append(t)
    paquet.types_reponse = types
    return paquet


def textes_a_traduire(paquet):
    """Textes anglais d'un paquet (avant ``ajouter``) que la famille doit traduire : ([noms], [phrases]), dans l'ordre du
    paquet, sans doublon."""
    noms, morceaux = {}, {}

    def nom(texte):
        if texte:
            noms[texte] = None

    def description(texte):
        for p in phrases(texte or ""):
            morceaux[p] = None
    for t in paquet.themes:
        nom(t["nom"].get("en"))
    for k in paquet.kpis:
        nom(k["libelle"].get("en"))
        for anglais in (k["descriptions"].get("en") or {}).values():
            description(anglais)
    for r in paquet.regles:
        en = (r.get("traductions") or {}).get("en") or {}
        nom(en.get("nom"))
        description(en.get("description"))
    for t in paquet.types_reponse:
        nom(t["libelle"].get("en"))
        for v in (t.get("valeurs") or {}).get("en") or []:
            nom(v)
        for colonne in t.get("colonnes") or []:
            nom((colonne.get("libelle") or {}).get("en"))
    return list(noms), list(morceaux)
