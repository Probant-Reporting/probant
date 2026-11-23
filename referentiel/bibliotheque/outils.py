"""Briques communes aux modèles de la bibliothèque : ``kpi`` (définition d'un KPI) et textes répétés.

Utilisées par ``socles.py`` (catalogue commun et quatre premiers socles) et par chaque fichier de ``definitions/`` (un
modèle par fichier). Contrôle d'un modèle : ``python3 manage.py bibliotheque --validate``.
"""

ZERO = " Saisir 0 s'il n'y en a pas (N/A rendrait le total non applicable)."
ZERO_EN = " Enter 0 if there is none (N/A would make the total not applicable)."
# Catégorie du scope 3 non significative : N/A, pas 0 (une catégorie à 0 se lirait « nulle ») ; dans un total purement
# additif, une source N/A compte comme 0 (case de la fiche KPI cochée à l'installation, KPI.na_compte_zero_par_defaut).
S3_NA = " Une catégorie qui n'est pas significative : répondre N/A (elle n'est pas publiée et ne compte pas dans un total)."
S3_NA_EN = " A category that is not significant: answer N/A (it is not disclosed and does not count in a total)."

NIVEAUX_CONSEILLES = ("", "haut", "pays", "entite", "bas")


def kpi(code, fr, en, unite, agregation="Somme", type_="Saisi", reponse="Numérique", formule="", temps="", decimales=None,
        description="", inclure="", exclure="", source="", niveau="", confidentialite=""):
    """Un KPI du catalogue de la bibliothèque, sous la forme (code, définition).

    Textes des descriptions (``description``, ``inclure``, ``exclure``, ``source``) : un texte seul = français seulement
    (anglais dans documentation.T, quatre premiers socles) ; un couple (français, anglais) pour les nouveaux modèles, qui
    voyagent alors dans les deux langues.

    ``niveau`` : niveau de saisie conseillé quand la règle automatique ne convient pas (voir
    collecte.paquets._niveaux_automatiques) : « haut » (une seule réponse pour toute l'entreprise : politique, texte rédigé,
    donnée du groupe), « pays » (un facteur qui dépend du pays : niveau Pays de l'installation s'il existe), « entite »
    (une réponse par entité juridique, par exemple une déclaration par employeur : niveau Entité ou Filiale de
    l'installation), « bas » (le plus bas, déjà la règle d'un KPI saisi).

    ``confidentialite`` : « Restreint » ou « Confidentiel » pour une donnée sensible (rémunérations) ; vide = « Non
    sensible ». Un KPI sensible n'est jamais envoyé à la prise IA sans réglage, et ses preuves se suivent dans la page de
    conservation (collecte/sensibles.py, collecte/conservation.py)."""
    return code, {"fr": fr, "en": en, "unite": unite, "agregation": agregation, "type": type_, "reponse": reponse,
                  "formule": formule, "temps": temps, "decimales": decimales, "description": description, "a_inclure": inclure,
                  "a_exclure": exclure, "source": source, "niveau": niveau,
                  **({"confidentialite": confidentialite} if confidentialite else {})}


def langue(texte, lg):
    """Texte d'une description dans une langue : couple (fr, en) ou texte seul (français)."""
    if isinstance(texte, (tuple, list)):
        return texte[0 if lg == "fr" else 1] if len(texte) > (0 if lg == "fr" else 1) else ""
    return texte if lg == "fr" else ""
