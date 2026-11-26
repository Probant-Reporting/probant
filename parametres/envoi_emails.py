"""Envoi des e-mails : le seul point de passage de tous les envois de l'outil (relances, e-mail de test, et tout envoi
futur). Aucun autre module ne lit ``settings.EMAIL_*`` ni ``DEFAULT_FROM_EMAIL`` pour envoyer (test
``parametres/test_connexion_envoi_point_unique.py``).

D'où viennent les réglages, dans cet ordre :

1. « environnement » : ``SMTP_HOST`` est rempli dans le fichier de réglages (``.env``). Il gagne toujours : réglage de
   l'IT, comportement d'avant inchangé, aucune surprise à la mise à jour. L'écran les montre en lecture seule.
2. « outil » : le serveur réglé dans Administration › Paramètres › Hébergement. Une seule valeur pour toute
   l'installation, au registre commun (``espaces.ServeurEnvoi``), modifiable seulement par un gestionnaire des espaces
   (``espaces.comptes.est_gestionnaire``). Mot de passe gardé chiffré avec le secret de
   l'installation (``chiffrement.py``), jamais renvoyé au navigateur.
3. « aucune » : rien n'est réglé. Aucune relance ne part ; l'e-mail de test est seulement écrit dans le journal du
   serveur (moteur « console »), comme avant.

Mode d'emploi (un envoi) :

    from parametres import envoi_emails as EE
    if EE.envoi_actif():
        connexion, expediteur = EE.connexion_envoi()
        EmailMessage(sujet, texte, expediteur, [adresse], connection=connexion).send()

``connexion_envoi`` lève ``MotDePasseIllisible`` (une ``OSError``, attrapée comme un échec d'envoi) quand le mot de
passe enregistré ne se lit plus (secret de l'installation changé) ; ``cause(e)`` donne la cause en clair.
"""
import datetime
import math
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import get_connection
from django.db import DatabaseError, transaction
from django.utils import timezone

from espaces import contexte as ESP

from . import chiffrement as CH
from .libelles import libelle

ENVIRONNEMENT, OUTIL, AUCUNE = "environnement", "outil", "aucune"
CONSOLE = "django.core.mail.backends.console.EmailBackend"
SMTP = "django.core.mail.backends.smtp.EmailBackend"
SECURITES = ("starttls", "ssl", "none")
NOMS_SECURITE = {"starttls": "STARTTLS", "ssl": "SSL"}  # « none » : libellé de la langue
DELAI_ESSAI = 10  # secondes : e-mail de test (bouton), plus court que les envois ordinaires (EMAIL_TIMEOUT)
ESSAIS_MAX, ESSAIS_FENETRE = 5, datetime.timedelta(minutes=15)  # e-mails de test avec les réglages de l'outil
MOT_DE_PASSE_MAX = 512
HOTE = re.compile(r"^(?=.{1,253}$)(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$")


class MotDePasseIllisible(OSError):
    """Le mot de passe enregistré ne se lit plus avec le secret de l'installation : à ressaisir."""


@dataclass(frozen=True)
class Reglage:
    """Réglages en vigueur, sans le mot de passe (seulement s'il y en a un, et s'il se lit)."""

    source: str
    hote: str = ""
    port: int = 587
    securite: str = "starttls"
    identifiant: str = ""
    expediteur: str = ""
    mot_de_passe: bool = False
    mot_de_passe_illisible: bool = False
    mot_de_passe_le: datetime.datetime | None = None
    modifie_le: datetime.datetime | None = None

    @property
    def actif(self):
        return self.source != AUCUNE

    @property
    def nom_securite(self):
        return NOMS_SECURITE.get(self.securite) or libelle("admin.hebergement.info.aucune")


def ligne():
    """La ligne du registre commun (ou None : jamais enregistrée, ou registre pas encore à jour pendant une mise à jour)."""
    from espaces.models import ServeurEnvoi

    try:
        return ServeurEnvoi.objects.filter(pk=1).first()
    except DatabaseError:
        return None


def par_environnement():
    """``SMTP_HOST`` est rempli dans le fichier de réglages : il gagne, rien ne se règle dans l'outil."""
    return bool(settings.EMAIL_HOST)


def delai_essai():
    """Délai de l'e-mail de test, en secondes : court (``DELAI_ESSAI``), jamais plus long que les envois ordinaires."""
    return min(DELAI_ESSAI, settings.EMAIL_TIMEOUT)


def _securite_environnement():
    return "ssl" if settings.EMAIL_USE_SSL else "starttls" if settings.EMAIL_USE_TLS else "none"


