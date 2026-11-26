"""Mise à jour automatique (Administration › Paramètres › Hébergement, « Automatic updates ») : le lien entre l'outil et la
tâche planifiée de la machine (``auto-update.sh``, posée par ``./install.sh --auto-update on``).

Règles du produit :
- l'outil n'appelle jamais l'extérieur et ne compare jamais deux versions : c'est la tâche de la machine qui cherche la
  nouvelle version, vérifie sa signature, met à jour et revient en arrière ; elle compare des empreintes d'image ;
- le conteneur n'a jamais accès au moteur Docker de la machine ;
- le lien passe par deux fichiers du dossier des données (le volume), dans ``auto-update/`` :
  ``choice``  écrit par l'outil (choix de l'administrateur), lu par la tâche ;
  ``result``  écrit par la tâche (dernier passage), lu par l'outil.

Le fichier ``result`` est une entrée non sûre pour l'outil : format strict (``clé=valeur``, clés et valeurs d'une liste
fermée ou d'un motif), taille bornée, jamais exécuté ; un fichier qui sort du format est ignoré en entier, et aucun texte
n'en est montré tel quel (états et raisons rendus par des clés de libellé, versions et dates contrôlées par motif).
Le fichier ``choice`` est une entrée non sûre pour la tâche : elle n'en lit que des valeurs d'une liste fermée.

Choix, réglé par un gestionnaire des espaces (``espaces.comptes.est_gestionnaire``) :
« automatic », « notify » (prévenir seulement), « off » ; et le délai : n'installer une version que N jours après sa
publication (``DELAIS``). Sans fichier : « off » (installation existante, clone Git, hors ligne…) ; une installation neuve
faite en une commande (``get.sh``) l'écrit à « automatic » (``python manage.py auto_update --set-choice automatic
--if-unset``, lancé par ``install.sh``).

Alertes (``alertes.signaler`` / ``alertes.resoudre``) refaites à chaque tour des boucles planifiées
(``alertes.passage_planifie``) depuis le dernier résultat : mise à jour faite (24 h), mise à jour disponible en mode
« prévenir », signature refusée, échec avec retour arrière réussi, échec sans retour arrière (panne), tâche qui ne tourne
plus, vérification impossible depuis plusieurs jours."""
import datetime
import fcntl
import hashlib
import logging
import os
import re
import stat
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, connections
from django.utils import timezone

journal = logging.getLogger("reporting.mise_a_jour_auto")

DOSSIER = "auto-update"
CHOIX, RESULTAT, VERROU = "choice", "result", ".choice.lock"
AUTOMATIQUE, PREVENIR, ETEINT = "automatic", "notify", "off"
MODES = (AUTOMATIQUE, PREVENIR, ETEINT)
DELAIS = (0, 1, 3, 7, 14)  # jours ; liste fermée (la tâche n'en accepte pas d'autre)
DELAI_DEFAUT = 3
TAILLE_MAX = 4096  # octets lus au plus dans le fichier de la tâche

# états écrits par la tâche (auto-update.sh) ; tout autre état rend le fichier invalide
ETATS = ("installed", "off", "up_to_date", "available", "waiting", "postponed", "check_failed", "refused", "updated",
         "rolled_back", "failed", "not_available", "task_removed")
RAISONS = ("busy_restore", "busy_backup", "busy_import", "busy_export", "busy_unknown", "network", "registry",
           "tool_stopped", "tool_check", "signature", "verifier", "registry_migrations", "already_failed", "health",
           "update_script", "restore_failed", "rollback_health", "git", "image", "lock")
TACHES = ("systemd", "cron", "manual", "none")
VERSION = r"\d{1,4}\.\d{1,4}\.\d{1,6}"
EMPREINTE = r"sha256:[0-9a-f]{64}"
INSTANT = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
MOTIFS = {
    "format": r"1",
    "task": "|".join(TACHES),
    "time": r"([01]\d|2[0-3]):[0-5]\d",
    "checked": INSTANT,
    "since": INSTANT,
    "state": "|".join(ETATS),
    "reason": "|".join(RAISONS),
    "installed": VERSION,
    "installed_digest": EMPREINTE,
    "available": VERSION,
    "available_digest": EMPREINTE,
    "install_after": r"\d{4}-\d{2}-\d{2}",
    "previous": VERSION,
    "restored": r"yes|no",
}
OBLIGATOIRES = ("format", "checked", "state")

