"""Alertes par e-mail de la santé de l'installation : l'outil prévient lui-même quand il va mal, sans supervision à
brancher (Administration › Paramètres › Santé, « Alertes par e-mail »).

Une seule source de vérité : les lignes de la page Santé (``sante_installation.constats``), mesurées dans chaque espace
actif ; une ligne alerte quand son cas le dit (``alerte`` non vide). S'y ajoutent les problèmes signalés par d'autres
parties de l'outil (``signaler`` / ``resoudre``), montrés aussi sur la page.

Règles (pas de bruit) :
- un passage au plus toutes les ``INTERVALLE`` (15 minutes) pour toute l'installation, réservé par une écriture
  conditionnelle au registre commun (``_reserver``) : plusieurs processus, plusieurs espaces, jamais deux passages ;
- un e-mail quand un problème apparaît ; ce qui change dans un même passage part dans un seul e-mail qui liste tout ;
- un rappel au plus une fois par ``RAPPEL`` (24 h) tant qu'un problème dure, un seul e-mail pour tous ;
- « résolu » quand le problème a disparu à ``ABSENCES`` passages de suite (un problème qui va et vient ne part pas à
  chaque passage) ;
- état gardé au registre commun (``espaces.EtatAlertes``), hors des bases des espaces : une restauration d'espace ne
  fait rien repartir.

Si l'e-mail ne part pas (serveur d'envoi en panne) : rien ne plante, l'échec est journalisé (``resume_technique``) et
noté pour la page Santé, l'état n'avance pas et le passage suivant réessaie. Rien n'est envoyé sans réglage
(``envoi_emails.envoi_actif``). Alertes allumées d'office sur une installation neuve, éteintes sur une installation
existante tant qu'un administrateur ne les allume pas (``reglage``, ``installation_neuve``). L'outil n'appelle jamais
rien d'autre que le serveur d'envoi réglé.

Mode d'emploi pour une autre partie de l'outil (mise à jour automatique, copie externe des sauvegardes…) :

    from parametres import alertes
    alertes.signaler("copie_externe", "admin.copie.titre", "admin.copie.echec", "admin.copie.echec_quoi", {"quand": …})
    alertes.resoudre("copie_externe")

Les textes sont des clés de libellé (rendues dans la langue de chaque destinataire) ; ``espace`` limite le problème à un
espace ; ``detail`` (pour l'IT) n'est montré que sur la page, jamais dans un e-mail."""
import datetime
import logging
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from espaces import contexte as ESP

from . import envoi_emails as EE
from .libelles import libelle

journal = logging.getLogger("reporting.alertes")

INTERVALLE = datetime.timedelta(minutes=15)
RAPPEL = datetime.timedelta(hours=24)
ABSENCES = 2  # passages de suite sans le problème avant de le dire résolu
DEMARRAGE = 120  # secondes après le lancement d'une boucle planifiée avant son premier passage (les autres démarrent)
ADRESSES_MAX = 20
SIGNALE = "signale"


# ---------------------------------------------------------------- réglage (registre commun)
MIGRATION_ALERTES = ("espaces", "0003_alertes_sante")  # celle qui a créé le réglage des alertes


def installation_neuve():
    """Vrai si l'installation a été créée par une version qui a déjà les alertes (décision du produit : allumées d'office
    sur une installation neuve, inchangées sur une installation existante qui se met à jour). Sans migration ni écriture,
    d'après le registre commun : la migration des alertes y est appliquée, et la ligne de l'installation
    (``Installation.creee_le``) comme chaque compte (``Compte.date_joined``, repris tel quel d'une base plus ancienne
    par l'amorçage) sont nés au plus tôt à ce moment-là. Une installation existante a, d'avant sa mise à jour, sa ligne
    d'installation ou ses comptes ; une base ou un registre restaurés gardent leurs dates. Dans le doute (registre
    illisible, migration absente) : faux."""
    from django.db import connections
    from django.db.migrations.recorder import MigrationRecorder

    from espaces.models import Compte, Installation

    try:
        appliquee = (MigrationRecorder(connections[ESP.COMMUN]).migration_qs
                     .filter(app=MIGRATION_ALERTES[0], name=MIGRATION_ALERTES[1]).values_list("applied", flat=True).first())
        if appliquee is None or Installation.objects.filter(creee_le__lt=appliquee).exists():
            return False
        return not Compte.objects.filter(date_joined__lt=appliquee).exists()
    except DatabaseError:
        return False


