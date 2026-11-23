"""Gros exports fabriqués en arrière-plan.

Au-delà de ``Instance.exports_fond_cellules`` cellules (lignes × colonnes, estimées par une requête ``count()`` avant de
lire les réponses ; Paramètres › Hébergement, 100 000 par défaut, 0 : jamais), « Télécharger » un export (Import /
Export › Mes exports, constructeur d'export) ou le fichier à remplir ne fabrique plus le fichier dans la requête : il
crée une tâche (``TacheExport``) et la personne retrouve son fichier dans Import / Export › Mes exports, gardé
``Instance.exports_fond_jours`` jours (7 par défaut). En dessous du seuil, rien ne change.

Qui fabrique, sans nouveau service : le planificateur des imports (``run_imports --schedule``, image Docker, worker
Clever Cloud) dans un fil à lui (un gros export ne retarde pas un import), sinon un fil du processus web
(développement, version Windows portable), comme ``imports_arriere_plan``. Le fichier sort des MÊMES fonctions que le
téléchargement immédiat (``exports.exporter``, ``imports_modele.fichier_a_remplir``) : il est identique.

Règles :
- une tâche n'est prise qu'une fois (mise à jour conditionnelle du statut, avec plusieurs processus, SQLite et
  PostgreSQL) et une seule à la fois par espace (mémoire du serveur) ; une personne a au plus une tâche en attente ou en
  cours ;
- une tâche dont le battement s'arrête (serveur redémarré) est reprise une fois depuis le début, puis marquée
  « interrompue » ;
- le fichier est écrit dans files/exports/<uuid>.<ext> (nom caché puis mise en place d'un coup : ``StockageEspace``),
  jamais sauvegardé ; il n'est donné qu'à la personne qui l'a demandé, et seulement si ses droits et son périmètre sont
  ceux de la demande (``empreinte``, mêmes fonctions que la page ; contrôlé juste avant et juste après la fabrication, puis
  au téléchargement) : sinon il n'est pas fabriqué, ou il est supprimé sans être donné ;
- le planificateur efface les fichiers expirés, les fichiers sans tâche (restauration, arrêt brutal) et les tâches
  finies depuis ``CONSERVER_JOURS`` jours ; son premier tour, au démarrage, fait ce ménage.
Lecteur et auditeur : une demande crée une tâche, trace technique comme leurs exports enregistrés ; rien au journal des
modifications (un export n'y est jamais écrit). Messages du journal du serveur en anglais (pour l'IT).
"""
import contextvars
import datetime
import hashlib
import json
import logging
import re
import threading
import time
import uuid

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connections
from django.db.models import Exists, F, Q
from django.utils import timezone

from espaces import contexte as ESP
from parametres import langues as L
from parametres.libelles import libelle
from parametres.rangement import EXPORTS

from . import exports as E
from . import imports_arriere_plan as AP
from . import lecture_seule as LS
from .models import TacheExport

journal = logging.getLogger("collecte.exports")

T = TacheExport.Statut
G = TacheExport.Genre
BATTEMENT = 10  # secondes entre deux signes de vie d'une tâche en cours (0 : aucun fil compagnon, tests)
PERIME = 120  # secondes sans signe de vie : la tâche est reprise (une fois) ou marquée interrompue
REPRISES_MAX = 1
CONSERVER_JOURS = 30  # tâches finies (expirées, en échec…) gardées ce nombre de jours, puis supprimées
ORPHELIN_HEURES = 1  # fichier de files/exports sans tâche prête depuis ce temps : effacé
MENAGE_SECONDES = 60  # le planificateur fait le ménage au plus une fois par minute et par espace
# motif d'une tâche prête dont le fichier n'a pas suivi la base (restauration d'une sauvegarde, copie des données dans la
# version tout-en-un : files/exports n'est jamais copié) ; même texte dans portable/build_package.py (FICHIER_ABSENT)
FICHIER_ABSENT = "fichier_absent"
PAUSE = AP.PAUSE
VERROU_PRISE = 0x50524F42  # clé du verrou consultatif PostgreSQL de la prise d'une tâche (``prise``)


