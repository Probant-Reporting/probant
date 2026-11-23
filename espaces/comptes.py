"""Comptes communs : le registre (``Compte``, base « commun ») fait foi pour l'identité et le mot de passe ; chaque
espace garde une copie du compte (``referentiel.Utilisateur``, même numéro) avec le rôle propre à cet espace.

- ``amorcer()`` : premier démarrage d'une installation existante (registre créé d'après l'espace principal).
- ``reconcilier()`` : remet le registre et les copies d'accord (après ``migrate`` et après toute restauration).
"""
import logging
import uuid

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connections
from django.utils import timezone

from . import contexte as E

journal = logging.getLogger("reporting.espaces")

COMMUNS = ["username", "email", "password", "first_name", "last_name", "doit_changer_mdp"]
ETATS_OUVERTS = ("actif",)


class ConflitInstallation(ImproperlyConfigured):
    pass


def codes_ouverts():
    """Codes des espaces dont les copies des comptes sont tenues à jour : le principal, puis les espaces actifs et
    disponibles. Un espace en création, archivé ou indisponible est remis d'accord par la réconciliation (fin de la
    création, réactivation, démarrage)."""
    from .models import Espace

    autres = Espace.objects.filter(etat__in=ETATS_OUVERTS).exclude(code=E.PRINCIPAL).values_list("code", flat=True)
    return [E.PRINCIPAL] + [c for c in autres if not E.indisponible(c)]


def role_index(u):
    return "admin" if u.is_superuser else u.role


def plus_grand_numero(code):
    """Plus grand numéro de copie dans un espace (0 si sa base est illisible)."""
    from referentiel.models import Utilisateur

    try:
        return Utilisateur.objects.using(E.declarer(code)).order_by("-pk").values_list("pk", flat=True).first() or 0
    except DatabaseError:
        journal.exception("Space \"%s\" unreadable (account numbers)", code)
        return 0


def remettre_sequence():
    """PostgreSQL : séquence des numéros de compte au-dessus du plus grand numéro, tous espaces confondus."""

    from .models import Compte

    c = connections[E.COMMUN]
    if c.vendor != "postgresql":
        return
    plus_grand = max([Compte.objects.order_by("-pk").values_list("pk", flat=True).first() or 0]
                     + [plus_grand_numero(code) for code in codes_ouverts()])
    with c.cursor() as cur:
        cur.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)", [Compte._meta.db_table, max(plus_grand, 1)])


def installation():
    """Ligne de l'installation au registre, ou None (registre pas encore créé : premier démarrage d'une mise à jour)."""
    from .models import Installation

    if Installation._meta.db_table not in connections[E.COMMUN].introspection.table_names():
        return None
    return Installation.objects.first()


# ---------------------------------------------------------------- amorçage
def amorcer(journal_sortie=None):
    """Registre d'une installation : identifiant, espace principal, marque de la base principale, comptes de l'espace
    principal (mêmes numéros, mêmes mots de passe). Idempotent ; rapide quand tout est déjà fait."""
    from referentiel.models import Utilisateur

    from .models import Compte, Espace, Installation, MarqueEspace

    with E.toutes_les_bases():
        marque = MarqueEspace.objects.using("default").first()
        inst = Installation.objects.first()
        if inst is None:
            inst = Installation.objects.create(identifiant=marque.installation if marque else uuid.uuid4().hex)
        if marque is None:
            MarqueEspace.objects.using("default").create(code=E.PRINCIPAL, installation=inst.identifiant)
        elif marque.code != E.PRINCIPAL or marque.installation != inst.identifiant:
            raise ConflitInstallation(
                f"The main database belongs to another space or another installation (space \"{marque.code}\", "
                f"installation {marque.installation}) than the shared registry (installation {inst.identifiant}). "
                "Check DATA_DIR and the configured database (see docs/spaces.md).")
        Espace.objects.get_or_create(code=E.PRINCIPAL, defaults={"nom": "Espace principal", "etat": Espace.Etat.ACTIF})
        premier = not Compte.objects.exists()
        connus = set(Compte.objects.values_list("pk", flat=True))
        nouveaux = []
        for u in Utilisateur.objects.using("default").order_by("pk"):
            if u.pk in connus:
                continue
            if Compte.objects.filter(email__iexact=u.email).exists() or Compte.objects.filter(username=u.username).exists():
                continue  # conflit : traité par la réconciliation
            nouveaux.append(Compte(pk=u.pk, actif=True, last_login=u.last_login, date_joined=u.date_joined,
                                   gestionnaire=premier and u.is_active and (u.is_superuser or u.role == "admin"),
                                   **{f: getattr(u, f) for f in COMMUNS}))
        if nouveaux:
            Compte.objects.bulk_create(nouveaux)
            if journal_sortie:
                journal_sortie(f"Shared registry: {len(nouveaux)} account(s) taken over from the main space.")
        _copier_sessions()
    reconcilier()