UPDATED_DUREE = datetime.timedelta(hours=24)  # alerte « mise à jour faite » montrée un jour
SILENCE = datetime.timedelta(days=3)  # tâche posée qui n'a pas tourné, ou vérification impossible, depuis plus longtemps : alerte
CLE_ALERTE = "mise_a_jour_auto"
# applications dont les tables sont au registre commun (espaces.routeur) ; leurs migrations, listées par auto-update.sh
# dans chaque image, ne se défont pas automatiquement
REGISTRE = ("espaces", "sessions", "connexion_entreprise")


def dossier():
    return Path(settings.DOSSIER_DONNEES) / DOSSIER


def disponible():
    """La mise à jour automatique n'existe qu'avec l'image Docker (``DANS_DOCKER``) : ni avec l'hébergement géré, ni avec
    la version tout-en-un, qui se mettent à jour autrement."""
    return os.environ.get("DANS_DOCKER") == "1"


# ---------------------------------------------------------------- choix de l'administrateur (écrit par l'outil)
def _lire_texte_borne(chemin):
    """Contenu (octets) d'un fichier ordinaire, au plus ``TAILLE_MAX`` + 1 octets ; None s'il manque. Jamais un lien
    symbolique, une file ou un périphérique (un FIFO bloquerait la lecture)."""
    try:
        fd = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ValueError(f"unreadable ({e.strerror})") from e
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular file")
        morceaux, reste = [], TAILLE_MAX + 1
        while reste > 0:
            m = os.read(fd, reste)
            if not m:
                break
            morceaux.append(m)
            reste -= len(m)
        return b"".join(morceaux)
    finally:
        os.close(fd)


def lire_choix():
    """{"mode", "delai", "ecrit"} : le choix enregistré, sinon « éteint » (rien n'est installé sans un choix)."""
    choix = {"mode": ETEINT, "delai": DELAI_DEFAUT, "ecrit": False}
    try:
        brut = _lire_texte_borne(dossier() / CHOIX)
    except ValueError:
        return choix
    if not brut or len(brut) > TAILLE_MAX:
        return choix
    for ligne in brut.decode("utf-8", "replace").splitlines():
        cle, _, valeur = ligne.strip().partition("=")
        if cle == "mode" and valeur in MODES:
            choix.update(mode=valeur, ecrit=True)
        elif cle == "delay" and valeur in {str(d) for d in DELAIS}:
            choix["delai"] = int(valeur)
    return choix


def texte_choix(mode, delai):
    return ("# Written by Probant (Settings > Hosting, \"Automatic updates\"). Read by auto-update.sh on the server.\n"
            f"mode={mode}\ndelay={delai}\n")


