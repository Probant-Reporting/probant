"""Historique des connexions.

Chaque connexion par la page de connexion (de l'outil, du mode expert, de l'assistant de mise en place) laisse une ligne
``HistoriqueConnexion`` : réussie, manquée, ou refusée par la limite d'essais (``referentiel/connexion.py``).

- Où : dans la base de l'espace où elle a lieu, comme le journal (sauvegardée et restaurée avec l'espace). Une connexion
  réussie est notée dans l'espace où la session s'ouvre (celui de la page, ou l'espace où la personne a accès quand la page
  de l'outil l'y renvoie) ; un échec, dans l'espace de la page (le mode expert ne renvoie pas dans un autre espace : un bon
  mot de passe sans accès ici y est un échec). Une seule ligne « bloquee » par période de blocage.
- Quoi : la date, le compte s'il a une copie dans cet espace, le résultat. Jamais le mot de passe, jamais l'adresse réseau
  (la fiche ne la prévoit pas), jamais l'identifiant tapé : son empreinte seulement (HMAC tronqué par la clé secrète de
  l'installation), qui montre des essais répétés avec le même identifiant sans le révéler (une personne tape parfois son
  mot de passe dans le champ de l'identifiant). Un compte d'un autre espace essayé ici n'apparaît que par son empreinte :
  l'administrateur de cet espace n'apprend pas qu'il existe.
- Combien de temps : ``Instance.connexions_jours`` de l'espace (Paramètres › Hébergement), puis le ménage de la nuit
  efface la ligne (``purger``) ; les pages ne montrent jamais une ligne plus ancienne (``recentes``).
- Qui voit : l'administrateur de l'espace (Administration › Comptes › Historique des connexions) ; chaque personne, ses
  dernières connexions dans Mon compte.

Noter ne bloque jamais une connexion : une erreur de base est notée au journal du serveur."""
import datetime
import hashlib
import hmac
import logging

from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils import timezone

from espaces import contexte as E

journal = logging.getLogger("referentiel.connexion")
DERNIERES = 10  # Mon compte : les dernières connexions de la personne
MOT_DE_PASSE, ENTREPRISE = "mot_de_passe", "entreprise"  # méthode de la connexion


def empreinte(identifiant):
    """Empreinte courte et stable d'un identifiant tapé (sans majuscules ni espaces autour) : 8 caractères hexadécimaux."""
    texte = (identifiant or "").strip().lower().encode()
    return hmac.new(settings.SECRET_KEY.encode(), b"connexion|" + texte, hashlib.sha256).hexdigest()[:8]


def trouver_compte(identifiant):
    """Compte du registre que la connexion vise : même recherche que ``auth.EmailOuIdentifiant`` (e-mail, identifiant
    exact, puis sans majuscules), ou None."""
    from espaces.models import Compte

    ident = (identifiant or "").strip()
    if not ident:
        return None
    return (Compte.objects.filter(email__iexact=ident).order_by("pk").first()
            or Compte.objects.filter(username=ident).order_by("pk").first()
            or Compte.objects.filter(username__iexact=ident).order_by("pk").first())


def noter(resultat, identifiant="", utilisateur=None, alias=None, methode=MOT_DE_PASSE, motif=""):
    """Ajoute une ligne. ``utilisateur`` : la copie connectée (réussite) ; sinon le compte visé par ``identifiant`` est
    rattaché seulement s'il a une copie dans l'espace ``alias`` (par défaut l'espace courant). ``methode`` : mot de passe
    ou compte d'entreprise ; ``motif`` : cause courte d'un refus (connexion_entreprise/flux.py). Compte d'entreprise
    refusé avant que l'adresse soit connue : ni compte ni empreinte."""
    from .models import HistoriqueConnexion, Utilisateur

    try:
        with E.toutes_les_bases():
            alias = alias or (utilisateur._state.db if utilisateur is not None else None) or E.alias_courant()
            pk = utilisateur.pk if utilisateur is not None else None
            if pk is None:
                c = trouver_compte(identifiant)
                # même comparaison que ``auth.copie_active`` : la copie porte l'e-mail du registre (base d'espace restaurée
                # où ce numéro appartient à quelqu'un d'autre : l'échec ne lui est pas attribué)
                if c is not None and Utilisateur._default_manager.using(alias).filter(
                        pk=c.pk, email__iexact=(c.email or "")).exists():
                    pk = c.pk
            with transaction.atomic(using=alias):
                HistoriqueConnexion.objects.using(alias).create(
                    utilisateur_id=pk, resultat=resultat, methode=methode, motif=motif[:16],
                    empreinte="" if utilisateur is not None or (methode == ENTREPRISE and not identifiant)
                    else empreinte(identifiant))
    except DatabaseError:
        journal.exception("Sign-in not written to the sign-in history (%s)", resultat)


def limite():
    """Date avant laquelle une connexion n'est plus gardée (réglage de l'espace courant)."""
    from parametres.models import Instance

    return timezone.now() - datetime.timedelta(days=max(Instance.courante().connexions_jours, 1))


def recentes():
    """Connexions encore gardées dans l'espace courant, les plus récentes d'abord."""
    from .models import HistoriqueConnexion

    return HistoriqueConnexion.objects.filter(date__gte=limite())


def dernieres(utilisateur, n=DERNIERES):
    return list(recentes().filter(utilisateur_id=utilisateur.pk)[:n])


def purger():
    """Ménage de la nuit : efface les connexions plus anciennes que le réglage de l'espace courant ; renvoie le nombre."""
    from .models import HistoriqueConnexion

    return HistoriqueConnexion.objects.filter(date__lt=limite()).delete()[0]
