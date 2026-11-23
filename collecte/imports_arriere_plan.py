"""Gros imports de valeurs en arrière-plan (Import / Export › Importer).

Au-delà de ``IMPORT_ARRIERE_PLAN_LIGNES`` lignes (variable ``BACKGROUND_IMPORT_ROWS``, 5 000 par défaut), la
confirmation de l'aperçu ne fait plus l'import dans la requête (une page ne peut durer que 120 s) : elle crée une tâche
(``TacheImport``) et la personne suit l'avancement sur la page d'import, qu'elle peut quitter.

Qui exécute la tâche, sans nouveau service à installer :
- le planificateur ``python manage.py run_imports --schedule``, lancé comme les autres par l'image Docker
  (docker/entrypoint.sh) et par un worker Clever Cloud : il lit la file de chaque espace toutes les 2 s ;
- à défaut (développement, ``runserver``, version Windows portable), un fil du processus web, lancé à la création de la
  tâche quand aucun planificateur ne donne signe de vie (fichier ``.import-worker`` du dossier des données).
Une tâche n'est prise qu'une fois (mise à jour conditionnelle du statut), une seule à la fois par espace.

Robustesse : un fil compagnon note un battement toutes les ``BATTEMENT`` secondes ; une tâche « en cours » dont le
battement s'est arrêté depuis ``PERIME`` secondes (serveur redémarré) est reprise une fois depuis le début du fichier
(les valeurs déjà écrites sont alors « inchangées », rien n'est écrit deux fois), puis marquée « interrompue ». Le
fichier déposé est gardé jusqu'à la fin de la tâche, puis effacé.

« Arrêter » : l'import s'arrête proprement entre deux paquets de ``imports.PAQUET_IMPORT`` lignes ; ce qui est écrit
reste écrit (un import de la page Import / Export n'a jamais été tout ou rien : il écrit déjà par paquets pour que la
saisie des autres continue). Messages du journal du serveur en anglais (pour l'IT).
"""
import contextvars
import datetime
import logging
import threading
import time
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import connections, models
from django.db.models import F
from django.utils import timezone

from espaces import contexte as ESP
from parametres import langues as L

from . import imports as I
from .models import Journal, TacheImport

journal = logging.getLogger("collecte.imports")

BATTEMENT = 10  # secondes entre deux signes de vie d'une tâche en cours (0 : aucun fil compagnon, tests)
PERIME = 120  # secondes sans signe de vie : la tâche est reprise (une fois) ou marquée interrompue
REPRISES_MAX = 1
ATTENTE_MAX = 600  # secondes : une tâche qui attend plus longtemps est signalée par /sante/
PLANIFICATEUR_VIVANT = 30  # secondes : signe de vie du planificateur assez récent pour lui laisser les tâches
PAUSE = 2  # secondes entre deux lectures de la file (planificateur)
PAUSE_PAQUETS = 0.15  # secondes entre deux paquets sous SQLite : le verrou d'écriture va aussi aux saisies qui attendent
AVERTISSEMENTS_GARDES = 1000
CONSERVER_JOURS = 90  # tâches terminées gardées (résultat consultable), puis supprimées

T = TacheImport.Statut


def seuil():
    """Nombre de lignes au-delà duquel un import se fait en arrière-plan (0 : jamais)."""
    return max(0, int(getattr(settings, "IMPORT_ARRIERE_PLAN_LIGNES", 5000) or 0))


def en_arriere_plan(lignes):
    s = seuil()
    return bool(s) and lignes > s


class DejaEnCours(Exception):
    def __init__(self, tache):
        super().__init__(tache)
        self.tache = tache


def active_de(utilisateur):
    """Tâche en attente ou en cours de la personne (une seule à la fois), ou None."""
    return TacheImport.objects.filter(utilisateur=utilisateur, statut__in=TacheImport.ACTIVES).order_by("cree_le").first()


def a_montrer(utilisateur):
    """Dernière tâche finie de la personne dont elle n'a pas encore vu le résultat, ou None."""
    return (TacheImport.objects.filter(utilisateur=utilisateur, vu=False).exclude(statut__in=TacheImport.ACTIVES)
            .order_by("-fin", "-pk").first())