def reglage():
    """Le réglage enregistré ; sans ligne (aucun administrateur ne l'a encore enregistré), les valeurs par défaut :
    alertes allumées sur une installation neuve (``installation_neuve``), éteintes sur une installation existante ou
    quand le registre n'est pas encore à jour pendant une mise à jour. ``par_defaut`` : vrai si la ligne manque."""
    from espaces.models import ReglageAlertes

    try:
        r = ReglageAlertes.objects.filter(pk=1).first()
        neuve = r is None and installation_neuve()
    except DatabaseError:
        r, neuve = None, False
    if r is None:
        r = ReglageAlertes(pk=1, actives=neuve)
    r.par_defaut = r._state.adding
    return r


def pourquoi(r, court=False):
    """Pourquoi les alertes sont dans cet état (page Santé), dans la langue en cours : par défaut, installation neuve ou
    existante (``court`` : sans renvoyer au formulaire, pour qui ne le voit pas) ; sinon qui l'a réglé et quand (vide si
    la personne n'est plus connue)."""
    from collecte.dates_courtes import date_heure_courte
    from espaces.models import Compte

    if r.par_defaut:
        cle = "admin.alertes.pourquoi." + ("neuve" if r.actives else "existante") + ("_court" if court else "")
        return libelle(cle)
    c = Compte.objects.filter(pk=r.modifie_par).first() if r.modifie_par and r.modifie_le else None
    if c is None:
        return ""
    nom = f"{c.first_name} {c.last_name}".strip() or c.email
    return libelle("admin.alertes.pourquoi.modifiees", nom=nom, quand=date_heure_courte(r.modifie_le))


def lire_adresses(texte):
    """(adresses valides sans doublon, adresses refusées) d'un texte : une adresse par ligne, ou séparées par des
    virgules ou des points-virgules."""
    bonnes, refusees, vues = [], [], set()
    for morceau in (texte or "").replace(";", "\n").replace(",", "\n").splitlines():
        a = morceau.strip()
        if not a:
            continue
        try:
            validate_email(a)
        except ValidationError:
            refusees.append(a)
            continue
        if a.lower() not in vues:
            vues.add(a.lower())
            bonnes.append(a)
    return bonnes, refusees


def enregistrer(par, actives, aux_comptes, adresses):
    """Enregistre le réglage (relu sous verrou) ; renvoie les changements [(champ, avant, après)] pour l'historique.
    Alertes rallumées : ce qui a été dit avant est oublié (les problèmes en cours partent dans le premier e-mail)."""
    from espaces.models import EtatAlertes, ReglageAlertes

    adresses = "\n".join(lire_adresses(adresses)[0])
    with transaction.atomic(using=ESP.COMMUN):
        premier = False
        if not ReglageAlertes.objects.filter(pk=1).exists():  # premier enregistrement : on part de l'état montré
            premier = ReglageAlertes.objects.get_or_create(pk=1, defaults={"actives": reglage().actives})[1]
        r = ReglageAlertes.objects.select_for_update().get(pk=1)
        allumees = actives and not r.actives
        changements = []
        for champ, apres in (("actives", bool(actives)), ("aux_comptes", bool(aux_comptes)), ("adresses", adresses)):
            avant = getattr(r, champ)
            if avant != apres:
                changements.append((champ, avant, apres))
                setattr(r, champ, apres)
        if changements or premier:  # premier enregistrement sans changement : le choix par défaut est confirmé
            r.modifie_le, r.modifie_par = timezone.now(), getattr(par, "pk", None)
            r.save()
        if allumees:
            EtatAlertes.objects.update_or_create(pk=1, defaults={"problemes": {}, "envoye_le": None})
    return changements


def etat():
    from espaces.models import EtatAlertes

    try:
        return EtatAlertes.objects.filter(pk=1).first() or EtatAlertes(pk=1)
    except DatabaseError:
        return EtatAlertes(pk=1)