def reglage(s=None):
    """Réglages en vigueur (``Reglage``) : le fichier de réglages s'il nomme un serveur, sinon l'outil, sinon aucun."""
    if settings.EMAIL_HOST:
        return Reglage(ENVIRONNEMENT, settings.EMAIL_HOST, settings.EMAIL_PORT, _securite_environnement(),
                       settings.EMAIL_HOST_USER, settings.DEFAULT_FROM_EMAIL, bool(settings.EMAIL_HOST_PASSWORD))
    s = s or ligne()
    if s is None or not s.hote:
        return Reglage(AUCUNE, expediteur=settings.DEFAULT_FROM_EMAIL)
    illisible = False
    if s.mot_de_passe_chiffre:
        try:
            CH.dechiffrer(s.mot_de_passe_chiffre, CH.MOT_DE_PASSE_SMTP)
        except CH.Illisible:
            illisible = True
    return Reglage(OUTIL, s.hote, s.port, s.securite, s.identifiant, s.expediteur, bool(s.mot_de_passe_chiffre),
                   illisible, s.mot_de_passe_le, s.modifie_le)


def envoi_actif():
    """Un serveur d'envoi est réglé (fichier de réglages ou outil). Sans lui, aucune relance ne part ni n'est notée."""
    return reglage().actif


def moteur_outil():
    """Moteur des envois réglés dans l'outil : celui des réglages (``EMAIL_BACKEND`` : la boîte en mémoire pendant les
    tests), sauf la console, qui n'est que le repli « aucun serveur » : alors le SMTP."""
    return SMTP if settings.EMAIL_BACKEND == CONSOLE else settings.EMAIL_BACKEND


def connexion_envoi(timeout=None):
    """(connexion, expéditeur) effectifs : la connexion Django (pas encore ouverte) et l'adresse d'expédition à mettre
    dans chaque e-mail. ``timeout`` : délai en secondes (par défaut ``EMAIL_TIMEOUT``). Lève ``MotDePasseIllisible``."""
    if settings.EMAIL_HOST:
        return get_connection(**({"timeout": timeout} if timeout else {})), settings.DEFAULT_FROM_EMAIL
    s = ligne()
    if s is None or not s.hote:
        return get_connection(), settings.DEFAULT_FROM_EMAIL
    mot_de_passe = ""
    if s.mot_de_passe_chiffre:
        try:
            mot_de_passe = CH.dechiffrer(s.mot_de_passe_chiffre, CH.MOT_DE_PASSE_SMTP)
        except CH.Illisible:
            raise MotDePasseIllisible("saved SMTP password unreadable with this secret key: enter it again") from None
    return get_connection(moteur_outil(), host=s.hote, port=s.port, username=s.identifiant, password=mot_de_passe,
                          use_tls=s.securite == "starttls", use_ssl=s.securite == "ssl",
                          timeout=timeout or settings.EMAIL_TIMEOUT), s.expediteur


# ---------------------------------------------------------------- enregistrement (registre commun, relu sous verrou)
def _ligne_verrouillee():
    from espaces.models import ServeurEnvoi

    ServeurEnvoi.objects.get_or_create(pk=1)  # deux premiers enregistrements en même temps : get_or_create relit
    return ServeurEnvoi.objects.select_for_update().get(pk=1)


CHAMPS = ("hote", "port", "securite", "identifiant", "expediteur")
EFFACE_SERVEUR_CHANGE = "mot de passe effacé (serveur changé)"  # au journal, sans rien de secret


def destination_changee(s, hote, port, securite, identifiant):
    """Le mot de passe enregistré partirait-il ailleurs, ou autrement, que là où il a été saisi ? Vrai pour un autre
    serveur (nom comparé sans la casse ni les espaces autour), un autre port, un passage de la sécurité vers « Aucune »
    (il partirait en clair) ou un autre identifiant (un mot de passe est celui d'un compte : avec un autre compte, il
    serait au mieux faux, au pire présenté sous une autre identité). STARTTLS ↔ SSL : même serveur, toujours chiffré,
    rien ne change. ``s`` : la ligne enregistrée (ou None)."""
    if s is None:
        return False
    return ((s.hote or "").strip().lower() != (hote or "").strip().lower() or int(s.port) != int(port)
            or (securite == "none" and s.securite != "none") or (s.identifiant or "").strip() != (identifiant or "").strip())


def enregistrer(par, hote, port, securite, identifiant, expediteur, mot_de_passe=""):
    """Enregistre les réglages de l'outil ; ``mot_de_passe`` vide : le mot de passe enregistré est gardé, sauf si la
    destination change (``destination_changee``, relu sous verrou) : il est alors effacé, à saisir de nouveau (un
    secret ne part jamais vers une destination pour laquelle il n'a pas été saisi). Renvoie les changements
    [(champ, avant, après)] pour l'historique : l'identifiant et le mot de passe sans leur valeur ; un mot de passe
    effacé ainsi : (« mot_de_passe », "", ``EFFACE_SERVEUR_CHANGE``)."""
    if securite not in SECURITES:
        raise ValueError(securite)
    nouveau = {"hote": hote.strip(), "port": int(port), "securite": securite, "identifiant": identifiant.strip(),
               "expediteur": expediteur.strip()}
    with transaction.atomic(using=ESP.COMMUN):
        s = _ligne_verrouillee()
        changements = []
        efface = (not mot_de_passe and bool(s.mot_de_passe_chiffre)
                  and destination_changee(s, nouveau["hote"], nouveau["port"], securite, nouveau["identifiant"]))
        for champ in CHAMPS:
            avant, apres = getattr(s, champ), nouveau[champ]
            if avant != apres:
                cache = champ == "identifiant"
                changements.append((champ, "" if cache else avant, "modifié" if cache else apres))
                setattr(s, champ, apres)
        if mot_de_passe:
            s.mot_de_passe_chiffre = CH.chiffrer(mot_de_passe, CH.MOT_DE_PASSE_SMTP)
            s.mot_de_passe_le = timezone.now()
            changements.append(("mot_de_passe", "", "mot de passe enregistré"))
        elif efface:
            s.mot_de_passe_chiffre, s.mot_de_passe_le = "", None
            changements.append(("mot_de_passe", "", EFFACE_SERVEUR_CHANGE))
        if changements:
            s.modifie_le, s.modifie_par = timezone.now(), getattr(par, "pk", None)
            s.save()
    return changements


