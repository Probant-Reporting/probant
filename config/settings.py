"""Réglages de l'outil de collecte.

Toutes les valeurs sensibles ou propres à l'hébergement viennent de variables d'environnement (voir .env.example et
docs/installation.md). Sans variable : réglages de production (DEBUG désactivé), base SQLite et clé secrète générée dans
le dossier des données ; DJANGO_DEBUG=1 pour le développement.
"""
import os
import sys
import warnings
import zoneinfo
from pathlib import Path

from django.conf.locale import LANG_INFO
from django.core.exceptions import ImproperlyConfigured

from config import autorites_certificats as AUTORITES

BASE_DIR = Path(__file__).resolve().parent.parent

# Droits des fichiers : tout ce que l'outil et ses commandes créent (bases, archives,
# exports, preuves, journaux des restaurations et des contrôles, dossiers) n'est lisible que par l'utilisateur de l'outil
# (fichiers 0600, dossiers 0700), quel que soit le masque du processus qui le lance (« docker compose exec … backup »
# créait des archives en 0666). Posé ici, avant toute écriture : serveur (gunicorn, runserver), manage.py, tâches
# planifiées et tests. Les fichiers créés par une version antérieure sont resserrés au démarrage
# (``parametres.droits_fichiers``). Les fichiers statiques de l'image restent lisibles (Dockerfile : chmod a+rX).
if os.name == "posix":
    os.umask(0o077)


# Variables d'environnement : noms anglais (installations à l'étranger) ; l'ancien nom français reste accepté.
ANCIENS_NOMS = {
    "DATA_DIR": "DOSSIER_DONNEES", "BACKUPS_DIR": "SAUVEGARDES_DIR", "BACKUPS_KEEP": "SAUVEGARDE_CONSERVER",
    "BACKUP_TIME": "SAUVEGARDE_HEURE", "BACKUP_AUTO": "SAUVEGARDE_AUTO", "SPACES_DIR": "ESPACES_DOSSIER",
    "SPACES_CONN_MAX_AGE": "ESPACES_CONN_MAX_AGE", "SPACE": "ESPACE", "SQLITE_FILE": "SQLITE_FICHIER", "DOMAIN": "DOMAINE",
    "PUBLIC_URL": "URL_PUBLIQUE", "REMINDER_TIME": "RELANCE_HEURE", "SMTP_HOST": "SMTP_HOTE", "SMTP_USER": "SMTP_UTILISATEUR",
    "SMTP_PASSWORD": "SMTP_MOT_DE_PASSE", "SMTP_SECURITY": "SMTP_SECURITE", "SMTP_FROM": "SMTP_EXPEDITEUR",
    "MAX_EVIDENCE_SIZE_MB": "TAILLE_MAX_PREUVE_MO", "MAX_IMPORT_SIZE_MB": "TAILLE_MAX_IMPORT_MO",
    "DJANGO_HSTS_SECONDS": "DJANGO_HSTS_SECONDES", "DJANGO_HSTS_SUBDOMAINS": "DJANGO_HSTS_SOUS_DOMAINES",
    "DJANGO_LOG_LEVEL": "DJANGO_JOURNAL_NIVEAU", "DATA_CHECK_TIME": "CONTROLE_HEURE",
}


def env(name, default=None):
    """Variable d'environnement (nom anglais, sinon son ancien nom français) ; vide (« SMTP_PORT= ») = valeur par défaut."""
    for n in (name, ANCIENS_NOMS.get(name)):
        valeur = os.environ.get(n, "").strip() if n else ""
        if valeur:
            return valeur
    return default


# Dossier des données de l'installation : bases SQLite, fichiers déposés (preuves, logo), sauvegardes, clé secrète.
# Rangement détaillé : parametres/rangement.py et docs/file_layout.md. Dans l'image Docker : /data (un seul volume). Sur
# un poste de développement ou un Codespace : « local-data », à part du code (jamais versionné). Chemin relatif : sous le
# dossier du projet (ex. « data » chez un hébergeur clé en main).
DONNEES_LOCALES = "local-data"
# avant la mise à jour, en développement, les données étaient à la racine du projet, mêlées au code ; puis dans « donnees-locales » : déplacées une fois
ANCIENNES_DONNEES_LOCALES = ("db.sqlite3", "commun.sqlite3", "acme.sqlite3", "acme-commun.sqlite3", "vide.sqlite3",
                             "vide-commun.sqlite3", ".cle_secrete", "media", "sauvegardes", "espaces-donnees",
                             "acme-espaces-donnees", "vide-espaces-donnees")