# ---------------------------------------------------------------- destinataires
def comptes_permis():
    """[(adresse, langue, nom)] des comptes actifs qui voient le détail de l'installation (même règle que
    ``sante_installation.detail_installation_permis``) : administrateurs de l'espace principal et gestionnaires des
    espaces. Langue : celle du compte dans l'espace principal (vide : langue de l'installation)."""
    from espaces.models import Compte
    from referentiel.models import Utilisateur

    with ESP.activer(ESP.PRINCIPAL):
        copies = {u["pk"]: u for u in Utilisateur.objects.values("pk", "email", "langue", "first_name", "last_name",
                                                                  "is_active", "role", "is_superuser")}
    comptes = {c["pk"]: c for c in Compte.objects.values("pk", "email", "actif", "gestionnaire", "first_name", "last_name")}
    sortie, vues = [], set()
    for pk, u in copies.items():
        c = comptes.get(pk)
        if u["is_active"] and (u["is_superuser"] or u["role"] == Utilisateur.Role.ADMIN) and (c is None or c["actif"]):
            sortie.append((u["email"], u["langue"], f"{u['first_name']} {u['last_name']}".strip() or u["email"]))
            vues.add(pk)
    for pk, c in comptes.items():
        if c["gestionnaire"] and c["actif"] and pk not in vues:
            u = copies.get(pk) or {}
            sortie.append((c["email"], u.get("langue", ""), f"{c['first_name']} {c['last_name']}".strip() or c["email"]))
    return sorted((s for s in sortie if s[0]), key=lambda s: s[0].lower())


def destinataires(r=None):
    """[(adresse, langue)] sans doublon : les comptes permis (si le réglage le dit), puis les adresses saisies (langue
    de l'installation)."""
    r = r or reglage()
    sortie, vues = [], set()
    for adresse, langue, _ in (comptes_permis() if r.aux_comptes else []):
        if adresse.lower() not in vues:
            vues.add(adresse.lower())
            sortie.append((adresse, langue))
    for adresse in lire_adresses(r.adresses)[0]:
        if adresse.lower() not in vues:
            vues.add(adresse.lower())
            sortie.append((adresse, ""))
    return sortie


# ---------------------------------------------------------------- problèmes signalés par une autre partie de l'outil
def signaler(cle, titre, constat, quoi="", params=None, etat="panne", espace="", detail=""):
    """Déclare (ou met à jour) un problème : clé stable (« copie_externe »), clés de libellé du titre, du constat et de
    ce qu'il faut faire, paramètres des libellés, état (« panne » ou « regarder »), espace concerné (vide : toute
    l'installation), détail pour l'IT (page seulement). Montré sur la page Santé et envoyé au passage suivant."""
    from espaces.models import ProblemeSignale

    from . import sante_installation as SI

    if etat not in (SI.PANNE, SI.A_REGARDER):
        raise ValueError(etat)
    maintenant = timezone.now()
    ProblemeSignale.objects.update_or_create(cle=cle, defaults={
        "titre": titre, "constat": constat, "quoi": quoi, "params": params or {}, "etat": etat, "espace": espace or "",
        "detail": (detail or "")[:300], "modifie_le": maintenant})


def resoudre(cle):
    """Le problème ``cle`` a disparu (« résolu » dans l'e-mail suivant). Sans effet s'il n'était pas signalé."""
    from espaces.models import ProblemeSignale

    ProblemeSignale.objects.filter(cle=cle).delete()


def lignes_signalees(codes, permis):
    """Lignes de la page Santé des problèmes signalés : ceux de toute l'installation et ceux des espaces ``codes``."""
    from espaces.models import Espace, ProblemeSignale

    from . import sante_installation as SI

    try:
        problemes = list(ProblemeSignale.objects.filter(Q(espace="") | Q(espace__in=list(codes))).order_by("depuis", "cle"))
        noms = dict(Espace.objects.values_list("code", "nom")) if permis else {}
    except DatabaseError:
        return []
    sortie = []
    for p in problemes:
        params = p.params if isinstance(p.params, dict) else {}
        constat = libelle(p.constat, **params)
        if p.espace and permis and p.espace != ESP.code_courant():
            constat = f"{noms.get(p.espace, p.espace)} – {constat}"
        ligne = SI.ligne_sante(f"signal-{p.cle}", p.etat, constat, libelle(p.quoi, **params) if p.quoi else "",
                          p.detail if permis else "", alerte=SIGNALE, portee=SI.ESPACE if p.espace else SI.INSTALLATION,
                          titre=libelle(p.titre, **params))
        ligne["titre_cle"], ligne["titre_params"] = p.titre, params
        sortie.append(ligne)
    return sortie