# ---------------------------------------------------------------- seuil, estimation, droits
def seuil():
    """Cellules au-delà desquelles un export se fabrique en arrière-plan (0 : jamais)."""
    from parametres.models import Instance

    return max(0, Instance.courante().exports_fond_cellules or 0)


def jours():
    from parametres.models import Instance

    return Instance.courante().exports_fond_jours or 7


def en_arriere_plan(cellules):
    s = seuil()
    return bool(s) and cellules > s


def empreinte(utilisateur):
    """Droits et périmètre de la personne, relus en base, par les fonctions des pages d'export (``exports.perimetre`` :
    cases saisissables et organisations dont elle voit les résultats ; rôle ; organisations consultées d'un lecteur ou
    d'un auditeur). Deux empreintes égales : le fichier contient ce que la page lui montrerait."""
    from . import saisie as S

    u = get_user_model().objects.get(pk=utilisateur.pk)
    paires, resultats = E.perimetre(u, S.arbre_organisations())
    permises = u.orgs_permises()
    donnees = [u.role, u.is_active, u.is_superuser, None if permises is None else sorted(permises),
               None if paires is None else sorted(paires), None if resultats is None else sorted(resultats)]
    return hashlib.sha256(json.dumps(donnees, default=str).encode()).hexdigest()


def page_permise(utilisateur, genre):
    """La personne peut-elle encore demander ce fichier par la page (compte actif ; lecteur, auditeur : même règle que
    ``lecture_seule``) ?"""
    if not utilisateur.is_active:
        return False
    if utilisateur.lecture_seule:
        page = "echanges_exporter" if genre == G.EXPORT else "echanges_modele"
        return not LS.motif_refus_page(utilisateur, "collecte", page, "POST")
    return True


def droits_inchanges(t, utilisateur):
    return page_permise(utilisateur, t.genre) and empreinte(utilisateur) == t.empreinte


def droits_de_la_demande(t):
    """La personne qui a demandé ``t`` a-t-elle encore, relus en base, les droits et le périmètre de sa demande ? Contrôlé
    juste avant et juste après la fabrication : des droits élargis puis rendus entre la demande et le téléchargement ne
    donnent jamais un fichier au contenu des droits élargis."""
    u = get_user_model().objects.filter(pk=t.utilisateur_id).first()
    return u is not None and droits_inchanges(t, u)


# ---------------------------------------------------------------- ce que voit la personne
def active_de(utilisateur):
    return TacheExport.objects.filter(utilisateur=utilisateur, statut__in=TacheExport.ACTIVES).order_by("cree_le").first()


def a_montrer(utilisateur):
    """Tâches de la personne à montrer dans Mes exports : en attente ou en cours, prêtes (non expirées), et finies sans
    fichier (échec, interrompue, rien à remplir) pas encore vues."""
    maintenant = timezone.now()
    return list(TacheExport.objects.filter(utilisateur=utilisateur).filter(
        Q(statut__in=TacheExport.ACTIVES) | Q(statut=T.PRET, expire_le__gt=maintenant)
        | Q(statut__in=TacheExport.FINIES_A_MONTRER, vu=False)).order_by("-cree_le", "-pk")[:10])


def retirer_droits_changes(utilisateur, taches):
    """Tâches prêtes dont les droits ou le périmètre de la personne ont changé depuis la demande : fichier supprimé sans
    être donné (« expirée », motif « droits »), retirées de la liste. Renvoie (tâches gardées, nombre retiré) : Mes
    exports ne montre plus « Prêt » un fichier qui serait refusé au clic, et dit pourquoi (seconde recette, B3)."""
    pretes = [t for t in taches if t.statut == T.PRET]
    if not pretes or droits_inchanges(pretes[0], utilisateur) and all(t.empreinte == pretes[0].empreinte for t in pretes):
        return taches, 0
    retirees = [t for t in pretes if not droits_inchanges(t, utilisateur)]
    for t in retirees:
        expirer(t, "droits")
    return [t for t in taches if t not in retirees], len(retirees)