def effacer_mot_de_passe(par):
    """Efface le mot de passe enregistré ; vrai s'il y en avait un."""
    with transaction.atomic(using=ESP.COMMUN):
        s = _ligne_verrouillee()
        if not s.mot_de_passe_chiffre:
            return False
        s.mot_de_passe_chiffre, s.mot_de_passe_le = "", None
        s.modifie_le, s.modifie_par = timezone.now(), getattr(par, "pk", None)
        s.save()
    return True


def reserver_essai():
    """Limite des e-mails de test avec les réglages de l'outil (``ESSAIS_MAX`` par ``ESSAIS_FENETRE`` pour toute
    l'installation) : None si l'essai est permis (il est noté), sinon le nombre de minutes à attendre."""
    maintenant = timezone.now()
    with transaction.atomic(using=ESP.COMMUN):
        s = _ligne_verrouillee()
        recents = []
        for d in s.essais if isinstance(s.essais, list) else []:
            try:
                quand = datetime.datetime.fromisoformat(d)
            except (TypeError, ValueError):
                continue
            if maintenant - ESSAIS_FENETRE < quand <= maintenant:
                recents.append(quand)
        if len(recents) >= ESSAIS_MAX:
            return max(1, math.ceil((min(recents) + ESSAIS_FENETRE - maintenant).total_seconds() / 60))
        s.essais = [d.isoformat() for d in recents] + [maintenant.isoformat()]
        s.save(update_fields=["essais"])
    return None


# ---------------------------------------------------------------- échec d'un envoi, en clair
CAUSES = (  # du plus précis au plus général (SSLCertVerificationError est une SSLError, toutes sont des OSError)
    (MotDePasseIllisible, "mot_de_passe_illisible"),
    (smtplib.SMTPAuthenticationError, "identifiants"),
    (smtplib.SMTPNotSupportedError, "securite"),
    (ssl.SSLCertVerificationError, "certificat"),
    (ssl.SSLError, "securite"),
    (smtplib.SMTPSenderRefused, "expediteur"),
    (smtplib.SMTPRecipientsRefused, "destinataire"),
    (socket.gaierror, "introuvable"),
    (TimeoutError, "delai"),
    (ConnectionRefusedError, "refusee"),
    (smtplib.SMTPServerDisconnected, "coupee"),
    (smtplib.SMTPConnectError, "coupee"),
    (ConnectionResetError, "coupee"),
    (smtplib.SMTPException, "refuse"),
    (OSError, "injoignable"),
)


def cle_cause(e):
    # délai dépassé en attendant une réponse : smtplib le rend en « connexion coupée » (SMTPServerDisconnected levée
    # pendant le TimeoutError)
    if isinstance(e, smtplib.SMTPServerDisconnected) and isinstance(e.__context__, TimeoutError):
        return "delai"
    for genre, cle in CAUSES:
        if isinstance(e, genre):
            return cle
    return "refuse"


def cause(e, delai=None):
    """Cause d'un échec, en clair, dans la langue de la personne, et ce qu'il faut faire. Jamais la réponse du serveur."""
    return texte_cause(cle_cause(e), delai)


def texte_cause(cle, delai=None):
    """Cause notée par sa clé (``cle_cause``, ex. l'échec d'une alerte par e-mail), en clair dans la langue de qui lit."""
    return libelle(f"admin.hebergement.smtp.cause.{cle}", delai=delai or settings.EMAIL_TIMEOUT)


def resume_technique(e):
    """Nom de l'erreur et code SMTP éventuel (« SMTPAuthenticationError 535 ») : jamais le texte renvoyé par le serveur,
    qui pourrait recopier la réponse d'un service interne (bouton de test détourné pour sonder le réseau)."""
    code = getattr(e, "smtp_code", None)
    if code is None and isinstance(e, smtplib.SMTPRecipientsRefused):
        codes = [v[0] for v in (e.recipients or {}).values() if isinstance(v, tuple) and v]
        code = codes[0] if codes else None
    return f"{e.__class__.__name__} {code}" if isinstance(code, int) and code > 0 else e.__class__.__name__