# ---------------------------------------------------------------- mesure : les lignes qui alertent, dans chaque espace
def _cle(code, ligne):
    if ligne["alerte"] == SIGNALE:
        return f"{ligne['cle']}" if ligne["portee"] == "installation" else f"{code}:{ligne['cle']}"
    base = f"{ligne['cle']}.{ligne['alerte']}"
    return base if ligne["portee"] == "installation" else f"{code}:{base}"


def problemes_actuels():
    """{clé: (ligne, code de l'espace)} des lignes qui alertent, dans la langue en cours, pour tous les espaces actifs.
    Un espace qu'on ne peut pas mesurer (base injoignable) donne la ligne « Base de données » en panne, comme la page."""
    from . import sante_installation as SI
    from . import sauvegardes as SV

    sortie = {}
    for code in ESP.codes_planifies(journal):
        try:
            with ESP.activer(code):
                if SV.base_vide():
                    continue
                lignes = SI.constats(True, codes=[code])
        except Exception:  # noqa: BLE001 - base de l'espace injoignable : dite comme la ligne « Base de données »
            journal.exception("Health checks for the email alerts failed (space \"%s\")", code)
            lignes = [SI.ligne_sante("base", SI.PANNE, libelle("admin.sante.base.panne"), libelle("admin.sante.base.panne_quoi"),
                                alerte="panne")]
        for ligne in lignes:
            if ligne["alerte"]:
                sortie.setdefault(_cle(code, ligne), (ligne, code))
    return sortie


def _titre_cle(ligne):
    return ligne.get("titre_cle") or f"admin.sante.{ligne['cle']}.titre", ligne.get("titre_params") or {}


# ---------------------------------------------------------------- passage
def _reserver(maintenant):
    """Réserve le passage pour tout le monde (processus, espaces, machines) : écriture conditionnelle de ``passage_le``
    (sous SQLite comme sous PostgreSQL, une seule réussit). Faux si un passage a eu lieu depuis moins de ``INTERVALLE``
    ou si un autre processus écrit en ce moment."""
    from espaces.models import EtatAlertes

    try:
        EtatAlertes.objects.get_or_create(pk=1)
        libre = (Q(passage_le__isnull=True) | Q(passage_le__lte=maintenant - INTERVALLE + datetime.timedelta(seconds=30))
                 | Q(passage_le__gt=maintenant + datetime.timedelta(hours=1)))  # horloge remise en arrière
        return EtatAlertes.objects.filter(libre, pk=1).update(passage_le=maintenant) == 1
    except DatabaseError:
        return False


def _langue_installation():
    from . import langues as L

    with ESP.activer(ESP.PRINCIPAL):
        return L.interface_de("")