# noms français du dossier des données (avant la mise à jour) → noms anglais, renommés une fois au lancement
ANCIENS_DOSSIERS = [("media", "files"), ("fichiers", "files"), ("sauvegardes", "backups"), (".cle_secrete", ".secret_key")]


def _renommer(ancien, nouveau):
    """Renomme ``ancien`` en ``nouveau`` s'il existe et que la place est libre (sans rien écraser)."""
    if ancien.exists() and not nouveau.exists():
        try:
            nouveau.parent.mkdir(parents=True, exist_ok=True)
            ancien.rename(nouveau)
        except OSError:
            pass


def _ranger_donnees_locales(projet, dossier):
    """Déplace dans ``dossier`` les données de développement restées à la racine du projet ou dans « donnees-locales »
    (bases, fichiers, sauvegardes), sans rien écraser."""
    _renommer(projet / "donnees-locales", dossier)
    for nom in ANCIENNES_DONNEES_LOCALES:
        for suffixe in (("", "-wal", "-shm", "-journal") if nom.endswith(".sqlite3") else ("",)):
            _renommer(projet / (nom + suffixe), dossier / (nom + suffixe))


def _noms_anglais(dossier):
    """Dossier des données aux noms français (avant la mise à jour) : renommé en anglais, sans rien écraser. Les bases et
    les fichiers des espaces sont renommés plus loin, une fois connus leurs préfixes ; les sous-dossiers des fichiers
    déposés par parametres/rangement.py (démarrage, migration collecte/0030)."""
    for ancien, nouveau in ANCIENS_DOSSIERS:
        if (nouveau == "files" and env("MEDIA_ROOT")) or (nouveau == "backups" and env("BACKUPS_DIR")):
            continue  # dossier choisi par l'IT : laissé où il est
        _renommer(dossier / ancien, dossier / nouveau)
    sauvegardes = dossier / "backups"
    for ancien, nouveau in (("commun", "shared"), ("espaces", "spaces"), ("restaurations.jsonl", "restores.jsonl")):
        _renommer(sauvegardes / ancien, sauvegardes / nouveau)
    try:
        (dossier / "LISEZ-MOI.txt").unlink(missing_ok=True)  # remplacé par README.txt (écrit au démarrage)
    except OSError:
        pass  # dossier en lecture seule : expliqué par le démarrage et /sante/, pas ici


_ESSAIS = "test" in sys.argv[1:2]
if env("DATA_DIR") is None and _ESSAIS:
    # Tests sans DATA_DIR : dossier temporaire propre à l'exécution, jamais « local-data » (ni lu ni écrit) ; supprimé à la fin.
    import atexit
    import shutil
    import tempfile

    DOSSIER_DONNEES = Path(tempfile.mkdtemp(prefix="kpi-tests-"))
    atexit.register(shutil.rmtree, DOSSIER_DONNEES, ignore_errors=True)
elif env("DATA_DIR") is None:
    DOSSIER_DONNEES = BASE_DIR / DONNEES_LOCALES
    _ranger_donnees_locales(BASE_DIR, DOSSIER_DONNEES)
    DOSSIER_DONNEES.mkdir(exist_ok=True)
else:
    DOSSIER_DONNEES = BASE_DIR / env("DATA_DIR")
if DOSSIER_DONNEES.is_dir():
    _noms_anglais(DOSSIER_DONNEES)
    # Autorités de certification ajoutées par l'IT (EXTRA_CA_CERTS, réseau d'entreprise) : réunies avec celles du
    # système et données à tous les appels sortants par SSL_CERT_FILE (config/autorites_certificats.py). Dans l'image,
    # docker/entrypoint.sh l'a déjà fait une fois pour tous les processus : rien n'est refait ici.
    AUTORITES.appliquer(os.environ, DOSSIER_DONNEES)