def marquer_vues(taches):
    pks = [t.pk for t in taches if t.statut in TacheExport.FINIES_A_MONTRER and not t.vu]
    if pks:
        TacheExport.objects.filter(pk__in=pks).update(vu=True)


# ---------------------------------------------------------------- création
class DejaEnCours(Exception):
    def __init__(self, tache):
        super().__init__(tache)
        self.tache = tache


def creer(utilisateur, genre, titre, parametres, cellules):
    """Crée la tâche (droits et langues de la demande notés) et la fait exécuter. Lève ``DejaEnCours`` si la personne a
    déjà un export en attente ou en cours (relu sous verrou : deux demandes simultanées n'en créent qu'une)."""
    e = empreinte(utilisateur)  # avant la transaction : pas de verrou d'écriture pendant ce calcul
    with ESP.atomic():
        get_user_model().objects.select_for_update().filter(pk=utilisateur.pk).first()  # PostgreSQL ; SQLite : « immediate »
        deja = active_de(utilisateur)
        if deja is not None:
            raise DejaEnCours(deja)
        t = TacheExport.objects.create(utilisateur=utilisateur, genre=genre, titre=titre[:255], cellules=cellules, empreinte=e,
                                       parametres={**parametres, "langue": L.courante(), "interface": L.interface()})
    journal.info("Background export #%s (space \"%s\") queued by user #%s: %s cells", t.pk, ESP.code_courant(),
                 utilisateur.pk, cellules)
    lancer()
    return t


# ---------------------------------------------------------------- qui exécute : planificateur ou fil de secours
_fils = {}
_verrou = threading.Lock()


def lancer(code=None):
    """La file de l'espace sera traitée : par le planificateur s'il donne signe de vie, sinon par un fil de ce processus."""
    if AP.planificateur_actif():
        return
    demarrer_fil(code or ESP.code_courant())


def demarrer_fil(code):
    with _verrou:
        f = _fils.get(code)
        if f is not None and f.is_alive():
            return
        f = threading.Thread(target=_fil, args=(code,), name=f"background-export-{code}", daemon=True)
        _fils[code] = f
        f.start()


def _fil(code):
    try:
        with ESP.activer(code):
            traiter_file()
    except Exception:  # noqa: BLE001 - jamais d'erreur muette : au journal du serveur
        journal.exception("Background exports failed (space \"%s\")", code)
    finally:
        connections.close_all()


def planifier():
    """Boucle sans fin, dans un fil du planificateur des imports (``imports_arriere_plan.planifier``)."""
    from parametres import sauvegardes as SV

    journal.info("Background export scheduler started")
    while True:
        try:
            ESP.pour_chaque_espace(lambda: SV.base_vide() or traiter_file(), journal, "Background exports failed (space \"%s\")")
        except Exception:  # noqa: BLE001 - le fil ne s'arrête jamais : au tour suivant
            journal.exception("Background exports failed")
        connections.close_all()
        time.sleep(PAUSE)


# ---------------------------------------------------------------- exécution
_dernier_menage = {}


def traiter_file():
    """Fabrique les fichiers en attente de l'espace courant, un à la fois, jusqu'à ce qu'il n'y en ait plus."""
    code = ESP.code_courant()
    menage = time.monotonic() - _dernier_menage.get(code, -MENAGE_SECONDES) >= MENAGE_SECONDES
    if menage:
        _dernier_menage[code] = time.monotonic()
    entretien(menage=menage)
    while True:
        t = prendre()
        if t is None:
            return
        executer(t)
        entretien()


def candidate():
    return TacheExport.objects.filter(statut=T.ATTENTE).order_by("cree_le", "pk").first()