def passage(maintenant=None):
    """Un passage des alertes : mesure, compare à ce qui a déjà été dit, envoie au plus un e-mail par destinataire,
    note l'état. Renvoie un résumé {fait, nouveaux, toujours, resolus, envoyes, erreur} (journal, tests)."""
    from espaces.models import EtatAlertes

    from . import langues as L

    maintenant = maintenant or timezone.now()
    r = reglage()
    if not r.actives:
        return {"fait": False, "raison": "off"}
    if not EE.envoi_actif():
        return {"fait": False, "raison": "no_smtp"}
    if not _reserver(maintenant):
        return {"fait": False, "raison": "busy"}
    langue = _langue_installation()
    with L.activer_interface(langue):
        actuels = problemes_actuels()
    e = EtatAlertes.objects.get(pk=1)
    connus = {k: dict(v) for k, v in (e.problemes or {}).items() if isinstance(v, dict)}
    iso = maintenant.isoformat()
    nouveaux, toujours, resolus = [], [], []
    for k, (ligne, code) in actuels.items():
        if k in connus:
            connus[k].update({"absent": 0, "vu_le": iso})
            toujours.append(k)
        else:
            titre, params = _titre_cle(ligne)
            connus[k] = {"depuis": iso, "vu_le": iso, "absent": 0, "cle": ligne["cle"], "titre": titre, "params": params,
                         "espace": code if ligne["portee"] == "espace" else ""}
            nouveaux.append(k)
    en_cours = {(v["espace"], v["cle"]) for k, v in connus.items() if k in actuels}
    for k in [k for k in connus if k not in actuels]:
        v = connus[k]
        v["absent"] = v.get("absent", 0) + 1
        if (v.get("espace", ""), v.get("cle")) in en_cours:
            del connus[k]  # même ligne, autre cas : le nouveau cas est annoncé, l'ancien n'est pas « résolu »
        elif v["absent"] >= ABSENCES:
            resolus.append(connus.pop(k))
    rappel = bool(toujours) and (e.envoye_le is None or maintenant - e.envoye_le >= RAPPEL)
    resume = {"fait": True, "nouveaux": sorted(nouveaux), "toujours": sorted(toujours),
              "resolus": sorted(v["cle"] for v in resolus), "envoyes": 0, "erreur": ""}
    if not (nouveaux or resolus or rappel):
        EtatAlertes.objects.filter(pk=1).update(problemes=connus)
        return resume
    dest = destinataires(r)
    if not dest:
        journal.warning("Email alerts: no recipient (Settings > Health): %s problem(s) not sent", len(actuels))
        resume["erreur"] = "no_recipient"
        return resume  # état inchangé : tout partira quand un destinataire sera réglé

    par_langue = {langue: actuels}

    def contenu():  # dans la langue en cours (celle du destinataire) ; mesure refaite une fois par langue
        if L.interface() not in par_langue:
            par_langue[L.interface()] = {**actuels, **{k: v for k, v in problemes_actuels().items() if k in actuels}}
        lignes = par_langue[L.interface()]
        avec = [(lignes[k][0], connus[k]) for k in nouveaux]
        encore = [(lignes[k][0], connus[k]) for k in toujours]
        return rediger(avec, encore, resolus, maintenant=maintenant)

    envoyes, erreur = _envoyer(dest, contenu)
    resume["envoyes"] = envoyes
    if erreur is not None:
        _noter_echec(erreur, maintenant)
        resume["erreur"] = EE.cle_cause(erreur)
    if not envoyes:
        return resume  # rien n'est parti : le passage suivant refait le même e-mail
    EtatAlertes.objects.filter(pk=1).update(problemes=connus, envoye_le=maintenant)
    journal.info("Email alerts sent to %s recipient(s): %s new, %s still open, %s resolved", envoyes, len(nouveaux),
                 len(toujours), len(resolus))
    return resume


def _noter_echec(erreur, maintenant):
    from espaces.models import EtatAlertes

    try:
        EtatAlertes.objects.update_or_create(pk=1, defaults={"echec_le": maintenant, "echec": EE.cle_cause(erreur)[:40],
                                                             "echec_resume": EE.resume_technique(erreur)[:200]})
    except DatabaseError:
        pass


def _envoyer(dest, contenu, timeout=None):
    """Envoie à chaque destinataire, dans sa langue, le message de ``contenu()`` ; une seule connexion. Renvoie (nombre
    envoyé, dernière erreur ou None). Toute erreur d'envoi est une ``OSError`` (``envoi_emails``) : journalisée avec le
    résumé technique, jamais la réponse du serveur."""
    from . import langues as L

    r = EE.reglage()
    try:
        connexion, expediteur = EE.connexion_envoi(timeout=timeout)
        connexion.open()
    except OSError as e:
        journal.warning("Email alerts not sent through %s:%s (%s): next try at the next check", r.hote or "-", r.port,
                        EE.resume_technique(e))
        return 0, e
    envoyes, erreur = 0, None
    try:
        for adresse, langue in dest:
            with L.activer_interface(langue or None):
                sujet, texte = contenu()
            try:
                EmailMessage(sujet, texte, expediteur, [adresse], connection=connexion).send()
                envoyes += 1
            except OSError as e:
                erreur = e
                journal.warning("Email alert to %s through %s:%s failed (%s)", adresse, r.hote or "-", r.port,
                                EE.resume_technique(e))
    finally:
        try:
            connexion.close()
        except OSError:
            pass
    return envoyes, erreur


