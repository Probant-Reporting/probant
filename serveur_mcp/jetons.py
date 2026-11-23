"""Jetons personnels du serveur MCP (docs/mcp.md, 1.4).

Un jeton : « prb_ » + 32 octets au hasard (``secrets.token_urlsafe``). La base garde son empreinte SHA-256 (le jeton
ne se retrouve pas à partir d'elle : un hachage lent n'ajoute rien pour 256 bits de hasard), ses premiers caractères,
son nom, son propriétaire et ses dates. Il n'est montré qu'une fois, à la création.

``authentifier`` relit tout à chaque requête : jeton connu dans la base de l'espace courant (un jeton d'un autre espace
y est inconnu), ni révoqué ni expiré, compte actif dans l'espace et dans le registre commun (``get_user`` de la
connexion, la même règle que pour une session), mot de passe provisoire déjà remplacé. Le jeton n'a aucun droit propre :
le rôle, les attributions et le périmètre de la personne s'appliquent tels qu'ils sont à ce moment."""
import datetime
import hashlib
import logging
import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from collecte.models import Journal
from espaces import contexte as ESP
from parametres.libelles import libelle

from .models import JetonMCP, ReglageMCP

journal = logging.getLogger("serveur_mcp")

PREFIXE = "prb_"
JETONS_MAX = 10  # jetons actifs par personne
DUREES = (7, 30, 90)  # jours proposés (bornés par le réglage de l'espace)
DUREE_DEFAUT = 30
NOM_MAX = 80


def empreinte(jeton):
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def empreinte_mdp(hachage):
    """Empreinte du mot de passe haché d'un compte (même calcul que la migration 0002) : gardée avec le jeton ; un mot
    de passe changé ne la retrouve plus."""
    return hashlib.sha256(("probant-mcp-mdp:" + (hachage or "")).encode("utf-8")).hexdigest()


def durees_proposees(reglage=None):
    """Durées proposées à la création (jours) : 7, 30, 90 sous la durée maximale de l'espace, puis cette durée maximale
    (90 → 7, 30, 90 ; 60 → 7, 30, 60 ; 365 → 7, 30, 90, 365 ; 5 → 5)."""
    maxi = (reglage or ReglageMCP.courant()).duree_max_jours
    return [d for d in DUREES if d < maxi] + [maxi]


def duree_par_defaut(durees):
    return DUREE_DEFAUT if DUREE_DEFAUT in durees else max(d for d in durees if d <= DUREE_DEFAUT) if min(durees) <= DUREE_DEFAUT else durees[0]


def actifs(utilisateur=None):
    qs = JetonMCP.objects.filter(revoque_le__isnull=True, expire_le__gt=timezone.now()).select_related("utilisateur")
    return qs if utilisateur is None else qs.filter(utilisateur=utilisateur)


@ESP.atomic
def creer(utilisateur, nom, jours):
    """Crée un jeton pour la personne (tout rôle : un lecteur ou un auditeur n'aura que les outils de lecture) ; renvoie
    (jeton en clair, objet). Refus clair : assistants éteints dans l'espace, nom vide ou trop long, durée hors de ce qui
    est proposé, trop de jetons actifs."""
    reglage = ReglageMCP.courant()
    if not reglage.actif:
        raise PermissionDenied(libelle("mcp.jetons.eteint"))
    nom = " ".join((nom or "").split())
    if not nom:
        raise ValidationError(libelle("mcp.jetons.nom_requis"))
    if len(nom) > NOM_MAX:
        raise ValidationError(libelle("mcp.jetons.nom_long", max=NOM_MAX))
    try:
        jours = int(jours)
    except (TypeError, ValueError):
        jours = 0
    if jours not in durees_proposees(reglage):
        raise ValidationError(libelle("mcp.jetons.duree_invalide"))
    from referentiel.models import Utilisateur

    Utilisateur.objects.select_for_update().filter(pk=utilisateur.pk).first()  # relu sous verrou : pas de 11e jeton à deux
    if actifs(utilisateur).count() >= JETONS_MAX:
        raise ValidationError(libelle("mcp.jetons.trop", max=JETONS_MAX))
    clair = PREFIXE + secrets.token_urlsafe(32)
    from espaces.models import Compte

    # mot de passe du registre commun (celui que relit ``authentifier``) ; la copie de l'espace s'il manque
    mdp = Compte.objects.filter(pk=utilisateur.pk).values_list("password", flat=True).first()
    if mdp is None:
        mdp = Utilisateur.objects.filter(pk=utilisateur.pk).values_list("password", flat=True).first()
    j = JetonMCP.objects.create(utilisateur=utilisateur, nom=nom, empreinte=empreinte(clair), debut=clair[:10],
                                expire_le=timezone.now() + datetime.timedelta(days=jours), mdp_empreinte=empreinte_mdp(mdp))
    Journal.ecrire(utilisateur, "jeton_mcp", j, "mcp_jeton_cree", "", f"{nom} ({j.debut}…) → {j.expire_le:%Y-%m-%d}")
    return clair, j