AUTORITES_AJOUTEES = os.environ.get(AUTORITES.VARIABLE, "").strip()
# pour Paramètres › Santé (aucune application n'importe config) : autorités lues une fois par processus, et fichier
# réuni en service ou non dans ce processus
AUTORITES_BILAN = AUTORITES.lire(AUTORITES_AJOUTEES)
AUTORITES_EN_SERVICE = AUTORITES.en_service() is not None
VERSION = (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip() if (BASE_DIR / "VERSION").exists() else "dev"
VERSION_COMMIT = env("VERSION_COMMIT", "")

DEBUG = env("DJANGO_DEBUG", "0") == "1"
# version tout-en-un (portable/launch.py la pose) : mode développement pour le serveur local (HTTP, fichiers statiques),
# mais sa propre clé secrète, gardée dans son dossier des données sous un autre nom que celle d'un serveur : un dossier
# « data » recopié sur un serveur (docs/from_pc_to_server.md) n'y apporte pas la clé du PC, le serveur crée la sienne
TOUT_EN_UN = env("PROBANT_ALL_IN_ONE", "0") == "1"
CLE_DEVELOPPEMENT = "dev-only-change-me"  # connue de tous : jamais pour des données réelles
FICHIER_CLE = ".secret_key_all_in_one" if TOUT_EN_UN else ".secret_key"


def _cle_secrete():
    """DJANGO_SECRET_KEY si fournie ; sinon une clé générée une fois et gardée dans le dossier des données (les sessions
    survivent aux redémarrages et aux mises à jour) ; en développement, une clé fixe suffit (pas pour la version
    tout-en-un, qui garde de vraies données : sa clé à elle, ``FICHIER_CLE``).

    Le fichier est écrit à part puis mis en place d'un coup (jamais de fichier vide ou à moitié écrit après un arrêt
    brutal) ; un fichier vide (ancienne version interrompue) est remplacé. Fichier perdu : une nouvelle
    clé, chacun se reconnecte (rien d'autre n'en dépend)."""
    if env("DJANGO_SECRET_KEY"):
        return env("DJANGO_SECRET_KEY")
    if DEBUG and not TOUT_EN_UN:
        return CLE_DEVELOPPEMENT
    fichier = DOSSIER_DONNEES / FICHIER_CLE
    try:
        cle = fichier.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        cle = ""
    except (OSError, UnicodeDecodeError) as e:
        raise ImproperlyConfigured(f"The secret key file {fichier} cannot be read ({e}): check the owner and rights "
                                   "of the data folder (docs/installation.md, \"Troubleshooting\").") from e
    if cle:
        return cle
    from django.core.management.utils import get_random_secret_key

    nouvelle = get_random_secret_key() + get_random_secret_key()
    tmp = DOSSIER_DONNEES / f"{FICHIER_CLE}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(nouvelle)
            f.flush()
            os.fsync(f.fileno())
        if fichier.exists():  # fichier vide : remplacé
            os.replace(tmp, fichier)
        else:
            try:
                os.link(tmp, fichier)  # n'écrase pas une clé créée au même moment par un autre processus
            except FileExistsError:
                return fichier.read_text(encoding="ascii").strip()
            except OSError:
                os.replace(tmp, fichier)  # système de fichiers sans liens
    except OSError as e:
        if not DOSSIER_DONNEES.exists():
            raise ImproperlyConfigured(f"The data folder {DOSSIER_DONNEES} does not exist: create it, or set DATA_DIR "
                                       "to an existing folder (docs/installation.md, \"Troubleshooting\").") from e
        raise ImproperlyConfigured(f"The secret key file {fichier} cannot be created ({e}): the data folder must be "
                                   "writable by the tool (docs/installation.md, \"Troubleshooting\").") from e
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    print(f"New secret key created in {fichier}: "
          "everyone will have to sign in again.", file=sys.stderr)
    return nouvelle


SECRET_KEY = _cle_secrete()

# Domaine : DOMAINE=reporting.example.com (plusieurs : séparés par des virgules). localhost reste permis (page de santé).
DOMAINES = [d.strip() for d in env("DOMAIN", "").split(",") if d.strip()]
HTTPS = env("DJANGO_HTTPS", "0") == "1"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "").split(",") if h] or list(dict.fromkeys(DOMAINES + ["localhost", "127.0.0.1"]))
CSRF_FAILURE_VIEW = "collecte.reponses_script.echec_csrf"  # jeton périmé : page de l'outil, jamais la page technique de Django
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o] or [
    f"{'https' if HTTPS else 'http'}://{d}" for d in DOMAINES]