def prise(t):
    """Prend la tâche ``t`` : une seule mise à jour conditionnelle (encore en attente, et aucune autre en cours dans
    l'espace) ; vrai pour un seul processus. Sous PostgreSQL, le ``NOT EXISTS`` ne voit pas la prise non encore validée
    d'un autre processus (deux tâches différentes prises au même instant) : un verrou consultatif de transaction fait
    passer les prises l'une après l'autre (le verrou vaut pour la base, donc pour l'espace). SQLite : une écriture à la fois,
    rien de plus."""
    c = ESP.connexion()
    if c.vendor != "postgresql":
        return _prise(t)
    with ESP.atomic():
        with c.cursor() as curseur:
            curseur.execute("SELECT pg_advisory_xact_lock(%s)", [VERROU_PRISE])
        return _prise(t)


def _prise(t):
    maintenant = timezone.now()
    autre = TacheExport.objects.filter(statut=T.EN_COURS)
    return bool(TacheExport.objects.filter(pk=t.pk, statut=T.ATTENTE).filter(~Exists(autre))
                .update(statut=T.EN_COURS, debut=maintenant, battement=maintenant))


def prendre():
    """La plus ancienne tâche en attente, prise par ce processus ; None si aucune, ou si une autre est en cours."""
    while True:
        if TacheExport.objects.filter(statut=T.EN_COURS).exists():
            return None
        t = candidate()
        if t is None:
            return None
        if prise(t):
            t.refresh_from_db()
            return t


class Battement:
    """Fil compagnon : signe de vie toutes les ``BATTEMENT`` secondes pendant la fabrication (une tâche longue n'est pas
    prise pour une tâche abandonnée)."""

    def __init__(self, pk):
        self.pk, self.arret, self.fil = pk, threading.Event(), None

    def __enter__(self):
        if BATTEMENT:
            contexte = contextvars.copy_context()  # même espace (base) que la tâche
            self.fil = threading.Thread(target=contexte.run, args=(self._boucle,), name=f"background-export-{self.pk}", daemon=True)
            self.fil.start()
        return self

    def _boucle(self):
        try:
            while not self.arret.wait(BATTEMENT):
                try:
                    TacheExport.objects.filter(pk=self.pk, statut=T.EN_COURS).update(battement=timezone.now())
                except Exception:  # noqa: BLE001 - base occupée : au prochain battement
                    journal.warning("Background export #%s: heartbeat not saved", self.pk, exc_info=True)
        finally:
            connections.close_all()

    def __exit__(self, *exc):
        self.arret.set()
        if self.fil is not None:
            self.fil.join(BATTEMENT + 5)


def fabriquer(t):
    """Réponse HTTP du fichier, par les fonctions du téléchargement immédiat ; None : rien à remplir."""
    from . import imports_modele as IM
    from .models import Campagne

    o = t.parametres
    if t.genre == G.EXPORT:
        return E.exporter(t.utilisateur, E.Parametres.depuis(o["reglages"]), o.get("titre", ""), o.get("adresse", ""))
    campagne = Campagne.objects.filter(pk=o.get("campagne")).first() if o.get("campagne") else None
    return IM.fichier_a_remplir(t.utilisateur, IM.choix_depuis(o.get("choix") or {}), campagne)


def nom_telecharge(reponse):
    m = re.search(r'filename="([^"]+)"', reponse.get("Content-Disposition", ""))
    return m.group(1) if m else "export"


