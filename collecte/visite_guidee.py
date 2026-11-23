"""Visite guidée de la première connexion : trois ou quatre bulles courtes par rôle, tirées des guides par rôle.

Affichage seulement : rien n'est écrit en base (aucune migration). Que la personne l'ait vue ou fermée est gardé dans son
NAVIGATEUR (``localStorage``, une clé par espace, par compte et par rôle) ; sans stockage disponible, la visite ne
s'ouvre pas d'elle-même (elle se relance à la main). Ce module ne fait que préparer les textes et la clé pour le gabarit
``templates/_visite.html`` ; le script de la visite est dans ce gabarit.

Quand elle s'ouvre : une seule fois, sur une page d'accueil de la personne (``PAGES_ACCUEIL``), en arrivant de la page de
connexion. Une personne qui arrive par un lien direct n'est jamais interrompue. Elle ne bloque jamais l'écran (bulle non
modale), se ferme d'un clic, avec Échap et « Ne plus afficher », et se relance depuis l'Aide (« Show the tour again »).

Retrait : ``GUIDED_TOUR=off`` (variable d'environnement, ``settings.VISITE_GUIDEE``) la retire de toutes les pages ; c'est le
réglage des tests et des captures des guides (``qa/guide_screenshots.js``).
"""
from django.conf import settings
from django.urls import reverse

from espaces import contexte as ESP
from parametres.libelles import libelle


# page d'accueil de chaque rôle (valeur de ``data-page`` du corps de la page) : la visite ne s'ouvre d'elle-même que là
PAGES_ACCUEIL = ("saisie", "pour_moi", "tableau_de_bord", "visualisation")

# rôle → étapes : (clé de l'élément montré dans la barre du haut ; None : pas d'élément). Les textes sont
# « cadre.visite.<rôle>.<numéro>.titre » et « .texte ».
ETAPES = {
    "contributeur": ["saisie", None, None, None],
    "validateur": ["saisie", None, "coherence", "tableau_de_bord"],
    "admin": ["administration", "tableau_de_bord", "echanges", "aide"],
    "lecteur": ["tableau_de_bord", "visualisation", "aide"],
    "auditeur": ["saisie", "coherence", "historique", "echanges"],
}
# clé → adresses (noms d'URL) des onglets de la barre du haut que la clé désigne ; « aide » : l'icône d'aide
ONGLETS = {
    "saisie": ("collecte:saisie", "collecte:pour_moi"), "tableau_de_bord": ("collecte:tableau_de_bord",),
    "visualisation": ("collecte:visu",), "coherence": ("collecte:coherence",), "historique": ("collecte:historique",),
    "echanges": ("collecte:echanges", "collecte:echanges_importer"), "administration": ("collecte:admin_accueil",),
}
TEXTES_COMMUNS = ("titre", "etape", "precedent", "suivant", "terminer", "fermer", "plus", "annonce")


def role_de(user):
    """Rôle de la visite d'une personne : celui de son guide (l'administrateur, super-utilisateur compris)."""
    return "admin" if user.est_admin else user.role if user.role in ETAPES else "contributeur"


def selecteur(cle):
    """Sélecteur CSS de l'élément de la barre du haut que désigne une clé d'étape (vide : pas d'élément)."""
    if not cle:
        return ""
    if cle == "aide":
        return "a.aide-haut"
    return ", ".join(f'nav.onglets a[href="{reverse(nom)}"]' for nom in ONGLETS[cle])


def donnees(user):
    """Ce que lit le script : clé du navigateur, étapes (titre, texte, élément montré) et textes communs ; ``None`` si la
    visite est retirée (``GUIDED_TOUR=off``)."""
    if not settings.VISITE_GUIDEE:
        return None
    role = role_de(user)
    etapes = [{"titre": libelle(f"cadre.visite.{role}.{i}.titre"), "texte": libelle(f"cadre.visite.{role}.{i}.texte"), "cible": selecteur(cible)}
              for i, cible in enumerate(ETAPES[role], 1)]
    return {
        "cle": f"probant.visite.{ESP.code_courant()}.{user.pk}.{role}",
        "accueil": list(PAGES_ACCUEIL),
        "etapes": etapes,
        "textes": {c: libelle(f"cadre.visite.{c}") for c in TEXTES_COMMUNS},
    }


def contexte(request):
    """Variable de gabarit « visite » (personne connectée, visite non retirée) : ses données, ou rien."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or getattr(user, "doit_changer_mdp", False):
        return {}
    d = donnees(user)
    return {"visite": d} if d else {}