def _copier_sessions():
    """Sessions encore valides de l'espace principal (version d'avant les espaces) recopiées une fois dans le registre :
    personne n'est déconnecté par la mise à jour."""
    from django.contrib.sessions.models import Session

    base = connections["default"]
    if "django_session" not in base.introspection.table_names() or Session.objects.exists():
        return
    with base.cursor() as c:
        c.execute("SELECT session_key, session_data, expire_date FROM django_session WHERE expire_date > %s", [timezone.now()])
        lignes = c.fetchall()
    if lignes:
        Session.objects.bulk_create([Session(session_key=k, session_data=d, expire_date=x) for k, d, x in lignes],
                                    ignore_conflicts=True)


# ---------------------------------------------------------------- réconciliation
def reconcilier(codes=None):
    """Pour chaque espace ouvert : copies remises d'accord avec le registre (champs communs repris du registre), comptes
    manquants recréés (même numéro), conflits (e-mail déjà pris, numéro porté par une autre personne) : copie désactivée
    et notée au journal du serveur, jamais fusionnée en silence. Index des accès reconstruit. Idempotent."""
    from referentiel.models import Utilisateur

    from .models import Compte, Espace

    conflits = []
    with E.toutes_les_bases():
        for code in codes or codes_ouverts():
            alias = E.declarer(code)
            espace = Espace.objects.filter(code=code).first()
            comptes = {c.pk: c for c in Compte.objects.all()}
            for u in Utilisateur.objects.using(alias).order_by("pk"):
                c = comptes.get(u.pk)
                if c is None:
                    if Compte.objects.filter(email__iexact=u.email).exists() or Compte.objects.filter(username=u.username).exists():
                        conflits.append((code, u.pk, u.email, "e-mail or username already taken by another account"))
                        Utilisateur.objects.using(alias).filter(pk=u.pk).update(is_active=False)
                        continue
                    c = Compte.objects.create(pk=u.pk, actif=True, last_login=u.last_login, date_joined=u.date_joined,
                                              **{f: getattr(u, f) for f in COMMUNS})
                    comptes[c.pk] = c
                elif (c.email or "").lower() != (u.email or "").lower():
                    if u.is_active:
                        conflits.append((code, u.pk, u.email, f"number {u.pk} is in the registry for {c.email}"))
                        Utilisateur.objects.using(alias).filter(pk=u.pk).update(is_active=False)
                    continue
                else:
                    ecarts = {f: getattr(c, f) for f in COMMUNS if getattr(u, f) != getattr(c, f)}
                    if ecarts:
                        Utilisateur.objects.using(alias).filter(pk=u.pk).update(**ecarts)
            if espace is not None:
                indexer(espace, alias)
        remettre_sequence()
    for code, pk, email, motif in conflits:
        journal.error("Space \"%s\": account no. %s (%s) deactivated in this space, %s. To be settled by an administrator.",
                      code, pk, email, motif)
    return conflits


def indexer(espace, alias):
    """Index ``AccesEspace`` d'un espace remis d'accord avec ses copies : seules les lignes qui changent sont écrites
    (avant : tout supprimé puis recréé à chaque réconciliation, donc à chaque démarrage, avec de nouveaux numéros et un
    instant sans aucun accès). Index relu sous verrou, dans une transaction du registre."""
    from django.db import transaction

    from referentiel.models import Utilisateur

    from .models import AccesEspace, Compte

    connus = set(Compte.objects.values_list("pk", flat=True))
    voulues = {u.pk: (role_index(u), u.is_active)
               for u in Utilisateur.objects.using(alias).only("pk", "role", "is_superuser", "is_active") if u.pk in connus}
    with transaction.atomic(using=E.COMMUN):
        actuelles = {a.compte_id: a for a in AccesEspace.objects.select_for_update().filter(espace=espace)}
        AccesEspace.objects.filter(pk__in=[a.pk for pk, a in actuelles.items() if pk not in voulues]).delete()
        for pk, (role, actif) in voulues.items():
            a = actuelles.get(pk)
            if a is not None and (a.role, a.actif) != (role, actif):
                AccesEspace.objects.filter(pk=a.pk).update(role=role, actif=actif)
        # ignore_conflicts : une ligne écrite au même instant par l'enregistrement de la copie (même contenu) est gardée
        AccesEspace.objects.bulk_create([AccesEspace(compte_id=pk, espace=espace, role=role, actif=actif)
                                         for pk, (role, actif) in voulues.items() if pk not in actuelles],
                                        ignore_conflicts=True)