def executer(t):
    """Fabrique le fichier de la tâche ``t`` (déjà prise : « en cours ») et note le résultat. Ne lève jamais d'erreur."""
    o, debut, code = t.parametres or {}, time.monotonic(), ESP.code_courant()
    journal.info("Background export #%s (space \"%s\") started%s", t.pk, code, " again" if t.reprises else "")
    statut, erreur, nom, chemin, taille = T.PRET, "", "", "", 0
    try:
        with Battement(t.pk), L.session(), L.activer(o.get("langue") or None), L.activer_interface(o.get("interface") or None):
            reponse = None
            if not droits_de_la_demande(t):  # droits changés depuis la demande : rien n'est fabriqué
                statut, erreur = T.ECHEC, libelle("suivi.echanges.msg.export_fond_droits")
            else:
                try:
                    reponse = fabriquer(t)
                except E.ExportTropGros as e:  # plus de lignes qu'une feuille Excel : le message propose le CSV
                    statut, erreur = T.ECHEC, str(e)
                if reponse is not None and not droits_de_la_demande(t):  # changés pendant la fabrication : jeté
                    reponse, statut, erreur = None, T.ECHEC, libelle("suivi.echanges.msg.export_fond_droits")
            if reponse is None and statut == T.PRET:
                statut, erreur = T.VIDE, libelle("suivi.echanges.msg.rien_a_remplir")
            elif reponse is not None:
                nom = nom_telecharge(reponse)
                extension = nom.rsplit(".", 1)[-1] if "." in nom else "xlsx"
                contenu = reponse.content
                taille = len(contenu)
                chemin = default_storage.save(f"{EXPORTS}/{uuid.uuid4().hex}.{extension}", ContentFile(contenu))
    except Exception as e:  # noqa: BLE001 - la tâche est marquée en échec, jamais laissée « en cours »
        journal.exception("Background export #%s (space \"%s\") failed", t.pk, code)
        statut, erreur = T.ECHEC, f"{e.__class__.__name__}: {e}"[:500]
    fin = timezone.now()
    fait = TacheExport.objects.filter(pk=t.pk, statut=T.EN_COURS).update(
        statut=statut, erreur=erreur, nom_fichier=nom[:255], chemin=chemin, taille=taille, fin=fin,
        expire_le=fin + datetime.timedelta(days=jours()) if statut == T.PRET else None)
    if not fait:  # reprise ailleurs entre-temps (ne devrait pas arriver avec le battement) : rien de gardé ici
        _effacer(chemin)
        journal.warning("Background export #%s (space \"%s\") was taken over: file not kept", t.pk, code)
    else:
        etat = {T.PRET: "ready", T.ECHEC: "failed"}.get(statut, "ended")  # le journal du serveur est en anglais (pas le code de la base)
        journal.info("Background export #%s (space \"%s\") %s in %.0f s (%s bytes)", t.pk, code, etat,
                     time.monotonic() - debut, taille)
    t.refresh_from_db()
    return t


def _effacer(chemin):
    try:
        if chemin and default_storage.exists(chemin):
            default_storage.delete(chemin)
    except OSError:
        journal.warning("Background export file %s not deleted", chemin)


def expirer(t, erreur=""):
    """Fichier effacé, tâche « expirée » (plus montrée) : durée passée, ou droits changés (``erreur`` = « droits »)."""
    if TacheExport.objects.filter(pk=t.pk, statut=T.PRET).update(statut=T.EXPIRE, erreur=erreur):
        _effacer(t.chemin)
        if erreur:
            journal.info("Background export #%s (space \"%s\") deleted without being given: %s", t.pk, ESP.code_courant(), erreur)


def expirer_fichiers_absents():
    """Tâches « prêtes » dont le fichier n'est plus là (après une restauration : les gros exports ne sont jamais
    sauvegardés, et la base restaurée peut garder des tâches dont le fichier a été effacé depuis) : « expirées », motif
    ``FICHIER_ABSENT`` (message juste au clic). Renvoie le nombre de tâches."""
    n = 0
    for t in TacheExport.objects.filter(statut=T.PRET):
        try:
            present = bool(t.chemin) and default_storage.exists(t.chemin)
        except OSError:
            present = False
        if not present:
            n += TacheExport.objects.filter(pk=t.pk, statut=T.PRET).update(statut=T.EXPIRE, erreur=FICHIER_ABSENT)
    return n


