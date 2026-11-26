"""Règles de la connexion d'entreprise, en un seul endroit (docs/single_sign_on.md).

- ``disponible`` : l'IT ne l'a pas coupée (``COMPANY_SIGN_IN=off``) et les bibliothèques sont là (la version tout-en-un,
  en Python pur, ne les a pas : la connexion d'entreprise n'y existe pas).
- ``active`` : disponible, allumée par un gestionnaire des espaces, réglage complet (émetteur, client, secret lisible).
- ``mot_de_passe_permis`` : connexion d'entreprise allumée, le mot de passe de l'outil ne sert plus qu'aux gestionnaires
  des espaces (comptes de secours : ce sont eux qui la règlent, ils ne peuvent donc pas s'enfermer dehors), sauf si le
  réglage le laisse à tous. Éteinte ou coupée : mot de passe permis à tous, comme avant.
- ``assistants_permis`` (jetons des assistants, serveur_mcp/jetons.py ; décision du produit) : une personne qui ne peut
  plus se connecter par mot de passe n'a aucun accès par un assistant : ses jetons sont refusés et elle n'en crée pas.
  Gestionnaires des espaces, et tout le monde si le réglage laisse le mot de passe à tous : jetons comme avant.
  Éteinte ou coupée : rien ne change.
"""
import logging

from django.conf import settings
from django.db import DatabaseError

journal = logging.getLogger("connexion_entreprise")


def bibliotheques():
    try:
        import cryptography.fernet  # noqa: F401
        import jwt  # noqa: F401
    except ImportError:
        return False
    return True


def disponible():
    return bool(getattr(settings, "CONNEXION_ENTREPRISE_PERMISE", True)) and bibliotheques()


def reglage():
    """Réglage de l'installation (ligne 1 du registre commun), ou un réglage vide (éteint) s'il n'y en a pas : rien
    n'est écrit en lisant."""
    from .models import ReglageEntreprise

    try:
        return ReglageEntreprise.objects.filter(pk=1).first() or ReglageEntreprise()
    except DatabaseError:  # table absente (base pas encore migrée) ou registre illisible : éteinte
        journal.exception("Company sign-in settings unreadable: company sign-in is off")
        return ReglageEntreprise()


def complet(r):
    """Émetteur, client et secret lisible (un secret chiffré avec une clé secrète que l'installation n'a plus ne compte
    pas : la connexion d'entreprise est alors éteinte, l'écran le dit)."""
    from .secret import dechiffrer

    return bool(r.emetteur and r.client_id and r.secret_chiffre) and bibliotheques() and dechiffrer(r.secret_chiffre) is not None


def active(r=None):
    r = r if r is not None else reglage()
    return disponible() and r.actif and complet(r)


def mot_de_passe_permis(compte_id, r=None):
    """Vrai si ce compte (numéro du registre commun) peut se connecter avec le mot de passe de l'outil."""
    r = r if r is not None else reglage()
    if not active(r) or r.mot_de_passe_pour_tous:
        return True
    from espaces.models import Compte

    return Compte.objects.filter(pk=compte_id, gestionnaire=True, actif=True).exists()


CLE_ETAT, DUREE_ETAT = "connexion-entreprise-etat", 60  # cache « connexion » (fichiers partagés par les processus)


def oublier_etat(**kwargs):
    """Réglage enregistré ou retiré (signal) : l'état mis en cache est relu à la requête suivante."""
    from django.core.cache import caches

    caches["connexion"].delete(CLE_ETAT)


def _etat():
    """(allumée et complète, mot de passe pour tous). Seul « éteinte » est gardé en cache (``DUREE_ETAT`` secondes,
    oublié aussitôt après un enregistrement du réglage) : éteinte, aucune requête en base par page. Allumée, le réglage
    est relu à chaque fois : un état « allumée » mis en cache ne survit jamais à un retour en arrière du registre
    (restauration, transaction annulée) ; seul un « éteinte » peut durer au plus ``DUREE_ETAT`` après une restauration
    qui l'allume sans passer par l'écran."""
    from django.core.cache import caches

    cache = caches["connexion"]
    if cache.get(CLE_ETAT) == "eteinte":
        return False, False
    r = reglage()
    allumee = bool(r.actif and complet(r))
    if not allumee:
        cache.set(CLE_ETAT, "eteinte", DUREE_ETAT)
    return allumee, bool(r.mot_de_passe_pour_tous)


def session_permise(compte_id, methode):
    """Une session ouverte par ``methode`` (« entreprise », « mot_de_passe » ; vide : ouverte avant la mise à jour,
    traitée comme « mot_de_passe ») reste-t-elle permise ? Même règle que la connexion par mot de passe
    (``mot_de_passe_permis``), appliquée à chaque requête : une session d'entreprise toujours ; une session par mot de
    passe tant que ce compte a droit au mot de passe. Éteinte ou coupée : toujours, sans requête en base."""
    if methode == "entreprise" or not disponible():
        return True
    allumee, pour_tous = _etat()
    if not allumee or pour_tous:
        return True
    from espaces.models import Compte

    return Compte.objects.filter(pk=compte_id, gestionnaire=True, actif=True).exists()


def assistants_permis(compte_id, r=None):
    """Vrai si ce compte peut avoir des jetons d'assistant (créer, s'en servir) : exactement quand il peut se connecter
    avec le mot de passe de l'outil. Une personne qui n'entre que par son compte d'entreprise n'a pas d'accès par un
    assistant : un jeton ne peut pas suivre ce que son entreprise décide (compte bloqué, départ)."""
    return mot_de_passe_permis(compte_id, r)