if DEBUG:  # essai sur le poste ou dans un Codespace ouvert depuis VS Code : https://localhost:8000 (port redirigé)
    CSRF_TRUSTED_ORIGINS += [f"{p}://{h}:8000" for p in ("http", "https") for h in ("localhost", "127.0.0.1")]
# Adresse de l'outil dans les e-mails envoyés sans page ouverte (relances automatiques)
URL_PUBLIQUE = env("PUBLIC_URL") or (f"{'https' if HTTPS else 'http'}://{DOMAINES[0]}" if DOMAINES else "")
RELANCE_HEURE = env("REMINDER_TIME", "09:00")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "parametres",
    "referentiel",
    "collecte",
    "espaces",  # plusieurs espaces dans une installation (docs/spaces.md) ; sa commande migrate migre toutes les bases
    "serveur_mcp",  # assistants (MCP) : lire et agir avec les droits de la personne, jeton personnel (docs/mcp.md)
    "connexion_entreprise",  # connexion par le compte d'entreprise (OpenID Connect), éteinte par défaut (docs/single_sign_on.md)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "collecte.politique_contenus.PolitiqueContenusMiddleware",  # Content-Security-Policy de chaque page, jeton par requête
    "parametres.cache_statique.CacheStatiqueVersionneMiddleware",  # cache long des fichiers statiques dont l'adresse porte ?v= (avant WhiteNoise)
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",  # pages ~200 Ko (styles et scripts intégrés) ; protégé contre BREACH
    "espaces.intergiciels.EspaceMiddleware",  # /espace/<code>/… : base, fichiers et liens de cet espace
    "django.contrib.sessions.middleware.SessionMiddleware",
    "espaces.session.SessionEspaceMiddleware",  # clés de session de l'outil propres à chaque espace
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "collecte.garde_requetes.GardeRequetesMiddleware",  # envoi trop gros sans connexion, octet NUL : refus clair
    "parametres.langues.LangueMiddleware",  # avant la page « pas d'accès » : elle s'affiche dans la langue choisie
    "parametres.pannes.PanneStockageMiddleware",  # disque plein, lecture seule : page claire (503), rien d'enregistré
    "espaces.intergiciels.AccesEspaceMiddleware",  # personne connectée sans accès à cet espace : page « pas d'accès »
    "collecte.reponses_script.SessionExpireeMiddleware",  # envoi du script sans session : 401 lisible, pas la page de connexion
    "django.contrib.messages.middleware.MessageMiddleware",
    "connexion_entreprise.intergiciels.SessionSelonLaRegleMiddleware",  # session par mot de passe refusée si la règle a changé
    "parametres.mise_en_place.MiseEnPlaceMiddleware",
    "collecte.compte.MotDePasseProvisoireMiddleware",
    "collecte.lecture_seule.LectureSeuleMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "parametres.contexte.instance",
                "parametres.mise_en_place.contexte",
                "collecte.contexte.choix_reponse",
                "collecte.aide.contexte",  # lien « Aide » de la barre du haut
                "collecte.visite_guidee.contexte",  # visite guidée de la première connexion
                "espaces.contexte_gabarits.espaces",  # sélecteur « Espace » de la barre du haut
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"



