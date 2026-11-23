"""Prise IA (docs/ai_socket.md) : état, clé, plafond d'appels par jour, journal, et la seule fonction qui envoie.

- Éteinte par défaut, dans chaque espace (``Instance.ia_active``), et chaque usage aussi ; coupée pour toute
  l'installation par l'IT avec AI_SOCKET=off (``settings.IA_PRISE_PERMISE``).
- La clé du client : un fichier par espace (``<dossier des données>/ai-keys/<espace>.key``, droits 600), jamais en base,
  jamais dans une sauvegarde (``sauvegardes._proteges``), jamais réaffichée ni écrite au journal.
- ``appeler`` refuse avant tout réseau (``Refus``) quand la prise, l'usage ou la clé manque, quand le plafond du jour
  est atteint ou quand les données dépassent la taille permise ; sinon il écrit une ligne au journal (qui, quel usage,
  quand, fournisseur, modèle, taille ; jamais le contenu), puis appelle le fournisseur et renvoie la réponse vérifiée.
"""
import datetime
import os
import re

from django.conf import settings
from django.utils import timezone

from espaces import contexte as ESP

from . import ia_fournisseurs as F
from .libelles import libelle

USAGES = ("expliquer_alerte", "reprise", "traduction")
CHAMP_USAGE = {"expliquer_alerte": "ia_expliquer_alertes", "reprise": "ia_reprise", "traduction": "ia_traductions"}
ACTION = "ia_appel"  # action du journal d'un appel
CLE_MOTIF = re.compile(r"^[\x21-\x7e]{20,400}$")  # caractères visibles, sans espace


class Refus(Exception):
    """Demande refusée avant tout envoi (message en clair, dans la langue de la personne)."""


# ---------------------------------------------------------------- clé
def chemin_cle(code=None):
    code = code or ESP.code_courant()
    if not ESP.CODE.match(code) and code != ESP.PRINCIPAL:
        raise ValueError(code)
    return settings.IA_CLES_DIR / f"{code}.key"


def cle_presente():
    try:
        return chemin_cle().stat().st_size > 0
    except OSError:
        return False


def date_cle():
    """Date d'enregistrement de la clé de l'espace courant (heure locale), ou None."""
    try:
        return timezone.localtime(datetime.datetime.fromtimestamp(chemin_cle().stat().st_mtime, tz=datetime.timezone.utc))
    except OSError:
        return None


def valider_cle(texte):
    """Clé nettoyée, ou ValueError (message en clair)."""
    texte = (texte or "").strip()
    if not CLE_MOTIF.match(texte):
        raise ValueError(libelle("admin.ia.cle_invalide"))
    return texte


def enregistrer_cle(texte):
    """Écrit la clé (validée) de l'espace courant : fichier à part puis mis en place d'un coup, lisible par l'outil seul."""
    texte = valider_cle(texte)
    dossier = settings.IA_CLES_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dossier, 0o700)
    except OSError:
        pass
    final = chemin_cle()
    tmp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(texte)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)


def retirer_cle():
    try:
        chemin_cle().unlink()
        return True
    except FileNotFoundError:
        return False


def _lire_cle():
    try:
        return chemin_cle().read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------- état
def instance():
    from .models import Instance

    return Instance.courante()


def fournisseur(i=None):
    """Classe du fournisseur réglé (None s'il n'est pas proposé ici)."""
    i = i or instance()
    return F.disponibles().get(i.ia_fournisseur)


def modele(i=None):
    """Modèle réglé s'il est connu du fournisseur, sinon son modèle par défaut."""
    i = i or instance()
    f = fournisseur(i)
    if f is None:
        return ""
    return i.ia_modele if f().connait(i.ia_modele) else f.modele_par_defaut


def disponible(usage=None, i=None):
    """Vrai si une demande peut partir : prise permise par l'IT, allumée dans l'espace, fournisseur connu, clé
    enregistrée et, pour ``usage``, cet usage allumé. Sert aussi à montrer ou non les boutons."""
    if not settings.IA_PRISE_PERMISE:
        return False
    i = i or instance()
    if not i.ia_active or fournisseur(i) is None or not cle_presente():
        return False
    return usage is None or bool(getattr(i, CHAMP_USAGE[usage]))


def bouton_visible(usage=None, i=None):
    """Vrai si un bouton IA s'affiche : demande possible (``disponible``) et limite du jour pas encore atteinte
    (docs/ai_socket.md §1 : aucun bouton quand la limite est atteinte ; seconde recette, B4). L'envoi (``appeler``)
    vérifie de nouveau la limite sous verrou."""
    i = i or instance()
    return disponible(usage, i) and appels_aujourdhui() < i.ia_appels_jour


def debut_du_jour():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def appels_aujourdhui():
    from collecte.models import Journal

    return Journal.objects.filter(action=ACTION, date__gte=debut_du_jour()).count()


# ---------------------------------------------------------------- envoi
def appeler(utilisateur, invite, objet):
    """Envoie ``invite`` (parametres.ia_invites.Invite) et renvoie la réponse vérifiée (``invite.verifier``).
    ``objet`` : ce que la demande concerne, pour le journal (alerte, langue, paramètres). Refus avant envoi : ``Refus`` ;
    échec de l'appel : ``ia_fournisseurs.ErreurIA``."""
    from collecte.models import Journal

    from .models import Instance

    i = instance()
    if not disponible(invite.usage, i):
        raise Refus(libelle("admin.ia.refus.eteinte"))
    taille = len(invite.systeme) + len(invite.donnees)
    if taille > i.ia_taille_max:
        from collecte.templatetags.collecte import entier

        raise Refus(libelle("admin.ia.refus.trop_grand", taille=entier(taille), limite=entier(i.ia_taille_max)))
    with ESP.atomic():
        # relu sous verrou : deux demandes simultanées ne dépassent pas le plafond (PostgreSQL ; sous SQLite, les
        # transactions « immediate » se suivent déjà)
        i = Instance.objects.select_for_update().get(pk=i.pk)
        if appels_aujourdhui() >= i.ia_appels_jour:
            raise Refus(libelle("admin.ia.refus.plafond", n=i.ia_appels_jour))
        f, m = fournisseur(i), modele(i)
        Journal.ecrire(utilisateur, ACTION, objet, invite.usage, "", f"{f.code} · {m} · {taille}")
    cle = _lire_cle()
    if not cle:
        raise Refus(libelle("admin.ia.refus.eteinte"))
    reponse = f().demander(F.Requete(cle=cle, modele=m, systeme=invite.systeme, donnees=invite.donnees, schema=invite.schema,
                                     max_jetons=invite.max_jetons, effort=invite.effort, delai=i.ia_delai, usage=invite.usage))
    try:
        return invite.verifier(reponse.donnees)
    except (TypeError, ValueError, AttributeError, KeyError):
        raise F.ErreurIA("reponse_invalide") from None


def message_erreur(e):
    """Texte en clair d'un refus ou d'une erreur d'appel."""
    if isinstance(e, F.ErreurIA):
        return libelle(f"admin.ia.erreur.{e.code}")
    return str(e)