_premier = None


def passage_planifie():
    """Appelé à chaque tour des boucles planifiées (``backup --schedule``, ``check_data --schedule``) : un passage si
    l'heure est venue (``_reserver``), jamais d'erreur qui arrête la boucle. Pas de passage pendant les ``DEMARRAGE``
    premières secondes de la boucle : au redémarrage, les autres tâches posent d'abord leur signe de vie."""
    global _premier
    maintenant = time.monotonic()
    if _premier is None:
        _premier = maintenant
    if maintenant - _premier < DEMARRAGE:
        return None
    try:  # dernier passage de la tâche de mise à jour automatique de la machine : problème signalé ou résolu
        from . import mise_a_jour_auto

        mise_a_jour_auto.synchroniser_alertes()
    except Exception:  # noqa: BLE001 - on réessaiera au tour suivant
        journal.exception("Automatic update: alerts not refreshed")
    try:
        return passage()
    except Exception:  # noqa: BLE001 - on réessaiera au tour suivant
        journal.exception("Email alerts failed")
        return None


# ---------------------------------------------------------------- e-mail
def nom_installation():
    """« Probant (Exemplia) » : nom de l'outil et de la structure, réglés dans l'identité de l'espace principal."""
    from .models import Instance

    with ESP.activer(ESP.PRINCIPAL):
        i = Instance.courante()
        return f"{i.titre} ({i.nom})" if i.nom and i.nom != i.titre else i.titre


def lien_sante():
    """Adresse de la page Santé (``PUBLIC_URL``) ; vide si l'adresse publique n'est pas connue."""
    if not settings.URL_PUBLIQUE:
        return ""
    with ESP.activer(ESP.PRINCIPAL):
        return settings.URL_PUBLIQUE.rstrip("/") + reverse("parametres:sante_installation")


def _noms_espaces():
    """{code: nom} des espaces actifs s'il y en a plusieurs (sinon {} : l'e-mail ne nomme aucun espace)."""
    from espaces.models import Espace

    try:
        codes = ESP.codes_actifs()
    except DatabaseError:
        return {}
    return dict(Espace.objects.filter(code__in=codes).values_list("code", "nom")) if len(codes) > 1 else {}


def _date(iso):
    from . import sante_installation as SI

    try:
        return SI.quand(datetime.datetime.fromisoformat(iso))
    except (TypeError, ValueError):
        return ""


def _titre_section(cle):
    t = libelle(cle)
    return f"{t}\n{'-' * len(t)}"


