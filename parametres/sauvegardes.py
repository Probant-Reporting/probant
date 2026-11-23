"""Sauvegarde et restauration d'une installation : une seule archive datée (.zip) avec la base, les fichiers déposés
(preuves, logo) et un descriptif (version de l'outil, migrations, nombre de lignes par table).

- Base SQLite (par défaut) : copie exacte et cohérente par l'API de sauvegarde de SQLite, même pendant que l'outil
  tourne (``database.sqlite3``). Restaurée telle quelle puis migrée : une archive d'une version antérieure de l'outil se
  restaure dans une version plus récente.
- Base PostgreSQL : contenu de toutes les tables au format JSON de Django (``database.json``), restauré dans une base de même
  version de l'outil (mêmes migrations).

Les archives sont rangées dans le dossier des sauvegardes de l'espace courant (SAUVEGARDES_DIR, ``/data/sauvegardes``
dans l'image Docker, pour l'espace principal ; ``sauvegardes/espaces/<code>`` pour les autres) ; seules les
``SAUVEGARDE_CONSERVER`` plus récentes sont gardées. Les fichiers d'import temporaires ne sont pas sauvegardés. Chaque
archive porte le code de son espace et l'identifiant de l'installation : elle ne se restaure que là. Le registre commun
(comptes, espaces) a ses propres archives (``sauvegardes/commun``).
"""
import contextlib
import datetime
import errno
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.management import call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from .libelles import libelle
from .rangement import EXPORTS, IMPORTS
from collecte.statistiques_postgresql import statistiques_a_jour
from espaces import contexte as ESP
from espaces.migrations_renommees import autres_bases, harmoniser, paires_actuelles

journal = logging.getLogger("reporting.sauvegarde")

FORMAT = 1
# Valeur du champ "outil" du descriptif d'une archive : toute autre valeur est refusée.
OUTIL = "probant"
OUTILS_ACCEPTES = (OUTIL,)
MOTIF = re.compile(r"^[a-z0-9-]{0,40}$")
NOM = re.compile(r"^(backup|sauvegarde)-\d{8}-\d{6}(-[a-z0-9-]+)?\.zip$")  # « sauvegarde- » : avant la mise à jour
# contenu d'une archive : noms anglais, anciens noms français encore lus
DESCRIPTIF, BASE_SQLITE, BASE_JSON, FICHIERS_ARCHIVE = "backup.json", "database.sqlite3", "database.json", "files/"
ANCIENS = {"backup.json": "sauvegarde.json", "database.sqlite3": "base.sqlite3", "database.json": "base.json",
           "files/": "fichiers/", "registry.json": "registre.json"}
ANCIENS_MOTIFS = {"avant-mise-a-jour": "before-update", "avant-restauration": "before-restore", "deposee": "uploaded"}


def nom_dans(noms, nom):
    """Nom de ``nom`` dans une archive : le nom anglais, sinon l'ancien nom français, sinon None."""
    return nom if nom in noms else ANCIENS.get(nom) if ANCIENS.get(nom) in noms else None


def _horodatage(nom):
    """« 20261101-023000 » d'un nom d'archive (préfixe anglais ou français)."""
    return nom.split("-", 1)[1][:15] if "-" in nom else ""
EXCLUS = {IMPORTS, EXPORTS, "imports", ".restore-new", ".restore-old"}  # dossiers de fichiers non sauvegardés (fichiers temporaires ; « imports » : ancien nom ; gros exports : refaits sur demande)
# recréées par Django ; jetons des assistants (MCP) : jamais sauvegardés, une restauration ne peut pas rendre valide un jeton
# révoqué après la sauvegarde (docs/mcp.md, 1.4) : chacun en crée un nouveau
TABLES_EXCLUES = ["contenttypes", "auth.permission", "sessions", "admin.logentry", "serveur_mcp.jetonmcp"]
# archive SQLite (copie entière de la base) : tables de TABLES_EXCLUES vidées dans la copie, jamais dans la base vivante.
# Jetons des assistants (un secret : jamais dans une archive), sessions (table d'avant les espaces, plus utilisée : les
# sessions sont dans le registre commun) et journal du mode expert (lecture seule). Les types de contenu et les
# permissions restent : Django les recrée à l'identique, d'autres tables les citent, aucun secret.
TABLES_VIDEES_DANS_LA_COPIE = ["sessions", "admin.logentry", "serveur_mcp.jetonmcp"]
# Empreintes des mots de passe : jamais dans l'archive d'un espace. Un administrateur de
# l'espace peut télécharger l'archive ; avec les empreintes, il pouvait tenter de casser hors ligne les mots de passe de
# toutes les personnes de l'espace (gestionnaire de l'installation compris). Le mot de passe fait foi au registre commun
# (``referentiel.auth``) : à la restauration, la réconciliation remet dans chaque copie celui du registre. Valeur posée à
# la place : « ! » en tête, donc inutilisable pour Django (``is_password_usable``), et reconnaissable après une
# restauration sans le registre (autre serveur) : ``comptes_sans_mot_de_passe``. Seule l'archive du registre
# (``backups/shared``, jamais téléchargeable dans l'outil) garde les empreintes.
MOT_DE_PASSE_RETIRE = "!password-not-in-backup"


class ErreurSauvegarde(Exception):
    pass


@dataclass
class Archive:
    chemin: Path

    @property
    def nom(self):
        return self.chemin.name

    @property
    def taille(self):
        return self.chemin.stat().st_size

    @property
    def taille_texte(self):
        return taille_lisible(self.taille)

    @property
    def date(self):
        d = datetime.datetime.strptime(_horodatage(self.nom), "%Y%m%d-%H%M%S")
        return timezone.make_aware(d)

    @property
    def motif(self):
        motif = self.nom.split("-", 1)[1][len("AAAAMMJJ-HHMMSS"):-len(".zip")].lstrip("-")
        return ANCIENS_MOTIFS.get(motif, motif)


# ---------------------------------------------------------------- état
def dossier():
    """Dossier des sauvegardes de l'espace courant (SAUVEGARDES_DIR pour l'espace principal)."""
    return ESP.dossier_sauvegardes()


def archives():
    """Archives du dossier des sauvegardes, la plus récente d'abord."""
    d = dossier()
    if not d.is_dir():
        return []
    return sorted((Archive(p) for p in d.iterdir() if NOM.match(p.name) and p.is_file()), key=lambda a: (_horodatage(a.nom), a.nom), reverse=True)


def archive(nom):
    """Archive par son nom (refusé s'il ne suit pas le modèle : pas de chemin arbitraire)."""
    if not NOM.match(nom or "") or not (dossier() / nom).is_file():
        raise ErreurSauvegarde(libelle("admin.sauvegarde.introuvable", nom=nom))
    return Archive(dossier() / nom)


def migrations_appliquees():
    """Migrations notées dans la base, telles quelles : c'est ce qu'écrit le descriptif d'une archive (une sauvegarde faite
    avant une mise à jour doit rester restaurable par la version qui l'a faite)."""
    return sorted([a, n] for a, n in MigrationRecorder(ESP.connexion()).applied_migrations())


def migrations_comparables():
    """Migrations de la base aux noms actuels (migrations renommées) : pour la comparer au descriptif d'une archive."""
    return paires_actuelles(migrations_appliquees())


def comptes():
    """Nombre de lignes par table de l'outil (contrôle d'une restauration). Lu en SQL : la base peut être d'une version
    antérieure (sauvegarde automatique avant les migrations d'une mise à jour)."""
    tables = set(ESP.connexion().introspection.table_names())
    sortie = {}
    with ESP.connexion().cursor() as c:
        for m in apps.get_models():
            if m._meta.app_label in ("parametres", "referentiel", "collecte", "auth") and m._meta.db_table in tables:
                c.execute(f"SELECT COUNT(*) FROM {ESP.connexion().ops.quote_name(m._meta.db_table)}")
                sortie[m._meta.label] = c.fetchone()[0]
    return sortie


def nom_installation():
    """Nom de l'installation, s'il est déjà enregistré (base d'une version antérieure : vide)."""
    from .models import Instance

    if Instance._meta.db_table not in ESP.connexion().introspection.table_names():
        return ""
    with ESP.connexion().cursor() as c:
        c.execute(f"SELECT nom FROM {ESP.connexion().ops.quote_name(Instance._meta.db_table)} WHERE id = 1")
        ligne = c.fetchone()
    return ligne[0] if ligne else ""


def _identifiant_installation():
    from espaces import comptes as EC

    i = EC.installation()
    return i.identifiant if i else ""


def controler_espace(d, autre_espace=False):
    """Refuse de restaurer dans cet espace une archive d'un autre espace ou d'une autre installation (sauf option de
    l'IT ``autre_espace``). Une archive d'avant les espaces (sans marque) ne va que dans l'espace principal."""
    if autre_espace:
        return
    ici, ident = ESP.code_courant(), _identifiant_installation()
    source = d.get("espace") or ESP.PRINCIPAL
    if source != ici:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.autre_espace", source=source, ici=ici))
    if d.get("identifiant_installation") and ident and d["identifiant_installation"] != ident:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.autre_installation"))