# ---------------------------------------------------------------- tâches abandonnées, ménage
def entretien(menage=False):
    """Tâches « en cours » sans signe de vie depuis ``PERIME`` secondes : reprises une fois, sinon « interrompues ».
    ``menage`` : fichiers expirés et fichiers sans tâche effacés, vieilles tâches supprimées."""
    maintenant = timezone.now()
    limite = maintenant - datetime.timedelta(seconds=PERIME)
    for t in TacheExport.objects.filter(statut=T.EN_COURS, battement__lt=limite):
        reste = TacheExport.objects.filter(pk=t.pk, statut=T.EN_COURS, battement__lt=limite)
        if t.reprises < REPRISES_MAX:
            if reste.update(statut=T.ATTENTE, reprises=F("reprises") + 1):
                journal.warning("Background export #%s (space \"%s\") had stopped (server restart?): started again",
                                t.pk, ESP.code_courant())
        elif reste.update(statut=T.INTERROMPUE, fin=maintenant, erreur="interrompue"):
            journal.error("Background export #%s (space \"%s\") interrupted (server restart?); the user has been told "
                          "to ask for it again", t.pk, ESP.code_courant())
    if not menage:
        return
    for t in TacheExport.objects.filter(statut=T.PRET, expire_le__lt=maintenant):
        expirer(t)
    TacheExport.objects.exclude(statut__in=(*TacheExport.ACTIVES, T.PRET)).filter(
        fin__lt=maintenant - datetime.timedelta(days=CONSERVER_JOURS)).delete()
    effacer_orphelins()


# ---------------------------------------------------------------- supervision (/sante/)
def pour_sante(codes):
    """État des gros exports en arrière-plan de ``codes`` (espaces) pour /sante/, comme ``imports_arriere_plan.pour_sante`` :
    en cours, en attente, bloqués (sans signe de vie depuis ``PERIME`` secondes, ou en attente depuis plus de
    ``AP.ATTENTE_MAX`` secondes : ni planificateur ni serveur web ne les traite). Jamais un 503."""
    maintenant = timezone.now()
    perime = maintenant - datetime.timedelta(seconds=PERIME)
    attente = maintenant - datetime.timedelta(seconds=AP.ATTENTE_MAX)
    d = {"running": 0, "waiting": 0, "stuck": 0}
    bloques = []
    for code in codes:
        try:
            with ESP.toutes_les_bases():
                qs = TacheExport.objects.using(ESP.declarer(code)).filter(statut__in=TacheExport.ACTIVES)
                for statut, battement, cree_le, pk in qs.values_list("statut", "battement", "cree_le", "pk"):
                    d["running" if statut == T.EN_COURS else "waiting"] += 1
                    if (statut == T.EN_COURS and (battement is None or battement < perime)) or (statut == T.ATTENTE and cree_le < attente):
                        bloques.append(f"#{pk}" + ("" if code == ESP.PRINCIPAL else f" (space {code})"))
        except Exception:  # noqa: BLE001 - base illisible : déjà signalée par /sante/
            continue
    d["stuck"] = len(bloques)
    if bloques:
        d["message"] = (f"background export stuck: {', '.join(bloques[:5])}; check that "
                        "\"python manage.py run_imports --schedule\" is running (it is started by the Docker image), or restart")
    return d


def effacer_orphelins():
    """Fichiers de files/exports qu'aucune tâche prête ne garde (restauration d'une sauvegarde, arrêt brutal pendant
    l'écriture), plus vieux que ``ORPHELIN_HEURES`` : effacés."""
    try:
        if not default_storage.exists(EXPORTS):
            return
        gardes = set(TacheExport.objects.filter(statut=T.PRET).values_list("chemin", flat=True))
        limite = timezone.now() - datetime.timedelta(hours=ORPHELIN_HEURES)
        for nom in default_storage.listdir(EXPORTS)[1]:
            chemin = f"{EXPORTS}/{nom}"
            if chemin not in gardes and default_storage.get_modified_time(chemin) < limite:
                default_storage.delete(chemin)
    except OSError:
        journal.warning("Background exports: folder %s not cleaned", EXPORTS, exc_info=True)
