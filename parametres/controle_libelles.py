"""Contrôle des fichiers de langue de l'interface : une langue est proposée aux personnes seulement si elle est complète. Ajouter une langue = ajouter ses fichiers ``libelles/<zone>.<langue>.json`` :
rien d'autre à écrire dans le code.

Une langue est complète quand, pour chaque zone (``parametres.zones_langue.ZONES``), son fichier existe et a exactement les
clés du fichier de la langue de base (l'anglais), avec pour chaque clé les mêmes paramètres ``{nom}``, les mêmes balises, la
même forme (texte ou pluriel ``{"one", "other"}``) et un texte non vide. Le même contrôle sert au chargement (langues
proposées : ``libelles.langues_disponibles``), aux tests (``parametres/test_controle_libelles.py``) et à l'outil de
traduction (``qa/translation_check.py``).
"""
import json
import re
from pathlib import Path

from . import zones_langue as Z

RACINE = Path(__file__).resolve().parent.parent  # sans réglages Django : utilisable par qa/translation_check.py
BASE = "en"  # langue de base : on écrit d'abord en anglais
PARAMETRE = re.compile(r"\{(\w+)\}")
BALISE = re.compile(r"</?([a-zA-Z]+)[^>]*>")
BALISES_PERMISES = {"strong", "b", "em", "code", "br"}
FORMES = {"one", "other"}
# Langues dont un fichier abîmé est une erreur franche (le démarrage s'arrête : ``parametres.controles``) : l'anglais,
# langue de base et de repli, et le français, langue par défaut des installations. Une autre langue abîmée n'est plus
# proposée.
ESSENTIELLES = {"en", "fr"}


def dossier():
    return RACINE / "libelles"


def chemin(zone, langue):
    return dossier() / f"{zone}.{langue}.json"


def lire(zone, langue):
    """{clé: texte ou {"one", "other"}} d'une zone et d'une langue (None si le fichier n'existe pas)."""
    p = chemin(zone, langue)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def forme_valide(valeur):
    """Un texte, ou un pluriel {"one", "other"} de deux textes."""
    return isinstance(valeur, str) or (isinstance(valeur, dict) and set(valeur) == FORMES
                                       and all(isinstance(t, str) for t in valeur.values()))


def lire_controle(zone, langue):
    """Comme ``lire`` ; un fichier qui n'est pas un objet JSON lisible lève ValueError (``illisible``)."""
    d = lire(zone, langue)
    if d is not None and not isinstance(d, dict):
        raise ValueError("not a JSON object")
    return d


def textes(valeur):
    return list(valeur.values()) if isinstance(valeur, dict) else [valeur]


def parametres(valeur):
    return {m for t in textes(valeur) for m in PARAMETRE.findall(t)}


def balises(valeur):
    return sorted(m for t in textes(valeur) for m in BALISE.findall(t))


def langues_presentes():
    """Codes des langues qui ont au moins un fichier, la langue de base d'abord."""
    codes = {p.name.split(".")[-2] for p in dossier().glob("*.*.json")}
    return sorted(codes, key=lambda c: (c != BASE, c))


def problemes(langue):
    """[(type, zone, clé, détail)] des écarts d'une langue avec la langue de base ; liste vide : langue complète.

    Types : ``fichier`` (fichier de zone absent), ``illisible`` (pas un objet JSON valide ; pour l'anglais et le français,
    l'erreur est levée), ``manquante`` (clé de la base absente), ``en_trop`` (clé inconnue de la
    base), ``parametres`` (paramètres différents), ``balises`` (balises différentes), ``forme`` (pluriel d'un côté,
    texte de l'autre, ou formes autres que one / other), ``vide`` (texte vide)."""
    sortie = []
    for zone in Z.ZONES:
        base = lire_controle(zone, BASE) or {}
        try:
            autre = lire_controle(zone, langue)
        except ValueError as e:  # JSON invalide, encodage, pas un objet (UnicodeDecodeError est une ValueError)
            if langue in ESSENTIELLES:
                raise
            sortie.append(("illisible", zone, "", f"{zone}.{langue}.json: {e}"))
            continue
        if autre is None:
            sortie.append(("fichier", zone, "", f"{zone}.{langue}.json"))
            continue
        for cle in sorted(set(base) - set(autre)):
            sortie.append(("manquante", zone, cle, ""))
        for cle in sorted(set(autre) - set(base)):
            sortie.append(("en_trop", zone, cle, ""))
        for cle in sorted(set(base) & set(autre)):
            b, a = base[cle], autre[cle]
            if not forme_valide(a) or isinstance(a, dict) != isinstance(b, dict):
                sortie.append(("forme", zone, cle, ""))
                continue
            if not all(t for t in textes(a)):
                sortie.append(("vide", zone, cle, ""))
            if parametres(a) != parametres(b):
                sortie.append(("parametres", zone, cle, f"{sorted(parametres(b))} → {sorted(parametres(a))}"))
            if balises(a) != balises(b):
                sortie.append(("balises", zone, cle, f"{balises(b)} → {balises(a)}"))
    return sortie


def est_complete(langue):
    return not problemes(langue)