def base_vide():
    """Vrai si la base n'a pas encore de tables (premier démarrage) : rien à sauvegarder."""
    return "django_migrations" not in ESP.connexion().introspection.table_names()


# ---------------------------------------------------------------- sauvegarder
def creer(motif="", format_base=None, accepter_abimee=False):
    """Crée une archive dans le dossier des sauvegardes et la renvoie. ``format_base`` : « sqlite » ou « json »
    (par défaut : sqlite pour une base SQLite, json sinon).

    Base SQLite : la copie est contrôlée (``PRAGMA quick_check``) avant d'être gardée. Une base abîmée n'est pas
    sauvegardée (ErreurSauvegarde, base signalée à /sante/) : sinon la rotation remplacerait peu à peu les bonnes
    archives par des copies abîmées. ``accepter_abimee`` (sauvegarde avant une restauration) : l'archive est gardée
    quand même, avec « -damaged » dans son nom. Fichiers en cours (archive partielle cachée dans le dossier des
    sauvegardes, copie temporaire de la base) : effacés en cas d'erreur, ou au démarrage suivant après un arrêt brutal."""
    motif = (motif or "").strip().lower()
    if not MOTIF.match(motif):
        raise ErreurSauvegarde(libelle("admin.sauvegarde.motif"))
    format_base = format_base or ("sqlite" if ESP.connexion().vendor == "sqlite" else "json")
    if format_base == "sqlite" and ESP.connexion().vendor != "sqlite":
        raise ErreurSauvegarde(libelle("admin.sauvegarde.sqlite_impossible"))
    if format_base == "sqlite" and ESP.connexion().in_atomic_block:  # la copie attendrait sans fin la fin de la transaction
        raise ErreurSauvegarde(libelle("admin.sauvegarde.transaction"))
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    partiel = d / f".backup-{os.getpid()}-{time.monotonic_ns()}.partiel"
    debut = time.monotonic()
    nb_fichiers = 0
    integrite = ""
    tables = migrations = None
    try:
        with tempfile.TemporaryDirectory(prefix=TEMPORAIRE) as tmp, \
                zipfile.ZipFile(partiel, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            if format_base == "sqlite":
                copie = Path(tmp) / BASE_SQLITE
                ESP.connexion().ensure_connection()
                cible = sqlite3.connect(copie)
                try:
                    ESP.connexion().connection.backup(cible)
                    vider_dans_la_copie(cible)
                    integrite = controle_sqlite(cible)
                finally:
                    cible.close()
                if integrite != "ok":
                    noter_base_abimee(integrite)
                    if not accepter_abimee:
                        raise ErreurSauvegarde(libelle("admin.sauvegarde.base_abimee", detail=integrite[:300]))
                    motif = (motif + "-damaged").strip("-")[:40]
                else:
                    noter_base_abimee("")
                z.write(copie, BASE_SQLITE)
            else:
                sortie = Path(tmp) / BASE_JSON
                with open(sortie, "w", encoding="utf-8") as f, instantane():  # comptes du descriptif du même instantané
                    exporter_json(f, sans_mots_de_passe=True)
                    tables, migrations = comptes(), migrations_appliquees()
                z.write(sortie, BASE_JSON)
            for chemin, rel in _fichiers_deposes():
                z.write(chemin, f"{FICHIERS_ARCHIVE}{rel}")
                nb_fichiers += 1
            maintenant = timezone.localtime()
            descriptif = {
                "format": FORMAT, "outil": OUTIL, "version": settings.VERSION, "date": maintenant.isoformat(),
                "motif": motif, "moteur": ESP.connexion().vendor, "contenu_base": format_base, "installation": nom_installation(),
                "espace": ESP.code_courant(), "identifiant_installation": _identifiant_installation(),
                "migrations": migrations if migrations is not None else migrations_appliquees(),
                "tables": tables if tables is not None else comptes(), "fichiers": nb_fichiers,
                "integrite": integrite or "not checked",
            }
        with zipfile.ZipFile(partiel, "a", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            # signature : calculée sur le contenu tel qu'il est écrit dans l'archive (relu), puis descriptif ajouté
            descriptif[SIGNATURE] = {"algorithme": ALGORITHME_SIGNATURE,
                                     "valeur": _signer(descriptif, _empreintes(z), settings.SECRET_KEY)}
            z.writestr(DESCRIPTIF, json.dumps(descriptif, ensure_ascii=False, indent=1))
        nom = _nom_libre(d, "backup", maintenant, motif)
        os.replace(partiel, d / nom)
    except OSError as e:
        if getattr(e, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
            raise ErreurSauvegarde(libelle("admin.sauvegarde.disque_plein", dossier=str(d),
                                           libre=taille_lisible(_place_libre(d)))) from e
        raise
    finally:
        if partiel.exists():
            partiel.unlink()
    a = Archive(d / nom)
    journal.info("Backup %s: %s uploaded file(s), %.1f MB, %.1f s", a.nom, nb_fichiers, a.taille / 1e6,
                 time.monotonic() - debut)
    return a


def _tables(etiquettes):
    """Noms des tables des modèles désignés par ``etiquettes`` (« application » ou « application.modèle »)."""
    noms = []
    for e in etiquettes:
        app, _, modele = e.lower().partition(".")
        try:
            config = apps.get_app_config(app)
        except LookupError:
            continue
        noms += [m._meta.db_table for m in config.get_models(include_auto_created=True)
                 if not modele or m._meta.model_name == modele]
    return noms


def _table_comptes():
    from referentiel.models import Utilisateur

    return Utilisateur._meta.db_table


def vider_dans_la_copie(cible):
    """Vide, dans la copie SQLite ``cible`` d'une archive, les tables de ``TABLES_VIDEES_DANS_LA_COPIE`` (jetons des
    assistants…) et retire les empreintes des mots de passe (``MOT_DE_PASSE_RETIRE``). ``secure_delete`` : les lignes
    effacées sont écrasées dans le fichier, pas seulement libérées ; puis ``VACUUM`` réécrit la copie sans aucune page
    libre : une empreinte d'avant (compte supprimé, mot de passe changé), restée dans l'espace libre de la base vivante et
    recopiée par l'API de sauvegarde, ne passe pas dans l'archive."""
    presentes = {r[0] for r in cible.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    cible.execute("PRAGMA secure_delete = ON")
    for table in _tables(TABLES_VIDEES_DANS_LA_COPIE):
        if table in presentes:
            cible.execute(f'DELETE FROM "{table}"')
    if _table_comptes() in presentes:
        cible.execute(f'UPDATE "{_table_comptes()}" SET password = ?', [MOT_DE_PASSE_RETIRE])
    cible.commit()
    cible.execute("VACUUM")


def _sans_mot_de_passe(objets):
    """Archive JSON : chaque compte écrit avec ``MOT_DE_PASSE_RETIRE`` à la place de l'empreinte de son mot de passe."""
    for o in objets:
        if o._meta.label_lower == "referentiel.utilisateur":
            o.password = MOT_DE_PASSE_RETIRE
        yield o


def comptes_sans_mot_de_passe():
    """Comptes actifs de l'espace courant sans mot de passe après une restauration : leur archive n'en a pas
    (``MOT_DE_PASSE_RETIRE``) et le registre commun ne les connaissait pas (archive restaurée sur un autre serveur sans le
    registre, ou compte retiré du registre depuis la sauvegarde). Personne n'y entre tant que l'IT n'a pas restauré le
    registre (``restore --shared``) ou qu'on ne leur a pas donné un nouveau mot de passe."""
    from referentiel.models import Utilisateur

    try:
        return Utilisateur._default_manager.filter(password=MOT_DE_PASSE_RETIRE, is_active=True).count()
    except Exception:  # noqa: BLE001 - base d'une version antérieure : rien à compter
        return 0


def empreintes_jetons_mcp():
    """Empreintes des jetons d'assistant encore utilisables dans la base de l'espace (lu avant une restauration)."""
    from serveur_mcp.models import JetonMCP

    try:
        if JetonMCP._meta.db_table not in ESP.connexion().introspection.table_names():
            return set()
        return set(JetonMCP.objects.filter(revoque_le__isnull=True, expire_le__gt=timezone.now())
                   .values_list("empreinte", flat=True))
    except Exception:  # base illisible ou d'une version antérieure : rien à compter
        return set()


def retirer_jetons_mcp(avant=()):
    """Après une restauration (tout format, toute archive, même faite avant que les jetons en soient retirés) : plus aucun
    jeton d'assistant dans l'espace restauré, les personnes en recréent un (docs/mcp.md, 1.4). ``avant`` : empreintes
    des jetons utilisables avant la restauration (remplacés avec la base). Une ligne au journal de l'espace (nombre de
    jetons qui ne servent plus) et au journal du serveur. Renvoie ce nombre."""
    from collecte.models import Journal
    from serveur_mcp.models import JetonMCP

    if JetonMCP._meta.db_table not in ESP.connexion().introspection.table_names():
        return 0
    restes = set(JetonMCP.objects.filter(revoque_le__isnull=True, expire_le__gt=timezone.now())
                 .values_list("empreinte", flat=True))
    JetonMCP.objects.all().delete()
    n = len(set(avant) | restes)
    if n:
        Journal.objects.create(utilisateur=None, action="jeton_mcp", objet="Instance", objet_id="1",
                               champ="mcp_jetons_restauration", avant=str(n), apres="")
        journal.info("Restore: %s assistant token(s) (MCP) deleted; people create new ones", n)
    return n


# copie de la base en cours de sauvegarde ou de restauration, dans le dossier temporaire du système (hors du disque des
# données, souvent plein le premier) ; restes d'un arrêt brutal effacés au démarrage
TEMPORAIRE = "reporting-backup-"


def _nom_libre(d, prefixe, maintenant, motif):
    """« backup-20261101-023000-auto.zip » ; deux sauvegardes dans la même seconde : la seconde suivante."""
    while True:
        nom = f"{prefixe}-{maintenant:%Y%m%d-%H%M%S}{'-' + motif if motif else ''}.zip"
        if not (d / nom).exists():
            return nom
        maintenant += datetime.timedelta(seconds=1)


def _place_libre(d):
    try:
        return shutil.disk_usage(d).free
    except OSError:
        return 0


def nettoyer_restes():
    """Démarrage : fichiers laissés par une sauvegarde, un dépôt ou une restauration interrompus brutalement dans
    l'espace courant (archive partielle, fichiers extraits) et copies temporaires de la base (dossier temporaire du
    système, de plus de 10 minutes) ; renvoie le nombre d'éléments effacés.
    Jamais une archive terminée."""
    d = dossier()
    n = 0
    for p in (d.iterdir() if d.is_dir() else []):
        if p.name.startswith(".") and p.name.endswith(".partiel"):
            p.unlink(missing_ok=True)
            n += 1
    try:
        temporaires = [p for p in Path(tempfile.gettempdir()).iterdir() if p.is_dir() and p.name.startswith(TEMPORAIRE)]
    except OSError:
        temporaires = []
    for p in temporaires:  # plus de 10 minutes : plus aucune sauvegarde ne s'en sert (copie en quelques secondes)
        try:
            if time.time() - p.stat().st_mtime > 600:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except OSError:
            continue
    if not restauration_en_cours():  # extraction interrompue avant tout changement : dossiers de passage inutiles
        for reste in (NOUVEAUX, ANCIENS_FICHIERS):
            if (ESP.dossier_medias() / reste).exists():
                shutil.rmtree(ESP.dossier_medias() / reste, ignore_errors=True)
                n += 1
    return n


DEPOT_PARTIEL = re.compile(r"^\..+\.[0-9a-f]{8}\.part$")  # fichier déposé en cours d'écriture (espaces/stockage.py)


def nettoyer_depots_partiels():
    """Démarrage : fichiers déposés restés à moitié écrits après un arrêt brutal (jamais une preuve enregistrée)."""
    racine = ESP.dossier_medias()
    n = 0
    if racine.is_dir():
        for dossier_courant, _, noms in os.walk(racine):
            for nom in noms:
                if DEPOT_PARTIEL.match(nom):
                    (Path(dossier_courant) / nom).unlink(missing_ok=True)
                    n += 1
    return n


# ---------------------------------------------------------------- intégrité (SQLite)
ABIMEE = ".database-damaged"  # dans le dossier des sauvegardes de l'espace : base abîmée (lu par /sante/)


def controle_sqlite(connexion_sqlite):
    """« ok », ou le début du rapport de ``PRAGMA quick_check`` (base abîmée)."""
    try:
        lignes = [r[0] for r in connexion_sqlite.execute("PRAGMA quick_check(20)").fetchall()]
    except sqlite3.DatabaseError as e:
        return str(e) or "unreadable"
    return "ok" if lignes == ["ok"] else "; ".join(lignes)[:2000]


def controler_base():
    """Contrôle la base SQLite de l'espace courant (démarrage) ; renvoie « ok » ou le défaut (noté pour /sante/).
    PostgreSQL : « ok » (contrôles du serveur)."""
    c = ESP.connexion()
    if c.vendor != "sqlite":
        return "ok"
    try:
        c.ensure_connection()
        resultat = controle_sqlite(c.connection)
    except Exception as e:  # en-tête détruit : « file is not a database »
        resultat = str(e) or type(e).__name__
    noter_base_abimee("" if resultat == "ok" else resultat)
    return resultat


def noter_base_abimee(detail, code=None):
    f = ESP.dossier_sauvegardes(code) / ABIMEE
    try:
        if detail:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(detail[:2000], encoding="utf-8")
        else:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def base_abimee(code=None):
    """Défaut noté par le dernier contrôle de la base de l'espace (démarrage, sauvegarde), sinon ""."""
    try:
        return (ESP.dossier_sauvegardes(code) / ABIMEE).read_text(encoding="utf-8")
    except OSError:
        return ""


def derniere_archive_saine():
    """Archive la plus récente dont la base a passé le contrôle d'intégrité (ou d'avant ce contrôle), sinon None."""
    for a in archives():
        if "damaged" in a.motif:
            continue
        try:
            if lire_descriptif(a.chemin).get("integrite", "ok") in ("ok", "not checked"):
                return a
        except ErreurSauvegarde:
            continue
    return None


class EncodeurExact(DjangoJSONEncoder):
    """Comme celui de Django, mais sans tronquer les dates aux millisecondes (restauration à l'identique)."""

    def default(self, o):
        if isinstance(o, (datetime.datetime, datetime.time)):
            r = o.isoformat()
            return r[:-6] + "Z" if r.endswith("+00:00") else r
        return super().default(o)


def modeles_sauvegardes(registre=None):
    """Modèles de toutes les applications rangés dans la base de l'espace courant (jamais le registre commun des
    comptes), dans un ordre où chaque table vient après celles dont elle dépend. ``registre`` : les modèles tels que les
    décrivent les migrations déjà appliquées (base pas encore mise à jour), au lieu de ceux du code."""
    from django.db import router

    from espaces import contexte as E

    alias = E.alias_courant()
    exclus = {e.lower() for e in TABLES_EXCLUES}
    liste = []
    for app in (registre or apps).get_app_configs():
        if app.label in exclus:
            continue
        modeles = [m for m in app.get_models() if m._meta.label_lower not in exclus and m._meta.managed and not m._meta.proxy
                   and router.allow_migrate_model(alias, m)]
        if modeles:
            liste.append((app, modeles))
    return serializers.sort_dependencies(liste, allow_cycles=True)


def modeles_de_la_base():
    """Base avec des migrations en attente (sauvegarde automatique avant une mise à jour, PostgreSQL) : les modèles tels
    que les migrations déjà appliquées les décrivent, c'est-à-dire les tables et colonnes qui existent vraiment ; None si
    la base est à jour (les modèles du code). Sans cela, une table ou une colonne ajoutée par la mise à jour ferait
    échouer la sauvegarde, et donc le démarrage."""
    from django.db.migrations.executor import MigrationExecutor

    ex = MigrationExecutor(ESP.connexion())
    if not ex.migration_plan(ex.loader.graph.leaf_nodes()):
        return None
    appliquees = [n for n in ex.loader.applied_migrations if n in ex.loader.graph.nodes]  # sans les applications retirées
    return ex.loader.project_state(appliquees, at_end=True).apps


@contextlib.contextmanager
def instantane():
    """Transaction de lecture sur la base de l'espace courant, qui voit la base telle qu'elle était à sa première lecture.
    Sans elle, l'export lit les tables une par une : une saisie ou un import fait entre deux tables laisserait dans
    l'archive une preuve, une alerte ou une ligne du journal pointant vers une réponse absente, et la restauration (tout ou
    rien) échouerait. PostgreSQL : REPEATABLE READ READ ONLY. SQLite : transaction différée, comme
    ``collecte.controle_donnees._lecture_seule`` (les réglages de l'outil ouvrent les transactions en IMMEDIATE, qui
    poserait le verrou d'écriture pendant tout l'export : toute saisie attendrait puis échouerait « database is locked » ;
    en WAL, une lecture différée voit un instantané fixe sans bloquer personne). Déjà dans une transaction : rien de plus
    (le niveau d'isolement ne peut plus changer)."""
    c = ESP.connexion()
    if c.in_atomic_block:
        yield
        return
    if c.vendor == "sqlite":
        c.ensure_connection()  # le mode est relu des réglages à l'ouverture de la connexion : l'ouvrir avant de le changer
    mode = getattr(c, "transaction_mode", None)
    if c.vendor == "sqlite":
        c.transaction_mode = "DEFERRED"
    try:
        with transaction.atomic(using=c.alias):
            if c.vendor == "postgresql":
                with c.cursor() as curseur:
                    curseur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield
    finally:
        if c.vendor == "sqlite":
            c.transaction_mode = mode


def _naturelles(modele):
    """Clés étrangères de ``modele`` écrites par leur clé naturelle dans l'archive (modèle cité doté de ``natural_key`` :
    utilisateur, type de contenu, permission…), avec, un niveau plus bas, celles que cette clé naturelle cite à son tour
    (une permission se nomme avec son type de contenu)."""
    noms = []
    for f in modele._meta.concrete_fields:
        if f.is_relation and f.remote_field is not None and hasattr(f.remote_field.model, "natural_key"):
            noms.append(f.name)
            noms += [f"{f.name}__{g.name}" for g in f.remote_field.model._meta.concrete_fields
                     if g.is_relation and g.remote_field is not None and hasattr(g.remote_field.model, "natural_key")]
    return noms


def requete_export(modele):
    """Lignes de ``modele`` pour l'archive JSON, avec ce que le sérialiseur lirait sinon ligne par ligne : les objets
    cités par clé naturelle (une requête par ligne du journal pour retrouver l'utilisateur : 15 minutes pour 4 millions de
    lignes sous PostgreSQL) et les liens plusieurs-à-plusieurs, lus avec les mêmes requêtes (même ordre) que le
    sérialiseur. Contenu de l'archive inchangé."""
    from django.db.models import Prefetch

    qs = modele._base_manager.order_by(modele._meta.pk.name)
    naturelles = _naturelles(modele)
    if naturelles:
        qs = qs.select_related(*naturelles)
    liens = []
    for f in modele._meta.many_to_many:
        if not f.remote_field.through._meta.auto_created:
            continue  # table intermédiaire déclarée : sérialisée à part, comme avant
        cible = f.remote_field.model
        if hasattr(cible, "natural_key"):
            liens.append(Prefetch(f.name, queryset=cible._default_manager.select_related(*_naturelles(cible))))
        else:
            liens.append(Prefetch(f.name, queryset=cible._default_manager.select_related(None).only("pk")))
    if liens:
        qs = qs.prefetch_related(*liens)
    return qs.iterator(chunk_size=2000)


def exporter_json(flux, sans_mots_de_passe=False):
    """Toutes les tables au format JSON de Django (clés naturelles pour les types de contenu et permissions), telles
    qu'elles sont dans la base (avant une mise à jour : selon les migrations déjà appliquées), lues dans un même
    instantané (``instantane``), sans une requête par ligne (``requete_export``). ``sans_mots_de_passe`` (archive,
    ``creer``) : empreintes des mots de passe remplacées par ``MOT_DE_PASSE_RETIRE``."""
    with instantane():
        objets = (o for m in modeles_sauvegardes(modeles_de_la_base()) for o in requete_export(m))
        if sans_mots_de_passe:
            objets = _sans_mot_de_passe(objets)
        serializers.serialize("json", objets, stream=flux, use_natural_foreign_keys=True, cls=EncodeurExact)


def _proteges(racine):
    """Chemins placés dans le dossier des fichiers ``racine`` de l'espace (par l'IT : ``ESPACES_DOSSIER`` sous
    ``MEDIA_ROOT``…) qui ne sont pas des fichiers déposés : dossier des autres espaces, sauvegardes, bases SQLite
    (registre des comptes compris), clé secrète, clés de la prise IA. Ni sauvegardés avec l'espace, ni effacés ni
    écrasés quand on le restaure."""
    from django.db import connections

    chemins = {Path(settings.ESPACES_DOSSIER), ESP.dossier_sauvegardes(ESP.PRINCIPAL),
               Path(settings.DOSSIER_DONNEES) / ".cle_secrete", Path(settings.DOSSIER_DONNEES) / ".secret_key",
               Path(settings.IA_CLES_DIR)}
    for conf in connections.settings.values():
        if str(conf.get("ENGINE", "")).endswith("sqlite3") and str(conf.get("NAME", "")) not in ("", ":memory:"):
            nom = str(conf["NAME"])
            chemins |= {Path(nom + suffixe) for suffixe in ("", "-wal", "-shm", "-journal")}
    racine = Path(racine).resolve()
    return {c.resolve() for c in chemins if racine in c.resolve().parents}


def _touche_un_protege(chemin, proteges):
    """Vrai si ``chemin`` est protégé ou contient un chemin protégé."""
    c = Path(chemin).resolve()
    return any(p == c or c in p.parents for p in proteges)


def _fichiers_deposes():
    racine = ESP.dossier_medias()
    if not racine.is_dir():
        return
    proteges = _proteges(racine)
    for dossier_courant, sous, noms in os.walk(racine):
        rel_dossier = Path(dossier_courant).relative_to(racine)
        sous[:] = [s for s in sous if not (rel_dossier == Path(".") and s in EXCLUS)
                   and (Path(dossier_courant) / s).resolve() not in proteges]
        for n in sorted(noms):
            p = Path(dossier_courant) / n
            if p.resolve() in proteges or DEPOT_PARTIEL.match(n):
                continue
            yield p, (rel_dossier / n).as_posix()


def tourner(conserver=None):
    """Supprime les archives au-delà des ``conserver`` plus récentes ; renvoie les noms supprimés."""
    if conserver is None:
        from .models import Instance

        conserver = Instance.courante().sauvegarde_conserver if not base_vide() else settings.SAUVEGARDE_CONSERVER
    supprimees = []
    limite = timezone.localtime() + datetime.timedelta(days=1)
    liste = archives()
    futures = [a for a in liste if a.date > limite]
    if futures:  # horloge du serveur remise en arrière : ces archives ne sont pas les plus récentes, mais on les garde
        journal.warning("%s backup(s) dated in the future (%s): check the server clock; they are kept, not rotated",
                        len(futures), futures[0].nom)
    for a in [a for a in liste if a not in futures][max(conserver, 1):]:
        a.chemin.unlink()
        supprimees.append(a.nom)
    if supprimees:
        journal.info("Rotation: %s old backup(s) deleted (%s kept)", len(supprimees), conserver)
    return supprimees


# ---------------------------------------------------------------- signature
# Signature des archives : à la création, l'outil signe l'archive (HMAC-SHA256, clé dérivée
# du secret de l'installation, ``SECRET_KEY``) ; la signature, dans le descriptif, couvre tout le descriptif et le nom,
# la taille et l'empreinte SHA-256 de chaque autre fichier de l'archive. Restauration depuis l'outil et archive déposée :
# une archive sans signature valide est refusée (``exiger_signature``). L'IT peut toujours la restaurer en ligne de
# commande (« restore … --unsigned ») : archives d'avant cette version, d'un autre serveur, d'une installation dont le
# secret a changé. Le secret ne quitte jamais le serveur : une archive téléchargée puis modifiée ne se signe pas ailleurs.
SIGNATURE = "signature"
ALGORITHME_SIGNATURE = "hmac-sha256"
SEL_SIGNATURE = "probant.backup-signature.v1"


def _empreintes(z, exclure=(DESCRIPTIF,)):
    """[[nom, taille, SHA-256]] de chaque fichier de l'archive ouverte ``z`` (sauf ``exclure``), triés par nom ; lus
    décompressés, comme la restauration les lira."""
    import hashlib

    sortie = []
    for info in z.infolist():
        if info.filename in exclure:
            continue
        h = hashlib.sha256()
        with z.open(info) as f:
            for bloc in iter(lambda: f.read(1 << 20), b""):
                h.update(bloc)
        sortie.append([info.filename, info.file_size, h.hexdigest()])
    return sorted(sortie)


def _signer(descriptif, empreintes, secret):
    """Signature (hexadécimal) du descriptif (sans sa signature) et des empreintes du contenu, avec la clé dérivée de
    ``secret``."""
    from django.utils.crypto import salted_hmac

    # relu comme du JSON : la même chose à la création (objets Python) et à la vérification (descriptif lu dans l'archive)
    d = json.loads(json.dumps({k: v for k, v in descriptif.items() if k != SIGNATURE}, cls=DjangoJSONEncoder))
    message = json.dumps({"descriptif": d, "contenu": empreintes}, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return salted_hmac(SEL_SIGNATURE, message, secret=secret, algorithm="sha256").hexdigest()


def signature_valide(chemin):
    """Vrai si l'archive a été signée par cette installation (``SECRET_KEY``, ou une clé de ``SECRET_KEY_FALLBACKS``) et
    que rien n'y a changé depuis : ni le descriptif, ni un fichier, ni un fichier ajouté ou retiré. Faux pour une archive
    sans signature (faite avant cette version, ou par une version antérieure), d'un autre serveur, abîmée ou forgée.
    Deux fichiers du même nom dans l'archive : refusée (on ne saurait pas lequel la restauration lirait)."""
    import hmac

    try:
        with zipfile.ZipFile(chemin) as z:
            noms = [i.filename for i in z.infolist()]
            if len(noms) != len(set(noms)) or nom_dans(set(noms), DESCRIPTIF) != DESCRIPTIF \
                    or ANCIENS[DESCRIPTIF] in noms:
                return False
            d = json.loads(z.read(DESCRIPTIF))
            s = d.get(SIGNATURE) if isinstance(d, dict) else None
            if not isinstance(s, dict) or s.get("algorithme") != ALGORITHME_SIGNATURE or not isinstance(s.get("valeur"), str):
                return False
            empreintes = _empreintes(z)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, ValueError, OSError, EOFError, RuntimeError):
        return False
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]
    return any(hmac.compare_digest(_signer(d, empreintes, secret), s["valeur"]) for secret in secrets)


def controler_signature(chemin):
    """Refuse (ErreurSauvegarde, message pour l'administrateur) une archive sans signature valide de cette installation."""
    if not signature_valide(chemin):
        raise ErreurSauvegarde(libelle("admin.sauvegarde.non_signee"))


# ---------------------------------------------------------------- restaurer
def lire_descriptif(chemin):
    try:
        with zipfile.ZipFile(chemin) as z:
            noms = set(z.namelist())
            d = json.loads(z.read(nom_dans(noms, DESCRIPTIF) or DESCRIPTIF))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.pas_une_sauvegarde", erreur=str(e))) from e
    if not isinstance(d, dict) or d.get("outil") not in OUTILS_ACCEPTES or d.get("format") != FORMAT:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.format_inconnu"))
    if not (nom_dans(noms, BASE_SQLITE) or nom_dans(noms, BASE_JSON)):
        raise ErreurSauvegarde(libelle("admin.sauvegarde.incomplete"))
    m = d.get("migrations")
    if isinstance(m, list) and all(isinstance(x, (list, tuple)) and len(x) == 2 and all(isinstance(y, str) for y in x)
                                   for x in m):
        d["migrations"] = paires_actuelles(m)  # archive faite avant le renommage d'une migration : noms actuels
    return d


def deposer(fichier):
    """Range dans le dossier des sauvegardes une archive déposée depuis l'outil (après vérification) et la renvoie."""
    if (getattr(fichier, "size", 0) or 0) > settings.SAUVEGARDE_DEPOT_MAX:
        raise ErreurSauvegarde(libelle("messages.envoi.trop_gros", mo=f"{settings.SAUVEGARDE_DEPOT_MAX / 1024 / 1024:.0f}"))
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    partiel = d / f".depot-{os.getpid()}-{time.monotonic_ns()}.partiel"
    try:
        try:
            with open(partiel, "wb") as f:
                for morceau in fichier.chunks():
                    f.write(morceau)
        except OSError as e:
            if getattr(e, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
                raise ErreurSauvegarde(libelle("admin.sauvegarde.disque_plein", dossier=str(d),
                                               libre=taille_lisible(_place_libre(d)))) from e
            raise
        lire_descriptif(partiel)
        controler_signature(partiel)  # seules les archives de cette installation, intactes, entrent par l'outil
        nom = f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-uploaded.zip"
        while (d / nom).exists():
            time.sleep(1)
            nom = f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-uploaded.zip"
        os.replace(partiel, d / nom)
    finally:
        if partiel.exists():
            partiel.unlink()
    return Archive(d / nom)


HISTORIQUE = "restores.jsonl"  # dans le dossier des sauvegardes : hors de la base, il survit aux restaurations


def _historique():
    """Fichier de l'historique des restaurations (ancien nom « restaurations.jsonl » repris)."""
    f, ancien = dossier() / HISTORIQUE, dossier() / "restaurations.jsonl"
    if ancien.is_file() and not f.exists():
        ancien.rename(f)
    return f


def historique_restaurations():
    """Restaurations passées, la plus récente d'abord : [{date, archive, date_sauvegarde, version, avant, par, origine}]."""
    f = _historique()
    if not f.is_file():
        return []
    sortie = []
    for ligne in f.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ligne)
            e["date"] = datetime.datetime.fromisoformat(e["date"])
            sortie.append(e)
        except (ValueError, KeyError, TypeError):
            continue
    return sortie[::-1]


def _noter_restauration(chemin, d, avant, par, origine):
    dossier().mkdir(parents=True, exist_ok=True)
    e = {"date": timezone.localtime().isoformat(), "archive": Path(chemin).name, "date_sauvegarde": d.get("date", ""),
         "version": d.get("version", ""), "avant": avant.nom if avant else "", "par": par or "", "origine": origine}
    with open(_historique(), "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")


def controler_place(chemin):
    """Refuse une archive qui, décompressée, ne tiendrait pas sur le disque (archive piégée : quelques Mo compressés qui
    annoncent des Go). Les tailles annoncées dans l'archive sont des plafonds : la lecture s'arrête à la taille annoncée."""
    with zipfile.ZipFile(chemin) as z:
        besoin = sum(i.file_size for i in z.infolist())
    racine = ESP.dossier_medias()
    racine.mkdir(parents=True, exist_ok=True)
    libre = min(shutil.disk_usage(tempfile.gettempdir()).free, shutil.disk_usage(racine).free)
    if besoin > libre - 100 * 1024 * 1024:  # 100 Mo gardés pour l'outil
        raise ErreurSauvegarde(libelle("admin.sauvegarde.trop_grosse", besoin=taille_lisible(besoin), libre=taille_lisible(libre)))


EN_COURS = ".restore-in-progress.json"  # dans le dossier des sauvegardes : restauration commencée, pas terminée
NOUVEAUX, ANCIENS_FICHIERS = ".restore-new", ".restore-old"  # dossiers de passage dans le dossier des fichiers


def restauration_en_cours(code=None):
    """Restauration commencée et pas terminée (arrêt brutal, serveur tué) : {archive, avant, par, origine, date…},
    sinon None. Elle est terminée au démarrage suivant (``reprendre_restauration``)."""
    try:
        return json.loads((ESP.dossier_sauvegardes(code) / EN_COURS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def restauration_abandonnee(code=None):
    """Restauration interrompue dont le processus n'existe plus (processus du serveur tué en pleine restauration, par
    exemple au-delà du délai de gunicorn) : le planificateur la termine sans attendre un redémarrage. Linux / macOS
    seulement (ailleurs : au démarrage)."""
    e = restauration_en_cours(code)
    if not e or os.name != "posix" or not isinstance(e.get("pid"), int):
        return False
    try:
        os.kill(e["pid"], 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _base_lisible():
    """Faux si la base SQLite de l'espace ne s'ouvre plus (en-tête détruit…) : la restauration remplace alors le
    fichier lui-même (mode secours) au lieu de copier dans la base ouverte."""
    c = ESP.connexion()
    if c.vendor != "sqlite":
        return True
    try:
        c.ensure_connection()
        c.connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return True
    except Exception:
        c.close()
        return False


def _controler_base_extraite(fichier, d):
    """La base de l'archive est bien une base de l'outil, lisible, avec les migrations annoncées : sinon rien n'est touché
    (une base vide ou étrangère remplaçait celle de l'espace, et plus personne n'y entrait)."""
    try:
        source = sqlite3.connect(f"file:{fichier}?mode=ro", uri=True)
        try:
            etat = source.execute("PRAGMA quick_check").fetchone()
            presentes = {tuple(l) for l in paires_actuelles(source.execute("SELECT app, name FROM django_migrations"))}
        finally:
            source.close()
    except sqlite3.Error as e:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.pas_une_sauvegarde", erreur=str(e))) from e
    if not etat or etat[0] != "ok" or not {tuple(x) for x in d["migrations"]} <= presentes:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.incomplete"))


def migrations_du_code():
    """Migrations que le code installé connaît (toutes applications), en paires [application, nom]."""
    return sorted([a, n] for a, n in MigrationLoader(None, ignore_no_migrations=True).graph.nodes)


def reconstruction_possible(d):
    """Vrai si la base de l'espace peut être reconstruite pour l'archive JSON ``d`` (« restore --rebuild ») : base
    PostgreSQL, et l'archive a exactement les migrations du code installé (retour à la version qui l'a faite). Une
    archive plus ancienne que le code ne se reconstruit pas : le contenu se charge avec les modèles du code, qui
    attendraient des colonnes absentes du schéma de l'archive."""
    return ESP.connexion().vendor == "postgresql" and paires_actuelles(d.get("migrations") or []) == migrations_du_code()


def _tables_de_l_outil():
    """Tables de l'outil dans le schéma de l'espace courant (PostgreSQL) : celles des modèles du code, et celles d'une
    version plus récente, reconnues à leur préfixe (« <application>_ », applications notées dans django_migrations,
    « django_ »). Les tables d'un autre logiciel dans le même schéma ne sont pas touchées."""
    c = ESP.connexion()
    with c.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        presentes = [r[0] for r in cur.fetchall()]
        prefixes = {"django_"} | {f"{cfg.label}_" for cfg in apps.get_app_configs()}
        if "django_migrations" in presentes:
            cur.execute("SELECT DISTINCT app FROM django_migrations")
            prefixes |= {f"{r[0]}_" for r in cur.fetchall()}
    connues = {m._meta.db_table for m in apps.get_models(include_auto_created=True)}
    return [t for t in presentes if t in connues or t.startswith(tuple(prefixes))]


def _reconstruire_et_charger(fichier_json, d):
    """« restore --rebuild » (PostgreSQL) : dans UNE transaction, les tables de l'outil de l'espace sont supprimées
    (y compris celles d'une version plus récente), recréées par les migrations du code installé, contrôlées (exactement
    les migrations de l'archive), puis remplies avec le contenu de l'archive. Un échec à n'importe quelle étape annule
    tout : la base reste telle qu'elle était."""
    c = ESP.connexion()
    with transaction.atomic(using=c.alias):
        tables = _tables_de_l_outil()
        with c.cursor() as cur:
            for t in tables:
                cur.execute(f"DROP TABLE IF EXISTS {c.ops.quote_name(t)} CASCADE")
        call_command("migrate", interactive=False, verbosity=0, database=c.alias)
        harmoniser(c, autres_bases(c.alias))  # migration renommée : la version d'avant doit encore démarrer ici
        if migrations_comparables() != paires_actuelles(d["migrations"]):
            raise ErreurSauvegarde(libelle("admin.sauvegarde.autre_version_postgres", version=d.get("version")))
        with c.cursor() as cur:  # les migrations passent des contraintes en IMMEDIATE pour la fin de la transaction :
            cur.execute("SET CONSTRAINTS ALL DEFERRED")  # le chargement, lui, les veut différées (ordre des lignes libre)
        call_command("flush", interactive=False, verbosity=0, database=c.alias)
        call_command("loaddata", str(fichier_json), verbosity=0, database=c.alias)
        statistiques_a_jour(c.alias)  # tables recréées, sans statistiques : ANALYZE après la validation
    journal.info("Rebuild: %s table(s) of the space dropped and created again with the migrations of the archive",
                 len(tables))


def restaurer(chemin, sauvegarder_avant=True, par="", origine="commande", autre_espace=False, _reprise=None,
              reconstruire=False, exiger_signature=False):
    """Remplace la base et les fichiers déposés par ceux de l'archive. Une sauvegarde de l'état actuel est faite avant
    (motif « before-restore »). Chaque restauration est notée dans l'historique (fichier du dossier des sauvegardes).
    Renvoie le descriptif de l'archive.

    Sans perte en cas d'arrêt brutal ou de disque plein : les fichiers de l'archive sont d'abord extraits à part
    (rien n'est encore changé si cela échoue) ; puis un repère « restauration en cours » est posé, la base remplacée
    (en une transaction) et les fichiers échangés ; le repère est retiré à la fin. Interrompue après le repère, la
    restauration est refaite depuis l'archive au démarrage suivant (``reprendre_restauration``).

    ``reconstruire`` (IT, « restore --rebuild », PostgreSQL) : archive JSON dont les migrations diffèrent de celles de
    la base (base déjà mise à jour par une version plus récente, retour arrière) ; acceptée seulement si elle a
    exactement les migrations du code installé (``reconstruction_possible``) : la base est alors reconstruite
    (``_reconstruire_et_charger``).

    ``exiger_signature`` (restauration depuis l'outil, et commande sans « --unsigned ») : une archive sans signature
    valide de cette installation est refusée avant tout changement (``controler_signature``)."""
    chemin = Path(chemin)
    d = lire_descriptif(chemin)
    if exiger_signature:
        controler_signature(chemin)
    m = d.get("migrations")
    if not isinstance(m, list) or not m or not all(
            isinstance(x, (list, tuple)) and len(x) == 2 and all(isinstance(y, str) for y in x) for x in m):
        raise ErreurSauvegarde(libelle("admin.sauvegarde.incomplete"))  # archive forgée ou abîmée : sans liste des migrations
    controler_espace(d, autre_espace)
    connues = {(a, n) for a, n in MigrationLoader(None, ignore_no_migrations=True).disk_migrations}
    inconnues = [f"{a}.{n}" for a, n in d["migrations"] if (a, n) not in connues]
    if inconnues:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.version_recente", version=d.get("version")))
    if ESP.connexion().in_atomic_block:
        raise ErreurSauvegarde(libelle("admin.sauvegarde.restauration_transaction"))
    if _reprise is None and restauration_en_cours():
        raise ErreurSauvegarde(libelle("admin.sauvegarde.restauration_en_cours"))
    if _reprise is not None:  # restes de la tentative interrompue : refaits depuis l'archive
        for reste in (NOUVEAUX, ANCIENS_FICHIERS):
            shutil.rmtree(ESP.dossier_medias() / reste, ignore_errors=True)
    controler_place(chemin)
    lisible = _base_lisible()
    jetons_avant = empreintes_jetons_mcp() if lisible and _reprise is None else set()
    avant = None
    if _reprise is not None:
        avant = Archive(dossier() / _reprise["avant"]) if _reprise.get("avant") else None
    elif sauvegarder_avant and lisible and not base_vide():
        avant = creer("before-restore", accepter_abimee=True)
    racine = ESP.dossier_medias()
    racine.mkdir(parents=True, exist_ok=True)
    dossier().mkdir(parents=True, exist_ok=True)
    repere = dossier() / EN_COURS
    with tempfile.TemporaryDirectory(prefix=TEMPORAIRE) as tmp, zipfile.ZipFile(chemin) as z:
        noms = set(z.namelist())
        try:
            _extraire_fichiers(z, racine)  # rien n'est encore changé si cela échoue (disque plein…)
            if nom_dans(noms, BASE_SQLITE):
                if ESP.connexion().vendor != "sqlite":
                    raise ErreurSauvegarde(libelle("admin.sauvegarde.sqlite_vers_postgres"))
                z.extract(nom_dans(noms, BASE_SQLITE), tmp)
                _controler_base_extraite(Path(tmp) / nom_dans(noms, BASE_SQLITE), d)
            else:
                if paires_actuelles(d["migrations"]) == migrations_comparables():
                    reconstruire = False  # même structure : chargement ordinaire
                elif not (reconstruire and reconstruction_possible(d)):
                    raise ErreurSauvegarde(libelle("admin.sauvegarde.autre_version_postgres", version=d.get("version")))
                z.extract(nom_dans(noms, BASE_JSON), tmp)
        except BaseException as e:
            shutil.rmtree(racine / NOUVEAUX, ignore_errors=True)
            if isinstance(e, OSError) and getattr(e, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
                raise ErreurSauvegarde(libelle("admin.sauvegarde.disque_plein_restauration",
                                               libre=taille_lisible(_place_libre(racine)))) from e
            raise
        _ecrire_atomique(repere, json.dumps({
            "archive": str(chemin.resolve()), "avant": avant.nom if avant else "", "par": par or "", "origine": origine,
            "autre_espace": bool(autre_espace), "reconstruire": bool(reconstruire), "date": timezone.localtime().isoformat(),
            "pid": os.getpid()}))
        try:  # remplacement de la base en une étape : en cas d'échec, elle est telle qu'avant (rien à reprendre)
            if nom_dans(noms, BASE_SQLITE):
                source_db = Path(tmp) / nom_dans(noms, BASE_SQLITE)
                if lisible:
                    source = sqlite3.connect(source_db)
                    try:
                        ESP.connexion().ensure_connection()
                        source.backup(ESP.connexion().connection)  # une seule étape : tout ou rien
                    finally:
                        source.close()
                else:
                    _remplacer_fichier_base(source_db)
            elif reconstruire:
                _reconstruire_et_charger(Path(tmp) / nom_dans(noms, BASE_JSON), d)
            else:
                alias = ESP.alias_courant()
                # tout ou rien : un contenu refusé par loaddata (lien cassé, donnée invalide) laisse la base telle
                # qu'elle était, au lieu d'une base vidée sans aucun compte pour se reconnecter
                with transaction.atomic(using=alias):
                    call_command("flush", interactive=False, verbosity=0, database=alias)
                    call_command("loaddata", str(Path(tmp) / nom_dans(noms, BASE_JSON)), verbosity=0, database=alias)
                    # tables vidées par TRUNCATE, sans statistiques : ANALYZE après la validation (PostgreSQL ; test :
                    # parametres/test_statistiques_a_jour_restaurer_postgresql.py)
                    statistiques_a_jour(alias)
        except Exception:
            shutil.rmtree(racine / NOUVEAUX, ignore_errors=True)
            repere.unlink(missing_ok=True)
            raise
        # la base est remplacée : à partir d'ici, une interruption est terminée au démarrage suivant (repère gardé)
        if nom_dans(noms, BASE_SQLITE):
            ESP.connexion().close()
            call_command("migrate", interactive=False, verbosity=0, database=ESP.connexion().alias)
            harmoniser(ESP.connexion(), autres_bases(ESP.connexion().alias))  # migration renommée (version d'avant)
        _echanger_fichiers(racine)
    retirer_jetons_mcp(jetons_avant)
    _apres_restauration(d, autre_espace)
    d["comptes_sans_mot_de_passe"] = comptes_sans_mot_de_passe()
    if d["comptes_sans_mot_de_passe"]:
        journal.warning("Restore: %s account(s) without a password (backups hold no password and the shared registry "
                        "does not know them): restore the shared registry, or give new passwords",
                        d["comptes_sans_mot_de_passe"])
    _expirer_exports_absents()
    noter_base_abimee("")
    _noter_restauration(chemin, d, avant, par, origine)
    repere.unlink(missing_ok=True)
    journal.info("Restore of %s (version %s, %s)%s%s", chemin.name, d.get("version"), d.get("date"),
                 f"; previous state kept in {avant.nom}" if avant else "",
                 " (interrupted restore finished)" if _reprise is not None else "")
    return d


def reprendre_restauration():
    """Démarrage : termine une restauration interrompue de l'espace courant (repère « restauration en cours ») en la
    refaisant depuis son archive. Renvoie None (rien à faire), ou (archive, erreur) ; erreur vide si c'est terminé."""
    e = restauration_en_cours()
    if e is None:
        return None
    chemin = Path(e.get("archive", ""))
    if not chemin.is_file():
        chemin = dossier() / chemin.name
    try:
        if not chemin.is_file():
            raise ErreurSauvegarde(libelle("admin.sauvegarde.introuvable", nom=chemin.name))
        restaurer(chemin, par=e.get("par", ""), origine=e.get("origine", "commande"),
                  autre_espace=e.get("autre_espace", False), _reprise=e, reconstruire=e.get("reconstruire", False))
    except Exception as x:  # signalé (démarrage, /sante/) ; le repère reste : l'IT décide
        journal.exception("Interrupted restore of %s could not be finished", chemin.name)
        return chemin.name, str(x) or type(x).__name__
    return chemin.name, ""


def _ecrire_atomique(f, texte):
    f = Path(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.{os.getpid()}.partiel")
    with open(tmp, "w", encoding="utf-8") as x:
        x.write(texte)
        x.flush()
        os.fsync(x.fileno())
    os.replace(tmp, f)


def _remplacer_fichier_base(source_db):
    """Mode secours (base illisible) : le fichier abîmé est gardé à côté (« .damaged-<date> », avec son -wal et son
    -shm), puis remplacé par celui de l'archive."""
    from django.db import connections

    connections.close_all()
    nom = Path(str(ESP.connexion().settings_dict["NAME"]))
    marque = f".damaged-{timezone.localtime():%Y%m%d-%H%M%S}"
    tmp = nom.with_name(f".{nom.name}.restore.partiel")
    try:
        shutil.copyfile(source_db, tmp)  # d'abord la copie (disque plein : rien n'a bougé)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    for suffixe in ("", "-wal", "-shm", "-journal"):
        f = Path(str(nom) + suffixe)
        if f.exists():
            os.replace(f, Path(str(nom) + marque + suffixe))
    os.replace(tmp, nom)
    journal.warning("Damaged database %s kept as %s; replaced by the one of the archive", nom.name, nom.name + marque)


def _expirer_exports_absents():
    """Gros exports « prêts » de la base restaurée dont le fichier n'est plus là (``EXPORTS`` n'est jamais sauvegardé) :
    « expirés », avec le motif que la page donne au clic. Un échec ne fait pas échouer la restauration."""
    try:
        from collecte.exports_arriere_plan import expirer_fichiers_absents

        n = expirer_fichiers_absents()
    except Exception:  # noqa: BLE001 - la base est restaurée : le reste est du ménage
        journal.warning("After the restore: background exports not checked", exc_info=True)
        return
    if n:
        journal.info("After the restore: %s background export(s) whose file is no longer there marked as expired", n)


def _apres_restauration(d, autre_espace):
    """Marque de la base remise à cet espace (archive d'un autre espace forcée par l'IT), puis registre des comptes remis
    d'accord avec la base restaurée (le registre n'est jamais restauré avec un espace)."""
    from django.db import connections

    from espaces import comptes as EC
    from espaces.models import Espace, MarqueEspace

    if Espace._meta.db_table not in connections[ESP.COMMUN].introspection.table_names():
        # installation neuve (registre pas encore créé) : registre créé d'après la base restaurée
        call_command("migrate", database=ESP.COMMUN, interactive=False, verbosity=0)
        harmoniser(connections[ESP.COMMUN], autres_bases(ESP.COMMUN))  # migration renommée (version d'avant)
        if ESP.est_principal():
            EC.amorcer()
            return
    if autre_espace and _identifiant_installation():
        MarqueEspace.objects.all().delete()
        MarqueEspace.objects.create(code=ESP.code_courant(), installation=_identifiant_installation())
    EC.reconcilier([ESP.code_courant()])


def _extraire_fichiers(z, racine):
    """Fichiers déposés de l'archive extraits dans ``racine/.restore-new`` (rien d'autre n'est touché)."""
    racine = Path(racine)
    proteges = _proteges(racine)
    base = racine.resolve()
    nouveaux = racine / NOUVEAUX
    shutil.rmtree(nouveaux, ignore_errors=True)
    nouveaux.mkdir(parents=True)
    for info in z.infolist():
        prefixe = next((x for x in (FICHIERS_ARCHIVE, ANCIENS[FICHIERS_ARCHIVE]) if info.filename.startswith(x)), None)
        if prefixe is None or info.is_dir():
            continue
        rel = info.filename[len(prefixe):]
        cible = (racine / rel).resolve()
        if base not in cible.parents:  # chemin « ../ » ou absolu : ignoré
            continue
        if any(p == cible or p in cible.parents for p in proteges):  # jamais écrit dans un autre espace ni une base
            continue
        if cible.relative_to(base).parts[0] in EXCLUS:
            continue
        dest = nouveaux / cible.relative_to(base)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)


def _restaurer_fichiers(z):
    """Fichiers déposés de l'archive ``z`` mis à la place de ceux de l'espace courant (extraction à part, puis échange)."""
    racine = ESP.dossier_medias()
    racine.mkdir(parents=True, exist_ok=True)
    _extraire_fichiers(z, racine)
    _echanger_fichiers(racine)


def _echanger_fichiers(racine):
    """Les fichiers actuels passent dans ``.restore-old``, ceux de l'archive (``.restore-new``) prennent leur place,
    puis ``.restore-old`` est effacé. Renommages seulement (même disque) : rapide, sans copie."""
    racine = Path(racine)
    proteges = _proteges(racine)
    nouveaux, anciens = racine / NOUVEAUX, racine / ANCIENS_FICHIERS
    anciens.mkdir(exist_ok=True)
    gardes = set()
    for entree in list(racine.iterdir()):
        if entree.name in EXCLUS or _touche_un_protege(entree, proteges):
            continue  # autres espaces, sauvegardes, bases : gardés
        if entree.is_dir() and any(_touche_un_protege(p, proteges) for p in entree.rglob("*")):
            # dossier qui contient un chemin protégé (réglage de l'IT) : seuls ses fichiers déposés partent
            for f in [f for f in entree.rglob("*") if f.is_file() and not _touche_un_protege(f, proteges)]:
                f.unlink()
            gardes.add(entree.name)
        else:
            os.replace(entree, anciens / entree.name)
    if nouveaux.is_dir():
        for entree in list(nouveaux.iterdir()):
            cible = racine / entree.name
            if entree.name in gardes and entree.is_dir():  # fusion dans le dossier gardé
                for f in [f for f in entree.rglob("*") if f.is_file()]:
                    (cible / f.relative_to(entree)).parent.mkdir(parents=True, exist_ok=True)
                    os.replace(f, cible / f.relative_to(entree))
            else:
                os.replace(entree, cible)
    shutil.rmtree(nouveaux, ignore_errors=True)
    shutil.rmtree(anciens, ignore_errors=True)


# ---------------------------------------------------------------- planification
PAS = {"6h": datetime.timedelta(hours=6), "12h": datetime.timedelta(hours=12), "jour": datetime.timedelta(days=1),
       "semaine": datetime.timedelta(days=7)}


def prochaine(heure, maintenant=None):
    """Prochaine échéance quotidienne « HH:MM » (heure locale de l'installation)."""
    return echeance_suivante("jour", heure, None, maintenant)


def echeance_suivante(frequence, heure, derniere=None, maintenant=None):
    """Prochaine sauvegarde automatique : créneaux à ``heure`` puis tous les 6 h, 12 h, jours ou 7 jours. Après la
    dernière sauvegarde automatique s'il y en a une (une échéance manquée, serveur arrêté, est rattrapée tout de
    suite), sinon après maintenant."""
    maintenant = maintenant or timezone.localtime()
    try:
        h, m = (int(x) for x in (heure or "02:30").split(":"))
    except ValueError:
        h, m = 2, 30
    pas = PAS.get(frequence, PAS["jour"])
    # comparées en temps universel : deux heures locales du même fuseau se comparent sans leur décalage, et la nuit où
    # l'heure recule, la sauvegarde de 02:30 (heure d'été) passait pour « dans le futur » à 02:05 (heure d'hiver)
    utc = datetime.timezone.utc
    if derniere and derniere.astimezone(utc) > maintenant.astimezone(utc) + datetime.timedelta(minutes=5):
        derniere = None  # dernière sauvegarde datée dans le futur (horloge remise en arrière) : on repart de maintenant
    reference = timezone.localtime(derniere) if derniere else timezone.localtime(maintenant)
    ancre = reference.replace(hour=h, minute=m, second=0, microsecond=0)  # le jour de la référence : semaines stables
    k = (reference - ancre) // pas + 1
    return ancre + k * pas


def derniere_auto():
    a = next((a for a in archives() if a.motif == "auto"), None)
    return a.date if a else None


def etat_automatique(instance=None, maintenant=None):
    """Pour la page Hébergement : {active, derniere, prochaine, en_retard}."""
    from .models import Instance

    i = instance or Instance.courante()
    maintenant = maintenant or timezone.localtime()
    try:
        derniere = derniere_auto()
    except OSError:
        derniere = None
    prochaine_ = echeance_suivante(i.sauvegarde_frequence, i.sauvegarde_heure, derniere, maintenant)
    return {"active": i.sauvegarde_auto, "derniere": derniere, "prochaine": prochaine_,
            "en_retard": bool(i.sauvegarde_auto and derniere and prochaine_ < maintenant - datetime.timedelta(hours=1))}


def planifier(heure=None):
    """Boucle sans fin (image Docker, worker) : vérifie chaque minute les réglages de l'outil (Paramètres ›
    Hébergement : activée, fréquence, heure, nombre gardé) et sauvegarde à l'échéance, puis rotation. ``heure`` force
    l'heure de départ (option --heure)."""
    from .models import Instance

    from django.db import connections

    journal.info("Backup scheduler started (settings read from the tool), archives in %s", dossier())
    # sans archive « auto » (installation neuve), l'échéance part d'un départ fixe : calculée depuis « maintenant » à
    # chaque tour, elle restait toujours dans le futur et la première sauvegarde ne partait jamais. Un départ par
    # espace, noté la première fois que le planificateur le voit actif sans archive « auto » (pas au démarrage du
    # planificateur : un espace créé, ou une sauvegarde activée, des jours après partait tout de suite) ; oublié quand
    # la sauvegarde automatique est éteinte (la rallumer repart de ce moment-là)
    departs = {}

    def sauvegarder_si_echeance():  # chaque espace avec ses propres réglages (Paramètres › Hébergement de cet espace)
        if restauration_abandonnee():  # processus du serveur tué pendant une restauration : terminée ici
            journal.warning("Restore interrupted (server process stopped): finishing it")
            reprendre_restauration()
        if not base_vide():
            i = Instance.courante()
            code = ESP.code_courant()
            if not i.sauvegarde_auto:
                departs.pop(code, None)
                return
            reference = derniere_auto() or departs.setdefault(code, timezone.localtime())
            if echeance_suivante(i.sauvegarde_frequence, heure or i.sauvegarde_heure, reference) <= timezone.localtime():
                creer("auto")
                tourner(i.sauvegarde_conserver)

    while True:
        # un échec : la boucle continue, on réessaiera à la prochaine vérification (dans 10 minutes)
        pause = 60 if ESP.pour_chaque_espace(sauvegarder_si_echeance, journal, "Automatic backup failed (space \"%s\")") else 600
        try:
            registre_du_jour()
        except Exception:
            journal.exception("Backup of the shared registry failed")
        connections.close_all()
        time.sleep(pause)


# ---------------------------------------------------------------- registre commun (comptes, espaces)
NOM_REGISTRE = re.compile(r"^(registry|registre)-\d{8}-\d{6}(-[a-z0-9-]+)?\.zip$")  # « registre- » : avant la mise à jour
MODELES_REGISTRE = ["espaces.installation", "espaces.espace", "espaces.compte", "espaces.accesespace"]  # sans les sessions


def archives_registre():
    d = ESP.dossier_sauvegardes_commun()
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if NOM_REGISTRE.match(p.name) and p.is_file()), key=lambda p: (_horodatage(p.name), p.name), reverse=True)


def creer_registre(motif=""):
    """Archive du registre commun (installation, espaces, comptes, accès ; pas les sessions) dans backups/shared."""
    motif = (motif or "").strip().lower()
    if not MOTIF.match(motif):
        raise ErreurSauvegarde(libelle("admin.sauvegarde.motif"))
    d = ESP.dossier_sauvegardes_commun()
    d.mkdir(parents=True, exist_ok=True)
    maintenant = timezone.localtime()
    nom = f"registry-{maintenant:%Y%m%d-%H%M%S}{'-' + motif if motif else ''}.zip"
    while (d / nom).exists():
        time.sleep(1)
        maintenant = timezone.localtime()
        nom = f"registry-{maintenant:%Y%m%d-%H%M%S}{'-' + motif if motif else ''}.zip"
    partiel = d / f".{nom}.partiel"
    try:
        with zipfile.ZipFile(partiel, "w", zipfile.ZIP_DEFLATED) as z:
            objets = (o for label in MODELES_REGISTRE for o in apps.get_model(label)._base_manager.order_by("pk"))
            z.writestr("registry.json", serializers.serialize("json", objets, cls=EncodeurExact))
            z.writestr(DESCRIPTIF, json.dumps({"format": FORMAT, "outil": OUTIL, "contenu": "registre",
                                                      "version": settings.VERSION, "date": maintenant.isoformat(),
                                                      "identifiant_installation": _identifiant_installation()}, indent=1))
        os.replace(partiel, d / nom)
    finally:
        if partiel.exists():
            partiel.unlink()
    for ancienne in archives_registre()[max(settings.SAUVEGARDE_CONSERVER, 1):]:
        ancienne.unlink()
    return d / nom


def registre_du_jour():
    """Planificateur : une archive du registre par jour."""
    if not any(_horodatage(p.name).startswith(f"{timezone.localtime():%Y%m%d}") for p in archives_registre()):
        creer_registre("auto")


def restaurer_registre(chemin):
    """IT seulement (``restauration --commun``) : remplace le registre commun par celui de l'archive (les sessions sont
    vidées : chacun se reconnecte), puis le remet d'accord avec les espaces."""
    from django.db import connections

    from espaces import comptes as EC

    try:
        with zipfile.ZipFile(chemin) as z:
            noms = set(z.namelist())
            d = json.loads(z.read(nom_dans(noms, DESCRIPTIF) or DESCRIPTIF))
            contenu = z.read(nom_dans(noms, "registry.json") or "registry.json")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        raise ErreurSauvegarde(f"This file is not a backup of the registry ({e}).") from e
    if d.get("contenu") != "registre":
        raise ErreurSauvegarde("This file is not a backup of the shared registry.")
    with ESP.toutes_les_bases():
        creer_registre("before-restore")
        from django.db import transaction

        with transaction.atomic(using=ESP.COMMUN):  # vidage et rechargement ensemble : jamais un registre vide
            call_command("flush", database=ESP.COMMUN, interactive=False, verbosity=0)
            for o in serializers.deserialize("json", contenu, using=ESP.COMMUN):
                o.save(using=ESP.COMMUN)
            # PostgreSQL : lignes rechargées avec leur numéro, séquences remises au-dessus (sinon la création suivante
            # d'un espace ou d'un accès reprenait un numéro déjà pris : IntegrityError)
            from django.core.management.color import no_style

            c = connections[ESP.COMMUN]
            with c.cursor() as cur:
                for sql in c.ops.sequence_reset_sql(no_style(), [apps.get_model(m) for m in MODELES_REGISTRE]):
                    cur.execute(sql)
        connections[ESP.COMMUN].close()
    EC.reconcilier()
    return d


def taille_lisible(octets):
    from parametres.libelles import libelle

    for unite in ("o", "ko", "mo", "go"):  # unités dans la langue de l'interface (o / Ko… en français, B / KB… sinon)
        if octets < 1024 or unite == "go":
            nom = libelle(f"admin.taille.{unite}")
            from collecte.templatetags.collecte import separateurs

            return f"{octets:.0f} {nom}" if unite == "o" else f"{octets:.1f}".replace(".", separateurs()[1]) + f" {nom}"
        octets /= 1024
