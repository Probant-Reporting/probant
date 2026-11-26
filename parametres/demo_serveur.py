"""Démo sur un serveur (Administration › Paramètres › Santé, ligne « Données de démonstration ») : la base de cet espace
est celle de la démo et des comptes de démo ont encore le mot de passe public, connu de tous, alors que l'outil ne tourne
ni en mode développement ni dans la version tout-en-un. L'outil démarre quand même (évaluer la démo sur un serveur est
un usage normal) ; la ligne est « À regarder », dit quoi faire et part dans les alertes par e-mail comme tout constat de
la page (``alerte`` : « publics »). Elle disparaît dès qu'aucun compte de démo actif n'a plus le mot de passe public
(mots de passe changés, comptes désactivés ou supprimés).

Coût : vérifier un mot de passe est lent à dessein (PBKDF2, plusieurs centaines de millisecondes) et la démo a douze
comptes ; le résultat est gardé pour chaque empreinte de mot de passe (``_publics``) : un mot de passe changé a une autre
empreinte et se vérifie de nouveau, un affichage suivant ne refait aucun calcul."""
from django.conf import settings
from django.contrib.auth.hashers import check_password

_publics = {}  # empreinte du mot de passe → vrai si c'est le mot de passe public de la démo (propre au processus)
_PUBLICS_MAX = 256


def concernee():
    """Faux en mode développement et dans la version tout-en-un : là, la démo est chez elle."""
    return not settings.DEBUG and not getattr(settings, "TOUT_EN_UN", False)


def mot_de_passe_public(empreinte):
    from collecte.management.commands.charger_demo import MOT_DE_PASSE

    if empreinte not in _publics:
        if len(_publics) >= _PUBLICS_MAX:
            _publics.clear()
        _publics[empreinte] = bool(empreinte) and check_password(MOT_DE_PASSE, empreinte)
    return _publics[empreinte]


def comptes_publics():
    """Identifiants des comptes de démo actifs de l'espace courant qui ont encore le mot de passe public ; [] si la base
    n'est pas celle de la démo."""
    from collecte.management.commands._exemplia import COMPTES
    from collecte.management.commands.charger_demo import base_de_demo
    from referentiel.models import Utilisateur

    comptes = list(Utilisateur.objects.filter(username__in=[c[0] for c in COMPTES], is_active=True)
                   .order_by("username").values_list("username", "password"))
    if not comptes or not base_de_demo():
        return []
    return [nom for nom, empreinte in comptes if mot_de_passe_public(empreinte)]


def ligne():
    """La ligne de la page Santé, ou None (rien à dire)."""
    from . import sante_installation as SI
    from .libelles import libelle

    if not concernee():
        return None
    publics = comptes_publics()
    if not publics:
        return None
    return SI.ligne_sante("demo", SI.A_REGARDER, libelle("admin.sante.demo.regarder", n=len(publics)),
                          libelle("admin.sante.demo.quoi", comptes=", ".join(publics)), alerte="publics")