# ---------------------------------------------------------------- récepteurs : numéro unique, propagation
def refus_identite():
    from parametres.libelles import libelle

    return libelle("espaces.refus_identite")


def peut_modifier_identite(cible_pk, acteur=None):
    """Règle contre l'élévation de droits entre espaces : changer un champ commun (mot de passe, e-mail, nom) d'un compte
    est permis à une commande (pas d'acteur), à la personne elle-même, à un gestionnaire, ou (sauf pour le compte d'un
    gestionnaire) à un administrateur actif de chaque espace où ce compte a une copie, active ou désactivée, y compris dans un espace archivé, en création ou
    indisponible."""
    from referentiel.models import Utilisateur

    from .models import AccesEspace, Compte

    acteur = E.acteur_courant() if acteur is None else acteur
    if acteur is None or acteur == cible_pk:
        return True
    if acteur == E.ANONYME:
        return False
    with E.toutes_les_bases():
        if Compte.objects.filter(pk=acteur, actif=True, gestionnaire=True).exists():
            return True
        # l'identité d'un gestionnaire des espaces ne se change que par lui-même, un autre gestionnaire ou une commande :
        # sinon l'administrateur d'un espace où il a sa seule copie prendrait son compte, puis toute l'installation
        if Compte.objects.filter(pk=cible_pk, gestionnaire=True).exists():
            return False
        ouverts = codes_ouverts()
        for code in ouverts:
            alias = E.declarer(code)
            try:
                # copie active ou désactivée : une copie désactivée peut être réactivée plus tard, et celui qui aurait
                # choisi le mot de passe entrerait alors dans cet espace avec le rôle de la personne
                if not Utilisateur.objects.using(alias).filter(pk=cible_pk).exists():
                    continue
                if not Utilisateur.admins(Utilisateur.objects.using(alias).filter(pk=acteur, is_active=True)).exists():
                    return False
            except DatabaseError:  # base de cet espace illisible : on ne peut pas vérifier, donc refusé
                journal.exception("Space \"%s\" unreadable: identity change refused as a precaution", code)
                return False
        # espaces archivés, en création ou indisponibles : leur base peut être illisible, l'index des accès fait foi
        fermes = AccesEspace.objects.filter(compte_id=cible_pk).exclude(espace__code__in=ouverts)
        for espace_id in set(fermes.values_list("espace_id", flat=True)):
            if not AccesEspace.objects.filter(compte_id=acteur, espace_id=espace_id, role="admin", actif=True).exists():
                return False
    return True


def partage_ailleurs(cible_pk, alias=None):
    """Noms des autres espaces où ce compte a une copie, active ou désactivée (index des accès), sauf en création."""
    from .models import AccesEspace

    code = E.code_de(alias or E.alias_courant())
    noms = (AccesEspace.objects.filter(compte_id=cible_pk).exclude(espace__etat="creation").exclude(espace__code=code)
            .order_by("espace__rang", "espace__nom").values_list("espace__nom", flat=True))
    return list(dict.fromkeys(noms))


def _copies_ailleurs(pk, sauf_alias):
    """Alias des espaces ouverts (autres que ``sauf_alias``) qui ont une copie du compte ``pk``."""
    from referentiel.models import Utilisateur

    sortie = []
    for code in codes_ouverts():
        alias = E.declarer(code)
        try:
            if alias != sauf_alias and Utilisateur.objects.using(alias).filter(pk=pk).exists():
                sortie.append(alias)
        except DatabaseError:  # espace en défaut (le démarrage le marquera indisponible) : les autres continuent
            journal.exception("Space \"%s\" unreadable (shared accounts): skipped, to reconcile", code)
    return sortie


def copies_ailleurs(pk, sauf_alias):
    """Nom public de ``_copies_ailleurs`` (révocation des jetons d'assistant après un changement de mot de passe,
    serveur_mcp/jetons.py)."""
    return _copies_ailleurs(pk, sauf_alias)


def recopier_langue(utilisateur):
    """Langue choisie par la personne (barre du haut, Mon compte) recopiée dans les copies de son compte des autres
    espaces : c'est un choix de la personne, pas de l'espace (la page d'un autre espace, ou la session suivante, s'ouvre
    dans la même langue). Un espace illisible est ignoré (la langue n'y change pas)."""
    from referentiel.models import Utilisateur

    with E.toutes_les_bases():
        for alias in _copies_ailleurs(utilisateur.pk, utilisateur._state.db):
            try:
                Utilisateur.objects.using(alias).filter(pk=utilisateur.pk).update(langue=utilisateur.langue)
            except DatabaseError:
                journal.exception("Space \"%s\": language of account %s not copied", alias, utilisateur.pk)