@ESP.atomic
def revoquer(par, pk, tous=False):
    """Révoque un jeton de la personne (``tous`` : n'importe quel jeton de l'espace, pour l'administrateur). Relu sous
    verrou : révoquer deux fois ne fait rien de plus. Renvoie le jeton, ou None s'il n'existe pas pour elle."""
    qs = JetonMCP.objects.select_for_update()
    if not tous:
        qs = qs.filter(utilisateur=par)
    try:
        j = qs.filter(pk=int(pk)).first()
    except (TypeError, ValueError):
        return None
    if j is None:
        return None
    if j.revoque_le is None:
        j.revoque_le, j.revoque_par = timezone.now(), par
        j.save(update_fields=["revoque_le", "revoque_par"])
        Journal.ecrire(par, "jeton_mcp", j, "mcp_jeton_revoque", f"{j.nom} ({j.debut}…)", "")
    return j


class JetonRefuse(Exception):
    """Jeton absent ou refusé : un seul message pour toutes les causes (``cause`` : pour le journal du serveur)."""

    def __init__(self, cause):
        super().__init__(cause)
        self.cause = cause


def lire_entete(valeur):
    """Jeton d'un en-tête « Authorization: Bearer … », ou ""."""
    morceaux = (valeur or "").split()
    if len(morceaux) == 2 and morceaux[0].lower() == "bearer":
        return morceaux[1]
    return ""


def authentifier(clair):
    """(utilisateur, jeton) pour un jeton valide dans l'espace courant ; ``JetonRefuse`` sinon."""
    from referentiel.auth import EmailOuIdentifiant

    if not clair or not clair.startswith(PREFIXE) or len(clair) > 200:
        raise JetonRefuse("absent ou mal formé")
    j = JetonMCP.objects.filter(empreinte=empreinte(clair)).first()
    if j is None:
        raise JetonRefuse("inconnu dans cet espace")
    if j.revoque_le is not None:
        raise JetonRefuse(f"révoqué (jeton n° {j.pk})")
    if j.expire_le <= timezone.now():
        raise JetonRefuse(f"expiré (jeton n° {j.pk})")
    u = EmailOuIdentifiant().get_user(j.utilisateur_id)  # copie active ici, compte actif au registre, même e-mail
    if u is None:
        raise JetonRefuse(f"compte désactivé ou absent (jeton n° {j.pk})")
    if u.doit_changer_mdp:
        raise JetonRefuse(f"mot de passe provisoire à remplacer (jeton n° {j.pk})")
    if not secrets.compare_digest(j.mdp_empreinte, empreinte_mdp(u.password)):
        raise JetonRefuse(f"mot de passe changé depuis la création (jeton n° {j.pk})")
    return u, j


# ---------------------------------------------------------------- mot de passe changé : jetons révoqués
def avant_enregistrement_compte(sender, instance, raw=False, using=None, update_fields=None, **kwargs):
    """``pre_save`` d'une copie de compte : note un mot de passe changé (« change ») ou seulement haché de nouveau
    (« meme » : même mot de passe, par exemple après une mise à jour de Django, qui recalcule le hachage à la connexion).
    Branché après celui des espaces (ordre de ``INSTALLED_APPS``) : le mot de passe comparé est celui qui sera écrit."""
    if raw or instance._state.adding or instance.pk is None:
        return
    if update_fields is not None and "password" not in update_fields:
        return
    ancien = type(instance).objects.using(using).filter(pk=instance.pk).values_list("password", flat=True).first()
    if ancien is None or ancien == instance.password:
        return
    instance._mcp_mdp = ("meme" if meme_mot_de_passe(instance, ancien) else "change", ancien)