def _base():
    """SQLite par défaut (aucun serveur à gérer) ; PostgreSQL par une seule variable :
    DATABASE_URL=postgres://utilisateur:motdepasse@serveur:5432/base (ou les variables POSTGRES_*)."""
    from urllib.parse import unquote, urlparse

    url = env("DATABASE_URL") or env("POSTGRESQL_ADDON_URI", "")  # POSTGRESQL_ADDON_URI : add-on Clever Cloud
    if url.startswith(("postgres://", "postgresql://")):
        u = urlparse(url)
        return {"ENGINE": "django.db.backends.postgresql", "NAME": unquote(u.path.lstrip("/")), "USER": unquote(u.username or ""),
                "PASSWORD": unquote(u.password or ""), "HOST": u.hostname or "", "PORT": str(u.port or 5432), "CONN_MAX_AGE": 60}
    if env("POSTGRES_DB"):
        return {"ENGINE": "django.db.backends.postgresql", "NAME": env("POSTGRES_DB"), "USER": env("POSTGRES_USER", "probant"),
                "PASSWORD": env("POSTGRES_PASSWORD", ""), "HOST": env("POSTGRES_HOST", "db"), "PORT": env("POSTGRES_PORT", "5432"),
                "CONN_MAX_AGE": 60}
    # SQLITE_FILE : une autre base locale, ex. vide.sqlite3 pour une installation vierge à côté de la démo Exemplia.
    # WAL et transactions « immediate » : plusieurs processus du serveur écrivent sans « database is locked ».
    # timeout : attente du verrou d'écriture (une écriture à la fois) ; 60 s plutôt que 20 : en pleine campagne, un
    # serveur très chargé faisait attendre certains enregistrements plus de 20 s, refusés alors par une erreur
    # (essai de charge) ; mieux vaut attendre (les requêtes durent jusqu'à 120 s).
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": DOSSIER_DONNEES / env("SQLITE_FILE", "db.sqlite3"),
            "OPTIONS": {"timeout": 60, "transaction_mode": "IMMEDIATE",
                        "init_command": "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL"}}


DATABASES = {"default": _base()}

# Espaces (docs/spaces.md) : un registre commun (comptes, liste des espaces, sessions), un fichier SQLite à côté de la
# base principale ou un schéma « commun » de la même base PostgreSQL ; chaque espace supplémentaire a sa base
# (spaces-data/<code>/database.sqlite3, ou le schéma espace_<code>). SQLITE_FILE=vide.sqlite3 : vide-shared.sqlite3.
_PREFIXE_ESPACES = "" if env("SQLITE_FILE", "db.sqlite3") == "db.sqlite3" else Path(env("SQLITE_FILE")).stem + "-"
_renommer(DOSSIER_DONNEES / f"{_PREFIXE_ESPACES}espaces-donnees", DOSSIER_DONNEES / f"{_PREFIXE_ESPACES}spaces-data")
for _suffixe in ("", "-wal", "-shm", "-journal"):  # registre des comptes : ancien nom français
    _renommer(DOSSIER_DONNEES / f"{_PREFIXE_ESPACES}commun.sqlite3{_suffixe}", DOSSIER_DONNEES / f"{_PREFIXE_ESPACES}shared.sqlite3{_suffixe}")
ESPACES_DOSSIER = Path(env("SPACES_DIR", DOSSIER_DONNEES / f"{_PREFIXE_ESPACES}spaces-data"))
ESPACES_CONN_MAX_AGE = int(env("SPACES_CONN_MAX_AGE", "60"))
# Langue par défaut d'une nouvelle installation (interface et contenus, réglable ensuite dans Paramètres › Langues) :
# l'anglais ; DEFAULT_LANGUAGE=fr pour une installation française. Les tests, écrits en
# français, gardent le français.
LANGUE_PAR_DEFAUT = env("DEFAULT_LANGUAGE", "fr" if _ESSAIS else "en").strip().lower() or "en"
# Visite guidée de la première connexion (collecte/visite_guidee.py) : affichage seulement. GUIDED_TOUR=off la retire
# partout (captures des guides, essais) ; les tests ne l'affichent pas, sauf ceux qui la testent.
VISITE_GUIDEE = env("GUIDED_TOUR", "off" if _ESSAIS else "on").strip().lower() not in ("off", "0", "false", "no", "non")