def a_signaler(utilisateur):
    """Imports de la personne à rappeler (« À traiter », « Pour moi ») : en attente ou en cours, ou finis et pas vus."""
    return list(TacheImport.objects.filter(utilisateur=utilisateur)
                .filter(models.Q(statut__in=TacheImport.ACTIVES) | models.Q(vu=False)).order_by("cree_le")[:5])


# ---------------------------------------------------------------- création, arrêt
def creer(utilisateur, info, lignes):
    """Crée la tâche d'import du fichier de l'aperçu ``info`` (session : chemin, nom, options) et la fait exécuter.
    Lève ``DejaEnCours`` si la personne a déjà un import en attente ou en cours."""
    with ESP.atomic():
        deja = active_de(utilisateur)
        if deja is not None:
            raise DejaEnCours(deja)
        # « forcer » : lignes de KPI calculés dont la personne a confirmé le forçage dans l'aperçu (``imports.appliquer``)
        options = {c: info.get(c) for c in ("campagne_defaut", "creer_campagnes", "valider", "corrections", "apercu_le", "forcer")}
        options.update(langue=L.courante(), interface=L.interface())
        t = TacheImport.objects.create(utilisateur=utilisateur, nom_fichier=info.get("nom", "")[:255], chemin=info["chemin"],
                                       options=options, lignes=lignes)
    Journal.ecrire(utilisateur, "import_arriere_plan", t, "fichier", "", f"{t.nom_fichier} : {lignes} ligne(s)")
    journal.info("Background import #%s (space \"%s\") queued by %s: %s, %s rows", t.pk, ESP.code_courant(), utilisateur,
                 t.nom_fichier, lignes)
    lancer()
    return t


def arreter(tache):
    """« Arrêter » : une tâche en attente est arrêtée tout de suite (rien n'est écrit) ; une tâche en cours s'arrête à la
    fin du paquet en cours (ce qui est écrit reste écrit)."""
    if TacheImport.objects.filter(pk=tache.pk, statut=T.ATTENTE).update(statut=T.ARRETEE, fin=timezone.now(), arret_demande=True):
        tache.refresh_from_db()
        _effacer_fichier(tache)
        Journal.ecrire(tache.utilisateur, "import_arrete", tache, "fichier", "", f"{tache.nom_fichier} : 0 valeur(s)")
        journal.info("Background import #%s (space \"%s\") cancelled before it started", tache.pk, ESP.code_courant())
        return
    TacheImport.objects.filter(pk=tache.pk, statut=T.EN_COURS).update(arret_demande=True)


# ---------------------------------------------------------------- qui exécute : planificateur ou fil de secours
def fichier_planificateur():
    return Path(settings.DOSSIER_DONNEES) / ".import-worker"


def planificateur_actif():
    try:
        return time.time() - fichier_planificateur().stat().st_mtime < PLANIFICATEUR_VIVANT
    except OSError:
        return False


def signe_de_vie_planificateur():
    try:
        f = fichier_planificateur()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(timezone.now().isoformat(), encoding="utf-8")
    except OSError:
        journal.warning("Cannot write %s (background imports will also be run by the web server)", fichier_planificateur())


_fils = {}
_verrou = threading.Lock()


def lancer(code=None):
    """S'assure que la file de l'espace sera traitée : par le planificateur s'il donne signe de vie, sinon par un fil de
    ce processus (développement, runserver, version Windows portable)."""
    if planificateur_actif():
        return
    demarrer_fil(code or ESP.code_courant())


def demarrer_fil(code):
    with _verrou:
        f = _fils.get(code)
        if f is not None and f.is_alive():
            return
        f = threading.Thread(target=_fil, args=(code,), name=f"background-import-{code}", daemon=True)
        _fils[code] = f
        f.start()


def _fil(code):
    try:
        with ESP.activer(code):
            traiter_file()
    except Exception:  # noqa: BLE001 - jamais d'erreur muette : au journal du serveur
        journal.exception("Background imports failed (space \"%s\")", code)
    finally:
        connections.close_all()