def _langue_ailleurs(pk, sauf_alias):
    """Langue choisie par la personne dans une autre copie de son compte (« » : aucune). La langue n'est pas dans le
    registre commun : chaque copie la garde, ``recopier_langue`` les tient d'accord ; une copie nouvelle la reprend."""
    from referentiel.models import Utilisateur

    for alias in _copies_ailleurs(pk, sauf_alias):
        try:
            langue = Utilisateur.objects.using(alias).filter(pk=pk).values_list("langue", flat=True).first()
        except DatabaseError:
            continue
        if langue:
            return langue
    return ""


def _acces_fermes(pk):
    """Vrai si l'index garde un accès de ce compte à un espace archivé, en création ou indisponible : sa copie y est
    toujours (elle reviendra à la réactivation), le compte n'est donc pas orphelin."""
    from .models import AccesEspace

    return AccesEspace.objects.filter(compte_id=pk).exclude(espace__code__in=codes_ouverts()).exists()


def doit_devenir_gestionnaire(u, using):
    """Règle de la reprise (``amorcer``) appliquée à la création d'un compte et à un compte nommé administrateur : un
    administrateur actif de l'espace principal devient gestionnaire des espaces quand l'installation n'en a aucun
    d'actif (jamais d'installation sans gestionnaire possible). Avant la mise à jour, le premier compte du registre le
    devenait quel que soit son rôle ; l'administrateur d'un espace secondaire ne le devient jamais (il prendrait la main
    sur les autres espaces). Actif : la copie (``is_active``) et le compte du registre commun (``Compte.actif``, connexion
    permise dans tous les espaces ; un compte encore absent du registre, à sa création, est actif)."""
    from .models import Compte

    return (E.code_de(using) == E.PRINCIPAL and u.is_active and role_index(u) == "admin"
            and not (u.pk is not None and Compte.objects.filter(pk=u.pk, actif=False).exists())
            and not Compte.objects.filter(gestionnaire=True, actif=True).exists())


def _nouveau_numero(instance, using):
    """Copie nouvelle : rattachée au compte du registre qui a le même e-mail (sans tenir compte des majuscules), sinon
    un compte neuf est créé au registre. Seul le registre attribue les numéros."""
    from django.db import IntegrityError

    from referentiel.models import Utilisateur

    from .models import Compte

    c = Compte.objects.filter(email__iexact=instance.email).first() if instance.email else None
    if c is not None and not _copies_ailleurs(c.pk, using) and not _acces_fermes(c.pk) \
            and not Utilisateur.objects.using(using).filter(pk=c.pk).exists():
        c.delete()  # compte orphelin (enregistrement interrompu) : la nouvelle copie fait foi
        c = None
    if c is not None:
        if Utilisateur.objects.using(using).filter(pk=c.pk).exists():
            raise IntegrityError("An account already exists with this e-mail in this space.")
        if Utilisateur.objects.using(using).filter(username=c.username).exists():
            raise IntegrityError("Username already taken in this space.")
        for f in COMMUNS:
            setattr(instance, f, getattr(c, f))
        if not getattr(instance, "langue", ""):  # la langue est un choix de la personne : celle d'une autre copie
            instance.langue = _langue_ailleurs(c.pk, using)
        instance.pk = c.pk
        instance._espaces_rattache = True
        return
    if Compte.objects.filter(username=instance.username).exists():
        raise IntegrityError("UNIQUE constraint failed: username already taken (shared account registry).")
    c = Compte(gestionnaire=doit_devenir_gestionnaire(instance, using), **{f: getattr(instance, f) for f in COMMUNS})
    c.save()
    if _copies_ailleurs(c.pk, None):  # registre restauré trop ancien : numéro déjà porté par une copie
        plus_grand = max([c.pk] + [plus_grand_numero(code) for code in codes_ouverts()])
        journal.error("Shared registry behind: number %s already taken by a copy; account created as no. %s.",
                      c.pk, plus_grand + 1)
        Compte.objects.filter(pk=c.pk).update(pk=plus_grand + 1)
        c.pk = plus_grand + 1
        remettre_sequence()
    instance.pk = c.pk
    instance._espaces_rattache = False