def _alias_schema(schema, suffixe):
    b = DATABASES["default"]
    if b["ENGINE"].endswith("sqlite3"):
        nom = DOSSIER_DONNEES / f"{_PREFIXE_ESPACES}shared.sqlite3" if schema == "commun" else ":memory:"
        return {**b, "OPTIONS": dict(b.get("OPTIONS", {})), "NAME": nom, "TEST": {}}
    options = {**b.get("OPTIONS", {}), "options": f"-c search_path={schema}"}
    return {**b, "OPTIONS": options, "TEST": {"NAME": f"test_{b['NAME']}_{suffixe}"}}


DATABASES["commun"] = _alias_schema("commun", "commun")
if _ESSAIS:  # second espace des tests des espaces (espaces.essais.EspacesTestCase)
    DATABASES["espace_essai"] = _alias_schema("espace_essai", "essai")
DATABASE_ROUTERS = ["espaces.routeur.Routeur"]

AUTH_USER_MODEL = "referentiel.Utilisateur"

if _ESSAIS:  # hacheur rapide pour les tests seulement (aucun test ne dépend du format de l'empreinte)
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
# Langues de l'interface : celles qui ont des fichiers dans libelles/ (ajouter une langue = ajouter ses fichiers ; la liste
# proposée aux personnes, elle, ne garde que les langues complètes : parametres/controle_libelles.py).
_CODES_LANGUES = sorted({p.name.split(".")[-2] for p in (BASE_DIR / "libelles").glob("*.*.json")}, key=lambda c: (c != "en", c))
LANGUAGES = [(c, (LANG_INFO.get(c) or {}).get("name_local", c).capitalize()) for c in _CODES_LANGUES]
# Fuseau horaire de l'installation (nom IANA : « Europe/Paris », « America/New_York »…) : heure des relances automatiques,
# de la sauvegarde et du contrôle de nuit, « aujourd'hui », dates des exports et du journal. Une valeur inconnue arrête le
# démarrage avec un message clair (sinon les heures seraient fausses sans que personne ne le voie).
TIME_ZONE = env("TIME_ZONE", "Europe/Brussels")
try:
    zoneinfo.ZoneInfo(TIME_ZONE)
except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
    raise ImproperlyConfigured(f"TIME_ZONE={TIME_ZONE!r} is not a known time zone: use a name from the IANA list, for "
                               "example Europe/Paris or America/New_York (docs/installation.md, \"Settings\").") from e
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"  # absolu : un lien relatif prendrait le préfixe /espace/<code>/ de la première requête
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # feuille de style et polices de l'outil
# Fichiers statiques servis par WhiteNoise, avant Django (compressés, mis en cache par les navigateurs)
STORAGES = {"default": {"BACKEND": "espaces.stockage.StockageEspace"},  # dossier des fichiers de l'espace courant
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}}
WHITENOISE_USE_FINDERS = True  # sert aussi static/ sans collectstatic (essai sur un poste, mode production)
warnings.filterwarnings("ignore", message="No directory at")  # développement : pas de collectstatic
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", DOSSIER_DONNEES / "files"))  # documents déposés de l'espace principal (preuves, logo)