def planifier():
    """Boucle sans fin (image Docker, worker Clever Cloud) : la file de chaque espace actif toutes les ``PAUSE`` secondes ;
    les gros exports (``exports_arriere_plan``) dans un fil à part du même processus."""
    from parametres import sauvegardes as SV

    journal.info("Background import scheduler started (imports above %s rows)", seuil())
    arret = threading.Event()

    def battre():  # signe de vie, même pendant une longue tâche
        while not arret.is_set():
            signe_de_vie_planificateur()
            arret.wait(5)

    threading.Thread(target=battre, name="background-import-heartbeat", daemon=True).start()
    from . import exports_arriere_plan as EAP  # gros exports : leur propre fil (un export long ne retarde pas un import)

    threading.Thread(target=EAP.planifier, name="background-export-scheduler", daemon=True).start()
    try:
        while True:
            ESP.pour_chaque_espace(lambda: SV.base_vide() or traiter_file(), journal, "Background imports failed (space \"%s\")")
            connections.close_all()
            time.sleep(PAUSE)
    finally:
        arret.set()


# ---------------------------------------------------------------- exécution
def traiter_file():
    """Exécute les tâches en attente de l'espace courant, une à la fois, jusqu'à ce qu'il n'y en ait plus."""
    while True:
        entretien(menage=True)
        t = prendre()
        if t is None:
            return
        executer(t)


def prendre():
    """Prend la plus ancienne tâche en attente (mise à jour conditionnelle : un seul processus l'obtient), sauf si une
    autre tâche de l'espace est déjà en cours (une à la fois : SQLite n'écrit qu'une transaction à la fois)."""
    while True:
        if TacheImport.objects.filter(statut=T.EN_COURS).exists():
            return None
        t = TacheImport.objects.filter(statut=T.ATTENTE).order_by("cree_le", "pk").first()
        if t is None:
            return None
        maintenant = timezone.now()
        if TacheImport.objects.filter(pk=t.pk, statut=T.ATTENTE).update(statut=T.EN_COURS, etape="lecture", lues=0,
                                                                         debut=t.debut or maintenant, battement=maintenant):
            t.refresh_from_db()
            return t


class Suivi:
    """Avancement d'une tâche, noté en base par une mise à jour courte : au plus chaque seconde pendant la lecture, après
    chaque paquet écrit pendant l'écriture."""

    def __init__(self, tache):
        self.pk = tache.pk
        self.deja_faites, self.deja_ecrites = tache.faites, tache.ecrites  # reprise : ce que la première fois a écrit
        self.dernier = 0.0

    def _maj(self, force=False, **champs):
        if not force and time.monotonic() - self.dernier < 1:
            return
        self.dernier = time.monotonic()
        TacheImport.objects.filter(pk=self.pk).update(battement=timezone.now(), **champs)

    def lecture(self, lues):
        self._maj(lues=lues)

    def ecriture(self, faites, total, ecrites):  # après chaque paquet : compte exact, même si le processus s'arrête net
        self._maj(force=True, etape="ecriture", faites=self.deja_faites + faites,
                  total=self.deja_faites + total, ecrites=self.deja_ecrites + ecrites)
        if faites and faites < total and ESP.connexion().vendor == "sqlite":
            # SQLite n'est pas équitable : une saisie qui attend le verrou le réessaie par intervalles (jusqu'à 100 ms) et
            # le paquet suivant le reprenait aussitôt (saisies de 4 à 27 s pendant un import de 100 000 lignes) ; une
            # courte pause lui laisse la place (environ +15 % sur la durée de l'import)
            time.sleep(PAUSE_PAQUETS)

    def arreter(self):
        return TacheImport.objects.filter(pk=self.pk, arret_demande=True).exists()