def avant_enregistrement(sender, instance, raw=False, using=None, update_fields=None, **kwargs):
    """``pre_save`` d'une copie : numéro donné par le registre (copie nouvelle), ou champs communs reportés au registre
    avant l'enregistrement de la copie (règle contre l'élévation de droits vérifiée d'abord)."""
    if raw:
        return
    from django.core.exceptions import PermissionDenied
    from django.db import IntegrityError

    from referentiel.models import Utilisateur

    from .models import Compte

    with E.toutes_les_bases():
        if instance._state.adding and instance.pk is None:
            _nouveau_numero(instance, using)
            return
        champs = [f for f in COMMUNS if update_fields is None or f in update_fields]
        if not champs:
            return
        c = Compte.objects.filter(pk=instance.pk).first()
        ancien = Utilisateur.objects.using(using).filter(pk=instance.pk).values(*champs).first()
        if c is None:  # copie sans compte (base restaurée, chargée d'ailleurs) : recréé, même numéro
            if Compte.objects.filter(email__iexact=instance.email).exists() or Compte.objects.filter(username=instance.username).exists():
                raise IntegrityError("Account in conflict with the shared registry (e-mail or username already taken).")
            Compte.objects.create(pk=instance.pk, **{f: getattr(instance, f) for f in COMMUNS})
            remettre_sequence()
            instance._espaces_propager = list(COMMUNS)
            return
        ecarts = [f for f in champs if ancien is None or getattr(instance, f) != ancien[f]]
        for f in champs:
            if f not in ecarts:
                setattr(instance, f, getattr(c, f))  # copie en retard sur le registre : remise d'accord
        ecarts = [f for f in ecarts if getattr(instance, f) != getattr(c, f)]
        if not ecarts:
            return
        if not peut_modifier_identite(instance.pk):
            raise PermissionDenied(refus_identite())
        if "email" in ecarts and Compte.objects.filter(email__iexact=instance.email).exclude(pk=instance.pk).exists():
            raise IntegrityError("An account already exists with this e-mail (shared account registry).")
        if "username" in ecarts and Compte.objects.filter(username=instance.username).exclude(pk=instance.pk).exists():
            raise IntegrityError("Username already taken (shared account registry).")
        Compte.objects.filter(pk=instance.pk).update(**{f: getattr(instance, f) for f in ecarts})
        instance._espaces_propager = ecarts


def apres_enregistrement(sender, instance, created=False, raw=False, using=None, update_fields=None, **kwargs):
    """``post_save`` d'une copie : champs communs recopiés dans les copies des autres espaces (tous les espaces ouverts
    du registre), index des accès, dernière connexion au registre."""
    if raw:
        return
    from referentiel.models import Utilisateur

    from .models import AccesEspace, Compte, Espace

    with E.toutes_les_bases():
        champs = instance.__dict__.pop("_espaces_propager", None)
        if champs:
            valeurs = {f: getattr(instance, f) for f in champs}
            for alias in _copies_ailleurs(instance.pk, using):
                Utilisateur.objects.using(alias).filter(pk=instance.pk).update(**valeurs)
        if instance.last_login and (update_fields is None or "last_login" in update_fields):
            Compte.objects.filter(pk=instance.pk).exclude(last_login__gte=instance.last_login).update(last_login=instance.last_login)
        if update_fields is None or {"role", "is_active", "is_superuser"} & set(update_fields):
            if doit_devenir_gestionnaire(instance, using):
                Compte.objects.filter(pk=instance.pk).update(gestionnaire=True)
            espace = Espace.objects.filter(code=E.code_de(using)).first()
            if espace is not None:
                AccesEspace.objects.update_or_create(compte_id=instance.pk, espace=espace,
                                                     defaults={"role": role_index(instance), "actif": instance.is_active})


def apres_suppression(sender, instance, using=None, **kwargs):
    """``post_delete`` d'une copie : accès retiré de l'index ; plus aucune copie (ni dans un espace archivé, en création
    ou indisponible) : le compte quitte le registre."""
    from .models import AccesEspace, Compte

    with E.toutes_les_bases():
        AccesEspace.objects.filter(compte_id=instance.pk, espace__code=E.code_de(using)).delete()
        if not _copies_ailleurs(instance.pk, using) and not _acces_fermes(instance.pk):
            Compte.objects.filter(pk=instance.pk).delete()


def brancher():
    from django.db.models.signals import post_delete, post_save, pre_save

    from referentiel.models import Utilisateur

    pre_save.connect(avant_enregistrement, sender=Utilisateur, dispatch_uid="espaces.avant_enregistrement")
    post_save.connect(apres_enregistrement, sender=Utilisateur, dispatch_uid="espaces.apres_enregistrement")
    post_delete.connect(apres_suppression, sender=Utilisateur, dispatch_uid="espaces.apres_suppression")