def meme_mot_de_passe(instance, ancien):
    """Vrai si le nouveau hachage de ``instance`` est celui du même mot de passe que ``ancien`` : mot de passe en clair
    donné à ``set_password`` (gardé jusqu'à l'enregistrement) qui correspond à l'ancien hachage ; sans lui (Django efface
    le mot de passe en clair quand il recalcule un hachage dépassé à la connexion) : ancien hachage dépassé, nouveau
    hachage à jour."""
    from django.contrib.auth.hashers import check_password, get_hasher, identify_hasher

    brut = getattr(instance, "_password", None)
    if brut is not None:
        return check_password(brut, ancien)
    prefere = get_hasher("default")
    try:  # la règle de ``check_password`` de Django pour recalculer un hachage
        depasse = identify_hasher(ancien).algorithm != prefere.algorithm or prefere.must_update(ancien)
        a_jour = identify_hasher(instance.password).algorithm == prefere.algorithm and not prefere.must_update(instance.password)
    except ValueError:  # hachage inconnu ou inutilisable
        return False
    return depasse and a_jour


def suivre_hachage(alias, pk, ancien, nouveau):
    """Même mot de passe haché de nouveau sans enregistrer le compte (connexion avec un hachage dépassé,
    ``referentiel.auth`` : ``update()``, donc aucun signal) : l'empreinte gardée avec les jetons de la personne dans la
    base ``alias`` suit, pour ceux qui portaient celle de l'ancien hachage (un jeton déjà refusé le reste). Un espace
    sans la table ou illisible : rien (ses jetons sont refusés, la connexion n'échoue pas)."""
    from django.db import DatabaseError, transaction

    try:
        with transaction.atomic(using=alias):
            JetonMCP.objects.using(alias).filter(utilisateur_id=pk, mdp_empreinte=empreinte_mdp(ancien)).update(
                mdp_empreinte=empreinte_mdp(nouveau))
    except DatabaseError:
        journal.exception("MCP: tokens of account %s not updated in %s after a password rehash", pk, alias)


def apres_enregistrement_compte(sender, instance, raw=False, using=None, **kwargs):
    """``post_save`` d'une copie de compte : mot de passe changé (Mon compte, réinitialisation par un administrateur,
    commande de gestion, démo…) → tous les jetons actifs de la personne révoqués, dans chaque espace ouvert où elle a
    une copie, avec une ligne au journal de cet espace par jeton. Même mot de passe haché de nouveau : l'empreinte
    gardée avec les jetons suit. Un espace fermé ou illisible à ce moment : ses jetons sont refusés quand même
    (``authentifier`` compare l'empreinte du mot de passe)."""
    etat = instance.__dict__.pop("_mcp_mdp", None)
    if raw or not etat:
        return
    from django.db import DatabaseError, transaction

    from espaces.comptes import copies_ailleurs

    nature, ancien = etat
    acteur = ESP.acteur_courant() or instance.pk
    maintenant = timezone.now()
    with ESP.toutes_les_bases():
        for alias in [using] + copies_ailleurs(instance.pk, using):
            try:
                with transaction.atomic(using=alias):
                    qs = JetonMCP.objects.using(alias).select_for_update().filter(utilisateur_id=instance.pk)
                    if nature == "meme":
                        qs.filter(mdp_empreinte=empreinte_mdp(ancien)).update(mdp_empreinte=empreinte_mdp(instance.password))
                        continue
                    jetons = list(qs.filter(revoque_le__isnull=True, expire_le__gt=maintenant))
                    if not jetons:
                        continue
                    par = acteur if type(instance).objects.using(alias).filter(pk=acteur).exists() else None
                    JetonMCP.objects.using(alias).filter(pk__in=[j.pk for j in jetons]).update(revoque_le=maintenant,
                                                                                               revoque_par_id=par)
                    Journal.objects.using(alias).bulk_create([
                        Journal(utilisateur_id=par, action="jeton_mcp", objet="JetonMCP", objet_id=str(j.pk),
                                champ="mcp_jeton_revoque_mdp", avant=f"{j.nom} ({j.debut}…)", apres="") for j in jetons])
            except DatabaseError:  # espace sans la table (pas encore migré) ou illisible : l'empreinte refusera ses jetons
                journal.exception("MCP: tokens of account %s not revoked in %s after a password change", instance.pk, alias)