def rediger(nouveaux, toujours, resolus, essai=False, auteur="", maintenant=None):
    """(objet, texte brut) dans la langue en cours. ``nouveaux`` et ``toujours`` : [(ligne de la page Santé, état noté
    {depuis, espace})] ; ``resolus`` : [état noté {titre, params, espace, depuis}]. Ni donnée des espaces, ni chemin du
    disque, ni détail pour l'IT : seulement le titre, l'état, le constat et quoi faire de la page Santé."""
    maintenant = maintenant or timezone.now()
    installation = nom_installation()
    noms = _noms_espaces()
    if essai:
        sujet = libelle("admin.alertes.mail.sujet.essai", installation=installation)
        intro = libelle("admin.alertes.mail.intro.essai", auteur=auteur)
    elif nouveaux:
        sujet = libelle("admin.alertes.mail.sujet.nouveaux", n=len(nouveaux), installation=installation)
        intro = libelle("admin.alertes.mail.intro.nouveaux", n=len(nouveaux))
    elif toujours:
        if resolus:
            sujet = libelle("admin.alertes.mail.sujet.resolus_reste", n=len(resolus), reste=len(toujours), installation=installation)
            intro = libelle("admin.alertes.mail.intro.resolus", n=len(resolus))
        else:
            sujet = libelle("admin.alertes.mail.sujet.rappel", n=len(toujours), installation=installation)
            intro = libelle("admin.alertes.mail.intro.rappel", n=len(toujours))
    else:
        sujet = libelle("admin.alertes.mail.sujet.resolus", n=len(resolus), installation=installation)
        intro = libelle("admin.alertes.mail.intro.resolus", n=len(resolus))

    def bloc(ligne, note):
        morceaux = [f"* {ligne['titre']} ({libelle('admin.sante.etat.' + ligne['etat'])})"]
        if note.get("espace") in noms:
            morceaux.append("  " + libelle("admin.alertes.mail.espace", espace=noms[note["espace"]]))
        morceaux.append(f"  {ligne['constat']}")
        if ligne.get("quoi"):
            morceaux.append("  " + libelle("admin.alertes.mail.quoi", quoi=ligne["quoi"]))
        if note.get("depuis"):
            morceaux.append("  " + libelle("admin.alertes.mail.depuis", quand=_date(note["depuis"])))
        return "\n".join(morceaux)

    parties = [intro]
    if nouveaux:
        parties.append(_titre_section("admin.alertes.mail.section.nouveaux") + "\n" + "\n\n".join(bloc(l, n) for l, n in nouveaux))
    if toujours:
        titre = "admin.alertes.mail.section.actuels" if essai else "admin.alertes.mail.section.toujours"
        parties.append(_titre_section(titre) + "\n" + "\n\n".join(bloc(l, n) for l, n in toujours))
    if essai and not toujours:
        parties.append(libelle("admin.alertes.mail.aucun"))
    if resolus:
        textes = []
        for v in resolus:
            t = [f"* {libelle(v.get('titre', ''), **(v.get('params') or {}))}"]
            if v.get("espace") in noms:
                t.append("  " + libelle("admin.alertes.mail.espace", espace=noms[v["espace"]]))
            t.append("  " + libelle("admin.alertes.mail.resolu", debut=_date(v.get("depuis")), fin=_date(maintenant.isoformat())))
            textes.append("\n".join(t))
        parties.append(_titre_section("admin.alertes.mail.section.resolus") + "\n" + "\n\n".join(textes))
    lien = lien_sante()
    parties.append(libelle("admin.alertes.mail.lien", url=lien) if lien else libelle("admin.alertes.mail.lien_sans"))
    parties.append(libelle("admin.alertes.mail.pourquoi"))
    return sujet.replace("\n", " ").strip(), "\n\n".join(parties) + "\n"


# ---------------------------------------------------------------- alerte d'essai (bouton de la page Santé)
def envoyer_essai(par):
    """Alerte d'essai aux destinataires enregistrés, avec les problèmes du moment ; n'avance pas l'état. Renvoie
    (nombre envoyé, message d'erreur en clair ou "")."""
    from . import langues as L

    if not EE.envoi_actif():
        return 0, libelle("admin.alertes.essai.sans_envoi")
    r = reglage()
    dest = destinataires(r)
    if not dest:
        return 0, libelle("admin.alertes.essai.sans_destinataire")
    if EE.reglage().source == EE.OUTIL:
        attente = EE.reserver_essai()  # même limite que l'e-mail de test, pour toute l'installation
        if attente:
            return 0, libelle("admin.hebergement.test.trop", n=attente)
    connus = etat().problemes or {}
    auteur = par.get_full_name() or par.email

    par_langue = {}

    def contenu():
        if L.interface() not in par_langue:
            par_langue[L.interface()] = problemes_actuels()
        actuels = par_langue[L.interface()]
        encore = [(ligne, {"depuis": (connus.get(k) or {}).get("depuis"), "espace": code if ligne["portee"] == "espace" else ""})
                  for k, (ligne, code) in actuels.items()]
        return rediger([], encore, [], essai=True, auteur=auteur)

    delai = EE.delai_essai()
    envoyes, erreur = _envoyer(dest, contenu, timeout=delai)
    if erreur is not None:
        _noter_echec(erreur, timezone.now())
        texte = libelle("admin.hebergement.test.echec", cause=EE.cause(erreur, delai), detail=EE.resume_technique(erreur))
        return envoyes, texte
    return envoyes, ""