class Battement:
    """Fil compagnon : note un signe de vie toutes les ``BATTEMENT`` secondes pendant la tâche (lecture d'un gros fichier
    Excel comprise), pour distinguer une tâche longue d'une tâche abandonnée par un redémarrage."""

    def __init__(self, pk):
        self.pk, self.arret, self.fil = pk, threading.Event(), None

    def __enter__(self):
        if BATTEMENT:
            contexte = contextvars.copy_context()  # même espace (base) que la tâche
            self.fil = threading.Thread(target=contexte.run, args=(self._boucle,), name=f"background-import-{self.pk}", daemon=True)
            self.fil.start()
        return self

    def _boucle(self):
        try:
            while not self.arret.wait(BATTEMENT):
                try:
                    TacheImport.objects.filter(pk=self.pk, statut=T.EN_COURS).update(battement=timezone.now())
                except Exception:  # noqa: BLE001 - base occupée : au prochain battement
                    journal.warning("Background import #%s: heartbeat not saved", self.pk, exc_info=True)
        finally:
            connections.close_all()

    def __exit__(self, *exc):
        self.arret.set()
        if self.fil is not None:
            self.fil.join(BATTEMENT + 5)


def _date(texte):
    try:
        return datetime.datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def executer(t):
    """Exécute la tâche ``t`` (déjà prise : « en cours ») et note son résultat. Ne lève jamais d'erreur."""
    o, debut = t.options or {}, time.monotonic()
    code = ESP.code_courant()
    journal.info("Background import #%s (space \"%s\") started%s: %s", t.pk, code, " again" if t.reprises else "", t.nom_fichier)
    statut, erreur, resultat = T.TERMINEE, "", dict(t.resultat or {})
    try:
        with Battement(t.pk), L.session(), L.activer(o.get("langue") or None), L.activer_interface(o.get("interface") or None):
            if not default_storage.exists(t.chemin):
                raise FileNotFoundError(t.chemin)
            with default_storage.open(t.chemin, "rb") as f:
                f.name = t.chemin
                analyse, n, avertissements = I.appliquer(
                    t.utilisateur, f, t.nom_fichier, o.get("campagne_defaut"), o.get("creer_campagnes", False),
                    o.get("valider", False), corrections=o.get("corrections") or None, vu_le=_date(o.get("apercu_le")),
                    par_paquets=True, suivi=Suivi(t), forcer=o.get("forcer") or None)
            if analyse.erreur:
                statut, erreur = T.ECHEC, analyse.erreur
            else:
                etat = I.etat_importees(analyse)
                resultat.update(etat, comptes=[[a, n_] for a, _, n_ in analyse.comptes], ecrites_ici=n,
                                avertissements=avertissements[:AVERTISSEMENTS_GARDES], nb_avertissements=len(avertissements),
                                rejets=I.lignes_rejetees(analyse, t.utilisateur))
                if analyse.arrete:
                    statut = T.ARRETEE
    except Exception as e:  # noqa: BLE001 - la tâche est marquée en échec, jamais laissée « en cours »
        journal.exception("Background import #%s (space \"%s\") failed", t.pk, code)
        statut, erreur = T.ECHEC, f"{e.__class__.__name__}: {e}"[:500]
    t.refresh_from_db()
    t.statut, t.erreur, t.resultat, t.fin, t.etape = statut, erreur, resultat, timezone.now(), ""
    if statut == T.TERMINEE:
        t.faites = t.total
    t.save(update_fields=["statut", "erreur", "resultat", "fin", "etape", "faites"])
    _effacer_fichier(t)
    if statut == T.ARRETEE:
        Journal.ecrire(t.utilisateur, "import_arrete", t, "fichier", "", f"{t.nom_fichier} : {t.ecrites} valeur(s)")
    elif statut == T.ECHEC:
        Journal.ecrire(t.utilisateur, "import_echec", t, "fichier", "", t.nom_fichier)
    journal.info("Background import #%s (space \"%s\") %s: %s of %s values written in %.0f s", t.pk, code,
                 {T.TERMINEE: "finished", T.ARRETEE: "stopped by the user", T.ECHEC: "failed"}[statut], t.ecrites, t.total,
                 time.monotonic() - debut)
    return t


def _effacer_fichier(t):
    try:
        if t.chemin and default_storage.exists(t.chemin):
            default_storage.delete(t.chemin)
    except OSError:
        journal.warning("Background import #%s: file %s not deleted", t.pk, t.chemin)