def ecrire_choix(mode, delai, seulement_si_absent=False):
    """Enregistre le choix (fichier remplacé d'un bloc, 0600) ; le fichier est relu sous verrou avant d'écrire (deux
    administrateurs en même temps : l'historique de chacun part de ce qui était écrit). Renvoie les changements
    [(champ, avant, après)] ; rien si ``seulement_si_absent`` et qu'un choix existe déjà."""
    if mode not in MODES or delai not in DELAIS:
        raise ValueError((mode, delai))
    d = dossier()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(d / VERROU, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        avant = lire_choix()
        if seulement_si_absent and avant["ecrit"]:
            return []
        changements = [(c, a, b) for c, a, b in (("mode", avant["mode"] if avant["ecrit"] else "", mode),
                                                  ("delai", avant["delai"] if avant["ecrit"] else "", delai)) if a != b]
        temporaire = d / f".{CHOIX}.{os.getpid()}.tmp"
        f = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(f, "w", encoding="utf-8") as sortie:
            sortie.write(texte_choix(mode, delai))
        os.replace(temporaire, d / CHOIX)
        return changements
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------- résultat de la tâche (écrit par la machine : non sûr)
class ResultatInvalide(ValueError):
    pass


def analyser_resultat(brut):
    """Dictionnaire des valeurs d'un fichier ``result`` ; ``ResultatInvalide`` au moindre écart du format (taille,
    encodage, caractère de contrôle, clé inconnue ou répétée, valeur hors motif, clé obligatoire absente)."""
    if len(brut) > TAILLE_MAX:
        raise ResultatInvalide("too large")
    try:
        texte = brut.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ResultatInvalide("not UTF-8") from e
    sortie = {}
    for ligne in texte.split("\n"):
        if ligne == "":
            continue
        if not re.fullmatch(r"[a-z_]{1,20}=[\x21-\x7e]{0,80}", ligne):
            raise ResultatInvalide("line out of format")
        cle, valeur = ligne.split("=", 1)
        if cle not in MOTIFS or cle in sortie:
            raise ResultatInvalide(f"key {cle}")
        if not re.fullmatch(MOTIFS[cle], valeur):
            raise ResultatInvalide(f"value of {cle}")
        sortie[cle] = valeur
    if any(c not in sortie for c in OBLIGATOIRES):
        raise ResultatInvalide("missing key")
    for cle in ("checked", "since"):
        if cle in sortie:
            try:
                sortie[cle] = datetime.datetime.strptime(sortie[cle], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            except ValueError as e:
                raise ResultatInvalide(f"date {cle}") from e
    if "install_after" in sortie:
        try:
            sortie["install_after"] = datetime.date.fromisoformat(sortie["install_after"])
        except ValueError as e:
            raise ResultatInvalide("date install_after") from e
    return sortie


_signale = None


def lire_resultat():
    """(résultat, invalide) : le dernier résultat de la tâche, ou None ; ``invalide`` vrai si un fichier est là mais sort
    du format (il est alors ignoré en entier)."""
    try:
        brut = _lire_texte_borne(dossier() / RESULTAT)
        if brut is None:
            return None, False
        return analyser_resultat(brut), False
    except ValueError as e:
        global _signale
        if _signale != str(e):  # une fois par cause, pas à chaque tour des boucles planifiées
            _signale = str(e)
            journal.warning("Result file of the automatic update ignored (%s): %s", e, dossier() / RESULTAT)
        return None, True


# ---------------------------------------------------------------- écran
def _instant(d):
    from . import sante_installation as SI

    return SI.quand(d) if d else ""


def _jour(d):
    from collecte import dates_courtes as DC

    return DC.date_courte(d) if d else ""


def etat_ecran(maintenant=None):
    """Ce que montre la page Hébergement : disponibilité, choix, tâche de la machine, dernier passage. Textes : clés de
    libellé et valeurs contrôlées seulement."""
    from .libelles import libelle

    maintenant = maintenant or timezone.now()
    if not disponible():
        return {"disponible": False}
    choix = lire_choix()
    r, invalide = lire_resultat()
    tache = (r or {}).get("task", "")
    posee = tache in ("systemd", "cron")
    sortie = {"disponible": True, "choix": choix, "invalide": invalide, "resultat": r, "posee": posee,
              "silence": False, "etat_texte": "", "tache_texte": ""}
    if r is None or tache in ("", "none"):
        sortie["tache_texte"] = libelle("admin.maj_auto.tache.absente")
    elif posee:
        heure = r.get("time", "")
        sortie["tache_texte"] = (libelle("admin.maj_auto.tache.posee_heure", heure=heure) if heure
                                 else libelle("admin.maj_auto.tache.posee"))
        sortie["silence"] = maintenant - r["checked"] > SILENCE
    else:
        sortie["tache_texte"] = libelle("admin.maj_auto.tache.manuelle")
    if r is not None:
        sortie["dernier"] = _instant(r["checked"])
        sortie["etat_texte"] = texte_etat(r)
    return sortie


def texte_etat(r):
    """Phrase du dernier passage, dans la langue en cours."""
    from .libelles import libelle

    etat, raison = r["state"], r.get("reason", "")
    valeurs = {"version": r.get("installed", ""), "nouvelle": r.get("available", ""), "avant": r.get("previous", ""),
               "jour": _jour(r.get("install_after"))}
    texte = libelle(f"admin.maj_auto.etat.{etat}", **valeurs)
    if raison:
        texte += " " + libelle(f"admin.maj_auto.raison.{raison}", **valeurs)
    if etat == "rolled_back":
        texte += " " + libelle("admin.maj_auto.restauree" if r.get("restored") == "yes" else "admin.maj_auto.non_restauree")
    return texte


# ---------------------------------------------------------------- alertes
def alerte_attendue(r, maintenant=None):
    """(état de l'alerte, clé du constat, clé de ce qu'il faut faire) que le dernier résultat appelle, ou None."""
    from . import sante_installation as SI

    maintenant = maintenant or timezone.now()
    if r is None or not disponible():
        return None
    etat = r["state"]
    if r.get("task") in ("systemd", "cron") and maintenant - r["checked"] > SILENCE:
        return SI.A_REGARDER, "silence"
    if etat == "updated" and maintenant - r["checked"] <= UPDATED_DUREE:
        return SI.A_REGARDER, "updated"
    if etat == "available":
        return SI.A_REGARDER, "available"
    if etat in ("refused", "rolled_back"):
        return SI.A_REGARDER, etat
    if etat == "failed":
        return SI.PANNE, "failed"
    if etat == "check_failed" and maintenant - r.get("since", r["checked"]) > SILENCE:
        return SI.A_REGARDER, "check_failed"
    return None


CAS_ALERTE = ("silence", "updated", "available", "refused", "rolled_back", "failed", "check_failed")


def synchroniser_alertes(maintenant=None):
    """Problème signalé (page Santé, alertes par e-mail) selon le dernier résultat : un seul cas à la fois, chacun sa clé
    (un nouveau cas part comme un nouveau problème) ; les autres sont résolus. Renvoie le cas, ou None."""
    from . import alertes as AL

    r, _ = lire_resultat()
    attendu = alerte_attendue(r, maintenant)
    cas = attendu[1] if attendu else None
    for autre in CAS_ALERTE:
        if autre != cas:
            AL.resoudre(f"{CLE_ALERTE}.{autre}")
    if attendu:
        etat, cas = attendu
        depuis = r.get("since", r["checked"]) if cas == "check_failed" else r["checked"]
        params = {"version": r.get("installed", ""), "nouvelle": r.get("available", ""), "avant": r.get("previous", ""),
                  "quand": _instant(depuis)}
        detail = " ".join(f"{k}={r[k]}" for k in ("state", "reason", "installed", "available", "previous") if r.get(k))
        AL.signaler(f"{CLE_ALERTE}.{cas}", "admin.maj_auto.alerte.titre", f"admin.maj_auto.alerte.{cas}",
                    f"admin.maj_auto.alerte.{cas}_quoi", params, etat=etat, detail=detail)
    return cas


# ---------------------------------------------------------------- pour la tâche de la machine (commande auto_update)
def occupe():
    """Raison (« busy_restore », « busy_backup », « busy_import », « busy_export ») si une restauration, une sauvegarde,
    un import ou un gros export est en cours dans un espace ; "" sinon. La tâche ne met jamais à jour pendant ce temps."""
    from collecte.models import TacheExport, TacheImport
    from espaces import contexte as ESP
    from espaces.models import Espace

    from . import sauvegardes as SV

    codes = [ESP.PRINCIPAL] + list(Espace.objects.exclude(code=ESP.PRINCIPAL).values_list("code", flat=True))
    for code in codes:
        if SV.restauration_en_cours(code):
            return "busy_restore"
        try:
            d = ESP.dossier_sauvegardes(code)
            if d.is_dir() and any(p.name.startswith(".") and p.name.endswith(".partiel") for p in d.iterdir()):
                return "busy_backup"
        except OSError:
            return "busy_unknown"
    for code in codes:
        with ESP.activer(code):
            if SV.base_vide():
                continue
            if TacheImport.objects.filter(statut__in=TacheImport.ACTIVES).exists():
                return "busy_import"
            if TacheExport.objects.filter(statut__in=TacheExport.ACTIVES).exists():
                return "busy_export"
    return ""


def empreintes():
    """[(partie, empreinte)] des migrations notées dans chaque base, telles quelles (lues en SQL : la base peut être d'une
    version plus récente que le code) : « registry » pour le registre commun, « space <code> » pour chaque espace ;
    « empty » pour une base sans table des migrations. Comparées avant et après une mise à jour ratée, elles disent si la
    nouvelle version a changé la structure d'une base (il faut alors restaurer la sauvegarde « before-update »).
    Registre commun : seulement les applications qui y ont leurs tables (``REGISTRE``). Django note chaque migration de
    chaque application dans chaque base, même là où elle n'a aucune table (le routeur l'y refuse) : ces lignes ne
    changent rien à la structure du registre."""
    from espaces import contexte as ESP
    from espaces.models import Espace

    def empreinte(alias, applications=None):
        c = connections[alias]
        if "django_migrations" not in c.introspection.table_names():
            return "empty"
        with c.cursor() as cur:
            cur.execute("SELECT app, name FROM django_migrations")
            lignes = sorted(f"{a}\t{n}" for a, n in cur.fetchall() if applications is None or a in applications)
        return hashlib.sha256("\n".join(lignes).encode()).hexdigest()

    sortie = [("registry", empreinte(ESP.COMMUN, REGISTRE))]
    try:
        autres = sorted(Espace.objects.exclude(code=ESP.PRINCIPAL).values_list("code", flat=True))
    except DatabaseError:
        autres = []
    with ESP.toutes_les_bases():
        for code in [ESP.PRINCIPAL] + autres:
            sortie.append((f"space {code}", empreinte(ESP.declarer(code))))
    return sortie