# Caches. Par défaut : en mémoire de chaque processus. « connexion » : compteur des essais de connexion manqués
# (referentiel/connexion.py), partagé par tous les processus du serveur (gunicorn en lance plusieurs) et gardé après un
# redémarrage : des fichiers dans le dossier des données (sign-in-attempts/), sans service ni table de plus. En mémoire,
# la limite valait 5 essais PAR processus et repartait de zéro au redémarrage. Pendant les tests : en mémoire de chaque
# processus (les tests en parallèle ne se gênent pas ; le partage par fichiers est prouvé par
# referentiel/test_connexion_partagee.py, avec ce réglage).
CACHE_CONNEXION = {
    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
    "LOCATION": str(DOSSIER_DONNEES / "sign-in-attempts"),
    "TIMEOUT": 15 * 60,
    "OPTIONS": {"MAX_ENTRIES": 20000},  # au-delà, Django efface un tiers des compteurs au hasard
}
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "connexion": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "connexion"} if _ESSAIS
    else CACHE_CONNEXION,
}
SAUVEGARDES_DIR = Path(env("BACKUPS_DIR", DOSSIER_DONNEES / "backups"))
# /sante/ signale un disque presque plein (Mo libres) : les sauvegardes, les preuves et la base n'écriraient plus
ALERTE_DISQUE_MO = int(env("DISK_ALERT_MB", "100"))
SAUVEGARDE_CONSERVER = int(env("BACKUPS_KEEP", "14"))  # archives gardées (les plus anciennes sont supprimées)
CONTROLE_HEURE = env("DATA_CHECK_TIME", "03:30")  # contrôle de cohérence de la base, chaque nuit (check_data --schedule)
SAUVEGARDE_HEURE = env("BACKUP_TIME", "02:30")  # sauvegarde automatique quotidienne (image Docker)