# ---------------------------------------------------------------- tâches abandonnées, ménage
def entretien(menage=False):
    """Tâches « en cours » sans signe de vie depuis ``PERIME`` secondes (processus arrêté : redémarrage, mise à jour) :
    reprises une fois depuis le début du fichier, sinon marquées « interrompues » (jamais « en cours » pour toujours).
    Appelé aussi par la page qui suit l'avancement : n'écrit rien s'il n'y a rien à faire. ``menage`` (file d'attente) :
    supprime aussi les tâches finies depuis ``CONSERVER_JOURS`` jours."""
    limite = timezone.now() - datetime.timedelta(seconds=PERIME)
    for t in TacheImport.objects.filter(statut=T.EN_COURS, battement__lt=limite):
        if not t.arret_demande and t.reprises < REPRISES_MAX and default_storage.exists(t.chemin):
            if TacheImport.objects.filter(pk=t.pk, statut=T.EN_COURS, battement__lt=limite).update(
                    statut=T.ATTENTE, reprises=F("reprises") + 1, etape=""):
                journal.warning("Background import #%s (space \"%s\") had stopped (server restart?) after %s of %s values: "
                                "started again from the beginning of the file (values already written are not written twice)",
                                t.pk, ESP.code_courant(), t.faites, t.total)
            continue
        statut = T.ARRETEE if t.arret_demande else T.INTERROMPUE
        if TacheImport.objects.filter(pk=t.pk, statut=T.EN_COURS, battement__lt=limite).update(
                statut=statut, fin=timezone.now(), etape="", erreur="" if t.arret_demande else "interrompue"):
            t.refresh_from_db()
            _effacer_fichier(t)
            Journal.ecrire(t.utilisateur, "import_arrete" if t.arret_demande else "import_interrompu", t, "fichier", "",
                           f"{t.nom_fichier} : {t.ecrites} valeur(s)")
            journal.error("Background import #%s (space \"%s\") interrupted (server restart?) after %s of %s values; "
                          "the user has been told to import the file again", t.pk, ESP.code_courant(), t.faites, t.total)
    if not menage:
        return
    ancien = timezone.now() - datetime.timedelta(days=CONSERVER_JOURS)
    TacheImport.objects.exclude(statut__in=TacheImport.ACTIVES).filter(fin__lt=ancien).delete()


def fichiers_utilises():
    """Fichiers déposés que des tâches en attente ou en cours lisent encore (jamais purgés)."""
    return set(TacheImport.objects.filter(statut__in=TacheImport.ACTIVES).values_list("chemin", flat=True))


# ---------------------------------------------------------------- supervision (/sante/)
def pour_sante(codes):
    """État des imports en arrière-plan de ``codes`` (espaces) pour /sante/ : en cours, en attente, bloqués (sans signe
    de vie depuis ``PERIME`` secondes, ou en attente depuis plus de ``ATTENTE_MAX`` secondes : ni planificateur ni
    serveur web ne les traite)."""
    maintenant = timezone.now()
    perime = maintenant - datetime.timedelta(seconds=PERIME)
    attente = maintenant - datetime.timedelta(seconds=ATTENTE_MAX)
    d = {"running": 0, "waiting": 0, "stuck": 0, "scheduler": "running" if planificateur_actif() else "not running"}
    bloquees = []
    for code in codes:
        try:
            with ESP.toutes_les_bases():
                qs = TacheImport.objects.using(ESP.declarer(code)).filter(statut__in=TacheImport.ACTIVES)
                for statut, battement, cree_le, pk in qs.values_list("statut", "battement", "cree_le", "pk"):
                    d["running" if statut == T.EN_COURS else "waiting"] += 1
                    if (statut == T.EN_COURS and (battement is None or battement < perime)) or (statut == T.ATTENTE and cree_le < attente):
                        bloquees.append(f"#{pk}" + ("" if code == ESP.PRINCIPAL else f" (space {code})"))
        except Exception:  # noqa: BLE001 - base illisible : déjà signalée par /sante/
            continue
    d["stuck"] = len(bloquees)
    if bloquees:
        d["message"] = (f"background import stuck: {', '.join(bloquees[:5])}; check that "
                        "\"python manage.py run_imports --schedule\" is running (it is started by the Docker image), or restart")
    return d