# Fichiers déposés : preuves (cahier des charges, section 5.4) et fichiers d'import, tailles réglables
PREUVE_EXTENSIONS = ["pdf", "jpg", "jpeg", "png"]
PREUVE_TAILLE_MAX = int(float(env("MAX_EVIDENCE_SIZE_MB", "5")) * 1024 * 1024)
IMPORT_TAILLE_MAX = int(float(env("MAX_IMPORT_SIZE_MB", "10")) * 1024 * 1024)
# Classeur Excel déposé : taille totale une fois décompressé (un .xlsx est un zip : 157 Ko peuvent cacher une cellule de
# 157 millions de caractères) ; refusé au-delà, avant d'être ouvert (collecte/fichiers.py, controler_classeur). Par
# défaut 20 fois la taille d'import (200 Mo pour 10 Mo) : un vrai classeur se décompresse 10 à 17 fois
XLSX_DECOMPRESSE_MAX = int(float(env("MAX_XLSX_UNCOMPRESSED_MB", "0")) * 1024 * 1024) or 20 * IMPORT_TAILLE_MAX
# Sauvegarde déposée depuis l'outil (Hébergement › Restaurer) par un administrateur : seule exception à la taille d'envoi
# bornée par la plus grande des deux tailles ci-dessus (collecte/garde_requetes.py) ; avec le proxy Caddy, CADDY_MAX_SIZE
# (50 Mo par défaut) s'applique aussi
SAUVEGARDE_DEPOT_MAX = int(float(env("MAX_BACKUP_UPLOAD_MB", "2048")) * 1024 * 1024)
# Import de valeurs : au-delà de ce nombre de lignes, l'import se fait en arrière-plan avec une barre d'avancement
# (collecte/imports_arriere_plan.py) ; 0 : jamais (tout import dans la requête, limitée à 120 s par gunicorn)
IMPORT_ARRIERE_PLAN_LIGNES = int(env("BACKGROUND_IMPORT_ROWS", "5000"))
# preuves, logo, imports déposés : lisibles par l'utilisateur de l'outil seul (0640 avant la mise à jour) ; leurs
# dossiers suivent le masque posé en tête (0700)
FILE_UPLOAD_PERMISSIONS = 0o600

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Connexion : comptes créés par l'administrateur, connexion par e-mail ; le compte d'entreprise (OpenID Connect) peut
# prouver qui est la personne, jamais créer un compte (connexion_entreprise/, docs/single_sign_on.md)
AUTHENTICATION_BACKENDS = ["referentiel.auth.EmailOuIdentifiant"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "collecte:accueil"
LOGOUT_REDIRECT_URL = "login"
TEST_RUNNER = "espaces.essais.Lanceur"  # chaque test ouvre aussi le registre commun

# ---------------------------------------------------------------- production
# HTTPS (derrière Caddy ou un autre proxy qui transmet X-Forwarded-Proto) : cookies sécurisés, redirection, HSTS.
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^sante/$"]  # supervision interne en HTTP
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env("DJANGO_HSTS_SUBDOMAINS", "1") == "1"
    SECURE_HSTS_PRELOAD = env("DJANGO_HSTS_PRELOAD", "0") == "1"
# L'inscription à la liste « preload » des navigateurs est un choix de l'IT pour tout le domaine (DJANGO_HSTS_PRELOAD=1).
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Politique de sécurité des contenus (collecte/politique_contenus.py) : bloquante par défaut ; « report-only » la passe en
# signalement seulement si un écran casse chez un client (docs/installation.md).
POLITIQUE_CONTENUS_MODE = env("CONTENT_SECURITY_POLICY_MODE", "enforce")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 12

# E-mails (relances, test d'envoi depuis Administration › Paramètres › Hébergement). Sans SMTP_HOTE : affichés dans le
# journal du serveur, rien n'est envoyé.
EMAIL_HOST = env("SMTP_HOST", "")
EMAIL_PORT = int(env("SMTP_PORT", "587"))
EMAIL_HOST_USER = env("SMTP_USER", "")
EMAIL_HOST_PASSWORD = env("SMTP_PASSWORD", "")
EMAIL_USE_TLS = env("SMTP_SECURITY", "starttls") == "starttls"
EMAIL_USE_SSL = env("SMTP_SECURITY", "starttls") == "ssl"
EMAIL_TIMEOUT = 20
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST else "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("SMTP_FROM", EMAIL_HOST_USER or "reporting@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = ""

# Prise IA (docs/ai_socket.md) : éteinte dans chaque espace tant qu'un administrateur ne l'allume pas avec la clé du
# client (Paramètres › Assistant IA). AI_SOCKET=off : coupée par l'IT pour toute l'installation (rien ne sort, aucun
# bouton). Clés : un fichier par espace dans ce dossier, jamais en base ni dans une sauvegarde.
IA_PRISE_PERMISE = env("AI_SOCKET", "on").strip().lower() not in ("off", "0", "no", "false")
IA_CLES_DIR = DOSSIER_DONNEES / "ai-keys"
# fournisseur factice (aucun réseau) : dans les tests, et sur un poste de développement avec AI_FAKE_PROVIDER=1 pour
# voir les écrans ; jamais proposé autrement
IA_FOURNISSEUR_FACTICE = _ESSAIS or env("AI_FAKE_PROVIDER", "0") == "1"
IA_RESEAU_INTERDIT = _ESSAIS  # aucun appel réel pendant les tests, jamais

# Connexion par le compte d'entreprise (docs/single_sign_on.md) : réglée dans l'outil (Paramètres › Connexion
# d'entreprise) par un gestionnaire des espaces, éteinte par défaut. COMPANY_SIGN_IN=off : coupée par l'IT pour toute
# l'installation (bouton retiré, mot de passe permis à tous : la porte de secours si le fournisseur est en panne).
CONNEXION_ENTREPRISE_PERMISE = env("COMPANY_SIGN_IN", "on").strip().lower() not in ("off", "0", "no", "false")
# Appels au fournisseur (connexion_entreprise/sortant.py) : délai de chaque appel, en secondes ; adresses en http et sur
# la machine elle-même (localhost) permises seulement pour les essais et le développement (DEBUG) : en production, https
CONNEXION_ENTREPRISE_DELAI = float(env("COMPANY_SIGN_IN_TIMEOUT", "5"))
CONNEXION_ENTREPRISE_LOCAL = _ESSAIS or DEBUG
# Copie externe des sauvegardes (parametres/copie_externe.py) : destination réglée dans l'outil (Paramètres › Hébergement).
# La machine elle-même (127.0.0.1, ::1) n'est une destination permise que pour les essais et le développement.
COPIE_EXTERNE_LOCAL = _ESSAIS or DEBUG

# Journaux lisibles sur la sortie standard (docker compose logs) : date, niveau, origine, message.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"lisible": {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "datefmt": "%Y-%m-%d %H:%M:%S"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "lisible"}},
    "root": {"handlers": ["console"], "level": "WARNING" if "test" in sys.argv[1:2] else env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        # erreurs serveur (500) détaillées ; les 403 / 404 sont déjà dans le journal d'accès de gunicorn
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security.DisallowedHost": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
